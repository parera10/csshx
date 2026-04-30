"""iTerm2 launcher via ``osascript`` and iTerm's AppleScript dictionary.

The first block creates a new window with the default profile; each
subsequent block splits the current session vertically. iTerm2 auto-
balances split panes, so :meth:`tile` is a no-op.
"""
from __future__ import annotations

import shlex
import subprocess

from csshx_latest.launcher import BlockHandle


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


def _escape(s: str) -> str:
    """Escape backslashes and double-quotes for embedding in an AppleScript literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


class ITerm2Launcher:
    """Open each block as an iTerm2 split pane via AppleScript."""

    name = "iterm2"

    def __init__(self) -> None:
        self._first = True

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Create or split-then-write — running ``attach_cmd`` in the new session."""
        cmd_str = " ".join(shlex.quote(a) for a in attach_cmd)
        cmd_esc = _escape(cmd_str)
        title_esc = _escape(title)

        if self._first:
            script = (
                'tell application "iTerm"\n'
                '  activate\n'
                '  set newWindow to (create window with default profile)\n'
                '  tell current session of newWindow\n'
                f'    write text "{cmd_esc}"\n'
                f'    set name to "{title_esc}"\n'
                '  end tell\n'
                'end tell\n'
            )
            self._first = False
        else:
            script = (
                'tell application "iTerm"\n'
                '  tell current session of current window\n'
                '    set newSession to (split vertically with default profile)\n'
                '  end tell\n'
                '  tell newSession\n'
                f'    write text "{cmd_esc}"\n'
                f'    set name to "{title_esc}"\n'
                '  end tell\n'
                'end tell\n'
            )
        _osascript(script)
        return BlockHandle(backend=self.name, data={"title": title})

    def close_block(self, handle: BlockHandle) -> None:
        """No-op: iTerm2 sessions die when the user closes them or ssh exits."""

    def tile(self, handles: list[BlockHandle]) -> None:
        """No-op: iTerm2 evenly balances split panes automatically."""

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Best-effort rename of the current session."""
        title_esc = _escape(title)
        _osascript(
            'tell application "iTerm" to tell current session of current window '
            f'to set name to "{title_esc}"'
        )
