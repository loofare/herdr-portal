# herdr-portal

**English** · [简体中文](README.zh-CN.md)

![HERDR Portal — cover built from real, redacted UI](assets/banner.png)

**Mission control for every Herdr agent.** One plugin aggregates every workspace / tab / pane in your Herdr session into a single live board, in two forms:

- **TUI board** — press **`Ctrl+B` then `A`**: three agent columns plus a separate window view, `Enter` lands you in the session
- **Web big-screen** — press **`Ctrl+B` then `Shift+A`**: four themes (command / neon / light / dark), structured progress, click a card to focus Herdr and raise its terminal, reply to an agent from the browser, recent output rendered as Markdown

![herdr 0.7+](https://img.shields.io/badge/herdr-0.7%2B-8a2be2) ![platforms](https://img.shields.io/badge/platforms-macOS%20%E2%80%A2%20Linux-informational) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.9%2B-orange)

## Why `Ctrl+B` `A` is the way to use it

The TUI opens as a Herdr popup pane, so the whole round trip is two keystrokes and never leaves the keyboard:

```
Ctrl+B  A        board opens over your current pane
↑ ↓ ← →          pick the agent that needs you (or just click it)
Enter            jump to that pane — the board closes itself on the way out
```

No window switching, no mouse hunt, no "which tab was that agent in again". `Ctrl+B` is Herdr's prefix, `A` is the board, and `Shift+A` is the same board as a web dashboard. Because the board closes the instant it jumps, the gesture is one motion instead of a mode you have to exit.

## Preview

**Web board** (default *command* theme): left command rail, system status bar, red/blue/green status columns, terminal status strip. The "waiting" column hides itself when nothing is blocked.

![web board](assets/web-board.png)

**Reply from the web**: click a card to focus Herdr, click `↩` on the card to expand the reply area — an input box plus that agent's recent output, rendered as Markdown and following live.

![web reply](assets/web-reply.png)

**Window view**: plain SSH / shell terminals live in their own view instead of crowding the agent board.

![web windows](assets/web-windows.png)

**TUI board** (real curses render, redacted demo data): nothing is blocked here, so the board collapses to two columns — *running* and *ready* — while keeping the real selection state, detail bar, and key hints.

![tui board](assets/tui-board.png)

## Features

- **Every agent state in one place** — waiting / running / idle / done, plus plain windows
- **Agent detection** — PI, OMP, Claude, Codex and 20+ others
- **Structured live progress** — current phase (running a command / editing code / waiting on a subtask / waiting for you…) plus the execution title, tool type, and last-active time
- **Dynamic waiting column** — zero footprint until an agent stops for you (approval or question), then it appears first and blinks in the header counters
- **Click to land** — web or TUI, clicking a card switches Herdr to that workspace/tab/pane and raises the terminal window that hosts Herdr (Ghostty, iTerm2, Terminal, kitty, Alacritty, WezTerm… all detected)
- **Keyboard *and* mouse in the TUI** — full keyboard control, plus click to select, click again (or double-click) to jump, click a column to switch to it
- **Reply to an agent from the web** — text goes straight to that agent's terminal (`agent prompt` when idle, simulated keystrokes while it runs), multi-line paste included
- **Sturdy** — the web service runs independently of Herdr (closing the popup does not drop it), reconnects while keeping the last data, preserves scroll position, and skips redraws with a data fingerprint

## Quick start

```bash
herdr plugin install loofare/herdr-portal
```

Then bind the keys in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+a"            # Ctrl+B then A
type = "plugin_action"
command = "herdr-portal.open-board"
description = "open global board TUI"

[[keys.command]]
key = "prefix+shift+a"      # Ctrl+B then Shift+A
type = "plugin_action"
command = "herdr-portal.open-web"
description = "open web portal"
```

Finish with `herdr server reload-config` and press **`Ctrl+B` `A`**.

> `prefix` is Herdr's prefix key, `Ctrl+B` by default. If you remapped it, substitute your own prefix — the plugin only cares about the `+a` half.

## TUI guide

**`Ctrl+B` `A`** opens the **agent board** (three columns):

- **Dynamic columns** — with nothing blocked you get *running* and *ready*; the moment an agent stops for you, the waiting column appears and takes first place
- **Virtual scrollbar** — a column with more cards than fit grows a colored scrollbar whose thumb size and position track the list
- **Structured cards** — badge/workspace → title → `▸ phase · execution title` → status/tool/pane id
- **Detail bar** (when the terminal is tall enough) — current phase, execution title, location path, recent output digest
- **`Enter` lands** — jumps to the pane and **closes the board immediately**, leaving the session you aimed at in front of you; on failure the board stays and tells you why
- **Window view** — `Tab` or `v` switches to the SSH/shell grid, press again to switch back

### Mouse

The TUI is keyboard-first but never keyboard-only:

| Gesture | Effect |
| --- | --- |
| Click a card | Select it (instant detail bar update) |
| Click the selected card again, or double-click any card | Jump to that pane and close the board |
| Click a column's empty area | Make that column active |
| Anything else | Keyboard shortcuts below, unchanged |

Mouse reporting degrades silently: on a terminal or ncurses build without it, every key still works. The scroll wheel is deliberately not bound — macOS ships ncurses 5.7, which reports wheel-down and pointer motion on the same bit, so binding it would scroll the board whenever the pointer moved.

## Key reference

### TUI

| Key | Action |
| --- | --- |
| `↑ ↓ ← →` / `hjkl` | Move between cards / columns |
| `Enter` | Jump to the pane and close the board |
| `Tab` / `v` | Agent board ↔ window view |
| `1-3` | Jump straight to a column |
| `r` | Refresh now |
| `q` / `Esc` | Close the board |

### Web

| Action | Effect |
| --- | --- |
| Click a card | Focus Herdr on that pane and raise the terminal window |
| Click `↩` on a card | Expand the reply area (input box + recent output) |
| `Enter` / `Shift+Enter` / `Esc` | Send / newline / collapse the reply area |
| Bottom-left *light / dark / neon / command* | Switch theme (command by default, choice remembered) |
| *Board / Workspaces / Windows* | Switch view |

## Use cases

- **Watching parallel projects** — several agents running in different workspaces; the board shows who is working and who is waiting, and one keystroke or click puts you there
- **Approving and replying remotely** — when an agent blocks on a permission or a question, the waiting column pops up and you can answer from the web input without going back to the terminal
- **Big-screen supervision** — park the web board on a second display or tablet; progress scrolls live and the workspace view groups by project
- **Window overview** — SSH sessions and log tails stay in the window view instead of mixing with agent state

## Environment variables

| Variable | Effect |
| --- | --- |
| `HERDR_PORTAL_PORT` | Web port (default 8787) |
| `HERDR_PORTAL_NO_FRONT=1` | Do not raise the terminal window when a card is clicked |

Service control: `python3 board/daemon.py start|stop|restart|status` (the plugin starts the web service on demand; logs live in `~/.local/state/herdr-portal/server.log`).

## Local development

```bash
herdr plugin link /path/to/herdr-portal
herdr server reload-config
```

Layout:

```
board/
  tui.py          # curses TUI board (keyboard + mouse)
  collect.py      # collects herdr snapshots + parses sessions
  server.py       # local web service
  daemon.py       # service supervisor (runs detached from the Herdr popup)
  web/            # web frontend (vanilla JS, zero dependencies)
scripts/
  open-board.sh   # open the TUI (plugin pane overlay)
  open-web.sh     # start the web service and open/reuse a browser tab
```

## Requirements

- herdr 0.7+
- Python 3.9+ (bundled on macOS, install it on Linux)
- A browser for the web big-screen (Chrome / Safari / Edge all fine)

## License

[MIT](LICENSE)
