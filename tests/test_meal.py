#!/usr/bin/env python3
"""Unit suite for src/meal.py (the 🥘 model) and src/meal_notes.py (the
weekly note's bullet). Pure: no network, no cache, no Calendar store and
no Mela DB - the plan rows are tiny duck-typed objects (date/uuid/title,
the mela_cal.Planned shape) and the recipes duck-type mela.Recipe
(id/title/link/categories). Run: python3 tests/test_meal.py
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

print(f"\nmeal: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
