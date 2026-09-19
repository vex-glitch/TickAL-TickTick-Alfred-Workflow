#!/usr/bin/env python3
"""Unit suite for src/meal.py (the 🥘 model) and src/meal_notes.py (the
weekly note's bullet). Pure: no network, no cache, a temp dir for the
ledger. Run: python3 tests/test_meal.py
"""
import os
import sys
import tempfile
from datetime import date

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
LIST, RLIST, RID = "5eed00000000000000000a01", "5eed00000000000000000b01", "5eed00000000000000000b02"

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
check("grocery_title / is_grocery", meal.is_grocery(meal.grocery_title("Oats", U2)) and not meal.is_grocery(ptr))
check("is_library_title", meal.is_library_title(f"[Oats](mela://recipe/{U2})") and not meal.is_library_title(ptr))
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
    T("r0", "🥘 Meal Prep", pid=RLIST, startDate="2026-09-27T17:00:00.000+0000"),
]
ents = meal.library_entries(TASKS, LIST)
check("library_entries: the three tagged + the untagged", [e["tid"] for e in ents] == ["t1", "t2", "t3", "t4"], [e["tid"] for e in ents])
check("library_entries: slot, uuid, content", ents[1]["slot"] == "l" and ents[1]["uuid"] == U1 and ents[1]["content"] == "body")
check("library_entries: untagged has no slot", ents[3]["slot"] is None)
by = meal.entries_by_slot(ents)
check("entries_by_slot", [e["tid"] for e in by["b"]] == ["t1"] and [e["tid"] for e in by["s"]] == ["t3"])
kids = meal.pointers_of(TASKS, RID)
check("pointers_of: by slot, archived + strangers skipped", sorted(kids) == ["b", "l", "s"]
      and kids["b"]["id"] == "p1" and kids["s"]["id"] == "p5", sorted(kids))
check("pointers_of: archived occurrence never counts", all(k["id"] != "p3" for k in kids.values()))
groc = meal.groceries_of(TASKS, LIST)
check("groceries_of", set(groc) == {U2, "22222222-2222-2222-2222-222222222222"} and groc[U2]["id"] == "g1")

# ── week arithmetic ──────────────────────────────────────────────────────────
sat, sun, mon = date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)
check("next_sunday", meal.next_sunday(sat) == sun and meal.next_sunday(sun) == sun and meal.next_sunday(mon) == date(2026, 9, 27))
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
check("api_day", meal.api_day(sun) == "2026-09-20")

# ── the ledger ────────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="tickal-meal-")
path = os.path.join(tmp, "sub", "meal_ledger.json")
led = meal.load_ledger(path)
check("load_ledger: missing reads empty", led == {"weeks": []})
picks = {"b": {"tid": "t1", "uuid": U2, "name": "Oats"}, "l": {"tid": "t2", "uuid": U1, "name": "Bulgogi"}}
meal.ledger_add(led, date(2026, 9, 6), picks, pointers=["p1"], groceries=["g1"])
meal.ledger_add(led, date(2026, 9, 13), {"s": {"tid": "t3", "uuid": U3, "name": "Pockets"}})
meal.ledger_add(led, date(2026, 9, 13), {"s": {"tid": "t3", "uuid": U3, "name": "Pockets v2"}})
check("ledger_add: one entry per Sunday, latest wins", len(led["weeks"]) == 2 and led["weeks"][1]["s"]["name"] == "Pockets v2")
check("ledger_add: missing slots are blank", led["weeks"][1]["b"] == {"tid": "", "uuid": "", "name": ""})
meal.save_ledger(path, led)
check("save/load round trip (dirs made)", meal.load_ledger(path) == led)
with open(path, "w") as f:
    f.write("{not json")
check("corrupt ledger reads empty", meal.load_ledger(path) == {"weeks": []})
check("last_cooked: weeks ago", meal.last_cooked(led, U2, sat) == 1 and meal.last_cooked(led, U3, sat) == 0)
check("last_cooked: case-insensitive, never", meal.last_cooked(led, U2.lower(), sat) == 1 and meal.last_cooked(led, "zz", sat) is None)
check("last_cooked: a future week does not count", meal.last_cooked(led, U3, date(2026, 9, 12)) is None)
check("cooked_chip", meal.cooked_chip(None) == "never cooked" and meal.cooked_chip(0) == "cooked this week"
      and meal.cooked_chip(1) == "cooked last week" and meal.cooked_chip(3) == "cooked 3 weeks ago")
pool = [{"tid": "a", "uuid": U2, "name": "Oats"}, {"tid": "b", "uuid": "N1", "name": "Zebra"},
        {"tid": "c", "uuid": U3, "name": "Pockets"}, {"tid": "d", "uuid": "N2", "name": "Apple"}]
order = [e["tid"] for e in meal.sort_for_pick(pool, led, sat)]
check("sort_for_pick: never first (by name), then oldest", order == ["d", "b", "a", "c"], order)
sp = [e["tid"] for e in meal.surprise_pool(pool, led, sat)]
check("surprise_pool: not cooked in 4 weeks", sp == ["b", "d"], sp)
check("surprise_pool: falls back to everything", len(meal.surprise_pool(pool[:1], led, sat)) == 1)
check("surprise: from the pool", meal.surprise(pool, led, sat)["tid"] in ("b", "d"))
check("surprise: empty", meal.surprise([], led, sat) is None)

# ── the picker chain's ctx ────────────────────────────────────────────────────
check("slots_from_ids", meal.slots_from_ids(["-", "x"]) == ["", "x", ""] and meal.slots_from_ids(None) == ["", "", ""]
      and meal.slots_from_ids(["a", "b", "c", "d"]) == ["a", "b", "c"])
check("ctx_for: trailing empties dropped, interior ride as -",
      meal.ctx_for(["", "", ""]) == "ctx:mealplan" and meal.ctx_for(["", "l", ""]) == "ctx:mealplan:-:l"
      and meal.ctx_for(["b", "l", "s"]) == "ctx:mealplan:b:l:s" and meal.ctx_for(["b"]) == "ctx:mealplan:b")
rt = meal.slots_from_ids(meal.ctx_for(["", "l", ""]).split(":")[2:])
check("ctx round trip", rt == ["", "l", ""], rt)
check("next_slot", meal.next_slot(["", "l", ""]) == 0 and meal.next_slot(["b", "", ""]) == 1 and meal.next_slot(["b", "l", "s"]) is None)
pay = meal.commit_payload(["b", "l", "s"], sun)
check("commit_payload", pay == {"b": "b", "l": "l", "s": "s", "sunday": "2026-09-20", "back": "ctx:meal"})
check("outcome_text", meal.outcome_text(sun, 3, 3) == "🥘 Week of 21 Sep planned · 3 meals · 3 grocery lists"
      and meal.outcome_text(sun, 3, 2, False).endswith("· note not written"))

# ── meal_notes over the shipped weekly template ───────────────────────────────
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

print(f"\nmeal: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
