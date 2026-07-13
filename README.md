# TickAL

**TickTick, without opening TickTick.** One hotkey opens your whole TickTick world in Alfred: search it, browse it, add to it, schedule, tag, complete, focus. Every change lands in a local cache first, so nothing waits on the network between keystrokes.

![Alfred 5](https://img.shields.io/badge/Alfred-5-blueviolet) ![Version 2.5](https://img.shields.io/badge/version-2.5-blue) ![License MIT](https://img.shields.io/badge/license-MIT-green)

![Search everything from one box](docs/assets/shots/01-hero-search.png)

Three chords run everything, on every screen: **⌥⏎ deeper · ⌘⏎ actions · ⌃⏎ back**. Type to filter. That is the whole learning curve; everything below is detail.

## Search

One box over lists, sections, tasks, subtasks, tags, folders, smart lists, filters, notes and note bodies. Thirteen one-letter scopes narrow it (`tse t buy` searches tasks only), task rows show a `📝` first-line peek of their note, and the 👉 Last Added scope lists what you just created, newest first. Full scope table: [Search](docs/40-search.md).

![Search scopes](docs/assets/shots/06-search-scopes.png)

## Browse

Drill any list → section → task → subtask ladder with ⌥⏎ and walk back up with ⌃⏎. 📋 Show-all flattens a whole list, grouped by your own TickTick tag order with priorities first. Inbox, Today, Tomorrow and Next 7 Days are each one keyword away. More in [Browse & drill](docs/41-browse-drill.md).

![Drill down and back](docs/assets/shots/drill.gif)

## Add

A whole task in a single line: `tad Call Anna *tomorrow @14 !2 #calls =bring the contract`. Tokens cover date, time, duration, repeat, reminder, priority, tag, list/section/parent, note, task links and clipboard images; `/` opens the token menu whenever you forget one. Unknown `#tags` are created on the fly, and ⌘⏎ chains the new task straight into a running focus session. Every token, with examples: [Add](docs/42-add.md).

![Add tokens](docs/assets/shots/08-add-tokens.png)

## Actions

⌘⏎ on any row opens a menu built for that item: schedule, move, rename, priority, tags, convert task ↔ note, copy link, complete, delete and more. Tag rows get their own menu (open, drill, send everything to focus, delete). The full matrix per item type: [Actions](docs/43-actions.md).

![Actions menu](docs/assets/shots/09-actions-menu.png)

## Focus

Start a timer ⏱️ or pomodoro 🍅 on any task from `tfo` or straight off a search row. Stage checkbox blocks in the focus task (one at a time, a whole tag or section, today's list, or the 🅿️ buffer), tick boxes as you go, then sweep: every ticked box completes its real task. A floating focus bar shows the clock and ticks, reorders and sweeps without opening Alfred. All of it: [Focus](docs/44-focus.md).

![Floating focus bar](docs/assets/shots/12-focus-bar.png)

## Periodic notes

Obsidian-style daily, weekly, monthly, quarterly and yearly notes minted inside TickTick, new in 2.5 as a preview. Breadcrumbs link the whole pyramid, mornings bring weather, a quote, countdowns and habits, journals ask their questions in prompt dialogs, a money log rolls up from day to year, and the ✅ Today section mirrors real tasks: tick the box in the note and the task completes. The whole system: [Periodic notes](docs/47-periodic.md).

![Daily note](docs/assets/shots/19-periodic-note.png)

## CRM

An opinionated booking hub: 🔥 group tags for your client lists, automatic "Prepare for [[booking]]" follow-ups, and clipboard-image attach for reference shots. Skip its list id in Configure Workflow and the module stays dormant. Setup and flow: [CRM](docs/45-crm.md).

![CRM hub](docs/assets/shots/13-crm-hub.png)

## Notes, links and images

Edit a task's note in a proper text window, link tasks to each other with `[[`, save the active browser tab as a task with `tur`, and paste clipboard images as real attachments. Details: [Notes, links & images](docs/46-notes-links-images.md).

![Note editor](docs/assets/shots/14-note-editor.png)

## Requirements

- macOS with [Alfred 5](https://www.alfredapp.com/) + Powerpack
- Python 3, any install: Homebrew (Apple Silicon or Intel) or Xcode CLT, the workflow finds it itself
- A TickTick account + your own free TickTick developer app (2 minutes, next section)
- Optional: `pip3 install pyobjc` for the floating focus bar; every other focus feature works without it

## Setup

1. [developer.ticktick.com/manage](https://developer.ticktick.com/manage) → **Create App** → set the redirect URI to `http://localhost:8080`
2. Paste the **Client ID** and **Client Secret** into Configure Workflow
3. Run `tlogin`: a browser opens, log in and approve
4. Run `tsy` to prime the cache, and set your main hotkey on the workflow canvas
5. Recommended: `tup` → **Attachment Login** (password masked, only a session token is stored). One sign-in unlocks attachments, the Completed view, nested tags, your filters, auto-named folders and your own tag order on every sync
6. Optional: paste list and folder ids for the CRM / CTA / Projects extras

Step-by-step with screenshots: [Getting started](docs/10-getting-started.md) · every credential detail: [Setup](docs/30-setup.md).

## Keywords and keys

| | |
|---|---|
| Core | `tal` main menu · `tse` search · `tad` add · `tup` settings · `tca` calendar |
| Views | `tod` today · `tom` tomorrow · `tne` next 7 days · `tin` inbox · `tsl` smart lists · `tfi` filters · `tta` tags · `tbu` buffer |
| More | `tfo` focus · `tur` save browser tab · `tst` statistics · `tcr` crm · `tsy` sync · `tdo` docs |
| Periodic | `pn` scope in search: daily to yearly notes, journals, money log |

On task rows: ⇧⏎ complete · ⌥⇧⏎ send to the 🅿️ buffer · ⌥⌘⏎ copy link · ⌃⇧⏎ start focus · ⌘⇧⏎ add here. All 20 keywords are re-mappable in Configure Workflow, and 7 hotkey nodes ship unbound, ready to assign. The whole map on one page: [Cheatsheet](docs/95-cheatsheet.md).

## Cache and sync

Everything reads a local JSON cache that is patched in place on every write, so your own changes show up instantly and only outside edits need a refresh. `tsy` refreshes in full. An optional LaunchAgent syncs hourly in the background: [Settings & sync](docs/90-settings-sync.md).

## Tests

`make test` runs 187 offline checks (the periodic-notes engine and the focus checkbox parser) on stock Python 3. No account or credentials needed.

## Limitations

- macOS only, Alfred Powerpack required.
- You register your own TickTick developer app; API credentials cannot be bundled.
- Attachments, the Completed list, nested tags, tag creation and the tags/folders/filters auto-config ride TickTick's undocumented v2 API with a session token, so they can break without notice. Everything else uses the official API.
- The floating focus bar needs PyObjC; focus itself does not.
- The CRM module is opinionated by design: a dedicated list, 🔥-prefixed group tags, a fixed booking → prepare flow.

## Docs

| | Page | Covers |
|---|------|--------|
| Learn | [Getting started](docs/10-getting-started.md) | Install to first task |
| | [Concepts](docs/20-concepts.md) | Scopes, drill, tokens, buffer, focus blocks |
| Do | [Search](docs/40-search.md) · [Browse & drill](docs/41-browse-drill.md) · [Add](docs/42-add.md) · [Actions](docs/43-actions.md) | The daily drivers |
| | [Focus](docs/44-focus.md) · [CRM](docs/45-crm.md) · [Notes, links & images](docs/46-notes-links-images.md) · [Periodic notes](docs/47-periodic.md) | The deep features |
| Reference | [Setup](docs/30-setup.md) · [Settings & sync](docs/90-settings-sync.md) · [Cheatsheet](docs/95-cheatsheet.md) · [Troubleshooting](docs/99-troubleshooting.md) | Every option, key and fix |

Or run `tdo` from Alfred once installed.

## License

[MIT](LICENSE). Bugs and questions: [Issues](https://github.com/vex-glitch/TickAL-TickTick-Alfred-Workflow/issues).
