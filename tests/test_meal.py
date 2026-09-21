#!/usr/bin/env python3
"""Unit suite for src/meal.py (the 🥘 model) and src/meal_notes.py (the
weekly note's bullet). Pure: no network, no cache, no Calendar store and
no Mela DB - the plan rows are tiny duck-typed objects (date/uuid/title,
the mela_cal.Planned shape) and the recipes duck-type mela.Recipe
(id/title/link/categories). Pins, in order: the picker era stays gone,
the title grammar, the library as the screens see it, week arithmetic,
slot_for_recipe, the plan folded into weeks, cooked history off the
calendar, the sync verb (its toast's rated / ratings_left too), meal_notes
over the weekly template, zones /
upcoming / batch, and (2026-09-21) rating, comments and cooked: the
star grammar, the head block, set_rating / add_comment on the sample
layout, Mela's "Rating:" line adopted, the payloads, the chips and the
library order with the 👨‍🍳cooked tag. Run: python3 tests/test_meal.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import meal                                   # noqa: E402
import meal_notes                             # noqa: E402
import periodic_model as pm                   # noqa: E402
import periodic_sections as ps                # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


U1 = "A84938FE-88F9-467C-9D01-745D92E75EE1"
U2 = "62946285-B1C4-4A50-BB17-6CA9B1417EA3"
U3 = "7EB6A2B6-0C98-4B8A-B10F-86E0C3CCA3D3"
U4 = "F3F9B0BC-E4FD-4CE0-A463-608A5603C218"
U5 = "0B2B9C6E-4C2A-4D6E-9B0A-1C2D3E4F5A6B"
LIST, RLIST, RID = "5eed00000000000000000a01", "5eed00000000000000000b01", "5eed00000000000000000b02"

# ── the picker era is gone ───────────────────────────────────────────────────
for gone in ("ledger_add", "ledger_week", "surprise", "surprise_pool", "SURPRISE_WEEKS",
             "sort_for_pick", "slots_from_ids", "ctx_for", "next_slot", "commit_payload",
             "outcome_text"):
    check(f"removed: {gone}", not hasattr(meal, gone))

# ── title grammar ─────────────────────────────────────────────────────────────
check("parse_title: plain", meal.parse_title(f"[Beef Bulgogi](mela://recipe/{U1.lower()})") == ("Beef Bulgogi", U1))
check("parse_title: app-escaped", meal.parse_title(f"\\[Beef Bulgogi\\]\\(mela://recipe/{U1}\\)") == ("Beef Bulgogi", U1))
check("parse_title: pointer glyph", meal.parse_title(f"🍛 [Beef Bulgogi](mela://recipe/{U1})") == ("Beef Bulgogi", U1))
check("parse_title: none", meal.parse_title("Buy milk") is None and meal.parse_title("") is None)
check("link_uuid", meal.link_uuid(f"x mela://recipe/{U1.lower()} y") == U1 and meal.link_uuid("nope") is None)
check("md_link strips brackets", meal.md_link("A [b] \\c", U1) == f"[A b c](mela://recipe/{U1})")
check("md_link empty name", meal.md_link("", U1) == f"[Recipe](mela://recipe/{U1})")
ptr = meal.pointer_title("b", "Oats", U2)
check("pointer_title", ptr == f"🍳 [Oats](mela://recipe/{U2})", ptr)
check("is_pointer", meal.is_pointer(ptr) and meal.is_pointer(f"🌮 [X](mela://recipe/{U3})"))
check("is_pointer: library entry is not one", not meal.is_pointer(f"[Oats](mela://recipe/{U2})"))
check("is_pointer: grocery is not one", not meal.is_pointer(meal.grocery_title("Oats", U2)))
check("pointer_slot", meal.pointer_slot(ptr) == "b" and meal.pointer_slot(f"🌮 [X](mela://recipe/{U3})") == "s")
# slot "x" = 🍽️: a planned recipe outside the three Mela categories
xptr = meal.pointer_title("x", "Cake", U4)
check("pointer_title: x → 🍽️", xptr == f"🍽️ [Cake](mela://recipe/{U4})", xptr)
check("pointer_title: unknown key falls to 🍽️", meal.pointer_title("zz", "Cake", U4) == xptr)
check("is_pointer: 🍽️ with VS16", meal.is_pointer(xptr))
check("is_pointer: 🍽 without VS16 (the app drops it)", meal.is_pointer(xptr.replace("\ufe0f", "")))
check("pointer_slot: x both ways", meal.pointer_slot(xptr) == "x" and meal.pointer_slot(xptr.replace("\ufe0f", "")) == "x")
check("slot(): x known, SLOTS untouched", meal.slot("x") == meal.SLOT_X and meal.slot("q") is None
      and meal.SLOT_KEYS == ("b", "l", "s") and meal.ALL_SLOT_KEYS == ("b", "l", "s", "x"))
check("GLYPH", meal.GLYPH == {"b": "🍳", "l": "🍛", "s": "🌮", "x": "🍽️"})
check("grocery_title / is_grocery", meal.is_grocery(meal.grocery_title("Oats", U2)) and not meal.is_grocery(ptr))
check("is_library_title", meal.is_library_title(f"[Oats](mela://recipe/{U2})") and not meal.is_library_title(ptr)
      and not meal.is_library_title(xptr))
check("slot_of_tags", meal.slot_of_tags(["🍛lunch", "asian"]) == "l" and meal.slot_of_tags(["🍳BREAKFAST"]) == "b"
      and meal.slot_of_tags(["🛒groceries"]) is None and meal.slot_of_tags(None) is None)
check("slot_of_tags: SLOTS order wins", meal.slot_of_tags(["🌮snack", "🍳breakfast"]) == "b")


# ── the library as the screens see it ────────────────────────────────────────
def T(tid, title, pid=LIST, tags=(), status=0, parent=None, **kw):
    t = {"id": tid, "projectId": pid, "title": title, "tags": list(tags), "status": status,
         "parentId": parent, "content": ""}
    t.update(kw)
    return t


TASKS = [
    T("t1", f"[Oats](mela://recipe/{U2})", tags=["🍳breakfast"]),
    T("t2", f"[Beef Bulgogi](mela://recipe/{U1})", tags=["🍛lunch", "asian"], content="body"),
    T("t3", f"[Pockets](mela://recipe/{U3})", tags=["🌮snack"]),
    T("t4", "[Untagged](mela://recipe/11111111-1111-1111-1111-111111111111)"),
    T("t5", f"[Done](mela://recipe/{U1})", tags=["🍛lunch"], status=2),
    T("t6", "Food Prep"),
    T("g1", meal.grocery_title("Oats", U2), tags=["🛒groceries"], dueDate="2026-09-26T00:00:00+0000"),
    T("g2", meal.grocery_title("Old", "22222222-2222-2222-2222-222222222222"), tags=["🛒groceries"]),
    T("p1", meal.pointer_title("b", "Oats", U2), pid=RLIST, parent=RID),
    T("p2", meal.pointer_title("l", "Beef Bulgogi", U1), pid=RLIST, parent=RID),
    T("p3", meal.pointer_title("s", "Ghost", U3), pid=RLIST, parent=RID, repeatTaskId="arch"),
    T("p4", "1. Combine everything", pid=RLIST, parent=RID),
    T("p5", meal.pointer_title("s", "Other list", U3), pid=LIST, parent=RID),
    T("p6", meal.pointer_title("x", "Cake", U4), pid=RLIST, parent=RID),
    T("p7", meal.pointer_title("b", "Second breakfast", U5), pid=RLIST, parent=RID),
    T("r0", "🥘 Meal Prep", pid=RLIST, startDate="2026-09-27T17:00:00.000+0000"),
]
ents = meal.library_entries(TASKS, LIST)
check("library_entries: the three tagged + the untagged", [e["tid"] for e in ents] == ["t1", "t2", "t3", "t4"], [e["tid"] for e in ents])
check("library_entries: slot, uuid, content", ents[1]["slot"] == "l" and ents[1]["uuid"] == U1 and ents[1]["content"] == "body")
check("library_entries: untagged has no slot", ents[3]["slot"] is None)
by = meal.entries_by_slot(ents)
check("entries_by_slot", [e["tid"] for e in by["b"]] == ["t1"] and [e["tid"] for e in by["s"]] == ["t3"])
kids = meal.pointers_of(TASKS, RID)
check("pointers_of: by slot incl. x, archived + strangers skipped", sorted(kids) == ["b", "b:p7", "l", "s", "x"]
      and kids["b"]["id"] == "p1" and kids["s"]["id"] == "p5" and kids["x"]["id"] == "p6", sorted(kids))
check("pointers_of: a twin slot rides under key:tid, so .values() is every pointer",
      kids["b:p7"]["id"] == "p7" and sorted(t["id"] for t in kids.values()) == ["p1", "p2", "p5", "p6", "p7"])
check("pointers_of: archived occurrence never counts", all(k["id"] != "p3" for k in kids.values()))
groc = meal.groceries_of(TASKS, LIST)
check("groceries_of", set(groc) == {U2, "22222222-2222-2222-2222-222222222222"} and groc[U2]["id"] == "g1")

# ── week arithmetic ──────────────────────────────────────────────────────────
sat, sun, mon = date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)
check("next_sunday", meal.next_sunday(sat) == sun and meal.next_sunday(sun) == sun and meal.next_sunday(mon) == date(2026, 9, 27))
# cook_week_of over all seven weekdays: Sun 20 Sep .. Sat 26 Sep → 20 Sep, Sun 27 → 27
week = [meal.cook_week_of(sun + timedelta(days=i)) for i in range(8)]
check("cook_week_of: Sun..Sat fold to that Sunday", week[:7] == [sun] * 7, week)
check("cook_week_of: the next Sunday is its own", week[7] == date(2026, 9, 27))
check("cook_week_of: a Monday folds back a day", meal.cook_week_of(mon) == sun and meal.cook_week_of(sat) == date(2026, 9, 13))
check("cook_week_of: matches the given formula", all(meal.cook_week_of(d) == d - timedelta(days=(d.weekday() + 1) % 7)
                                                     for d in (sun + timedelta(days=i) for i in range(-10, 30))))
check("cook_sunday: the routine's occurrence when it is a Sunday ahead",
      meal.cook_sunday({"startDate": "2026-09-27T17:00:00.000+0000"}, sat) == date(2026, 9, 27))
check("cook_sunday: a stale (past) occurrence → next Sunday",
      meal.cook_sunday({"dueDate": "2026-09-13T17:00:00+0000"}, sat) == sun)
check("cook_sunday: undated → next Sunday", meal.cook_sunday({}, mon) == date(2026, 9, 27))
check("cook_sunday: a non-Sunday date is not trusted",
      meal.cook_sunday({"startDate": "2026-09-23T17:00:00+0000"}, sat) == sun)
check("grocery_day: the Saturday before, or today", meal.grocery_day(sun, sat) == sat and meal.grocery_day(sun, sun) == sun
      and meal.grocery_day(date(2026, 9, 27), sat) == date(2026, 9, 26))
check("note_day + week_label", meal.note_day(sun) == mon and meal.week_label(sun) == "Week of 21 Sep")
check("api_day: local midnight written in UTC, round-trips to the same day",
      meal.api_day(sun).endswith("+0000") and "T" in meal.api_day(sun) and meal._local_date(meal.api_day(sun)) == sun,
      meal.api_day(sun))


# ── slot_for_recipe (duck-typed mela.Recipe) ─────────────────────────────────
class R:
    def __init__(self, id, title, categories=(), link=""):
        self.id, self.title, self.categories, self.link = id, title, list(categories), link


check("slot_for_recipe: breakfast", meal.slot_for_recipe(R(U2, "Oats", ["02 • Breakfast"])) == "b")
check("slot_for_recipe: meal → lunch", meal.slot_for_recipe(R(U1, "Bulgogi", ["01 • Meal", "Asian"])) == "l")
check("slot_for_recipe: snack", meal.slot_for_recipe(R(U3, "Pockets", ["03 • Snack"])) == "s")
check("slot_for_recipe: none of the three → x", meal.slot_for_recipe(R(U4, "Cake", ["Dessert"])) == "x"
      and meal.slot_for_recipe(R(U4, "Cake", [])) == "x")
check("slot_for_recipe: None recipe → x", meal.slot_for_recipe(None) == "x")
check("slot_for_recipe: the NN • prefix is optional", meal.slot_for_recipe(R(U2, "Oats", ["breakfast"])) == "b")
check("slot_for_recipe: a custom tag map", meal.slot_for_recipe(R(U4, "Cake", ["Sweets"]), {"Sweets": "🌮snack"}) == "s")
check("slot_for_recipe: an unknown tag in the map → x", meal.slot_for_recipe(R(U4, "Cake", ["Sweets"]), {"Sweets": "🍰cake"}) == "x")


# ── the plan, folded into weeks ──────────────────────────────────────────────
class P:
    """A mela_cal.Planned-like row: date, uuid, title."""
    def __init__(self, d, uuid, title=""):
        self.date, self.uuid, self.title = d, uuid, title


S27, S04, S11 = date(2026, 9, 27), date(2026, 10, 4), date(2026, 10, 11)
RECIPES = {
    U2: R(U2, "Oats", ["02 • Breakfast"], link="https://example.com/oats"),
    U1: R(U1, "Beef Bulgogi", ["01 • Meal"]),
    U3: R(U3, "Pockets", ["03 • Snack"], link="https://example.com/pockets"),
    U4: R(U4, "Cake", ["Dessert"]),
}
PLANNED = [
    P(S27, U3, "Pockets"),                       # snack first in the list, sorted last of the three
    P(S27, U2.lower(), "Oats"),                   # lowercase uuid in the calendar url
    P(S27, U1, "Beef Bulgogi"),
    P(S27 + timedelta(days=3), U4, "Cake"),       # a Wednesday: still the 27 Sep cook week
    P(S27, U4, "Cake"),                           # Add to Calendar fired twice: one meal
    P(S11, U5, "Mystery Pie"),                    # Mela no longer knows this uuid
    P(S11, U2, "Oats"),
    P(date(2026, 9, 13), U1, "Beef Bulgogi"),     # the past: cooked history
    P(date(2026, 9, 6), U2, "Oats"),
]
weeks = meal.weeks_plan(PLANNED, RECIPES, None, ents, S27, 3)
check("weeks_plan: every week present, in order", [w.sunday for w in weeks] == [S27, S04, S11])
check("weeks_plan: Week.label", weeks[0].label == "Week of 28 Sep")
w0 = weeks[0].meals
check("weeks_plan: b, l, s, x order", [m.slot for m in w0] == ["b", "l", "s", "x"], [m.slot for m in w0])
check("weeks_plan: names from the recipe", [m.name for m in w0] == ["Oats", "Beef Bulgogi", "Pockets", "Cake"])
check("weeks_plan: uuid upper-cased", w0[0].uuid == U2)
check("weeks_plan: a Wednesday folds to the Sunday before, twice-planned = one meal, earliest date kept",
      len(w0) == 4 and w0[3].date == S27)
check("weeks_plan: web from the recipe link, '' when none", w0[0].web == "https://example.com/oats" and w0[1].web == "")
check("weeks_plan: tid/pid resolve through the library entries", w0[0].tid == "t1" and w0[0].pid == LIST
      and w0[3].tid == "" and w0[3].pid == "")
check("weeks_plan: an empty week is present and empty", weeks[1].meals == [])
w2 = weeks[2].meals
check("weeks_plan: an unknown recipe = a 🍽️ meal named after the event, no web",
      [(m.slot, m.name) for m in w2] == [("b", "Oats"), ("x", "Mystery Pie")] and w2[1].web == "" and w2[1].uuid == U5)
check("Meal.glyph / Meal.url", w0[0].glyph == "🍳" and w2[1].glyph == "🍽️" and w0[0].url == f"mela://recipe/{U2}")
check("weeks_plan: first_sunday given as a weekday folds back", meal.weeks_plan(PLANNED, RECIPES, None, ents, S27 + timedelta(days=2), 1)[0].sunday == S27)
check("weeks_plan: n_weeks 0 → [], no planned → empty weeks",
      meal.weeks_plan(PLANNED, RECIPES, None, ents, S27, 0) == []
      and [w.meals for w in meal.weeks_plan([], RECIPES, None, ents, S27, 2)] == [[], []])
check("weeks_plan: a row without uuid is skipped", meal.weeks_plan([P(S27, "", "Blank")], RECIPES, None, [], S27, 1)[0].meals == [])
check("weeks_plan: same slot twice keeps both, by date then name",
      [m.name for m in meal.weeks_plan([P(S27, U2, "Oats"), P(S27, U5, "Bagels")],
                                        {U2: RECIPES[U2], U5: R(U5, "Bagels", ["02 • Breakfast"])}, None, [], S27, 1)[0].meals]
      == ["Bagels", "Oats"])
check("weeks_plan: a custom tag map decides the slot",
      meal.weeks_plan([P(S27, U4, "Cake")], RECIPES, {"Dessert": "🌮snack"}, [], S27, 1)[0].meals[0].slot == "s")
wm = meal.week_meals(PLANNED, RECIPES, None, ents, S27)
check("week_meals: the one week", isinstance(wm, meal.Week) and wm.sunday == S27 and [m.name for m in wm.meals] == [m.name for m in w0])
check("week_meals: an empty week", meal.week_meals(PLANNED, RECIPES, None, ents, S04).meals == [])

# ── cooked history off the calendar ──────────────────────────────────────────
today = date(2026, 9, 28)      # Monday after the 27 Sep cooking
check("last_cooked: 0 = this cook week", meal.last_cooked(PLANNED, U2, today) == 0 and meal.last_cooked(PLANNED, U4, today) == 0)
check("last_cooked: whole cook-weeks (13 Sep vs the 20 Sep cook week = 1)", meal.last_cooked(PLANNED, U1, date(2026, 9, 21)) == 1
      and meal.last_cooked(PLANNED, U2, date(2026, 9, 21)) == 2)
check("last_cooked: the future never counts", meal.last_cooked(PLANNED, U5, today) is None
      and meal.last_cooked(PLANNED, U2, date(2026, 9, 5)) is None)
check("last_cooked: the cook Sunday itself is 0, the Saturday before still counts the old week",
      meal.last_cooked(PLANNED, U2, S27) == 0 and meal.last_cooked(PLANNED, U2, date(2026, 9, 26)) == 2)
check("last_cooked: never / blank / lowercase", meal.last_cooked(PLANNED, "zz", today) is None
      and meal.last_cooked(PLANNED, "", today) is None and meal.last_cooked(PLANNED, U1.lower(), date(2026, 9, 21)) == 1
      and meal.last_cooked([], U1, today) is None)
check("next_planned: the first day after today", meal.next_planned(PLANNED, U2, today) == S11
      and meal.next_planned(PLANNED, U2, date(2026, 9, 20)) == S27)
check("next_planned: the day itself is not next", meal.next_planned(PLANNED, U1, S27) is None)
check("next_planned: none / blank", meal.next_planned(PLANNED, U3, today) is None and meal.next_planned(PLANNED, "", today) is None)
check("cooked_chip", meal.cooked_chip(None) == "never cooked" and meal.cooked_chip(0) == "cooked this week"
      and meal.cooked_chip(1) == "cooked last week" and meal.cooked_chip(3) == "cooked 3 weeks ago")
check("lib_chip", meal.lib_chip(PLANNED, U2, today) == "cooked this week · next Sun 11 Oct"
      and meal.lib_chip(PLANNED, U3, today) == "cooked this week" and meal.lib_chip(PLANNED, "zz", today) == "never cooked")
pool = [{"tid": "a", "uuid": U2, "name": "Oats"}, {"tid": "b", "uuid": "N1", "name": "Zebra"},
        {"tid": "c", "uuid": U1, "name": "Bulgogi"}, {"tid": "d", "uuid": "N2", "name": "Apple"}]
order = [e["tid"] for e in meal.sort_for_lib(pool, PLANNED, date(2026, 9, 21))]
check("sort_for_lib: never first (by name), then least recently cooked", order == ["d", "b", "a", "c"], order)

# ── the sync verb ────────────────────────────────────────────────────────────
check("sync_payload", meal.sync_payload() == {"back": "ctx:meal"} and meal.sync_payload("ctx:mealq") == {"back": "ctx:mealq"})
txt = meal.sync_text(S27, [w0[0]], 2, 2, 3)
check("sync_text: the contract line", txt == "🔄 Mela · +2 recipes · 3 filled · cook Sun 27 Sep: 🍳 Oats · 2 grocery lists", txt)
check("sync_text: a count, singular", meal.sync_text(S27, 1, 1, 1, 0) == "🔄 Mela · +1 recipe · cook Sun 27 Sep: 1 meal · 1 grocery list")
check("sync_text: nothing new, nothing planned", meal.sync_text(S27, 0, 0, 0, 0)
      == "🔄 Mela · nothing new · cook Sun 27 Sep: nothing planned in Mela · 0 grocery lists")
check("sync_text: (slot, name) pairs", "🍳 Oats · 🍽️ Cake" in meal.sync_text(S27, [("b", "Oats"), ("x", "Cake")], 2, 0, 0))
check("sync_text: note not written", meal.sync_text(S27, 3, 3, 0, 0, note_ok=False).endswith(" · note not written"))
check("sync_text: ratings from Mela, worded like the dates",
      meal.sync_text(S27, 1, 1, 0, 0, dated=2, rated=2).endswith(" · 2 recipes dated · 2 ratings from Mela")
      and meal.sync_text(S27, 1, 1, 0, 0, rated=1).endswith(" · 1 grocery list · 1 rating from Mela"))
check("sync_text: ratings left · run again, and nothing said when both are 0",
      meal.sync_text(S27, 1, 1, 0, 0, rated=1, ratings_left=3).endswith(" · 1 rating from Mela · 3 ratings left · run again")
      and "rating" not in meal.sync_text(S27, 1, 1, 0, 0, rated=0, ratings_left=0))

# ── meal_notes over the shipped weekly template ───────────────────────────────
picks = {"b": {"tid": "t1", "uuid": U2, "name": "Oats"}, "l": {"tid": "t2", "uuid": U1, "name": "Bulgogi"}}
TPL = open(os.path.join(ROOT, "src", "periodic_templates", "weekly.md"), encoding="utf-8").read()
doc = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
check("template carries the bullet under 💿 Data", ps.find(doc, pm.SEC_MEALPREP, within=pm.SEC_WK_DATA) is not None)
check("SECTION_SCOPE knows it", pm.SECTION_SCOPE["weekly"].get(pm.SEC_MEALPREP) == pm.SEC_WK_DATA)
lines = meal_notes.block_lines(picks)
check("block_lines: three plain bullets, link last, a missing slot named",
      lines == [f"- 🍳 [Oats](mela://recipe/{U2})", f"- 🍛 [Bulgogi](mela://recipe/{U1})", "- 🌮 _(not planned)_"], lines)
check("write_block writes", meal_notes.write_block(doc, lines) is True)
check("write_block is idempotent", meal_notes.write_block(doc, lines) is False)
check("read_block", meal_notes.read_block(doc) == lines)
txt = ps.serialize_sections(doc)
i = txt.index("- 🥘 Meal prep")
check("lines sit under the bullet, tab-indented", txt[i:].split("\n")[1] == f"\t- 🍳 [Oats](mela://recipe/{U2})", txt[i:i + 80])
check("round trip", ps.serialize_sections(ps.parse_sections(txt)) == txt)
check("rewrite changes it", meal_notes.write_block(doc, meal_notes.block_lines({"b": picks["b"]})) is True)
# kill switch: the bullet AND its body gone from a note minted after the feature
gone = "\n".join(l for l in pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}).split("\n")
                 if "🥘 Meal prep" not in l)
d2 = ps.parse_sections(gone)
check("kill switch: a new note without the bullet is left alone",
      meal_notes.write_block(d2, lines, live={"createdTime": "2026-10-05T10:00:00+0000"}) is False
      and "🥘" not in ps.serialize_sections(d2))
check("kill switch: no createdTime = left alone", meal_notes.write_block(d2, lines) is False)
d3 = ps.parse_sections(gone)
check("seed: an older note gets the bullet once",
      meal_notes.write_block(d3, lines, live={"createdTime": "2026-09-14T10:00:00.000+0000"}) is True
      and meal_notes.read_block(d3) == lines)
t3 = ps.serialize_sections(d3)
check("seed lands at the end of 💿 Data, before the divider",
      "- 👽 People\n\n- 🥘 Meal prep\n\t- 🍳" in t3, t3[t3.index("- 👽 People"):t3.index("- 👽 People") + 60])
check("seed is idempotent", meal_notes.write_block(d3, lines, live={"createdTime": "2026-09-14T10:00:00.000+0000"}) is False)
old_layout = ps.parse_sections("### A\n- x\n")
check("no 💿 Data group = never written", meal_notes.write_block(old_layout, lines, live={"createdTime": "2026-01-01T00:00:00+0000"}) is False)


# ── zones, the upcoming occurrence, the batch (Vex 2026-09-21) ───────────────
print("-- zones / upcoming / batch")
from zoneinfo import ZoneInfo
lon = {"timeZone": "Europe/London", "startDate": "2026-09-21T22:00:00.000+0000"}
ber = {"timeZone": "Europe/Berlin", "startDate": "2026-09-21T22:00:00.000+0000"}
check("task_date reads a stamp in the task's OWN zone: 21T22Z is Mon 21 in London, Tue 22 in Berlin",
      meal.task_date(lon) == date(2026, 9, 21) and meal.task_date(ber) == date(2026, 9, 22))
check("task_date: no date, bad date", meal.task_date({}) is None and meal.task_date({"dueDate": "soon"}) is None)
check("api_day in a zone: London midnight of 22 Sep is 21T23Z, Berlin's is 21T22Z",
      meal.api_day(date(2026, 9, 22), ZoneInfo("Europe/London")) == "2026-09-21T23:00:00+0000"
      and meal.api_day(date(2026, 9, 22), ZoneInfo("Europe/Berlin")) == "2026-09-21T22:00:00+0000")
check("api_day round-trips through task_date in the same zone",
      meal.task_date({"timeZone": "Europe/London", "startDate": meal.api_day(date(2026, 12, 25), ZoneInfo("Europe/London"))}) == date(2026, 12, 25))
check("zone_name", meal.zone_name(ZoneInfo("Europe/Berlin")) == "Europe/Berlin")
check("routine_key folds case and spaces", meal.routine_key("  🥘  meal   PREP ") == meal.routine_key("🥘 Meal Prep"))
RID = "r" * 24
POOL = [
    {"id": RID, "title": "🥘 Meal Prep", "status": 0, "repeatFlag": "RRULE:FREQ=WEEKLY", "timeZone": "Europe/Berlin",
     "startDate": "2026-09-27T17:00:00.000+0000"},
    {"id": "c" * 24, "title": "🥘 Meal Prep", "status": 0, "timeZone": "Europe/Berlin",
     "startDate": "2026-09-22T07:00:00.000+0000"},                        # the copy Vex moved to Tuesday
    {"id": "d" * 24, "title": "🥘 Meal Prep", "status": 2, "startDate": "2026-09-20T17:00:00.000+0000"},   # done
    {"id": "e" * 24, "title": "🥘 Meal Prep", "status": 0, "startDate": "2026-09-13T17:00:00.000+0000"},   # stale, past
    {"id": "f" * 24, "title": "🥘 Meal Prep", "status": 0},                                                 # undated
    {"id": "g" * 24, "title": "Something else", "status": 0, "repeatTaskId": RID, "startDate": "2026-09-24T07:00:00.000+0000"},
    {"id": "h" * 24, "title": "🛒 Groceries", "status": 0, "startDate": "2026-09-22T06:00:00.000+0000"},
]
today = date(2026, 9, 21)
check("open_matching: title twins, the series and a split-off occurrence, never the done one",
      sorted(t["id"][0] for t in meal.open_matching(POOL, meal.PREP_TITLE, (RID,))) == ["c", "e", "f", "g", "r"])
up = meal.upcoming(POOL, meal.PREP_TITLE, today, ids=(RID,))
check("upcoming: the moved Tuesday copy beats the Sunday series", up and up["id"] == "c" * 24, up and up["id"])
check("upcoming: the past and the undated never count", meal.upcoming(POOL[3:5], meal.PREP_TITLE, today) is None)
check("upcoming on the cook day itself still counts", meal.upcoming(POOL, meal.PREP_TITLE, date(2026, 9, 22), ids=(RID,))["id"] == "c" * 24)
check("upcoming: after Tuesday the series is next", meal.upcoming(POOL, meal.PREP_TITLE, date(2026, 9, 23), ids=(RID,))["id"] == "g" * 24
      or meal.upcoming(POOL, meal.PREP_TITLE, date(2026, 9, 25), ids=(RID,))["id"] == RID)
tie = [dict(POOL[0], startDate="2026-09-22T17:00:00.000+0000"), POOL[1]]
check("upcoming: a same-day tie goes to the copy, not the series", meal.upcoming(tie, meal.PREP_TITLE, today, ids=(RID,))["id"] == "c" * 24)
check("upcoming: groceries by title", meal.upcoming(POOL, meal.GROCERIES_TITLE, today)["id"] == "h" * 24)
pl = [P(date(2026, 9, 22), U2, "Oats"), P(date(2026, 9, 22), U1, "Bulgogi"), P(date(2026, 9, 22), U2, "Oats again"),
      P(date(2026, 9, 27), U3, "Pockets")]
ms = meal.meals_on(pl, RECIPES, None, ents, date(2026, 9, 22))
check("meals_on: the day's meals only, one per recipe, slot order",
      [(m.slot, m.name) for m in ms] == [("b", "Oats"), ("l", "Beef Bulgogi")], [(m.slot, m.name) for m in ms])
check("meals_on: an empty day", meal.meals_on(pl, {}, None, [], date(2026, 9, 23)) == [])


# ── rating, comments, cooked (Vex 2026-09-21) ────────────────────────────────
print("-- rating / comments / cooked")
import mela                                   # noqa: E402  (pure: render only, no DB)
ST = "⭐️"                           # ⭐️ = U+2B50 + VS16, Mela's own
BARE = "⭐"                               # ⭐ without the selector
UR = "F052E26F-E879-44E9-8633-E6BA39676E87"
WEB = "https://www.instagram.com/reel/x"
L1 = f"> 🔗 [Burbon Asian Chicken](mela://recipe/{UR})"
L2 = f"> 🌐 [instagram.com]({WEB})"
BODY = "Serves: 4\n## Ingredients:\n- a\n"
SAMPLE = f"{L1}\n{L2}\n> {ST * 5}\n> add less salt next time\n\n{BODY}"
check("constants: the tag under its parent, ⭐️ with VS16, five at most",
      meal.COOKED_TAG == "\U0001F468‍\U0001F373cooked" and meal.COOKED_PARENT == "\U0001F371mealprep"
      and meal.STAR == ST and meal.MAX_STARS == 5)
# stars / parse_stars
check("stars: n copies, capped, '' for none", meal.stars(3) == ST * 3 and meal.stars(9) == ST * 5
      and meal.stars(0) == "" and meal.stars(None) == "" and meal.stars(-2) == "" and meal.stars("x") == "")
check("parse_stars: digits, n/5, capped", meal.parse_stars("3") == 3 and meal.parse_stars("3/5") == 3
      and meal.parse_stars(" 4 / 5 ") == 4 and meal.parse_stars("7") == 5 and meal.parse_stars("5") == 5)
check("parse_stars: ⭐️ with VS16, ⭐ without, ★, *", meal.parse_stars(ST * 3) == 3 and meal.parse_stars(BARE * 2) == 2
      and meal.parse_stars("★★★") == 3 and meal.parse_stars("***") == 3 and meal.parse_stars(ST * 6) == 5
      and meal.parse_stars(ST + " " + ST) == 2)
check("parse_stars: 0 / none / clear / - / empty -> 0", [meal.parse_stars(x) for x in ("0", "none", "Clear", "-", "", "  ", None)] == [0] * 7)
check("parse_stars: garbage -> None", meal.parse_stars("great") is None and meal.parse_stars("3/4") is None
      and meal.parse_stars(ST + " great") is None and meal.parse_stars("3 stars") is None)
# header_block
check("header_block: the sample", meal.header_block(SAMPLE) == ([L1, L2, f"> {ST * 5}", "> add less salt next time"], BODY))
check("header_block: no head", meal.header_block(BODY) == ([], BODY) and meal.header_block("x > y") == ([], "x > y"))
check("header_block: a bare > counts", meal.header_block("> a\n>\n> b\n\nx") == (["> a", ">", "> b"], "x"))
check("header_block: no trailing newline, no body", meal.header_block("> a\n\nx") == (["> a"], "x")
      and meal.header_block("> a") == (["> a"], "") and meal.header_block("> a\n") == (["> a"], ""))
check("header_block: only ONE blank line removed, none needed", meal.header_block("> a\n\n\nx") == (["> a"], "\nx")
      and meal.header_block("> a\nx") == (["> a"], "x"))
check("header_block: None / empty never raise", meal.header_block(None) == ([], "") and meal.header_block("") == ([], ""))
# the line classifiers
check("is_link_line: 🔗 and 🌐 quote lines only", meal.is_link_line(L1) and meal.is_link_line(L2)
      and not meal.is_link_line(f"> {ST * 3}") and not meal.is_link_line("> add salt") and not meal.is_link_line("🔗 x")
      and not meal.is_link_line(None))
check("is_link_line: a note that mentions the web is a note (the glyph must lead the line)",
      not meal.is_link_line("> see 🌐 for the web version") and not meal.is_link_line("> the 🔗 was dead")
      and meal.is_link_line(">🌐 [x](https://x)") and meal.is_link_line(">  🔗 [x](mela://recipe/1)"))
check("set_rating: a note mentioning the web keeps the stars right under the links, and stays a note",
      meal.set_rating(f"{L1}\n> see 🌐 for the web version", 2) == f"{L1}\n> {ST * 2}\n> see 🌐 for the web version"
      and meal.read_comments(f"{L1}\n> see 🌐 for the web version") == ["see 🌐 for the web version"])
check("is_stars_line: ⭐️, ⭐, ★, spaced, 1..5", meal.is_stars_line(f"> {ST * 5}") and meal.is_stars_line(f"> {BARE}")
      and meal.is_stars_line("> ★★★") and meal.is_stars_line(f"> {ST} {ST}") and meal.is_stars_line(f">{ST}"))
check("is_stars_line: not 6, not text, not without >", not meal.is_stars_line(f"> {ST * 6}")
      and not meal.is_stars_line(f"> {ST * 3} nice") and not meal.is_stars_line(ST * 3) and not meal.is_stars_line(">")
      and not meal.is_stars_line(None))
# read_rating / read_comments
check("read_rating: the sample, VS16 blind, none", meal.read_rating(SAMPLE) == 5
      and meal.read_rating(f"{L1}\n> {BARE * 3}\n\n{BODY}") == 3 and meal.read_rating(f"{L1}\n\n{BODY}") is None
      and meal.read_rating(None) is None and meal.read_rating(f"body {ST * 2}") is None)
check("read_comments: the sample", meal.read_comments(SAMPLE) == ["add less salt next time"])
check("read_comments: order kept, bare > and > empty skipped, links and stars never",
      meal.read_comments(f"{L1}\n> {ST}\n> first\n>\n> \n> second\n\nx") == ["first", "second"]
      and meal.read_comments(BODY) == [] and meal.read_comments(None) == [])
# mint_header
check("mint_header: 🔗 from the title, 🌐 host without www", meal.mint_header("Burbon Asian Chicken", UR, WEB) == [L1, L2]
      and meal.mint_header("Burbon Asian Chicken", UR) == [L1] and meal.mint_header("X", UR, "  ") == [f"> 🔗 [X](mela://recipe/{UR})"])
check("mint_header: exactly mela.render_markdown's header",
      mela.render_markdown(mela.Recipe(UR, 1, "Burbon Asian Chicken", link=WEB)).split("\n")[:2]
      == meal.mint_header("Burbon Asian Chicken", UR, WEB))
# set_rating
check("set_rating: after 🌐", meal.set_rating(f"{L1}\n{L2}\n\n{BODY}", 4) == f"{L1}\n{L2}\n> {ST * 4}\n\n{BODY}")
check("set_rating: after 🔗 when there is no 🌐", meal.set_rating(f"{L1}\n\n{BODY}", 2) == f"{L1}\n> {ST * 2}\n\n{BODY}")
check("set_rating: replace in place, comments kept after", meal.set_rating(SAMPLE, 3) == SAMPLE.replace(ST * 5, ST * 3)
      and meal.read_comments(meal.set_rating(SAMPLE, 3)) == ["add less salt next time"])
check("set_rating: a stars line that sat after a comment moves up under the links",
      meal.set_rating(f"{L1}\n> salty\n> {ST * 2}\n\nx", 4) == f"{L1}\n> {ST * 4}\n> salty\n\nx")
check("set_rating: remove with 0 and None", meal.set_rating(SAMPLE, 0) == SAMPLE.replace(f"> {ST * 5}\n", "")
      and meal.set_rating(SAMPLE, None) == meal.set_rating(SAMPLE, 0))
check("set_rating: nothing to remove = byte-identical", meal.set_rating(f"{L1}\nx", 0) == f"{L1}\nx"
      and meal.set_rating("", 0) == "" and meal.set_rating(None, 0) == "")
hdr = meal.mint_header("Burbon Asian Chicken", UR, WEB)
check("set_rating: minted header on empty content, no newline added", meal.set_rating("", 5, header=hdr) == f"{L1}\n{L2}\n> {ST * 5}")
check("set_rating: minted header on a hand-written body, blank line between",
      meal.set_rating("Serves: 4\n- a\n", 3, header=hdr) == f"{L1}\n{L2}\n> {ST * 3}\n\nServes: 4\n- a\n")
check("set_rating: no head and no header still lands the stars on top", meal.set_rating("body", 3) == f"> {ST * 3}\n\nbody")
odd = "Serves: 4\n\n\n- a   \n\n"
check("set_rating: the rest is byte-identical", meal.set_rating(f"{L1}\n\n{odd}", 1) == f"{L1}\n> {ST}\n\n{odd}")
check("set_rating: a trailing newline is kept", meal.set_rating(f"{L1}\n", 1) == f"{L1}\n> {ST}\n"
      and meal.set_rating(L1, 1) == f"{L1}\n> {ST}")
check("set_rating: the exact trailing newline run comes back (two, three) when there is no body",
      meal.set_rating(f"{L1}\n\n", 1) == f"{L1}\n> {ST}\n\n" and meal.set_rating(f"{L1}\n\n\n", 1) == f"{L1}\n> {ST}\n\n\n"
      and meal.add_comment(f"{L1}\n\n", "x") == f"{L1}\n> x\n\n")
check("set_rating: capped at 5, round-trips through read_rating", meal.read_rating(meal.set_rating(SAMPLE, 9)) == 5
      and meal.read_rating(meal.set_rating(SAMPLE, 3)) == 3 and meal.read_rating(meal.set_rating(SAMPLE, 0)) is None)
# add_comment
check("add_comment: after the stars", meal.add_comment(f"{L1}\n{L2}\n> {ST * 3}\n\n{BODY}", "less salt")
      == f"{L1}\n{L2}\n> {ST * 3}\n> less salt\n\n{BODY}")
check("add_comment: after earlier comments, never replacing", meal.add_comment(SAMPLE, "more chili")
      == SAMPLE.replace("> add less salt next time\n", "> add less salt next time\n> more chili\n")
      and meal.read_comments(meal.add_comment(SAMPLE, "more chili")) == ["add less salt next time", "more chili"])
check("add_comment: multi-line text, one quote line each, blanks dropped",
      meal.add_comment(SAMPLE, "a\n\n  b  \n") == SAMPLE.replace("next time\n", "next time\n> a\n> b\n"))
check("add_comment: blank / None text = untouched", meal.add_comment(SAMPLE, "   ") == SAMPLE
      and meal.add_comment(SAMPLE, None) == SAMPLE and meal.add_comment("", "") == "" and meal.add_comment(None, "") == "")
check("add_comment: minted header on empty and on a hand-written body", meal.add_comment("", "note", header=hdr) == f"{L1}\n{L2}\n> note"
      and meal.add_comment("Serves: 4\n", "note", header=hdr) == f"{L1}\n{L2}\n> note\n\nServes: 4\n")
check("add_comment: no head, no header", meal.add_comment("body", "note") == "> note\n\nbody")
check("add_comment: a pasted quote is not quoted twice", meal.add_comment(SAMPLE, "> quoted").count("> quoted") == 1
      and ">  >" not in meal.add_comment(SAMPLE, "> quoted"))
# strip_mela_rating / adopt_mela_rating
blurb = f"{L1}\n{L2}\n\nRating: {ST * 5}\n\n{BODY}"
check("strip_mela_rating: the blurb copy, one blank line kept", meal.strip_mela_rating(blurb) == f"{L1}\n{L2}\n\n{BODY}")
check("strip_mela_rating: a blurb with text keeps the text", meal.strip_mela_rating(f"{L1}\n\nNice.\nRating: {ST * 2}\n\n{BODY}")
      == f"{L1}\n\nNice.\n\n{BODY}")
notes = f"{L1}\n\n{BODY}\n## Notes:\nI did not have ranch\nRating: {ST * 3}\n"
check("strip_mela_rating: the ## Notes copy", meal.strip_mela_rating(notes) == f"{L1}\n\n{BODY}\n## Notes:\nI did not have ranch\n")
check("strip_mela_rating: a ## Notes left empty goes too, one trailing newline",
      meal.strip_mela_rating(f"{L1}\n\n{BODY}\n## Notes:\nRating: {ST * 3}\n") == f"{L1}\n\n{BODY}")
check("strip_mela_rating: a stars line INSIDE the head is never touched", meal.strip_mela_rating(SAMPLE) == SAMPLE
      and meal.strip_mela_rating(f"{L1}\n> Rating: {ST}\n\nx") == f"{L1}\n> Rating: {ST}\n\nx")
check("strip_mela_rating: nothing to strip = byte-identical", meal.strip_mela_rating(f"{L1}\nx") == f"{L1}\nx"
      and meal.strip_mela_rating(BODY) == BODY and meal.strip_mela_rating(None) == "" and meal.strip_mela_rating("") == "")
check("strip_mela_rating: ⭐ without VS16, ★, padding; 'Rating: great' stays",
      meal.strip_mela_rating(f"a\n  Rating: {BARE * 2}  \nb") == "a\nb" and meal.strip_mela_rating("a\nRating: ★★\nb") == "a\nb"
      and meal.strip_mela_rating("a\nRating: great\nb") == "a\nRating: great\nb")
check("strip_mela_rating: a rating line on top of a hand-written body", meal.strip_mela_rating(f"Rating: {ST}\n\nbody") == "body")
check("adopt_mela_rating: Mela's line leaves the body, the stars land under the links",
      meal.adopt_mela_rating(blurb, 5) == f"{L1}\n{L2}\n> {ST * 5}\n\n{BODY}"
      and meal.adopt_mela_rating(notes, 3) == f"{L1}\n> {ST * 3}\n\n{BODY}\n## Notes:\nI did not have ranch\n")
check("adopt_mela_rating: mints the header on a hand-written body",
      meal.adopt_mela_rating(f"Rating: {ST * 2}\nServes: 4\n", 2, header=hdr) == f"{L1}\n{L2}\n> {ST * 2}\n\nServes: 4\n")
# payloads
check("cooked_payload", meal.cooked_payload("p", "t") == {"pid": "p", "tid": "t"}
      and meal.cooked_payload("p", "t", "ctx:meal") == {"pid": "p", "tid": "t", "back": "ctx:meal"})
check("rate_payload", meal.rate_payload("p", "t", 4) == {"pid": "p", "tid": "t", "stars": 4}
      and meal.rate_payload("p", "t", 0, "ctx:meal") == {"pid": "p", "tid": "t", "stars": 0, "back": "ctx:meal"})
check("comment_payload", meal.comment_payload("p", "t") == {"pid": "p", "tid": "t"}
      and meal.comment_payload("p", "t", back="ctx:meallib:b") == {"pid": "p", "tid": "t", "back": "ctx:meallib:b"})
# chips and order with the tag and a rating
today = date(2026, 9, 28)
check("cooked_chip: the tag alone says 'cooked before', the calendar wins when it knows",
      meal.cooked_chip(None, tagged=True) == "cooked before" and meal.cooked_chip(None) == "never cooked"
      and meal.cooked_chip(0, True) == "cooked this week" and meal.cooked_chip(2, tagged=True) == "cooked 2 weeks ago")
check("lib_chip: old calls unchanged", meal.lib_chip(PLANNED, U2, today) == "cooked this week · next Sun 11 Oct"
      and meal.lib_chip(PLANNED, "zz", today) == "never cooked")
check("lib_chip: tagged, rated", meal.lib_chip(PLANNED, "zz", today, tagged=True) == "cooked before"
      and meal.lib_chip(PLANNED, U2, today, rating=3) == f"cooked this week · next Sun 11 Oct · {ST * 3}"
      and meal.lib_chip(PLANNED, "zz", today, tagged=True, rating=5) == f"cooked before · {ST * 5}"
      and meal.lib_chip(PLANNED, "zz", today, rating=0) == "never cooked" and meal.lib_chip(PLANNED, U3, today, rating=None) == "cooked this week")
pool2 = [{"tid": "a", "uuid": U2, "name": "Oats"}, {"tid": "b", "uuid": "N1", "name": "Zebra", "cooked": True},
         {"tid": "c", "uuid": U1, "name": "Bulgogi", "cooked": True}, {"tid": "d", "uuid": "N2", "name": "Apple"},
         {"tid": "e", "uuid": "N3", "name": "Mango", "cooked": True}, {"tid": "f", "uuid": "N4", "name": "Kiwi", "cooked": False}]
order = [e["tid"] for e in meal.sort_for_lib(pool2, PLANNED, date(2026, 9, 21))]
check("sort_for_lib: never (by name), then tag-only (by name), then least recently cooked", order == ["d", "f", "e", "b", "a", "c"], order)
check("sort_for_lib: entries without the key sort as before", [e["tid"] for e in meal.sort_for_lib(pool, PLANNED, date(2026, 9, 21))] == ["d", "b", "a", "c"])
ents2 = meal.library_entries(TASKS + [T("t7", f"[Rated](mela://recipe/{U5})", tags=["🍛lunch", "👨‍🍳COOKED"], content=SAMPLE),
                                     T("t8", f"[Plain](mela://recipe/{U4})", tags=["🍛lunch"], content=f"{L1}\n\n{BODY}")], LIST)
check("library_entries: cooked (case blind) and rating carried", [(e["tid"], e["cooked"], e["rating"]) for e in ents2[-2:]]
      == [("t7", True, 5), ("t8", False, None)] and ents2[0]["cooked"] is False and ents2[0]["rating"] is None,
      [(e["tid"], e["cooked"], e["rating"]) for e in ents2])

print(f"\nmeal: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
