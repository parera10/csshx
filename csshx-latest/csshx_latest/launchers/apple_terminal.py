"""Apple Terminal.app launcher via ``osascript``.

Author: Aditya Kapadia.

Terminal.app's only AppleScript hook for launching commands is
``do script``, which feeds the typed text into the new tab's login
shell. With Powerlevel10k as the user's default shell, the long
.zshrc + instant-prompt initialization can swallow / reorder the
attach command's keystrokes. To avoid that, we prefix the attach
command with ``exec /bin/sh -c '...'`` -- zsh's first parsed line
exec-replaces itself with ``/bin/sh`` running our command, so the
prompt never gets a chance to render and no shell init code runs.

The id of the spawned ``tty`` is captured into ``BlockHandle.data``
so :meth:`close_block` can close the tab on shutdown instead of
leaving the user to ``cmd-W`` every dead pane manually.

Terminal.app has no built-in tiling and AppleScript can't reliably
position windows from outside, so :meth:`tile` is a no-op.
"""
from __future__ import annotations

import logging
import shlex
import subprocess

from csshx_latest.launcher import BlockHandle

log = logging.getLogger(__name__)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


class AppleTerminalLauncher:
    """Open each block as a new Terminal.app tab via ``do script``."""

    name = "terminal"

    def start(self, total: int) -> None:
        """No-op: Terminal.app has no programmatic tiling."""

    def open_block(self, attach_cmd: list[str], title: str) -> BlockHandle:
        """Tell Terminal.app to ``do script`` with the attach command."""
        cmd_str = " ".join(shlex.quote(a) for a in attach_cmd)
        wrapped = f"exec /bin/sh -c {shlex.quote(cmd_str)}"
        cmd_esc = _escape(wrapped)
        title_esc = _escape(title)
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  set newTab to do script "{cmd_esc}"\n'
            f'  set custom title of newTab to "{title_esc}"\n'
            '  return tty of newTab\n'
            'end tell\n'
        )
        result = _osascript(script)
        tty_id = (result.stdout or "").strip().splitlines()[-1].strip() if result.stdout else ""
        if result.returncode != 0:
            log.warning("Terminal.app open_block exited %d: %s", result.returncode, result.stderr.strip())
        return BlockHandle(backend=self.name, data={"title": title, "tty": tty_id})

    def close_block(self, handle: BlockHandle) -> None:
        """Close the tab whose tty matches the captured id."""
        tty_id = handle.data.get("tty")
        if not tty_id:
            return
        tty_esc = _escape(tty_id)
        _osascript(
            'tell application "Terminal"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            f'      if tty of t is "{tty_esc}" then close t\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
        )

    def tile(self, handles: list[BlockHandle]) -> None:
        """No-op: Terminal.app has no programmatic tiling."""

    def set_title(self, handle: BlockHandle, title: str) -> None:
        """Rename the tab matched by tty id."""
        tty_id = handle.data.get("tty")
        if not tty_id:
            return
        tty_esc = _escape(tty_id)
        title_esc = _escape(title)
        _osascript(
            'tell application "Terminal"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            f'      if tty of t is "{tty_esc}" then set custom title of t to "{title_esc}"\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
        )
