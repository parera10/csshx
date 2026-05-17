"""iTerm2 launcher via ``osascript`` and iTerm's AppleScript dictionary.

Author: Aditya Kapadia.

The first block creates a new window using the default profile; each
subsequent block splits the current session vertically. Both forms
pass the attach command as the new session's ``command``, so iTerm
executes it directly via ``execvp`` and the user's interactive login
shell never runs. That sidesteps p10k / oh-my-zsh swallowing the
attach command's keystrokes.

Session ids returned by ``id of newSession`` are captured into
``BlockHandle.data`` so :meth:`close_block` can actually close the
pane on shutdown instead of leaving a dead socket sitting visible.
iTerm2 auto-balances split panes, so :meth:`tile` stays a no-op.
"""
from __future__ import annotations

import logging
import shlex
import subprocess

from csshx_latest.launcher import BlockHandle

log = logging.getLogger(__name__)


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

    def start(self, total: int) -> None:
        """No-op: iTerm2 split panes balance automatically."""

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Create or split-then-run -- running ``attach_cmd`` as the session's command."""
        cmd_str = " ".join(shlex.quote(a) for a in attach_cmd)
        cmd_esc = _escape(cmd_str)
        title_esc = _escape(title)

        if self._first:
            script = (
                'tell application "iTerm"\n'
                '  activate\n'
                '  set newWindow to (create window with default profile '
                f'  command "{cmd_esc}")\n'
                '  tell current session of newWindow\n'
                f'    set name to "{title_esc}"\n'
                '  end tell\n'
                '  return (id of newWindow) & "|" & (id of current session of newWindow)\n'
                'end tell\n'
            )
            self._first = False
        else:
            script = (
                'tell application "iTerm"\n'
                '  tell current session of current window\n'
                '    set newSession to (split vertically with default profile '
                f'    command "{cmd_esc}")\n'
                '  end tell\n'
                '  tell newSession\n'
                f'    set name to "{title_esc}"\n'
                '  end tell\n'
                '  return (id of current window) & "|" & (id of newSession)\n'
                'end tell\n'
            )
        result = _osascript(script)
        window_id, session_id = _parse_ids(result.stdout)
        if result.returncode != 0:
            log.warning("iTerm2 open_block exited %d: %s", result.returncode, result.stderr.strip())
        return BlockHandle(
            backend=self.name,
            data={"title": title, "window_id": window_id, "session_id": session_id},
        )

    def close_block(self, handle: BlockHandle) -> None:
        """Close the captured session id. No-op if iTerm2 didn't return one."""
        session_id = handle.data.get("session_id")
        if not session_id:
            return
        sid_esc = _escape(session_id)
        _osascript(
            'tell application "iTerm"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            '      repeat with s in sessions of t\n'
            f'        if id of s is "{sid_esc}" then close s\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
        )

    def tile(self, handles: list[BlockHandle]) -> None:
        """No-op: iTerm2 evenly balances split panes automatically."""

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename the captured session if we got an id."""
        session_id = handle.data.get("session_id")
        title_esc = _escape(title)
        if not session_id:
            _osascript(
                'tell application "iTerm" to tell current session of current window '
                f'to set name to "{title_esc}"'
            )
            return
        sid_esc = _escape(session_id)
        _osascript(
            'tell application "iTerm"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            '      repeat with s in sessions of t\n'
            f'        if id of s is "{sid_esc}" then set name of s to "{title_esc}"\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
        )


def _parse_ids(stdout: str) -> tuple[str, str]:
    """Parse ``"window_id|session_id"`` from osascript output."""
    if not stdout:
        return ("", "")
    line = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    if "|" not in line:
        return ("", "")
    win, _, sess = line.partition("|")
    return (win.strip(), sess.strip())
