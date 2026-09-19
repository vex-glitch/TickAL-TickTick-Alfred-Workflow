#!/usr/bin/env python3
"""src/meal_write.py against a FAKE TickTick client and a fake Mela: the
commit's order of writes (deletes before creates, pointer-only deletes,
the grocery rules), the dry run writing nothing, the ledger written only
after the acks, import dedupe + cap + rate limit, the backfill's live-read
rule. Caches live in a temp dir. Run: python3 tests/test_meal_write.py
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
RLIST = "5eed00000000000000000b01"
import cache as cache_store                    # noqa: E402
cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR)
import meal                                    # noqa: E402
import meal_write as mw                        # noqa: E402
import mela                                    # noqa: E402

mw.LEDGER = os.path.join(TMP, "meal_ledger.json")
mw.IMPORT_LEDGER = os.path.join(TMP, "meal_import.json")
mw.LOCK_FILE = os.path.join(TMP, "meal.lock")
mw.POST_GAP = 0.0
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
U9 = "99999999-9999-9999-9999-999999999999"


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


def R(uuid, title, cats=("01 • Meal",), yield_text="4", ings="500 g chicken\n1 tbsp oil\n# Sauce\n2 tsp soy"):
    return mela.Recipe(id=uuid, pk=1, title=title, yield_text=yield_text, ingredients=ings,
                       instructions="Cook.", categories=list(cats))


RECIPES = [R(U1, "Beef Bulgogi"), R(U2, "Oats", ("02 • Breakfast",)), R(U3, "Pockets", ("03 • Snack",))]
BY = {r.id: r for r in RECIPES}
mw._mela = lambda: (RECIPES, BY, None)          # no real Mela here
NOTE_CALLS = []
mw._write_note = lambda picks, sunday: (NOTE_CALLS.append((dict(picks), sunday)) or True)
import api as _api_mod                          # noqa: E402
_api_mod.RateLimitError = RateLimitError
mw._rate_limited = lambda e: isinstance(e, RateLimitError)


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


TODAY = date(2026, 9, 19)
SPEC = {"b": "t1", "l": "t2", "s": "t3", "sunday": "2026-09-27", "back": "ctx:meal"}

# ── dry run ───────────────────────────────────────────────────────────────────
api = fresh()
out = mw.commit(dict(SPEC, dry=True), today=TODAY, api=api)
check("dry run returns text", isinstance(out, str) and "DRY RUN" in out and "Week of 28 Sep" in out, out[:80])
check("dry run reads only", all(c[0] in ("get", "pd") for c in api.calls), api.calls)
check("dry run names the stale pointer + grocery",
      "p_old" in out and "g_old" in out and "keep 1" in out, out)
check("dry run: no ledger, no note", not os.path.exists(mw.LEDGER) and not NOTE_CALLS)

# ── refusals ─────────────────────────────────────────────────────────────────
try:
    mw.commit(dict(SPEC, s="t4"), today=TODAY, api=fresh())
    check("slot mismatch refused", False)
except mw.Refusal as e:
    check("slot mismatch refused", "not tagged 🌮snack" in str(e), str(e))
try:
    mw.commit(dict(SPEC, b="nope"), today=TODAY, api=fresh())
    check("unknown id refused", False)
except mw.Refusal as e:
    check("unknown id refused", "Not in the library" in str(e), str(e))
try:
    mw.commit(dict(SPEC, l=""), today=TODAY, api=fresh())
    check("missing pick refused", False)
except mw.Refusal as e:
    check("missing pick refused", "No lunch picked" in str(e), str(e))

# ── the real thing ────────────────────────────────────────────────────────────
api = fresh()
res = mw.commit(dict(SPEC), today=TODAY, api=api)
kinds = [c[0] for c in api.calls]
check("outcome", isinstance(res, mw.Outcome) and res.msg == "🥘 Week of 28 Sep planned · 3 meals · 3 grocery lists"
      and res.reopen == "ctx:meal", res)
dels = [c for c in api.calls if c[0] == "delete"]
creates = [c for c in api.calls if c[0] == "create"]
check("deletes: the old pointer and the stale grocery only",
      sorted(c[2] for c in dels) == ["g_old", "p_old"], dels)
check("the routine's own step and the archived copy survive",
      "step" in api.lists[RLIST] and "p_arch" in api.lists[RLIST])
check("pointer deletes come before pointer creates",
      kinds.index("delete") < kinds.index("create"))
ptrs = [t for t in api.lists[RLIST].values() if meal.is_pointer(t["title"]) and not t.get("repeatTaskId")]
check("three pointers under the routine, dated the cook Sunday, b/l/s order",
      [meal.pointer_slot(t["title"]) for t in sorted(ptrs, key=lambda t: t["id"])] == ["b", "l", "s"]
      and all(t["parentId"] == RID and t["dueDate"] == "2026-09-27" for t in ptrs), ptrs)
grocs = {meal.link_uuid(t["title"]): t for t in api.lists[LIST].values() if meal.is_grocery(t["title"])}
check("groceries: kept one re-dated, two created, stale gone",
      set(grocs) == {U1, U2, U3} and grocs[U2]["id"] == "g_keep" and grocs[U2]["dueDate"] == "2026-09-26"
      and grocs[U1]["kind"] == "CHECKLIST" and grocs[U1]["dueDate"] == "2026-09-26", grocs)
check("grocery checklist items scaled ×1.75 (4 → 7), header dropped",
      [it["title"] for it in grocs[U1]["items"]] == ["875 g chicken", "1 3/4 tbsp oil", "3 1/2 tsp soy"],
      grocs[U1].get("items"))
check("grocery description carries the yield note", grocs[U1]["content"].startswith("Scaled ×1.75: 4 → 7 portions"),
      grocs[U1]["content"])
check("grocery tag", grocs[U3]["tags"] == ["🛒groceries"])
check("the weekly note was written for the cook Sunday", NOTE_CALLS and NOTE_CALLS[-1][1] == date(2026, 9, 27)
      and NOTE_CALLS[-1][0]["b"]["uuid"] == U2)
led = meal.load_ledger(mw.LEDGER)
check("ledger remembers the week", len(led["weeks"]) == 1 and led["weeks"][0]["sunday"] == "2026-09-27"
      and led["weeks"][0]["l"]["uuid"] == U1 and len(led["weeks"][0]["pointers"]) == 3)
at = cache_store.get("all_tasks")
ids = {t["id"] for t in at}
check("cache: deleted ids gone, new ones in", "p_old" not in ids and "g_old" not in ids
      and all(t["id"] in ids for t in ptrs) and grocs[U1]["id"] in ids)
pd = cache_store.get(f"project_data_{RLIST}")
check("cache: the routine list's project_data mirrors it", "p_old" not in {t["id"] for t in pd["tasks"]}
      and all(t["id"] in {x["id"] for x in pd["tasks"]} for t in ptrs))
check("cache: all_tasks never invalidated", cache_store.get("all_tasks") is not None)
n_calls = len(api.calls)
check("call count is modest (< 25)", n_calls < 25, n_calls)

# a second commit replaces the week (re-plan): pointers deleted again, groceries kept
api2 = api
before = {t["id"] for t in api2.lists[RLIST].values() if meal.is_pointer(t["title"]) and not t.get("repeatTaskId")}
res2 = mw.commit(dict(SPEC), today=TODAY, api=api2)
after = {t["id"] for t in api2.lists[RLIST].values() if meal.is_pointer(t["title"]) and not t.get("repeatTaskId")}
check("re-plan: pointers re-minted, still three", not (before & after) and len(after) == 3)
check("re-plan: groceries kept, none created", "3 grocery lists" in res2.msg and
      len([c for c in api2.calls[n_calls:] if c[0] == "create" and c[1] == LIST]) == 0)
check("ledger: still one entry for that Sunday", len(meal.load_ledger(mw.LEDGER)["weeks"]) == 1)

# ── rate limit mid-way ────────────────────────────────────────────────────────
api = fresh()
api.fail_after = 5                              # 3 reads + delete + first create → boom on the 2nd create
try:
    mw.commit(dict(SPEC), today=TODAY, api=api)
    check("rate limit refuses", False)
except mw.Refusal as e:
    check("rate limit refuses with the wait wording", "rate limit" in str(e), str(e))

# ── rebuild_groceries ─────────────────────────────────────────────────────────
api = fresh()
mw.commit(dict(SPEC), today=TODAY, api=api)
n0 = len(api.calls)
res = mw.rebuild_groceries({"back": "ctx:meal"}, today=TODAY, api=api)
made = [c for c in api.calls[n0:] if c[0] == "create"]
check("rebuild: three lists remade from the pointers", "3 grocery lists rebuilt" in res.msg and len(made) == 3, res)
api = fresh()
api.lists[RLIST].pop("p_old")                   # no open pointer left → no plan
try:
    mw.rebuild_groceries({}, today=TODAY, api=api)
    check("rebuild without a plan refuses", False)
except mw.Refusal as e:
    check("rebuild without a plan refuses", "No meals planned" in str(e), str(e))

# ── import_new ────────────────────────────────────────────────────────────────
api = fresh()
recs = RECIPES + [R("11111111-1111-1111-1111-111111111111", "New Lunch"),
                  R("22222222-2222-2222-2222-222222222222", "New Snack", ("03 • Snack",)),
                  R("33333333-3333-3333-3333-333333333333", "No category", ())]
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0)
made = [c for c in api.calls if c[0] == "create"]
check("import: only the categorised unknowns", r["created"] == 2 and r["no_category"] == 1 and r["skipped"] == 3, r)
check("import: title is the Mela link, tag lowercased", made[0][2].startswith("[New ") and "mela://recipe/" in made[0][2]
      and all(t["tags"] in (["🍛lunch"], ["🌮snack"]) for t in api.lists[LIST].values() if t["id"].startswith("new")))
check("import: body rendered", all(t["content"].startswith("> 🔗 [New") for t in api.lists[LIST].values() if t["id"].startswith("new")))
check("import: chip", r["chip"] == "🥘 +2 recipes")
r2 = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0)
check("import: the ledger stops a second run even with a stale 'existing'", r2["created"] == 0 and r2["skipped"] == 5, r2)
api = fresh()
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=1, pace=0, ledger_path=os.path.join(TMP, "imp2.json"))
check("import: cap + remaining", r["created"] == 1 and r["remaining"] == 1, r)
api = fresh()
api.fail_after = 0
r = mw.import_new(api, recipes=recs, list_id=LIST, cap=10, pace=0, ledger_path=os.path.join(TMP, "imp3.json"))
check("import: rate limit stops the run", r["rate_limited"] and r["created"] == 0, r)

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

print(f"\nmeal_write: {COUNT[0] - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
