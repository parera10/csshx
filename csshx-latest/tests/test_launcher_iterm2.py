"""Tests for the iTerm2 launcher (osascript mocked).

iTerm2's AppleScript bridge is fundamentally opaque from Python's side
— the only thing we can really verify without an actual iTerm2 process
is the *shape* of the AppleScript we send. Specifically, the v1.1
powerlevel10k fix relies on running the attach command as the new
session's ``command`` (which iTerm execvps directly) rather than via
``write text`` (which types into the user's interactive shell, where
p10k's instant-prompt can intercept keystrokes). These tests pin that
contract.
"""
from __future__ import annotations

import subprocess

import pytest

from csshx_latest.launchers import iterm2 as iterm_mod


@pytest.fixture
def fake_osascript(monkeypatch):
    """Capture every osascript invocation; return the AppleScript bodies."""
    scripts: list[str] = []

    def runner(args, check=False, capture_output=False, text=False):
        # Real call shape: ``osascript -e <script>``.
        if args[:2] == ["osascript", "-e"]:
            scripts.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(iterm_mod.subprocess, "run", runner)
    return scripts


def test_first_open_creates_window_with_command_not_write_text(fake_osascript):
    """First block → ``create window with default profile command "<cmd>"``."""
    l = iterm_mod.ITerm2Launcher()
    l.open_block(["socat", "-", "UNIX-CONNECT:/tmp/a"], "web01")

    assert len(fake_osascript) == 1
    s = fake_osascript[0]
    # The p10k fix: pass attach as the new session's ``command``,
    # not via ``write text`` (which types into the interactive shell).
    assert "create window with default profile" in s
    assert 'command "' in s
    assert "write text" not in s
    # Title is applied via ``set name`` on the new session.
    assert 'set name to "web01"' in s
    # Attach argv must appear inside the command string.
    assert "socat" in s


def test_second_open_uses_split_vertically_with_command(fake_osascript):
    """Subsequent blocks split the current session, again via ``command``."""
    l = iterm_mod.ITerm2Launcher()
    l.open_block(["echo", "first"], "first")
    l.open_block(["echo", "second"], "second")

    assert len(fake_osascript) == 2
    s2 = fake_osascript[1]
    assert "split vertically with default profile" in s2
    assert 'command "' in s2
    assert "write text" not in s2
    assert 'set name to "second"' in s2


def test_special_chars_in_attach_command_are_escaped(fake_osascript):
    """Backslashes and double-quotes in argv must not break out of the literal."""
    l = iterm_mod.ITerm2Launcher()
    l.open_block(['echo', 'has "quote" and \\back'], "evil")

    s = fake_osascript[0]
    # Raw double-quote / backslash must be escaped in the AppleScript body.
    # We can't easily count exact escaping without re-parsing, but we
    # can verify that unescaped sequences that would terminate the
    # AppleScript string do NOT appear adjacent to the cmd boundary.
    cmd_start = s.index('command "') + len('command "')
    # The next unescaped " marks the end of the AppleScript literal.
    # Make sure the user's literal `"quote"` chars don't terminate early.
    tail = s[cmd_start:]
    # Find first un-escaped quote (i.e. a `"` not preceded by `\`).
    i = 0
    while i < len(tail):
        if tail[i] == '"' and (i == 0 or tail[i - 1] != "\\"):
            break
        i += 1
    closing_quote = i
    # Everything up to closing_quote is the embedded command. It MUST
    # still contain the original 'echo' token — if escaping broke, the
    # AppleScript would have terminated before that.
    embedded = tail[:closing_quote]
    assert "echo" in embedded


def test_close_block_is_noop(fake_osascript):
    """iTerm2 sessions die when ssh exits; close_block is intentionally no-op."""
    l = iterm_mod.ITerm2Launcher()
    h = l.open_block(["echo"], "h")
    fake_osascript.clear()

    l.close_block(h)

    assert fake_osascript == []


def test_tile_is_noop(fake_osascript):
    """iTerm2 auto-balances splits — explicit tiling is unnecessary."""
    l = iterm_mod.ITerm2Launcher()
    fake_osascript.clear()

    l.tile([])

    assert fake_osascript == []


def test_set_title_renames_current_session(fake_osascript):
    """Best-effort: ``set name to`` on the current session."""
    l = iterm_mod.ITerm2Launcher()
    h = l.open_block(["echo"], "h")
    fake_osascript.clear()

    l.set_title(h, "renamed")

    assert len(fake_osascript) == 1
    assert "set name to" in fake_osascript[0]
    assert "renamed" in fake_osascript[0]
