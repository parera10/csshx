"""Tests for the fallback attach client.

Covers:

* the new "token file" contract (the token is read from a file path,
  not embedded in argv, so ``ps`` can't be used to harvest it);
* the "AUTH rejected" exit path (master closes the socket before
  sending data → diagnostic to stderr + exit 1, so the user notices
  the problem rather than seeing the spawned block silently die);
* the happy-path exit code (master sends some bytes then closes →
  client returns 0);
* argv / connect-error handling.
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


def _write_token(token_dir: str, token: str) -> str:
    """Persist a token to a 0600 file inside ``token_dir`` and return its path."""
    path = os.path.join(token_dir, "tok")
    with open(path, "w", encoding="ascii") as fh:
        fh.write(token)
    os.chmod(path, 0o600)
    return path


def test_auth_rejection_returns_1_with_clear_stderr(
    short_socket_dir, stdio_devnull, capsys
):
    """Server closes immediately after reading AUTH → client must exit 1."""
    sock_path = os.path.join(short_socket_dir, "rejecting.sock")
    token_path = _write_token(short_socket_dir, "BAD_TOKEN")

    auth_sent = threading.Event()

    def reject(conn: socket.socket) -> None:
        # Drain whatever AUTH bytes the client sends so its sendall completes,
        # then close without ever writing back. This is exactly what the real
        # server does on a bad token.
        try:
            conn.recv(4096)
        except OSError:
            pass
        auth_sent.set()

    srv, t = _start_unix_server(sock_path, reject)
    try:
        rc = attach.main(["attach", sock_path, token_path])
    finally:
        srv.close()
        t.join(timeout=2)

    err = capsys.readouterr().err
    assert rc == 1
    assert "AUTH rejected" in err


def test_clean_eof_after_data_returns_0(short_socket_dir, stdio_devnull, capsys):
    """Server sends some bytes then closes → client exits 0 (normal disconnect)."""
    sock_path = os.path.join(short_socket_dir, "happy.sock")
    token_path = _write_token(short_socket_dir, "TOKEN")

    def serve(conn: socket.socket) -> None:
        try:
            conn.recv(4096)  # consume AUTH line
            conn.sendall(b"hello from master\n")
        except OSError:
            pass

    srv, t = _start_unix_server(sock_path, serve)
    try:
        rc = attach.main(["attach", sock_path, token_path])
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
    token_path = _write_token(short_socket_dir, "tok")
    rc = attach.main(["attach", sock_path, token_path])
    err = capsys.readouterr().err
    assert rc == 1
    assert "connect" in err


def test_missing_token_file_returns_1(short_socket_dir, capsys):
    """Token file missing → exit 1 with a clear diagnostic, no socket attempt."""
    sock_path = os.path.join(short_socket_dir, "any.sock")
    bogus_token_path = os.path.join(short_socket_dir, "does-not-exist.tok")
    rc = attach.main(["attach", sock_path, bogus_token_path])
    err = capsys.readouterr().err
    assert rc == 1
    assert "token" in err


def test_token_file_contents_are_used(short_socket_dir, stdio_devnull, capsys):
    """The bytes sent on AUTH must come from the token file, not from argv."""
    sock_path = os.path.join(short_socket_dir, "auth.sock")
    secret = "this-is-the-actual-token-7f3a"
    token_path = _write_token(short_socket_dir, secret)

    received_lines: list[bytes] = []

    def capture(conn: socket.socket) -> None:
        try:
            data = conn.recv(4096)
        except OSError:
            data = b""
        received_lines.append(data)
        # Close without sending → client should exit 1 (AUTH rejected),
        # but the test only cares about what was *sent* in AUTH.

    srv, t = _start_unix_server(sock_path, capture)
    try:
        attach.main(["attach", sock_path, token_path])
    finally:
        srv.close()
        t.join(timeout=2)

    assert received_lines, "server received nothing on the socket"
    assert received_lines[0].startswith(b"AUTH ")
    assert secret.encode("ascii") in received_lines[0]
