# Search

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Fuzzy-search everything in your TickTick account — lists, sections, tasks, subtasks, tags, notes, smart lists, and filters — from one bar.

**Keyword:** `tse` (`tse [scope] query`)

Type to search everything at once. Prefix the query with a scope letter to narrow the type, or drop a `/token` anywhere in the bar (`tse monday /t` ≡ `tse t monday`). Typing `/` alone opens the [scope menu](#scope-menu). Re-map the keyword in Configure Workflow.

<details><summary>Screenshot</summary>

![Search hero](assets/shots/01-hero-search.png)

</details>

## Scopes

| Scope | Searches | Notes |
|-------|----------|-------|
| _(none)_ | Everything | Every item type, relevance-sorted |
| `l` | Lists | |
| `s` | Sections | |
| `t` | Top-level tasks | Excludes subtasks |
| `tt` | Subtasks | Subtasks only |
| `a` | Tasks + subtasks | Tasks at any depth |
| `g` | Tags | Tag rows with counts first; ⏎ locks the bar to `g #tag`, then the query filters that tag's items. ⏎ on a parent tag lists its child tags. Type a name that matches nothing → **➕ Create tag** (top-level, or nested under a parent) |
| `v` | Smart lists | Today, Tomorrow, Next 7 Days, Inbox, Summary, Completed, Won't Do, Habits, Matrix, Pomodoro |
| `f` | Filters | Your TickTick filters, synced with the v2 token — rules included |
| `fo` | Folders | Your folders in TickTick order; ⌥⏎ drills into a folder's lists |
| `la` | Last added | Incomplete tasks, newest first; typing filters, recency keeps ruling |
| `pn` | Periodic notes | Daily → yearly notes: open, entries, income, goals, journals — see [Periodic notes](47-periodic.md) |
| `n` | Note titles | |
| `nc` | Note bodies | Title shows a content snippet; note name · folder as breadcrumb |

<details><summary>Screenshot</summary>

![Tag scope query](assets/shots/06-search-scopes.png)

</details>

## Scope menu

Typing `/` alone lists every scope in place — ⏎ inserts the scope's prefix, ⌘2–⌘9 jump straight to a row, and typing after the `/` filters the menu by letter or name (`/n`, `/nc`, …).

<details><summary>Screenshot</summary>

![Scope menu](assets/shots/17-search-scope-menu.png)

</details>

## Result-row anatomy

| Part | Content |
|------|---------|
| Title | Name · priority dot (⚫️ none / 🟡 low / 🟠 medium / 🔴 high) · 📆 date or time span (if set) · #tags |
| Subtitle | Item type · breadcrumb `List>Section>Parent` · chord legend |
| 🅿️ | Appended to the title when the task sits in the buffer |
| 🔗 | Markdown links render as `[name]🔗` — display only, raw titles stay intact |

The chord legend in each subtitle advertises exactly what that row supports.

## Chords on a result

Task rows wire the full set:

| Chord | Action |
|-------|--------|
| ⏎ | Open in TickTick |
| ⇧⏎ | Complete |
| ⌘⏎ | Actions menu |
| ⌥⏎ | Drill into subtasks |
| ⌥⇧⏎ | Add to the 🅿️ buffer |
| ⌥⌘⏎ | Copy link |
| ⌘⇧⏎ | Add here — Add window prefilled with the row's context |
| ⌃⇧⏎ | Start focus — the ⏱/🍅 flow on this task |
| ⌃⏎ | Back to the main menu |

Other row types rewire ⏎/⌥⏎ to what makes sense:

| Row type | Differences |
|----------|-------------|
| List | ⌥⏎ browses the list's tags · ⌥⇧⏎ browses its sections · ⇧⏎ disabled |
| Section | ⏎ opens its list · ⌥⏎ browses its tasks |
| Note | Open, Actions, copy link, ⌘⇧⏎ Add here — ⇧/⌥ disabled |
| Tag (`g`) | ⏎ locks the bar to `g #tag` · ⌥⌘⏎ copies the tag's web-app link |
| Smart list / filter | ⏎ drills inline · ⌥⏎ opens the view in the Browse box · app-only smart lists (Summary, Habits, Matrix, Pomodoro) open in TickTick on ⏎ |

## Smart lists and filters

Smart lists (`v`), filters (`f`) and folders live in search too: their rows rank first on an exact name hit, and `v Today buy` filters Today's tasks inline. The `tsl` and `tfi` keywords are shortcuts that open search pre-scoped to `v ` and `f `.

## Related

- [Browse & drill](41-browse-drill.md) — the ⌥⏎ ladder and view keywords
- [Actions](43-actions.md) — everything behind ⌘⏎
- [Add](42-add.md) — the ⌘⇧⏎ prefilled Add window
- [Cheatsheet](95-cheatsheet.md)
