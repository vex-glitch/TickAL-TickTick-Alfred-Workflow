#!/usr/bin/env python3
"""RED test (review 2026-09-24, item R15): a TickAL write must never revert a
change made in the TickTick app.

The Meal Prep bug (Vex 2026-09-24): the subtask was dragged in the app from
"Workflows" to the WF task, the hourly cache still said parentId=Workflows,
and the next update_task(current=<cached copy>) posted the cached parentId
back. A fake session plays TickTick; nothing reaches the network.

Contract under test (the design):
  * update_task trusts `current` without a GET only when the caller says
    fresh=True, or when `current` was read by THIS process (api.READ_RUN)
    less than api.LIVE_WINDOW seconds ago (get_task / get_project_data
    stamp _read_run/_read_at on every task dict they return).
  * otherwise it GETs live (positional pid, then current's projectId on a
    404) and applies ONLY the caller's fields (and derive(base)) over it.
  * RateLimitError on the GET raises with no POST; a transport failure
    falls back to `current` (logged); 404 at every candidate raises.
  * api_v2.update_tasks refuses (posts nothing, returns False) when any
    body is not a same-run read, unless fresh=True.
"""
import copy
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

SCRATCH = tempfile.mkdtemp(prefix="tickal_red_")
os.environ["HOME"] = SCRATCH               # before ANY repo import
os.environ["TICKAL_NO_SETTLE"] = "1"
os.environ["TT_V2_TOKEN"] = "fake-v2-token"   # no Keychain read in TickTickV2()

REPO = os.environ.get("TICKAL_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src", "lib"))
sys.path.insert(0, os.path.join(REPO, "src"))
import api          # noqa: E402
import api_v2       # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
    if not cond:
        FAILS.append(name)


T, P, P2 = "6aaeeab28f0859df6996e092", "6a3413e02522110c0d06e678", "b" * 24
OLD = "6aaeeab18f08bd7cd4abca18"   # Workflows (where the cache says)
NEW = "6aaeeaab8f085e121b2a9930"   # the WF task (where Vex dragged it)

LIVE = {"id": T, "projectId": P, "parentId": NEW, "title": "Meal Prep",
        "sortOrder": -1099511627776, "tags": ["a", "b"], "status": 0,
        "modifiedTime": "2026-09-23T09:00:00.000+0000"}
CACHED = {"id": T, "projectId": P, "parentId": OLD, "title": "Meal Prep",
          "sortOrder": 7, "tags": ["a"], "status": 0,
          "_projectId": P, "_projectName": "CTA", "_columnName": ""}


class Reply:
    def __init__(self, body, status=200):
        self.status_code, self.ok = status, status < 400
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise api.requests.HTTPError(f"{self.status_code}", response=self)


class Session:
    """GET answers from `where` ({pid: live object}); a pid not in it 404s
    (probe 2026-09-09, crm_records.locate). POST echoes the body, and
    json-encodes it exactly as requests would (a callable in the body
    raises TypeError, as it would on the wire)."""
    def __init__(self, where=None, get_error=None, get_reply=None):
        self.where = where if where is not None else {P: LIVE}
        self.get_error, self.get_reply = get_error, get_reply
        self.gets, self.posts = [], []

    def get(self, url, **kw):
        self.gets.append(url)
        if self.get_error is not None:
            raise self.get_error
        if self.get_reply is not None:
            return self.get_reply
        pid = url.split("/project/")[1].split("/")[0]
        obj = self.where.get(pid)
        return Reply(copy.deepcopy(obj)) if obj else Reply("", status=404)

    def post(self, url, json=None, **kw):
        body = __import__("json").loads(__import__("json").dumps(json))
        self.posts.append(body)
        return Reply(body)


def client(sess):
    c = api.TickTickAPI("fake-token")     # the real class; its session is swapped
    c.session = sess
    return c


def run(name, fn):
    try:
        fn()
    except Exception as e:                 # a crash is a FAIL, not an abort
        check(name, False, f"raised {type(e).__name__}: {e}")


def posted_clean(body):
    return not any(k.startswith("_") for k in body) and \
        "fresh" not in body and "derive" not in body


# R1 the bug itself: a cached current is refreshed, the drag survives
def r1():
    s = Session()
    client(s).update_task(T, P, current=dict(CACHED), title="x")
    check("R1 stale cached current: one live GET first", len(s.gets) == 1, s.gets)
    b = s.posts[0] if s.posts else {}
    check("R1 posts the LIVE parentId (the drag survives)", b.get("parentId") == NEW, b.get("parentId"))
    check("R1 posts the caller's field", b.get("title") == "x")
    check("R1 other live fields survive (sortOrder, tags)",
          b.get("sortOrder") == LIVE["sortOrder"] and b.get("tags") == ["a", "b"], b)
    check("R1 no internal keys on the wire", posted_clean(b), sorted(b))


# R2 fresh=True: the caller vouches, zero GETs, current posted as given
def r2():
    s = Session()
    client(s).update_task(T, P, current=dict(CACHED), fresh=True, title="x")
    b = s.posts[0] if s.posts else {}
    check("R2 fresh=True: no GET", s.gets == [], s.gets)
    check("R2 fresh=True: the given current is posted", b.get("parentId") == OLD, b.get("parentId"))
    check("R2 fresh is a flag, never a task field", posted_clean(b), sorted(b))


# R3 a same-run live read keeps ONE round trip (the _pn_rmw shape)
def r3():
    s = Session()
    c = client(s)
    live = c.get_task(P, T)
    c.update_task(T, P, current=live, content="new")
    check("R3 same-run read: no second GET", len(s.gets) == 1, s.gets)
    check("R3 same-run read: one POST with the live parent",
          len(s.posts) == 1 and s.posts[0].get("parentId") == NEW, s.posts)
    check("R3 the read stamp never reaches TickTick", posted_clean(s.posts[0]) if s.posts else False)


# R4 GET transport failure: RAISE, never post the given copy (the review of
# the first cut showed a fallback is the revert itself, and a POST needs the
# same network)
def r4():
    s = Session(get_error=api.requests.ConnectionError("offline"))
    raised = False
    try:
        client(s).update_task(T, P, current=dict(CACHED), title="x")
    except api.requests.ConnectionError:
        raised = True
    check("R4 transport failure: the GET was tried", len(s.gets) == 1, s.gets)
    check("R4 transport failure: raises, posts nothing", raised and s.posts == [], s.posts)
    s = Session(get_reply=Reply({"errorCode": "gateway"}, status=502))
    raised = False
    try:
        client(s).update_task(T, P, current=dict(CACHED), title="x")
    except api.requests.HTTPError:
        raised = True
    check("R4 a 5xx on the GET raises too, posts nothing", raised and s.posts == [], s.posts)


# R5 rate limit on the GET: raise, never POST (a POST deepens the lockout)
def r5():
    s = Session(get_reply=Reply({"errorCode": "exceed_query_limit",
                                 "errorMessage": "limit"}, status=500))
    raised = False
    try:
        client(s).update_task(T, P, current=dict(CACHED), title="x")
    except api.RateLimitError:
        raised = True
    check("R5 rate-limited GET raises RateLimitError", raised)
    check("R5 rate-limited GET posts nothing", s.posts == [], s.posts)


# R6 404 under the positional list, found under current's own list
def r6():
    live2 = dict(LIVE, projectId=P2)
    s = Session(where={P2: live2})
    client(s).update_task(T, P, current=dict(CACHED, projectId=P2), title="x")
    check("R6 404 at the positional pid, then current's pid",
          [u.split("/project/")[1].split("/")[0] for u in s.gets] == [P, P2], s.gets)
    check("R6 posts the live object under its real list",
          s.posts and s.posts[0].get("projectId") == P2 and s.posts[0].get("parentId") == NEW, s.posts)


# R6b 404 everywhere: raise, post nothing (the cached copy is not revived)
def r6b():
    s = Session(where={})
    raised = False
    try:
        client(s).update_task(T, P, current=dict(CACHED), title="x")
    except Exception:
        raised = True
    check("R6b gone from every candidate list: raises", raised)
    check("R6b gone: posts nothing", s.posts == [], s.posts)


# R7 derive: a read-modify-write field is computed from the LIVE base
def r7():
    s = Session()
    client(s).update_task(T, P, current=dict(CACHED),
                          derive=lambda base: {"tags": list(base.get("tags") or []) + ["c"]})
    b = s.posts[0] if s.posts else {}
    check("R7 derive merges over live tags (app-added tag kept)", b.get("tags") == ["a", "b", "c"], b.get("tags"))


# R7b derive returning None skips the write (the roll: already moved in the app)
def r7b():
    s = Session()
    out = client(s).update_task(T, P, current=dict(CACHED), derive=lambda base: None)
    check("R7b derive None: no POST", s.posts == [], s.posts)
    check("R7b derive None: returns None", out is None, out)


# R8 a cached row stamped by ANOTHER process (the hourly sync) is not trusted
def r8():
    s = Session()
    row = dict(CACHED, _read_run="sync-process", _read_at=time.time())
    client(s).update_task(T, P, current=row, title="x")
    check("R8 other-process stamp: GET first", len(s.gets) == 1, s.gets)
    check("R8 other-process stamp: live parent posted",
          s.posts and s.posts[0].get("parentId") == NEW, s.posts)


# R9 a same-run read older than the window is re-read (dialogs are slow)
def r9():
    s = Session()
    win = getattr(api, "LIVE_WINDOW", 120)
    row = dict(CACHED, _read_run=getattr(api, "READ_RUN", "?"), _read_at=time.time() - win - 1)
    client(s).update_task(T, P, current=row, title="x")
    check("R9 same-run read past the window: GET first", len(s.gets) == 1, s.gets)


# V1..V3 the v2 batch road
class V2Post:
    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, **kw):
        self.calls.append(json)
        return Reply({"id2etag": {}, "id2error": {}})


def with_v2(fn):
    saved = api_v2.requests.post
    rec = V2Post()
    api_v2.requests.post = rec
    try:
        fn(rec)
    finally:
        api_v2.requests.post = saved


def v1():
    def body(rec):
        ok = api_v2.TickTickV2().update_tasks([dict(CACHED, title="x")])
        check("V1 v2 stale body: not posted", rec.calls == [], rec.calls)
        check("V1 v2 stale body: reports not written", ok is False, ok)
    with_v2(body)


def v2():
    def body(rec):
        s = Session()
        live = client(s).get_task(P, T)
        ok = api_v2.TickTickV2().update_tasks([dict(live, title="x")])
        sent = rec.calls[0]["update"][0] if rec.calls else {}
        check("V2 v2 same-run body: posted", ok is True and sent.get("parentId") == NEW, rec.calls)
        check("V2 v2 stamp stripped", posted_clean(sent), sorted(sent))
    with_v2(body)


def v3():
    def body(rec):
        ok = api_v2.TickTickV2().update_tasks([dict(CACHED, title="x")], fresh=True)
        check("V3 v2 fresh=True (a just-created object): posted", ok is True and len(rec.calls) == 1, rec.calls)
    with_v2(body)


# V4 okr_write._write: v2 refuses a stale raw, the v1 fallback reads live
def v4():
    import okr_write

    def body(rec):
        s = Session()
        c = client(s)
        item = SimpleNamespace(id=T, pid=P, raw=dict(CACHED))
        snap = SimpleNamespace(list_id=P)
        written, failed = okr_write._write(snap, [(item, {"tags": ["okr"]})], c, api_v2.TickTickV2())
        check("V4 _write: v2 sent nothing stale", rec.calls == [], rec.calls)
        check("V4 _write: v1 fallback posted the live parent",
              s.posts and s.posts[0].get("parentId") == NEW and s.posts[0].get("tags") == ["okr"], s.posts)
        check("V4 _write: reported written", written == [T] and failed == [], (written, failed))
    with_v2(body)




# ── the second cut (review of the first, 2026-09-24 evening) ─────────────────
sys.path.insert(0, os.path.join(REPO, "Scripts"))
import cache as cache_store          # noqa: E402  (HOME is scratch: the cache dir too)
import dispatch                      # noqa: E402
import xact                          # noqa: E402
import repeat_settle                 # noqa: E402
from script_base import run_path     # noqa: E402

os.environ["token"] = "fake-token"   # cfg.get_token() reads it; no Keychain


# R10 TickTick's read lag: a cache row carrying TickAL's own last write lays
# those fields over a live read that predates it, and not over a newer one
def r10():
    old_live = dict(LIVE, priority=0, modifiedTime="2026-09-24T10:00:00.000+0000")
    row = dict(CACHED, _written={"modifiedTime": "2026-09-24T10:00:05.000+0000",
                                 "fields": {"priority": 5}})
    s = Session(where={P: old_live})
    b = client(s).update_task(T, P, current=row, title="x")
    check("R10 a lagging live read gets our last write laid over it",
          s.posts and s.posts[0].get("priority") == 5 and s.posts[0].get("parentId") == NEW, s.posts)
    newer = dict(old_live, modifiedTime="2026-09-24T10:00:09.000+0000", priority=1)
    s = Session(where={P: newer})
    client(s).update_task(T, P, current=row, title="x")
    check("R10 a live read newer than our write wins", s.posts[0].get("priority") == 1, s.posts)
    check("R10 the marker never reaches the wire", posted_clean(s.posts[0]), sorted(s.posts[0]))


# R11 update_task's reply is stamped and remembered; dispatch's cache mirror
# stores it on the row as _written; cache.set strips the read stamps
def r11():
    cache_store.CACHE_DIR = os.path.join(SCRATCH, "cache")
    cache_store.set("all_tasks", [dict(CACHED)])
    s = Session()
    resp = client(s).update_task(T, P, current=dict(LIVE), fresh=True, priority=5)
    check("R11 the reply is this run's fresh read", api.is_fresh(resp), resp)
    check("R11 and is remembered for the cache mirror", api.LAST_POSTED.get(T) is resp)
    dispatch._patch_task_cache(T, priority=5)
    row = cache_store.find_task(T)
    check("R11 the cache row carries the write (_written: modifiedTime + fields)",
          isinstance(row.get("_written"), dict) and row["_written"].get("fields") == {"priority": 5}
          and row.get("priority") == 5, row)
    check("R11 the marker is consumed once", T not in api.LAST_POSTED)
    cache_store.set("all_notes", [dict(LIVE)])            # a stamped live dict stored
    stored = [t for t in cache_store.get("all_notes") if t["id"] == T][0]
    check("R11 cache.set strips the read stamps, keeps the rest",
          "_read_run" not in stored and "_read_at" not in stored and stored.get("parentId") == NEW, sorted(stored))


class Lists:
    """A session serving project-data and single-task GETs from {pid: [tasks]};
    an unknown list 404s; POST echoes. Optional per-list errors."""
    def __init__(self, lists, errors=None):
        self.lists, self.errors = lists, errors or {}
        self.gets, self.posts = [], []
        self.headers = {}

    def mount(self, *a, **k):
        pass

    def get(self, url, **kw):
        self.gets.append(url)
        parts = url.split("/open/v1/")[1].split("/")
        pid = parts[1]
        if pid == "inbox":
            pid = next((k for k in self.lists if k.startswith("inbox")), pid)
        if pid in self.errors:
            e = self.errors[pid]
            if isinstance(e, Exception):
                raise e
            return Reply(e[0], status=e[1])
        if pid not in self.lists:
            return Reply("", status=404)
        rows = [dict(copy.deepcopy(t), projectId=pid) for t in self.lists[pid]]
        if len(parts) == 3 and parts[2] == "data":
            return Reply({"project": {"id": pid}, "tasks": rows})
        tid = parts[3]
        hit = next((t for t in rows if t["id"] == tid), None)
        return Reply(hit) if hit else Reply("", status=404)

    def post(self, url, json=None, **kw):
        body = __import__("json").loads(__import__("json").dumps(json))
        self.posts.append((url.split("/open/v1/")[1], body))
        return Reply(dict(body, modifiedTime="2026-09-24T12:00:00.000+0000"))


def _install(sess):
    api.requests.Session = lambda: sess           # TickTickAPI() gets the fake
    return sess


L1, L2 = "l" * 24, "m" * 24
A1, A2, B1, GONE = "a1" * 12, "a2" * 12, "b1" * 12, "g0" * 12


def _lists():
    return {L1: [{"id": A1, "title": "one", "parentId": NEW, "tags": ["live"], "status": 0, "sortOrder": 1},
                 {"id": A2, "title": "two", "status": 0}],
            L2: [{"id": B1, "title": "three", "status": 0}]}


# L1 live_tasks: one read per list, the inbox alias folded, an unreadable list
# skipped, a rate limit or a transport error propagated
def l1():
    s = _install(Lists(_lists()))
    got = client(s).live_tasks([(L1, A1), (L1, A2), (L2, B1), (L2, GONE), ("inbox", "x"), ("inbox131", "y")])
    data = [u for u in s.gets if u.endswith("/data")]
    check("L1 one project-data read per distinct list, the inbox alias folded", len(data) == 3, data)
    check("L1 the live rows come back keyed by id, the absent one missing",
          set(got) == {A1, A2, B1} and got[A1].get("parentId") == NEW and api.is_fresh(got[A1]), sorted(got))
    s = _install(Lists(_lists(), errors={L2: ("", 404)}))
    got = client(s).live_tasks([(L1, A1), (L2, B1)])
    check("L1 an unreadable list is skipped, the others still read", set(got) == {A1}, sorted(got))
    s = _install(Lists(_lists(), errors={L1: ({"errorCode": "exceed_query_limit"}, 500)}))
    raised = False
    try:
        client(s).live_tasks([(L1, A1)])
    except api.RateLimitError:
        raised = True
    check("L1 a rate limit propagates", raised)
    s = _install(Lists(_lists(), errors={L1: api.requests.ConnectionError("off")}))
    raised = False
    try:
        client(s).live_tasks([(L1, A1)])
    except api.requests.ConnectionError:
        raised = True
    check("L1 a transport error propagates", raised)


def _buffer(lines):
    with open(run_path("tickal_buffer.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


def _buffer_lines():
    try:
        return [ln.strip() for ln in open(run_path("tickal_buffer.txt")) if ln.strip()]
    except OSError:
        return []


# B the buffer roads: live bodies, skips counted, buffer kept on a failed read,
# a rate limit partway keeps the unapplied lines
def b1():
    cache_store.CACHE_DIR = os.path.join(SCRATCH, "cache")
    cache_store.set("all_tasks", [{"id": A1, "projectId": L1, "parentId": OLD, "tags": ["stale"], "status": 0}])
    s = _install(Lists(_lists()))
    _buffer([f"{L1}:{A1}", f"{L1}:{A2}", f"{L2}:{GONE}"])
    c = client(s)
    res = dispatch._buffer_apply(lambda bpid, btid, cur: c.update_task(btid, bpid, current=cur, priority=5))
    check("B1 two applied, one skipped (gone from live), none kept", res == (2, 1, 0), res)
    posted = {tid: body for url, body in s.posts for tid in [url.split("/")[-1]]}
    check("B1 the posts carry the LIVE parent and tags, plus the field",
          posted.get(A1, {}).get("parentId") == NEW and posted[A1].get("tags") == ["live"]
          and posted[A1].get("priority") == 5, posted.get(A1))
    check("B1 no second GET per task (the list read is the trusted base)",
          len([u for u in s.gets if not u.endswith("/data")]) == 0, s.gets)
    check("B1 the buffer is cleared", _buffer_lines() == [], _buffer_lines())
    check("B1 the toast names the skip", "1 changed in the app" in dispatch._buffer_toast(res, "tagged"))
    _buffer([f"{L1}:{A1}"])
    s = _install(Lists(_lists(), errors={L1: api.requests.ConnectionError("off")}))
    res = dispatch._buffer_apply(lambda bpid, btid, cur: None)
    check("B1 a failed live read applies nothing, keeps the buffer, says so",
          res is None and _buffer_lines() == [f"{L1}:{A1}"] and "buffer kept" in dispatch._buffer_toast(None, "x"))
    _buffer([f"{L1}:{A1}", f"{L1}:{A2}", f"{L2}:{B1}"])
    s = _install(Lists(_lists()))
    hits = []

    def fn(bpid, btid, cur):
        hits.append(btid)
        if len(hits) == 2:
            raise api.RateLimitError("limit")
    res = dispatch._buffer_apply(fn)
    check("B1 a rate limit partway stops the loop and keeps the rest",
          res == (1, 0, 2) and _buffer_lines() == [f"{L1}:{A2}", f"{L2}:{B1}"], (res, _buffer_lines()))
    _buffer([f"{L1}:{A1}"])
    s = _install(Lists(_lists()))
    moved = []
    res = dispatch._buffer_apply(lambda bpid, btid, cur: moved.append((btid, cur)), needs_live=False)
    check("B1 the move road needs no live read", res == (1, 0, 0) and s.gets == [] and moved[0][0] == A1, (res, s.gets))


# D the date bulks: live base, scope re-checked on the live task, skips counted
def d1():
    today = __import__("datetime").date.today()
    import day_move
    yday = day_move.all_day(today - __import__("datetime").timedelta(days=1))
    tmrw = day_move.all_day(today + __import__("datetime").timedelta(days=1))
    # top-level: the Overdue scope leaves subtasks out by design, so the live
    # field that must survive here is the tag list
    lists = {L1: [{"id": A1, "title": "overdue still", "tags": ["live"], "status": 0, **yday},
                  {"id": A2, "title": "moved to tomorrow in the app", "status": 0, **tmrw}],
             L2: [{"id": B1, "title": "done in the app", "status": 2, **yday}]}
    pool = [{"id": A1, "projectId": L1, "tags": ["stale"], **yday},
            {"id": A2, "projectId": L1, **yday},
            {"id": B1, "projectId": L2, **yday},
            {"id": GONE, "projectId": L2, **yday}]
    s = _install(Lists(lists))
    xact._api = lambda: client(s)
    done, skipped, failed = xact._date_bulk_run(pool, lambda b: {"startDate": None, "dueDate": None},
                                                keep=xact._scope_keep("overdue"))
    check("D1 clear dates on Overdue: one cleared, three skipped (rescheduled, done, gone), none failed",
          (done, skipped, failed) == (1, 3, 0), (done, skipped, failed))
    check("D1 the one post carries the LIVE tags and clears the dates",
          len(s.posts) == 1 and s.posts[0][1].get("tags") == ["live"] and s.posts[0][1].get("startDate") is None, s.posts)
    check("D1 two list reads, no per-task GET", len([u for u in s.gets if u.endswith("/data")]) == 2
          and not [u for u in s.gets if not u.endswith("/data")], s.gets)


# V5 repeat_settle vouches for its stamp-stripped copies (nudge_body) with
# fresh=True, so the real v2 gate posts them; without it the gate refuses
def v5():
    def body(rec):
        v2 = api_v2.TickTickV2()
        copy_ = dict(LIVE)
        api.stamp_read(copy_)
        nb = repeat_settle.nudge_body(copy_)
        check("V5 nudge_body strips the stamps", "_read_run" not in nb)
        check("V5 without fresh the gate refuses it", v2.update_tasks([nb]) is False and rec.calls == [])
        check("V5 with fresh=True it is posted", v2.update_tasks([nb], fresh=True) is True and len(rec.calls) == 1)
    with_v2(body)
    src = open(os.path.join(REPO, "src", "repeat_settle.py"), encoding="utf-8").read()
    check("V5 repeat_settle passes fresh=True", "fresh=True" in src.split("def settle")[1])


for n, f in [("R1", r1), ("R2", r2), ("R3", r3), ("R4", r4), ("R5", r5), ("R6", r6),
             ("R6b", r6b), ("R7", r7), ("R7b", r7b), ("R8", r8), ("R9", r9),
             ("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4),
             ("R10", r10), ("R11", r11), ("L1", l1), ("B1", b1), ("D1", d1), ("V5", v5)]:
    run(n, f)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
sys.exit(1 if FAILS else 0)
