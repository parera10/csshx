"""Tests for the fallback attach client.

Focused on the new "AUTH rejected" exit path: when the master closes
the socket before sending any data, the client should print a clear
diagnostic to stderr and exit 1 (so the user notices the problem
instead of seeing the spawned terminal block silently flash and
disappear).
"""
from __future__ import annotations

import os
import socket
import sys
import threading

import pytest

if sys.platform == "win32":  # pragma: no cover - skip path
    pytest.skip("AF_UNIX socket tests skip on Windows", allow_module_level=True)

from csshx_latest import attach


def _start_unix_server(sock_path: str, on_accept) -> tuple[socket.socket, threading.Thread]:
    """Bind a Unix socket and run ``on_accept(conn)`` in a daemon thread."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)

    def loop() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        try:
            on_accept(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return srv, t


def test_auth_rejection_returns_1_with_clear_stderr(
    short_socket_dir, stdio_devnull, capsys
):
    """Server closes immediately after reading AUTH → client must exit 1."""
    sock_path = os.path.join(short_socket_dir, "rejecting.sock")

    def reject(conn: socket.socket) -> None:
        # Drain whatever AUTH bytes the client sends so its sendall completes,
        # then close without ever writing back. This is exactly what the real
        # server does on a bad token.
        try:
            conn.recv(4096)
        except OSError:
            pass

    srv, t = _start_unix_server(sock_path, reject)
    try:
        rc = attach.main(["attach", sock_path, "BAD_TOKEN"])
    finally:
        srv.close()
        t.join(timeout=2)

    err = capsys.readouterr().err
    assert rc == 1
    assert "AUTH rejected" in err


def test_clean_eof_after_data_returns_0(short_socket_dir, stdio_devnull, capsys):
    """Server sends some bytes then closes → client exits 0 (normal disconnect)."""
    sock_path = os.path.join(short_socket_dir, "happy.sock")

    def serve(conn: socket.socket) -> None:
        try:
            conn.recv(4096)  # consume AUTH line
            conn.sendall(b"hello from master\n")
        except OSError:
            pass
        # Connection closes when this returns.

    srv, t = _start_unix_server(sock_path, serve)
    try:
        # Redirect stdout so the test doesn't pollute the pytest terminal with
        # the bytes we sent above.
        rc = attach.main(["attach", sock_path, "TOKEN"])
    finally:
        srv.close()
        t.join(timeout=2)

    err = capsys.readouterr().err
    assert rc == 0
    assert "AUTH rejected" not in err


def test_bad_argv_returns_2(capsys):
    rc = attach.main(["attach"])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_connect_failure_returns_1(short_socket_dir, capsys):
    """Connecting to a nonexistent socket prints an error and returns 1."""
    sock_path = os.path.join(short_socket_dir, "does-not-exist.sock")
    rc = attach.main(["attach", sock_path, "TOKEN"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "connect" in err
