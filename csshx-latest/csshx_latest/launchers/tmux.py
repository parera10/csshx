"""Tmux launcher — spawn each block as a pane in the active session.

Detects the ambient ``$TMUX`` session via ``detect_launcher``; the
launcher itself just shells out to ``tmux``. Operates on whatever
window the spawned panes ended up in.
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Optional

from csshx_latest.launcher import BlockHandle


class TmuxLauncher:
    """Open each block as a tmux pane in the user's current session."""

    name = "tmux"

    def __init__(self, target: Optional[str] = None) -> None:
        self._target = target

    @staticmethod
    def _run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(args, check=False, capture_output=capture, text=True)

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Run ``tmux split-window`` to open a new pane running ``attach_cmd``."""
        cmd = ["tmux", "split-window", "-P", "-F", "#{pane_id}"]
        if self._target:
            cmd += ["-t", self._target]
        cmd.append(" ".join(shlex.quote(a) for a in attach_cmd))
        out = self._run(cmd, capture=True)
        pane_id = (out.stdout or "").strip()
        if title and pane_id:
            self._run(["tmux", "select-pane", "-t", pane_id, "-T", title])
        return BlockHandle(backend=self.name, data={"pane_id": pane_id, "title": title})

    def close_block(self, handle: BlockHandle) -> None:
        """Kill the pane opened for this block. Silent if already gone."""
        pane_id = handle.data.get("pane_id")
        if not pane_id:
            return
        self._run(["tmux", "kill-pane", "-t", pane_id])

    def tile(self, handles: list[BlockHandle]) -> None:
        """Apply ``tiled`` layout to whichever window holds the panes."""
        if not handles:
            return
        first = handles[0].data.get("pane_id")
        if not first:
            return
        self._run(["tmux", "select-layout", "-t", first, "tiled"])

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename a pane via ``tmux select-pane -T``."""
        pane_id = handle.data.get("pane_id")
        if not pane_id:
            return
        self._run(["tmux", "select-pane", "-t", pane_id, "-T", title])
