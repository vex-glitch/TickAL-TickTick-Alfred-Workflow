#!/usr/bin/env python3
"""src/meal_write.py against a FAKE TickTick client, an injected Mela
library and an injected calendar plan (mela_cal.Planned rows built here -
NO real store, NO network): sync's order of writes (deletes before
creates, pointer-only deletes), one pointer per planned meal in b/l/s/x
order with 🍽️ for a recipe outside the three slots, the grocery rules, an
empty week clearing pointers + open groceries, the dry run writing nothing,
refusals (ids blank, calendar unreadable, Mela missing, rate limit),
plan_view's shape, import dedupe + cap + rate limit, the backfill's
live-read rule, and (2026-09-21) the verdict verbs: mark_cooked's tag +
note (live read, ONE update, no write when nothing changes, dry = no
call), rate (set / replace / clear / unchanged / refused), comment
(appended, blank refused), mirror_ratings (unrated entries only, Mela's
"Rating:" copy stripped, cap, rate limit) and the sync's rating pass (the
toast's "N ratings from Mela", a rate limit that never aborts the week,
the dry run's "would mirror"), and (2026-09-22, D25) the portions verb:
grocery_body at a count, _portions_of off content / desc, week_lists
(under the upcoming 🛒 task, loose in the library without one, sorted,
never raising, off the caches after a sync), set_portions (live read then
ONE update with items + content, the items re-cut with the ×1.25 note, a
tick carried by name, the same count = no write and "unchanged", 0 / 41 /
a word refused, a library task and a recipe Mela does not know refused,
dry = no call, the cache patched) and the sync re-making a loose list at
the count it was re-cut to, and (2026-09-22, D26) the prices: grocery_body
with a book (the suffix on every priced line, the cost line FIRST in the
description, portions_of still reading the note, no book or an empty book
= byte-identical), _write_groceries and the sync pricing new lists from
the book they load once, set_portions re-pricing a re-cut with the ticks
kept across the suffix, reprice_lists (ids and statuses kept, suffixes
and the cost line replaced, unchanged = no write, an empty book or an
itemless list = no write, a rate limit counted for the rest, dry = no
call), refresh_prices (keys off the cached week lists, a FAKE fetch,
the book saved to a temp path, the lists re-priced, the toast, dry = no
fetch, no week = refused), set_price / set_search on a temp book,
week_cost off the cached cost lines, and the real ~/.ticktick_alfred
book never written. Caches and the book live in a temp dir.
Run: python3 tests/test_meal_write.py
"""
import os
import sys
import tempfile
from datetime import date
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
TMP = tempfile.mkdtemp(prefix="tickal-mealw-")
os.environ["meal_list_id"] = LIST = "5eed00000000000000000a01"
os.environ["meal_routine_id"] = RID = "5eed00000000000000000b02"
os.environ.pop("TICKAL_MEAL_DRY", None)
RLIST = "5eed00000000000000000b01"
import cache as cache_store                    # noqa: E402
cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR)
import meal                                    # noqa: E402
import meal_price as mp                        # noqa: E402
import meal_write as mw                        # noqa: E402
import mela                                    # noqa: E402
import mela_cal                                # noqa: E402

# the price book (D26) lives in the temp dir for the whole run: _book_path
# hands back BOOK_PATH the moment it differs from its birth value, so this
# one line beats config.CONFIG_DIR, and the real book on this Mac is never
# read (it would price every list below) nor written (asserted at the end)
REAL_BOOK = mp._BOOK_PATH_BORN
HAD_REAL_BOOK = os.path.exists(REAL_BOOK)
mp.BOOK_PATH = os.path.join(TMP, "meal_prices.json")
mw.IMPORT_LEDGER = os.path.join(TMP, "meal_import.json")
mw.GONE_LEDGER = os.path.join(TMP, "meal_gone.json")          # never the real memory of trashed ids
mw.LOCK_FILE = os.path.join(TMP, "meal.lock")
mw.POST_GAP = 0.0
mw.PACE = 0.0                                   # the sync's own imports + backfills
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
U8 = "88888888-8888-8888-8888-888888888888"     # planned, unknown to Mela AND the library
U9 = "99999999-9999-9999-9999-999999999999"     # a stray library entry, never planned


class RateLimitError(Exception):
    pass


class FakeAPI:
    def __init__(self, lists):
        self.lists = {pid: {t["id"]: dict(t) for t in ts} for pid, ts in lists.items()}
        self.calls = []
        self.n = 0
        self.fail_after = None

    def _bump(self, kind, *a):
        self.calls.append((kind,) + a)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RateLimitError("exceed_query_limit")

    def get_task(self, pid, tid):
        self._bump("get", pid, tid)
        return dict(self.lists[pid][tid])

    def get_project_data(self, pid):
        self._bump("pd", pid)
        return {"project": {"id": pid}, "tasks": [dict(t) for t in self.lists.get(pid, {}).values()]}

    def create_task(self, title, project_id=None, due_date=None, content=None, priority=0,
                    tags=None, column_id=None, parent_id=None, kind=None, start_date=None,
                    repeat_flag=None, reminders=None, time_zone=None):
        self._bump("create", project_id, title)
        self.n += 1
        t = {"id": f"new{self.n}", "projectId": project_id, "title": title, "status": 0,
             "dueDate": due_date, "content": content or "", "tags": tags or [],
             "parentId": None, "kind": kind or "TEXT", "sortOrder": -self.n,
             "timeZone": time_zone}
        self.lists.setdefault(project_id, {})[t["id"]] = dict(t, parentId=parent_id)
        return dict(t)

    def update_task(self, tid, pid, current=None, **fields):
        assert current is not None, "the live-read rule"
        self._bump("update", pid, tid, tuple(sorted(fields)))
        t = dict(current)
        t.update(fields)
        self.lists.setdefault(pid, {})[tid] = t
        return dict(t)

    def delete_task(self, pid, tid):
        self._bump("delete", pid, tid)
        self.lists[pid].pop(tid, None)
        return True


def R(uuid, title, cats=("01 • Meal",), yield_text="4", ings="500 g chicken\n1 tbsp oil\n# Sauce\n2 tsp soy",
      link=""):
    return mela.Recipe(id=uuid, pk=1, title=title, yield_text=yield_text, ingredients=ings,
                       instructions="Cook.", categories=list(cats), link=link)


def P(day, uuid, title, cal="Inbox"):
    """A calendar row the way mela_cal.plan hands them over (timed 07:00)."""
    return mela_cal.Planned(date=day, start=None, all_day=True, uuid=uuid, title=title,
                            calendar=cal, event_id=f"ev-{uuid[:4]}-{day}",
                            url=f"mela://calendar/cal:ev/{uuid}")


RECIPES = [R(U1, "Beef Bulgogi", link="https://example.org/bulgogi"),
           R(U2, "Oats", ("02 • Breakfast",)), R(U3, "Pockets", ("03 • Snack",))]
BY = {r.id: r for r in RECIPES}
mw._mela = lambda: (RECIPES, BY, None)          # no real Mela here
mela.freshness = lambda: {"age_s": 0, "newest_recipe_date": None, "db_path": "", "present": True}   # nor its store: hub_counts would snapshot it
NOTE_CALLS = []
mw._write_note = lambda meals, sunday: (NOTE_CALLS.append((list(meals), sunday)) or True)
import api as _api_mod                          # noqa: E402
_api_mod.RateLimitError = RateLimitError
mw._rate_limited = lambda e: isinstance(e, RateLimitError)

SUN = date(2026, 9, 27)                          # the routine's live occurrence
TODAY = date(2026, 9, 21)                        # a Monday
PLANNED = [P(date(2026, 9, 20), U3, "Pockets"),                 # last week (cooked history)
           P(SUN, U1, "Beef Bulgogi"), P(SUN, U2, "Oats"), P(SUN, U3, "Pockets"),
           P(SUN, U8, "Mystery Bake", cal="Mela"),               # unknown to Mela → 🍽️
           P(date(2026, 10, 4), U1, "Beef Bulgogi")]              # next week: NOT mirrored


def T(tid, title, pid=LIST, tags=(), status=0, parent=None, **kw):
    t = {"id": tid, "projectId": pid, "title": title, "tags": list(tags), "status": status,
         "parentId": parent, "content": "", "kind": "TEXT"}
    t.update(kw)
    return t


def fresh():
    lib = [T("t1", f"[Oats](mela://recipe/{U2})", tags=["🍳breakfast"]),
           T("t2", f"[Beef Bulgogi](mela://recipe/{U1})", tags=["🍛lunch"]),
           T("t3", f"[Pockets](mela://recipe/{U3})", tags=["🌮snack"]),
           T("t4", f"[Stray](mela://recipe/{U9})", tags=["🍛lunch"]),
           T("g_old", meal.grocery_title("Gone", U9), tags=["🛒groceries"], kind="CHECKLIST"),
           T("g_done", meal.grocery_title("Ticked", U9), tags=["🛒groceries"], kind="CHECKLIST", status=2),
           T("g_keep", meal.grocery_title("Oats", U2), tags=["🛒groceries"], kind="CHECKLIST",
             dueDate="2026-09-01T00:00:00+0000")]
    rl = [T("r0", "🥘 Meal Prep", pid=RLIST, startDate="2026-09-27T17:00:00.000+0000"),
          T("p_old", meal.pointer_title("l", "Last week", U9), pid=RLIST, parent=RID),
          T("step", "Wipe the counter", pid=RLIST, parent=RID),
          T("p_arch", meal.pointer_title("s", "Archived", U3), pid=RLIST, parent=RID, repeatTaskId="x")]
    rl[0]["id"] = RID
    api = FakeAPI({LIST: lib, RLIST: rl})
    cache_store.set("all_tasks", [dict(t, _projectId=t["projectId"]) for t in lib + rl])
    cache_store.set("projects", [{"id": LIST, "name": "🍳Meal Prep"}, {"id": RLIST, "name": "🌅 Routines"}])
    cache_store.set(f"project_data_{LIST}", {"project": {"id": LIST}, "tasks": lib})
    cache_store.set(f"project_data_{RLIST}", {"project": {"id": RLIST}, "tasks": rl})
    return api


def pointers(api):
    return [t for t in api.lists[RLIST].values() if meal.is_pointer(t["title"]) and not t.get("repeatTaskId")]


def groceries(api):
    return {meal.link_uuid(t["title"]): t for t in api.lists[LIST].values()
            if meal.is_grocery(t["title"]) and t["status"] == 0}


# ── dry run ───────────────────────────────────────────────────────────────────
api = fresh()
out = mw.sync(today=TODAY, api=api, dry=True, planned=PLANNED, recipes=RECIPES)
check("dry run returns text", isinstance(out, str) and "DRY RUN" in out and "Week of 28 Sep" in out
      and "cook Sun 27 Sep" in out, out[:120])
check("dry run reads only", all(c[0] in ("get", "pd") for c in api.calls), api.calls)
check("dry run names the stale pointer + grocery and the four meals",
      "p_old" in out and "g_old" in out and "due 2026-09-26: keep 1" in out and "create 3" in out
      and "🍽️ Mystery Bake" in out and "NOT in the library" in out, out)
check("dry run: no import ledger, no note", not os.path.exists(mw.IMPORT_LEDGER) and not NOTE_CALLS)
os.environ["TICKAL_MEAL_DRY"] = "1"
api = fresh()
out = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
check("TICKAL_MEAL_DRY=1 is a dry run too", isinstance(out, str) and "DRY RUN" in out
      and all(c[0] in ("get", "pd") for c in api.calls))
os.environ.pop("TICKAL_MEAL_DRY", None)

# ── refusals ─────────────────────────────────────────────────────────────────
os.environ["meal_list_id"] = ""
try:
    mw.sync(today=TODAY, api=fresh(), planned=PLANNED, recipes=RECIPES)
    check("blank list id refused", False)
except mw.Refusal as e:
    check("blank list id refused", "Meal prep is off" in str(e), str(e))
os.environ["meal_list_id"] = LIST
_cal = mw._calendar_plan
mw._calendar_plan = lambda since=None, until=None: ([], [], "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)")
try:
    api = fresh()
    mw.sync(today=TODAY, api=api, recipes=RECIPES)
    check("unreadable calendar refused", False)
except mw.Refusal as e:
    check("unreadable calendar refused with the FDA line", "Full Disk Access" in str(e), str(e))
    check("unreadable calendar: nothing written, nothing read", api.calls == [], api.calls)
mw._calendar_plan = _cal
_m = mw._mela
mw._mela = lambda: ([], {}, "Mela database not found")
try:
    mw.sync(today=TODAY, api=fresh(), planned=PLANNED)
    check("Mela missing refused", False)
except mw.Refusal as e:
    check("Mela missing refused", "Mela" in str(e), str(e))
mw._mela = _m

# ── the real thing ────────────────────────────────────────────────────────────
api = fresh()
NEW_LUNCH = R("11111111-1111-1111-1111-111111111111", "New Lunch")
res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES + [NEW_LUNCH])
kinds = [c[0] for c in api.calls]
check("outcome is the sync toast", isinstance(res, mw.Outcome) and res.reopen == "ctx:meal" and res.msg ==
      "🔄 Mela · +1 recipe · 3 filled · cook Sun 27 Sep: 🍳 Oats · 🍛 Beef Bulgogi · 🌮 Pockets · 🍽️ Mystery Bake"
      " · 4 grocery lists · 3 recipes dated", res)
check("import ran inside the sync: the new recipe is in the library",
      any(t["title"].startswith("[New Lunch](mela://recipe/1111") for t in api.lists[LIST].values()))
check("backfill ran inside the sync: the three library bodies are filled, the stray untouched",
      all(api.lists[LIST][t]["content"].startswith("> 🔗 [") for t in ("t1", "t2", "t3"))
      and api.lists[LIST]["t4"]["content"] == "")
dels = [c for c in api.calls if c[0] == "delete"]
check("deletes: the old pointer and the stale grocery only",
      sorted(c[2] for c in dels) == ["g_old", "p_old"], dels)
check("the routine's own step, the archived copy and the ticked list survive",
      "step" in api.lists[RLIST] and "p_arch" in api.lists[RLIST] and "g_done" in api.lists[LIST])
first_ptr_create = next(i for i, c in enumerate(api.calls) if c[0] == "create" and c[1] == RLIST)
check("pointer deletes come before pointer creates",
      api.calls.index(("delete", RLIST, "p_old")) < first_ptr_create)
ptrs = sorted(pointers(api), key=lambda t: t["id"])
check("four pointers under the routine, dated the cook Sunday, b/l/s/x order",
      [meal.pointer_slot(t["title"]) for t in ptrs] == ["b", "l", "s", "x"]
      and all(t["parentId"] == RID and t["dueDate"] == meal.api_day(date(2026, 9, 27)) and t["kind"] == "TEXT" for t in ptrs), ptrs)
check("pointer titles: glyph + Mela link, 🍽️ named after the event",
      ptrs[0]["title"] == f"🍳 [Oats](mela://recipe/{U2})"
      and ptrs[3]["title"] == f"🍽️ [Mystery Bake](mela://recipe/{U8})", [t["title"] for t in ptrs])
check("next week's meal is NOT mirrored", not any("2026-10-04" in (t.get("dueDate") or "") for t in ptrs))
grocs = groceries(api)
check("groceries: kept one re-dated, three created, stale gone",
      set(grocs) == {U1, U2, U3, U8} and grocs[U2]["id"] == "g_keep" and grocs[U2]["dueDate"] == meal.api_day(date(2026, 9, 26))
      and grocs[U1]["kind"] == "CHECKLIST" and grocs[U1]["dueDate"] == meal.api_day(date(2026, 9, 26)), grocs)
check("grocery checklist items scaled ×1.75 (4 → 7), header dropped",
      [it["title"] for it in grocs[U1]["items"]] == ["875 g chicken", "1 3/4 tbsp oil", "3 1/2 tsp soy"],
      grocs[U1].get("items"))
check("grocery description carries the yield note", grocs[U1]["content"].startswith("Scaled ×1.75: 4 → 7 portions"),
      grocs[U1]["content"])
check("grocery for a recipe Mela does not know: the warning, no items",
      grocs[U8]["content"].startswith("⚠️ recipe not in Mela") and not grocs[U8].get("items"), grocs[U8])
check("grocery tag", grocs[U3]["tags"] == ["🛒groceries"])
check("the weekly note was written for the cook Sunday with the four meals",
      NOTE_CALLS and NOTE_CALLS[-1][1] == SUN and [m.slot for m in NOTE_CALLS[-1][0]] == ["b", "l", "s", "x"]
      and NOTE_CALLS[-1][0][0].uuid == U2, NOTE_CALLS)
check("no cooked-history ledger any more (only the import ledger file exists)",
      not hasattr(mw, "LEDGER") and not os.path.exists(os.path.join(TMP, "meal_ledger.json")))
led = mw._load_import_ledger(mw.IMPORT_LEDGER)
check("the import ledger remembers the import", [w["uuid"] for w in led["weeks"]] == [NEW_LUNCH.id])
at = cache_store.get("all_tasks")
ids = {t["id"] for t in at}
check("cache: deleted ids gone, new ones in", "p_old" not in ids and "g_old" not in ids
      and all(t["id"] in ids for t in ptrs) and grocs[U1]["id"] in ids)
pd = cache_store.get(f"project_data_{RLIST}")
check("cache: the routine list's project_data mirrors it", "p_old" not in {t["id"] for t in pd["tasks"]}
      and all(t["id"] in {x["id"] for x in pd["tasks"]} for t in ptrs))
check("cache: all_tasks never invalidated", cache_store.get("all_tasks") is not None)
n_calls = len(api.calls)
check("call count is modest (< 40)", n_calls < 40, n_calls)

# a second sync replaces the week: pointers re-minted, groceries kept, nothing imported
before = {t["id"] for t in pointers(api)}
res2 = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES + [NEW_LUNCH])
after = {t["id"] for t in pointers(api)}
check("re-sync: pointers re-minted, still four", not (before & after) and len(after) == 4)
check("re-sync: groceries kept, none created, nothing new",
      res2.msg.startswith("🔄 Mela · nothing new · cook Sun 27 Sep") and "4 grocery lists" in res2.msg
      and len([c for c in api.calls[n_calls:] if c[0] == "create" and c[1] == LIST]) == 0, res2.msg)

# ── note lines ────────────────────────────────────────────────────────────────
wk = meal.week_meals(PLANNED, BY, None, [], SUN)
lines = mw.note_lines(wk.meals)
check("note lines: the three slot lines then the 🍽️ extra",
      lines[0] == f"- 🍳 [Oats](mela://recipe/{U2})" and lines[2].startswith("- 🌮 [Pockets]")
      and lines[3] == f"- 🍽️ [Mystery Bake](mela://recipe/{U8})" and len(lines) == 4, lines)
check("note lines: a missing slot is a placeholder",
      mw.note_lines([m for m in wk.meals if m.slot != "l"])[1] == "- 🍛 _(not planned)_")
check("note lines: an empty week says so", mw.note_lines([]) == ["- _(nothing planned in Mela)_"])

# ── a week with nothing planned ───────────────────────────────────────────────
api = fresh()
NOTE_CALLS.clear()
res = mw.sync(today=TODAY, api=api, planned=[P(date(2026, 10, 4), U1, "Beef Bulgogi")], recipes=RECIPES)
check("empty week: pointers cleared, none minted", pointers(api) == [] and "step" in api.lists[RLIST])
check("empty week: open groceries cleared, the ticked one kept",
      groceries(api) == {} and "g_done" in api.lists[LIST], groceries(api))
check("empty week: toast says nothing planned in Mela",
      "cook Sun 27 Sep: nothing planned in Mela · 0 grocery lists" in res.msg, res.msg)
check("empty week: the note gets the empty block", NOTE_CALLS and NOTE_CALLS[-1][0] == [])

# ── rate limit mid-way ────────────────────────────────────────────────────────
api = fresh()
api.fail_after = 8                              # backfill reads/updates + live reads, then boom
try:
    mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
    check("rate limit refuses", False)
except mw.Refusal as e:
    check("rate limit refuses with the wait wording", "rate limit" in str(e) and "Partly synced" in str(e), str(e))

# ── plan_view ─────────────────────────────────────────────────────────────────
fresh()
pv = mw.plan_view(today=TODAY, planned=PLANNED, recipes=RECIPES)
check("plan_view: 13 weeks from the coming Sunday", len(pv["weeks"]) == 13 and pv["first_sunday"] == SUN
      and pv["weeks"][0].sunday == SUN and pv["weeks"][12].sunday == date(2026, 12, 20), pv["first_sunday"])
check("plan_view: this week's four meals, tid resolved from the cached library, web from Mela",
      [m.slot for m in pv["weeks"][0].meals] == ["b", "l", "s", "x"]
      and pv["weeks"][0].meals[1].tid == "t2" and pv["weeks"][0].meals[1].web == "https://example.org/bulgogi"
      and pv["weeks"][0].meals[3].tid == "", pv["weeks"][0].meals)
check("plan_view: next week one meal, the rest empty",
      [m.uuid for m in pv["weeks"][1].meals] == [U1] and all(w.meals == [] for w in pv["weeks"][2:]))
check("plan_view: no error, count, entries", pv["error"] == "" and pv["planned_count"] == 6
      and len(pv["entries"]) == 4)
pv = mw.plan_view(today=date(2026, 9, 27), planned=PLANNED, recipes=RECIPES)
check("plan_view on a Sunday: that Sunday is the first week", pv["first_sunday"] == SUN)
pv = mw.plan_view(today=TODAY, planned=PLANNED, recipes=RECIPES, first_sunday=date(2026, 10, 6))
check("plan_view: first_sunday snaps to the cook Sunday", pv["first_sunday"] == date(2026, 10, 4))
mw._calendar_plan = lambda since=None, until=None: ([], [], "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)")
pv = mw.plan_view(today=TODAY, recipes=RECIPES)
check("plan_view never raises: the FDA line as error, 13 empty weeks",
      "Full Disk Access" in pv["error"] and len(pv["weeks"]) == 13 and all(w.meals == [] for w in pv["weeks"]))
mw._calendar_plan = _cal
mw._mela = lambda: ([], {}, "no Mela")
pv = mw.plan_view(today=TODAY, planned=PLANNED)
check("plan_view without Mela: meals still shown, slot 🍽️ off the event title, mela_error set",
      pv["mela_error"] == "no Mela" and pv["error"] == "" and len(pv["weeks"][0].meals) == 4
      and all(m.slot == "x" for m in pv["weeks"][0].meals) and pv["weeks"][0].meals[0].name == "Beef Bulgogi")
mw._mela = _m

# ── import_new ────────────────────────────────────────────────────────────────
api = fresh()
recs = RECIPES + [R("11111111-1111-1111-1111-111111111111", "New Lunch"),
                  R("22222222-2222-2222-2222-222222222222", "New Snack", ("03 • Snack",)),
                  R("33333333-3333-3333-3333-333333333333", "No category", ())]
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0, ledger_path=os.path.join(TMP, "imp1.json"))
made = [c for c in api.calls if c[0] == "create"]
check("import: only the categorised unknowns", r["created"] == 2 and r["no_category"] == 1 and r["skipped"] == 3, r)
check("import: title is the Mela link, tag lowercased", made[0][2].startswith("[New ") and "mela://recipe/" in made[0][2]
      and all(t["tags"] in (["🍛lunch"], ["🌮snack"]) for t in api.lists[LIST].values() if t["id"].startswith("new")))
check("import: body rendered", all(t["content"].startswith("> 🔗 [New") for t in api.lists[LIST].values() if t["id"].startswith("new")))
check("import: chip", r["chip"] == "🥘 +2 recipes")
r2 = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0, ledger_path=os.path.join(TMP, "imp1.json"))
check("import: the ledger stops a second run even with a stale 'existing'", r2["created"] == 0 and r2["skipped"] == 5, r2)
api = fresh()
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=1, pace=0, ledger_path=os.path.join(TMP, "imp2.json"))
check("import: cap + remaining", r["created"] == 1 and r["remaining"] == 1, r)
api = fresh()
api.fail_after = 0
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0, ledger_path=os.path.join(TMP, "imp3.json"))
check("import: rate limit stops the run", r["rate_limited"] and r["created"] == 0, r)
check("import: the default cap and pace are the sync's", mw.CAP_IMPORT == 40 and mw.CAP_FILL == 60
      and mw.import_new.__defaults__[4] == 40)

# ── backfill_descriptions ─────────────────────────────────────────────────────
api = fresh()
api.lists[LIST]["t2"]["content"] = "hand-written"          # appeared since the cache
entries = [{"tid": "t1", "pid": LIST, "uuid": U2, "title": "x"},
           {"tid": "t2", "pid": LIST, "uuid": U1, "title": "y"},
           {"tid": "t4", "pid": LIST, "uuid": U9, "title": "z"}]
seen = []
r = mw.backfill_descriptions(api, entries=entries, by_id=BY, cap=10, pace=0, progress=lambda i, n: seen.append((i, n)))
check("backfill: one filled, one skipped (live content), one not in Mela",
      r["filled"] == 1 and r["skipped"] == 1 and r["not_in_mela"] == 1, r)
check("backfill: live read before the write", [c[0] for c in api.calls][:2] == ["get", "update"])
check("backfill: the hand-written body survived", api.lists[LIST]["t2"]["content"] == "hand-written")
check("backfill: rendered body", api.lists[LIST]["t1"]["content"].startswith("> 🔗 [Oats](mela://recipe/"))
check("backfill: progress called", seen == [(1, 3), (2, 3), (3, 3)], seen)
r = mw.backfill_descriptions(fresh(), entries=entries, by_id=BY, cap=1, pace=0)
check("backfill: cap + remaining", r["filled"] == 1 and r["remaining"] == 2, r)

# ── missing_descriptions + hub_counts (cache only) ────────────────────────────
fresh()
miss = mw.missing_descriptions(LIST)
check("missing_descriptions: library entries without a body, sorted by title",
      [e["tid"] for e in miss] == ["t2", "t1", "t3", "t4"], [e["tid"] for e in miss])
hc = mw.hub_counts()
check("hub_counts", hc["missing"] == 4 and hc["new"] == 0 and hc["mela_ok"], hc)
mw._mela = lambda: (RECIPES + [NEW_LUNCH, R("2222", "Snk", ("03 • Snack",)), R("3333", "Nope", ())], {}, None)
hc = mw.hub_counts()
check("hub_counts: new counts the categorised unknowns, ledger-imported ones excluded",
      hc["new"] == 1 and hc["uncategorised"] == 1, hc)
mw._mela = _m

# ── the retired surface ───────────────────────────────────────────────────────
check("hourly / commit / preview / rebuild_groceries / _wake_mela are gone",
      not any(hasattr(mw, n) for n in ("hourly", "commit", "preview", "rebuild_groceries", "_wake_mela",
                                       "_resolve_picks", "BUDGET_HOURLY", "PACE_BG", "PACE_FG", "CAP_FG",
                                       "STALE_WAKE_S", "CAP_IMPORT_HOURLY", "LEDGER")))
import config as _cfg                           # noqa: E402
check("config.get_meal_wake_mela is gone", not hasattr(_cfg, "get_meal_wake_mela"))
with open(os.path.join(ROOT, "src", "sync.py"), encoding="utf-8") as f:
    _src = f.read()
    check("sync.py imports no meal writer and calls no hourly hitchhiker",
          "import meal_write" not in _src and ".hourly(" not in _src)


# ── the library's dates follow Mela (Vex 2026-09-21) ─────────────────────────
print("-- library dates")
api = fresh()
lib_now = list(api.lists[LIST].values())
d_set, d_clear = mw.date_plan(lib_now, PLANNED, TODAY)
check("date_plan: every planned entry takes its NEAREST upcoming day, the past 20 Sep ignored",
      sorted((t["id"], d.isoformat()) for t, d in d_set) == [("t1", "2026-09-27"), ("t2", "2026-09-27"), ("t3", "2026-09-27")],
      sorted((t["id"], d.isoformat()) for t, d in d_set))
check("date_plan: an unplanned undated entry is left alone", d_clear == [])
dated_t2 = dict(api.lists[LIST]["t2"], startDate="2026-09-27T00:00:00.000+0000", dueDate="2026-09-27T00:00:00.000+0000", isAllDay=True)
d_set2, _ = mw.date_plan([dated_t2], PLANNED, TODAY)
check("date_plan: an entry already on its day is skipped", d_set2 == [])
stale = dict(api.lists[LIST]["t4"], startDate="2026-09-10T00:00:00.000+0000", dueDate="2026-09-10T00:00:00.000+0000", isAllDay=True)
_, d_clear2 = mw.date_plan([stale], PLANNED, TODAY)
check("date_plan: a dated entry with no upcoming plan is cleared", [t["id"] for t in d_clear2] == ["t4"])
g = dict(api.lists[LIST]["g_keep"])
check("date_plan: a grocery list is never touched", mw.date_plan([g], PLANNED, TODAY) == ([], []))

res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
ups = [c for c in api.calls if c[0] == "update" and "startDate" in c[3] and c[2].startswith("t")]   # not the backfill (content), not g_keep
check("sync: one paced update per entry, dates set on the day Mela has them",
      [c[2] for c in ups] == ["t1", "t2", "t3"]
      and all(api.lists[LIST][t]["startDate"] == meal.api_day(date(2026, 9, 27)) and api.lists[LIST][t]["dueDate"] == meal.api_day(date(2026, 9, 27))
              and api.lists[LIST][t]["isAllDay"] is True for t in ("t1", "t2", "t3")),
      (ups, {t: api.lists[LIST][t].get("startDate") for t in ("t1", "t2", "t3", "t4")}))
check("sync: the stray stays undated, untouched", "startDate" not in api.lists[LIST]["t4"] or not api.lists[LIST]["t4"]["startDate"])
check("sync: the toast counts them", res.msg.endswith(" · 3 recipes dated"), res.msg)
check("sync: the cache mirrors the dates",
      next(t for t in cache_store.get("all_tasks") if t["id"] == "t2")["startDate"] == meal.api_day(date(2026, 9, 27)))
res = mw.sync(today=TODAY, api=api, planned=[P(date(2026, 10, 4), U1, "Beef Bulgogi")], recipes=RECIPES)
check("sync again with one plan left: Bulgogi moves to 4 Oct, the others lose their date",
      api.lists[LIST]["t2"]["startDate"] == meal.api_day(date(2026, 10, 4))
      and api.lists[LIST]["t1"]["startDate"] is None and api.lists[LIST]["t3"]["dueDate"] is None
      and api.lists[LIST]["t1"]["isAllDay"] is False, {t: api.lists[LIST][t].get("startDate") for t in ("t1", "t2", "t3")})
check("… toast: 3 recipes dated (one moved, two cleared)", " · 3 recipes dated" in res.msg, res.msg)
n_before = len(api.calls)
res = mw.sync(today=TODAY, api=api, planned=[P(date(2026, 10, 4), U1, "Beef Bulgogi")], recipes=RECIPES)
check("a third pass with nothing to change writes no dates and says nothing about them",
      "dated" not in res.msg and not [c for c in api.calls[n_before:] if c[0] == "update" and "startDate" in c[3]],
      (res.msg, api.calls[n_before:]))
probe = fresh()
mw.sync(today=TODAY, api=probe, planned=PLANNED, recipes=RECIPES)
api = fresh()
api.fail_after = len(probe.calls) - 2      # the rate limit lands on the LAST date updates
try:
    res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
    check("a rate limit inside the dating pass keeps the mirrored week and says how many dates are left",
          isinstance(res, mw.Outcome) and "left · run again" in res.msg and " dated" in res.msg, res.msg)
except mw.Refusal as e:
    check("a rate limit inside the dating pass keeps the mirrored week and says how many dates are left", False, str(e))
api.fail_after = None
out = mw.sync(today=TODAY, api=fresh(), dry=True, planned=PLANNED, recipes=RECIPES)
check("dry run lists the date plan", "library dates: set 3, clear 0" in out and "Oats → 2026-09-27" in out, out.splitlines()[-4:])


# ── a pointer the listing lost (v1 left the first press's undated ones out) ──
print("-- childIds fallback")
api = fresh()
ghost = T("p_ghost", meal.pointer_title("b", "Ghost", U2), pid=RLIST, parent=RID)
api.lists[RLIST][RID]["childIds"] = ["p_old", "step", "p_arch", "p_ghost", "p_gone"]
api.ghost = ghost
_orig_get = api.get_task
def _get(pid, tid):
    if tid == "p_ghost":
        api._bump("get_task", pid, tid)
        return dict(ghost)
    if tid == "p_gone":
        api._bump("get_task", pid, tid)
        raise KeyError("404")
    return _orig_get(pid, tid)
api.get_task = _get
_orig_pd = api.get_project_data
api.get_project_data = lambda pid: (lambda d: d)(_orig_pd(pid))      # p_ghost is NOT in the listing
_orig_del = api.delete_task
deleted = []
def _del(pid, tid):
    deleted.append(tid)
    if tid in ("p_ghost",):
        api._bump("delete", pid, tid); return True
    return _orig_del(pid, tid)
api.delete_task = _del
res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
check("a pointer named in childIds but missing from the listing is read alone and deleted",
      "p_ghost" in deleted and "p_old" in deleted, deleted)
check("a childId that answers 404 is skipped, the sync still lands", "p_gone" not in deleted and isinstance(res, mw.Outcome), res)
check("the routine's own step is never touched", "step" not in deleted)


# ── the batch follows the MOVED prep task; lists hang off the 🛒 task (Vex 2026-09-21) ──
print("-- moved prep + groceries task")
BER = ZoneInfo("Europe/Berlin")
api = fresh()
api.lists[RLIST]["prep_tue"] = T("prep_tue", "🥘 Meal Prep", pid=RLIST, startDate="2026-09-22T07:00:00.000+0000", timeZone="Europe/Berlin")
api.lists[RLIST]["groc_tue"] = T("groc_tue", "🛒 Groceries", pid=RLIST, startDate="2026-09-22T06:00:00.000+0000", timeZone="Europe/Berlin")
TUE = [P(date(2026, 9, 22), U2, "Oats"), P(date(2026, 9, 22), U1, "Beef Bulgogi")] + PLANNED
out = mw.sync(today=TODAY, api=api, dry=True, planned=TUE, recipes=RECIPES)
check("dry run: the batch is the moved Tuesday task, groceries under the 🛒 task",
      "cook Tue 22 Sep" in out and "prep_tue" in out and "under groc_tue" in out and "due 2026-09-22" in out, out.splitlines()[:6])
res = mw.sync(today=TODAY, api=api, planned=TUE, recipes=RECIPES)
ptrs = pointers(api)
check("pointers under the moved copy only, dated its day in its zone",
      sorted(t["parentId"] for t in ptrs) == ["prep_tue", "prep_tue"]
      and all(t["dueDate"] == meal.api_day(date(2026, 9, 22), BER) for t in ptrs), ptrs)
check("… created in the prep task's zone", all(t.get("timeZone") == "Europe/Berlin" for t in ptrs), ptrs)
check("… the series' old pointer went", "p_old" not in api.lists[RLIST])
glists = [t for t in api.lists[RLIST].values() if meal.is_grocery(t["title"]) and meal.parse_title(t["title"]) and t["status"] == 0]
check("one list per meal as SUBTASKS of the 🛒 Groceries task, due its day",
      sorted(t["parentId"] for t in glists) == ["groc_tue", "groc_tue"]
      and all(t["dueDate"] == meal.api_day(date(2026, 9, 22), BER) and t.get("timeZone") == "Europe/Berlin" for t in glists), glists)
check("… the loose library-list lists are gone, the ticked one survives",
      groceries(api) == {} and "g_keep" not in api.lists[LIST] and "g_done" in api.lists[LIST])
check("… the toast names the cook day", "cook Tue 22 Sep: 🍳 Oats · 🍛 Beef Bulgogi · 2 grocery lists" in res.msg, res.msg)
check("… the note went to the week the batch feeds (Mon 21 Sep)", NOTE_CALLS and NOTE_CALLS[-1][1] == date(2026, 9, 20), NOTE_CALLS[-1:])
check("the trashed pointer id is remembered", "p_old" in mw._gone_ids(), mw._gone_ids())
res2 = mw.sync(today=TODAY, api=api, planned=TUE, recipes=RECIPES)
check("a second press keeps the lists (in place), re-mints the pointers",
      "2 grocery lists" in res2.msg and len(pointers(api)) == 2 and len([t for t in api.lists[RLIST].values() if meal.is_grocery(t["title"]) and meal.parse_title(t["title"]) and t["status"] == 0]) == 2, res2.msg)
api.lists[RLIST][RID]["childIds"] = ["p_old", "step"]
n_before = len(api.calls)
mw.sync(today=TODAY, api=api, planned=TUE, recipes=RECIPES)
check("a remembered childId is never read again",
      not [c for c in api.calls[n_before:] if c[0] == "get" and c[2] == "p_old"], [c for c in api.calls[n_before:] if c[0] == "get"])
api = fresh()
api.lists[LIST]["t1"]["timeZone"] = "Europe/London"
mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
check("a London-zone recipe gets London midnight; a zoneless one the Mac's",
      api.lists[LIST]["t1"]["startDate"] == meal.api_day(date(2026, 9, 27), ZoneInfo("Europe/London"))
      and api.lists[LIST]["t2"]["startDate"] == meal.api_day(date(2026, 9, 27)),
      (api.lists[LIST]["t1"]["startDate"], api.lists[LIST]["t2"]["startDate"]))



# ── the verdict verbs: cooked, rate, comment (Vex 2026-09-21) ────────────────
print("-- cooked / rate / comment")
TAG_CALLS = []
mw._ensure_cooked_tag = lambda: TAG_CALLS.append(1)     # never api_v2 (the Keychain) here
STAR = meal.STAR
api = fresh()
res = mw.mark_cooked(api, LIST, "t1")
check("cooked: the tag joins the others, in their order",
      api.lists[LIST]["t1"]["tags"] == ["🍳breakfast", "👨‍🍳cooked"], api.lists[LIST]["t1"]["tags"])
check("cooked: a LIVE read then ONE update",
      api.calls == [("get", LIST, "t1"), ("update", LIST, "t1", ("tags",))], api.calls)
check("cooked: the toast, no reopen of its own", isinstance(res, mw.Outcome) and res.msg == "👨‍🍳 Cooked · Oats"
      and res.reopen is None, res)
check("cooked: the tag entity was ensured once", TAG_CALLS == [1], TAG_CALLS)
check("cooked: the cache mirrors the tag",
      "👨‍🍳cooked" in next(t for t in cache_store.get("all_tasks") if t["id"] == "t1")["tags"])
n = len(api.calls)
res = mw.mark_cooked(api, LIST, "t1")
check("cooked again, no note: read only, nothing written, tag not doubled",
      api.calls[n:] == [("get", LIST, "t1")] and res.msg == "👨‍🍳 Already cooked · Oats"
      and api.lists[LIST]["t1"]["tags"] == ["🍳breakfast", "👨‍🍳cooked"], (api.calls[n:], res.msg))
res = mw.mark_cooked(api, LIST, "t2", comment="  less salt next time \n")
check("cooked with a note on an empty body: header minted (🔗 + 🌐 from Mela), the note under it, the tag",
      api.lists[LIST]["t2"]["content"] == f"> 🔗 [Beef Bulgogi](mela://recipe/{U1})\n"
      f"> 🌐 [example.org](https://example.org/bulgogi)\n> less salt next time"
      and api.lists[LIST]["t2"]["tags"] == ["🍛lunch", "👨‍🍳cooked"], api.lists[LIST]["t2"]["content"])
check("cooked with a note: ONE update carrying content + tags, the toast says note saved",
      api.calls[-1] == ("update", LIST, "t2", ("content", "tags")) and api.calls[-2] == ("get", LIST, "t2")
      and res.msg == "👨‍🍳 Cooked · Beef Bulgogi · note saved", (api.calls[-2:], res.msg))
res = mw.mark_cooked(api, LIST, "t2", comment="more garlic")
check("cooked again with a note: the note appended below the first, the tag kept single",
      meal.read_comments(api.lists[LIST]["t2"]["content"]) == ["less salt next time", "more garlic"]
      and api.lists[LIST]["t2"]["tags"] == ["🍛lunch", "👨‍🍳cooked"]
      and res.msg == "👨‍🍳 Already cooked · Beef Bulgogi · note saved", (api.lists[LIST]["t2"]["content"], res.msg))
check("cooked: the cache carries the note", meal.read_comments(next(t for t in cache_store.get("all_tasks") if t["id"] == "t2")["content"])
      == ["less salt next time", "more garlic"])
api.lists[LIST]["t3"]["tags"] = ["🌮snack", "👨‍🍳COOKED"]
n = len(api.calls)
res = mw.mark_cooked(api, LIST, "t3")
check("cooked: a hand-typed twin of the tag counts, case blind",
      api.calls[n:] == [("get", LIST, "t3")] and res.msg.startswith("👨‍🍳 Already cooked"), (api.calls[n:], res.msg))
api = fresh()
res = mw.mark_cooked(api, LIST, "t1", comment="x", dry=True)
check("cooked dry run: no api call at all, the line names the recipe and the note",
      api.calls == [] and res.msg == "🥘 Dry run · would tag Oats 👨‍🍳cooked · note", (api.calls, res.msg))
check("cooked dry run without a note", mw.mark_cooked(api, LIST, "t1", dry=True).msg == "🥘 Dry run · would tag Oats 👨‍🍳cooked"
      and api.calls == [])

# rate
api = fresh()
body = mela.render_markdown(BY[U2])             # Oats: a 🔗 line, then the body
api.lists[LIST]["t1"]["content"] = body
line0 = body.split("\n")[0]
res = mw.rate(api, LIST, "t1", 3)
c = api.lists[LIST]["t1"]["content"]
check("rate: the stars line right under the 🔗 line, the body byte-identical",
      c == body.replace(line0 + "\n", line0 + "\n> " + STAR * 3 + "\n", 1) and meal.read_rating(c) == 3, c[:160])
check("rate: live read, one update, the toast is the stars and the name",
      api.calls == [("get", LIST, "t1"), ("update", LIST, "t1", ("content",))] and res.msg == STAR * 3 + " Oats", (api.calls, res.msg))
n = len(api.calls)
res = mw.rate(api, LIST, "t1", "3")
check("rate: the same rating again (as a string, even) is no write",
      api.calls[n:] == [("get", LIST, "t1")] and res.msg == STAR * 3 + " Oats · unchanged", (api.calls[n:], res.msg))
res = mw.rate(api, LIST, "t1", 5)
c = api.lists[LIST]["t1"]["content"]
check("rate: replaced in place, one stars line", meal.read_rating(c) == 5 and c.count("> " + STAR) == 1
      and c.split("\n")[1] == "> " + STAR * 5 and res.msg == STAR * 5 + " Oats", c[:160])
res = mw.rate(api, LIST, "t1", 0)
check("rate 0: cleared, the description back to the render byte for byte",
      api.lists[LIST]["t1"]["content"] == body and res.msg == "Rating cleared · Oats", (api.lists[LIST]["t1"]["content"][:120], res.msg))
n = len(api.calls)
res = mw.rate(api, LIST, "t1", 0)
check("rate 0 on an unrated task: no write", api.calls[n:] == [("get", LIST, "t1")] and res.msg == "No rating · Oats · unchanged", res.msg)
check("rate: the cache mirrors the description", next(t for t in cache_store.get("all_tasks") if t["id"] == "t1")["content"] == body)
n = len(api.calls)
bad = []
for v in (None, 6, "abc", -1, "3/5"):
    try:
        mw.rate(api, LIST, "t1", v)
        bad.append((v, "accepted"))
    except mw.Refusal as e:
        if str(e) != "⭐️ Pick 1 to 5":
            bad.append((v, str(e)))
check("rate: None / 6 / a word / a negative / '3/5' refuse with the one line, nothing read", bad == [] and api.calls[n:] == [], (bad, api.calls[n:]))
res = mw.rate(api, LIST, "t3", 4)
check("rate on an empty body: the header minted from the title, the stars under it",
      api.lists[LIST]["t3"]["content"] == f"> 🔗 [Pockets](mela://recipe/{U3})\n> " + STAR * 4, api.lists[LIST]["t3"]["content"])
n = len(api.calls)
res = mw.rate(api, LIST, "t2", 2, dry=True)
check("rate dry run: no api call", api.calls[n:] == [] and res.msg == "🥘 Dry run · would rate Beef Bulgogi " + STAR * 2, res.msg)

# comment
n = len(api.calls)
res = mw.comment(api, LIST, "t3", "add less salt next time")
check("comment: appended under the stars, one update, the toast",
      api.lists[LIST]["t3"]["content"] == f"> 🔗 [Pockets](mela://recipe/{U3})\n> " + STAR * 4 + "\n> add less salt next time"
      and res.msg == "💬 Pockets · note saved"
      and api.calls[n:] == [("get", LIST, "t3"), ("update", LIST, "t3", ("content",))], (api.lists[LIST]["t3"]["content"], api.calls[n:]))
mw.comment(api, LIST, "t3", "more garlic\n\nand chilli")
check("comment: a second one goes below the first, one quote line per line",
      meal.read_comments(api.lists[LIST]["t3"]["content"]) == ["add less salt next time", "more garlic", "and chilli"],
      api.lists[LIST]["t3"]["content"])
mw.rate(api, LIST, "t3", 2)
check("rate after comments: the stars line replaced where it sits, the comments stay below it",
      api.lists[LIST]["t3"]["content"] == f"> 🔗 [Pockets](mela://recipe/{U3})\n> " + STAR * 2
      + "\n> add less salt next time\n> more garlic\n> and chilli", api.lists[LIST]["t3"]["content"])
n = len(api.calls)
bad = []
for v in ("", "  \n ", None, ">"):
    try:
        mw.comment(api, LIST, "t3", v)
        bad.append((v, "accepted"))
    except mw.Refusal as e:
        if str(e) != "💬 Nothing written":
            bad.append((v, str(e)))
check("comment: blank text refuses before any call (quote marks alone after the read)",
      bad == [] and all(c[0] == "get" for c in api.calls[n:]), (bad, api.calls[n:]))
n = len(api.calls)
res = mw.comment(api, LIST, "t1", "x", dry=True)
check("comment dry run: no api call", api.calls[n:] == [] and res.msg == "🥘 Dry run · would note on Oats: x", res.msg)

# ── Mela's ratings mirrored into the tasks that have none ────────────────────
print("-- Mela ratings mirrored")
RATED = [R(U2, "Oats", ("02 • Breakfast",)), R(U1, "Beef Bulgogi", link="https://example.org/bulgogi"),
         R(U3, "Pockets", ("03 • Snack",))]
RATED[0].text = "Rating: " + STAR * 4 + "\n\nSunday oats."     # description
RATED[1].notes = "Rating: " + STAR * 2                        # notes
RBY = {r.id: r for r in RATED}
OLD_OATS = (f"> 🔗 [Oats](mela://recipe/{U2})\n\nRating: " + STAR * 4
            + "\n\nSunday oats.\n\nServes: 4\n## Ingredients:\n- 500 g chicken\n")   # an older render: Mela's line in the blurb
RATED_BULGOGI = f"> 🔗 [Beef Bulgogi](mela://recipe/{U1})\n> " + STAR * 5 + "\n\nServes: 4\n"


def seed(api, **contents):
    for tid, content in contents.items():
        api.lists[LIST][tid]["content"] = content
        mw._cache_patch(tid, content=content)


api = fresh()
seed(api, t1=OLD_OATS, t2=RATED_BULGOGI)
entries = meal.library_entries(list(api.lists[LIST].values()), LIST)
check("library_entries reads the rating off the head block", {e["tid"]: e["rating"] for e in entries} == {"t1": None, "t2": 5, "t3": None, "t4": None})
r = mw.mirror_ratings(api, entries=entries, by_id=RBY, cap=10, pace=0)
check("mirror: only the unrated entry whose Mela recipe is rated", r == {"rated": 1, "skipped": 0, "remaining": 0, "failed": 0, "rate_limited": False}, r)
check("mirror: the stars under the 🔗 line, Mela's Rating: line gone from the body, the rest byte-identical",
      api.lists[LIST]["t1"]["content"] == f"> 🔗 [Oats](mela://recipe/{U2})\n> " + STAR * 4
      + "\n\nSunday oats.\n\nServes: 4\n## Ingredients:\n- 500 g chicken\n", api.lists[LIST]["t1"]["content"])
check("mirror: a TickTick-rated entry is left alone even though Mela rates it lower",
      api.lists[LIST]["t2"]["content"] == RATED_BULGOGI and not [c for c in api.calls if c[2] == "t2"])
check("mirror: live read then one update, nothing else", api.calls == [("get", LIST, "t1"), ("update", LIST, "t1", ("content",))], api.calls)
check("mirror: the cache mirrors it", meal.read_rating(next(t for t in cache_store.get("all_tasks") if t["id"] == "t1")["content"]) == 4)
stale = [dict(e, rating=None) for e in entries if e["tid"] == "t2"]
n = len(api.calls)
r = mw.mirror_ratings(api, entries=stale, by_id=RBY, cap=10, pace=0)
check("mirror: stars that appeared since the cache = skipped after the live read, no write",
      r["skipped"] == 1 and r["rated"] == 0 and api.calls[n:] == [("get", LIST, "t2")], (r, api.calls[n:]))
RATED[2].text = "Rating: " + STAR * 3
api = fresh()
seed(api, t1=OLD_OATS, t3=f"> 🔗 [Pockets](mela://recipe/{U3})\n\nServes: 2\n")
entries = meal.library_entries(list(api.lists[LIST].values()), LIST)
check("mirror: an EMPTY description is never a candidate (the backfill's, its render carries the stars)",
      [e["tid"] for e, _n, _r in mw._rating_candidates(entries, RBY)] == ["t1", "t3"], mw._rating_candidates(entries, RBY))
r = mw.mirror_ratings(api, entries=entries, by_id=RBY, cap=1, pace=0)
check("mirror: cap + remaining (t2's empty body is not counted)", r["rated"] == 1 and r["remaining"] == 1 and len(api.calls) == 2, r)
api = fresh()
seed(api, t1=OLD_OATS)
entries = meal.library_entries(list(api.lists[LIST].values()), LIST)
api.lists[LIST]["t1"]["content"] = ""                 # emptied between the cache and the live read
n = len(api.calls)
r = mw.mirror_ratings(api, entries=entries, by_id=RBY, cap=10, pace=0)
check("mirror: a body emptied since the cache = skipped after the live read, never a head block alone",
      r["skipped"] == 1 and r["rated"] == 0 and api.calls[n:] == [("get", LIST, "t1")]
      and api.lists[LIST]["t1"]["content"] == "", (r, api.calls[n:], api.lists[LIST]["t1"]["content"]))
api = fresh()
seed(api, t1=OLD_OATS, t3=f"> 🔗 [Pockets](mela://recipe/{U3})\n\nServes: 2\n")
entries = meal.library_entries(list(api.lists[LIST].values()), LIST)
api.fail_after = 0
r = mw.mirror_ratings(api, entries=entries, by_id=RBY, cap=10, pace=0)
check("mirror: the rate limit stops the pass, the rest counted", r["rate_limited"] and r["rated"] == 0 and r["remaining"] == 2, r)
check("mirror: the sync's cap", mw.CAP_RATE == 20 and mw.mirror_ratings.__defaults__[2] == 20)

# the sync's rating pass
api = fresh()
seed(api, t1=OLD_OATS, t3="Hand-written pockets.\n")
res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RATED)
check("sync: the toast counts the ratings from Mela", " · 2 ratings from Mela" in res.msg and "1 filled" in res.msg, res.msg)
check("sync: Oats adopted Mela's four stars, the Rating: copy gone",
      meal.read_rating(api.lists[LIST]["t1"]["content"]) == 4 and "Rating:" not in api.lists[LIST]["t1"]["content"])
check("sync: the hand-written body got a minted header and the stars on top, the body kept",
      api.lists[LIST]["t3"]["content"] == f"> 🔗 [Pockets](mela://recipe/{U3})\n> " + STAR * 3 + "\n\nHand-written pockets.\n",
      api.lists[LIST]["t3"]["content"])
check("sync: the backfilled body carries Mela's stars from the render, so it was never a candidate",
      meal.read_rating(api.lists[LIST]["t2"]["content"]) == 2 and len([c for c in api.calls if c[0] == "get" and c[2] == "t2"]) == 1)
check("sync: the week still landed", len(pointers(api)) == 4 and "4 grocery lists" in res.msg, res.msg)
n = len(api.calls)
res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RATED)
check("sync again: nothing to rate, the toast says nothing about ratings", "rating" not in res.msg, res.msg)
api = fresh()
seed(api, t1=OLD_OATS, t3="Hand-written pockets.\n")
_g, hits = api.get_task, []
def _limited_get(pid, tid):
    if tid == "t1" and not hits:
        hits.append(tid)
        api._bump("get", pid, tid)
        raise RateLimitError("exceed_query_limit")
    return _g(pid, tid)
api.get_task = _limited_get
res = mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RATED)
check("a rate limit inside the rating pass never aborts the sync: the week lands, the toast counts the ratings left",
      isinstance(res, mw.Outcome) and " · 2 ratings left · run again" in res.msg and "ratings from Mela" not in res.msg
      and len(pointers(api)) == 4, res.msg)
api = fresh()
seed(api, t1=OLD_OATS, t3="Hand-written pockets.\n")
out = mw.sync(today=TODAY, api=api, dry=True, planned=PLANNED, recipes=RATED)
check("dry run: says what it would rate (the empty body is fill's, not the mirror's) and writes nothing",
      "would mirror 2 Mela ratings" in out and "Oats " + STAR * 4 in out and "Bulgogi" not in out.splitlines()[2]
      and all(c[0] in ("get", "pd") for c in api.calls)
      and api.lists[LIST]["t1"]["content"] == OLD_OATS, out.splitlines()[:4])


# ── portions: a week's 🛒 lists re-cut (Vex 2026-09-22, D25) ─────────────────
print("-- portions")
NOTE7 = "Scaled ×1.75: 4 → 7 portions\n_(yield: '4' in yield)_"
NOTE5 = "Scaled ×1.25: 4 → 5 portions\n_(yield: '4' in yield)_"
lines5, desc5 = mw.grocery_body(BY[U1], 5)
check("grocery_body at 5 portions: the lines ×1.25, the note says 4 → 5",
      lines5 == ["625 g chicken", "1 1/4 tbsp oil", "2 1/2 tsp soy"] and desc5 == NOTE5, (lines5, desc5))
check("grocery_body's default is still the sync's 7",
      mw.grocery_body(BY[U1]) == (["875 g chicken", "1 3/4 tbsp oil", "3 1/2 tsp soy"], NOTE7), mw.grocery_body(BY[U1]))
check("_portions_of: content, then desc, else None",
      mw._portions_of({"content": NOTE7}) == 7 and mw._portions_of({"content": "", "desc": "Already 5 portions, unscaled"}) == 5
      and mw._portions_of({"content": ""}) is None and mw._portions_of({}) is None and mw._portions_of(None) is None
      and mw._portions_of({"content": "⚠️ Yield unknown, quantities unscaled"}) is None)

# week_lists over an injected pool
GT = T("groc_sat", "🛒 Groceries", pid=RLIST, startDate="2026-09-26T06:00:00.000+0000", timeZone="Europe/Berlin")
GT_OLD = T("groc_old", "🛒 Groceries", pid=RLIST, startDate="2026-09-12T06:00:00.000+0000", timeZone="Europe/Berlin")
POOL = [GT, GT_OLD,
        T("gl_b", meal.grocery_title("Beef Bulgogi", U1), pid=RLIST, parent="groc_sat", kind="CHECKLIST", sortOrder=20),
        T("gl_a", meal.grocery_title("Oats", U2), pid=RLIST, parent="groc_sat", kind="CHECKLIST", sortOrder=10),
        T("gl_done", meal.grocery_title("Pockets", U3), pid=RLIST, parent="groc_sat", kind="CHECKLIST", status=2),
        T("gl_last", meal.grocery_title("Last week", U9), pid=RLIST, parent="groc_old", kind="CHECKLIST"),
        T("gl_loose", meal.grocery_title("Loose", U9), kind="CHECKLIST"),
        T("gl_alpha", meal.grocery_title("Alpha", U8), kind="CHECKLIST"),
        T("step", "Wipe the counter", pid=RLIST, parent="groc_sat")]
wl = mw.week_lists(today=TODAY, tasks=POOL)
check("week_lists: the open lists under the upcoming 🛒 task by sortOrder; the ticked one, last week's, the loose ones and the step left out",
      [t["id"] for t in wl] == ["gl_a", "gl_b"], [t["id"] for t in wl])
wl = mw.week_lists(today=TODAY, tasks=[t for t in POOL if t["id"] != "groc_sat"])
check("week_lists: no upcoming 🛒 task (last week's does not count) = the loose library lists, by title",
      [t["id"] for t in wl] == ["gl_alpha", "gl_loose"], [t["id"] for t in wl])
check("week_lists never raises: garbage in, an empty week out",
      mw.week_lists(today=TODAY, tasks=[None, 3, {"title": None}, {"id": None, "title": meal.grocery_title("x", U1)}]) == [])
wl = mw.week_lists(today=TODAY, tasks=[t for t in POOL if t["id"] not in ("gl_a", "gl_b", "gl_done")])
check("week_lists: a 🛒 task ahead but nothing under it = every open list anywhere (what the hub row counts; "
      "gl_loose shares U9 with gl_last, first seen wins)",
      sorted(t["id"] for t in wl) == ["gl_alpha", "gl_last"], [t["id"] for t in wl])
fresh()
wl = mw.week_lists(today=TODAY)
check("week_lists off the caches: no 🛒 task in the routines list = the loose open lists of the library, the ticked one out",
      [t["id"] for t in wl] == ["g_old", "g_keep"], [t["id"] for t in wl])

# set_portions
api = fresh()
GL = T("gl", meal.grocery_title("Beef Bulgogi", U1), kind="CHECKLIST", tags=["🛒groceries"], content=NOTE7,
       items=[{"id": "i1", "status": 2, "title": "875 g chicken", "sortOrder": 0},
              {"id": "i2", "status": 0, "title": "1 3/4 tbsp oil", "sortOrder": 1},
              {"id": "i3", "status": 2, "title": "3 1/2 tsp soy", "sortOrder": 2}])
api.lists[LIST]["gl"] = dict(GL)
mw._cache_add([GL])
res = mw.set_portions(api, LIST, "gl", 5)
live = api.lists[LIST]["gl"]
check("set_portions: a live read then ONE update carrying items + content",
      api.calls == [("get", LIST, "gl"), ("update", LIST, "gl", ("content", "items"))], api.calls)
check("set_portions: the items re-cut ×1.25 (4 → 5), the note says so",
      [it["title"] for it in live["items"]] == ["625 g chicken", "1 1/4 tbsp oil", "2 1/2 tsp soy"]
      and live["content"] == NOTE5, (live["items"], live["content"]))
check("set_portions: the ticks carried by ingredient name, sortOrder fresh, no ids",
      [it["status"] for it in live["items"]] == [2, 0, 2] and [it["sortOrder"] for it in live["items"]] == [0, 1, 2]
      and not any("id" in it for it in live["items"]), live["items"])
check("set_portions: the toast counts the ticks kept, no reopen of its own",
      isinstance(res, mw.Outcome) and res.msg == "🛒 Beef Bulgogi · 5 portions · 2 ticks kept" and res.reopen is None
      and res.ids == ["gl"], res)
cached = next(t for t in cache_store.get("all_tasks") if t["id"] == "gl")
pd_gl = next(t for t in cache_store.get(f"project_data_{LIST}")["tasks"] if t["id"] == "gl")
check("set_portions: the cache mirrors items + content in both pools",
      [it["title"] for it in cached["items"]] == ["625 g chicken", "1 1/4 tbsp oil", "2 1/2 tsp soy"] and cached["content"] == NOTE5
      and pd_gl["content"] == NOTE5 and mw._portions_of(cached) == 5, (cached.get("items"), cached.get("content")))
n = len(api.calls)
res = mw.set_portions(api, LIST, "gl", "5")
check("set_portions: the same count (as a string, even) = the read, no write, 'unchanged'",
      api.calls[n:] == [("get", LIST, "gl")] and res.msg == "🛒 Beef Bulgogi · 5 portions · unchanged", (api.calls[n:], res.msg))
# an unknown yield: the scaler cannot cut it, so nothing is written and the toast tells the truth
BY[U8] = R(U8, "Salad", yield_text="", ings="2 tomatoes\n1 cucumber\n3 tbsp oil")
GS = T("gs", meal.grocery_title("Salad", U8), kind="CHECKLIST", tags=["🛒groceries"],
       content="⚠️ Yield unknown, quantities unscaled",
       items=[{"id": "s1", "status": 2, "title": "2 tomatoes", "sortOrder": 0}])
api.lists[LIST]["gs"] = dict(GS)
n = len(api.calls)
try:
    mw.set_portions(api, LIST, "gs", 5)
    bad = "accepted"
except mw.Refusal as e:
    bad = str(e)
check("set_portions: a recipe whose yield is unknown refuses after the read, nothing written",
      bad == "🛒 Salad · yield unknown · cannot re-cut" and api.calls[n:] == [("get", LIST, "gs")]
      and api.lists[LIST]["gs"]["items"][0]["status"] == 2, (bad, api.calls[n:]))
# the noted count but NO items (a failed items update): written, not "unchanged"
GE = T("ge", meal.grocery_title("Oats", U2), kind="CHECKLIST", tags=["🛒groceries"], content=NOTE7, items=[])
api.lists[LIST]["ge"] = dict(GE)
n = len(api.calls)
res = mw.set_portions(api, LIST, "ge", 7)
check("set_portions: the noted count with an empty checklist is repaired, not 'unchanged'",
      [c[0] for c in api.calls[n:]] == ["get", "update"] and res.msg == "🛒 Oats · 7 portions"
      and len(api.lists[LIST]["ge"]["items"]) > 0, (api.calls[n:], res.msg))
n = len(api.calls)
bad = []
for v in (0, 41, "x", None, "", 5.5, "7.0", True):
    try:
        mw.set_portions(api, LIST, "gl", v)
        bad.append((v, "accepted"))
    except mw.Refusal as e:
        if str(e) != "🔢 Portions: 1 to 40":
            bad.append((v, str(e)))
check("set_portions: 0 / 41 / a word / None / blank / a fraction / a bool refuse with the one line, nothing read",
      bad == [] and api.calls[n:] == [], (bad, api.calls[n:]))
n = len(api.calls)
try:
    mw.set_portions(api, LIST, "t1", 5)
    check("set_portions: a library task refuses", False)
except mw.Refusal as e:
    check("set_portions: a library task refuses after the read, nothing written",
          str(e) == "🛒 Not a grocery list" and api.calls[n:] == [("get", LIST, "t1")], (str(e), api.calls[n:]))
n = len(api.calls)
try:
    mw.set_portions(api, LIST, "g_old", 5)                      # "Gone", U9: not in Mela
    check("set_portions: a recipe Mela does not know refuses", False)
except mw.Refusal as e:
    check("set_portions: a recipe Mela does not know refuses by name, nothing written",
          str(e) == "🛒 Gone · recipe not in Mela on this Mac" and api.calls[n:] == [("get", LIST, "g_old")], (str(e), api.calls[n:]))
n = len(api.calls)
res = mw.set_portions(api, LIST, "gl", 6, dry=True)
check("set_portions dry run: no api call, the line names the list off the cache",
      api.calls[n:] == [] and res.msg == "🥘 Dry run · would cut Beef Bulgogi to 6 portions", res.msg)
api.lists[LIST]["gl"]["content"] = ""                          # one of the first lists: saved without a note
n = len(api.calls)
res = mw.set_portions(api, LIST, "gl", 7)
check("set_portions: a list without a note is written even at 7, and gets its note (the note is the memory)",
      api.calls[n:] == [("get", LIST, "gl"), ("update", LIST, "gl", ("content", "items"))]
      and api.lists[LIST]["gl"]["content"] == NOTE7 and [it["title"] for it in api.lists[LIST]["gl"]["items"]] == ["875 g chicken", "1 3/4 tbsp oil", "3 1/2 tsp soy"]
      and res.msg == "🛒 Beef Bulgogi · 7 portions · 2 ticks kept", (api.calls[n:], api.lists[LIST]["gl"]["content"], res.msg))

# the sync re-making a loose list under the 🛒 task keeps the count it was re-cut to
api = fresh()
api.lists[LIST]["g_keep"]["content"] = NOTE5                   # Oats, re-cut to 5 last press, loose in the library
api.lists[RLIST]["prep_tue"] = T("prep_tue", "🥘 Meal Prep", pid=RLIST, startDate="2026-09-22T07:00:00.000+0000", timeZone="Europe/Berlin")
api.lists[RLIST]["groc_tue"] = T("groc_tue", "🛒 Groceries", pid=RLIST, startDate="2026-09-22T06:00:00.000+0000", timeZone="Europe/Berlin")
mw._cache_add([api.lists[RLIST]["groc_tue"]])                # the hourly sync would have it
mw.sync(today=TODAY, api=api, planned=TUE, recipes=RECIPES)
glists = {meal.link_uuid(t["title"]): t for t in api.lists[RLIST].values() if meal.is_grocery(t["title"]) and t["status"] == 0}
check("sync: the loose Oats list re-made under the 🛒 task at ITS 5 portions, the new Bulgogi one at 7",
      "g_keep" not in api.lists[LIST] and glists[U2]["parentId"] == "groc_tue" and glists[U2]["content"] == NOTE5
      and [it["title"] for it in glists[U2]["items"]] == ["625 g chicken", "1 1/4 tbsp oil", "2 1/2 tsp soy"]
      and glists[U1]["content"] == NOTE7, {u: (t.get("parentId"), t.get("content")) for u, t in glists.items()})
wl = mw.week_lists(today=TODAY)
check("week_lists off the caches after the sync: the two lists under the upcoming 🛒 task",
      sorted(t["parentId"] for t in wl) == ["groc_tue", "groc_tue"] and {meal.link_uuid(t["title"]) for t in wl} == {U1, U2}, wl)


# ── prices: the book on the 🛒 lists (Vex 2026-09-22, D26) ───────────────────
print("-- prices")
BOOK = {"version": 1, "updated": "2026-09-22", "entries": {
    "chicken": {"key": "chicken", "search": "Hähnchen", "product": "Hähnchenbrust", "product_id": 1,
                "pack": "500 g", "pack_amount": 500, "pack_unit": "g", "price": 4.99, "per": 0.00998,
                "per_unit": "g", "source": "knuspr", "date": "2026-09-22", "pinned": False,
                "url": "https://www.knuspr.de/1-haehnchenbrust"},
    "oil": {"key": "oil", "search": "Öl", "product": "Rapsöl", "product_id": 2, "pack": "1 l",
            "pack_amount": 1000, "pack_unit": "ml", "price": 2.49, "per": 0.00249, "per_unit": "ml",
            "source": "knuspr", "date": "2026-09-22", "pinned": False, "url": ""}}}
COST7 = "≈ 8.80 € · 1.26 €/portion · 1 unpriced"        # 875 g chicken 8.73 + 26.25 ml oil 0.07, soy unpriced
COST5 = "≈ 6.29 € · 1.26 €/portion · 1 unpriced"
LINES7 = ["875 g chicken · ≈ 8.73 €", "1 3/4 tbsp oil · ≈ 0.07 €", "3 1/2 tsp soy"]
LINES5 = ["625 g chicken · ≈ 6.24 €", "1 1/4 tbsp oil · ≈ 0.05 €", "2 1/2 tsp soy"]
BARE7 = ["875 g chicken", "1 3/4 tbsp oil", "3 1/2 tsp soy"]

lines, desc = mw.grocery_body(BY[U1], book=BOOK)
check("grocery_body with a book: the suffix on every priced line, the unpriced one bare",
      lines == LINES7, lines)
check("grocery_body with a book: the cost line FIRST, the yield note under it",
      desc == COST7 + "\n" + NOTE7, desc)
check("grocery_body with a book: meal.portions_of still reads the note, the cost line reads its own",
      meal.portions_of(desc) == 7 and mw._cost_of(desc) == (8.80, 1), (meal.portions_of(desc), mw._cost_of(desc)))
check("grocery_body at 5 with a book", mw.grocery_body(BY[U1], 5, BOOK) == (LINES5, COST5 + "\n" + NOTE5),
      mw.grocery_body(BY[U1], 5, BOOK))
check("grocery_body without a book, with None, with an empty book, with a bookless dict: byte-identical to before",
      all(mw.grocery_body(BY[U1], 7, b) == (BARE7, NOTE7) for b in (None, {}, mp.empty_book(), {"entries": {}}))
      and mw.grocery_body(BY[U1]) == (BARE7, NOTE7))
check("grocery_body: a book that prices nothing on this recipe still writes an honest cost line",
      mw.grocery_body(BY[U1], 7, {"entries": {"unicorn": BOOK["entries"]["oil"]}})
      == (BARE7, "≈ 0.00 € · nothing priced yet\n" + NOTE7), mw.grocery_body(BY[U1], 7, {"entries": {"unicorn": {}}}))
check("_cost_of: the module's reader or the regex fallback, None without a line",
      mw._cost_of(COST7 + "\nx") == (8.80, 1) and mw._cost_of("≈ 4.47 €") == (4.47, 0)
      and mw._cost_of(NOTE7) is None and mw._cost_of("") is None and mw._cost_of(None) is None
      and mw._cost_of("≈ 0.00 € · nothing priced yet") is None,
      (mw._cost_of(COST7 + "\nx"), mw._cost_of("≈ 4.47 €"), mw._cost_of(NOTE7)))

# _write_groceries prices a new list from the book it is handed
api = fresh()
picks = {U1: {"name": "Beef Bulgogi", "uuid": U1, "slot": "l", "tid": "t2"}}
made, kept, gone = mw._write_groceries(api, LIST, picks, None, date(2026, 9, 26), BY, {}, None, BOOK)
check("_write_groceries with a book: the new list's items carry the suffixes, its content the cost line first",
      len(made) == 1 and [it["title"] for it in made[0]["items"]] == LINES7 and made[0]["content"] == COST7 + "\n" + NOTE7,
      made and (made[0].get("items"), made[0].get("content")))
api = fresh()
made, kept, gone = mw._write_groceries(api, LIST, picks, None, date(2026, 9, 26), BY, {})
check("_write_groceries without a book: bare, as before",
      [it["title"] for it in made[0]["items"]] == BARE7 and made[0]["content"] == NOTE7)

# the sync loads the book ONCE off the temp path and prices every new list
mp.save_book(BOOK)
check("the test book landed in the temp dir, never the real one", os.path.exists(mp.BOOK_PATH) and mp.BOOK_PATH.startswith(TMP))
api = fresh()
mw.sync(today=TODAY, api=api, planned=PLANNED, recipes=RECIPES)
grocs = groceries(api)
check("sync with a book on disk: the created lists are priced, the cost line above the note",
      [it["title"] for it in grocs[U1]["items"]] == LINES7 and grocs[U1]["content"] == COST7 + "\n" + NOTE7
      and grocs[U3]["content"].startswith("≈ ") and meal.portions_of(grocs[U3]["content"]) == 7,
      (grocs[U1].get("items"), grocs[U1].get("content")))
check("sync with a book: the not-in-Mela warning list is untouched by prices",
      grocs[U8]["content"].startswith("⚠️ recipe not in Mela") and not grocs[U8].get("items"))
check("sync never fetches: a book on disk is a file read, the calls are TickTick's only",
      all(c[0] in ("get", "pd", "create", "update", "delete") for c in api.calls))

# set_portions re-prices the re-cut, the ticks carried across the suffix
api = fresh()
GLP = T("glp", meal.grocery_title("Beef Bulgogi", U1), kind="CHECKLIST", tags=["🛒groceries"],
        content=COST7 + "\n" + NOTE7,
        items=[{"id": "i1", "status": 2, "title": LINES7[0], "sortOrder": 0},
               {"id": "i2", "status": 0, "title": LINES7[1], "sortOrder": 1},
               {"id": "i3", "status": 2, "title": LINES7[2], "sortOrder": 2}])
api.lists[LIST]["glp"] = dict(GLP)
mw._cache_add([GLP])
res = mw.set_portions(api, LIST, "glp", 5)
live = api.lists[LIST]["glp"]
check("set_portions with the book: the re-cut is re-priced at 5, the cost line first, the note under it",
      [it["title"] for it in live["items"]] == LINES5 and live["content"] == COST5 + "\n" + NOTE5
      and mw._portions_of(live) == 5, (live["items"], live["content"]))
check("set_portions with the book: the ticks carried by the ingredient, the suffix ignored, the toast unchanged",
      [it["status"] for it in live["items"]] == [2, 0, 2] and res.msg == "🛒 Beef Bulgogi · 5 portions · 2 ticks kept", res)
api.lists[LIST]["gl"] = dict(GL)                                   # bare items, NOTE7, ticks on chicken + soy
mw.set_portions(api, LIST, "gl", 6)
check("set_portions: a bare (pre-price) list re-cut gets priced too, its ticks kept",
      [it["title"] for it in api.lists[LIST]["gl"]["items"]] == ["750 g chicken · ≈ 7.49 €", "1 1/2 tbsp oil · ≈ 0.06 €", "3 tsp soy"]
      and [it["status"] for it in api.lists[LIST]["gl"]["items"]] == [2, 0, 2], api.lists[LIST]["gl"]["items"])

# reprice_lists: the same lists under a NEW book, ids and ticks kept
api = fresh()
STALE = T("gls", meal.grocery_title("Beef Bulgogi", U1), kind="CHECKLIST", tags=["🛒groceries"],
          content="≈ 99.00 € · 14.14 €/portion\n" + NOTE7,
          items=[{"id": "i1", "status": 2, "title": "875 g chicken · ≈ 90.00 €", "sortOrder": 0},
                 {"id": "i2", "status": 0, "title": "1 3/4 tbsp oil · ≈ 9.00 €", "sortOrder": 1},
                 {"id": "i3", "status": 2, "title": "3 1/2 tsp soy", "sortOrder": 2}])
BARE = T("glb", meal.grocery_title("Oats", U2), kind="CHECKLIST", tags=["🛒groceries"], content=NOTE7,
         items=[{"id": "j1", "status": 0, "title": "875 g chicken", "sortOrder": 0},
                {"id": "j2", "status": 2, "title": "1 3/4 tbsp oil", "sortOrder": 1},
                {"id": "j3", "status": 0, "title": "3 1/2 tsp soy", "sortOrder": 2}])
EMPTY = T("gle", meal.grocery_title("Nope", U8), kind="CHECKLIST", tags=["🛒groceries"],
          content="⚠️ recipe not in Mela on this Mac · no list (open Mela to sync)", items=[])
for t in (STALE, BARE, EMPTY):
    api.lists[LIST][t["id"]] = dict(t)
mw._cache_add([STALE, BARE, EMPTY])
r = mw.reprice_lists(api, lists=[STALE, BARE, EMPTY], book=BOOK)
check("reprice_lists: two updated, the itemless one unchanged",
      r == {"updated": 2, "unchanged": 1, "failed": 0}, r)
s = api.lists[LIST]["gls"]
check("reprice_lists: a LIVE read then ONE update per changed list, items + content",
      api.calls == [("get", LIST, "gls"), ("update", LIST, "gls", ("content", "items")),
                    ("get", LIST, "glb"), ("update", LIST, "glb", ("content", "items")),
                    ("get", LIST, "gle")], api.calls)
check("reprice_lists: the stale suffixes replaced, ids and statuses and sortOrder KEPT",
      s["items"] == [{"id": "i1", "status": 2, "title": LINES7[0], "sortOrder": 0},
                     {"id": "i2", "status": 0, "title": LINES7[1], "sortOrder": 1},
                     {"id": "i3", "status": 2, "title": LINES7[2], "sortOrder": 2}], s["items"])
check("reprice_lists: the old cost line replaced, the yield note kept",
      s["content"] == COST7 + "\n" + NOTE7, s["content"])
b = api.lists[LIST]["glb"]
check("reprice_lists: a bare list gains suffixes and a cost line, its tick kept",
      [it["title"] for it in b["items"]] == LINES7 and [it["status"] for it in b["items"]] == [0, 2, 0]
      and [it["id"] for it in b["items"]] == ["j1", "j2", "j3"] and b["content"] == COST7 + "\n" + NOTE7, b)
check("reprice_lists: the cache mirrors it",
      next(t for t in cache_store.get("all_tasks") if t["id"] == "gls")["content"] == COST7 + "\n" + NOTE7)
n = len(api.calls)
r = mw.reprice_lists(api, lists=[STALE, BARE], book=BOOK)
check("reprice_lists again under the same book: reads only, nothing written, all unchanged",
      r == {"updated": 0, "unchanged": 2, "failed": 0} and all(c[0] == "get" for c in api.calls[n:]), (r, api.calls[n:]))
n = len(api.calls)
r = mw.reprice_lists(api, lists=[STALE, BARE], book={"entries": {}})
check("reprice_lists under an empty book: no call at all, all unchanged (grocery_body's rule)",
      r == {"updated": 0, "unchanged": 2, "failed": 0} and api.calls[n:] == [], (r, api.calls[n:]))
r = mw.reprice_lists(api, lists=[], book=BOOK)
check("reprice_lists: no lists, nothing", r == {"updated": 0, "unchanged": 0, "failed": 0})
api2 = fresh()
for t in (STALE, BARE):
    api2.lists[LIST][t["id"]] = dict(t)
api2.fail_after = 1                         # the first update trips the limit
r = mw.reprice_lists(api2, lists=[STALE, BARE], book=BOOK)
check("reprice_lists: a rate limit stops the pass, this list and the rest counted as failed",
      r == {"updated": 0, "unchanged": 0, "failed": 2} and len(api2.calls) == 2, (r, api2.calls))
api2 = fresh()
api2.lists[LIST]["gls"] = dict(STALE)
r = mw.reprice_lists(api2, lists=[STALE, BARE], book=BOOK, dry=True)
check("reprice_lists dry: the cached rows costed, no call", r == {"updated": 2, "unchanged": 0, "failed": 0} and api2.calls == [], (r, api2.calls))
same_book = mw._repriced(dict(STALE, items=[dict(it, title=ln) for it, ln in zip(STALE["items"], LINES7)],
                              content=COST7 + "\n" + NOTE7), BOOK)
check("_repriced: a list already right under the book reads unchanged (the cost line at its own count)",
      same_book[2] is False and same_book[1] == COST7 + "\n" + NOTE7, same_book)
at5 = mw._repriced(dict(STALE, items=[dict(it, title=ln) for it, ln in zip(STALE["items"], LINES5)],
                        content=COST7 + "\n" + NOTE5), BOOK)
check("_repriced: the cost line is cut at the list's OWN count (the note's 5, not the sync's 7)",
      at5[1] == COST5 + "\n" + NOTE5 and [it["title"] for it in at5[0]] == LINES5, at5)

# refresh_prices: the keys off the cached week lists, a FAKE fetch, the book saved, the lists re-priced
def prod(pid, name, pack, price, ppu):
    return {"productId": pid, "productName": name, "baseLink": f"{pid}-{name.lower()}", "textualAmount": pack,
            "price": {"full": price}, "pricePerUnit": {"full": ppu}, "inStock": True}


SHOP = {"Hähnchen": [prod(1, "Hähnchenbrust", "500 g", 4.99, 9.98)], "Öl": [prod(2, "Rapsöl", "1 l", 2.49, 2.49)]}
FETCHED = []


def fake_fetch(term):
    FETCHED.append(term)
    return {"status": 200, "data": {"productList": SHOP.get(term, [])}}


check("refresh_prices paces knuspr at half a second by default", mw.PRICE_PACE == 0.5
      and mw.refresh_prices.__code__.co_varnames[:5] == ("api", "book", "today", "fetch", "dry"))
mw.PRICE_PACE = 0.0                          # no sleeping in the suite
mp.save_book(mp.empty_book())                # a fresh book
api = fresh()
for t in (dict(BARE, id="g_keep", title=api.lists[LIST]["g_keep"]["title"]),
          dict(STALE, id="g_old", title=api.lists[LIST]["g_old"]["title"])):
    api.lists[LIST][t["id"]] = dict(t)
    mw._cache_patch(t["id"], items=t["items"], content=t["content"])
wl = mw.week_lists(today=TODAY)
check("the week's cached lists carry their items (what the refresh keys on)",
      [t["id"] for t in wl] == ["g_old", "g_keep"] and all(t.get("items") for t in wl), [(t["id"], bool(t.get("items"))) for t in wl])
check("_week_keys: distinct keys off the stripped titles, in list order",
      mw._week_keys(wl) == ["chicken", "oil", "soy"], mw._week_keys(wl))
res = mw.refresh_prices(api, dry=True, fetch=lambda t: 1 / 0)
check("refresh_prices dry: the keys named, nothing fetched, nothing called, nothing saved",
      res.msg == "🥘 Dry run · would price 3 keys from knuspr.de: chicken, oil, soy" and api.calls == []
      and mp.load_book()["entries"] == {}, (res, api.calls))
check("_head: three, then an ellipsis", (mw._head(["a", "b", "c", "d"]), mw._head(["a"]), mw._head([])), ("a, b, c…", "a", ""))
res = mw.refresh_prices(api, today=date(2026, 9, 22), fetch=fake_fetch)
check("refresh_prices: the fake shop was asked by the default German terms, soy by itself",
      FETCHED == ["Hähnchen", "Öl", "soy"], FETCHED)
saved = mp.load_book()
check("refresh_prices: the book saved to the temp path with the two entries, stamped",
      set(saved["entries"]) == {"chicken", "oil"} and saved["entries"]["chicken"]["per"] == 0.00998
      and saved["entries"]["oil"]["per_unit"] == "ml" and saved["updated"] == "2026-09-22", saved)
check("refresh_prices: the toast", res.msg == "🏷 Prices · 2 priced · 0 kept · 1 unpriced (soy) · 2 lists updated"
      and res.reopen is None and res.ids == ["g_old", "g_keep"], res)
check("refresh_prices: both lists re-priced live (ids kept), the cache with them",
      [it["title"] for it in api.lists[LIST]["g_keep"]["items"]] == LINES7 and api.lists[LIST]["g_keep"]["content"] == COST7 + "\n" + NOTE7
      and [it["id"] for it in api.lists[LIST]["g_old"]["items"]] == ["i1", "i2", "i3"]
      and next(t for t in cache_store.get("all_tasks") if t["id"] == "g_old")["content"] == COST7 + "\n" + NOTE7,
      (api.lists[LIST]["g_keep"].get("items"), api.lists[LIST]["g_keep"].get("content")))
check("refresh_prices: TickTick calls are a get + an update per list, nothing else",
      [c[0] for c in api.calls] == ["get", "update", "get", "update"], api.calls)
del FETCHED[:]
n = len(api.calls)
res = mw.refresh_prices(api, today=date(2026, 9, 23), fetch=fake_fetch)
check("refresh_prices again: re-fetched, the lists unchanged under the same prices, no write",
      FETCHED == ["Hähnchen", "Öl", "soy"] and res.msg.endswith(" · 0 lists updated")
      and all(c[0] == "get" for c in api.calls[n:]), (res.msg, api.calls[n:]))
_wl = mw.week_lists
mw.week_lists = lambda *a, **k: []
try:
    mw.refresh_prices(api, fetch=fake_fetch)
    check("refresh_prices: no week lists refuses", False)
except mw.Refusal as e:
    check("refresh_prices: no week lists refuses, pointing at the sync",
          str(e) == "🏷 No grocery lists this week · 🔄 Sync with Mela first", str(e))
mw.week_lists = _wl

# week_cost off the cached cost lines (the hub's number: no live read, no network)
check("week_cost: the two re-priced lists summed off the cache, the holes counted",
      mw.week_cost() == (17.60, 2, 2), mw.week_cost())
check("week_cost over given lists: only the ones with a cost line count, None when none has one",
      mw.week_cost([dict(STALE, content=COST7), dict(BARE, content=NOTE7), {"content": "≈ 1.20 €"}]) == (10.0, 1, 2)
      and mw.week_cost([dict(BARE, content=NOTE7)]) == (None, 0, 0) and mw.week_cost([]) == (None, 0, 0),
      mw.week_cost([dict(STALE, content=COST7), dict(BARE, content=NOTE7), {"content": "≈ 1.20 €"}]))

# set_price / set_search on the temp book
if hasattr(mp, "parse_price_answer") and hasattr(mp, "manual_entry"):
    res = mw.set_price("soy", "1.49 / 100 ml", today=date(2026, 9, 22))
    e = mp.load_book()["entries"].get("soy") or {}
    check("set_price: a manual entry in the book, per ml, saved",
          e.get("source") == "manual" and e.get("per_unit") == "ml" and abs(float(e.get("per") or 0) - 0.0149) < 1e-9
          and e.get("date") == "2026-09-22", e)
    check("set_price: the toast", res.msg == "🏷 soy · 1.49 € / 100 ml · manual", res.msg)
    e_soy_after = dict(e)
    e_before = dict(mp.load_book()["entries"]["chicken"])
    res = mw.set_price("chicken", "9.99 / 1 kg", today=date(2026, 9, 22))
    e = mp.load_book()["entries"]["chicken"]
    check("set_price over a knuspr entry: manual wins, the search term carried over",
          e.get("source") == "manual" and e.get("search") == e_before.get("search") and abs(float(e["per"]) - 0.00999) < 1e-9, e)
    bad = []
    for v in ("", "abc", "1.49 / 100 elephants", None):
        try:
            mw.set_price("soy", v)
            bad.append((v, "accepted"))
        except mw.Refusal as e:
            if not str(e).startswith("🏷 "):
                bad.append((v, str(e)))
    check("set_price: a text that is not a price refuses with a 🏷 line", bad == [], bad)
    check("set_price: a refused text leaves the entry as it was", mp.load_book()["entries"]["soy"] == e_soy_after)
    try:
        mw.set_price("", "1 / 1 pc")
        check("set_price: a blank key refuses", False)
    except mw.Refusal as e:
        check("set_price: a blank key refuses", str(e) == "🏷 No ingredient", str(e))
    del FETCHED[:]
    res = mw.set_search("chicken", "Hähnchen", today=date(2026, 9, 22), fetch=fake_fetch)
    e = mp.load_book()["entries"]["chicken"]
    check("set_search on a manual entry: the term is stored, the manual price kept, nothing fetched",
          FETCHED == [] and e.get("source") == "manual" and e.get("search") == "Hähnchen"
          and res.msg == "🏷 chicken · Hähnchen · manual price kept", (e, res.msg))
    res = mw.set_search("chicken", "Einhorn", today=date(2026, 9, 22), fetch=fake_fetch)
    e = mp.load_book()["entries"]["chicken"]
    check("set_search: a second term on the manual entry replaces the stored one, the price still kept",
          e.get("source") == "manual" and e.get("search") == "Einhorn"
          and res.msg == "🏷 chicken · Einhorn · manual price kept", (e, res.msg))
    res = mw.set_search("egg", "Eier", today=date(2026, 9, 22), fetch=fake_fetch)
    e = mp.load_book()["entries"].get("egg")
    bk = mp.load_book()
    check("set_search on a key the book lacks: no bare entry minted, the term kept in book['terms'], nothing found",
          e is None and (bk.get("terms") or {}).get("egg") == "Eier" and mp.search_term("egg", bk) == "Eier"
          and res.msg.endswith("nothing found on knuspr.de"), (e, bk.get("terms"), res.msg))
    for key, term in (("", "x"), ("egg", ""), ("egg", "  ")):
        try:
            mw.set_search(key, term, fetch=fake_fetch)
            check(f"set_search refuses {key!r}/{term!r}", False)
        except mw.Refusal as e:
            check(f"set_search refuses {key!r}/{term!r}", str(e).startswith("🏷 "), str(e))
else:
    check("meal_price.parse_price_answer + manual_entry present (the module fixer's names, set_price rides them)",
          False, "absent: set_price / set_search checks skipped")

check("the real ~/.ticktick_alfred book was never written by this run",
      os.path.exists(REAL_BOOK) == HAD_REAL_BOOK and not os.path.exists(REAL_BOOK + ".tmp"), REAL_BOOK)

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print(f"\nmeal_write: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
