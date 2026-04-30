"""One SSH slave: PTY + ssh subprocess + UNIX-socket bridge.

The master forks ``ssh <host>`` attached to a fresh PTY and exposes
that PTY through a UNIX domain socket gated by an AUTH token.

Output direction (PTY -> socket) is one-way: bytes the SSH session
emits are fanned out to every authenticated socket connection (the
visible terminal block). Bytes that arrive *before* the terminal block
has connected are kept in a per-slave scrollback buffer and replayed to
each new client immediately after AUTH succeeds — otherwise the SSH
banner and login prompt would be silently dropped during the time it
takes the launcher to spawn the visible block.

Input direction (socket -> PTY) accepts bytes from the focused terminal
block AND from the master's broadcaster, both serialized through a
per-slave ``write_lock`` so individual escape sequences are never torn
apart by interleaving writes.
"""
from __future__ import annotations

import asyncio
import os
import signal
import socket
from dataclasses import dataclass, field
from typing import Optional

from csshx_latest.auth import authenticate
from csshx_latest.terminal import set_winsize


@dataclass
class Slave:
    """State for one SSH connection.

    ``enabled`` is the broadcast filter — keystrokes from the master
    TUI are only delivered to slaves with ``enabled=True``. Per-slave
    typing through the socket bridge ignores this flag (you can always
    type to a focused block).
    """

    index: int
    host: str
    sock_path: str
    token: str
    pty_master: int
    pid: int
    enabled: bool = True
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    server: Optional[asyncio.AbstractServer] = field(default=None, repr=False)
    pty_reader_task: Optional[asyncio.Task] = field(default=None, repr=False)
    connected_writers: list[asyncio.StreamWriter] = field(default_factory=list, repr=False)
    # Bytes the PTY has emitted so far. Replayed to each new client after AUTH
    # so late-connecting terminal blocks see the full session (banner, prompt,
    # whatever scrolled by while the launcher was spawning them).
    scrollback: bytearray = field(default_factory=bytearray, repr=False)
    scrollback_max: int = 65536
    # Held during the brief window where we (a) extend scrollback + snapshot
    # writers, or (b) replay scrollback + register a new writer. Ensures every
    # byte the PTY emits reaches every client exactly once and in order.
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def spawn_slave(
    index: int,
    host: str,
    sock_dir: str,
    ssh_args: list[str],
    login: Optional[str],
    token: str,
) -> Slave:
    """Fork ``ssh <host>`` attached to a new PTY and return its :class:`Slave`."""
    import pty  # local import so the package can be imported on non-Unix
    pty_master, pty_slave = pty.openpty()
    set_winsize(pty_master, 24, 80)

    cmd = ["ssh", *ssh_args]
    if login:
        cmd += ["-l", login]
    cmd.append(host)

    pid = os.fork()
    if pid == 0:  # pragma: no cover - child path
        try:
            os.setsid()
            os.close(pty_master)
            os.dup2(pty_slave, 0)
            os.dup2(pty_slave, 1)
            os.dup2(pty_slave, 2)
            if pty_slave > 2:
                os.close(pty_slave)
            os.execvp(cmd[0], cmd)
        except Exception as exc:
            os.write(2, f"slave spawn failed: {exc}\n".encode())
            os._exit(127)
    os.close(pty_slave)

    sock_path = os.path.join(sock_dir, f"slave-{index}.sock")
    return Slave(
        index=index,
        host=host,
        sock_path=sock_path,
        token=token,
        pty_master=pty_master,
        pid=pid,
    )


async def run_slave_bridge(slave: Slave) -> None:
    """Start the bidirectional PTY <-> socket bridge for ``slave``.

    Spawns:
      * a UNIX-domain server bound at ``slave.sock_path`` (mode 0600)
        that AUTH-gates every incoming connection and forwards bytes
        to the PTY master fd;
      * a background task that reads from the PTY master fd and fans
        bytes out to all currently connected, authenticated writers.
    """
    loop = asyncio.get_running_loop()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not await authenticate(reader, slave.token):
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        # Replay scrollback and register the writer atomically with respect to
        # pty_to_sockets — no await between buffering scrollback and joining
        # the writer list — so we can never duplicate or lose a chunk.
        async with slave.state_lock:
            if slave.scrollback:
                writer.write(bytes(slave.scrollback))
            slave.connected_writers.append(writer)
        try:
            await writer.drain()
        except Exception:
            pass
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                async with slave.write_lock:
                    _write_all(slave.pty_master, data)
        finally:
            try:
                slave.connected_writers.remove(writer)
            except ValueError:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_unix_server(handle_client, path=slave.sock_path)
    os.chmod(slave.sock_path, 0o600)
    slave.server = server

    async def pty_to_sockets() -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        pipe = os.fdopen(slave.pty_master, "rb", buffering=0, closefd=False)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, pipe)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                # Atomically: append to scrollback, snapshot current writers,
                # buffer the chunk to each. No await inside this block — the
                # writes go to in-memory asyncio buffers; drain() runs after.
                async with slave.state_lock:
                    slave.scrollback.extend(data)
                    excess = len(slave.scrollback) - slave.scrollback_max
                    if excess > 0:
                        del slave.scrollback[:excess]
                    writers = list(slave.connected_writers)
                    for w in writers:
                        try:
                            w.write(data)
                        except Exception:
                            try:
                                slave.connected_writers.remove(w)
                            except ValueError:
                                pass
                for w in writers:
                    try:
                        await w.drain()
                    except Exception:
                        try:
                            slave.connected_writers.remove(w)
                        except ValueError:
                            pass
        finally:
            transport.close()

    slave.pty_reader_task = asyncio.create_task(pty_to_sockets())


async def write_to_slave(slave: Slave, data: bytes) -> None:
    """Write ``data`` to ``slave``'s PTY iff the slave is ``enabled``."""
    if not slave.enabled:
        return
    async with slave.write_lock:
        _write_all(slave.pty_master, data)


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until every byte has been delivered (handles short writes)."""
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n == 0:
            break
        view = view[n:]


def shutdown_slave(slave: Slave) -> None:
    """Tear down a slave: stop the server, kill ssh, close fds, unlink the socket."""
    if slave.server is not None:
        slave.server.close()
    if slave.pty_reader_task is not None and not slave.pty_reader_task.done():
        slave.pty_reader_task.cancel()
    try:
        os.kill(slave.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        os.close(slave.pty_master)
    except OSError:
        pass
    try:
        os.unlink(slave.sock_path)
    except OSError:
        pass
