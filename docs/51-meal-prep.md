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
| **The routine** | The repeating Sunday 🥘 Meal Prep task in 🌅 Routines | You, once |
| **This week** | One pointer subtask per planned meal under the routine, dated the cook Sunday | 🔄 Sync |
| **Groceries** | One 🛒 checklist per meal in the library list, tagged 🛒groceries, due the Saturday before, ingredients scaled to 7 portions | 🔄 Sync |
| **The weekly note** | A `🥘 Meal prep` bullet under 💿 Data with the week's meals | 🔄 Sync |

The slot of a meal (🍳 breakfast, 🍛 lunch, 🌮 snack) comes from the recipe's Mela category (**02 • Breakfast**, **01 • Meal**, **03 • Snack**), never from the time of the event. A recipe in none of those shows as 🍽️ and is kept, not dropped.

## Weeks

The cook day is Sunday. A meal on a Sunday is cooked that evening and eaten the week after, so the hub calls it **Week of** the Monday that follows: a meal on Sun 27 Sep belongs to Week of 28 Sep, cook Sun 27 Sep. Put the event on the Sunday you cook; the time does not matter.

## The hub

| Row | ⏎ | Chords |
|---|---|---|
| 🥘 head | - | the week, the cook Sunday, how many meals ("nothing planned in Mela" when empty) |
| 🍳 🍛 🌮 this week's meals | opens the recipe in **Mela** | the [meal row](#a-meal-row) chords |
| 📆 Next 13 weeks | the quarter, one row per week | ⌥ same |
| 🔄 Sync with Mela · n new · n to fill | recipes in, descriptions filled, next Sunday's meals onto the routine + groceries + note + every recipe dated as Mela has it | ⌥⇧ same |
| 🛒 Groceries · n open lists | this week's checklists | ⌥ same |
| 📚 Breakfasts / Lunches / Snacks | that tag's library | ⌥ same |
| ℹ️ status | - | Mela's data age and how many meals the calendar holds, or why it can't be read |

### The quarter

**📆 Next 13 weeks** lists one row per week from the routine's cook Sunday: `⭐️ Week of 28 Sep · 🍳 Hot Pockets`, this week starred, several meals joined with a dot. A week with nothing in the calendar reads `Week of 5 Oct · nothing planned` and cannot be entered; its subtitle reminds you: plan it in Mela, ⌘⌥A. Type to filter on the week or a meal name. ⏎ (or ⌥) opens that week: its head row and its meal rows, the same shape as the hub. ⌃ steps back.

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
3. The calendar is read, and the routine's cook week is mirrored into TickTick: last week's pointers under the routine go (your own steps on it are never touched), one new pointer per planned meal is minted dated the cook Sunday, one 🛒 checklist per meal is made or kept (a list for a meal that stays stays, ticked items are never touched, lists for dropped meals go), and the weekly note's 🥘 bullet is filled.
4. Every recipe task takes the date Mela has it planned on next: the nearest day on or after today, all-day, the day itself rather than the cook Sunday. A recipe with no upcoming plan loses its date. So the recipe task itself shows when you eat it, in search rows and in TickTick's calendar, for the whole quarter. Groceries, pointers and anything you made by hand are never touched.

The toast says what happened: `🔄 Mela · +2 recipes · 3 filled · Week of 28 Sep: 🍳 Hot Pockets · 2 grocery lists · 41 recipes dated`. A week with nothing in the calendar clears the pointers and the open grocery lists, and the note bullet says "nothing planned in Mela". If TickTick's hundred-requests-a-minute limit stops the dating pass, the toast says how many dates are left; press the row again a minute later.

Only the cook week is mirrored onto the routine. The weeks after it live on the recipe tasks' dates and in the hub's 📆 view until their Sunday comes round.

## Portions

Every grocery line is scaled to seven portions from the recipe's yield. The yield comes from Mela's field when set, else from the text ("Makes 7", "6 Total", "Serves 4"), else estimated from the weight of the main protein (170 g a portion) and marked ≈, else the list is left unscaled with a ⚠️ note. The checklist's description says which. Amounts round the way a shopper would: 875 g, 2 3/4 tsp, 4 scallions. Section headers, "1. Heat the oil" steps and macro lines are dropped from the shopping list.

## Alfred needs Full Disk Access

The plan is read from the Mac's own calendar store, which macOS protects. If the hub's status row says the calendar store is unreadable, give Alfred **Full Disk Access** (System Settings › Privacy & Security › Full Disk Access) and open the hub again. Nothing is written to the calendar, ever.

Mela's database only reflects the phone once the Mac app has synced, so open Mela now and then; the status row shows the data age.

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
