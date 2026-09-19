#!/usr/bin/env python3
"""The 🥘 screens (Scripts/browse.py ctx:meal / mealplan / meallib /
mealgroc) rendered against a FAKE cache in a temp dir, no network, no
Mela: meal_write.hub_counts is stubbed and the routine's list is planted
as the meal_kids snapshot so the live read never fires.

What it pins (the traps that burned the other hubs):
  * every row spells out all six chords as fresh dicts, no xact: on ⌘ or ⌥,
    ⌘ dead on anything that is not a task, task rows carry the full variable set
  * the picker chain carries picks in the ctx ('-' = pick this one next) and
    lands on a summary whose ✅ row's payload says what commit() reads
  * typing "today" on a meal screen never jumps away (parse_ctx guard)
  * 🎲 Surprise never offers something cooked in the last 4 weeks
  * the Routines hub carries the zero-canvas door

    python3 tests/test_meal_screens.py
"""
import base64
import json
import os
import sys
import tempfile
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
TMP = tempfile.mkdtemp(prefix="tickal-meals-")
LIST, RLIST, RID = "5eed00000000000000000a01", "5eed00000000000000000b01", "5eed00000000000000000b02"
os.environ["meal_list_id"] = LIST
os.environ["meal_routine_id"] = RID
os.environ.pop("browse_ctx", None)
os.environ.pop("browse_back", None)
import cache as cache_store                    # noqa: E402
cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR)
import meal                                    # noqa: E402
import meal_write as mw                        # noqa: E402
mw.LEDGER = os.path.join(TMP, "meal_ledger.json")
mw.hub_counts = lambda: {"new": 2, "missing": 3, "uncategorised": 1, "mela_ok": True,
                         "mela_age_s": 120, "mela_error": None, "list_id": LIST}
import browse                                  # noqa: E402

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
U4 = "44444444-4444-4444-4444-444444444444"
TODAY = date.today()


def T(tid, title, pid=LIST, tags=(), status=0, parent=None, **kw):
    t = {"id": tid, "projectId": pid, "_projectId": pid, "title": title, "tags": list(tags),
         "status": status, "parentId": parent, "content": "", "kind": "TEXT", "columnId": ""}
    t.update(kw)
    return t


LIB = [T("t1", f"[Oats](mela://recipe/{U2})", tags=["🍳breakfast"]),
       T("t2", f"[Beef Bulgogi](mela://recipe/{U1})", tags=["🍛lunch"], content="body"),
       T("t3", f"[Pockets](mela://recipe/{U3})", tags=["🌮snack"]),
       T("t4", f"[Second Lunch](mela://recipe/{U4})", tags=["🍛lunch"]),
       T("g1", meal.grocery_title("Oats", U2), tags=["🛒groceries"], kind="CHECKLIST",
         dueDate="2026-09-26T00:00:00+0000", items=[{"title": "a", "status": 2}, {"title": "b", "status": 0}])]
ROUTINE = T(RID, "🥘 Meal Prep", pid=RLIST, startDate=f"{meal.next_sunday(TODAY).isoformat()}T17:00:00.000+0000")
PTR = T("p1", meal.pointer_title("b", "Oats", U2), pid=RLIST, parent=RID)


def plant(kids=(PTR,)):
    rl = [ROUTINE] + list(kids)
    cache_store.set("all_tasks", LIB + rl)
    cache_store.set("projects", [{"id": LIST, "name": "🍳Meal Prep"}, {"id": RLIST, "name": "🌅 Routines"}])
    cache_store.set(f"project_data_{LIST}", {"project": {"id": LIST}, "tasks": LIB})
    cache_store.set(f"project_data_{RLIST}", {"project": {"id": RLIST}, "tasks": rl})
    cache_store.set("meal_kids", {"rid": RID, "ts": time.time(), "routine": ROUTINE, "tasks": rl})


def render(ctx, query=""):
    os.environ["browse_ctx"] = ctx
    level, ids, q = browse.parse_ctx(query)
    os.environ.pop("browse_ctx", None)
    return level, ids, q


def rows_for(ctx, query=""):
    level, ids, q = render(ctx, query)
    fn = {"meal": lambda: browse.render_meal(ids, q),
          "mealplan": lambda: browse.render_mealplan(ids, q),
          "meallib": lambda: browse.render_meallib(ids, q),
          "mealgroc": lambda: browse.render_mealgroc(q)}[level]
    return fn()


def by_uid(rows):
    return {r.get("uid"): r for r in rows}


def sealed(rows, where):
    """The six-chord + ⌘-dead-on-non-task invariants (test_okr_screens)."""
    ok = True
    for r in rows:
        mods = r.get("mods") or {}
        for k in browse._OKR_CHORDS:
            if k not in mods:
                check(f"{where}: {r.get('uid')} missing chord {k}", False)
                ok = False
        for k in ("cmd", "alt"):
            if (mods.get(k) or {}).get("arg", "").startswith("xact:"):
                check(f"{where}: {r.get('uid')} xact on {k}", False)
                ok = False
        v = r.get("variables") or {}
        if not v.get("task_id") and (mods.get("cmd") or {}).get("valid"):
            check(f"{where}: {r.get('uid')} ⌘ live on a non-task row", False)
            ok = False
        if v.get("task_id") and set(v) < {"task_id", "task_list_id", "list_id", "section_id", "task_title", "item_type"}:
            check(f"{where}: {r.get('uid')} task row lacks the full variable set", False)
            ok = False
    ids = [id(r.get("mods", {}).get("cmd")) for r in rows]
    if len(ids) != len(set(ids)):
        check(f"{where}: rows share a mods dict", False)
        ok = False
    return ok


def payload(row):
    arg = row.get("arg") or ""
    return json.loads(base64.b64decode(arg.split(":", 2)[2]))


# ── the hub root ──────────────────────────────────────────────────────────────
plant()
rows = rows_for("ctx:meal")
r = by_uid(rows)
check("hub: sealed", sealed(rows, "hub"))
check("hub: head names the cook Sunday and 1/3 planned",
      "1/3 planned" in r["meal-head"]["title"] and not r["meal-head"]["valid"], r["meal-head"]["title"])
b = r["meal-b"]
check("hub: the planned breakfast is a task row opening Mela",
      b["arg"] == f"open:mela://recipe/{U2}" and b["variables"]["task_id"] == "p1"
      and b["variables"]["task_list_id"] == RLIST and b["mods"]["cmd"]["valid"], b)
check("hub: ⇧ completes the pointer, ⌥⌘ copies its link",
      b["mods"]["shift"]["arg"] == f"complete:{RLIST}:p1:{PTR['title']}"
      and b["mods"]["alt+cmd"]["arg"] == f"copy:ticktick:///webapp/#p/{RLIST}/tasks/p1")
check("hub: ⌥ swaps that slot (the others ride, this one is '-')",
      b["mods"]["alt"]["arg"] == "" and b["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealplan", b["mods"]["alt"])
l = r["meal-l"]
check("hub: an unplanned slot navigates to the picker with the planned one carried",
      l["arg"] == "xact:crmbrowse:ctx:mealplan:t1" and l["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealplan:t1"
      and not l["variables"].get("task_id") and not l["mods"]["cmd"]["valid"], l)
check("hub: plan row", r["meal-plan"]["arg"] == "xact:crmbrowse:ctx:mealplan" and "1 breakfasts · 2 lunches · 1 snacks" in r["meal-plan"]["subtitle"])
g = r["meal-groc"]
check("hub: groceries row counts + ⌥⇧ rebuild payload", "1 open list" in g["title"]
      and g["mods"]["alt+shift"]["arg"].startswith("xact:meal_groceries:")
      and payload(g["mods"]["alt+shift"]) == {"back": "ctx:meal"}, g)
check("hub: import row live with 2 new, names the uncategorised",
      r["meal-import"]["valid"] and "2 new" in r["meal-import"]["title"] and "1 uncategorised" in r["meal-import"]["subtitle"]
      and payload(r["meal-import"]) == {"back": "ctx:meal"})
check("hub: fill row live with 3 missing", r["meal-fill"]["valid"] and "3 missing" in r["meal-fill"]["title"])
check("hub: library rows", r["meal-lib-l"]["arg"] == "xact:crmbrowse:ctx:meallib:lunch" and "Lunches · 2" in r["meal-lib-l"]["title"])
check("hub: status row", "Mela data 2 min old" in r["meal-status"]["title"] and "4 recipes" in r["meal-status"]["subtitle"])
check("hub: ⌃ backs to the folders", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:folders" for x in rows))
mw.hub_counts = lambda: {"new": 0, "missing": 0, "uncategorised": 0, "mela_ok": False,
                         "mela_age_s": None, "mela_error": "Mela database not found", "list_id": LIST}
r2 = by_uid(rows_for("ctx:meal"))
check("hub: dead import/fill rows when nothing to do, Mela error shown",
      not r2["meal-import"]["valid"] and not r2["meal-fill"]["valid"] and "Mela: Mela database not found" in r2["meal-status"]["title"])
mw.hub_counts = lambda: {"new": 2, "missing": 3, "uncategorised": 1, "mela_ok": True,
                         "mela_age_s": 120, "mela_error": None, "list_id": LIST}
plant(kids=())
r3 = by_uid(rows_for("ctx:meal"))
check("hub: nothing planned → three picker rows, 0/3", "0/3 planned" in r3["meal-head"]["title"]
      and all(r3[f"meal-{k}"]["arg"] == "xact:crmbrowse:ctx:mealplan" for k in "bls"))
rq = rows_for("ctx:meal", "grocer")
check("hub: a typed bar filters the rows", [x["uid"] for x in rq] == ["meal-groc"], [x["uid"] for x in rq])
os.environ["meal_list_id"] = ""
ro = rows_for("ctx:meal")
check("hub: blank list id = off row", len(ro) == 1 and ro[0]["uid"] == "meal-off" and not ro[0]["valid"])
os.environ["meal_list_id"] = LIST

# ── parse_ctx guard ───────────────────────────────────────────────────────────
plant()
check("parse_ctx: 'today' typed on a meal screen stays put", render("ctx:mealplan:t1", "today") == ("mealplan", ["t1"], "today"))
check("parse_ctx: 'inbox' on the hub stays put", render("ctx:meal", "inbox") == ("meal", [], "inbox"))
os.environ["browse_ctx"] = "ctx:countdowns"
check("parse_ctx: elsewhere the alias still works", browse.parse_ctx("today")[0] == "smart")
os.environ.pop("browse_ctx", None)

# ── the picker chain ──────────────────────────────────────────────────────────
led = {"weeks": []}
meal.ledger_add(led, TODAY - __import__("datetime").timedelta(days=7 * 1 + TODAY.weekday() + 1),
                {"l": {"tid": "t2", "uuid": U1, "name": "Beef Bulgogi"}})
meal.save_ledger(mw.LEDGER, led)
rows = rows_for("ctx:mealplan")
r = by_uid(rows)
check("picker 1/3: sealed", sealed(rows, "picker-b"))
check("picker 1/3: head + surprise + the one breakfast", [x["uid"] for x in rows] == ["mp-head", "mp-surprise", "mp-t1"], [x["uid"] for x in rows])
check("picker: a row carries its pick in the ctx, ⌥ the same hop, ⌥⌘ opens Mela, ⌘ live (a task)",
      r["mp-t1"]["arg"] == "xact:crmbrowse:ctx:mealplan:t1" and r["mp-t1"]["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealplan:t1"
      and r["mp-t1"]["mods"]["alt+cmd"]["arg"] == f"open:mela://recipe/{U2}" and r["mp-t1"]["mods"]["cmd"]["valid"]
      and r["mp-t1"]["variables"]["task_id"] == "t1", r["mp-t1"])
check("picker 1/3: ⌃ backs to the hub", r["mp-t1"]["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal")
rows = rows_for("ctx:mealplan:t1")
r = by_uid(rows)
check("picker 2/3: lunches, recently cooked one last, surprise avoids it",
      [x["uid"] for x in rows] == ["mp-head", "mp-surprise", "mp-t4", "mp-t2"]
      and "Second Lunch" in r["mp-surprise"]["title"] and "cooked last week" in r["mp-t2"]["subtitle"], [x["uid"] for x in rows])
check("picker 2/3: the pick lands in slot 2", r["mp-t4"]["arg"] == "xact:crmbrowse:ctx:mealplan:t1:t4")
check("picker 2/3: ⌃ re-picks breakfast", r["mp-t4"]["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:mealplan")
rows = rows_for("ctx:mealplan:-:t4")
r = by_uid(rows)
check("picker: '-' = this slot next (breakfast, with lunch carried)",
      "breakfast" in r["mp-head"]["title"] and r["mp-t1"]["arg"] == "xact:crmbrowse:ctx:mealplan:t1:t4")
rows = rows_for("ctx:mealplan:t1:t4", "pock")
r = by_uid(rows)
check("picker 3/3: a typed bar filters and drops surprise", [x["uid"] for x in rows] == ["mp-head", "mp-t3"])
rows = rows_for("ctx:mealplan:t1:t4:t3")
r = by_uid(rows)
check("summary: sealed", sealed(rows, "summary"))
check("summary: three picks + commit", [x["uid"] for x in rows] == ["mp-head", "mp-b", "mp-l", "mp-s", "mp-commit"], [x["uid"] for x in rows])
check("summary: a pick row changes that slot", r["mp-l"]["arg"] == "xact:crmbrowse:ctx:mealplan:t1:-:t3"
      and r["mp-l"]["variables"]["task_id"] == "t4")
pay = payload(r["mp-commit"])
check("summary: commit payload = what commit() reads",
      r["mp-commit"]["valid"] and pay == {"b": "t1", "l": "t4", "s": "t3", "sunday": meal.next_sunday(TODAY).isoformat(), "back": "ctx:meal"}, pay)
check("summary: ⌃ backs to the hub", r["mp-commit"]["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal")
rows = rows_for("ctx:mealplan:t1:zz:t3")
r = by_uid(rows)
check("summary: a pick gone from the library kills the commit row", not r["mp-commit"]["valid"] and "not in the library" in r["mp-l"]["title"])

# ── the library + groceries ───────────────────────────────────────────────────
rows = rows_for("ctx:meallib:lunch")
r = by_uid(rows)
check("library: sealed", sealed(rows, "lib"))
check("library: rows open Mela, body chip, copy link",
      r["ml-t2"]["arg"] == f"open:mela://recipe/{U1}" and "recipe in the description" in r["ml-t2"]["subtitle"]
      and "no description yet" in r["ml-t4"]["subtitle"] and r["ml-t2"]["mods"]["alt+cmd"]["arg"].startswith("copy:ticktick:///"))
check("library: ⌥ dead without subtasks", not r["ml-t2"]["mods"]["alt"]["valid"])
check("library: filter", [x["uid"] for x in rows_for("ctx:meallib:lunch", "second")] == ["ml-head", "ml-t4"])
check("library: a bad tag", "needs" in browse.render_meallib(["dinner"], "")[0]["title"])
rows = rows_for("ctx:mealgroc")
r = by_uid(rows)
check("groceries: sealed", sealed(rows, "groc"))
check("groceries: one list, ticked count, due, ⇧ completes",
      "1/2 ticked" in r["mg-g1"]["subtitle"] and "due 2026-09-26" in r["mg-g1"]["subtitle"]
      and r["mg-g1"]["mods"]["shift"]["arg"].startswith(f"complete:{LIST}:g1:") and r["mg-g1"]["variables"]["task_id"] == "g1", r["mg-g1"])

# ── the Routines hub's door ───────────────────────────────────────────────────
rr = by_uid(browse.render_routines(""))
door = rr.get("rt-meal-hub")
check("routines hub: the 🥘 door row (trampoline ⏎, ⌥ by variable, ⌃ dead)",
      door is not None and door["arg"] == "xact:crmbrowse:ctx:meal" and door["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:meal"
      and door["mods"]["ctrl"]["arg"] == "" and not door["mods"]["cmd"].get("valid", True), door)
check("routines hub: the meal routine itself is listed", "rt-meal" in rr)

# ── main() end to end through argv ────────────────────────────────────────────
import contextlib, io                          # noqa: E402
os.environ["browse_ctx"] = "ctx:meal"
sys.argv = ["browse.py", ""]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
os.environ.pop("browse_ctx", None)
out = json.loads(buf.getvalue())
check("main(): the hub renders through argv + env", any(i.get("uid") == "meal-head" for i in out.get("items", [])))

print(f"\nmeal screens: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
