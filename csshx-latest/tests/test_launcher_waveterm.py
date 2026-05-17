"""Tests for the WaveTerm launcher (subprocess.run mocked)."""
from __future__ import annotations

import os
import subprocess

import pytest

from csshx_latest.launchers import waveterm as waveterm_mod


@pytest.fixture(autouse=True)
def _pin_wsh(monkeypatch, request):
    """Force ``_resolve_wsh`` to return the literal ``"wsh"`` so tests can
    assert on argv[0] without caring whether the host has wsh installed.

    Tests whose names start with ``test_resolve_wsh_`` opt out — they need
    the real resolver to verify its behavior.
    """
    if request.node.name.startswith(("test_resolve_wsh_", "test_swap_", "test_parse_bash_")):
        return
    monkeypatch.setattr(waveterm_mod, "_resolve_wsh", lambda: "wsh")
    # Don't let the launcher's __init__ swap a real token from the test
    # runner's env (e.g. when running tests inside a WaveTerm block).
    monkeypatch.setattr(waveterm_mod, "_swap_waveterm_token", lambda _wsh: True)


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


def test_tile_caches_first_successful_subcommand(monkeypatch):
    """Once a variant works, every subsequent tile() uses it without re-probing."""
    calls: list[list[str]] = []

    def runner(args, check=False, capture_output=False, text=False):
        calls.append(list(args))
        # Only the LAST variant in _TILE_VARIANTS succeeds.
        if args == ["wsh", "tile"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown cmd")

    monkeypatch.setattr(waveterm_mod.subprocess, "run", runner)
    l = waveterm_mod.WaveTermLauncher()

    # First tile() probes three variants.
    l.tile([])
    first_probe_count = len(calls)
    assert first_probe_count == 3
    assert calls[-1] == ["wsh", "tile"]

    # Subsequent tile() calls reuse the cached winner — exactly one call each.
    calls.clear()
    l.tile([])
    l.tile([])
    assert calls == [["wsh", "tile"], ["wsh", "tile"]]


def test_tile_does_not_reprobe_when_all_variants_fail(monkeypatch):
    """If nothing works, remember that — don't keep probing forever."""
    calls: list[list[str]] = []

    def runner(args, check=False, capture_output=False, text=False):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="x")

    monkeypatch.setattr(waveterm_mod.subprocess, "run", runner)
    l = waveterm_mod.WaveTermLauncher()

    l.tile([])
    first = len(calls)
    l.tile([])  # Should be a no-op now — nothing cached, probe already done.
    assert len(calls) == first


def test_resolve_wsh_prefers_path(monkeypatch):
    """If ``wsh`` is on PATH, that's what we use (don't probe fallback dirs)."""
    monkeypatch.setattr(waveterm_mod.shutil, "which", lambda name: "/usr/local/bin/wsh")
    assert waveterm_mod._resolve_wsh() == "/usr/local/bin/wsh"


def test_resolve_wsh_falls_back_to_known_install_paths(monkeypatch, tmp_path):
    """When PATH lookup fails, scan the WaveTerm install dirs.

    Simulates the widget case: ``controller: cmd`` execvp's csshx-latest with
    only the bare system PATH, which doesn't include WaveTerm's bin dir.
    The launcher must still find ``wsh`` so ``wsh run`` doesn't ENOENT.
    """
    fake_wsh = tmp_path / "wsh"
    fake_wsh.write_text("#!/bin/sh\nexit 0\n")
    fake_wsh.chmod(0o755)
    monkeypatch.setattr(waveterm_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(waveterm_mod, "_WSH_FALLBACK_PATHS", (str(fake_wsh),))
    assert waveterm_mod._resolve_wsh() == str(fake_wsh)


def test_resolve_wsh_returns_literal_when_nothing_found(monkeypatch):
    """Last-resort: return ``"wsh"`` so subprocess raises a clear ENOENT."""
    monkeypatch.setattr(waveterm_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(waveterm_mod, "_WSH_FALLBACK_PATHS", ())
    assert waveterm_mod._resolve_wsh() == "wsh"


def test_parse_bash_exports_handles_quoting_variants():
    """``wsh token`` emits double-quoted, single-quoted, and unquoted exports."""
    script = '\n'.join([
        'export WAVETERM_JWT="abc.def.ghi"',
        "export WAVETERM_BLOCKID='7f1791ee-62bf'",
        'export WAVETERM_VERSION=0.14.5',
        '# comment line',
        'echo something else',
    ])
    out = waveterm_mod._parse_bash_exports(script)
    assert out["WAVETERM_JWT"] == "abc.def.ghi"
    assert out["WAVETERM_BLOCKID"] == "7f1791ee-62bf"
    assert out["WAVETERM_VERSION"] == "0.14.5"
    assert "echo" not in out


def test_swap_waveterm_token_populates_env(monkeypatch):
    """A successful swap copies JWT (and friends) into os.environ."""
    monkeypatch.delenv("WAVETERM_JWT", raising=False)
    monkeypatch.setenv("WAVETERM_SWAPTOKEN", "totally-real-swap-token")

    def fake_run(args, check=False, capture_output=False, text=False, timeout=None):
        assert args[1:] == ["token", "totally-real-swap-token", "bash"]
        return subprocess.CompletedProcess(
            args, 0,
            stdout='export WAVETERM_JWT="jwt-xyz"\nexport WAVETERM_BLOCKID="bid-1"\n',
            stderr="",
        )

    monkeypatch.setattr(waveterm_mod.subprocess, "run", fake_run)
    assert waveterm_mod._swap_waveterm_token("/fake/wsh") is True
    assert os.environ["WAVETERM_JWT"] == "jwt-xyz"
    assert os.environ["WAVETERM_BLOCKID"] == "bid-1"


def test_swap_waveterm_token_is_noop_when_jwt_already_set(monkeypatch):
    """If WAVETERM_JWT is already exported, don't fork wsh again."""
    monkeypatch.setenv("WAVETERM_JWT", "pre-existing")
    called = []

    def fake_run(*args, **kwargs):
        called.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(waveterm_mod.subprocess, "run", fake_run)
    assert waveterm_mod._swap_waveterm_token("/fake/wsh") is True
    assert called == []


def test_swap_waveterm_token_returns_false_when_no_swaptoken(monkeypatch):
    """No swap token and no JWT means we can't authenticate — report it."""
    monkeypatch.delenv("WAVETERM_JWT", raising=False)
    monkeypatch.delenv("WAVETERM_SWAPTOKEN", raising=False)
    assert waveterm_mod._swap_waveterm_token("/fake/wsh") is False


def test_swap_waveterm_token_returns_false_on_wsh_nonzero(monkeypatch):
    """wsh token exit != 0 must not corrupt os.environ."""
    monkeypatch.delenv("WAVETERM_JWT", raising=False)
    monkeypatch.setenv("WAVETERM_SWAPTOKEN", "bad")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="invalid")

    monkeypatch.setattr(waveterm_mod.subprocess, "run", fake_run)
    assert waveterm_mod._swap_waveterm_token("/fake/wsh") is False
    assert "WAVETERM_JWT" not in os.environ
