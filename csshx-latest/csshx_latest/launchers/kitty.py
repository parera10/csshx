"""Kitty launcher — uses ``kitty @`` remote control.

Requires ``allow_remote_control yes`` in ``kitty.conf`` (or the
equivalent ``--listen-on`` flag). The constructor surfaces a clear
error if the kitty CLI isn't on PATH; runtime failures from
``kitty @ launch`` are reported with kitty's own stderr included so
config issues are easy to diagnose.
"""
from __future__ import annotations

import shutil
import subprocess

from csshx_latest.launcher import BlockHandle


class KittyLauncher:
    """Open each block as a new kitty window. Tile via ``goto-layout grid``."""

    name = "kitty"

    def __init__(self) -> None:
        if not shutil.which("kitty"):
            raise RuntimeError(
                "kitty CLI not found on PATH. Install kitty and ensure "
                "'allow_remote_control yes' is set in kitty.conf."
            )

    @staticmethod
    def _run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(args, check=False, capture_output=capture, text=True)

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Spawn a new kitty window via ``kitty @ launch --type=window``."""
        out = self._run(
            ["kitty", "@", "launch", "--type=window", "--title", title, *attach_cmd],
            capture=True,
        )
        if out.returncode != 0:
            raise RuntimeError(
                "kitty @ launch failed — make sure 'allow_remote_control yes' "
                f"is set in kitty.conf. stderr: {(out.stderr or '').strip()}"
            )
        window_id = (out.stdout or "").strip()
        return BlockHandle(backend=self.name, data={"window_id": window_id, "title": title})

    def close_block(self, handle: BlockHandle) -> None:
        """Close the window via ``kitty @ close-window --match id:<wid>``."""
        wid = handle.data.get("window_id")
        if not wid:
            return
        self._run(["kitty", "@", "close-window", "--match", f"id:{wid}"])

    def tile(self, handles: list[BlockHandle]) -> None:
        """Switch the active tab to kitty's ``grid`` layout."""
        self._run(["kitty", "@", "goto-layout", "grid"])

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename the window via ``kitty @ set-window-title``."""
        wid = handle.data.get("window_id")
        if not wid:
            return
        self._run(["kitty", "@", "set-window-title", "--match", f"id:{wid}", title])
