"""Launcher Protocol and environment-based auto-detection.

A Launcher knows how to ask one specific terminal application (Wave,
iTerm2, tmux, ...) to open a new visible block running an arbitrary
command, and optionally to tile/title the resulting blocks.

Concrete launchers live under :mod:`csshx_latest.launchers`. They are
imported lazily in :func:`detect_launcher` so that selecting one
backend doesn't pay the import cost of the others.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class BlockHandle:
    """Opaque handle returned by :meth:`Launcher.open_block`.

    ``data`` is a per-backend bag of identifiers (pane id, window id,
    block id, ...) that the same backend uses to later close, retitle,
    or tile the block.
    """

    backend: str
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Launcher(Protocol):
    """Pluggable terminal-backend interface."""

    name: str

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Open a visible block and run ``attach_cmd`` inside it."""
        ...

    def close_block(self, handle: BlockHandle) -> None:
        """Close a block previously returned by :meth:`open_block`."""
        ...

    def tile(self, handles: list[BlockHandle]) -> None:
        """Arrange the given blocks in a tiled layout. May be a no-op."""
        ...

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename a block. May be a no-op."""
        ...


_LAUNCHERS = {
    "waveterm": ("csshx_latest.launchers.waveterm", "WaveTermLauncher"),
    "tmux": ("csshx_latest.launchers.tmux", "TmuxLauncher"),
    "iterm2": ("csshx_latest.launchers.iterm2", "ITerm2Launcher"),
    "terminal": ("csshx_latest.launchers.apple_terminal", "AppleTerminalLauncher"),
    "kitty": ("csshx_latest.launchers.kitty", "KittyLauncher"),
    "wezterm": ("csshx_latest.launchers.wezterm", "WezTermLauncher"),
    "manual": ("csshx_latest.launchers.manual", "ManualLauncher"),
}


def _by_name(name: str) -> Launcher:
    """Instantiate the launcher class registered under ``name``."""
    if name not in _LAUNCHERS:
        raise ValueError(f"unknown launcher: {name!r}")
    mod_name, cls_name = _LAUNCHERS[name]
    import importlib
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)()


def detect_launcher(name: Optional[str] = None) -> Launcher:
    """Return a Launcher instance.

    If ``name`` is given (and not ``"auto"``), use that launcher
    explicitly. Otherwise inspect environment variables in the priority
    order documented in the project README. Falls back to the Manual
    launcher if nothing is recognized — never silently picks tmux.
    """
    if name and name != "auto":
        return _by_name(name)

    term_program = os.environ.get("TERM_PROGRAM", "")

    if term_program == "waveterm" and shutil.which("wsh"):
        return _by_name("waveterm")
    if term_program == "iTerm.app":
        return _by_name("iterm2")
    if term_program == "Apple_Terminal":
        return _by_name("terminal")
    if os.environ.get("KITTY_PID") and shutil.which("kitty"):
        return _by_name("kitty")
    if term_program == "WezTerm" and shutil.which("wezterm"):
        return _by_name("wezterm")
    if os.environ.get("TMUX") and shutil.which("tmux"):
        return _by_name("tmux")
    return _by_name("manual")
