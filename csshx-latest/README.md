# csshx-latest

A modern, terminal-agnostic cluster-SSH tool — a spiritual successor to
[csshX](https://github.com/brockgr/csshx) built on real PTYs and a
pluggable launcher layer instead of the old TIOCSTI keystroke-injection
hack.

## What it is

- **N terminal blocks** — one per SSH host. Click a block and type to
  send keystrokes to just that host.
- **1 master TUI** — runs in your current terminal. Every keystroke is
  broadcast to every enabled slave at once.
- **PTY end-to-end** — no TIOCSTI, works on modern macOS/Linux.
- **Pluggable backends** — WaveTerm, tmux, iTerm2, Terminal.app, Kitty,
  WezTerm, plus a `manual` fallback that works in any terminal by
  printing attach commands for you to paste.
- **Auto-detect** which terminal you're in. Falls back to manual if it
  doesn't recognize the environment — no surprise tmux sessions.
- **Stdlib-only Python 3.10+** — zero hard runtime dependencies.

## Install

From a checkout of this repo:

```bash
cd csshx-latest/

# with uv
uv venv && uv pip install -e '.[test]'

# or plain pip
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
```

## Usage

```bash
csshx-latest web01 web02 web03
csshx-latest --launcher tmux web0{1..5}
csshx-latest --login deploy --ssh-args "-i ~/.ssh/cluster_key" host1 host2
csshx-latest --launcher manual host1 host2   # prints attach commands
```

`--launcher` choices: `auto` (default), `waveterm`, `tmux`, `iterm2`,
`terminal`, `kitty`, `wezterm`, `manual`.

Press **Ctrl-Q** in the master TUI to exit. SIGINT / SIGTERM / SIGHUP
also shut down cleanly. SIGWINCH on the master propagates the new
window size to every slave PTY via TIOCSWINSZ.

## Architecture

```
   ┌────────────────────────── master process ──────────────────────────┐
   │                                                                    │
   │   raw stdin ──► Broadcaster ─┬─► Slave[1] PTY ─► ssh host1         │
   │   (your tty)                 ├─► Slave[2] PTY ─► ssh host2         │
   │                              └─► Slave[N] PTY ─► ssh hostN         │
   │                                                                    │
   │   per slave:                                                       │
   │     PTY master fd  ──►  UNIX socket (0600 + AUTH token)            │
   │                              ▲                                     │
   │                              │ bidirectional, per-fd write lock    │
   │                              ▼                                     │
   │                   Launcher.open_block(attach_cmd, host)            │
   │                              │                                     │
   │             ┌────────────────┴─────────────────┐                   │
   │             │  whichever backend you have:     │                   │
   │             │  waveterm / tmux / iterm2 / ...  │                   │
   │             │  (or `manual`: print and paste)  │                   │
   │             └──────────────────────────────────┘                   │
   └────────────────────────────────────────────────────────────────────┘
```

Output flows one way (PTY → socket → terminal block). Input arrives
from two writers: the master broadcaster *and* whichever terminal block
is focused. A per-slave `asyncio.Lock` serializes PTY writes so an
escape sequence can never get torn between them.

Each slave socket is gated by a 32-byte hex token; clients have 2
seconds to send `AUTH <token>\n` or they're dropped. Sockets live in
`$XDG_RUNTIME_DIR/csshx-<pid>/` (or `/tmp/csshx-<pid>/` on macOS), with
the directory at mode 0700 and each socket at 0600.

## Backend support matrix

| Backend       | Open block | Tile             | Set title | Set color | Platform           |
| ------------- | ---------- | ---------------- | --------- | --------- | ------------------ |
| WaveTerm      | yes        | yes (best-effort)| yes       | n/a (v2)  | mac / linux / win  |
| tmux          | yes        | yes              | yes       | partial   | anywhere with tmux |
| iTerm2        | yes        | auto-balanced    | yes       | n/a (v2)  | macOS              |
| Terminal.app  | yes        | manual           | yes       | n/a (v2)  | macOS              |
| Kitty         | yes        | yes (`grid`)     | yes       | n/a (v2)  | mac / linux        |
| WezTerm       | yes        | auto-balanced    | yes       | n/a (v2)  | mac / linux / win  |
| Manual        | print only | n/a              | n/a       | n/a       | anywhere           |

Notes:

- **Kitty** requires `allow_remote_control yes` in `kitty.conf`. The
  launcher surfaces a clear error if it's not enabled.
- **WaveTerm** tiling tries `wsh setlayout tiled`, then `wsh layout
  tiled`, then `wsh tile` — it degrades quietly if the wsh CLI grammar
  drifts between releases.
- **Set color** is a v2 hook reserved on `BlockHandle.data`; none of
  the v1 launchers wire it up.

## What's different from the original csshX

| | csshX (Perl) | csshx-latest |
|-|-|-|
| Keystroke delivery | TIOCSTI (deprecated/removed on modern systems) | Real PTYs |
| Terminal coupling | Hard-coded Terminal.app + iTerm | Pluggable Launcher protocol |
| Detection | macOS-only | macOS, Linux, WSL |
| Auth | None — anyone local could sniff a slave | 32-byte token per socket |
| Per-slave typing | Hidden window per slave | Authenticated, bidirectional socket |
| Globals | ~6 file-level `my` vars | Zero |
| Lazy module loading | `eval "use $mod"` | `importlib.import_module` |
| Key handler | Giant if/elsif chain | Future v2 dispatch dict |

## Run the tests

```bash
uv run pytest -q
# or
pytest -q
```

The test suite exercises the broadcaster routing logic (with real
pipes), the AUTH handshake (with a `StreamReader`), the
launcher-detection environment matrix, and the Manual / Tmux /
WaveTerm launchers (with `subprocess.run` mocked).

The package itself can't run on Windows — `pty`, `termios`, `tty`, and
`fcntl` are Unix-only. The tests assume a Unix-like host.

## v1 scope

In: spawn N ssh PTYs, broadcast keystrokes, all six concrete launchers
plus the manual fallback, clean shutdown, SIGWINCH propagation, socket
auth.

Out (designed to slot in later): action mode, `.csshrc` parsing,
per-slave focus toggling commands from the master TUI, ping pre-test,
color themes per slave.
