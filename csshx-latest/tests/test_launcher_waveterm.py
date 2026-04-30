"""Tests for the WaveTerm launcher (subprocess.run mocked)."""
from __future__ import annotations

import subprocess

import pytest

from csshx_latest.launchers import waveterm as waveterm_mod


@pytest.fixture
def fake_run(monkeypatch):
    """Replace ``subprocess.run`` with a recorder that mimics ``wsh``."""
    calls: list[list[str]] = []

    def runner(args, check=False, capture_output=False, text=False):
        calls.append(list(args))
        if args[:2] == ["wsh", "run"]:
            return subprocess.CompletedProcess(args, 0, stdout="block-7\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(waveterm_mod.subprocess, "run", runner)
    return calls


def test_open_block_invokes_wsh_run(fake_run):
    l = waveterm_mod.WaveTermLauncher()
    h = l.open_block(["socat", "-", "UNIX-CONNECT:/tmp/a"], "web01")
    assert fake_run[0][:3] == ["wsh", "run", "--"]
    assert "socat" in fake_run[0]
    assert h.data["block_id"] == "block-7"


def test_tile_attempts_layout_subcommands(fake_run):
    l = waveterm_mod.WaveTermLauncher()
    fake_run.clear()
    l.tile([])
    assert fake_run, "tile should attempt at least one wsh subcommand"
    assert all(c[0] == "wsh" for c in fake_run)
    # All attempts target a tiled-style layout.
    flat = [arg for c in fake_run for arg in c]
    assert any("tile" in a for a in flat) or any("tiled" in a for a in flat)


def test_close_block_invokes_deleteblock(fake_run):
    l = waveterm_mod.WaveTermLauncher()
    h = l.open_block(["echo", "hi"], "h")
    fake_run.clear()
    l.close_block(h)
    assert fake_run and fake_run[0][:2] == ["wsh", "deleteblock"]
    assert "block-7" in fake_run[0]


def test_set_title_invokes_settitle(fake_run):
    l = waveterm_mod.WaveTermLauncher()
    h = l.open_block(["echo", "hi"], "h")
    fake_run.clear()
    l.set_title(h, "renamed")
    assert fake_run and fake_run[0][:2] == ["wsh", "settitle"]
    assert "renamed" in fake_run[0]


def test_tile_stops_at_first_zero_exit(fake_run):
    """``setlayout`` succeeds first; we should not retry the others."""
    l = waveterm_mod.WaveTermLauncher()
    fake_run.clear()
    l.tile([])
    assert len(fake_run) == 1
