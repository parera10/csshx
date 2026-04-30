"""Command-line entry point for ``csshx-latest``."""
from __future__ import annotations

import argparse
import asyncio
import shlex
import sys
from typing import Optional

from csshx_latest.launcher import detect_launcher
from csshx_latest.master import run_master


def main(argv: Optional[list[str]] = None) -> int:
    """Parse args and run the master event loop. Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="csshx-latest",
        description="Modern, terminal-agnostic cluster-SSH (csshX rewrite).",
    )
    parser.add_argument("hosts", nargs="+", help="Hosts to ssh to.")
    parser.add_argument(
        "--ssh-args",
        default="",
        help="Extra arguments forwarded to ssh, as a single quoted string.",
    )
    parser.add_argument("--login", default=None, help="Username (passed to ssh -l).")
    parser.add_argument(
        "--launcher",
        default="auto",
        choices=["auto", "waveterm", "tmux", "iterm2", "terminal", "kitty", "wezterm", "manual"],
        help="Terminal backend (default: auto-detect).",
    )
    args = parser.parse_args(argv)

    launcher = detect_launcher(args.launcher)
    ssh_extra = shlex.split(args.ssh_args) if args.ssh_args else []

    try:
        return asyncio.run(run_master(args.hosts, ssh_extra, args.login, launcher))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
