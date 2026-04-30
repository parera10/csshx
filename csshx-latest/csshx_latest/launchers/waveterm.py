"""WaveTerm launcher — opens and tiles blocks via the ``wsh`` CLI.

The wsh subcommand grammar has changed across WaveTerm versions, so
:meth:`tile` tries a few likely incantations in order and stops at the
first one that exits 0.
"""
from __future__ import annotations

import subprocess

from csshx_latest.launcher import BlockHandle


class WaveTermLauncher:
    """Open each block via ``wsh run`` and tile via the closest available subcommand."""

    name = "waveterm"

    def __init__(self) -> None:
        self._counter = 0

    @staticmethod
    def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
        # capture=True by default so legacy wsh probes (setlayout/layout/tile,
        # deleteblock, settitle) don't spam the user's terminal on modern wsh
        # builds where those subcommands have been renamed or removed.
        return subprocess.run(args, check=False, capture_output=capture, text=True)

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Spawn a new Wave block running ``attach_cmd``."""
        self._counter += 1
        out = self._run(["wsh", "run", "--", *attach_cmd], capture=True)
        block_id = ""
        if out.stdout:
            tail = out.stdout.strip().splitlines()
            if tail:
                block_id = tail[-1]
        return BlockHandle(
            backend=self.name,
            data={"block_id": block_id, "title": title, "index": self._counter},
        )

    def close_block(self, handle: BlockHandle) -> None:
        """Delete the block (no-op if we never captured an id)."""
        block_id = handle.data.get("block_id")
        if not block_id:
            return
        self._run(["wsh", "deleteblock", "-b", block_id])

    def tile(self, handles: list[BlockHandle]) -> None:
        """Try several ``wsh`` layout subcommands; keep the first that succeeds."""
        for attempt in (
            ["wsh", "setlayout", "tiled"],
            ["wsh", "layout", "tiled"],
            ["wsh", "tile"],
        ):
            r = self._run(attempt)
            if r.returncode == 0:
                return

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename a block via ``wsh settitle``."""
        block_id = handle.data.get("block_id")
        if not block_id:
            return
        self._run(["wsh", "settitle", "-b", block_id, title])
