# Getting Started

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Zero to searching, drilling, scheduling, and adding tasks — the first 15 minutes.

**Keywords used:** `tse` · `tad` · `tlogin` · `tsy` (all re-mappable in Configure Workflow)

## 1. Install

1. Download `TickAL.alfredworkflow` from the [Releases page](https://github.com/vex-glitch/TickAL-TickTick-Alfred-Workflow/releases).
2. Double-click it. Alfred 5 imports the workflow.

Requirements: Alfred 5 with Powerpack, and any `python3` (Homebrew — Apple Silicon or Intel — or the Xcode Command Line Tools). The workflow finds it on its own; on a Mac with no Python at all, macOS itself prompts you to install the Command Line Tools the first time a keyword runs. PyObjC is optional — it powers the floating focus bar and clipboard-image attach; everything else runs without it.

## 2. Connect your account

Compressed version — the full walkthrough with screenshots is in [Setup](30-setup.md).

1. Open [developer.ticktick.com/manage](https://developer.ticktick.com/manage) → **Create App** → set the redirect URI to `http://localhost:8080`.
2. Paste the app's Client ID and Client Secret into Configure Workflow.
3. **Keyword:** `tlogin` — runs the browser OAuth flow; approve and return to Alfred.
4. **Keyword:** `tsy` — primes the local cache. Run it once now; run it again any time you want a fresh pull.

## 3. First search

**Keyword:** `tse` (`tse [scope] query`) — fuzzy search across lists, sections, tasks, tags, smart lists, filters, and notes.

1. Type `tse` and a few letters of any task title. Results render with breadcrumbs.
2. Narrow with a scope letter: `tse t milk` searches top-level tasks only, `tse l work` lists only.
3. Type `tse /` to open the scope picker — every scope with its letter, one ⏎ to autocomplete.

| Scope | Searches |
|-------|----------|
| `l` | lists |
| `s` | sections |
| `t` | top-level tasks |
| `tt` | subtasks only |
| `a` | tasks at any depth |
| `g` | tags |
| `v` | smart lists |
| `f` | your filters |
| `n` | note titles |
| `nc` | note bodies |

Three more scopes — `fo` folders, `la` last added, `pn` periodic notes — are on the [Search](40-search.md) page.

<details><summary>Screenshot</summary>

![Search results with breadcrumbs and modifier hints](assets/shots/01-hero-search.png)

</details>

## 4. Drill in, come back

Three chords do all the navigation, everywhere:

| Chord | Does |
|-------|------|
| ⌥⏎ | drill deeper (list → sections → tasks → subtasks) |
| ⌘⏎ | open the Actions menu for the selected row |
| ⌃⏎ | go back one level |

Try it: `tse l` → pick a list → ⌥⏎ into its sections → ⌥⏎ into a section's tasks → ⌃⏎ twice to climb back out. There's an animation of the full ladder on the [Browse & drill page](41-browse-drill.md). Bonus chords on task rows: ⇧⏎ completes, ⌥⌘⏎ copies the task link, ⌥⇧⏎ queues the task in the 🅿️ buffer.

## 5. First action: schedule a task

1. Find any task via `tse`.
2. ⌘⏎ opens its Actions menu.
3. Pick the **Schedule…** row (it shows the current date, or "📅 Not scheduled").
4. Choose a date from the picker. Done — the change writes through to TickTick and patches the local cache in place.

## 6. First add with tokens

**Keyword:** `tad` — one-line task capture with inline tokens.

Type:

```
tad Buy milk *tomorrow @08:30 !2 #shopping ~Personal
```

| Token | Sets |
|-------|------|
| `*` | date (`*tomorrow`, `*next monday`, `*21/07`) |
| `@` | time |
| `!` | priority (`!1` low · `!2` medium · `!3` high) |
| `#` | tag |
| `~` | destination list |

Each token pops a live picker as you type it; `/` opens the full token menu. The complete token set (duration, repeat, reminder, note, task links, images, and the `L `/`N `/`P ` create prefixes) is on the [Add page](42-add.md).

## What to read next

- Deepen the setup: the v2 token that makes tags, folders and filters configure themselves — [Setup](30-setup.md).
- One-page key reference — [Cheatsheet](95-cheatsheet.md).
- Everything else (views, focus sessions, buffer, CRM) — the page tree on [Home](00-index.md).

## Related

- [Home](00-index.md)
- [Setup](30-setup.md)
- [Cheatsheet](95-cheatsheet.md)
- [CRM](45-crm.md)
