"""Tiny stdlib-only attach client used when ``socat`` isn't installed.

Connects to a slave's UNIX socket, performs the AUTH handshake, then
shuttles bytes between stdin/stdout and the socket. Run as a module so
spawned terminal blocks can launch it without any extra dependency::

    python3 -m csshx_latest.attach <socket_path> <token>
"""
from __future__ import annotations

import os
import select
import socket
import sys

BUFSIZE = 4096


def main(argv: list[str]) -> int:
    """Entry point. Returns the process exit code."""
    if len(argv) != 3:
        sys.stderr.write("usage: python3 -m csshx_latest.attach <socket_path> <token>\n")
        return 2
    path, token = argv[1], argv[2]

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    except OSError as exc:
        sys.stderr.write(f"connect {path}: {exc}\n")
        return 1
    sock.sendall(f"AUTH {token}\n".encode("ascii"))

    in_fd = sys.stdin.fileno()
    out_fd = sys.stdout.fileno()

    saved = None
    if os.isatty(in_fd):
        import termios
        import tty
        saved = termios.tcgetattr(in_fd)
        tty.setraw(in_fd)

    watch_in = True
    try:
        while True:
            watches = [sock]
            if watch_in:
                watches.append(in_fd)
            r, _, _ = select.select(watches, [], [])
            if sock in r:
                data = sock.recv(BUFSIZE)
                if not data:
                    return 0
                os.write(out_fd, data)
            if watch_in and in_fd in r:
                try:
                    data = os.read(in_fd, BUFSIZE)
                except OSError:
                    data = b""
                if not data:
                    watch_in = False
                    try:
                        sock.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                else:
                    sock.sendall(data)
    except KeyboardInterrupt:
        return 130
    finally:
        if saved is not None:
            import termios
            termios.tcsetattr(in_fd, termios.TCSADRAIN, saved)
        sock.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
