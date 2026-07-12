# TickAL

> Make TickTick dance with Alfred — search everything, browse the full hierarchy in one box, and change any task attribute without ever opening the app.

Three chords to remember: **⌥⏎ deeper · ⌘⏎ actions · ⌃⏎ back**

![Alfred 5](https://img.shields.io/badge/Alfred-5-blueviolet) ![Version 2.5](https://img.shields.io/badge/version-2.5-blue)

![Drill down and back — ⌥ deeper, ⌃ back](docs/assets/shots/drill.gif)
![Actions menu](docs/assets/shots/09-actions-menu.png)
![Focus bar](docs/assets/shots/12-focus-bar.png)

## Requirements

- macOS with [Alfred 5](https://www.alfredapp.com/) + Powerpack
- Python 3 — any install works (Homebrew arm/Intel or Xcode CLT); the workflow resolves it itself
- A TickTick account + your own free developer app (2-minute registration, below)

## Setup

1. [developer.ticktick.com/manage](https://developer.ticktick.com/manage) → **Create App** → redirect URI `http://localhost:8080` → paste Client ID/Secret into Configure Workflow.
2. `tlogin` (browser OAuth) → `tsy` to prime the cache.
3. Set the main hotkey — and (recommended) sign in once via Settings → Attachment Login: tags, folders and filters then configure themselves on every `tsy`, straight from your TickTick ([docs/30-setup.md](docs/30-setup.md)).

Extras — attachments, CRM, filters, hourly sync → [docs/30-setup.md](docs/30-setup.md).

## What you get

**Search** — one box over lists, sections, tasks, subtasks, tags, folders, smart lists, filters, notes, and note bodies, with 13 typed scopes (`tse [scope] query`) including 👉 Last Added; task rows carry a `📝 first line` peek at their description.
→ there is more magic than fits here: [docs/40-search.md](docs/40-search.md)

**Browse & views** — drill any list → section → task → subtask ladder with ⌥⏎, walk back up with ⌃⏎; 📋 Show-all flattens a list grouped by your TickTick tag order, priority first; Inbox/Today/Tomorrow/Next-7 views one keyword away.
→ there is more magic than fits here: [docs/41-browse-drill.md](docs/41-browse-drill.md)

**Add** — token grammar in a single line: `*` date, `@` time, `>` duration, `&` repeat, `%` reminder, `!` priority, `#` tag, `~` list/section/parent, `=` note, `[[` task link, `^` clipboard image, `/` for the token menu. Unknown `#tags` are created on the fly (nested under a parent if you like), and ⌘⏎ / ⇧⌘⏎ chain the new task straight into Focus.
→ there is more magic than fits here: [docs/42-add.md](docs/42-add.md)

**⌘ Actions** — a per-item menu on every row: schedule, move, rename, priority, tags, convert task ↔ note, copy link, complete, delete, and more; tag rows get their own menu (open, drill, send-all-to-focus, delete tag).
→ there is more magic than fits here: [docs/43-actions.md](docs/43-actions.md)

**Focus** — timer ⏱️ / pomodoro 🍅 via the `tfo` keyword (or ⌃⇧⏎ on any search result), checkbox staging blocks in a focus task — added one at a time, in bulk (a tag, a section, today), or from the 🅿️ buffer — a sweep that completes the real tasks behind ticked boxes, a copy-as-bullet-list export, and a floating focus bar that ticks, reorders (⤒ ↑ ↓ ⤓), scrolls, and sweeps.
→ there is more magic than fits here: [docs/44-focus.md](docs/44-focus.md)

**CRM & extras** — an opinionated booking hub (🔥 group tags, auto "Prepare for [[booking]]" follow-ups, clipboard-image attach), plus attachments, the Completed smart list, and zero-setup tags/folders/filters via a one-time v2 sign-in.
→ there is more magic than fits here: [docs/45-crm.md](docs/45-crm.md)

**💫 Periodic notes** — Obsidian-style daily/weekly/monthly/quarterly/yearly notes minted inside TickTick: breadcrumbs, quote & weather, countdowns, habits, journals with prompt dialogs, a money log that rolls up the whole pyramid, and a ✅ Today section whose ticked boxes complete the real tasks.
→ there is more magic than fits here: [docs/47-periodic.md](docs/47-periodic.md)

## Keywords & keys

**⌥⏎ deeper · ⌘⏎ actions · ⌃⏎ back** — plus ⇧⏎ complete, ⌥⌘⏎ copy link, ⌥⇧⏎ add to the 🅿️ buffer, ⌃⇧⏎ start focus on any task row.

20 keywords ship (`tal` main menu, `tse` search, `tad` add, `tfo` focus, `tcr` CRM, …) — all re-mappable in Configure Workflow, with 7 unbound hotkeys ready to assign in Alfred. Full table: [docs/95-cheatsheet.md](docs/95-cheatsheet.md).

## Cache & sync

Everything reads a local JSON cache, patched in place on every write — no waiting on the API between keystrokes.
`tsy` (or Settings → Sync) refreshes it in full.
Optional hourly background sync: copy `assets/launchd/com.vex.tickal.cachesync.plist`, edit the workflow path inside, `launchctl load` it — see [docs/90-settings-sync.md](docs/90-settings-sync.md).

## Limitations

- macOS only. Alfred Powerpack required.
- You must register your own TickTick developer app — API credentials cannot be bundled.
- Attachments, the Completed list, nested tags, tag creation, and the tags/folders/filters auto-config ride TickTick's undocumented v2 API with a session token; they can break without notice. Everything else uses the official API.
- The floating focus bar needs PyObjC (`pip3 install pyobjc`); every other focus feature works without it.
- The CRM module is opinionated — a dedicated list, 🔥-prefixed group tags, a fixed booking→prepare flow. Skip the `crm_list_id` in Configure Workflow and it stays dormant.

---

Docs index: [docs/00-index.md](docs/00-index.md) · Bugs and questions: [Issues](https://github.com/vex-glitch/TickAL-TickTick-Alfred-Workflow/issues) · License: TBD
