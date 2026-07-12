# TickAL — TickTick, without opening TickTick

One hotkey (or `tal`) opens your whole TickTick world in Alfred: browse, search, add, schedule, tag, complete, focus — every change mirrored instantly in a local cache.

📖 Full docs: [docs/00-index.md](docs/00-index.md) — or via the `tdo` keyword.

## Dependencies

- Alfred 5 + Powerpack · Python 3 (Homebrew or Xcode CLT — TickAL finds either)
- A TickTick account + a free TickTick developer app (2 minutes, steps below)
- Optional: `pip3 install pyobjc` for the floating focus bar — focus works without it

## Setup

1. Go to [developer.ticktick.com/manage](https://developer.ticktick.com/manage) → **Create App** → set the redirect URI to `http://localhost:8080`
2. Paste the **Client ID** + **Client Secret** in Configure Workflow
3. Run `tlogin` — a browser opens; log in and approve
4. Run `tsy` to prime the cache, and set your main hotkey (top-left node on the canvas)
5. *Optional but recommended* — one sign-in unlocks attachments, the Completed view, nested tags, your filters, auto-named folders and your TickTick tag order: `tup` → **Attachment Login** (masked; only a session token is stored) — or paste a token via **Attachment Token** (Sign-in-with-Apple; guide in [docs/30-setup.md](docs/30-setup.md))
6. *Optional* — CRM / CTA / Projects features: paste your list and folder ids in Configure Workflow ([docs/45-crm.md](docs/45-crm.md) shows how to copy an id)

## Usage

Three chords run everything: **⌥⏎ deeper · ⌘⏎ actions · ⌃⏎ back**. Type to filter any screen.

| | |
|---|---|
| Core | `tal` main menu · `tse` search · `tad` add · `tup` settings · `tca` calendar |
| Views | `tod` today · `tom` tomorrow · `tne` next 7 days · `tin` inbox · `tsl` smart lists · `tfi` filters · `tta` tags · `tbu` buffer |
| More | `tfo` focus · `tur` save browser tab · `tst` statistics · `tcr` crm · `tsy` sync · `tdo` docs |
| Periodic | `pn` scope in search — daily / weekly / monthly notes, journals, money log |

Add tokens: `*` date · `@` time · `!` priority · `#` tag · `=` note · `[[` task link — or type `/` for the menu.

All keywords are re-mappable in Configure Workflow.
