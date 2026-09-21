# 🥘 Meal prep

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Plan your meals in Mela's calendar, and let one row mirror the cook week into TickTick: the Sunday routine, a grocery checklist per meal scaled to seven portions, and the weekly note's 🥘 bullet. See this week and the next thirteen, week by week.

**Keyword:** `tml` · **Hotkey:** (set in canvas) - or the **🥘 Meal Prep** row in the main menu (`tal`), or the **🥘 Meal Prep hub** row at the bottom of the Routines screen (`tro`).

## Why

One cooking session a week, three meals, seven portions each. The recipes live in the Mela app, and the plan is nicer to make there too: Mela's **Add to Calendar** (⌘⌥A on a recipe) puts the meal on a day. So Mela owns the plan, TickTick owns the doing. The hub reads the calendar, shows the weeks ahead, and one row syncs everything into TickTick. Nothing runs in the background.

## The moving parts

| Part | What it is | Who makes it |
|---|---|---|
| **The plan** | Calendar events made by Mela (**⌘⌥A Add to Calendar**), one per meal, on the Sunday it is cooked. Any calendar works: the hub reads them all and keeps only Mela's | You, in Mela |
| **The library** | One TickTick list (🍳Meal Prep) with one task per recipe: title `[Name](mela://recipe/…)`, tagged 🍳breakfast / 🍛lunch / 🌮snack, the recipe in the description | Mela + 🔄 Sync |
| **The routine** | The repeating Sunday 🥘 Meal Prep task in 🌅 Routines, or the copy you moved to another day | You |
| **The next cook** | One pointer subtask per meal Mela has on that day, under that 🥘 Meal Prep task, dated the day | 🔄 Sync |
| **Groceries** | One 🛒 checklist per meal as a subtask of your next 🛒 Groceries task, tagged 🛒groceries, dated its day, ingredients scaled to 7 portions | 🔄 Sync |
| **The weekly note** | A `🥘 Meal prep` bullet under 💿 Data with the week's meals | 🔄 Sync |

The slot of a meal (🍳 breakfast, 🍛 lunch, 🌮 snack) comes from the recipe's Mela category (**02 • Breakfast**, **01 • Meal**, **03 • Snack**), never from the time of the event. A recipe in none of those shows as 🍽️ and is kept, not dropped.

## Weeks

The cook day is whatever day your next **🥘 Meal Prep** task sits on in the Routines list. Usually that is Sunday, but when you move it to a Tuesday because of work, the hub and the sync follow the moved task, and they take the meals Mela has on that day. So plan the meals in Mela on the day you cook, then move the TickTick task to match if you need to; the time does not matter. For the week rows the hub still folds a cook day into the week it feeds: a meal cooked on Sun 27 Sep belongs to Week of 28 Sep, one cooked on Tue 22 Sep to Week of 21 Sep.

Groceries are not planned in Mela at all. The sync hangs one checklist per meal under your next **🛒 Groceries** task, dated its day, wherever you moved that one.

## The hub

| Row | ⏎ | Chords |
|---|---|---|
| 🥘 head | - | the next cook day (your 🥘 Meal Prep task, wherever you moved it), how many meals Mela has on it, the groceries day ("nothing planned in Mela on …" when empty) |
| 🍳 🍛 🌮 that day's meals | opens the recipe in **Mela** | the [meal row](#a-meal-row) chords |
| 📆 Next 13 weeks | the quarter, one row per week | ⌥ same |
| 🔄 Sync with Mela · n new · n to fill | recipes in, descriptions filled, the next cook's meals onto its prep task + groceries + note + every recipe dated as Mela has it | ⌥⇧ same |
| 🛒 Groceries · n open lists · day | the checklists under your next 🛒 Groceries task | ⌥ same |
| 📚 Breakfasts / Lunches / Snacks | that tag's library | ⌥ same |
| ℹ️ status | - | Mela's data age and how many meals the calendar holds, or why it can't be read |

### The quarter

**📆 Next 13 weeks** lists one row per week from this week on: `⭐️ Week of 21 Sep · 🍳 Breakfast Bagels · 🌮 Chicken subs`, this week starred, several meals joined with a dot. A week with nothing in the calendar reads `Week of 5 Oct · nothing planned` and cannot be entered; its subtitle reminds you: plan it in Mela, ⌘⌥A. Type to filter on the week or a meal name. ⏎ (or ⌥) opens that week: its head row and its meal rows, the same shape as the hub. ⌃ steps back.

### A meal row

The one row shape, on the hub, on a week and in the library:

| Chord | Does |
|---|---|
| ⏎ | Open the recipe in **Mela** |
| ⇧⏎ | Open the recipe's web page (dead, "No web page", when the recipe has none) |
| ⌥⌘⏎ | Copy the Mela link |
| ⌘⏎ | Actions - only when the meal is a task in your library; otherwise dead |
| ⌃⏎ | Back |

Plan rows carry the date (`· Sun 27 Sep`); library rows carry the cooked chip instead: **never cooked**, **cooked 2 weeks ago** or **next Sun 4 Oct**, read from the calendar. On library rows ⌥ still drills into subtasks when there are any.

## Syncing

**🔄 Sync with Mela** is the only writer, and it only runs when you press it. In order:

1. Every recipe categorised in Mela that the library does not have yet becomes a library task with its tag and the recipe text (up to forty a run).
2. Library tasks with an empty description get the recipe text (up to sixty a run).
3. The calendar is read, and the next cook is mirrored into TickTick: your next 🥘 Meal Prep task is found (the Sunday routine or the copy you moved to a weekday), every old pointer under any Meal Prep task goes (your own steps on it are never touched), one new pointer per meal Mela has on that day is minted under it dated that day, one 🛒 checklist per meal is made or kept under your next 🛒 Groceries task dated its day (a list already there stays, ticked items are never touched, lists for dropped meals go, a list sitting loose from an older press is remade under the task), and the 🥘 bullet is filled in the note of the week that cook feeds.
4. Every recipe task takes the date Mela has it planned on next: the nearest day on or after today, all-day, the day itself rather than the cook Sunday. A recipe with no upcoming plan loses its date. So the recipe task itself shows when you eat it, in search rows and in TickTick's calendar, for the whole quarter. Groceries, pointers and anything you made by hand are never touched.

The toast says what happened: `🔄 Mela · +2 recipes · 3 filled · cook Tue 22 Sep: 🍳 Breakfast Bagels · 🌮 Chicken subs · 2 grocery lists · 41 recipes dated`. A cook day with nothing in the calendar clears the pointers and the open grocery lists, and the note bullet says "nothing planned in Mela". If TickTick's hundred-requests-a-minute limit stops the dating pass, the toast says how many dates are left; press the row again a minute later.

Only the next cook is mirrored onto its prep task. The cooks after it live on the recipe tasks' dates and in the hub's 📆 view until their day comes round; press the row again once a cook is done.

## Portions

Every grocery line is scaled to seven portions from the recipe's yield. The yield comes from Mela's field when set, else from the text ("Makes 7", "6 Total", "Serves 4"), else estimated from the weight of the main protein (170 g a portion) and marked ≈, else the list is left unscaled with a ⚠️ note. The checklist's description says which. Amounts round the way a shopper would: 875 g, 2 3/4 tsp, 4 scallions. Section headers, "1. Heat the oil" steps and macro lines are dropped from the shopping list.

## Alfred needs Full Disk Access

The plan is read from the Mac's own calendar store, which macOS protects. If the hub's status row says the calendar store is unreadable, give Alfred **Full Disk Access** (System Settings › Privacy & Security › Full Disk Access) and open the hub again. Nothing is written to the calendar, ever.

Mela's database only reflects the phone once the Mac app has synced, so open Mela now and then; the status row shows the data age.

## Which calendar

Mela's "Add to Calendar" writes to whichever calendar you picked last, and the plan is read from exactly that one: the calendar Mela wrote to most recently. The status row names it. Two stale local calendars both called "Mela", left from the first experiments, are ignored that way; delete them in Calendar.app whenever you like. To pin the choice, put the calendar's name in `config.json` under `meal_calendars` (several names separated by commas).

Dates are written in each task's own time zone. TickTick shows an all-day task on the date its stamp has in that zone, and a task made through the API gets the account's zone (Europe/London) while the Mac runs on Europe/Berlin, which is how a Tuesday plan once showed up on Monday.

## What went away

The earlier version planned the week inside TickAL. Gone: the 🎲 Plan the week picker and its Surprise, the ✅ Commit, the cooked-history ledger, the 📥 Import and 📝 Fill rows (folded into 🔄 Sync), the hourly background imports and the `meal_wake_mela` switch. Plan in Mela, press one row.

## Limitations

- Sync is one way: Mela's calendar → TickTick. A meal moved or removed in TickTick does not move in Mela; change it in the calendar and sync again.
- The hub shows the calendar as it is on this Mac. An event added on the phone appears once iCloud has delivered it.
- A recipe you rename in TickTick keeps working (the link is the key); a recipe deleted in Mela gets a grocery list with no items and a note saying so.
- Groceries are TickTick checklists: tick items in the app; they carry no tags or dates of their own.
- Deleting the 🥘 bullet from a weekly note switches that note's block off (the periodic-note contract); notes minted before the hub existed get the bullet seeded once.

## Related

[Periodic notes](48-periodic.md) · [Browse & drill](41-browse-drill.md) · [Settings & sync](90-settings-sync.md)
