"""Token generation and authentication handshake for slave sockets.

Each slave socket created by the master is gated by a 32-byte hex
token. Connecting clients must send `AUTH <token>\\n` as the first
line within HANDSHAKE_TIMEOUT seconds; otherwise their connection is
dropped. This prevents other local users from injecting keystrokes
into your SSH sessions.
"""
from __future__ import annotations

import asyncio
import secrets

TOKEN_BYTES = 32
HANDSHAKE_TIMEOUT = 2.0


def make_token() -> str:
    """Return a fresh 64-character hex token (32 bytes of entropy)."""
    return secrets.token_hex(TOKEN_BYTES)


async def authenticate(reader: asyncio.StreamReader, expected: str) -> bool:
    """Read the first line and validate the AUTH handshake.

    Returns True iff the client sent ``AUTH <expected>\\n`` (\\r is
    tolerated) within HANDSHAKE_TIMEOUT seconds. Uses a constant-time
    comparison for the token.
    """
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
    except asyncio.TimeoutError:
        return False
    if not line:
        return False
    try:
        text = line.decode("ascii", errors="strict").rstrip("\r\n")
    except UnicodeDecodeError:
        return False
    if not text.startswith("AUTH "):
        return False
    return secrets.compare_digest(text[5:], expected)
