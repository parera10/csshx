"""Tests for the Tmux launcher (subprocess.run mocked)."""
from __future__ import annotations

import subprocess

import pytest

from csshx_latest.launchers import tmux as tmux_mod


@pytest.fixture
def fake_run(monkeypatch):
    """Replace ``subprocess.run`` with a recorder that mimics tmux output."""
    calls: list[list[str]] = []

    def runner(args, check=False, capture_output=False, text=False):
        calls.append(list(args))
        if "split-window" in args:
            return subprocess.CompletedProcess(args, 0, stdout="%42\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux_mod.subprocess, "run", runner)
    return calls


def test_open_block_runs_split_window_and_titles(fake_run):
    l = tmux_mod.TmuxLauncher()
    h = l.open_block(["socat", "-", "UNIX-CONNECT:/tmp/a"], "web01")
    assert h.backend == "tmux"
    assert h.data["pane_id"] == "%42"

    assert fake_run[0][:2] == ["tmux", "split-window"]
    assert "-P" in fake_run[0]
    title_call = next(c for c in fake_run if "select-pane" in c)
    assert "web01" in title_call


def test_tile_calls_select_layout_tiled(fake_run):
    l = tmux_mod.TmuxLauncher()
    h = l.open_block(["echo"], "h")
    fake_run.clear()
    l.tile([h])
    assert any("select-layout" in c and "tiled" in c for c in fake_run)


def test_close_block_kills_pane(fake_run):
    l = tmux_mod.TmuxLauncher()
    h = l.open_block(["echo"], "h")
    fake_run.clear()
    l.close_block(h)
    assert any("kill-pane" in c for c in fake_run)


def test_tile_with_no_handles_is_silent(fake_run):
    l = tmux_mod.TmuxLauncher()
    fake_run.clear()
    l.tile([])
    assert fake_run == []


def test_set_title_runs_select_pane_T(fake_run):
    l = tmux_mod.TmuxLauncher()
    h = l.open_block(["echo"], "h")
    fake_run.clear()
    l.set_title(h, "renamed")
    assert any("select-pane" in c and "renamed" in c for c in fake_run)
