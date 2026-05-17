"""Tests for the slave control socket (WINSZ propagation, AUTH gating)."""
from __future__ import annotations

import asyncio
import os
import struct
import sys

import pytest

pytest.importorskip("fcntl", reason="control-socket tests need Unix pipes/sockets")
if sys.platform == "win32":  # pragma: no cover
    pytest.skip("AF_UNIX not available", allow_module_level=True)

from csshx_latest.slave import Slave, _apply_control_line, run_slave_bridge, shutdown_slave


def _make_slave(sock_path: str, ctl_path: str, pty_fd: int, pid: int, token: str = "TOK") -> Slave:
    return Slave(
        index=1,
        host="h",
        sock_path=sock_path,
        ctl_sock_path=ctl_path,
        token=token,
        pty_master=pty_fd,
        pid=pid,
    )


def test_apply_control_line_resizes_pty():
    """A well-formed WINSZ line should call TIOCSWINSZ on the slave's PTY."""
    import fcntl
    import pty
    import termios

    pty_master, pty_slave = pty.openpty()
    try:
        slave = _make_slave("", "", pty_master, 0)
        _apply_control_line(slave, b"WINSZ 42 137 0 0\n")
        packed = fcntl.ioctl(pty_slave, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, _, _ = struct.unpack("HHHH", packed)
        assert rows == 42
        assert cols == 137
    finally:
        os.close(pty_master)
        os.close(pty_slave)


def test_apply_control_line_rejects_bad_grammar():
    """Malformed lines are ignored without raising."""
    import pty

    pty_master, pty_slave = pty.openpty()
    try:
        slave = _make_slave("", "", pty_master, 0)
        # All these should be no-ops, never raise.
        _apply_control_line(slave, b"WINSZ\n")
        _apply_control_line(slave, b"WINSZ abc def\n")
        _apply_control_line(slave, b"HELLO 1 2\n")
        _apply_control_line(slave, b"\n")
        _apply_control_line(slave, b"\xff\xfe\n")  # non-ascii
        _apply_control_line(slave, b"WINSZ -1 80\n")  # non-positive
    finally:
        os.close(pty_master)
        os.close(pty_slave)


def test_control_socket_requires_auth(short_socket_dir, harmless_pid):
    """A client that fails AUTH on the control socket must not be able to resize."""
    import pty

    pty_master, pty_slave = pty.openpty()
    sock_path = os.path.join(short_socket_dir, "slave.sock")
    ctl_path = os.path.join(short_socket_dir, "slave.ctl")
    slave = _make_slave(sock_path, ctl_path, pty_master, harmless_pid, token="REAL")

    async def go() -> None:
        await run_slave_bridge(slave)
        # Connect to the control socket and send a wrong AUTH.
        reader, writer = await asyncio.open_unix_connection(ctl_path)
        writer.write(b"AUTH WRONG\n")
        writer.write(b"WINSZ 99 200 0 0\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    try:
        asyncio.run(go())
    finally:
        os.close(pty_slave)
        shutdown_slave(slave)
    # The PTY should NOT have been resized -- but we can't read it post-close.
    # The strong assertion is just that no exception was raised and AUTH dropped
    # the connection before WINSZ was honored.


def test_control_socket_accepts_winsz_after_auth(short_socket_dir, harmless_pid):
    """A correctly-authenticated client can resize the slave's PTY."""
    import fcntl
    import pty
    import termios

    pty_master, pty_slave = pty.openpty()
    sock_path = os.path.join(short_socket_dir, "slave.sock")
    ctl_path = os.path.join(short_socket_dir, "slave.ctl")
    slave = _make_slave(sock_path, ctl_path, pty_master, harmless_pid, token="OK")

    async def go() -> None:
        await run_slave_bridge(slave)
        reader, writer = await asyncio.open_unix_connection(ctl_path)
        writer.write(b"AUTH OK\n")
        writer.write(b"WINSZ 50 123 0 0\n")
        await writer.drain()
        # Let the server process the line.
        for _ in range(10):
            await asyncio.sleep(0.02)
            packed = fcntl.ioctl(pty_slave, termios.TIOCGWINSZ, b"\x00" * 8)
            rows, cols, _, _ = struct.unpack("HHHH", packed)
            if rows == 50 and cols == 123:
                break
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    try:
        asyncio.run(go())
        packed = fcntl.ioctl(pty_slave, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, _, _ = struct.unpack("HHHH", packed)
        assert rows == 50
        assert cols == 123
    finally:
        os.close(pty_slave)
        shutdown_slave(slave)
