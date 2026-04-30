"""Master: orchestrates slaves, runs the broadcast TUI, drives shutdown.

The master process is the single source of truth: it owns every PTY,
every UNIX socket, every ssh subprocess. Terminal blocks (rendered by
whichever Launcher is active) are pure renderers — they connect to a
slave's socket, send keystrokes when focused, and display whatever the
PTY emits.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from csshx_latest.auth import make_token
from csshx_latest.launcher import BlockHandle, Launcher
from csshx_latest.slave import (
    Slave,
    run_slave_bridge,
    shutdown_slave,
    spawn_slave,
    write_to_slave,
)
from csshx_latest.terminal import get_winsize, raw_mode, set_winsize


@dataclass
class Broadcaster:
    """Routes bytes to enabled slaves. Pure logic — owns no fds."""

    slaves: list[Slave] = field(default_factory=list)

    def add(self, s: Slave) -> None:
        """Register a slave with the broadcaster."""
        self.slaves.append(s)

    def enabled_indices(self) -> list[int]:
        """Indices of slaves that currently receive broadcast bytes."""
        return [s.index for s in self.slaves if s.enabled]

    def toggle(self, index: int) -> None:
        """Flip the ``enabled`` flag of the slave with the given index."""
        for s in self.slaves:
            if s.index == index:
                s.enabled = not s.enabled
                return
        raise KeyError(index)

    async def broadcast(self, data: bytes) -> None:
        """Write ``data`` to every enabled slave concurrently."""
        await asyncio.gather(
            *(write_to_slave(s, data) for s in self.slaves),
            return_exceptions=True,
        )


def make_socket_dir() -> str:
    """Create a 0700 directory for slave sockets.

    Prefers ``$XDG_RUNTIME_DIR`` when present and a directory; falls
    back to the system temp dir (``/tmp`` on macOS).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = xdg if xdg and os.path.isdir(xdg) else tempfile.gettempdir()
    path = os.path.join(base, f"csshx-{os.getpid()}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def attach_command(sock_path: str, token: str) -> list[str]:
    """Build the attach command for a terminal block.

    Prefers ``socat`` when available, wrapped in a tiny ``sh -c`` so we
    can flip the local terminal into raw mode and inject the AUTH line
    before forwarding keystrokes. Falls back to the bundled stdlib
    attach client when ``socat`` isn't on PATH.
    """
    if shutil.which("socat"):
        sh_cmd = (
            'stty raw -echo 2>/dev/null; '
            f'{{ printf \'AUTH %s\\n\' \'{token}\'; cat; }} | '
            f'socat - UNIX-CONNECT:{sock_path}; '
            'stty sane 2>/dev/null'
        )
        return ["sh", "-c", sh_cmd]
    return [sys.executable, "-m", "csshx_latest.attach", sock_path, token]


async def run_master(
    hosts: list[str],
    ssh_args: list[str],
    login: Optional[str],
    launcher: Launcher,
) -> int:
    """Top-level entry: spawn slaves, run the TUI, tear down on exit."""
    sock_dir = make_socket_dir()
    bcast = Broadcaster()
    handles: list[BlockHandle] = []

    try:
        for i, host in enumerate(hosts, start=1):
            token = make_token()
            s = await spawn_slave(i, host, sock_dir, ssh_args, login, token)
            await run_slave_bridge(s)
            bcast.add(s)
            handle = launcher.open_block(attach_command(s.sock_path, s.token), host)
            handles.append(handle)

        try:
            launcher.tile(handles)
        except Exception as exc:
            sys.stderr.write(f"warning: tile() failed: {exc}\n")

        await tui_loop(bcast)
    finally:
        for h in handles:
            try:
                launcher.close_block(h)
            except Exception:
                pass
        for s in bcast.slaves:
            shutdown_slave(s)
        try:
            os.rmdir(sock_dir)
        except OSError:
            pass
    return 0


async def tui_loop(bcast: Broadcaster) -> None:
    """Read stdin in raw mode and broadcast keystrokes; render a status line.

    Exits when stdin EOFs, when Ctrl-Q is pressed, or when one of
    SIGINT / SIGTERM / SIGHUP is received. SIGWINCH propagates the
    master terminal's winsize to every slave PTY.
    """
    if not sys.stdin.isatty():
        await asyncio.Event().wait()
        return

    loop = asyncio.get_running_loop()
    quit_event = asyncio.Event()

    def on_sigwinch() -> None:
        rows, cols, xp, yp = get_winsize(sys.stdin.fileno())
        for s in bcast.slaves:
            set_winsize(s.pty_master, rows, cols, xp, yp)

    def on_quit_signal() -> None:
        quit_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            loop.add_signal_handler(sig, on_quit_signal)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        loop.add_signal_handler(signal.SIGWINCH, on_sigwinch)
    except (NotImplementedError, RuntimeError, AttributeError):
        pass

    on_sigwinch()
    render_status(bcast)

    with raw_mode():
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        pipe = os.fdopen(sys.stdin.fileno(), "rb", buffering=0, closefd=False)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, pipe)

        async def reader_task() -> None:
            while True:
                data = await reader.read(64)
                if not data:
                    quit_event.set()
                    return
                if b"\x11" in data:  # Ctrl-Q
                    quit_event.set()
                    return
                await bcast.broadcast(data)

        task = asyncio.create_task(reader_task())
        try:
            await quit_event.wait()
        finally:
            task.cancel()
            transport.close()


def render_status(bcast: Broadcaster) -> None:
    """Write a one-line status footer to stderr."""
    enabled = bcast.enabled_indices()
    total = len(bcast.slaves)
    sys.stderr.write(
        f"\r[csshx-latest] hosts: {total}  enabled: {len(enabled)}  (Ctrl-Q to quit)\n"
    )
    sys.stderr.flush()
