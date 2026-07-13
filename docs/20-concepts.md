# Concepts

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> The vocabulary every other page assumes - ten terms, one screen, no keystrokes to memorize yet.

## Navigating

**Browse box** - one Alfred window that renders every level of your TickTick tree. Whatever you type filters the current level fuzzily; the window re-renders in place as you drill up and down.

**Level ladder** - the drill order inside the Browse box: folders → lists → sections → tasks → subtasks → sub-subtasks. Lists with no sectioned content skip the sections rung automatically; tag views and smart lists hang off the same ladder.

**Context** - every row carries invisible Alfred variables (task id, list id, item type, the parent screen). That is why the search bar stays clean - you only ever see your query - and why ⌃⏎ always knows where "back" is without you retyping anything.

## Acting on rows

**The three chords** - the core grammar, identical on every surface:

| Chord | Meaning |
|---|---|
| ⌥⏎ | Deeper - drill into the row's children (hidden when there are none) |
| ⌘⏎ | Actions - open the per-item ⌘ Actions menu |
| ⌃⏎ | Back - return to the parent screen |

Three more ride alongside on task rows:

| Chord | Meaning |
|---|---|
| ⇧⏎ | Complete (⇧ on a completed row uncompletes) |
| ⌥⌘⏎ | Copy the item's TickTick link |
| ⌥⇧⏎ | Add the task to the 🅿️ buffer |

**⌘ Actions menu** - the action set for the selected item: open, browse, schedule, reminder, tags, priority, move, add, note, focus, complete, rename, delete, back, and more. Rows adapt to the item type, and current values (date, priority, breadcrumb) show inline.

**Act-again** - after any attribute change the ⌘ Actions menu reopens on the same task with fresh values. Chain edits - schedule, then tag, then move - without re-finding the task.

**Attribute picker** - the screen an action row opens to choose a value: a date grammar for schedule, a tag list, priority levels, a list/section tree for move, reminder offsets. Pick, it applies, act-again brings you back.

## Organizing

**Smart list** - a built-in computed view: Today, Tomorrow, Next 7 Days, Inbox, Summary, Completed, Won't Do, and the app-only views (Habits, Matrix, Pomodoro). Searchable via the `tse` keyword's `v` scope - the `tsl` keyword jumps straight into it, and Today, Tomorrow, Next 7 Days and Inbox have their own keywords too. Completed shows the last 60 days of server history once the optional v2 token is set (see [Setup](30-setup.md)); without it, only tasks completed through the workflow are tracked.

**Filter** - a TickTick filter, synced over with the v2 token (names, sidebar order, and rules - translated into the workflow's matcher) and searchable via the `f` scope. Smart lists ship built in; filters are yours - that is the whole difference. Tokenless fallback: a hand-written `filters_config.py`.

**Tag** - TickTick's cross-list label. Browse a list's tags from its ⌘ Actions menu, or search all tags via the `g` scope - the `tta` keyword jumps straight into it; nested tags need the optional v2 token.

**🅿️ Buffer** - a disposable local parking lot for tasks. ⌥⇧⏎ queues any task row; the `tbu` keyword opens the buffer, where you can tag, move, prioritize, or complete everything at once - or send the whole set into today's focus block. Clearing the buffer never touches the tasks themselves.

## Focusing

**Focus session** - a workflow timer ⏱️ or a real TickTick pomodoro 🍅, started via the `tfo` keyword or from a task's ⌘ Actions. Stopping a timer logs a genuine focus record to TickTick, pauses compressed out.

**Checkbox block** - the day's staging list, stored inside a focus task's description: task links as `- [ ] [Title](url)` checkboxes under a `### YYYY-MM-DD` header, blocks separated by `---`. When a new day's block is created, unchecked lines carry over to it; checked lines stay put as a permanent record, and the day's block rides along as the focus record's note.

**Sweep** - one action that completes the real TickTick task behind every ticked checkbox, across all blocks. Ticking a box is just staging; nothing completes until you sweep.

**Focus bar** - the floating pill showing the running timer/pomodoro and the current checkbox, with tick, expand, and hide controls. It is the one feature that needs PyObjC (`pip3 install pyobjc`); every other focus feature works without it.

## Plumbing

**Local cache** - every screen reads from JSON files under `~/.ticktick_alfred/cache/`, and every write patches the cache in place, so rows update instantly without a round-trip. The `tsy` keyword forces a full refresh; an optional LaunchAgent refreshes hourly (see [Settings & sync](90-settings-sync.md)).

**Keyword vs hotkey** - a keyword is what you type into Alfred (`tal`, `tse`, `tad`, …); all twenty are re-mappable in Configure Workflow. A hotkey is a global key combo you bind on the workflow canvas in Alfred; seven hotkey nodes ship unbound for the view family, Smart Lists, Calendar, and Focus.

## Related

- [Search](40-search.md) · [Browse & drill](41-browse-drill.md) · [Add](42-add.md) · [Actions](43-actions.md) · [Focus](44-focus.md)
- [Cheatsheet](95-cheatsheet.md) - every keyword and keystroke on one page
