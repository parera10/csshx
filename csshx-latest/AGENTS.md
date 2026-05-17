# AGENTS.md

Guide for any contributor (human or AI agent) picking up `csshx-latest`.

Author: Aditya Kapadia.

---

## Project at a glance

A modern, terminal-agnostic cluster-SSH tool — a rewrite of the Perl
[csshX](https://github.com/brockgr/csshx). Async Python 3.10+, stdlib
only (no runtime deps), real PTYs, pluggable terminal launchers, token-
authenticated UNIX sockets.

**Status:** v0.2.0 Beta. 150 tests passing in ~1.1s. Safe for daily use
on trusted networks with up to 16 hosts (raise `--max-hosts` for more).

```
csshx_latest/
├── __main__.py        CLI entry, argparse
├── orchestrator.py    Top-level run loop, preflight, reap, reconnect
├── master.py          Back-compat shim re-exporting orchestrator names
├── slave.py           One ssh subprocess + PTY + data/control sockets
├── broadcaster.py     Routes master keystrokes to enabled slaves
├── tui.py             Raw-mode stdin reader + Ctrl-T command mode
├── auth.py            32-byte hex token + AUTH handshake
├── attach.py          Stdlib attach client (run by spawned blocks)
├── terminal.py        raw-mode CM, winsize ioctls, xterm.js mode resets
├── hosts.py           Brace expansion + cluster alias resolution
├── config.py          ~/.config/csshx-latest/config.toml or ~/.csshrc
├── launcher.py        Launcher Protocol + auto-detect
├── logging_setup.py   stderr formatter
└── launchers/         One file per backend
    ├── waveterm.py
    ├── tmux.py
    ├── iterm2.py
    ├── apple_terminal.py
    ├── kitty.py
    ├── wezterm.py
    └── manual.py
```

---

## Conventions

- **Authorship:** every module starts with `Author: Aditya Kapadia.` in
  the docstring. New modules follow the same pattern.
- **No AI / process narration** in comments. Comments explain *why*, not
  *what changed*.
- **Files stay under 600 LOC.** Current largest is `orchestrator.py` at
  ~365. Split before crossing 600.
- **Zen of Python.** Flat over nested; explicit over implicit; one
  obvious way to do it.
- **Stdlib only at runtime.** Tests may use pytest; nothing else.
- **All sync subprocess calls run through `asyncio.to_thread`** when
  invoked from the event loop (osascript, tmux, wsh can block 100ms+).

### Test layout

- `tests/test_<unit>.py` — pure unit tests with mocked subprocess.
- `tests/test_slave_bridge.py` — pipe-pair smoke tests of the bridge.
- `tests/test_slave_control_socket.py` — real PTY + control socket.
- `tests/test_integration_pty.py` — real PTY + fork + cat as fake ssh.
- `tests/conftest.py` — shared fixtures (`short_socket_dir`,
  `harmless_pid`, `stdio_devnull`).

Run: `uv run pytest -q`. Target: <2 seconds wall-clock.

---

## DONE in v0.2.0

### Critical fixes (production safety)

| ID | What | Where |
| --- | --- | --- |
| C1 | Bounded reap with SIGKILL fallback (no more hang on shutdown) | `orchestrator._kill_and_reap` |
| C2 | `StrictHostKeyChecking=accept-new` injected unless user overrode | `orchestrator.maybe_inject_strict_host_key_opts` |
| C3 | `--max-hosts 16` cap to prevent fork-bomb typos | `orchestrator.run_master` + `__main__` |
| C4 | Broadcaster logs per-slave write failures (no more silent drops) | `broadcaster.broadcast` |
| C5 | WaveTerm export parser uses `shlex.split` (all quote forms safe) | `launchers.waveterm._parse_bash_exports` |

### Must-have features

| ID | What | Where |
| --- | --- | --- |
| M1 | Per-slave focus toggle: `Ctrl-T 1..9` direct, `Ctrl-T i <num>` prompt | `tui._handle_command_byte`, `tui._consume_index_prompt_byte` |
| M2 | iTerm2 + Terminal.app actually close panes on shutdown (track ids) | `launchers.iterm2`, `launchers.apple_terminal` |
| M3 | `Launcher.start(total)` lifecycle hook replaces env smuggle | `launcher.Launcher`, every concrete launcher |
| M4 | TOML or `~/.csshrc` cluster aliases (recursive, cycle-safe) | `config.py` + `hosts.expand_hosts` |
| M5 | Concurrent tcp/22 preflight, `--strict` and `--no-preflight` flags | `orchestrator.preflight_hosts` |
| M6 | Per-block SIGWINCH via dedicated control socket (`WINSZ rows cols`) | `slave._apply_control_line`, `attach._push_winsize` |
| M7 | Real-PTY integration test with cat as fake ssh | `tests/test_integration_pty.py` |
| M8 | `--reconnect` with exponential backoff (1, 2, 4, 8, 16 s) | `orchestrator._attempt_reconnect` |

### Extras delivered along the way

- Alphabetic brace expansion: `host-{a..c}`.
- Tile-after-every-spawn so panes stay balanced as blocks are added.
- Stdlib attach client is now the default (socat couldn't handle the
  dual data + control socket protocol).
- Always-on per-master SIGWINCH propagation was already there; now
  joined by per-block SIGWINCH via the control socket.
- `pyproject.toml` bumped to `0.2.0`, status `4 - Beta`, author Aditya.
- README rewritten with the new flag table, cluster examples, and key
  bindings.

### Test coverage delta

| | Before | After |
| --- | --- | --- |
| Test files | 16 | 21 |
| Tests | 111 | 150 |
| Wall clock | 0.45s | 1.10s |

New test modules: `test_config.py`, `test_orchestrator.py`,
`test_tui_focus_toggle.py`, `test_slave_control_socket.py`,
`test_integration_pty.py`, `test_waveterm_export_parser.py`.

---

## PENDING (Good-to-have, in priority order)

None of these block daily use. Pick the top one when you next sit down
with the project.

### High value

1. **Color blocks by state (`set_color` hook).** `BlockHandle.data`
   reserves the field; no launcher wires it. Dim disabled, red dead,
   green enabled would be a huge visual aid. Start with WaveTerm (`wsh
   setbg` or similar) and tmux (`select-pane -P`). 60-90 LOC.

2. **Action mode: `--action 'uptime' host1 host2`.** One-shot command
   broadcast, capture stdout per host, print a summary table, exit. No
   TUI. Useful for ops scripts. Original csshX had this. ~120 LOC.

3. **Backend conformance test harness.** Parametrized
   `@pytest.fixture(params=[KittyLauncher, TmuxLauncher, ...])` that
   verifies each launcher honors the Protocol contract uniformly
   (open returns non-empty handle, close uses that handle's data, etc).
   Catches drift cheaply.

4. **Bound `connected_writers` per slave.** Currently unbounded after
   AUTH; add a max-attaches cap (e.g. 4) so a leaked token can't fan
   out infinitely.

### Medium value

5. **Lower Python floor to 3.9 OR adopt 3.11+ `TaskGroup`.** Currently
   declares `>=3.10` but uses no 3.10-only feature. Either widen the
   install base (3.9) or actually use TaskGroup for parallel slave
   spawn (would parallelize the ~50ms-per-host launcher round-trips).

6. **Action menu help discoverability.** `_render_help` lists keys but
   users have to enter command mode to see it. Print a one-line hint
   on startup ("press Ctrl-T then ? for menu").

7. **Slave-status colors in the master status footer.** Today
   `render_status` writes `hosts: 3  enabled: 2  dead: 1` in plain
   text. ANSI-color the dead count red, enabled count green; users
   spot dead hosts faster.

8. **Configurable command-mode prefix.** Today `Ctrl-T` is hardcoded.
   Some users have `Ctrl-T` bound elsewhere (jed, emacs). Add
   `--command-key Ctrl-B` (or read from config).

9. **`_handle_command_byte` swallows unknown bytes silently.** The
   docstring documents "any other key cancels" but the user types a
   letter and it vanishes. Friendlier: echo the cancelled byte after
   exiting command mode.

### Low value / polish

10. **`master.py` shim.** Still a 28-line re-export. Either delete with
    a CHANGELOG note ("import from `csshx_latest.orchestrator`") or
    stop apologizing for it.

11. **`[project.urls]` in pyproject.toml.** Homepage / repo / issue
    tracker links. Standard hygiene.

12. **`_temporary_umask` thread-safety note.** Today it's only called
    on the event loop during single-threaded setup, so safe. If
    `asyncio.to_thread` launchers ever use it, add a lock. Currently
    has a comment to that effect; consider asserting it instead.

13. **WaveTerm `wsh token` JSON output.** When/if WaveTerm exposes a
    JSON variant of `wsh token`, switch to it from `shlex.split` of
    the bash output. Less brittle.

14. **Improve `--reconnect` UX.** Today it writes a one-liner to
    stderr. Could also re-set the block title to indicate
    "reconnecting...", clear scrollback or insert a divider, etc.

15. **Document the `WINSZ` control protocol** in `slave.py`'s
    module docstring so future protocol extensions have a precedent
    (e.g. `BELL`, `FOCUS`, `RESIZE`).

---

## Architecture notes (for future spelunkers)

### Two sockets per slave

Each slave exposes two AUTH-gated UNIX sockets:

- `slave-N.sock` (data): bidirectional bytes. PTY output fans out;
  client keystrokes flow in.
- `slave-N.ctl` (control): line-oriented. Today only `WINSZ rows cols
  [xpixel ypixel]`. Future: `BELL`, `FOCUS`, etc.

The stdlib attach client opens both; socat-based attach is no longer
supported because it can't multiplex two sockets cleanly.

### Why an `asyncio.Lock` per slave

The master broadcaster AND the focused block can both write into the
same PTY simultaneously. Without a per-slave `write_lock`, an ANSI
escape sequence from the broadcaster could interleave with a keystroke
from the block, producing garbage on the remote shell. The lock makes
each write atomic at the PTY level.

### Why a `state_lock` separately

The PTY reader task does *three* things every iteration: extend
scrollback, snapshot the current writers, and queue the chunk to each.
The `state_lock` makes those atomic with respect to a new client
authenticating and joining the writer list, so we can never duplicate
or drop a chunk.

### Reconnect path

`on_dead` callback fires from inside the PTY reader task when ssh
exits. With `--reconnect`, it schedules `_attempt_reconnect` on the
loop via `run_coroutine_threadsafe`. That coroutine:

1. Sleeps for the next backoff value.
2. Re-probes tcp/22.
3. Re-spawns `ssh` with the SAME token and socket paths.
4. Rebinds `slave.pty_master` and `slave.pid`, clears `dead`.
5. Re-runs the bridge.

The visible block keeps its socket connection — it never noticed the
underlying ssh died. The token file is re-written to the same path
(in case the file unlink was racy).

### Tile after every spawn

The orchestrator calls `launcher.tile(handles)` after every
`open_block`, not just once at the end. Without this, tmux's
default split halves the most-recent pane, producing visibly lopsided
layouts during launch.

---

## Common tasks

### Add a new terminal backend

1. New file under `csshx_latest/launchers/your_backend.py`.
2. Implement: `name`, `start(total)`, `open_block(cmd, title)`,
   `close_block(handle)`, `tile(handles)`, `set_title(handle, title)`.
3. Register in `launcher._LAUNCHERS`. The CLI choice list updates
   automatically.
4. Add auto-detect rule in `launcher.detect_launcher` if your backend
   sets a recognizable env var.
5. Tests: copy any existing `tests/test_launcher_*.py` and adapt.

### Add a new control-socket command

1. Extend the grammar comment in `slave._apply_control_line`.
2. Parse the new command in that function; ignore unknown commands
   silently so older attach clients don't break newer slaves.
3. If the command needs to flow from the attach client, add a tiny
   sender in `attach.py` (see `_push_winsize` for a template).

### Add a new TUI command-mode key

1. Add the dispatch in `tui._handle_command_byte`.
2. If your new command needs follow-up input (like the `i` index
   prompt), extend `_CommandState` and add a per-byte handler.
3. Update the help in `_render_help`.
4. Add a test in `tests/test_tui_focus_toggle.py` (or a sibling file).

---

## What this project will NEVER do

- **Run on Windows.** `pty`, `termios`, `tty`, `fcntl` are Unix-only.
  Windows users use WSL.
- **Re-introduce TIOCSTI.** It's deprecated, removed in newer kernels,
  and a known privilege-escalation vector.
- **Auto-spawn a multiplexer.** `detect_launcher` falls back to
  `manual` (which just prints attach commands) rather than starting
  tmux/screen behind your back.
- **Embed the AUTH token in argv.** Always read from a `0600` file
  inside a `0700` directory so `ps` can't leak it.
- **Cache or persist credentials.** Tokens are per-run, generated
  fresh, never written outside the run's socket dir.
