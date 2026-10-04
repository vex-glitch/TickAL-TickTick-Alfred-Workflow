# 🔑 OKRs

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Your OKR board, read back the way you laid it out: the months as rows, this month on top, each month's areas, objectives and key results under it, and the same board mirrored into your periodic notes and journals.

**Keyword:** `tok` · **Hotkey:** (set in canvas) - or the **🥅 OKRs** row in the main menu (`tal`).

## Why

OKRs are an inspiration board, not a plan of your working weeks. You set them once (or whenever), look at them every day, and review them every month, quarter and year. TickTick's kanban is the board; TickAL reads it and shows it back wherever you need to see it: a hub in Alfred, the 🥅 OKRs section of every periodic note, and the journal questions that ask about your objectives. TickAL never writes a date, never moves a card, and never adds one. The only thing it can change on the board is a key result's tick.

## The board

One TickTick list in **kanban view**, pointed at by `⚙️ Settings → OKR List` (a blank answer turns OKRs off). Its columns are months and years' goals, named like this:

| Column | Holds |
|---|---|
| `1️⃣ 2027` … `9️⃣ 2027`, `🔟 2027`, `1️⃣1️⃣ 2027`, `1️⃣2️⃣ 2027` | The month's cards |
| `2027 Goals` | The year's goals |

In a **month column** the card is an **area** (`🏔️ Work 1️⃣`, `🏔️ Personal 2️⃣`, … `🏔️ Manager 6️⃣`), its subtasks are **🥅 objectives**, and theirs are **🔑 key results**. In a **Goals column** the area's children are the **🏔️ year goals**. A title may carry a link (`🔑 [Grim Reaper](eagle://…)`, `🥅 [Onboard TickTicks](https://ticktick.com/…/tasks/…)`); the link is kept and shown with a 🔗.

Rules TickAL reads by:

- **The column is the schedule.** A card's month is the column of its top card, however you drag the subtasks. Dates on a card mean nothing to TickAL.
- **Same-named cards fold.** Two `🏔️ Learning 3️⃣` cards in one month read as one area; two `🥅 Learn Drawing` under it as one objective with every key result of both.
- **Progress is the only number**: ticked key results over all of them. A won't-do key result leaves both sides.
- **A year goal rolls up** the same-named monthly objectives of its year (`🏔️ Draw` over every month that has a `🥅 Draw`). A goal no month plans for reads plain.
- A `🥅` or `🔑` left at card level shows under an **Unsorted** separator; a card in a column that is not a month or a Goals column is counted on the hub's last row. Drag them where they belong in TickTick.

## The hub

Open it from the main menu or its keyword. The root lists the board's columns as rows, this month on top:

```
🔑OKRs · 23 months planned      Oct 2026 to Oct 2028 · board in TickTick
🔟 2026                          October 2026 · 3 objectives · 4/25 KRs
2026 Goals                       1 goal · VexOS
1️⃣1️⃣ 2026                       November 2026 · 2 objectives · 0/13 KRs
…
9️⃣ 2026                         September 2026 · 1 objective · 0/1 KRs · 1 open left
```

After this month come this year's Goals, the months ahead, and each later year's Goals before its January. Earlier months appear last, only while they still hold an open key result. Empty columns are left out.

⏎ on a month shows the column the way the board does: each area as a separator, its objectives as rows, their key results indented under them.

```
🏔️ VexOS 4️⃣                     4/25 KRs
🥅 Onboard TickTicks 🔗          3/5 KRs
      ✅ Finish periodic notes
      🔑 Audits
      🔑 Review
🥅 KeyCue/MIAs/Shared actions 🔗 0/16 KRs
      🔑 TickTick
```

| Key | Month or Goals row | Objective or goal row | Key result row |
|---|---|---|---|
| ⏎ | Its screen | The card in TickTick | The card in TickTick |
| ⌥ | Its screen | The task it links, in Alfred (when it links one) | The task or list it links |
| ⇧ | - | - | ✅ Done / ↩️ Reopen |
| ⌘ | - | Actions | Actions |
| ⌥⌘ | - | Copy the card's link | Copy the card's link |
| ⌃ | Back | Back | Back |

⏎ on a Goals row lists the year's goals under their areas, each with its roll-up (`0/12 KRs · 12 months`) or `no objectives yet`.

**Typing** on the root searches every objective and key result of the board; each hit names its month, area and objective. Typing on a month or Goals screen filters that column.

The head row of every screen opens the board in TickTick. The hub reads the board live when you open it (once every 45 seconds at most); a typed search reads the last read.

## In your periodic notes

Every periodic note carries a **🥅 OKRs** section at the top, right above 🏆 Goals. It mirrors the board: one bullet per column, the areas under it, the objectives under their area, the key results under their objective.

```
#### 🥅 OKRs
- 🔟 October • 4/25 KRs
	- 🏔️ VexOS 4️⃣ • 4/25 KRs
		- 🥅 Onboard TickTicks 3/5
			- ✅ Finish periodic notes
			- 🔑 Audits
			- 🔑 Review
		- 🥅 KeyCue/MIAs/Shared actions 0/16
			- 🔑 TickTick
			- +8 more
```

| Note | Shows |
|---|---|
| ☀️ Daily, ♻️ Weekly | This month, whole (a week belongs to the month its Thursday is in) |
| 🗓️ Monthly | Its month whole, then the other months of its quarter, objectives only |
| 🌓 Quarterly | The year's Goals column, then its three months, objectives only |
| 🎉 Yearly | The year's Goals column, then its planned months, objectives only |

Every name links to its card on the board. A won't-do key result is left out. Up to eight key results are listed per objective, then `+N more`; the hub holds them all. Delete the 🥅 OKRs section from a note and nothing OKR-related is written there again. A note minted before its period starts (next week's on Sunday, tomorrow's at shutdown) shows the board the moment it exists and is refreshed whenever you open the running note, so Sunday's board edits reach next week's note; a note whose period has ended keeps the board it had.

The yearly note's **🎯 Goals scorecard** gets one line per year goal: a bar and the roll-up of its monthly objectives (`▰▰▱▱▱ 5/12 • 12 months • Work 1️⃣`), or `no objectives yet`. The goals you set for the year stay in the same section.

**Journals.** The evening and weekly journals ask about this month's key results and objectives, the monthly about its objectives and the quarter's, the quarterly about its objectives and the year's goals, the yearly about the year's goals, each quoting the note's 🥅 OKRs section. A drawn prompt that names "the objective" or "the chosen goals" shows them under itself.

**Goal pickers.** Every goal picker opens with 🔮 rows: a day's and a week's offer this month's open key results then its objectives, a month's its objectives then key results, a quarter's the year's goals then the objectives of its months, a year's the year goals; the year's goals close every list, and typing a glyph (🏔️, 🥅, 🔑) lists that kind. ⏎ makes the card the goal: a link to it on the board, labelled as the board shows it. A daily goal picked from the board is never moved onto the day. Then **📋 Pick a goal** and the usual search.

## Actions on a card

⌘⏎ on a card of the board shows the ordinary task rows (complete, won't do, note, rename, move, tags, subtasks). The rows that would put a date or a place on it are left out: add to today or tomorrow, the day goal, schedule, reminder, create a CTA, add to focus. Moving a card to another month is a drag in TickTick.

## Routine steps

Each routine checklist can open an OKR screen with a Link verb (`alfred://runtrigger/com.vex.tickal/Link/?argument=view%3A<slot>`):

| Slot | Opens |
|---|---|
| `okr` | The hub |
| `okrdaily` · `okrweekly` · `okrmonthly` | This month's column |
| `okrquarterly` · `okrcarry` | The hub (the months ahead, and the earlier months with something still open) |

⌘⏎ → ☑️ TickTick Internals → **🔑 OKRs** copies the hub's link.

## Sync

The hourly sync keeps the board's completed cards cached beside its open ones, so the notes (which never read the network while they refresh) and the 04:30 run see the same board the hub shows. Nothing is written to TickTick by it.

## Limitations

- Key results are deliverables, ticked or not. There are no numeric key results.
- TickAL writes no dates and moves no cards. An objective is in a month because its card is in that column, and nowhere else.
- A year goal rolls up by name: `🏔️ Draw` finds `🥅 Draw`, not `🥅 Drawing`.

## Related

- [Periodic notes](48-periodic.md) - the notes the board feeds
- [Settings & sync](90-settings-sync.md) - the hourly sync that caches the board's completed cards
