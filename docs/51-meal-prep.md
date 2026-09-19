# 🥘 Meal prep

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Plan the week's three meals from your recipe library, get a grocery checklist per meal scaled to seven portions, and let new recipes flow in from Mela on their own.

**Keyword:** `tml` · **Hotkey:** (set in canvas) - or the **🥘 Meal Prep** row in the main menu (`tal`), or the **🥘 Meal Prep hub** row at the bottom of the Routines screen (`tro`).

## Why

One cooking session a week, three meals, seven portions each. The recipes live in the Mela app; the plan lives in TickTick. Before this hub the plan meant copying a link out of Mela, adding it, tagging it, scheduling it, scheduling it again in Mela, and maybe pasting the recipe text by hand. Now the library fills itself from Mela, the week is three keystrokes, and the shopping list writes itself.

## The moving parts

| Part | What it is | Who makes it |
|---|---|---|
| **The library** | One TickTick list (🍳Meal Prep) with one task per recipe: title `[Name](mela://recipe/…)`, tagged 🍳breakfast / 🍛lunch / 🌮snack, the recipe in the description | Mela + the hourly sync |
| **The routine** | The repeating Sunday 🥘 Meal Prep task in 🌅 Routines | You, once |
| **This week** | Three pointer subtasks under the routine, one per meal, dated the cook Sunday | ✅ Commit |
| **Groceries** | One 🛒 checklist per meal in the library list, tagged 🛒groceries, due the Saturday before, ingredients scaled to 7 portions | ✅ Commit |
| **The weekly note** | A `🥘 Meal prep` bullet under 💿 Data with the three meals | ✅ Commit |

## The hub

| Row | ⏎ | Chords |
|---|---|---|
| 🥘 head | - | the cook Sunday, the grocery day, n/3 planned |
| 🍳 🍛 🌮 this week | opens the recipe in **Mela** | ⇧ cooked · ⌥ swap that one meal · ⌥⌘ copy link · ⌘ Actions |
| a slot not planned | the picker for that slot | ⌥ same |
| 🎲 Plan the week | the picker chain | ⌥ same |
| 🛒 Groceries · n open | this week's checklists | ⌥ same · ⌥⇧ rebuild them from Mela |
| 📥 Import from Mela · n new | imports every categorised recipe not in the library yet | (dead when nothing is new) |
| 📝 Fill descriptions · n missing | writes the recipe text into empty descriptions | (dead when none is missing) |
| 📚 Breakfasts / Lunches / Snacks | that tag's library | ⌥ same |
| ℹ️ status | - | Mela's data age, or why it can't be read |

## Planning a week

1. `tml` → **🎲 Plan the week**.
2. Pick a breakfast. Rows are least-recently-cooked first, with "never cooked" / "cooked 3 weeks ago" under each; type to search. **🎲 Surprise me** picks one that hasn't been cooked in four weeks.
3. Pick a lunch, then a snack, the same way. ⌃ steps back one pick.
4. **✅ Commit the plan.**

What commit does, in order: deletes last week's three pointers under the routine (your own steps on it are never touched), mints three new ones dated the cook Sunday, makes or keeps one 🛒 checklist per meal (a list for a meal you keep stays, ticked ones are never touched, lists for dropped meals go), fills the weekly note's 🥘 bullet, and remembers the week so "cooked 3 weeks ago" is true next time.

Change one meal later: ⌥ on it in the hub (or ⏎ it on the picker's summary) reopens only that slot; commit again.

## Portions

Every grocery line is scaled to seven portions from the recipe's yield. The yield comes from Mela's field when set, else from the text ("Makes 7", "6 Total", "Serves 4"), else estimated from the weight of the main protein (170 g a portion) and marked ≈, else the list is left unscaled with a ⚠️ note. The checklist's description says which. Amounts round the way a shopper would: 875 g, 2 3/4 tsp, 4 scallions. Section headers, "1. Heat the oil" steps and macro lines are dropped from the shopping list.

## Recipes flow in from Mela

Tag a recipe in Mela with **02 • Breakfast**, **01 • Meal** or **03 • Snack** and the hourly sync creates its library task with the matching tag and the recipe text, ten per run; **📥 Import** does up to forty now. Mela's database only reflects the phone once the Mac app has synced, so keep Mela open now and then (or set `meal_wake_mela` in config.json to let the sync launch it hidden when the data is older than six hours).

## Limitations

- The plan is for the routine's next Sunday. To plan two weeks ahead, plan again after the routine rolls.
- A recipe Vex renames in TickTick keeps working (the link is the key); a recipe deleted in Mela gets a grocery list with no items and a note saying so.
- Groceries are TickTick checklists: tick items in the app; they carry no tags or dates of their own.
- Mela's own calendar is not used; TickTick is the only place the week is planned.
- Deleting the 🥘 bullet from a weekly note switches that note's block off (the periodic-note contract); notes minted before the hub existed get the bullet seeded once.

## Related

[Periodic notes](48-periodic.md) · [Browse & drill](41-browse-drill.md) · [Settings & sync](90-settings-sync.md)
