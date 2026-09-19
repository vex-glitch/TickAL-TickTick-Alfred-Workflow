# 🥅 OKRs

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> A guiding-star plan of your goals inside TickTick: year objectives, objectives and key results on a timeline, with pace, progress and moves that keep the whole line intact.

**Keyword:** `tok` · **Hotkey:** (set in canvas) - or the **🥅 OKRs** row in the main menu (`tal`).

## Why

A plan is a forecast, and reality drifts from it. OKRs here are not a daily to-do list: they are the plan you set once a year (or whenever), review every quarter and month, and keep in view while the real work happens in your normal lists. Every OKR item is an all-day entry with no time, so it sits on top of your calendar, outside your time blocks: you see what the ideal plan says for today, and you adjust.

The plan lives in ONE TickTick list you schedule by hand in the **timeline view** - drag an item, stretch it, slide it. TickAL never replaces that. It reads the plan and keeps its arithmetic right: parents that cover their children, progress, pace, and moves that push the rest of the line along.

> [!IMPORTANT]
> OKRs are a workflow, not a single action - a list, three levels, a naming convention and a few automations. Give this page a full read before first use.

## The moving parts

| Part | What it is | Who makes it |
|---|---|---|
| **The plan list** | One TickTick list in timeline view holds every OKR item (`⚙️ Settings → OKR List`) | You, once |
| **🏔️ Y • Year objective** | The top level, one per area of your life - a step above objectives | You |
| **🥅 O • Objective** | Something you want to achieve - mostly a project | You, or ⌘⏎ → 🥅 Add to OKRs |
| **🔑 KR • Key result - CODE** | A deliverable that gets the objective there - a task or subtask, never a number | You, or 🥅 Add to OKRs |
| **The code** | A short suffix per objective (TickAL → `TA`), stamped on every KR under it | The automation - proposed, you can override |
| **Area tags** | The lanes of the timeline: the subtags of your `0️⃣Area` tag (plus the tags your Y/O items carry) | You, once |
| **Heal + auto-tick** | Parents re-cover their children; a KR whose linked task is done gets ticked | The automation - on hub open and on the hourly sync |
| **Countdowns** | One TickTick countdown per started objective, to its end | The automation - the same passes, and every schedule action |

## Planning copies

Everything in the plan list is a **copy that links to the real thing**:

- an objective links to its project's 📌CTA task (see [Projects](49-projects.md)), or to a list;
- a key result links to a task, a subtask or a note;
- a text-only item is fine too - link it later with **🔗 Link…**.

Moving a copy never moves the real task. The copy is the plan, the original is reality, and the gap between them is the point. When the real task is completed, its key result ticks itself.

## Set it up once

1. **Create the plan list** in TickTick and switch it to **timeline view**. Group it by tag if you want lanes.
2. **Point TickAL at it:** copy its id (`tse l <name>` → ⌘⏎ → **🆔 Copy id**), then `tal` → ⚙️ **Settings → OKR List** and paste. A blank answer turns OKRs off.
3. **Area tags:** OKRs use the subtags of your `0️⃣Area` tag as lanes. Nothing to register - they arrive with the next sync.

## The hub

Open it from the main menu or its keyword. The root shows your year objectives, then loose objectives, each with its span, progress and pace:

```
🥅 TickAL        Sep 19 - Oct 14 · 2/6 KRs · behind 2d · 40%
```

| Key | On a 🏔️ / 🥅 row | On a 🔑 row |
|---|---|---|
| ⏎ | Inside (its children) | Open the copy in TickTick |
| ⌥ | Inside | The real task in Alfred (its subtasks, or its list) |
| ⇧ | - | ✅ Done / ↩️ Reopen |
| ⌥⇧ | 📅 Schedule | 📅 Schedule |
| ⌘ | Actions | Actions |
| ⌃ | Back | Back |

**📈 Pace** opens four rows - 🌓 Quarter, 🗓️ Month, ♻️ Week, ☀️ Day - each counting the key results the plan puts in that period, how many are done, and how far behind the late ones are. ⏎ on a row shows that period's plan.

The last row is **⚖️ Capacity**: the key results your plan puts due in the next four weeks against the ones you ticked in the last four, per week (`plan 1.8/wk · done 0.5/wk`), with ⚠️ when two or more are due and the plan asks for more than half again what you finish. The week's plan (♻️ Week) shows it too, since that is where the weekly review plans the next week.

**↪️ Carry-over** shows up under 📈 Pace while a quarter leaves key results open - see [The quarter carry-over](#the-quarter-carry-over).

**Typing** in the hub searches every item. With no match (or below the matches), ➕ rows add what you typed: **➕ New objective / year objective** on the root, **➕ New objective** on a year objective, **➕ New KR** on an objective. A pipe adds several: `Draft spec | Review | Publish`. `=XY` sets a new objective's code.

## Scheduling and the ripple

**📅 Schedule** (⌥⇧, or ⌘⏎ → 📅 Schedule…) moves one item without breaking the line:

| Type | Does |
|---|---|
| `+3`, `+3d`, `+2w` | Extend by that much |
| `-1`, `-1d` | Pull the end in |
| 🌙 Tomorrow | Start tomorrow, same length |
| `12.10`, `next mon` | Start on that date, same length |

Every later item in the same year objective moves by the same amount, so the plan's total length stays true. Parents stretch to cover their children. Extending an objective extends its last open key result. Done items never move. Dates in the past, times of day, and pull-ins longer than the item are refused - the row tells you why before you press ⏎.

A drag in the TickTick timeline does not ripple (nothing can see a drag happen), but the parent re-covers its children on the next heal.

## Adding to the plan

**⌘⏎ → 🥅 Add to OKRs** on any task, note or list opens one screen:

- **🔑 KR under 🥅 (an objective)** - one row per open objective, the current ones first;
- **🥅 New objective** - on its own, or under a year objective;
- **🏔️ New year objective**.

The copy is made undated (drag it into place), named with the prefix and code, and a new objective or year objective goes straight to the tag picker. A key result takes its objective's tag. Importing a project list links its 📌CTA task when it has one. Something already in the plan says so and opens the existing copy instead of making a second one.

## Actions on an OKR item

⌘⏎ on any item in the plan shows its own rows first - **📅 Schedule…**, **🔗 Link…**, **🏷 Tag…**, **🔑 Add KRs** (objectives), **✔️ Done** (key results) - and drops the generic ones that would drag a planning copy into a time block (add to today, day goal, timed schedule, reminders, focus).

**🏷 Tag…** offers only plan tags (the area subtags and the tags your year objectives and objectives carry). It replaces the plan tag and keeps any other tag; on an objective, its open key results follow.

## In your periodic notes

Every periodic note carries a **🥅 OKRs** section at the top, right above 🏆 Goals: one bullet per period, from the year down to the note's own, with that period's key results done and how far behind it runs, and the plan items under it, one per line:

```
- 🗓️ Sep • 0/7 KRs • 🔴 1d
	- 🥅 Onboard TickTicks 0/5 🔴 1d
	- 🥅 TickAL 0/6
- ♻️ W38 • 0/2 KRs • 🔴 1d
	- 🔑 Finish periodic notes 🔴 1d
	- 🔑 Goals wf
```

The daily shows all five periods, the weekly four, the monthly three, the quarterly two, the yearly one. It is the plan only: the goals you pick stay in 🏆 Goals below. The yearly note's 🎯 Goals scorecard lists every objective with its progress bar and span. Delete the 🥅 OKRs section from a note and nothing OKR-related is written there again.

**Aligned work (weekly note):** the weekly note's 📊 Stats carries

```
- 🥅 Aligned: 68% • 17/25 • 🟢 ▲ 7 pts
	- 🥅 TickAL • 12 done • 4h 10m
	- 🥅 Onboard TickTicks • 5 done • 1h 05m
```

Of the tasks you finished this week (routine lists, the plan's own copies and won't-dos left out), how many served an objective, the change against last week in points, and one line per objective: its done count and the focus time that went into it. A task serves an objective when it is the real thing a plan item links, a subtask of one at any depth, or in a list an item links. An objective linked to its project's 📌CTA covers the whole project list, and the CTA's focus counts even after the CTA is re-made. Links are the only join: until your plan items link something, the line says `no linked OKR items`. Delete the bullet and it stays gone.

**Setting goals from the plan:** every goal picker opens with 🔮 rows, the plan for that period. ⏎ on one makes it the goal - aimed at the real task the key result links, never at the planning copy. Then **📋 Pick a goal**, and the usual search below it (which never offers planning copies).

## The quarter carry-over

When a quarter ends, every key result it leaves open gets one decision, so nothing leaks silently into the next one. During a quarter's last two weeks (and after it ends, while its leftovers are still open) the hub shows **↪️ Carry-over · Q3 · 5 open**. It lists every open, dated key result that ends by the quarter's last day, earlier quarters' leftovers included. ⏎ on one opens its three choices:

| Choice | Does |
|---|---|
| ↪️ Carry into Q4 | Starts it on the next quarter's first day (today, when that day is already past), same length. The rest of its line moves along, like any schedule action. |
| 🚫 Won't do | TickTick's won't do: out of progress and pace. Undo it from 🚫 Won't Do. |
| 💤 Someday | Takes its dates away: off the timeline, still in the plan and in its objective's count. |

On the list, ⇧ still ticks a key result done and ⌥⇧ still schedules it to any date. After each decision the list reopens with the next leftover on top. The 🌓 Quarterly Review's checklist opens this screen (see below).

## Countdowns

Every objective and year objective that has **started** gets a TickTick countdown to its end, named like the plan item (`🥅 TickAL`). It moves when the end moves, and it is archived when the objective is done, won't do, deleted or loses its dates. Archive or delete one yourself and it is never made again. The countdowns show in TickTick's countdown view, the ⏳ hub and the daily note's ⏳ Countdowns. They need the v2 token.

## OKR steps in your routines

Each routine checklist can open an OKR screen with a Link verb (`alfred://runtrigger/com.vex.tickal/Link/?argument=view%3A<slot>`):

| Slot | Opens |
|---|---|
| `okr` | The hub |
| `okrdaily` · `okrweekly` · `okrmonthly` · `okrquarterly` | That 📈 Pace period's plan |
| `okrcarry` | The quarter carry-over |

⌘⏎ → ☑️ TickTick Internals → **🥅 OKRs** copies the hub's link.

## Automations

- **Heal:** a parent always runs from its first dated child's start to its last dated child's end.
- **Auto-tick:** a key result that links a single task is ticked when that task is completed.
- **Countdowns:** kept in step with the started objectives (above).

All three run when you open the hub (at most every five minutes) and with the optional hourly sync ([Settings & sync](90-settings-sync.md)). Writes only happen from a complete live read of the list; anything less and the automation waits.

## Limitations

- Key results are deliverables. There are no numeric key results; the only number is progress (ticked key results over all of them).
- A drag in the timeline does not ripple.
- Pulling the line in mirrors pushing it out: later items move earlier by the same amount.

## Related

- [Projects](49-projects.md) - the 📌CTA tasks objectives link to
- [Periodic notes](48-periodic.md) - the notes the plan feeds
- [Settings & sync](90-settings-sync.md) - the hourly sync that runs the heal
