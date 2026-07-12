# Add

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Create tasks, lists, notes, and projects from one input line with a token grammar and live sub-pickers.

**Keyword:** `tad` (grammar: `tad Title *date @time !1-3 #tag ~l List =note`)

Type a title, then add tokens in any order. Each token opens a live sub-picker; ⏎ on a picker row fills the value back into the query. ⏎ on the **Create:** preview row creates the task — the subtitle shows every parsed field before you commit. Once a date or time is set, the preview offers follow-up rows (⏰ Add time, ⏳ Add duration, 🔔 Add reminder); ⏎ drops you into the matching picker.

## Tokens

| Char | What | Example |
|------|------|---------|
| `*` | Date — natural language | `*tomorrow`, `*next monday`, `*21/07`, `*in 3 days` |
| `@` | Time — hour picker, then minutes (00/15/30/45) | `@14:30` |
| `>` | Duration — end time or length (needs a `@` time) | `>16`, `>16:30`, `>2h`, `>90m`, `>1h30` |
| `!` | Priority — 1 low 🟡 · 2 medium 🟠 · 3 high 🔴 | `!2` |
| `#` | Tag — picker from your tags; repeatable | `#errand #home` |
| `~` | Location — list `~l` · section `~s` · parent task `~p` | `~l Groceries` |
| `&` | Repeat preset (needs a `*` date) | `&weekly` |
| `%` | Reminder (needs a `*` date; repeatable) | `%15`, `%1d`, `%7am` |
| `=` | Note — everything after `=` becomes the description | `=call first` |
| `[[` | Task link — picker inserts `[[Title]]` | `[[Quarterly review]]` |
| `^` | Attach the clipboard image on create | `^` |
| `/` | Menu of every add-on (doubles as a syntax reference) | `/` |

<details><summary>Screenshot</summary>

![tad add flow with token pickers](assets/shots/08-add-tokens.png)

</details>

Notes on specific tokens:

- **Dates** parse natural language (parsedatetime) and surface a shortcut list — Today, Tomorrow, In 2 Days, In a Week, This Weekend, next weekdays, month starts and ends. Unparseable input shows a hint with examples.
- **Time** is a two-step dropdown: pick the hour (typing `6` also surfaces `18`), ⏎, pick minutes. A full `@14:30` typed directly also works.
- **Duration** requires a start time. Type an end hour, an exact `16:30`, or a length (`2h`, `90m`, `1h30`); end times before the start wrap past midnight.
- **Repeat** presets: `daily` · `weekdays` (Mon–Fri) · `weekly` · `monthly` · `yearly`.
- **Reminder** presets: `at` (when due) · `5` · `15` · `30` · `1h` · `1d` · `2d` · `3d` · `7d` · `7am` (07:00 on the day, for all-day tasks). Free-typed offsets like `45m` or `2h` also resolve.
- **Note** text is opaque — no tokens are parsed after `=`, so put it last (the preview's follow-up rows also disappear once a note is present). Multi-line pastes are kept intact.
- **Location**: bare `~` shows the List / Section / Parent menu; typing straight after `~` filters lists. `~p` makes the new task a subtask and inherits the parent's list; `~s` narrows sections to the chosen list.

## The `/` menu

On an empty field, `/` picks what to create — Task, List, Note, Project, or Tag. Once a title exists (or the window is pinned to a container), `/` lists every applicable add-on (date, time, duration, repeat, reminder, priority, tag, location, note, image); ⏎ autocompletes its symbol into the query. Context-dependent rows appear only when valid — `@` after a date, `>` after a time, `&`/`%` after a date.

<details><summary>Screenshot</summary>

![the / attribute menu on a task title](assets/shots/15-add-slash-menu.png)

</details>

## Creation modes: L / N / P / T

| Prefix | Creates | Details |
|--------|---------|---------|
| `L name` | List | One ⏎, done |
| `N title` | Note | Notes take `*` `@` `>` `&` `%` `#` `~` `=` too; `~l` includes note lists |
| `P name` | Project | Pick an area tag → creates a `💼P • name` list plus its scheduled meta task |
| `T name` | Tag | Two rows: **➕** creates it top-level, **🪆 under parent…** opens the parent list (typing filters it). Needs the [v2 token](30-setup.md) |

Prefixes are case-insensitive (`l `, `n `, `p `, `t ` work). Area tags for `P` are your tags starting with a keycap number (1️⃣…) — they arrive with the tag sync, no setup.

## Adding into a list, section, or task

⌘⏎ on any list, section, or task → **➕ Add task** opens the same add window pinned to that container. The hint row shows where the task will land — "Adding to *list*", "Adding to §*section*", or "↳ Subtask of *task*" — and the created task goes there with no tokens needed. Explicit `~l` / `~s` / `~p` tokens override the pinned target. ⌃⏎ goes back — to the task's Actions menu when pinned to a task, to the main menu otherwise. See [Actions](43-actions.md).

## Task links: `[[`

Typing `[[` opens a picker over all cached open tasks and notes; ⏎ inserts the readable `[[Title]]` form. On create, each `[[Title]]` in the title resolves to a real TickTick task link (name collisions prefer the current list); unresolved names stay literal. In a CRM add the picker scopes to bookings — see [CRM](45-crm.md).

## Clipboard image: `^`

Add `^` (or pick 🖼️ Add image from the `/` menu) to upload the clipboard image as a real attachment to the new task. Attachments use the v2 API and need the one-time session token — see [Setup](30-setup.md). No image on the clipboard → the task is still created and the notification says so.

## Straight into a focus session: ⌘⏎ / ⇧⌘⏎, or `+stage` / `+focus`

Hold a chord on the **Create** row itself — the preview subtitle advertises them as `⌘🎯 ⇧⌘📍`:

- **⌘⏎** — create, then 🎯: while a task-bound session runs, the new task lands straight in its checkbox block ("Add to the running focus"); otherwise the ⏱/🍅 start flow opens on it ("Start Focus").
- **⇧⌘⏎** — create, then 📍 stage it: the stage screen opens on the new task (checkbox-link it into another task/note).

The same chains exist as typed markers via two `/` menu rows, like `^`:

- **🎯 Stage for Focus** (`+stage`) — identical to ⇧⌘⏎.
- **➕ Add to focus** (`+focus`, shown while a task-bound session runs) — identical to ⌘⏎ during a session.

The preview shows a 🎯/➕ chip while a marker is set. Either way, no add → search → stage round-trip.

## New tags on the fly

Type `#name` for a tag that doesn't exist yet and the picker offers two rows: **➕ #name** (plain) and **➕ #name → parent…**, which lists your tags to nest the new one under — the choice rides the query as `#name>parent`. The real TickTick tag is created the moment the task saves (needs the v2 token). Matching is emoji-blind: typing `crm` counts as the existing `🔥CRM`, so no bald duplicates. The `tta` tag search creates tags the same way.

## Related

- [Search](40-search.md) — find what you just added
- [Browse & drill](41-browse-drill.md) — walk into the list it landed in
- [Actions](43-actions.md) — the ⌘⏎ menu, including Add-into-container
- [Notes, links & images](46-notes-links-images.md) — editing notes and attachments later
- [Setup](30-setup.md) — the v2 token for image attachments
