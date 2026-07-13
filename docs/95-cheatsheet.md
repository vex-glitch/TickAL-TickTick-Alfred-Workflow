# Cheatsheet

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Every keyword, chord, add token, and search scope on one page.

## Keywords

All 20 are defaults - remap any of them in Configure Workflow. Seven hotkey nodes ship unbound (Today, Tomorrow, Next 7 Days, Inbox, Smart Lists, Calendar, Focus) - bind keys on the workflow canvas in Alfred.

| Keyword | Opens | Docs |
|---------|-------|------|
| `tal` | Main menu - every surface from one screen | [Getting started](10-getting-started.md) |
| `tse` | Search everything, with one-letter scopes | [Search](40-search.md) |
| `tad` | Add - tasks, lists, notes, projects | [Add](42-add.md) |
| `tup` | Settings menu | [Settings & sync](90-settings-sync.md) |
| `tsy` | Full cache refresh | [Settings & sync](90-settings-sync.md) |
| `tlogin` | Browser OAuth login | [Setup](30-setup.md) |
| `tca` | TickTick's Calendar (day/week/month/year views) | - |
| `tfo` | Focus screen - timer ⏱️ / pomodoro 🍅 | [Focus](44-focus.md) |
| `tur` | Save the active browser tab as a task | [Notes, links & images](46-notes-links-images.md) |
| `tst` | TickTick's Statistics | - |
| `tcr` | CRM booking hub | [CRM](45-crm.md) |
| `tsl` | Search pre-scoped to smart lists (`v `) | [Search](40-search.md) |
| `tin` | Inbox view | [Browse & drill](41-browse-drill.md) |
| `tod` | Today view | [Browse & drill](41-browse-drill.md) |
| `tom` | Tomorrow view | [Browse & drill](41-browse-drill.md) |
| `tne` | Next 7 Days view | [Browse & drill](41-browse-drill.md) |
| `tbu` | 🅿️ Buffer view | [Browse & drill](41-browse-drill.md) |
| `tta` | Tags - search locked to the `g` scope | [Browse & drill](41-browse-drill.md) |
| `tfi` | Search pre-scoped to filters (`f `) | [Search](40-search.md) |
| `tdo` | These docs on GitHub | [Home](00-index.md) |

## Chords

Global - the same moves on every row:

| Chord | Does |
|-------|------|
| ⏎ | Open / drill (the row's default) |
| ⌥⏎ | Go deeper |
| ⌘⏎ | Actions menu |
| ⌃⏎ | Back |

Per row type (⌘⏎ = Actions and ⌃⏎ = back everywhere; - = nothing bound):

| Row type | ⏎ | ⌥⏎ | ⇧⏎ | ⌥⇧⏎ | ⌥⌘⏎ |
|----------|---|-----|-----|------|------|
| Task / subtask | Open in TickTick | Subtasks | Complete | Add to 🅿️ buffer | Copy link |
| List | Open | Tags | - | Sections | Copy link |
| Section | Open | Tasks | - | - | Copy link |
| Tag | Its tasks | Its tasks | - | - | Copy tag link |
| Smart list | Its tasks* | Its tasks | - | - | Copy app link |
| Filter | Its tasks | Its tasks | - | - | - |
| Note | Open | - | - | - | Copy link |
| Completed task | Open | - | Uncomplete | - | - |
| Won't Do task | Open | - | Reopen | - | - |

\* App-only smart lists (no in-Alfred view) open in TickTick instead. Inside the ⌘⏎ Actions menu, ⌃⏎ returns to the screen you came from.

Task rows also wire **⌘⇧⏎** (Add here - the Add window prefilled with the row's context) and **⌃⇧⏎** (Start focus - the ⏱/🍅 flow on the task). On the Add window's Create row, **⌘⏎** chains the new task into the running focus (or opens the start flow on it) and **⇧⌘⏎** stages it. Periodic-note rows (the `pn` scope) open as a sticky note with **⌃⇧⏎**.

## Add tokens

Via the `tad` keyword (grammar: `tad Title *date @time !1-3 #tag ~l List =note`). `/` mid-add lists every token; `/` on an empty field lists the create modes.

| Token | Sets | Notes |
|-------|------|-------|
| `*` | Date | natural language, picker-assisted |
| `@` | Time | needs a date; `@HH:MM` |
| `>` | Duration | needs a time; end time (`>15`, `>15:30`) or a length via the picker |
| `!` | Priority | `!1` low · `!2` medium · `!3` high |
| `#` | Tag | repeatable |
| `~` | Location | bare `~` opens the menu; `~l` list · `~s` section · `~p` parent |
| `&` | Repeat | daily · weekdays · weekly · monthly · yearly |
| `%` | Reminder | repeatable; at-time and before-due presets |
| `=` | Note text | always last - everything after `=` is the note, no tokens inside |
| `[[` | Task link | picker opens; closes on `]]` |
| `^` | Clipboard image | attached to the task on create |
| `/` | Token menu | doubles as the syntax reference |

Leading prefixes switch what gets created:

| Prefix | Creates |
|--------|---------|
| `L ` | List |
| `N ` | Note |
| `P ` | Project (list + meta task) |
| `T ` | Tag (top-level, or nested under a parent) |

## Search scopes

Via the `tse` keyword (grammar: `tse [scope] query`). `/` opens the scope menu.

| Scope | Searches |
|-------|----------|
| (none) | Everything |
| `l` | Lists |
| `s` | Sections |
| `t` | Top-level tasks |
| `tt` | Subtasks |
| `a` | Tasks at any depth |
| `g` | Tags |
| `v` | Smart lists |
| `f` | Filters |
| `fo` | Folders |
| `la` | Last added (newest first) |
| `pn` | 💫 Periodic notes - open daily…yearly, `+` entry, `$` income, `day` / `goal` pickers, `today` / `tmrw` scheduling, journals ([docs](47-periodic.md)) |
| `n` | Note titles |
| `nc` | Note bodies |

## Related

- [Search](40-search.md) - scope behavior in full
- [Add](42-add.md) - every token with examples
- [Actions](43-actions.md) - the full ⌘⏎ menu per item type
- [Browse & drill](41-browse-drill.md) - views, drill ladder, buffer, tags
