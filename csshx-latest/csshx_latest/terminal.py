"""Terminal helpers: raw-mode context manager and PTY winsize ioctls.

These are tiny wrappers around termios / fcntl that hide the boilerplate
and degrade to no-ops on platforms without those modules (e.g. Windows),
so the package can at least be imported there.
"""
from __future__ import annotations

import os
import struct
import sys
from contextlib import contextmanager
from typing import Iterator, Optional

try:
    import fcntl
    import termios
    import tty
    _UNIX = True
except ImportError:  # pragma: no cover - non-unix
    _UNIX = False


def get_winsize(fd: int) -> tuple[int, int, int, int]:
    """Return ``(rows, cols, xpixel, ypixel)`` for ``fd``.

    Falls back to ``(24, 80, 0, 0)`` if the ioctl fails or the platform
    doesn't support TIOCGWINSZ.
    """
    if not _UNIX:
        return (24, 80, 0, 0)
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\x00" * 8)
        return struct.unpack("HHHH", packed)
    except OSError:
        return (24, 80, 0, 0)


def set_winsize(fd: int, rows: int, cols: int, xpixel: int = 0, ypixel: int = 0) -> None:
    """Set the window size on a PTY master ``fd`` via TIOCSWINSZ."""
    if not _UNIX:
        return
    packed = struct.pack("HHHH", rows, cols, xpixel, ypixel)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except OSError:
        pass


@contextmanager
def raw_mode(fd: Optional[int] = None) -> Iterator[None]:
    """Put ``fd`` (default stdin) into termios raw mode; restore on exit.

    No-ops on non-Unix or when the fd is not a TTY, so callers don't
    need to special-case those cases themselves.
    """
    if not _UNIX:
        yield
        return
    if fd is None:
        fd = sys.stdin.fileno()
    if not os.isatty(fd):
        yield
        return
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
