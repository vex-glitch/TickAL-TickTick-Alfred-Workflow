#!/usr/bin/env python3
"""The 🥘 screens (Scripts/browse.py ctx:meal / mealq / mealw / meallib /
mealgroc) rendered against a FAKE cache in a temp dir, no network, no
Mela, no Calendar store: meal_write.plan_view, meal_write.hub_counts,
mela_cal.plan and mela.library are stubbed, and the routine's list is
planted as the meal_kids snapshot so the live read never fires.

What it pins (the traps that burned the other hubs):
  * every row spells out all six chords as fresh dicts, no xact: on ⌘ or ⌥,
    ⌘ dead on anything that is not a library task, task rows carry the full
    variable set
  * THE MEAL ROW: ⏎ open:mela://recipe, ⇧ open:<web> (dead "No web page"
    without a link), ⌥⌘ copy:mela://recipe, ⌥ and ⌥⇧ dead on plan rows
  * the hub reads the cook week off the calendar plan anchored on the
    ROUTINE's cook Sunday; 🎲 Plan / 📥 Import / 📝 Fill are gone, 🔄 Sync is
    the one verb (⏎ and ⌥⇧ the same xact:meal_sync payload)
  * ctx:mealq = 13 weeks, this week starred, empty weeks dead
  * typing "today" on a meal screen never jumps away (parse_ctx guard)
  * the Routines hub carries the zero-canvas door

    python3 tests/test_meal_screens.py
"""
import base64
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from types import SimpleNamespace

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
import mela                                    # noqa: E402
import mela_cal                                # noqa: E402
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
U5 = "55555555-5555-5555-5555-555555555555"      # planned, unknown to Mela
TODAY = date.today()
SUN = meal.next_sunday(TODAY)                  # the routine's cook Sunday (what 🔄 mirrors)
WK = meal.cook_week_of(TODAY)                  # THIS week's cook Sunday: the hub's anchor


def COOK(s):
    return ("cooked" if s < TODAY else "cook") + f" {s:%a %-d %b}"

HORIZON = 13
if not hasattr(mw, "HORIZON_WEEKS"):           # until the meal_write group lands
    mw.HORIZON_WEEKS = HORIZON


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
ROUTINE = T(RID, "🥘 Meal Prep", pid=RLIST, startDate=f"{SUN.isoformat()}T17:00:00.000+0000")
PTR = T("p1", meal.pointer_title("b", "Oats", U2), pid=RLIST, parent=RID)


def R(uid, title, cats, link=""):
    return SimpleNamespace(id=uid, title=title, categories=list(cats), link=link)


RECIPES = {U2: R(U2, "Oats", ["02 • Breakfast"], "https://oats.example/recipe"),
           U1: R(U1, "Beef Bulgogi", ["01 • Meal"]),
           U3: R(U3, "Pockets", ["03 • Snack"], "https://pockets.example"),
           U4: R(U4, "Second Lunch", ["01 • Meal"], "https://second.example")}


def P(day, uuid, title):
    return SimpleNamespace(date=day, uuid=uuid, title=title, start=None, all_day=False)


# the calendar: this cook week has a breakfast, a lunch and a recipe Mela
# does not know (dropped on the Monday, still this week); Pockets in two
# weeks; Bulgogi cooked two cook-weeks before today's
PLANNED = [P(WK, U2, "Oats"), P(WK, U1, "Beef Bulgogi"), P(WK + timedelta(days=1), U5, "Mystery Pie"),
           P(WK + timedelta(days=14), U3, "Pockets"),
           P(meal.cook_week_of(TODAY) - timedelta(days=14), U1, "Beef Bulgogi")]
CALLS = []
ERROR = [""]


def fake_plan_view(today=None, n_weeks=HORIZON, planned=None, recipes=None, tasks=None, first_sunday=None):
    CALLS.append((today, n_weeks, first_sunday))
    first = meal.cook_week_of(first_sunday) if first_sunday else meal.next_sunday(today or TODAY)
    if ERROR[0]:
        return {"weeks": [], "first_sunday": first, "planned_count": 0, "error": ERROR[0]}
    entries = meal.library_entries(LIB, LIST)
    return {"weeks": meal.weeks_plan(PLANNED, RECIPES, None, entries, first, n_weeks),
            "first_sunday": first, "planned_count": len(PLANNED), "error": ""}


mw.plan_view = fake_plan_view
mw.hub_counts = lambda: {"new": 2, "missing": 14, "uncategorised": 1, "mela_ok": True,
                         "mela_age_s": 240, "mela_error": None, "list_id": LIST}
mela_cal.plan = lambda since=None, until=None, path=None, now=None: [
    p for p in PLANNED if (since is None or p.date >= since) and (until is None or p.date <= until)]
mela.library = lambda path=None: list(RECIPES.values())


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
          "mealq": lambda: browse.render_mealq(ids, q),
          "mealw": lambda: browse.render_mealw(ids, q),
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


def meal_row_ok(r, uuid, web, where):
    """THE MEAL ROW's chords."""
    m = r["mods"]
    check(f"{where}: ⏎ opens the recipe in Mela", r["arg"] == f"open:mela://recipe/{uuid}" and r["valid"], r["arg"])
    if web:
        check(f"{where}: ⇧ opens the web page", m["shift"]["arg"] == f"open:{web}" and m["shift"]["valid"], m["shift"])
    else:
        check(f"{where}: ⇧ dead without a web page", m["shift"]["arg"] == "" and not m["shift"]["valid"]
              and m["shift"]["subtitle"] == "No web page", m["shift"])
    check(f"{where}: ⌥⌘ copies the Mela link", m["alt+cmd"]["arg"] == f"copy:mela://recipe/{uuid}" and m["alt+cmd"]["valid"])
    check(f"{where}: ⌥⇧ dead", not m["alt+shift"]["valid"] and m["alt+shift"]["arg"] == "")


# ── the hub root ──────────────────────────────────────────────────────────────
plant()
CALLS.clear()
rows = rows_for("ctx:meal")
r = by_uid(rows)
uids = [x["uid"] for x in rows]
check("hub: sealed", sealed(rows, "hub"))
check("hub: plan_view anchored on THIS week's cook Sunday (first_sunday), the full horizon",
      CALLS and CALLS[-1] == (TODAY, HORIZON, WK), CALLS)
check("hub: head = week label · cook Sunday · 3 meals, dead",
      r["meal-head"]["title"] == f"🥘 {meal.week_label(WK)} · {COOK(WK)} · 3 meals"
      and not r["meal-head"]["valid"], r["meal-head"]["title"])
check("hub: rows in order (b, l, x), then 📆 🔄 🛒 📚×3 ℹ️",
      uids == ["meal-head", f"meal-b-{U2[:8]}", f"meal-l-{U1[:8]}", f"meal-x-{U5[:8]}", "meal-next", "meal-sync",
               "meal-groc", "meal-lib-b", "meal-lib-l", "meal-lib-s", "meal-status"], uids)
check("hub: the retired rows are gone",
      not any(u in r for u in ("meal-plan", "meal-import", "meal-fill", "meal-b", "meal-l", "meal-s")))
b = r[f"meal-b-{U2[:8]}"]
check("hub: breakfast title carries the glyph and the planned day",
      b["title"] == f"🍳 Oats · {WK:%a %-d %b}", b["title"])
meal_row_ok(b, U2, "https://oats.example/recipe", "hub breakfast")
check("hub: ⌘ live on a meal with a library task, the task variables ride",
      b["mods"]["cmd"]["valid"] and b["variables"]["task_id"] == "t1" and b["variables"]["task_list_id"] == LIST
      and b["variables"]["item_type"] == "task" and "Oats" in b["variables"]["task_title"], b["variables"])
check("hub: ⌥ dead on a plan row", not b["mods"]["alt"]["valid"] and b["mods"]["alt"]["arg"] == "")
l = r[f"meal-l-{U1[:8]}"]
meal_row_ok(l, U1, "", "hub lunch")
x = r[f"meal-x-{U5[:8]}"]
check("hub: a recipe Mela does not know is a 🍽️ row named after the event, ⌘ dead, no task id",
      x["title"].startswith("🍽️ Mystery Pie") and x["arg"] == f"open:mela://recipe/{U5}"
      and not x["mods"]["cmd"]["valid"] and not x["variables"].get("task_id"), x)
check("hub: 📆 row → ctx:mealq by trampoline, ⌥ by variable, counts the calendar",
      r["meal-next"]["arg"] == "xact:crmbrowse:ctx:mealq" and r["meal-next"]["mods"]["alt"]["variables"]["browse_ctx"] == "ctx:mealq"
      and r["meal-next"]["title"] == f"📆 Next {HORIZON} weeks" and "5 planned meals" in r["meal-next"]["subtitle"], r["meal-next"])
s = r["meal-sync"]
check("hub: 🔄 row = xact:meal_sync with the back payload, ⌥⇧ the same verb, counts new + to fill",
      s["arg"].startswith("xact:meal_sync:") and payload(s) == {"back": "ctx:meal"} and s["valid"]
      and s["mods"]["alt+shift"]["arg"] == s["arg"] and s["title"] == "🔄 Sync with Mela · 2 new · 14 to fill"
      and "onto the routine + groceries + note" in s["subtitle"], s)
check("hub: 🔄 never on ⌘ or ⌥", not s["mods"]["cmd"]["valid"] and not s["mods"]["alt"]["valid"])
check("hub: groceries row counts, no rebuild verb any more",
      "1 open list" in r["meal-groc"]["title"] and r["meal-groc"]["arg"] == "xact:crmbrowse:ctx:mealgroc"
      and not r["meal-groc"]["mods"]["alt+shift"]["valid"], r["meal-groc"])
check("hub: library rows", r["meal-lib-l"]["arg"] == "xact:crmbrowse:ctx:meallib:lunch" and "Lunches · 2" in r["meal-lib-l"]["title"])
check("hub: status row = Mela age · calendar count", r["meal-status"]["title"] == "ℹ️ Mela data 4 min old · calendar 5 planned meals"
      and "4 recipes" in r["meal-status"]["subtitle"] and not r["meal-status"]["valid"], r["meal-status"]["title"])
check("hub: ⌃ backs to the folders", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:folders" for x in rows))
ERROR[0] = "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)"
r2 = by_uid(rows_for("ctx:meal"))
check("hub: plan_view error → head wears the cache chip, says nothing planned, status shows the line",
      r2["meal-head"]["title"].endswith("nothing planned in Mela · cache") and r2["meal-status"]["title"] == f"ℹ️ {ERROR[0]}"
      and not any(u.startswith("meal-b-") for u in r2), r2["meal-head"]["title"])
ERROR[0] = ""
saved = PLANNED[:]
del PLANNED[:3]
r3 = by_uid(rows_for("ctx:meal"))
check("hub: nothing planned this week → head says so, no meal rows, the rest stays",
      "nothing planned in Mela" in r3["meal-head"]["title"] and "meal-next" in r3 and "meal-sync" in r3
      and not any(u.startswith(("meal-b-", "meal-l-", "meal-x-")) for u in r3), list(r3))
PLANNED[:] = saved
rq = rows_for("ctx:meal", "grocer")
check("hub: a typed bar filters the rows", [x["uid"] for x in rq] == ["meal-groc"], [x["uid"] for x in rq])
os.environ["meal_list_id"] = ""
ro = rows_for("ctx:meal")
check("hub: blank list id = off row", len(ro) == 1 and ro[0]["uid"] == "meal-off" and not ro[0]["valid"])
os.environ["meal_list_id"] = LIST

# ── parse_ctx guard ───────────────────────────────────────────────────────────
plant()
check("parse_ctx: 'today' typed on the quarter stays put", render("ctx:mealq", "today") == ("mealq", [], "today"))
check("parse_ctx: 'inbox' on the hub stays put", render("ctx:meal", "inbox") == ("meal", [], "inbox"))
check("parse_ctx: a week ctx carries its Sunday", render("ctx:mealw:2026-10-04") == ("mealw", ["2026-10-04"], ""))
os.environ["browse_ctx"] = "ctx:countdowns"
check("parse_ctx: elsewhere the alias still works", browse.parse_ctx("today")[0] == "smart")
os.environ.pop("browse_ctx", None)

# ── the quarter ───────────────────────────────────────────────────────────────
rows = rows_for("ctx:mealq")
r = by_uid(rows)
check("quarter: sealed", sealed(rows, "quarter"))
check("quarter: 13 rows, one per cook Sunday from this week's",
      [x["uid"] for x in rows] == [f"mq-{(WK + timedelta(days=7 * i)).isoformat()}" for i in range(HORIZON)], [x["uid"] for x in rows])
w0 = r[f"mq-{WK.isoformat()}"]
check("quarter: this week starred, meals joined, ⏎ trampoline to the week, ⌥ by variable, ⌘ dead",
      w0["title"] == f"⭐️ {meal.week_label(WK)} · 🍳 Oats · 🍛 Beef Bulgogi · 🍽️ Mystery Pie" and w0["valid"]
      and w0["arg"] == f"xact:crmbrowse:ctx:mealw:{WK.isoformat()}"
      and w0["mods"]["alt"]["variables"]["browse_ctx"] == f"ctx:mealw:{WK.isoformat()}"
      and not w0["mods"]["cmd"]["valid"], w0)
w1 = r[f"mq-{(WK + timedelta(days=7)).isoformat()}"]
check("quarter: an empty week is dead and says where to plan it",
      w1["title"] == f"{meal.week_label(WK + timedelta(days=7))} · nothing planned" and not w1["valid"]
      and "Plan it in Mela: ⌘⌥A Add to Calendar" in w1["subtitle"] and not w1["title"].startswith("⭐️"), w1)
w2 = r[f"mq-{(WK + timedelta(days=14)).isoformat()}"]
check("quarter: a later planned week is live", w2["valid"] and "🌮 Pockets" in w2["title"] and "1 meal " in w2["subtitle"], w2)
check("quarter: ⌃ backs to the hub", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
check("quarter: the bar filters on meal names", [x["uid"] for x in rows_for("ctx:mealq", "pockets")] == [f"mq-{(WK + timedelta(days=14)).isoformat()}"])
check("quarter: the bar filters on the week label",
      [x["uid"] for x in rows_for("ctx:mealq", meal.week_label(WK + timedelta(days=7)))][:1] == [f"mq-{(WK + timedelta(days=7)).isoformat()}"])

# ── one week ──────────────────────────────────────────────────────────────────
wk = (WK + timedelta(days=14)).isoformat()
rows = rows_for(f"ctx:mealw:{wk}")
r = by_uid(rows)
check("week: sealed", sealed(rows, "week"))
check("week: head + the meal row", [x["uid"] for x in rows] == ["mw-head", f"mw-s-{U3[:8]}"]
      and r["mw-head"]["title"] == f"🥘 {meal.week_label(WK + timedelta(days=14))} · {COOK(WK + timedelta(days=14))} · 1 meal", [x["uid"] for x in rows])
meal_row_ok(r[f"mw-s-{U3[:8]}"], U3, "https://pockets.example", "week snack")
check("week: ⌘ live (Pockets is t3)", r[f"mw-s-{U3[:8]}"]["variables"]["task_id"] == "t3" and r[f"mw-s-{U3[:8]}"]["mods"]["cmd"]["valid"])
check("week: ⌃ backs to the quarter", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:mealq" for x in rows))
rows = rows_for(f"ctx:mealw:{(WK + timedelta(days=21)).isoformat()}")
check("week: an empty one = the head alone, nothing planned", len(rows) == 1 and "nothing planned in Mela" in rows[0]["title"]
      and "⌘⌥A" in rows[0]["subtitle"], rows)
check("week: a weekday resolves to its cook Sunday",
      by_uid(rows_for(f"ctx:mealw:{(WK + timedelta(days=3)).isoformat()}"))["mw-head"]["title"].startswith(f"🥘 {meal.week_label(WK)}"))
check("week: a bad date", "needs" in browse.render_mealw(["yesterday"], "")[0]["title"])
check("week: the bar filters", [x["uid"] for x in rows_for(f"ctx:mealw:{WK.isoformat()}", "bulg")] == ["mw-head", f"mw-l-{U1[:8]}"])

# ── the library + groceries ───────────────────────────────────────────────────
rows = rows_for("ctx:meallib:lunch")
r = by_uid(rows)
check("library: sealed", sealed(rows, "lib"))
check("library: never cooked first, then least recently cooked", [x["uid"] for x in rows] == ["ml-head", "ml-t4", "ml-t2"], [x["uid"] for x in rows])
check("library: chips read off the calendar",
      r["ml-t4"]["subtitle"].startswith("never cooked · no description yet")
      and r["ml-t2"]["subtitle"].startswith(f"{meal.lib_chip(PLANNED, U1, TODAY)} · recipe in the description"),
      (r["ml-t4"]["subtitle"], r["ml-t2"]["subtitle"]))
meal_row_ok(r["ml-t4"], U4, "https://second.example", "library lunch")
meal_row_ok(r["ml-t2"], U1, "", "library bulgogi")
check("library: ⌘ live with the task variables", r["ml-t2"]["mods"]["cmd"]["valid"] and r["ml-t2"]["variables"]["task_id"] == "t2"
      and r["ml-t2"]["variables"]["task_title"] == LIB[1]["title"])
check("library: ⌥ dead without subtasks, still the drill hop", not r["ml-t2"]["mods"]["alt"]["valid"]
      and r["ml-t2"]["mods"]["alt"]["variables"]["browse_ctx"] == f"ctx:subtasks:{LIST}:t2")
rs = by_uid(rows_for("ctx:meallib:snack"))
check("library: the next planned Sunday shows", f"next {WK + timedelta(days=14):%a %-d %b}" in rs["ml-t3"]["subtitle"], rs["ml-t3"]["subtitle"])
check("library: filter", [x["uid"] for x in rows_for("ctx:meallib:lunch", "second")] == ["ml-head", "ml-t4"])
check("library: a bad tag", "needs" in browse.render_meallib(["dinner"], "")[0]["title"])
check("library: ⌃ backs to the hub", all(x["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:meal" for x in rows))
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
sys.argv = ["browse.py", "ctx:mealq"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    browse.main()
out = json.loads(buf.getvalue())
check("main(): the quarter renders by explicit ctx", sum(1 for i in out.get("items", []) if i.get("uid", "").startswith("mq-")) == HORIZON)

print(f"\nmeal screens: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
