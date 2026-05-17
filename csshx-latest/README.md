# csshx-latest

A modern, terminal-agnostic cluster-SSH tool — a spiritual successor to
[csshX](https://github.com/brockgr/csshx) built on real PTYs and a
pluggable launcher layer instead of the old TIOCSTI keystroke-injection
hack.

Author: Aditya Kapadia.

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
  doesn't recognize the environment.
- **Stdlib-only Python 3.10+** — zero hard runtime dependencies.

## Install

```bash
cd csshx-latest/
uv venv && uv pip install -e '.[test]'
```

## Usage

```bash
csshx-latest web01 web02 web03
csshx-latest --launcher tmux web0{1..5}
csshx-latest --login deploy --ssh-args "-i ~/.ssh/cluster_key" host1 host2
csshx-latest --launcher manual host1 host2          # prints attach commands
csshx-latest --reconnect --strict web0{1..10}       # safer mode
csshx-latest production-cluster                     # uses ~/.csshrc alias
```

### CLI flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--launcher` | `auto` | Pick a backend: `auto`, `waveterm`, `tmux`, `iterm2`, `terminal`, `kitty`, `wezterm`, `manual`. |
| `--login` | (ssh default) | Username, forwarded as `-l`. |
| `--ssh-args` | `""` | Extra arguments forwarded to ssh (single quoted string). |
| `--max-hosts` | `16` | Refuse to start above this many hosts. Saves you from typo fork-bombs. |
| `--strict` | off | Abort if any host fails the tcp/22 preflight (default: warn and skip). |
| `--no-preflight` | off | Skip the tcp/22 reachability check entirely. |
| `--reconnect` | off | Re-spawn ssh with exponential backoff (1s, 2s, 4s, 8s, 16s) on slave death. |
| `--debug` | off | Verbose logging to stderr. |

## Cluster aliases

Two config sources, first-match wins:

1. `~/.config/csshx-latest/config.toml` (preferred):

   ```toml
   [clusters]
   web        = ["web01", "web02", "web03"]
   db         = "db1 db2"
   production = ["web", "db"]   # clusters can reference clusters
   ```

2. `~/.csshrc` (original csshX format):

   ```
   cluster web        = web01 web02 web03
   cluster db         = db1 db2
   cluster production = web db
   ```

Any token on the command line that matches a cluster name is expanded
recursively before brace expansion runs.

## Master TUI keys

| Key | Action |
| --- | --- |
| (any byte) | Broadcast to every enabled slave |
| `Ctrl-Q` | Quit |
| `Ctrl-T` then `b` | Toggle broadcast for ALL alive slaves |
| `Ctrl-T` then `1..9` | Toggle broadcast for that specific slave |
| `Ctrl-T` then `i`, digits, Enter | Toggle slave by index (for 10+ hosts) |
| `Ctrl-T` then `l` | List slaves and their state |
| `Ctrl-T` then `?` | Help |
| `Ctrl-T` then `Ctrl-T` | Send a literal Ctrl-T to slaves |

SIGINT / SIGTERM / SIGHUP also shut down cleanly. SIGWINCH on the
master propagates the new window size to every slave PTY via TIOCSWINSZ;
each individual block also reports its own resizes back through the
control socket.

## Architecture

```
   master process
   ----------------------------------------------------------------
   raw stdin --> Broadcaster --> Slave[1] PTY --> ssh host1
                                Slave[2] PTY --> ssh host2
                                Slave[N] PTY --> ssh hostN

   per slave:
       PTY master fd
       data socket   (0600, AUTH-gated)  -- bidirectional bytes
       control socket(0600, AUTH-gated)  -- WINSZ <rows> <cols> ...
       per-fd write_lock                  -- escape sequences stay whole

   per launcher:
       BlockHandle (backend, data{...})
       open_block / close_block / tile / set_title / start(total)
```

Output flows one way (PTY -> data socket -> terminal block). Input
arrives from two writers: the master broadcaster *and* whichever
terminal block is focused. A per-slave `asyncio.Lock` serializes PTY
writes so an escape sequence can never get torn between them.

Each socket is gated by a 32-byte hex token; clients have 2 seconds
to send `AUTH <token>\n` or they're dropped. Sockets live in
`$XDG_RUNTIME_DIR/csshx-<pid>/` (or `/tmp/csshx-<pid>/` on macOS),
with the directory at mode 0700 and each socket at 0600.

## Safety defaults

- **TCP-22 preflight**: every host gets a 1-second TCP probe before ssh
  forks. Unreachable hosts are warned & skipped (or aborted with
  `--strict`). No more screens full of timed-out panes when your VPN
  is down.
- **`StrictHostKeyChecking=accept-new`** is injected unless your
  `--ssh-args` already specifies a value. First-connect prompts no
  longer fan out across every broadcast slave.
- **`--max-hosts 16`** hard cap. Raise explicitly if you really need
  more.
- **Bounded reap**: on shutdown we send SIGTERM, poll-wait up to 2s,
  then SIGKILL. The master can never hang on a stuck ssh.

## Backend support matrix

| Backend | Open | Close | Tile | Title | Platform |
| --- | --- | --- | --- | --- | --- |
| WaveTerm | yes | yes | yes (best-effort) | yes | mac / linux / win |
| tmux | yes | yes | yes (`select-layout tiled`) | yes | anywhere with tmux |
| iTerm2 | yes | yes (by session id) | auto-balanced | yes | macOS |
| Terminal.app | yes | yes (by tty id) | manual | yes | macOS |
| Kitty | yes | yes | yes (`grid`) | yes | mac / linux |
| WezTerm | yes | yes | auto-balanced | yes | mac / linux / win |
| Manual | print only | n/a | n/a | n/a | anywhere |

Notes:

- **Kitty** requires `allow_remote_control yes` in `kitty.conf`.
- **WaveTerm** tiling tries `wsh setlayout tiled`, then `wsh layout
  tiled`, then `wsh tile` — it degrades quietly if the wsh CLI grammar
  drifts between releases.
- The orchestrator calls `launcher.tile()` after every spawn so panes
  stay balanced as blocks are added.

## What's different from the original csshX

| | csshX (Perl) | csshx-latest |
| --- | --- | --- |
| Keystroke delivery | TIOCSTI (deprecated/removed on modern systems) | Real PTYs |
| Terminal coupling | Hard-coded Terminal.app + iTerm | Pluggable Launcher protocol |
| Detection | macOS-only | macOS, Linux, WSL |
| Auth | None | 32-byte token per socket, constant-time compare |
| Per-slave typing | Hidden window per slave | Authenticated, bidirectional socket |
| Per-slave focus toggle | Action menu | `Ctrl-T <digit>` (or `Ctrl-T i` for 10+) |
| Connectivity preflight | Optional ping | Built-in concurrent tcp/22 probe |
| Reconnect | none | `--reconnect` with exponential backoff |
| Per-block SIGWINCH | n/a | Dedicated control socket per slave |
| Config | `~/.csshrc` only | TOML preferred, `.csshrc` fallback |

## Run the tests

```bash
uv run pytest -q
```

150+ tests cover the broadcaster, the AUTH handshake, the launcher
auto-detect matrix, every concrete launcher (subprocess mocked), the
TUI command mode (including per-slave focus toggle), the orchestrator's
preflight / kill-and-reap / max-hosts cap, the slave control socket's
WINSZ grammar, and a real-PTY round-trip integration test.

The package itself can't run on Windows — `pty`, `termios`, `tty`, and
`fcntl` are Unix-only.
