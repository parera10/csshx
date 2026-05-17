"""Tests for the Apple Terminal launcher (osascript mocked).

The p10k fix here is the ``exec /bin/sh -c '...'`` wrapper around the
attach command: zsh's first parsed line exec-replaces the user's
interactive shell with ``/bin/sh`` running our command, so p10k's
instant-prompt never runs and never gets a chance to swallow
keystrokes. These tests pin that contract — the generated AppleScript
must include the ``exec`` prefix.
"""
from __future__ import annotations

import subprocess

import pytest

from csshx_latest.launchers import apple_terminal as term_mod


@pytest.fixture
def fake_osascript(monkeypatch):
    scripts: list[str] = []

    def runner(args, check=False, capture_output=False, text=False):
        if args[:2] == ["osascript", "-e"]:
            scripts.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(term_mod.subprocess, "run", runner)
    return scripts


def test_open_block_wraps_attach_in_exec_sh(fake_osascript):
    """The do-script body must start with ``exec /bin/sh -c`` (p10k fix)."""
    l = term_mod.AppleTerminalLauncher()
    l.open_block(["socat", "-", "UNIX-CONNECT:/tmp/a"], "web01")

    assert len(fake_osascript) == 1
    s = fake_osascript[0]
    # The wrapper is the contract: without it, p10k can swallow keystrokes.
    assert "exec /bin/sh -c" in s
    # Custom title is applied to the new tab.
    assert 'set custom title of newTab to "web01"' in s
    # ``do script`` is Terminal.app's only AppleScript entry point.
    assert "do script" in s


def test_open_block_returns_handle_with_title(fake_osascript):
    """The handle records the title so future ``set_title`` calls can find it."""
    l = term_mod.AppleTerminalLauncher()
    h = l.open_block(["echo", "hi"], "host-x")
    assert h.backend == "terminal"
    assert h.data["title"] == "host-x"


def test_close_block_is_noop(fake_osascript):
    """Terminal.app gives us no tab handle, so close_block is intentionally no-op."""
    l = term_mod.AppleTerminalLauncher()
    h = l.open_block(["echo"], "h")
    fake_osascript.clear()

    l.close_block(h)

    assert fake_osascript == []


def test_tile_is_noop(fake_osascript):
    """Terminal.app has no programmatic tiling."""
    l = term_mod.AppleTerminalLauncher()
    fake_osascript.clear()

    l.tile([])

    assert fake_osascript == []


def test_set_title_is_noop(fake_osascript):
    """We don't track tab references after creation, so set_title no-ops."""
    l = term_mod.AppleTerminalLauncher()
    h = l.open_block(["echo"], "h")
    fake_osascript.clear()

    l.set_title(h, "x")

    assert fake_osascript == []


def test_special_chars_in_title_are_escaped(fake_osascript):
    """A title containing a double-quote must not break the AppleScript string."""
    l = term_mod.AppleTerminalLauncher()
    l.open_block(["echo"], 'evil"title')

    s = fake_osascript[0]
    # The literal `"` in the title must be backslash-escaped in the script.
    assert 'evil\\"title' in s
