# Concepts

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> The vocabulary every other page assumes - one screen, no keystrokes to memorize yet.

## Navigating

**Browse box** - one Alfred window that renders every level of your TickTick tree. Whatever you type filters the current level fuzzily; the window re-renders in place as you drill up and down.

**Level ladder** - the drill order inside the Browse box: folders → lists → sections → tasks → subtasks → sub-subtasks. Lists with no sectioned content skip the sections rung automatically. Tag views, smart lists, and filters enter the same ladder at the tasks rung - drilling in and ⌃⏎ back work identically inside them.

**Context** - every row carries invisible Alfred variables (task id, list id, item type, the parent screen). That is why the search bar stays clean - you only ever see your query - and why ⌃⏎ always knows where "back" is without you retyping anything.

## Acting on rows

**The three chords** - the core grammar, identical on every surface:

| Chord | Meaning |
|---|---|
| ⌥⏎ | Deeper - drill into the row's children (hidden when there are none) |
| ⌘⏎ | Actions - open the per-item ⌘ Actions menu |
| ⌃⏎ | Back - return to the parent screen |

Five more ride alongside on task rows:

| Chord | Meaning |
|---|---|
| ⇧⏎ | Complete (⇧ on a completed row uncompletes) |
| ⌥⌘⏎ | Copy the item's TickTick link |
| ⌥⇧⏎ | Add the task to the 🅿️ buffer |
| ⌃⇧⏎ | Start a focus session on the task |
| ⌘⇧⏎ | Add here - a new task into the row's context |

**⌘ Actions menu** - the action set for the selected item: open, browse, schedule, reminder, tags, priority, move, add, note, focus, complete, rename, delete, back, and more. The menu is dynamic - only actions that apply to the selected item appear (a note row drops Complete, a list row swaps in list actions) - and current values (date, priority, breadcrumb) show inline.

**Act-again** - after any attribute change the ⌘ Actions menu reopens on the same task with fresh values. Chain edits - schedule, then tag, then move - without re-finding the task.

**`/` menu** - the Add window's menu key: on an empty field it lists what to create (task, list, note, project, tag); once a title exists it lists every applicable attribute token. `/` lives in the Add window only - on search and browse rows the menu key is ⌘⏎.

**Attribute picker** - the screen an action row opens to choose a value: a date grammar for schedule, a tag list, priority levels, a list/section tree for move, reminder offsets. Pick, it applies, act-again brings you back.

## Organizing

**Smart list** - a built-in computed view: Today, Tomorrow, Next 7 Days, Inbox, Summary, Completed, Won't Do, and the app-only views (Habits, Matrix, Pomodoro). Searchable via the `tse` keyword's `v` scope - the `tsl` keyword jumps straight into it, and Today, Tomorrow, Next 7 Days and Inbox have their own keywords too. Completed shows the last 60 days of server history once the optional v2 token is set (see [Setup](30-setup.md)); without it, only tasks completed through the workflow are tracked.

**Filter** - a TickTick filter, synced over with the v2 token (names, sidebar order, and rules - translated into the workflow's matcher) and searchable via the `f` scope. Smart lists ship built in; filters are yours - that is the whole difference.

**Tag** - TickTick's cross-list label. Browse a list's tags from its ⌘ Actions menu, or search all tags via the `g` scope - the `tta` keyword jumps straight into it; nested tags need the optional v2 token.

**Project / CTA / Area** - a project is a `💼P • name` list; its presence in your day is a **CTA** (call-to-action) task in the 📌CTA list, deep-linked to the project and scheduled; the **area** is a keycap-led tag (`1️⃣Work`) the CTA inherits automatically. The whole convention: [Projects](49-projects.md).

**🅿️ Buffer** - a disposable local parking lot for tasks. ⌥⇧⏎ queues any task row; the `tbu` keyword opens the buffer, where you can tag, move, prioritize, or complete everything at once - or send the whole set into today's focus block. Clearing the buffer never touches the tasks themselves.

## Focusing

**Focus session** - a timer ⏱️ or a pomodoro 🍅, started via the `tfo` keyword or from a task's ⌘ Actions. Both log real TickTick focus records: the timer logs on stop (pauses compressed out), the pomodoro runs through the app itself.

**Focus bar** - the floating pill that follows a session: the running timer/pomodoro and the current checkbox from today's staging list, with tick, expand, and hide controls. It and clipboard-image attach are the only features that need PyObjC (one Settings row installs it - see [Setup](30-setup.md#focus-bar)); every other focus feature works without it.

**Checkbox block** - where those checkboxes live: the day's staging list, stored inside a focus task's description as `- [ ] [Title](url)` lines under a `### YYYY-MM-DD` header, blocks separated by `---`. When a new day's block is created, unchecked lines carry over to it; checked lines stay put as a permanent record, and the day's block rides along as the focus record's note.

**Sweep** - one action that completes the real TickTick task behind every ticked checkbox, across all blocks. Ticking a box is just staging; nothing completes until you sweep.

## Plumbing

**Local cache** - every screen reads from JSON files under `~/.ticktick_alfred/cache/`, and every write patches the cache in place, so rows update instantly without a round-trip. The `tsy` keyword forces a full refresh; an optional LaunchAgent refreshes hourly (see [Settings & sync](90-settings-sync.md)).

**Keywords & hotkeys** - 35 keywords and 34 global-hotkey nodes cover every entry point. Keywords re-map in Configure Workflow; hotkeys bind on the workflow canvas - the marked top row - and all ship unbound (Alfred clears combos on import), so set your own.

## Related

- [Search](40-search.md) · [Browse & drill](41-browse-drill.md) · [Add](42-add.md) · [Actions](43-actions.md) · [Focus](44-focus.md)
- [Cheatsheet](95-cheatsheet.md) - every keyword and keystroke on one page
