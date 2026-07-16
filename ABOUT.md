# TickAL - TickTick, without opening TickTick

One keyword `tal` (or a hotkey you set) opens your whole TickTick world in Alfred: browse, search, add, schedule, tag, complete, focus, periodic notes, CRM - every change mirrored instantly in a local cache.

📖 Full docs: [docs/00-index.md](docs/00-index.md) - or via the `tdo` keyword.

## Dependencies

- Alfred 5 + Powerpack · Python 3 (Homebrew or Xcode CLT - TickAL finds either)
- A TickTick account + a free TickTick developer app (2 minutes, steps below)
- Optional: PyObjC for the floating focus bar and clipboard-image attach - install from inside Alfred: `tup` → **Install PyObjC** (terminal variants in [docs/30-setup.md](docs/30-setup.md)) - focus works without it

## Setup

1. Go to [developer.ticktick.com/manage](https://developer.ticktick.com/manage) → **Create App** → set the redirect URI to `http://localhost:8080`
2. Paste the **Client ID** + **Client Secret** in Configure Workflow
3. Run `tlogin` - a browser opens; log in and approve
4. Run `tsy` to prime the cache - wait for the "Synced …" notification (enable Alfred notifications in System Settings if none shows)
5. *Optional but recommended* - one sign-in unlocks attachments, the Completed view, nested tags, your filters, auto-named folders and your TickTick tag order: `tup` → **Attachment Login** (masked; only a session token is stored) - or paste a token via **Attachment Token** (Sign-in-with-Apple; guide in [docs/30-setup.md](docs/30-setup.md))
6. *Optional* - CRM / CTA / Projects features: paste your list and folder ids in Configure Workflow (⌘⏎ on a list row → 🆔 Copy id; ⌥⌘⏎ on a folder row)

## Usage

Four keys run everything: **⌥⏎ browse · ⌘⏎ actions · ⌃⏎ back · `/` more**. Type to filter any screen.

| | |
|---|---|
| Core | `tal` main menu · `tse` search · `tad` add · `tup` settings · `tca` calendar |
| Views | `tod` today · `tom` tomorrow · `tne` next 7 days · `tin` inbox · `tsl` smart lists · `tfi` filters · `tta` tags · `tbu` buffer |
| Native views | `tha` habits · `tpo` pomodoro · `tmx` matrix · `tst` statistics |
| More | `tfo` focus · `tur` save browser tab · `tcr` crm · `tsy` sync · `tdo` docs |
| Periodic | `tpn` or `pn` scope in search · direct: `tdn` daily · `twn` weekly · `tmn` monthly · `tqn` quarterly · `tyn` yearly · `tmj`/`tej` journals · `tmo` income · `tdg` day goal · `tde` entry · `tat` add to today |

Add tokens: `*` date · `@` time · `!` priority · `#` tag · `=` note · `[[` task link - or type `/` for the menu.

All 35 keywords are re-mappable in Configure Workflow; hotkey nodes ship unbound (Alfred clears combos on import) - bind your own on the canvas.
