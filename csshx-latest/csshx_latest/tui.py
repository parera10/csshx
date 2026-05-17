"""Master TUI: raw-mode stdin, status line, and command-mode dispatch.

Author: Aditya Kapadia.

Command mode (``Ctrl-T`` prefix, then one key):

* ``b`` -- toggle broadcast for ALL alive slaves
* ``1`` ... ``9`` -- toggle broadcast for that single slave
* ``i`` -- prompt for a slave index (for clusters with 10+ hosts)
* ``l`` -- list slaves with their state
* ``q`` -- quit
* ``?`` -- show command-mode help
* ``Ctrl-T`` -- send a literal ``Ctrl-T`` byte to slaves
* (any other key) -- cancel command mode
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from csshx_latest.broadcaster import Broadcaster
from csshx_latest.terminal import get_winsize, raw_mode, set_winsize

log = logging.getLogger(__name__)

KEY_QUIT = b"\x11"               # Ctrl-Q
KEY_COMMAND_PREFIX = b"\x14"     # Ctrl-T
KEY_INDEX_PROMPT = b"i"


def render_status(bcast: Broadcaster) -> None:
    """Write a one-line status footer to stderr."""
    total = len(bcast.slaves)
    enabled = len(bcast.enabled_indices())
    dead = sum(1 for s in bcast.slaves if s.dead)
    sys.stderr.write(
        f"\r[csshx-latest] hosts: {total}  enabled: {enabled}  "
        f"dead: {dead}  (Ctrl-Q quit, Ctrl-T menu)\r\n"
    )
    sys.stderr.flush()


def _write_msg(msg: str) -> None:
    sys.stderr.write("\r" + msg + "\r\n")
    sys.stderr.flush()


def _render_help() -> None:
    _write_msg("--- csshx-latest command mode ---")
    _write_msg("  b        toggle broadcast for ALL alive slaves")
    _write_msg("  1..9     toggle broadcast for that single slave")
    _write_msg("  i        prompt for a slave index (for 10+ hosts)")
    _write_msg("  l        list slaves and their state")
    _write_msg("  q        quit")
    _write_msg("  ?        show this help")
    _write_msg("  Ctrl-T   send a literal Ctrl-T")
    _write_msg("  (other)  cancel command mode")


def _render_list(bcast: Broadcaster) -> None:
    _write_msg(f"--- {len(bcast.slaves)} slaves ---")
    for s in bcast.slaves:
        state = "DEAD" if s.dead else ("ON" if s.enabled else "off")
        _write_msg(f"  [{s.index:>3}] {s.host:<30} {state}")


def _toggle_slave(bcast: Broadcaster, index: int) -> None:
    try:
        new_state = bcast.toggle(index)
    except KeyError:
        _write_msg(f"no slave with index {index}")
        return
    _write_msg(f"slave [{index}] -> {'ON' if new_state else 'off'}")


class _CommandState:
    """State machine for command mode: prefix -> dispatch / index-prompt."""

    def __init__(self) -> None:
        self.in_command = False
        self.in_index_prompt = False
        self.index_buffer = bytearray()

    def reset(self) -> None:
        self.in_command = False
        self.in_index_prompt = False
        self.index_buffer.clear()


async def _handle_command_byte(
    bcast: Broadcaster, byte: int, quit_event: asyncio.Event
) -> bytes:
    """Apply one command-mode keystroke.

    Returns any bytes that should still be broadcast (e.g. the user
    pressed Ctrl-T twice -> send a literal Ctrl-T). Empty bytes mean
    "consumed, broadcast nothing".
    """
    ch = bytes([byte])
    if ch == KEY_COMMAND_PREFIX:
        return KEY_COMMAND_PREFIX
    if ch == b"b":
        any_enabled = any(s.enabled for s in bcast.slaves if not s.dead)
        bcast.set_all_enabled(not any_enabled)
        _write_msg(f"broadcast -> {'OFF' if any_enabled else 'ON'} for all alive slaves")
        render_status(bcast)
        return b""
    if ch in (b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8", b"9"):
        _toggle_slave(bcast, int(ch))
        render_status(bcast)
        return b""
    if ch == b"l":
        _render_list(bcast)
        render_status(bcast)
        return b""
    if ch == b"q":
        _write_msg("quitting...")
        quit_event.set()
        return b""
    if ch == b"?":
        _render_help()
        render_status(bcast)
        return b""
    _write_msg("(command-mode cancelled)")
    render_status(bcast)
    return b""


async def tui_loop(bcast: Broadcaster) -> None:
    """Read stdin in raw mode and broadcast keystrokes; render a status line."""
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

        state = _CommandState()

        async def reader_task() -> None:
            while True:
                data = await reader.read(64)
                if not data:
                    quit_event.set()
                    return
                if KEY_QUIT in data:
                    quit_event.set()
                    return
                if (
                    not state.in_command
                    and not state.in_index_prompt
                    and KEY_COMMAND_PREFIX not in data
                ):
                    await bcast.broadcast(data)
                    continue
                await _drain_with_command_handling(data, bcast, state, quit_event)

        task = asyncio.create_task(reader_task())
        try:
            await quit_event.wait()
        finally:
            task.cancel()
            transport.close()


async def _drain_with_command_handling(
    data: bytes,
    bcast: Broadcaster,
    state: _CommandState,
    quit_event: asyncio.Event,
) -> None:
    """Walk a chunk byte-by-byte when command / index-prompt mode is live."""
    buf = bytearray()
    for b in data:
        if state.in_index_prompt:
            if buf:
                await bcast.broadcast(bytes(buf))
                buf.clear()
            _consume_index_prompt_byte(b, bcast, state)
            continue
        if state.in_command:
            if buf:
                await bcast.broadcast(bytes(buf))
                buf.clear()
            if bytes([b]) == KEY_INDEX_PROMPT:
                state.in_command = False
                state.in_index_prompt = True
                state.index_buffer.clear()
                _write_msg("index: (type digits, Enter to apply, Esc to cancel)")
                continue
            extra = await _handle_command_byte(bcast, b, quit_event)
            state.in_command = False
            if extra:
                buf.extend(extra)
            continue
        if bytes([b]) == KEY_COMMAND_PREFIX:
            if buf:
                await bcast.broadcast(bytes(buf))
                buf.clear()
            state.in_command = True
            _write_msg("command mode (press ? for help)")
            continue
        buf.append(b)
    if buf:
        await bcast.broadcast(bytes(buf))


def _consume_index_prompt_byte(b: int, bcast: Broadcaster, state: _CommandState) -> None:
    """Process one byte while we're collecting digits for the index prompt."""
    if b in (0x1B, 0x03):
        _write_msg("(index prompt cancelled)")
        state.reset()
        render_status(bcast)
        return
    if b in (ord("\r"), ord("\n")):
        if not state.index_buffer:
            _write_msg("(no index given)")
        else:
            try:
                idx = int(state.index_buffer.decode("ascii"))
            except ValueError:
                _write_msg("(not a number)")
            else:
                _toggle_slave(bcast, idx)
        state.reset()
        render_status(bcast)
        return
    if b in (0x7F, 0x08):
        if state.index_buffer:
            state.index_buffer.pop()
        return
    if 0x30 <= b <= 0x39:
        state.index_buffer.append(b)
