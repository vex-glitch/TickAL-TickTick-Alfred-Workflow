# Changelog

All notable user-visible changes to TickAL. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.7] - 2026-07-17

### Added

- **🆔 Copy id** - ⌘⏎ on any list row copies its TickTick id; ⌥⌘⏎ on a
  folder row copies the folder id. The Configure Workflow id fields no longer
  need a trip to the web app.
- **Hourly Sync** settings row - installs (or removes) the hourly
  background-refresh LaunchAgent from inside Alfred: `tup` → Hourly Sync,
  one dialog, done. Detects installs left stale by a workflow update and
  offers Repair. No more hand-editing plist templates.
- **Install PyObjC** settings row - the focus-bar / image-attach dependency
  installs into the workflow's own Python from inside Alfred, PEP-668
  handled automatically. The missing-PyObjC hint notification now points at
  the row instead of a terminal command.
- **[Projects](docs/49-projects.md) docs page** - the `P ` bootstrap flow,
  the 📌 Create CTA row, and the keycap area-tag convention, all on one page.
- **📜 Docs browser** - `tdo` (and a new main-menu Docs row) opens every doc
  page from inside Alfred; typing filters the pages AND live-builds a GitHub
  search over the whole repo.
- **Periodic Agent** settings row - the 04:30 note-mint LaunchAgent installs,
  repairs, and removes itself from one dialog, like Hourly Sync. The manual
  template dance is gone.
- **Main menu reordered** - CRM sits below Periodic Notes, then Docs,
  Settings, Save URL, Statistics.

### Changed

- **Docs renumbered** - Notes 44, Views 45, Focus 46, CRM 47, Periodic 48,
  Projects 49: the four workflow pages now sit together with room to grow.

## [2.6] - 2026-07-15

### Added

- **Direct periodic keywords** - every periodic action now has its own
  keyword: `tpn` (the periodic surface), `tdn` / `twn` / `tmn` / `tqn` /
  `tyn` (daily to yearly notes), `tmj` / `tej` (morning / evening journal),
  `tde` (entry), `tmo` (income), `tdg` (day goal), `tat` (add to today).
- **Native TickTick views** - `tha` Habits, `tpo` Pomodoro / Focus and `tmx`
  Eisenhower Matrix open TickTick's own screens, documented on a new
  [Views](docs/45-views.md) page (which also covers `tca` Calendar and `tst`
  Statistics).
- **Hotkey nodes** for every major action - all ship unbound (Alfred clears
  hotkey combos on import); bind your own on the workflow canvas.

### Changed

- The keyword surface grew from 20 to **35 keywords**, all re-mappable in
  Configure Workflow.
- The `tod` / `tom` / `tne` smart-list keywords now offer an "Open in
  TickTick" row first, matching search. Search results break ties by
  priority and note rows show their tag chips.

### Fixed

- Pressing Enter on a row in any Browse view (folders, lists, tags, tasks,
  smart lists) now opens it. Previously Enter did nothing there.

## [2.5] - 2026-07-12

### Added

- **💫 Periodic notes (preview)** - Obsidian-style daily/weekly/monthly/quarterly/yearly
  notes as real TickTick notes in a list of your choosing (`pn` scope in
  search, or type "daily note" anywhere): auto-mint at 04:30 (launchd agent,
  lazy-mint fallback), instant open with background refresh, breadcrumb
  navigation, quote & weather with mood 😢-😁 and day rating ★, countdowns,
  habits, ☀️ Day Goal + ☀️/🌙 add-to-today/tomorrow (also in ⌘ Actions and
  the add window's `/` menu), a ✅ Today + ⏩ Tomorrow section whose ticked
  boxes complete the real tasks, morning/evening/weekly journals (answers
  route themselves - money to the log, rating to stars, highlight to the
  weekly), entries (`pn +`), a money log whose totals roll up
  daily→weekly→monthly→quarterly→yearly, a weekly 📌 This Week dashboard with
  vs-last-week chips, 📨 Entries digest, and a ♻️ Weekly Review section that
  mirrors your review list both directions. New `periodic_list_id` +
  `weekly_review_id` config fields - empty keeps it all off.
- **Documentation suite** - full docs under
  [`docs/`](https://github.com/vex-glitch/TickAL-TickTick-Alfred-Workflow/tree/main/docs),
  reachable in-workflow via the `tdo` keyword and Settings → Help • TickAL
  Docs.
- **20-keyword family** - every entry point has its own keyword (`tal` `tse`
  `tad` `tup` `tsy` `tlogin` `tca` `tfo` `tur` `tst` `tcr` `tsl` `tin` `tod`
  `tom` `tne` `tbu` `tta` `tfi` `tdo`), all re-mappable in Configure Workflow.
  7 unbound hotkeys ship for the view family, Smart Lists, Calendar and Focus
  - bind them in Alfred if you want them.
- **Focus system** (via the `tfo` keyword) - timer ⏱️ and pomodoro 🍅
  sessions; checkbox staging blocks in a focus task's description (dated
  `### YYYY-MM-DD` blocks of `- [ ] [Title](url)` lines); session-end sweep
  that completes the real tasks behind ticked boxes; the day's block saved as
  the focus record's note; a floating focus bar showing the running
  timer/pomo and current checkbox, with tick-with-confetti, expandable task
  list and hide/show. The bar needs PyObjC (install command in
  [Setup](docs/30-setup.md#focus-bar)) - a hint fires if it is missing; every
  other focus feature works without it.
- **🅿️ Buffer** - ⌥⇧⏎ on any task row queues it; the `tbu` keyword opens the
  buffer view for batch actions; the buffer feeds focus staging via "Add
  buffer to focus".
- **v2 sign-in for attachments, the Completed smart list and nested tags** -
  one-time masked sign-in (Settings → Attachment Login; password is never
  stored, only the session token - Keychain or a `chmod 600` config file), or
  paste the `t` cookie yourself via Settings → Attachment Token (the
  Sign-in-with-Apple path).
- **Needs-setup pointer rows** - unconfigured features (CRM, CTA, projects
  folder) show a single "… needs setup" row that opens the matching docs page
  instead of failing silently.
- **Portable Python resolver** - `Scripts/py.sh` finds any `python3`
  (Homebrew arm/Intel or Xcode CLT); a missing Python produces a clear
  install hint instead of a broken canvas.

- **Zero-setup tags, folders and filters** - with the v2 token, every sync
  pulls your tag list in TickTick sidebar order, your folder names and order,
  and your TickTick filters WITH their rules (translated into the built-in
  matcher; the rare untranslatable clause is dropped with an honest ⚠ note).
  The Settings Tags/Filters/Folders rows, both Configure Workflow textareas,
  and the tags_config.py editor flow are gone - there is nothing to set up.
  Tokenless installs run on tags discovered from tasks and a hand-written
  `filters_config.py`.
- **Create tags from the pickers** - type a tag name that matches nothing and
  ➕ rows appear in the add window's `#` picker (plain, or pick a parent to
  nest under, right in the flow), the tag manager, the change-tag picker, and
  the tag search (`tta`). The add window also has a dedicated `T name`
  creation mode next to `L`/`N`/`P`, and the ⌘ menu on any top-level tag
  offers **➕ Add nested tag** (a dialog asks the name). Matching is
  emoji-blind - typing `crm` counts as the existing `🔥CRM`. Real TickTick
  tags, created via the v2 session; the ⌘ menu on a tag can delete one too.
- **🚫 Won't do** - TickTick's third status from the ⌘ Actions menu: the
  task leaves every open list without pretending it was done. A **Won't Do**
  smart list joins the `v` search scope (⇧⏎ there reopens a task), and
  abandoning the task your focus session runs on ends the session first,
  like Complete.
- **Focus bar, rounder** - ticked checkboxes leave the bar (the description
  keeps them), the expanded list scrolls with the wheel past 10 rows (with a
  "scroll ↑/↓" strip), every row grew ⤒ ↑ ↓ ⤓ buttons that reorder the block
  (one slot or straight to an edge), a 🌬 sweep button completes the ticked
  tasks right from the bar, and the check circles wear the glow's own muted
  green.
- **Bulk add to focus** - `/` inside the session's ➕ Add-to-focus search:
  a whole tag of a list, a whole section, or every task due today lands in
  the block in one ⏎.
- **📝 description marker** - tasks with a real description show
  `📝 <first line>` at the end of their subtitle in search and browse
  (focus checkbox blocks don't count as a description).
- **Search scopes `fo` (Folders) and `la` (Last Added)** - folders in TickTick
  order with ⌥⏎ drill, and a newest-first view of recent tasks; folders also
  surface in the everything search.
- **Add → focus chaining** - hold ⌘⏎ on the add window's Create row (running
  session → the new task lands in its checkbox block; idle → the ⏱/🍅 start
  flow opens on it) or ⇧⌘⏎ to stage it; the `/` menu carries the same chains
  as typed markers (🎯 Stage for Focus / ➕ Add to focus). The new task
  chains into the focus flow the moment it is created.
- **⌃⇧⏎ Start focus in search** - every open task row starts the ⏱/🍅 flow
  straight from a search result.
- **🔃 Convert to note / task** - one dynamic ⌘-menu row flips the item's
  kind; title, description, dates and tags survive.
- **📋 Copy as bullet list** - on the running session's `tfo` screen: today's
  unticked checkboxes land on the clipboard as paste-ready `- Title` lines.
- **📋 Show all tasks** - tops a list's tag and section pickers in the drill
  ladder: the whole list flat, grouped by tag in your TickTick tag order
  (the order that drives the app's group-by-tag sections), priority first.
- **🎯 Stage for Focus from the `tfo` menu** - pick any task, then the normal
  stage flow; no ⌘ menu needed.

### Changed

- Every list, section, and tag drill view now sorts priority first
  (🔴 → 🟠 → 🟡), keeping your TickTick order within each band.
- Update menu is now **Settings** (via the `tup` keyword), with the new
  Attachment Login and Attachment Token rows.
- Configure Workflow panel rebuilt - 27 fields, neutral defaults; set
  everything there, no code edits needed.
- README and the in-Alfred About text rewritten for the public release.
- The v2 API now uses a **per-install device id** generated on first use -
  no shared fingerprint ships with the workflow.
- **Unified search** (via the `tse` keyword) now owns smart lists and filters
  through its `v` and `f` scopes; the separate view-picker and filter chains
  are gone.
- Core keywords renamed: `tt`→`tal`, `ts`→`tse`, `ta`→`tad`, `tsync`→`tsy`
  (all still re-mappable in Configure Workflow).
- Every row subtitle swept to a terse house style - fewer words, one chip
  vocabulary, one separator convention (a few older hints still advertised
  chords that no longer existed).

### Fixed

- `tlogin` now opens the consent page in your **default browser** explicitly.
  The TickTick desktop app claims ticktick.com links, so the plain open got
  swallowed by the app and the OAuth dance never finished
  ([#1](https://github.com/vex-glitch/TickAL-TickTick-Alfred-Workflow/issues/1)).

### Removed

- Dead keywords `tot` `toi` `td` `tf` `tl` `tbt` `tbi` - drill and filters
  folded into search's scopes; the old browse-today/inbox entries live on as
  `tod` and `tin`.
- Slash app integration (send-to-Slash rows, sync script, watcher agent).
- Personal defaults - no hard-coded list ids, tag names or machine paths
  remain; everything is set in Configure Workflow.

## Earlier versions

Versions 2.0-2.2 predate this repository's public history and are not tagged here.
