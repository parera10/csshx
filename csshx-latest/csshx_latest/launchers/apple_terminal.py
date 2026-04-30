"""Apple Terminal.app launcher via ``osascript``.

Terminal.app has no built-in tiling and AppleScript can't reliably
position windows from outside, so :meth:`tile` is a no-op — the user
arranges the windows themselves.
"""
from __future__ import annotations

import shlex
import subprocess

from csshx_latest.launcher import BlockHandle


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class AppleTerminalLauncher:
    """Open each block as a new Terminal.app window."""

    name = "terminal"

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Tell Terminal.app to ``do script`` with the attach command."""
        cmd_esc = _escape(" ".join(shlex.quote(a) for a in attach_cmd))
        title_esc = _escape(title)
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  set newTab to do script "{cmd_esc}"\n'
            f'  set custom title of newTab to "{title_esc}"\n'
            'end tell\n'
        )
        subprocess.run(
            ["osascript", "-e", script], check=False, capture_output=True, text=True
        )
        return BlockHandle(backend=self.name, data={"title": title})

    def close_block(self, handle: BlockHandle) -> None:
        """No-op: tabs close when the user closes them or ssh exits."""

    def tile(self, handles: list[BlockHandle]) -> None:
        """No-op: Terminal.app has no programmatic tiling."""

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """No-op: we don't track tab references after creation."""
