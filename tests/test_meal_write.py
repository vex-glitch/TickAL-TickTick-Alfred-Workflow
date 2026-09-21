#!/usr/bin/env python3
"""src/meal_write.py against a FAKE TickTick client, an injected Mela
library and an injected calendar plan (mela_cal.Planned rows built here -
NO real store, NO network): sync's order of writes (deletes before
creates, pointer-only deletes), one pointer per planned meal in b/l/s/x
order with 🍽️ for a recipe outside the three slots, the grocery rules, an
empty week clearing pointers + open groceries, the dry run writing nothing,
refusals (ids blank, calendar unreadable, Mela missing, rate limit),
plan_view's shape, import dedupe + cap + rate limit, the backfill's
live-read rule. Caches live in a temp dir. Run: python3 tests/test_meal_write.py
"""
import os
import sys
import tempfile
from datetime import date

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
import meal_write as mw                        # noqa: E402
import mela                                    # noqa: E402
import mela_cal                                # noqa: E402

mw.IMPORT_LEDGER = os.path.join(TMP, "meal_import.json")
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
                    repeat_flag=None, reminders=None):
        self._bump("create", project_id, title)
        self.n += 1
        t = {"id": f"new{self.n}", "projectId": project_id, "title": title, "status": 0,
             "dueDate": due_date, "content": content or "", "tags": tags or [],
             "parentId": None, "kind": kind or "TEXT", "sortOrder": -self.n}
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
      "p_old" in out and "g_old" in out and "keep 1" in out and "create 3 due 2026-09-26" in out
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
_cal = mw._calendar
mw._calendar = lambda since=None, until=None: ([], "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)")
try:
    api = fresh()
    mw.sync(today=TODAY, api=api, recipes=RECIPES)
    check("unreadable calendar refused", False)
except mw.Refusal as e:
    check("unreadable calendar refused with the FDA line", "Full Disk Access" in str(e), str(e))
    check("unreadable calendar: nothing written, nothing read", api.calls == [], api.calls)
mw._calendar = _cal
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
      "🔄 Mela · +1 recipe · 3 filled · Week of 28 Sep: 🍳 Oats · 🍛 Beef Bulgogi · 🌮 Pockets · 🍽️ Mystery Bake"
      " · 4 grocery lists", res)
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
      and all(t["parentId"] == RID and t["dueDate"] == "2026-09-27" and t["kind"] == "TEXT" for t in ptrs), ptrs)
check("pointer titles: glyph + Mela link, 🍽️ named after the event",
      ptrs[0]["title"] == f"🍳 [Oats](mela://recipe/{U2})"
      and ptrs[3]["title"] == f"🍽️ [Mystery Bake](mela://recipe/{U8})", [t["title"] for t in ptrs])
check("next week's meal is NOT mirrored", not any("2026-10-04" in (t.get("dueDate") or "") for t in ptrs))
grocs = groceries(api)
check("groceries: kept one re-dated, three created, stale gone",
      set(grocs) == {U1, U2, U3, U8} and grocs[U2]["id"] == "g_keep" and grocs[U2]["dueDate"] == "2026-09-26"
      and grocs[U1]["kind"] == "CHECKLIST" and grocs[U1]["dueDate"] == "2026-09-26", grocs)
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
      res2.msg.startswith("🔄 Mela · nothing new · Week of 28 Sep") and "4 grocery lists" in res2.msg
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
      "Week of 28 Sep: nothing planned in Mela · 0 grocery lists" in res.msg, res.msg)
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
mw._calendar = lambda since=None, until=None: ([], "Calendar store unreadable · give Alfred Full Disk Access (System Settings › Privacy › Full Disk Access)")
pv = mw.plan_view(today=TODAY, recipes=RECIPES)
check("plan_view never raises: the FDA line as error, 13 empty weeks",
      "Full Disk Access" in pv["error"] and len(pv["weeks"]) == 13 and all(w.meals == [] for w in pv["weeks"]))
mw._calendar = _cal
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

print(f"\nmeal_write: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
