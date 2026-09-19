#!/usr/bin/env python3
"""The OKR writers (src/okr_write.py) and their xact verbs, phase 2.

Everything a 🥅 hub write does, against FAKE clients: a v1 double that
keeps a little task store, a v2 double for the completed read and the batch
write, and an in-memory cache. No network, no dialogs, no Alfred, no real
cache or config file: the lock, the heal stamp and the log live in a temp
dir, and okr_list_id rides the env the way config.get_okr_list_id reads it.

    python3 tests/test_okr_write.py
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
os.environ["TICKAL_NO_SETTLE"] = "1"

PID = "a" * 24                     # a made-up list id: never Vex's real list
os.environ["okr_list_id"] = PID

import cache  # noqa: E402
import okr  # noqa: E402
import okr_write as ow  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="okr_write_test_")
ow.LOCK_FILE = os.path.join(TMP, "okr.lock")
ow.HEAL_STAMP = os.path.join(TMP, "okr_heal.stamp")
ow.HEAL_LOG = os.path.join(TMP, "okr.log")
ow.LOCK_WAIT = 0.4
ow.CD_REGISTRY = os.path.join(TMP, "okr_countdowns.json")
ow._mtime = lambda key: None       # the in-memory cache has no files to date
TODAY = date(2026, 9, 18)


def d(m, day, y=2026):
    return date(y, m, day)


def D(tid, title, s=None, e=None, parent=None, status=0, tags=None, **kw):
    """A raw task from INCLUSIVE dates, written the way okr writes a span."""
    st = du = None
    if s is not None:
        st, du = okr.span_raw(s, e)
    t = {"id": tid, "projectId": PID, "title": title, "startDate": st,
         "dueDate": du, "timeZone": "", "isAllDay": True, "status": status,
         "parentId": parent, "childIds": [], "tags": list(tags or []),
         "content": "", "sortOrder": 0, "etag": "e0"}
    t.update(kw)
    return t


LINK_T = "https://ticktick.com/webapp/#p/eeeeeeeeeeeeeeeeeeeeeeee/tasks/ffffffffffffffffffffffff"


def fixture():
    """(open rows, completed rows). O1 is STORED stale at the SAME LENGTH as
    its wanted span (Sep 29 - Oct 24 vs Sep 19 - Oct 14: 26 days each) - the
    shape where writing a healed() copy would shift by zero (map trap 1)."""
    open_rows = [
        D("O1", "🥅 O • TickAL", d(9, 29), d(10, 24), tags=["💼tickal"]),
        D("K1", "🔑 KR • Goals wf - TA", d(9, 19), d(10, 4), "O1", tags=["💼tickal"]),
        D("K2", "🔑 KR • Hub - TA", d(10, 5), d(10, 14), "O1", tags=["💼tickal"]),
        D("K3", "🔑 KR • Eagle - TA", parent="O1"),
        D("K5", "🔑 KR • Side quest - TA", d(9, 20), d(9, 21), "O1", tags=["💼adhoc"]),
        D("K7", "🔑 KR • Stray - TA", d(9, 22), d(9, 23), "O1",
          tags=["💼tickal", "⭐solo2"]),
        D("K8", "🔑 KR • Call Anna - Monday", parent="O1", tags=["💼tickal"]),
        D("K9", f"🔑 KR • [Ship it]({LINK_T}) - TA", parent="O1", tags=["💼tickal"]),
        D("O2", "🥅 O • Workflows", d(10, 15), d(10, 20), tags=["💼workflows"]),
        D("K6", "🔑 KR • Typinator WF", d(10, 15), d(10, 20), "O2", tags=["💼workflows"]),
        D("O4", "🥅 O • ✨"),
        D("U1", "Loose note", tags=["⭐solo"]),
    ]
    done_rows = [
        D("K4", "🔑 KR • Model - TA", d(9, 19), d(9, 25), "O1", status=2,
          tags=["💼tickal"]),
        D("O3", "🥅 O • Other things", d(8, 1), d(8, 30), status=2, tags=["💼adhoc"]),
    ]
    return open_rows, done_rows


def cp(x):
    return json.loads(json.dumps(x))


class FakeAPI:
    def __init__(self, open_rows, done_rows):
        self.store = {t["id"]: cp(t) for t in open_rows}
        self.done = {t["id"]: cp(t) for t in done_rows}
        self.calls = []
        self.n = 0
        self.fail_update = False
        self.fail_ids = set()              # update_task refuses these ids only
        self.create_tz = None              # a zone the create response carries
        self.create_order = None           # a sortOrder EVERY create gets (a tie)
        self.create_orders = None          # one sortOrder per create, in order
        self.fail_create = None            # an exception every create raises

    def get_project_data(self, pid):
        self.calls.append(("get_project_data", pid))
        return {"project": {"id": pid, "name": "🏆Goals Planning"},
                "tasks": [cp(t) for t in self.store.values()
                          if t.get("projectId") == pid and t.get("status") == 0]}

    def get_task(self, pid, tid):
        self.calls.append(("get_task", pid, tid))
        t = self.store.get(tid) or self.done.get(tid)
        if not t:
            raise RuntimeError("404")
        return cp(t)

    def update_task(self, tid, pid, current=None, **fields):
        self.calls.append(("update_task", tid, pid, cp(fields), cp(current)))
        if self.fail_update or tid in self.fail_ids:
            raise RuntimeError("v1 down")
        body = {**(current or {}), **fields}
        self.store[tid] = cp(body)
        return cp(body)

    def create_task(self, title, project_id=None, parent_id=None, tags=None,
                    content=None, **kw):
        self.n += 1
        tid = f"new{self.n}"
        self.calls.append(("create_task", title, project_id, parent_id, tags, content, kw))
        if self.fail_create is not None:
            raise self.fail_create
        order = (self.create_orders[self.n - 1] if self.create_orders
                 else 1000 - self.n * 100 if self.create_order is None
                 else self.create_order)
        t = {"id": tid, "projectId": project_id, "title": title,
             "tags": list(tags or []), "parentId": parent_id, "status": 0,
             "sortOrder": order, "isAllDay": False}
        if content:
            t["content"] = content
        if self.create_tz:
            t["timeZone"] = self.create_tz
        self.store[tid] = cp(t)
        lie = dict(t)
        lie["parentId"] = None               # the v1 create response lies
        return lie

    def complete_task(self, pid, tid):
        self.calls.append(("complete_task", pid, tid))
        t = self.store.pop(tid)
        t["status"] = 2
        self.done[tid] = t
        return True

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


class FakeV2:
    def __init__(self, api, token="tok", ok=True, completed=True):
        self.api = api
        self.token = token
        self.ok = ok
        self.completed = completed
        self.batches = []
        self.cds = None                    # the countdown list (None = the read fails)
        self.cd_ok = True
        self.cd_batches = []
        self.abandon_ok = True
        self.abandoned = []

    def project_completed(self, pid, days=120, limit=500):
        if not self.token or not self.completed:
            return None
        return [cp(t) for t in self.api.done.values()]

    def update_tasks(self, bodies):
        self.batches.append(cp(bodies))
        if not self.token or not self.ok:
            return False
        for b in bodies:
            if b["id"] in self.api.store:
                self.api.store[b["id"]] = cp({k: v for k, v in b.items()
                                              if not k.startswith("_")})
        return True


    def get_countdowns(self):
        return None if self.cds is None else cp(self.cds)

    def countdown_batch(self, add=None, update=None, delete=None):
        self.cd_batches.append(cp({"add": add or [], "update": update or [],
                                   "delete": delete or []}))
        if not self.token or not self.cd_ok:
            return False
        by = {c["id"]: c for c in self.cds or []}
        for c in (add or []) + (update or []):
            by[c["id"]] = cp(c)
        self.cds = list(by.values())
        return True

    def abandon_task(self, task):
        self.abandoned.append(cp(task))
        if not self.token or not self.abandon_ok:
            return False
        self.api.store.pop(task["id"], None)     # in no read any more
        return True


class Boom(FakeAPI):
    """v1 down: okr.load falls back to the cache, which no writer takes."""
    def get_project_data(self, pid):
        self.calls.append(("get_project_data", pid))
        raise RuntimeError("boom")


# ── the in-memory cache ──────────────────────────────────────────────────────
MEM = {}
_orig = (cache.get, cache.set, cache.invalidate, cache.age_seconds)
cache.get = lambda k: cp(MEM[k]) if k in MEM else None
cache.set = lambda k, v: MEM.__setitem__(k, cp(v))
cache.invalidate = lambda k=None: MEM.pop(k, None) if k else MEM.clear()
cache.age_seconds = lambda k: 60.0 if k in MEM else None


def seed_cache(open_rows, done_rows):
    MEM.clear()
    rows = [dict(t, _projectId=PID, _projectName="🏆Goals Planning", _columnName="")
            for t in open_rows]
    MEM["all_tasks"] = cp(rows) + [{"id": "zz", "projectId": "other", "title": "x"}]
    MEM["all_notes"] = []
    MEM[f"project_data_{PID}"] = {"project": {"id": PID}, "tasks": cp(rows)}
    MEM["okr_rows"] = {"list_id": PID, "name": "🏆Goals Planning", "detail": "t",
                       "rows": cp(open_rows) + cp(done_rows)}
    MEM["projects"] = [{"id": PID, "name": "🏆Goals Planning"},
                       {"id": "d" * 24, "name": "Workflows"}]
    MEM["tags_tree"] = [
        {"name": "0️⃣area", "label": "0️⃣Area", "parent": ""},
        {"name": "1️⃣work", "label": "1️⃣Work", "parent": "0️⃣area"},
        {"name": "2️⃣personal", "label": "2️⃣Personal", "parent": "0️⃣area"},
        {"name": "💼tickal", "label": "💼TickAL", "parent": "💼projects"},
        {"name": "🔥crm", "label": "🔥CRM", "parent": ""},
    ]
    MEM["completed_tasks"] = [{"id": "old", "title": "old"}]


def world(**v2kw):
    o, dn = fixture()
    seed_cache(o, dn)
    api = FakeAPI(o, dn)
    return api, FakeV2(api, **v2kw)


def boom_world():
    o, dn = fixture()
    seed_cache(o, dn)
    api = Boom(o, dn)
    return api, FakeV2(api)


def wrote_nothing(api, v2):
    return not (v2.batches or api.of("update_task") or api.of("create_task")
                or api.of("complete_task"))


def snapshot(api, v2):
    return okr.load(api=api, v2=v2, list_id=PID)


def cached(key, tid):
    rows = MEM.get(key)
    if isinstance(rows, dict):
        rows = rows.get("tasks") if "tasks" in rows else rows.get("rows")
    return next((t for t in rows or [] if t.get("id") == tid), None)


def refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ow.Refusal as e:
        return str(e)
    return None


def refusal(fn, *a, **kw):
    """The Refusal itself (its reopen matters), or None."""
    try:
        fn(*a, **kw)
    except ow.Refusal as e:
        return e
    return None


def attempt(fn, *a, **kw):
    """What the call returned, or the Refusal it raised: a write that should
    go through then FAILS its check instead of aborting the whole run."""
    try:
        return fn(*a, **kw)
    except ow.Refusal as e:
        return e


def ids(out):
    return getattr(out, "ids", None)


try:
    # ── 1. apply_spans: stored items, later wins, v2 then v1, the cache ──────
    print("apply_spans")
    api, v2 = world()
    snap = snapshot(api, v2)
    check("fixture: a live, complete read (writable)", snap.writable, snap.detail)
    by = okr.index(snap.items)
    heal = okr.heal_diff(snap.items)
    check("fixture: O1 is stale at the same length", heal == [("O1", d(9, 19), d(10, 14))], heal)
    res = ow.apply_spans(snap, heal, api, v2)
    body = v2.batches[0][0]
    check("heal written through ONE v2 batch", len(v2.batches) == 1 and res.written == ["O1"],
          (v2.batches, res))
    check("trap 1: the STORED O1 shifts onto its wanted span (not a zero shift)",
          okr.span(body) == (d(9, 19), d(10, 14)), okr.span(body))
    check("the body is the stored raw with the fields over it",
          body["etag"] == "e0" and body["title"] == "🥅 O • TickAL" and body["isAllDay"] is True)
    check("same length on an all-day item = a SHIFT keeping its own form",
          body["startDate"] == okr.shift_raw(by["O1"].raw["startDate"],
                                             by["O1"].raw["dueDate"], -10)[0])
    for key in ("all_tasks", f"project_data_{PID}", "okr_rows"):
        c = cached(key, "O1")
        check(f"cache {key}: O1 patched", c and c["startDate"] == body["startDate"]
              and c["dueDate"] == body["dueDate"], c)
    check("cache: the unrelated row survives", cached("all_tasks", "zz") is not None)
    rc = MEM["okr_rows"]
    check("okr_rows REBUILT from the live read: its shape, the done KR, the read's own "
          "detail (never the seed's)",
          rc.get("list_id") == PID and rc.get("name") == "🏆Goals Planning"
          and rc.get("done_complete") is True and rc.get("detail") == snap.detail != "t"
          and sorted(rc) == ["detail", "done_complete", "list_id", "name", "rows"]
          and cached("okr_rows", "K4")["status"] == 2, sorted(rc))
    oc = MEM.get("okr_complete") or {}
    check("C3 a complete live read is kept as okr_complete too: list, ts, every row with "
          "the write over it",
          sorted(oc) == ["list_id", "rows", "ts"] and oc["list_id"] == PID
          and isinstance(oc["ts"], int)
          and sorted(t["id"] for t in oc["rows"]) == sorted(t["id"] for t in rc["rows"])
          and cached("okr_complete", "O1")["startDate"] == body["startDate"]
          and cached("okr_complete", "K4")["status"] == 2, oc and sorted(oc))
    check("the write folds back into the snap (a second mirror builds on it)",
          okr.index(snap.items)["O1"].start == d(9, 19))

    api, v2 = world()
    api.store["K2"].update({"startDate": "2026-10-05T08:00:00+0000",
                            "dueDate": "2026-10-14T09:00:00+0000",
                            "timeZone": "Europe/Berlin", "isAllDay": False})
    snap = snapshot(api, v2)
    k2 = okr.index(snap.items)["K2"]
    check("fixture: a TIMED K2 on Oct 5 - Oct 14", (k2.start, k2.end) == (d(10, 5), d(10, 14)),
          (k2.start, k2.end))
    res = ow.apply_spans(snap, [("K2", d(10, 5), d(10, 14))], api, v2)
    body = v2.batches[0][0] if v2.batches else {}
    check("a timed item on the SAME span is still written, all-day (the rule)",
          res.written == ["K2"] and body.get("isAllDay") is True
          and okr.span(body) == (d(10, 5), d(10, 14)), (res, body.get("dueDate")))
    check("... in the exclusive midnight form, not the shifted timed stamp",
          body.get("dueDate") == okr.span_raw(d(10, 5), d(10, 14), "Europe/Berlin",
                                              like="2026-10-05T08:00:00+0000")[1],
          body.get("dueDate"))

    api, v2 = world(completed=False)
    snap = snapshot(api, v2)
    r = refused(ow.apply_spans, snap, [("K2", d(10, 6), d(10, 16))], api, v2)
    check("W8 apply_spans refuses a live read without every completed KR, whoever calls",
          r and "Not written" in r and wrote_nothing(api, v2), r)
    api, v2 = boom_world()
    snap = snapshot(api, v2)
    r = refused(ow.apply_spans, snap, [("K2", d(10, 6), d(10, 16))], api, v2)
    check("... and a cache read", snap.source == "cache" and r and "unreachable" in r
          and wrote_nothing(api, v2), r)
    r = refused(ow.apply_spans, snap, [], api, v2)
    check("... even with nothing to write", r is not None, r)

    api, v2 = world()
    snap = snapshot(api, v2)
    pairs = [("K2", d(10, 5), d(10, 20)), ("K2", d(10, 6), d(10, 16)),
             ("K1", d(9, 19), d(10, 4)), ("K4", d(1, 1), d(1, 2))]
    res = ow.apply_spans(snap, pairs, api, v2)
    wrote = {b["id"]: b for b in v2.batches[0]}
    check("the LATER pair for an id wins (moves, then heals)",
          okr.span(wrote["K2"]) == (d(10, 6), d(10, 16)), okr.span(wrote["K2"]))
    check("an all-day item already on that span is not written", "K1" not in wrote)
    check("history (a done KR) never moves", "K4" not in wrote and res.written == ["K2"])

    api, v2 = world(token="")
    snap = snapshot(api, FakeV2(api))          # read complete, write tokenless
    res = ow.apply_spans(snap, [("K2", d(10, 6), d(10, 16))], api, v2)
    up = api.of("update_task")
    check("no v2 token: v1, one full object, TASK id first then list id (trap 2)",
          len(up) == 1 and up[0][1] == "K2" and up[0][2] == PID, up)
    check("v1 fields carry isAllDay True, so v1 never guesses it (trap 3)",
          up and up[0][3].get("isAllDay") is True and "startDate" in up[0][3], up)
    check("v1 posts over the stored raw (current=)", up and up[0][4]["etag"] == "e0")

    api, v2 = world(ok=False)
    snap = snapshot(api, v2)
    res = ow.apply_spans(snap, [("K2", d(10, 6), d(10, 16))], api, v2)
    check("a refused v2 batch falls back to v1", len(v2.batches) == 1
          and len(api.of("update_task")) == 1 and res.written == ["K2"])

    api, v2 = world(ok=False)
    snap = snapshot(api, v2)
    api.fail_update = True
    before = cached("all_tasks", "K2")["startDate"]
    res = ow.apply_spans(snap, [("K2", d(10, 6), d(10, 16))], api, v2)
    check("v1 failing too: reported failed, not written", res.failed == ["K2"] and not res.written)
    check("a failed write leaves the cache alone", cached("all_tasks", "K2")["startDate"] == before)

    api, v2 = world()
    many = [D(f"X{i}", f"🔑 KR • x{i} - TA", d(11, 1), d(11, 2), "O1") for i in range(120)]
    snap = okr.Snapshot(okr.items_from(many), "live", "t", PID, "", True)
    res = ow.apply_spans(snap, [(f"X{i}", d(11, 3), d(11, 4)) for i in range(120)], api, v2)
    check("batches of 50: 120 items = 3 requests", [len(b) for b in v2.batches] == [50, 50, 20],
          [len(b) for b in v2.batches])

    # ── 2. schedule ──────────────────────────────────────────────────────────
    print("schedule")
    api, v2 = world()
    msg = ow.schedule({"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    wrote = {b["id"]: b for b in v2.batches[0]}
    check("extend a KR +3: the KR and its stale O are written, nothing else",
          set(wrote) == {"K2", "O1"}, set(wrote))
    check("the KR lands on Oct 5 - Oct 17", okr.span(wrote["K2"]) == (d(10, 5), d(10, 17)))
    check("its O heals onto Sep 19 - Oct 17", okr.span(wrote["O1"]) == (d(9, 19), d(10, 17)),
          okr.span(wrote["O1"]))
    check("another lane (O2, no shared Y) stays put", "O2" not in wrote and "K6" not in wrote)
    check("toast: name, new span, the heal", msg == "📅 Hub → Oct 5 - Oct 17 · 1 healed", msg)

    api, v2 = world()
    msg = ow.schedule({"id": "O1", "action": "extend", "arg": "+2"}, api, v2, today=TODAY)
    wrote = {b["id"]: b for b in v2.batches[0]}
    check("extend an O: handed to its LAST open KR", okr.span(wrote["K2"]) == (d(10, 5), d(10, 16)))
    check("extend an O: the O ends on the asked day", okr.span(wrote["O1"]) == (d(9, 19), d(10, 16)))
    check("toast names the KR it went through", msg == "📅 TickAL → Sep 19 - Oct 16 · via Hub", msg)

    api, v2 = world()
    snap0 = snapshot(api, v2)
    plan = okr.schedule_plan(snap0.items, "O1", "date", d(10, 1), TODAY)
    msg = ow.schedule({"id": "O1", "action": "date", "arg": "2026-10-01"}, api, v2, today=TODAY)
    wrote = {b["id"]: okr.span(b) for b in v2.batches[0]}
    want = {}
    for i, s, e in plan[0] + plan[1]:
        want[i] = (s, e)
    by0 = okr.index(snap0.items)
    want = {i: se for i, se in want.items()
            if not ((by0[i].start, by0[i].end) == se and by0[i].raw.get("isAllDay") is True)}
    check("pick a date on an O: exactly okr.schedule_plan's moves + heals are written",
          wrote == want, (wrote, want))
    check("pick a date: the toast counts what moved along", "moved along" in msg, msg)

    api, v2 = world()
    msg = ow.schedule({"id": "K3", "action": "tomorrow", "arg": None}, api, v2, today=TODAY)
    wrote = {b["id"]: b for b in v2.batches[0]}
    check("tomorrow on an undated KR: one day, all-day exclusive form",
          okr.span(wrote["K3"]) == (d(9, 19), d(9, 19)) and wrote["K3"]["isAllDay"] is True,
          okr.span(wrote["K3"]))

    api, v2 = world()
    r = refused(ow.schedule, {"id": "K4", "action": "extend", "arg": 2}, api, v2, today=TODAY)
    check("a done KR: okr's own refusal, toasted as is", r and "closed" in r, r)
    check("... and nothing written", not v2.batches and not api.of("update_task"))
    r = refused(ow.schedule, {"id": "K3", "action": "extend", "arg": 2}, api, v2, today=TODAY)
    check("extend on an undated KR is refused", r and "no dates" in r, r)
    r = refused(ow.schedule, {"id": "nope", "action": "extend", "arg": 2}, api, v2, today=TODAY)
    check("an id gone from the list is refused", r and "Not in the OKR list" in r, r)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": "abc"}, api, v2, today=TODAY)
    check("extend by a non-number is refused", r and "how many days" in r, r)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": True}, api, v2, today=TODAY)
    check("extend by a bool is refused", r is not None, r)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 99999}, api, v2, today=TODAY)
    check("extend by 99999 days is refused", r is not None, r)
    r = refused(ow.schedule, {"id": "K2", "action": "date", "arg": "2026-13-40"}, api, v2, today=TODAY)
    check("a bad date is refused", r and "Not a date" in r, r)
    r = refused(ow.schedule, {"id": "K2", "action": "later"}, api, v2, today=TODAY)
    check("an unknown action is refused", r == "📅 Nothing to schedule", r)
    check("refusals wrote nothing", not v2.batches and not api.of("update_task"))

    api, v2 = world(completed=False)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("WRITER RULE: completed KRs unreadable = refused", r and "Not written" in r, r)
    check("... nothing written", not v2.batches and not api.of("update_task"))
    api, v2 = world(token="")
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("no v2 token: the toast names the Attachment Login", r and "Attachment Login" in r, r)

    # B2 the rate limit (300 / 5 min) says to WAIT. It reaches a toast by v1
    # only: api.RateLimitError is the v1 client's, and api_v2.
    # project_completed never raises - a v2 limit answers None, which reads
    # "completed KRs unreadable" like any other v2 blip.
    from api import RateLimitError
    RATE = "🥅 Not written · TickTick rate limit · try again in a minute"

    class RateAPI(FakeAPI):
        def get_project_data(self, pid):
            self.calls.append(("get_project_data", pid))
            raise RateLimitError("exceed_query_limit")

    o, dn = fixture()
    seed_cache(o, dn)
    api = RateAPI(o, dn)
    v2 = FakeV2(api)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("B2 v1 rate-limited (only the cache answered): 'rate limit · try again in a "
          "minute'", r == RATE and ow.RATE_LIMITED == RATE and wrote_nothing(api, v2), r)
    r = refused(ow.add_items, {"kind": "O", "names": ["x"],
                               "link": {"to": "list", "pid": "3" * 24}}, api, v2)
    check("B2 ... a linked add says the same", r == RATE and wrote_nothing(api, v2), r)
    r = refused(ow.add_items, {"kind": "O", "names": ["x"]}, api, v2)
    check("B2 ... and a typed one, never 'unreachable'", r == RATE and wrote_nothing(api, v2), r)
    MEM.clear()
    r = refused(ow.retag, {"id": "K1", "tag": "1️⃣work"}, api, FakeV2(api))
    check("B2 v1 rate-limited with no cache to fall back on (OkrLoadError): the same",
          r == RATE, r)

    class LimitedV2(FakeV2):
        """What a v2 rate limit really looks like: project_completed None."""
        def project_completed(self, pid, days=120, limit=500):
            return None

    api, _v = world()
    v2 = LimitedV2(api)
    r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("B2 v2 limited (project_completed None, it never raises): 'completed KRs "
          "unreadable', not the rate-limit wording",
          r == "🥅 Not written · completed KRs unreadable right now · try again"
          and wrote_nothing(api, v2), r)

    api, v2 = world()
    import fcntl
    with open(ow.LOCK_FILE, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
        fcntl.flock(held, fcntl.LOCK_UN)
    check("the lock held elsewhere: waits LOCK_WAIT, then refuses busy", r and "Busy" in r, r)
    check("... and read nothing", not api.of("get_project_data"))

    api, v2 = world()
    os.environ["okr_list_id"] = ""
    try:
        r = refused(ow.schedule, {"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    finally:
        os.environ["okr_list_id"] = PID
    check("OKRs off (blank list id): refused, pointing at Settings", r and "Settings" in r, r)

    api, v2 = world()
    r = refused(ow.schedule, {"id": "K3", "action": "date", "arg": "2026-09-17"}, api, v2,
                today=TODAY)
    check("W2 a picked day before today is refused, before any read",
          r == "📅 That day is gone · today or later" and not api.calls, r)
    msg = ow.schedule({"id": "K3", "action": "date", "arg": "2026-09-18"}, api, v2, today=TODAY)
    check("... today itself is fine", msg.startswith("📅 Eagle → Sep 18"), msg)

    api, v2 = world()
    r = refused(ow.schedule, {"id": "K5", "action": "extend", "arg": 2}, api, v2,
                today=d(9, 25))
    check("W2 an extend whose new end is before today is refused",
          r == "📅 That end is gone · today or later" and wrote_nothing(api, v2), r)
    msg = ow.schedule({"id": "K5", "action": "extend", "arg": 2}, api, v2, today=d(9, 23))
    check("... ending ON today is fine", msg.startswith("📅 Side quest → Sep 20 - Sep 23"), msg)

    api, v2 = world()
    r = refused(ow.schedule, {"id": "K5", "action": "extend", "arg": -5}, api, v2, today=TODAY)
    check("W2 a pull-in longer than the item: 'bad span' in words",
          r == "📅 Longer than the item · pick a date" and wrote_nothing(api, v2), r)
    r = refused(ow.schedule, {"id": "O1", "action": "extend", "arg": -40}, api, v2, today=TODAY)
    check("... handed down from an O too", r == "📅 Longer than the item · pick a date", r)

    api, v2 = world(ok=False)
    api.fail_update = True
    msg = ow.schedule({"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("W10 nothing written: the toast says where it STAYS",
          msg == "📅 Not written · Hub stays on Oct 5 - Oct 14", msg)

    api, v2 = world(ok=False)
    api.fail_ids = {"K2"}
    msg = ow.schedule({"id": "K2", "action": "extend", "arg": 3}, api, v2, today=TODAY)
    check("the item itself not written (its heal was): never '→ <new span>'",
          msg == "📅 Not written · Hub stays on Oct 5 - Oct 14 · ⚠️ 1 not written, 1 were", msg)

    # the "stays on" span is the HEALED one - the span every screen shows -
    # never the stale stored one (O1: stored Sep 29 - Oct 24, healed Sep 19 - Oct 14)
    api, v2 = world(ok=False)
    api.fail_update = True
    msg = ow.schedule({"id": "O1", "action": "extend", "arg": 2}, api, v2, today=TODAY)
    check("a stale-stored O not written: it stays on its HEALED span",
          msg == "📅 Not written · TickAL stays on Sep 19 - Oct 14", msg)
    api, v2 = world(ok=False)
    api.fail_ids = {"K2"}
    msg = ow.schedule({"id": "O1", "action": "extend", "arg": 2}, api, v2, today=TODAY)
    check("an O extend whose carrier KR failed: never '→ <new span>'",
          msg.startswith("📅 Not written · TickAL stays on Sep 19 - Oct 14"), msg)
    api, v2 = world()
    r = refused(ow.schedule, {"id": "O1", "action": "extend", "arg": 2}, api, v2,
                today=d(10, 20))
    check("W2 the end-before-today test reads the O's HEALED end (Oct 14 + 2 < Oct 20)",
          r == "📅 That end is gone · today or later" and wrote_nothing(api, v2), r)

    # ── 3. add_krs ───────────────────────────────────────────────────────────
    print("add_krs")
    api, v2 = world()
    msg = ow.add_krs({"oid": "O1", "names": ["Alpha", " Beta  one ", "", "Gamma"],
                      "code": None}, api, v2)
    made = api.of("create_task")
    check("three KRs, the O's code, empty segments dropped",
          [c[1] for c in made] == ["🔑 KR • Alpha - TA", "🔑 KR • Beta one - TA",
                                   "🔑 KR • Gamma - TA"], made)
    check("under the O, in the OKR list, tagged like the O",
          all(c[2] == PID and c[3] == "O1" and c[4] == ["💼tickal"] for c in made), made)
    check("the O already has a code: its description is not touched",
          not api.of("update_task"))
    order = v2.batches[-1]
    check("typed order restored: ascending sortOrder Alpha, Beta, Gamma",
          [b["title"] for b in sorted(order, key=lambda b: b["sortOrder"])]
          == [c[1] for c in made], order)
    check("the order bodies restate the parent (the response said null)",
          all(b["parentId"] == "O1" and b["projectId"] == PID for b in order))
    check("W4 ... and carry the O's zone (blank on the O = Europe/Berlin), in that ONE batch",
          len(v2.batches) == 1 and all(b.get("timeZone") == "Europe/Berlin" for b in order), order)
    check("W4 the KRs read back in the zone",
          all(api.store[b["id"]].get("timeZone") == "Europe/Berlin" for b in order))
    for key in ("all_tasks", f"project_data_{PID}", "okr_rows"):
        rows = [t for t in (MEM[key] if isinstance(MEM[key], list) else
                            MEM[key].get("tasks") or MEM[key].get("rows"))
                if t.get("id", "").startswith("new")]
        check(f"cache {key}: the new KRs with their parent", len(rows) == 3
              and all(t["parentId"] == "O1" for t in rows), rows)
    check("cache all_tasks: the list alias rides along",
          cached("all_tasks", "new1")["_projectId"] == PID)
    check("toast", msg == "🔑 3 KRs under TickAL · code TA", msg)
    kids = [i for i in okr.items_from(list(api.store.values())) if i.parent == "O1"
            and i.id.startswith("new")]
    check("the new KRs read back settled: name + code",
          sorted((k.name, k.code) for k in kids) == [("Alpha", "TA"), ("Beta one", "TA"),
                                                     ("Gamma", "TA")], kids)

    api, v2 = world()
    msg = ow.add_krs({"oid": "O2", "names": ["Zapier"]}, api, v2)
    up = api.of("update_task")
    check("an O with no code: proposed from its name, written as its 🏷️ line",
          len(up) == 1 and up[0][1] == "O2" and up[0][3] == {"content": "🏷️ W"}, up)
    check("... on a LIVE GET of the O first", ("get_task", PID, "O2") in api.calls)
    check("... and the KR carries it", api.of("create_task")[0][1] == "🔑 KR • Zapier - W")
    o2 = okr.index(okr.items_from(list(api.store.values())))["O2"]
    check("code_of now reads the 🏷️ line", okr.code_of(o2, []) == "W")
    check("cache: the O's description patched", cached("all_tasks", "O2")["content"] == "🏷️ W")

    api, v2 = world()
    msg = ow.add_krs({"oid": "O2", "names": ["Zapier"], "code": "XY"}, api, v2)
    check("a given code on an O without one: written there too",
          api.of("update_task")[0][3] == {"content": "🏷️ XY"})
    check("... and on the KR", api.of("create_task")[0][1] == "🔑 KR • Zapier - XY")

    api, v2 = world()
    ow.add_krs({"oid": "O1", "names": ["Zapier"], "code": "XY"}, api, v2)
    check("a given code under an O WITH one: the KRs take it, the O keeps its own",
          not api.of("update_task") and api.of("create_task")[0][1] == "🔑 KR • Zapier - XY")

    api, v2 = world()
    r = refused(ow.add_krs, {"oid": "O1", "names": ["a"], "code": "xy"}, api, v2)
    check("a code that would not read back is refused before any read", r and "xy" in r
          and not api.calls, r)
    r = refused(ow.add_krs, {"oid": "K1", "names": ["a"]}, api, v2)
    check("KRs only under an O", r and "not one" in r, r)
    r = refused(ow.add_krs, {"oid": "O3", "names": ["a"]}, api, v2)
    check("a closed O is refused", r and "closed" in r, r)
    r = refused(ow.add_krs, {"oid": "O1", "names": ["", "  "]}, api, v2)
    check("no names is refused", r == "🔑 No KR names", r)
    check("refusals created nothing", not api.of("create_task"))

    api, v2 = world()
    msg = ow.add_krs({"oid": "O4", "names": ["Trip - USA", "Call Anna - Monday"]}, api, v2)
    made = api.of("create_task")
    check("no code at all: an all-caps tail would read as a code, skipped (trap 13)",
          [c[1] for c in made] == ["🔑 KR • Call Anna - Monday"], made)
    check("... and the toast says so", "skipped 'Trip - USA'" in msg and "no code" in msg, msg)
    check("an O with no letters proposes no code: nothing written to it",
          not api.of("update_task"))

    api, v2 = world(completed=False)
    msg = ow.add_krs({"oid": "O1", "names": ["Delta"]}, api, v2)
    check("adding KRs needs a live read, not the completed feed",
          msg.startswith("🔑 1 KR under TickAL"), msg)

    api, v2 = world()
    api.store["O1"]["timeZone"] = "America/New_York"
    ow.add_krs({"oid": "O1", "names": ["Solo"]}, api, v2)
    check("W4 one KR: no order to fix, the zone still lands - ONE body, the O's zone",
          [[(b["id"], b.get("timeZone"), b["parentId"]) for b in bt] for bt in v2.batches]
          == [[("new1", "America/New_York", "O1")]] and not api.of("update_task"),
          v2.batches)
    check("W4 the cache carries the zone", cached("all_tasks", "new1").get("timeZone")
          == "America/New_York" and cached("okr_rows", "new1").get("timeZone") == "America/New_York")

    api, v2 = world()
    api.create_tz = "Europe/Berlin"
    ow.add_krs({"oid": "O1", "names": ["Solo"]}, api, v2)
    check("W4 one KR already in the O's zone: nothing posted after the create",
          not v2.batches and not api.of("update_task"), (v2.batches, api.of("update_task")))
    check("B8 ... and the cache still carries its parent (the response said null)",
          all((cached(k, "new1") or {}).get("parentId") == "O1"
              for k in ("all_tasks", f"project_data_{PID}", "okr_rows")),
          [cached(k, "new1") for k in ("all_tasks", "okr_rows")])

    # B1 the server TIED the new siblings' sortOrder: dealt back out they
    # would still tie, so strictly increasing ones are made, below the rest.
    # The O's KRs carry DISTINCT orders (the fixture's are all 0, where
    # "below every sibling" would only ever test "below 0")
    def spread(api, parent="O1", base=-3 * 2 ** 29, step=2 ** 29):
        """Distinct sortOrders on `parent`'s children, open and done; -> them."""
        kids = [t for t in list(api.store.values()) + list(api.done.values())
                if t.get("parentId") == parent]
        for i, t in enumerate(sorted(kids, key=lambda t: t["id"])):
            t["sortOrder"] = base + i * step
        return [t["sortOrder"] for t in kids]

    api, v2 = world()
    sibs = spread(api)
    api.create_order = 5
    ow.add_krs({"oid": "O1", "names": ["Alpha", "Beta", "Gamma"]}, api, v2)
    got = {b["title"]: b["sortOrder"] for b in v2.batches[-1]}
    seq = [got.get(f"🔑 KR • {n} - TA") for n in ("Alpha", "Beta", "Gamma")]
    check("B1 fixture: the O's siblings carry distinct orders, some below 0",
          len(set(sibs)) == len(sibs) >= 6 and min(sibs) < 0, sibs)
    check("B1 tied orders: strictly increasing in TYPED order",
          None not in seq and seq[0] < seq[1] < seq[2], got)
    check("B1 ... all below every existing sibling of the O: max(new) < min(existing)",
          None not in seq and max(seq) < min(sibs), (seq, min(sibs)))
    check("B1 ... a step apart, ORDER_STEP", None not in seq
          and seq[1] - seq[0] == seq[2] - seq[1] == ow.ORDER_STEP, seq)
    check("B1 ... and they read back in that order",
          [api.store[b["id"]]["title"] for b in sorted(v2.batches[-1],
                                                       key=lambda b: b["sortOrder"])]
          == ["🔑 KR • Alpha - TA", "🔑 KR • Beta - TA", "🔑 KR • Gamma - TA"])
    api, v2 = world()
    api.create_order = 7
    ow.add_krs({"oid": "O4", "names": ["Alpha", "Beta"]}, api, v2)
    got = [b["sortOrder"] for b in sorted(v2.batches[-1], key=lambda b: b["title"])]
    check("B1 tied under an O with no KRs: the block ENDS on the server's value",
          got == [7 - ow.ORDER_STEP, 7], got)
    api, v2 = world(token="")
    api.create_order = 0
    ow.add_krs({"oid": "O1", "names": ["Alpha", "Beta"]}, api, v2)
    up = [c for c in api.of("update_task") if c[1].startswith("new")]
    check("B1 tied, no v2 token: v1 carries the synthesized order too",
          [c[1] for c in up] == ["new1", "new2"]
          and up[0][3]["sortOrder"] < up[1][3]["sortOrder"] < 0, up)
    api, v2 = world()
    sibs = spread(api)
    api.create_orders = [5, 5, 3]
    ow.add_krs({"oid": "O1", "names": ["Alpha", "Beta", "Gamma"]}, api, v2)
    got = {b["title"]: b["sortOrder"] for b in v2.batches[-1]}
    seq = [got.get(f"🔑 KR • {n} - TA") for n in ("Alpha", "Beta", "Gamma")]
    check("B1 a PARTIAL tie [5, 5, 3] is a tie: strictly increasing in TYPED order, "
          "a step apart", None not in seq and seq[0] < seq[1] < seq[2]
          and seq[1] - seq[0] == seq[2] - seq[1] == ow.ORDER_STEP, got)
    check("B1 ... and below every existing sibling", None not in seq
          and max(seq) < min(sibs), (seq, min(sibs)))
    check("B1 ... read back in that order",
          [api.store[b["id"]]["title"] for b in sorted(v2.batches[-1],
                                                       key=lambda b: b["sortOrder"])]
          == ["🔑 KR • Alpha - TA", "🔑 KR • Beta - TA", "🔑 KR • Gamma - TA"])
    check("B1 _typed_orders: [5, 5, 3] with no siblings ends on the server's lowest",
          ow._typed_orders([{"sortOrder": 5}, {"sortOrder": 5}, {"sortOrder": 3}], [])
          == [3 - 2 * ow.ORDER_STEP, 3 - ow.ORDER_STEP, 3])
    check("B1 distinct orders are the server's own, dealt out ascending (no synthesis)",
          ow._typed_orders([{"sortOrder": 900}, {"sortOrder": 800}], [0]) == [800, 900])
    check("B1 no sortOrder at all is a tie too",
          ow._typed_orders([{}, {}], []) == [-ow.ORDER_STEP, 0])

    api, v2 = world()
    r = refused(ow.add_krs, {"oid": "O3", "names": ["a"]}, api, v2)
    check("B4 the alias's closed-O refusal speaks 🔑", r == "🔑 Other things is closed · "
          "reopen it first", r)


    api, v2 = world(token="")
    ow.add_krs({"oid": "O1", "names": ["Alpha", "Beta"]}, api, v2)
    up = [c for c in api.of("update_task") if c[1].startswith("new")]
    check("W4 no v2 token: v1, one object per KR, the zone + the parent + typed order",
          [(c[1], c[3].get("timeZone"), c[3].get("parentId")) for c in up]
          == [("new1", "Europe/Berlin", "O1"), ("new2", "Europe/Berlin", "O1")]
          and up[0][3].get("sortOrder", 0) < up[1][3].get("sortOrder", 0), up)

    api, v2 = boom_world()
    r = refused(ow.add_krs, {"oid": "O1", "names": ["Delta"]}, api, v2)
    check("W11 v1 down (only the cache answered): add_krs refused, nothing created",
          r and "unreachable" in r and wrote_nothing(api, v2), r)

    # ── 3b. add_items (phase 3: Y / O / KR, typed or imported) ───────────────
    print("add_items")
    P2, T2 = "b" * 24, "c" * 24
    L = "d" * 24                       # "Workflows" in the projects cache
    E, F = "e" * 24, "f" * 24          # what K9 already links (LINK_T)

    def put(api, *rows, done=False):
        for r in rows:
            (api.done if done else api.store)[r["id"]] = cp(r)

    def years(api):
        put(api, D("Y1", "🏔️ Y • Productivity System", tags=["1️⃣work"],
                   timeZone="America/New_York"))
        put(api, D("Y2", "🏔️ Y • Old year", status=2), done=True)

    api, v2 = world()
    out = ow.add_items({"kind": "O", "parent": None, "names": ["Travel plans"],
                        "code": None, "link": None, "then": "tag", "back": "ctx:okr"}, api, v2)
    made = api.of("create_task")
    check("a root O, text only: its prefix, NO suffix, no parent, no tags",
          [(c[1], c[2], c[3], c[4]) for c in made]
          == [("🥅 O • Travel plans", PID, None, None)], made)
    check("... its OWN code proposed and written as ITS 🏷️ line at the create",
          made[0][5] == "🏷️ TP", made)
    check("... read back: an O named Travel plans, code TP",
          (lambda it: (it.kind, it.name, okr.code_of(it, [])))(
              okr.from_task(api.store["new1"])) == ("O", "Travel plans", "TP"))
    check("the toast", out.msg == "🥅 Added · 🥅 Travel plans · code TP", out.msg)
    check("then:tag + one O = its tag picker", out.reopen == "ctx:okrtag:new1"
          and out.ids == ["new1"], out)
    body = v2.batches[-1][0] if v2.batches else {}
    check("the zone lands (Europe/Berlin, no parent to take one from), one body",
          len(v2.batches) == 1 and body.get("timeZone") == "Europe/Berlin", v2.batches)
    check("... and a ROOT body states no parentId at all", "parentId" not in body, body)
    check("nothing else written (no heal: undated)", not api.of("update_task"))
    for key in ("all_tasks", f"project_data_{PID}", "okr_rows"):
        c = cached(key, "new1")
        check(f"cache {key}: the new O, root, with its 🏷️ line (the tag screen finds it)",
              c and c.get("parentId") is None and c.get("content") == "🏷️ TP", c)

    api, v2 = world()
    years(api)
    out = ow.add_items({"kind": "O", "parent": "Y1", "names": ["Health plan"],
                        "then": "tag", "back": "ctx:okr:y:Y1"}, api, v2)
    made = api.of("create_task")
    check("an O under an open Y: parented, inherits NO tag (the picker follows)",
          [(c[1], c[3], c[4], c[5]) for c in made]
          == [("🥅 O • Health plan", "Y1", None, "🏷️ HP")], made)
    check("... the Y's zone, the parent restated", [(b.get("timeZone"), b.get("parentId"))
          for b in v2.batches[-1]] == [("America/New_York", "Y1")], v2.batches)
    check("... toast names the Y", out.msg == "🥅 Added · 🥅 Health plan under "
          "🏔️ Productivity System · code HP", out.msg)
    check("... and goes to its tag picker", out.reopen == "ctx:okrtag:new1", out)
    check("cache okr_rows: under Y1", cached("okr_rows", "new1")["parentId"] == "Y1")

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["Alpha", "Beta two"], "then": "tag"}, api, v2)
    made = api.of("create_task")
    check("pipe = sibling O's, each with its own code",
          [(c[1], c[5]) for c in made] == [("🥅 O • Alpha", "🏷️ A"),
                                           ("🥅 O • Beta two", "🏷️ BT")], made)
    order = v2.batches[-1]
    check("... in TYPED order (ascending sortOrder Alpha, Beta two)",
          [b["title"] for b in sorted(order, key=lambda b: b["sortOrder"])]
          == ["🥅 O • Alpha", "🥅 O • Beta two"], order)
    check("... two made: no tag picker (it is for ONE item), the back instead",
          out.reopen is None and out.ids == ["new1", "new2"], out)
    check("... toast", out.msg == "🥅 Added · 2 🥅 objectives · codes A, BT", out.msg)

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["Travel plans"], "code": "XY"}, api, v2)
    check("a given code on a new O is its 🏷️ line", api.of("create_task")[0][5] == "🏷️ XY"
          and out.msg.endswith("· code XY"), (api.of("create_task"), out.msg))
    check("no then: the back (reopen None)", out.reopen is None)

    api, v2 = world()
    out = ow.add_items({"kind": "Y", "names": ["Health"], "code": "XY", "then": "tag"},
                       api, v2)
    made = api.of("create_task")
    check("a Y: its prefix, no code (a given one ignored), no description, no parent",
          [(c[1], c[3], c[4], c[5]) for c in made] == [("🏔️ Y • Health", None, None, None)],
          made)
    check("... toast + tag picker", out.msg == "🥅 Added · 🏔️ Health"
          and out.reopen == "ctx:okrtag:new1", out)

    api, v2 = world()
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Goals wf"],
                        "link": {"to": "task", "pid": P2, "tid": T2}, "then": "tag"}, api, v2)
    made = api.of("create_task")
    url = f"https://ticktick.com/webapp/#p/{P2}/tasks/{T2}"
    check("an imported KR: prefix + code OUTSIDE the link, the O's tags",
          [(c[1], c[3], c[4], c[5]) for c in made]
          == [(f"🔑 KR • [Goals wf]({url}) - TA", "O1", ["💼tickal"], None)], made)
    check("... reads back", okr.parse_title(made[0][1]) == ("KR", "Goals wf", url, "TA"))
    check("B4 ... a KR never goes to the tag picker (it inherits); an IMPORT toasts "
          "like the other levels", out.reopen is None
          and out.msg == "🥅 Added · 🔑 Goals wf under TickAL · code TA", out)
    check("... the target is never touched", not any(c[1] == T2 for c in api.of("update_task")))

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["Workflows 2"],
                        "link": {"to": "list", "pid": "5" * 24, "tid": "-"}}, api, v2)
    t1 = api.of("create_task")[0][1]
    lurl = f"ticktick:///webapp/#p/{'5' * 24}/tasks"
    check("an O imported from a list: the list link, no suffix, its code in the description",
          t1 == f"🥅 O • [Workflows 2]({lurl})" and api.of("create_task")[0][5] == "🏷️ W2"
          and okr.parse_title(t1) == ("O", "Workflows 2", lurl, None), (t1, api.of("create_task")))

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["Trip - USA", "Plan - Monday"]}, api, v2)
    check("an O whose name ends in a code-like word would lose it: skipped, both",
          not api.of("create_task") and out.msg == "🥅 No objective added · skipped "
          "'Trip - USA', 'Plan - Monday' (reads as a code)", out.msg)
    check("... nothing made: the back", out.reopen is None and out.ids == [])

    api, v2 = world(completed=False)
    out = ow.add_items({"kind": "O", "names": ["Delta"]}, api, v2)
    check("adding needs a live read, not the completed feed", out.ids == ["new1"], out)

    # B8 the survivors
    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": "Solo trip"}, api, v2)
    check("B8 names as a bare string: one item of that name",
          [c[1] for c in api.of("create_task")] == ["🥅 O • Solo trip"] and out.ids == ["new1"],
          api.of("create_task"))
    api, v2 = world()
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Plain"], "link": {}}, api, v2)
    check("B8 link {} = no link: a text-only KR, the typed toast",
          [c[1] for c in api.of("create_task")] == ["🔑 KR • Plain - TA"]
          and out.msg == "🔑 1 KR under TickAL · code TA", (api.of("create_task"), out.msg))
    api, v2 = world()
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Plain", "Two"]}, api, v2)
    check("B4 typed KRs through okr_add keep the count toast",
          out.msg == "🔑 2 KRs under TickAL · code TA", out.msg)
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["a"],
                               "link": {"to": "task", "pid": P2, "tid": "-"}}, api, v2)
    check("B8 a '-' tid on a task link is no task: refused, nothing read",
          r == "🔗 Nothing to link" and len(api.of("get_project_data")) == 1, r)

    api, v2 = world(token="")
    ow.add_items({"kind": "O", "names": ["Travel plans"]}, api, v2)
    up = [c for c in api.of("update_task") if c[1] == "new1"]
    check("B8 a root O with no v2 token: v1 posts the zone, and NO parentId anywhere "
          "(not in the fields, not in the current)",
          len(up) == 1 and up[0][3].get("timeZone") == "Europe/Berlin"
          and "parentId" not in up[0][3] and "parentId" not in up[0][4], up)

    api, v2 = world()
    put(api, D("O6", "🥅 O • Dropped", status=-1), D("Y6", "🏔️ Y • Shelved", status=-1),
        done=True)
    r = refused(ow.add_items, {"kind": "KR", "parent": "O6", "names": ["a"]}, api, v2)
    check("B8 a won't-do O is closed too: refused, in 🔑", r == "🔑 Dropped is closed · "
          "reopen it first", r)
    r = refused(ow.add_items, {"kind": "O", "parent": "Y6", "names": ["a"]}, api, v2)
    check("B8 ... and a won't-do Y for an O", r == "🏔️ Shelved is closed · reopen it first", r)
    check("... nothing created", not api.of("create_task"))

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["日本語 計画"]}, api, v2)
    made = api.of("create_task")
    check("B8 a caseless O name: no code (none would read back), its whole name kept",
          [(c[1], c[5]) for c in made] == [("🥅 O • 日本語 計画", None)]
          and out.msg == "🥅 Added · 🥅 日本語 計画 · no code", (made, out.msg))
    check("... and it reads back as that O", okr.parse_title(made[0][1])
          == ("O", "日本語 計画", None, None) if made else False)

    api, v2 = world()
    out = ow.add_items({"kind": "O", "names": ["Trip - USA", "Health"], "then": "tag"}, api, v2)
    check("B8 one name skipped, one made: the made one named, the skipped one too",
          [c[1] for c in api.of("create_task")] == ["🥅 O • Health"]
          and out.msg == "🥅 Added · 🥅 Health · code H · skipped 'Trip - USA' (reads as a code)",
          out.msg)
    check("... one Y / O made: its tag picker", out.reopen == "ctx:okrtag:new1"
          and out.ids == ["new1"], out)

    # M60 a caseless O name proposes no code that reads back: no code, and
    # EVERY KR is created (no name lost to a code, nothing stamped)
    api, v2 = world()
    api.store["OJ"] = D("OJ", "🥅 O • 日本語 計画")
    out = ow.add_items({"kind": "KR", "parent": "OJ", "names": ["調査", "Draft two"]}, api, v2)
    made = api.of("create_task")
    check("M60 a caseless-named O: no code, both KRs created",
          [c[1] for c in made] == ["🔑 KR • 調査", "🔑 KR • Draft two"]
          and out.ids == ["new1", "new2"], made)
    check("M60 ... nothing stamped on the O, the toast says no code",
          not [c for c in api.of("update_task") if c[1] == "OJ"]
          and out.msg == "🔑 2 KRs under 日本語 計画 · no code", out.msg)
    check("M60 kr_code agrees: (None, None)",
          ow.kr_code(okr.index(snapshot(api, v2).items)["OJ"], []) == (None, None))

    # C5 a skip is worded by its CAUSE: an O whose own 🏷️ line holds a code
    # a KR title cannot read back skips every name for the CODE, not the name
    api, v2 = world()
    api.store["O1"]["content"] = "notes\n🏷️ xy"
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Alpha", "Beta"]}, api, v2)
    BAD = "TickAL's code 'xy' does not read back · fix its 🏷️ line"
    check("C5 the O's code does not read back: nothing created, the code named, "
          "not 'reads as a code'",
          not api.of("create_task") and out.ids == []
          and out.msg == f"🔑 No KR added under TickAL · {BAD}", out.msg)
    check("C5 ... and nothing written to the O (its code is never rewritten)",
          not api.of("update_task") and not v2.batches)
    check("C5 code_problem words it, and passes a code that reads back",
          ow.code_problem("TickAL", "xy") == BAD and ow.code_problem("TickAL", "TA") is None
          and ow.code_problem("TickAL", None) is None)
    api, v2 = world()
    api.store["O1"]["content"] = "🏷️ xy"
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Goals wf"],
                        "link": {"to": "task", "pid": P2, "tid": T2}}, api, v2)
    check("C5 ... an import says it as the import's refusal",
          out.msg == f"🥅 Not added · 🔑 Goals wf under TickAL · {BAD}" and out.ids == [],
          out.msg)
    api, v2 = world()
    out = ow.add_items({"kind": "KR", "parent": "O4", "names": ["Trip - USA", "Fine"]}, api, v2)
    check("C5 a NAME that reads as a code keeps its own wording",
          out.msg == "🔑 1 KR under ✨ · no code · skipped 'Trip - USA' (reads as a code)",
          out.msg)

    # the import's create fails: the toast says the import did not land, and why
    api, v2 = world()
    api.fail_create = RuntimeError("HTTP 500")
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Goals wf"],
                        "link": {"to": "task", "pid": P2, "tid": T2}}, api, v2)
    check("an import whose create FAILED: 'Not added', named, a retry offered",
          out.msg == "🥅 Not added · 🔑 Goals wf under TickAL · TickTick refused the create "
          "· try again" and out.ids == [] and out.reopen is None, out)
    check("... nothing written after it", not api.of("update_task") and not v2.batches,
          api.of("update_task"))
    api, v2 = world()
    api.fail_create = RuntimeError("HTTP 500")
    out = ow.add_items({"kind": "KR", "parent": "O2", "names": ["Goals wf"],
                        "link": {"to": "task", "pid": P2, "tid": T2}}, api, v2)
    check("... under an O with NO code yet: the proposed code is not stamped on it, a KR "
          "that never landed names nothing", out.ids == [] and not api.of("update_task")
          and "🏷️" not in (api.store["O2"].get("content") or ""),
          (out, api.of("update_task")))
    api, v2 = world()
    out = ow.add_items({"kind": "KR", "parent": "O2", "names": ["Goals wf"],
                        "link": {"to": "task", "pid": P2, "tid": T2}}, api, v2)
    check("... and when it lands, the code is stamped after it (the control)",
          out.ids == ["new1"] and (api.store["O2"].get("content") or "").endswith(
              okr.code_line(ow.kr_code(okr.from_task(api.store["O2"]), [])[0])),
          (out, api.store["O2"].get("content")))
    api, v2 = world()
    years(api)
    api.fail_create = RateLimitError("exceed_query_limit")
    out = ow.add_items({"kind": "O", "parent": "Y1", "names": ["Proj"], "then": "tag",
                        "link": {"to": "list", "pid": "3" * 24}}, api, v2)
    check("... a rate-limited create says to wait, and no tag picker follows",
          out.msg == "🥅 Not added · 🥅 Proj under 🏔️ Productivity System · TickTick rate "
          "limit · try again in a minute" and out.reopen is None, out)
    api, v2 = world()
    api.fail_create = RuntimeError("HTTP 500")
    out = ow.add_items({"kind": "KR", "parent": "O1", "names": ["Alpha", "Beta"]}, api, v2)
    check("typed KRs whose creates fail keep the count toast and its warning",
          out.msg == "🔑 No KR added under TickAL · code TA · ⚠️ 2 not created", out.msg)

    # refusals before any read
    api, v2 = world()
    for spec, want, why in [
        ({"kind": "Z", "names": ["a"]}, "🥅 Add what? A 🏔️ Y, 🥅 O or 🔑 KR", "a bad kind"),
        ({"kind": "O", "names": ["", " "]}, "🥅 No names", "no names"),
        ({"kind": "KR", "parent": "O1", "names": []}, "🔑 No KR names", "no KR names"),
        ({"kind": "Y", "parent": "Y1", "names": ["a"]},
         "🏔️ A year objective is top level · no parent", "a Y with a parent"),
        ({"kind": "KR", "names": ["a"]}, "🔑 KRs go under a 🥅 O · pick one", "a KR with none"),
        ({"kind": "O", "names": ["a"], "code": "xy"},
         "🥅 Code 'xy' would not read back · one word, capital first", "a bad code"),
        ({"kind": "O", "names": ["a", "b"], "code": "XY"},
         "🥅 =XY codes ONE objective · add them one at a time", "one code, two O's"),
        ({"kind": "KR", "parent": "O1", "names": ["a", "b"],
          "link": {"to": "task", "pid": P2, "tid": T2}},
         "🔗 A link copies ONE item · one name, or no link", "a link with two names"),
        ({"kind": "KR", "parent": "O1", "names": ["a"], "link": {"to": "task", "pid": P2}},
         "🔗 Nothing to link", "a task link with no task"),
        ({"kind": "KR", "parent": "O1", "names": ["a"], "link": "junk"},
         "🔗 Nothing to link", "a link that is not a dict"),
        ({"kind": "KR", "parent": "O1", "names": ["a"],
          "link": {"to": "task", "pid": PID, "tid": "K2"}},
         "🥅 That is a planning copy · add the original", "a task in the plan list"),
        ({"kind": "O", "names": ["a"], "link": {"to": "list", "pid": PID}},
         "🥅 That is the plan list · add the real one", "the plan list itself"),
    ]:
        r = refused(ow.add_items, spec, api, v2)
        check(f"refused before any read: {why}", r == want and not api.calls, r)

    # refusals after the read
    api, v2 = world()
    years(api)
    for spec, want, why in [
        ({"kind": "KR", "parent": "O1", "names": ["a"],
          "link": {"to": "task", "pid": P2, "tid": "K2"}},
         "🥅 That is a planning copy · add the original", "a plan item under a stale list id"),
        ({"kind": "O", "parent": "O1", "names": ["a"]},
         "🥅 Objectives go under a 🏔️ Y · TickAL is not one", "an O under an O"),
        ({"kind": "O", "parent": "Y2", "names": ["a"]},
         "🏔️ Old year is closed · reopen it first", "an O under a closed Y"),
        ({"kind": "O", "parent": "nope", "names": ["a"]},
         "🥅 That year objective is gone from the list", "an O under nothing"),
        ({"kind": "KR", "parent": "Y1", "names": ["a"]},
         "🔑 KRs go under a 🥅 O · Productivity System is not one", "a KR under a Y"),
    ]:
        r = refused(ow.add_items, spec, api, v2)
        check(f"refused: {why}", r == want, r)
    check("... and nothing created", not api.of("create_task") and not v2.batches)

    # the dedupe
    api, v2 = world()
    e = refusal(ow.add_items, {"kind": "O", "names": ["Ship it"],
                               "link": {"to": "task", "pid": E, "tid": F},
                               "back": "ctx:okrimport:task:x:y"}, api, v2)
    check("DEDUPE: the task is already planned (K9): refused, named",
          e and str(e) == "🥅 Already in the plan · 🔑 Ship it", e)
    check("... and it lands on K9's screen (its O's), not the back",
          e and e.reopen == "ctx:okr:o:O1", e and e.reopen)
    check("... nothing created", not api.of("create_task"))
    e = refusal(ow.add_items, {"kind": "KR", "parent": "O2", "names": ["x"],
                               "link": {"to": "task", "pid": P2, "tid": F}}, api, v2)
    check("... by task id, whatever list the payload names (a task keeps its id)",
          e and e.reopen == "ctx:okr:o:O1", e)

    api, v2 = world()
    L2 = "5" * 24
    put(api, D("O5", f"🥅 O • [Old proj](ticktick:///webapp/#p/{L2}/tasks)", status=2),
        done=True)
    e = refusal(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("DEDUPE counts a CLOSED item too, and lands on its own screen (an O)",
          e and str(e) == "🥅 Already in the plan · 🥅 Old proj"
          and e.reopen == "ctx:okr:o:O5", e and (str(e), e.reopen))

    import areas
    real_cta = areas.CTA_LIST_ID
    CTA, CT, L3 = "7" * 24, "8" * 24, "6" * 24
    try:
        areas.CTA_LIST_ID = CTA
        cta_row = {"id": CT, "projectId": CTA, "status": 0,
                   "title": f"💼 P • [Proj](ticktick:///webapp/#p/{L3}/tasks) 🔗"}
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("O7", f"🥅 O • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "task", "pid": CTA, "tid": CT}}, api, v2)
        check("DEDUPE by project: the CTA task of a list an O already links",
              e and e.reopen == "ctx:okr:o:O7", e and (str(e), e.reopen))
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("O8", f"🥅 O • [Proj](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "list", "pid": L3}}, api, v2)
        check("... and the list whose CTA task an O already links",
              e and e.reopen == "ctx:okr:o:O8", e and (str(e), e.reopen))

        # B6 the list <-> CTA face is a GOAL's (Y / O); a KR plans exactly
        # what it links
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("KL", f"🔑 KR • [Proj list](ticktick:///webapp/#p/{L3}/tasks)", parent="O2"))
        out = attempt(ow.add_items, {"kind": "O", "names": ["Proj"],
                      "link": {"to": "task", "pid": CTA, "tid": CT}}, api, v2)
        check("B6 a KR on the LIST does not plan the project's CTA task", ids(out) == ["new1"],
              out)
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("KC", f"🔑 KR • [Proj](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})",
                   parent="O2"))
        out = attempt(ow.add_items, {"kind": "O", "names": ["Proj"],
                      "link": {"to": "list", "pid": L3}}, api, v2)
        check("B6 ... nor a KR on the CTA task the list", ids(out) == ["new1"], out)
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("KC", f"🔑 KR • [Proj](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})",
                   parent="O2"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "task", "pid": CTA, "tid": CT}}, api, v2)
        check("B6 ... the KR's own exact task IS planned", e and e.reopen == "ctx:okr:o:O2"
              and str(e) == "🥅 Already in the plan · 🔑 Proj", e and (str(e), e.reopen))
        # (the 📌CTA row is still cached from the world above: planned reads it)
        items = okr.items_from([
            D("KL", f"🔑 KR • [x](ticktick:///webapp/#p/{L3}/tasks)", parent="O2"),
            D("OC", f"🥅 O • [y](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})")])
        got = [getattr(ow.planned(items, *a), "id", None)
               for a in (("list", L3), ("task", CTA, CT))]
        check("B6 planned (pure): the list = the KR on it (exact); the CTA task = the O on "
              "it, never the KR through the list's face", got == ["KL", "OC"], got)
        check("B6 ... a KR alone never answers for the other face",
              ow.planned(okr.items_from([D("KL", f"🔑 KR • [x](ticktick:///webapp/#p/{L3}/tasks)",
                                           parent="O2")]), "task", CTA, CT) is None)

        # C7 a 🏔️ Y is a goal too: it plans the project through either face
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("YP", f"🏔️ Y • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "task", "pid": CTA, "tid": CT}}, api, v2)
        check("C7 a Y on the LIST plans the project's CTA task: refused, lands on the Y",
              e and str(e) == "🥅 Already in the plan · 🏔️ Proj" and e.reopen == "ctx:okr:y:YP",
              e and (str(e), e.reopen))
        api, v2 = world()
        MEM["all_tasks"].append(cp(cta_row))
        put(api, D("YC", f"🏔️ Y • [Proj](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})"))
        e = refusal(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["Proj"],
                                   "link": {"to": "list", "pid": L3}}, api, v2)
        check("C7 ... and a Y on the CTA task plans the list",
              e and e.reopen == "ctx:okr:y:YC", e and (str(e), e.reopen))

        # B8 the app backslash-escapes a saved title: the CTA still maps
        esc_row = {"id": CT, "projectId": CTA, "status": 0,
                   "title": f"💼 P • \\[Proj\\]\\(ticktick:///webapp/#p/{L3}/tasks\\) 🔗"}
        api, v2 = world()
        MEM["all_tasks"].append(cp(esc_row))
        put(api, D("O7", f"🥅 O • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "task", "pid": CTA, "tid": CT}}, api, v2)
        check("B8 an app-escaped 📌CTA title: the O on its list still plans the CTA task",
              e and e.reopen == "ctx:okr:o:O7", e and (str(e), e.reopen))
        api, v2 = world()
        MEM["all_tasks"].append(cp(esc_row))
        put(api, D("O8", f"🥅 O • [Proj](https://ticktick.com/webapp/#p/{CTA}/tasks/{CT})"))
        e = refusal(ow.add_items, {"kind": "O", "names": ["Proj"],
                                   "link": {"to": "list", "pid": L3}}, api, v2)
        check("B8 ... and the list, through its escaped CTA task",
              e and e.reopen == "ctx:okr:o:O8", e and (str(e), e.reopen))

        # B8 a task OUTSIDE the 📌CTA list that links the list is no CTA
        NT = "9" * 24
        not_cta = {"id": NT, "projectId": P2, "status": 0,
                   "title": f"💼 P • [Proj](ticktick:///webapp/#p/{L3}/tasks) 🔗"}
        api, v2 = world()
        MEM["all_tasks"].append(cp(not_cta))
        put(api, D("O9", f"🥅 O • [Notes](https://ticktick.com/webapp/#p/{P2}/tasks/{NT})"))
        out = attempt(ow.add_items, {"kind": "O", "names": ["Proj"],
                      "link": {"to": "list", "pid": L3}}, api, v2)
        check("B8 an O on a non-CTA task linking the list does not plan the list",
              ids(out) == ["new1"], out)
        api, v2 = world()
        MEM["all_tasks"].append(cp(not_cta))
        put(api, D("O7", f"🥅 O • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        out = attempt(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["Proj notes"],
                      "link": {"to": "task", "pid": P2, "tid": NT}}, api, v2)
        check("B8 ... nor does an O on the list plan that task", ids(out) == ["new1"], out)
    finally:
        areas.CTA_LIST_ID = real_cta

    # B3 a task that lives IN the plan list, by what it is
    api, v2 = world()
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["a"],
                               "link": {"to": "task", "pid": PID, "tid": "U1"}}, api, v2)
    check("B3 an unprefixed item of the plan list: wants its prefix, not a copy",
          r == "🥅 Already in the plan list · give it a 🏔️ / 🥅 / 🔑 prefix"
          and not api.calls, r)
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["a"],
                               "link": {"to": "task", "pid": P2, "tid": "U1"}}, api, v2)
    check("B3 ... under a stale list id too (found by its id in the live read)",
          r == "🥅 Already in the plan list · give it a 🏔️ / 🥅 / 🔑 prefix", r)
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["a"],
                               "link": {"to": "task", "pid": P2, "tid": "O2"}}, api, v2)
    check("B3 an item WITH a kind stays a planning copy", r == "🥅 That is a planning copy · "
          "add the original", r)
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["a"],
                               "link": {"to": "task", "pid": PID, "tid": "gone"}}, api, v2)
    check("B3 a plan-list task nobody knows: the planning-copy wording",
          r == "🥅 That is a planning copy · add the original", r)
    check("... nothing created", not api.of("create_task"))

    # B5 / C3 the dedupe must see CLOSED items; a read without them borrows
    # the last COMPLETE read (okr_complete - never okr_rows, which is the
    # LAST read, complete or not), and with neither a linked add is refused
    L2 = "5" * 24
    done_o = D("O5", f"🥅 O • [Old proj](ticktick:///webapp/#p/{L2}/tasks)", status=2)
    UNREAD = "🥅 Not written · completed KRs unreadable right now · try again"

    def full(*extra, list_id=PID):
        """okr_complete: the fixture's complete read, plus `extra` rows."""
        o, dn = fixture()
        MEM["okr_complete"] = {"list_id": list_id, "ts": 1,
                               "rows": cp(o) + cp(dn) + [cp(x) for x in extra]}

    api, v2 = world(completed=False)
    put(api, done_o, done=True)                  # there, but v2 cannot hand it over
    full(done_o)
    e = refusal(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("B5 completed KRs unreadable: the done O comes from the last complete read",
          e and str(e) == "🥅 Already in the plan · 🥅 Old proj" and e.reopen == "ctx:okr:o:O5"
          and not api.of("create_task"), e and (str(e), e.reopen))
    out = attempt(ow.add_items, {"kind": "O", "names": ["Fresh"],
                  "link": {"to": "list", "pid": "3" * 24}}, api, v2)
    check("B5 ... a target nothing plans is added", ids(out) == ["new1"], out)
    check("C3 ... and an incomplete read never overwrites okr_complete",
          cached("okr_complete", "O5") is not None and cached("okr_complete", "new1") is None,
          MEM.get("okr_complete"))

    api, v2 = world(completed=False)
    put(api, done_o, done=True)
    MEM["okr_rows"]["rows"].append(cp(done_o))
    MEM["okr_rows"]["done_complete"] = True      # okr_rows says complete: still never asked
    r = refused(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("C3 no okr_complete: a LINKED add is refused, okr_rows is never the memory",
          r == UNREAD and not api.of("create_task"), r)
    out = attempt(ow.add_items, {"kind": "O", "names": ["Typed"]}, api, v2)
    check("B5 ... a typed add has nothing to dedupe: it goes", ids(out) == ["new1"], out)
    e = refusal(ow.add_items, {"kind": "O", "names": ["Ship it"],
                               "link": {"to": "task", "pid": E, "tid": F}}, api, v2)
    check("C1 blind, but an OPEN item of the live read plans it: that answer stands",
          e and str(e) == "🥅 Already in the plan · 🔑 Ship it" and e.reopen == "ctx:okr:o:O1",
          e and (str(e), e.reopen))
    api, v2 = world(completed=False)
    full(done_o, list_id="other")
    r = refused(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("B5 another list's complete read answers nothing here", r == UNREAD, r)
    api, v2 = world(completed=False, token="")
    r = refused(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("B5 ... no v2 token: the Attachment Login wording", r and "Attachment Login" in r, r)
    api, v2 = world(completed=False)
    # the complete read held K9 CLOSED on the old project; live, K9 is open on its task
    full(dict(cp(done_o), id="K9"))
    out = attempt(ow.add_items, {"kind": "O", "names": ["Old proj"],
                  "link": {"to": "list", "pid": L2}}, api, v2)
    check("B5 the live read wins on an id both hold (the remembered K9 is not asked)",
          ids(out) == ["new1"], out)

    # C3 open THEN, gone NOW: closed or deleted, and nothing can tell which
    gone_o = D("OG", f"🥅 O • [Gone proj](ticktick:///webapp/#p/{L2}/tasks)")
    api, v2 = world(completed=False)
    full(gone_o)
    r = refused(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("C3 the only hit is a row open in the complete read, gone from this one: "
          "refused, the _why_not wording", r == UNREAD and not api.of("create_task"), r)
    api, v2 = world(completed=False)
    full(gone_o, done_o)
    e = refusal(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("C3 ... a KNOWN closed hit beside it is the answer: Already in the plan",
          e and str(e) == "🥅 Already in the plan · 🥅 Old proj" and e.reopen == "ctx:okr:o:O5",
          e and (str(e), e.reopen))
    api, v2 = world(completed=False)
    full(D("OW", f"🥅 O • [Shelved proj](ticktick:///webapp/#p/{L2}/tasks)", status=-1))
    e = refusal(ow.add_items, {"kind": "O", "names": ["Old proj"],
                               "link": {"to": "list", "pid": L2}}, api, v2)
    check("C7 a WON'T-DO row of okr_complete is known closed too: Already in the plan",
          e and str(e) == "🥅 Already in the plan · 🥅 Shelved proj"
          and e.reopen == "ctx:okr:o:OW", e and (str(e), e.reopen))
    check("C3 closed_cached = okr_complete's done AND won't-do rows",
          sorted(t["id"] for t in ow.closed_cached(PID)) == ["K4", "O3", "OW"]
          and ow.closed_cached("other") is None, ow.closed_cached(PID))

    # M24 a closed planning copy the live read missed, found by its id in
    # okr_complete (the payload's list is stale, so nothing refused it earlier)
    api, v2 = world(completed=False)
    full(D("KX", "🔑 KR • Old deliverable - TA", parent="O1", status=2))
    r = refused(ow.add_items, {"kind": "KR", "parent": "O1", "names": ["Old deliverable"],
                               "link": {"to": "task", "pid": P2, "tid": "KX"}}, api, v2)
    check("M24 a closed copy known only to okr_complete: the planning-copy refusal",
          r == "🥅 That is a planning copy · add the original" and not api.of("create_task"), r)

    # C3 remember_complete: only a complete live read is kept
    api, v2 = world(completed=False)
    MEM.pop("okr_complete", None)
    check("C3 remember_complete refuses a read missing completed KRs",
          ow.remember_complete(snapshot(api, v2)) is False and "okr_complete" not in MEM)
    api, v2 = boom_world()
    check("C3 ... and a cache read", ow.remember_complete(snapshot(api, v2)) is False
          and "okr_complete" not in MEM)
    check("C3 ... never raises on junk", ow.remember_complete(None) is False
          and ow.remember_complete(object()) is False)
    api, v2 = world()
    MEM.pop("okr_complete", None)
    r = refused(ow.add_items, {"kind": "O", "names": ["Ship it"],
                               "link": {"to": "task", "pid": E, "tid": F}}, api, v2)
    check("C3 a writer's complete read is kept even when the verb then refuses",
          r and r.startswith("🥅 Already in the plan")
          and sorted(t["id"] for t in (MEM.get("okr_complete") or {}).get("rows", []))
          == sorted(t["id"] for t in fixture()[0] + fixture()[1]), MEM.get("okr_complete"))

    api, v2 = boom_world()
    r = refused(ow.add_items, {"kind": "O", "names": ["Delta"]}, api, v2)
    check("v1 down (only the cache answered): add_items refused, nothing created",
          r and "unreachable" in r and wrote_nothing(api, v2), r)

    api, v2 = world()
    with open(ow.LOCK_FILE, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = refused(ow.add_items, {"kind": "O", "names": ["Delta"]}, api, v2)
        fcntl.flock(held, fcntl.LOCK_UN)
    check("the lock held elsewhere: busy, nothing read", r and "Busy" in r
          and not api.of("get_project_data"), r)

    # planned + screen_of (pure)
    rows = [r for r in fixture()[0]] + [
        D("Y1", "🏔️ Y • Productivity System"),
        D("OY", "🥅 O • Under Y", parent="Y1"),
        D("KY", "🔑 KR • Straight under Y", parent="Y1"),
        D("KL", "🔑 KR • Loose"),
    ]
    items = okr.items_from(rows)
    by = okr.index(items)
    check("screen_of: an O / a Y = its own screen",
          (ow.screen_of(by["O1"], items), ow.screen_of(by["Y1"], items))
          == ("ctx:okr:o:O1", "ctx:okr:y:Y1"))
    check("screen_of: a KR = its parent's (O or Y), a loose one = the root",
          [ow.screen_of(by[k], items) for k in ("K1", "KY", "KL", "U1")]
          == ["ctx:okr:o:O1", "ctx:okr:y:Y1", "ctx:okr", "ctx:okr"])
    edge = okr.items_from(rows + [
        D("KG", "🔑 KR • Orphan", parent="GONE"),             # its O deleted since
        D("KK", "🔑 KR • Sub-deliverable", parent="K1"),      # a KR under a KR
        D("OD", "🥅 O • Done one", status=2, parent="Y1"),
        D("KD", "🔑 KR • Under a done O", parent="OD", status=2),
        D("UL", "Loose parent"),
        D("KU", "🔑 KR • Under a loose item", parent="UL"),
        D("YW", "🏔️ Y • Shelved", status=-1),
    ])
    eby = okr.index(edge)
    check("screen_of edges: a KR whose O is gone, under a KR, under a loose item = the root",
          [ow.screen_of(eby[k], edge) for k in ("KG", "KK", "KU")]
          == ["ctx:okr", "ctx:okr", "ctx:okr"])
    check("screen_of edges: a closed O / Y still has its own screen (never its Y's), a "
          "KR of a closed O lands on that O",
          [ow.screen_of(eby[k], edge) for k in ("OD", "YW", "KD", "OY")]
          == ["ctx:okr:o:OD", "ctx:okr:y:YW", "ctx:okr:o:OD", "ctx:okr:o:OY"])
    check("planned: K9 by its task id", getattr(ow.planned(items, "task", E, F), "id", None)
          == "K9")
    three = okr.items_from(rows + [
        D("OX", f"🥅 O • [Doubt](ticktick:///webapp/#p/{L}/tasks)"),
        D("OC", f"🥅 O • [Closed](ticktick:///webapp/#p/{L}/tasks)", status=2)])
    check("planned: a doubt id answers LAST, after a closed one",
          getattr(ow.planned(three, "list", L, doubt={"OX"}), "id", None) == "OC"
          and getattr(ow.planned(three, "list", L), "id", None) == "OX")
    check("planned: nothing for an unplanned task or list",
          ow.planned(items, "task", P2, T2) is None and ow.planned(items, "list", L) is None)
    two = okr.items_from(rows + [
        D("OC", f"🥅 O • [Closed](ticktick:///webapp/#p/{L}/tasks)", status=2),
        D("OO", f"🥅 O • [Open](ticktick:///webapp/#p/{L}/tasks)")])
    check("planned: an open item answers before a closed one",
          getattr(ow.planned(two, "list", L), "id", None) == "OO")

    # ── 3c. import_source (pure over the caches) ─────────────────────────────
    print("import_source")
    real_cta = areas.CTA_LIST_ID
    CTA, CT, L3, L4 = "7" * 24, "8" * 24, "6" * 24, "4" * 24
    real_get = cache.get
    try:
        areas.CTA_LIST_ID = CTA
        api, v2 = world()
        MEM["all_tasks"] += [
            {"id": "t1", "projectId": P2, "title": "Write the [docs](https://x.y/z) 🔗"},
            {"id": CT, "projectId": CTA,
             "title": f"💼 P • [Proj](ticktick:///webapp/#p/{L3}/tasks) 🔗"},
            {"id": "t2", "projectId": P2,
             "title": "💼P • \\[Esc \\[2\\]\\]\\(https://ticktick.com/webapp/#p/x/tasks/y\\) 🔗"},
            {"id": "t3", "projectId": P2, "title": "🔑 KR • Old thing - OT"},
            {"id": "t4", "projectId": P2, "title": "🔑 KR • Call Anna - Monday"},
            {"id": "t5", "projectId": P2, "title": " 🔗 "},
            {"id": "t6", "_projectId": P2, "title": "Moved   here"},
        ]
        MEM["all_notes"] = [{"id": "n1", "projectId": P2, "title": "A note"}]
        MEM["projects"] += [{"id": L3, "name": "💼P • Proj 4️⃣"},
                            {"id": L4, "name": "🏆 Plain list"}]

        r = ow.import_source("task", P2, "t1")
        check("a task: links flattened, 🔗 dropped, the task linked, a KR hint",
              r == {"name": "Write the docs", "link": {"to": "task", "pid": P2, "tid": "t1"},
                    "kind_hint": "KR"}, r)
        r = ow.import_source("task", CTA, CT)
        check("a 📌CTA task: its 💼 P • lead dropped, an O hint",
              r == {"name": "Proj", "link": {"to": "task", "pid": CTA, "tid": CT},
                    "kind_hint": "O"}, r)
        r = ow.import_source("task", P2, "t2")
        check("the app's escapes, a nested bracket label, the glued 💼P • lead",
              isinstance(r, dict) and r["name"] == "Esc [2]", r)
        r = ow.import_source("task", P2, "t3")
        check("an old planning copy: its level prefix and all-caps code dropped",
              isinstance(r, dict) and r["name"] == "Old thing", r)
        r = ow.import_source("task", P2, "t4")
        check("... a code that is not all caps stays in the name",
              isinstance(r, dict) and r["name"] == "Call Anna - Monday", r)
        r = ow.import_source("task", "stale", "t6")
        check("the CACHED list wins over the payload's (the task moved), spaces collapsed",
              isinstance(r, dict) and r["link"]["pid"] == P2 and r["name"] == "Moved here", r)
        r = ow.import_source("note", P2, "n1")
        check("a note from all_notes", isinstance(r, dict) and r["name"] == "A note"
              and r["link"] == {"to": "task", "pid": P2, "tid": "n1"}, r)
        r = ow.import_source("list", L3, "-")
        check("a project list: its clean name, linked to its 📌CTA TASK, an O hint",
              r == {"name": "Proj", "link": {"to": "task", "pid": CTA, "tid": CT},
                    "kind_hint": "O"}, r)
        r = ow.import_source("list", L4, None)
        check("B7 a list with no CTA: the list itself, its leading emoji dropped",
              r == {"name": "Plain list", "link": {"to": "list", "pid": L4, "tid": None},
                    "kind_hint": "O"}, r)
        for a, want, why in [
            (("task", P2, "t5"), "🥅 No name to copy · give it a title first", "nothing to name"),
            (("task", PID, "K1"), "🥅 That is a planning copy · add the original",
             "a planning copy"),
            (("task", P2, "K1"), "🥅 That is a planning copy · add the original",
             "a planning copy by its cached list"),
            (("list", PID, "-"), "🥅 That is the plan list · add the real one", "the plan list"),
            (("task", P2, "nope"), "🥅 Not cached yet · sync or reopen", "an uncached task"),
            (("list", "z" * 24, "-"), "🥅 List not cached yet · sync or reopen",
             "an uncached list"),
            (("task", P2, "-"), "🥅 Nothing to add", "a task with no id"),
            (("habit", P2, "t1"), "🥅 Nothing to add", "a kind it does not know"),
        ]:
            r = ow.import_source(*a)
            check(f"import_source RETURNS a Refusal: {why}",
                  isinstance(r, ow.Refusal) and str(r) == want, r)

        # B3 an unprefixed item of the plan list: the verb's wording, both ways in
        for a in (("task", PID, "U1"), ("task", P2, "U1")):
            r = ow.import_source(*a)
            check(f"B3 import_source: an unprefixed plan-list item wants its prefix {a[1][:1]}",
                  isinstance(r, ow.Refusal)
                  and str(r) == "🥅 Already in the plan list · give it a 🏔️ / 🥅 / 🔑 prefix", r)

        # B7 a plain list's leading emoji run is decoration; a title is Vex's
        LR, LK, LE, LD = "r" * 24, "k" * 24, "m" * 24, "q" * 24
        MEM["projects"] += [{"id": LR, "name": "🌅 Routines"},
                            {"id": LK, "name": "1️⃣ Work"},
                            {"id": LE, "name": "🌅"},
                            {"id": LD, "name": "[Draft] notes"},
                            {"id": "j" * 24, "name": "👨‍👩‍👧 🏠Family"}]
        MEM["all_tasks"].append({"id": "t7", "projectId": P2, "title": "🌅 Morning run"})
        got = [(ow.import_source("list", x) or {}).get("name")
               for x in (LR, LK, LE, LD, "j" * 24)]
        check("B7 a plain list loses its leading emoji run (keycap, ZWJ family, spaced "
              "run); all-emoji keeps itself; punctuation is no emoji",
              got == ["Routines", "Work", "🌅", "[Draft] notes", "Family"], got)
        got = [ow._strip_lead_emoji(x) for x in
               ("⚙️ Settings", "⚙ Settings", "👍🏽 Approved", "`dev` tools", "^Top",
                "🇩🇪 Berlin")]
        check("C6 VS16 and a skin tone are part of the run; an ASCII backtick or caret "
              "starts a word and stays",
              got == ["Settings", "Settings", "Approved", "`dev` tools", "^Top", "Berlin"], got)
        LB = "u" * 24
        MEM["projects"].append({"id": LB, "name": "`dev` tools"})
        r = ow.import_source("list", LB)
        check("C6 ... through import_source: the list keeps its backtick",
              isinstance(r, dict) and r["name"] == "`dev` tools", r)
        r = ow.import_source("list", LR)
        check("B7 ... so the link label reads the name", isinstance(r, dict)
              and okr.parse_title(okr.build_title("O", r["name"], link=okr.list_link(LR)))[1]
              == "Routines", r)
        r = ow.import_source("task", P2, "t7")
        check("B7 a task title keeps its emoji", isinstance(r, dict)
              and r["name"] == "🌅 Morning run", r)

        # Vex's notes lists lead with "N - " / "N • " (live: "🗒N - Work",
        # "🗒N •\u200b \u200b×15Manager") - filing, not the name; zero-width
        # marks never reach a planning copy's label
        LN1, LN2, LN3 = "v" * 24, "w" * 24, "x" * 24
        MEM["projects"] += [{"id": LN1, "name": "🗒N - Work"},
                            {"id": LN2, "name": "🗒N \u2022\u200b \u200bManager"},
                            {"id": LN3, "name": "Nature walks"}]
        got = [(ow.import_source("list", x) or {}).get("name") for x in (LN1, LN2, LN3)]
        check("notes lists lose their 'N - ' lead and zero-width marks; a name that "
              "merely starts with N keeps it",
              got == ["Work", "Manager", "Nature walks"], got)
        MEM["all_tasks"].append({"id": "t8", "projectId": P2, "title": "Plan\u200b trip"})
        r = ow.import_source("task", P2, "t8")
        check("a task title loses zero-width marks too", isinstance(r, dict)
              and r["name"] == "Plan trip", r)

        # B8 an app-escaped 📌CTA title still maps its list; a task outside
        # the 📌CTA list that links a list is not that list's CTA
        L5, C5, L6 = "2" * 24, "1" * 24, "3" * 24
        MEM["projects"] += [{"id": L5, "name": "💼P • Esc proj"},
                            {"id": L6, "name": "💼P • Other proj"}]
        MEM["all_tasks"] += [
            {"id": C5, "projectId": CTA,
             "title": f"💼 P • \\[Esc proj\\]\\(ticktick:///webapp/#p/{L5}/tasks\\) 🔗"},
            {"id": "t8", "projectId": P2,
             "title": f"💼 P • [Other proj](ticktick:///webapp/#p/{L6}/tasks) 🔗"}]
        r = ow.import_source("list", L5)
        check("B8 import: an app-escaped CTA title still maps the list to its CTA task",
              isinstance(r, dict) and r["link"] == {"to": "task", "pid": CTA, "tid": C5}
              and r["name"] == "Esc proj", r)
        r = ow.import_source("list", L6)
        check("B8 import: a non-CTA task linking the list is not taken as its CTA",
              isinstance(r, dict) and r["link"] == {"to": "list", "pid": L6, "tid": None}, r)
        os.environ["okr_list_id"] = ""
        try:
            r = ow.import_source("task", P2, "t1")
        finally:
            os.environ["okr_list_id"] = PID
        check("OKRs off", isinstance(r, ow.Refusal) and "OKRs are off" in str(r), r)

        def broken(k):
            raise OSError("disk")
        cache.get = broken
        r = ow.import_source("task", P2, "t1")
        check("an unreadable cache: a Refusal, never a raise",
              isinstance(r, ow.Refusal) and str(r) == "🥅 Unreadable · OSError", r)
        cache.get = real_get
        check("import_source reads nothing live", not api.calls, api.calls)
    finally:
        cache.get = real_get
        areas.CTA_LIST_ID = real_cta

    # ── 3d. import_plan: THE answer, the same as the verb's ─────────────────
    print("import_plan")
    L2, LF, L3 = "5" * 24, "3" * 24, "6" * 24
    CTA, CT = "7" * 24, "8" * 24
    UNREAD = "🥅 Not written · completed KRs unreadable right now · try again"
    done_o = D("O5", f"🥅 O • [Old proj](ticktick:///webapp/#p/{L2}/tasks)", status=2)
    gone_o = D("OG", f"🥅 O • [Gone proj](ticktick:///webapp/#p/{L2}/tasks)")
    lazy = []
    real_lazy = ow._lazy_v2

    def at(completed=True, token="tok", complete_rows=None, extra_done=(), last=True):
        """A world whose caches know the targets; okr_rows marks its last
        read complete or not, okr_complete holds `complete_rows`."""
        api, v2 = world(completed=completed, token=token)
        for x in extra_done:
            api.done[x["id"]] = cp(x)
            MEM["okr_rows"]["rows"].append(cp(x))
        MEM["okr_rows"]["done_complete"] = completed
        if not last:
            MEM.pop("okr_rows")
        MEM["projects"] += [{"id": L2, "name": "Old proj"}, {"id": LF, "name": "Fresh proj"},
                            {"id": L3, "name": "💼P • Proj"}]
        MEM["all_tasks"] += [{"id": F, "projectId": E, "title": "Ship it"},
                             {"id": CT, "projectId": CTA,
                              "title": f"💼 P • [Proj](ticktick:///webapp/#p/{L3}/tasks) 🔗"},
                             {"id": "KX", "projectId": P2, "title": "🔑 KR • Old - TA"}]
        if complete_rows is not None:
            o, dn = fixture()
            MEM["okr_complete"] = {"list_id": PID, "ts": 1, "rows": cp(o) + cp(dn)
                                   + [cp(x) for x in complete_rows]}
        return api, v2

    def both(kind, pid, tid, api, v2, okind="O", parent=None, v2_plan="same"):
        """(import_plan's answer, the verb's) over the same caches: the verb
        gets the payload the screen's row would carry."""
        p = ow.import_plan(kind, pid, tid, v2=v2 if v2_plan == "same" else v2_plan)
        link = p["link"] or {"to": "list" if kind == "list" else "task", "pid": pid,
                             "tid": tid}
        out = attempt(ow.add_items, {"kind": okind, "parent": parent,
                                     "names": [p["name"] or "x"], "link": link}, api, v2)
        return p, out

    def agree(p, out):
        if p["hit"] is not None:
            h = p["hit"]
            return (isinstance(out, ow.Refusal) and out.reopen == p["screen"]
                    and str(out) == f"🥅 Already in the plan · {ow.GLYPH[h.kind]} {h.name}")
        if p["blocked"] is not None:
            return isinstance(out, ow.Refusal) and str(out) == p["blocked"]
        return isinstance(out, ow.Outcome) and bool(out.ids)

    real_cta, real_per = areas.CTA_LIST_ID, areas.PERIODIC_LIST_ID
    try:
        areas.CTA_LIST_ID = CTA
        ow._lazy_v2 = lambda: (lazy.append(1), None)[1]
        api, v2 = at()
        p, out = both("task", E, F, api, v2, okind="KR", parent="O2")
        check("import_plan: planned by an OPEN KR = hit + its screen, not blocked",
              getattr(p["hit"], "id", None) == "K9" and p["screen"] == "ctx:okr:o:O1"
              and p["blocked"] is None and p["name"] == "Ship it"
              and p["link"] == {"to": "task", "pid": E, "tid": F} and p["kind_hint"] == "KR", p)
        check("... the verb gives the SAME answer (refused, lands on the same screen)",
              agree(p, out), (p, out))
        api, v2 = at()
        p, out = both("list", LF, None, api, v2)
        check("import_plan: nothing plans it = free (no hit, not blocked)",
              p["hit"] is None and p["blocked"] is None
              and p["link"] == {"to": "list", "pid": LF, "tid": None}, p)
        check("... and the verb adds it", agree(p, out), out)
        check("... no Keychain read for an answer that needs no wording", not lazy, lazy)
        api, v2 = at(extra_done=[done_o])
        p, out = both("list", L2, None, api, v2)
        check("import_plan: a DONE O of the last complete read = hit (closed ones count)",
              getattr(p["hit"], "id", None) == "O5" and p["screen"] == "ctx:okr:o:O5", p)
        check("... the verb agrees", agree(p, out), (p, out))

        api, v2 = at(completed=False)
        p, out = both("list", L2, None, api, v2)
        check("C1 blocked: the last read missed completed KRs and none is remembered - "
              "the verb's own refusal text", p["blocked"] == UNREAD and p["hit"] is None
              and p["link"] is not None, p)
        check("... the verb refuses in exactly those words", agree(p, out), (p, out))
        api, v2 = at(completed=False, token="")
        p, out = both("list", L2, None, api, v2)
        check("C1 ... no v2 token: both say Attachment Login",
              "Attachment Login" in (p["blocked"] or "") and agree(p, out), (p, out))
        lazy.clear()
        api, v2 = at(completed=False)
        p = ow.import_plan("list", L2, None)
        check("C1 ... with no client handed in, the token is looked up only now, once",
              lazy == [1] and "Attachment Login" in (p["blocked"] or ""), (lazy, p))
        api, v2 = at(completed=False)
        MEM["okr_rows"]["detail"] = "v1 open 9; v2 completed 500 (120 d) - TRUNCATED"
        lazy.clear()
        p = ow.import_plan("list", L2, None)
        check("C1 ... a TRUNCATED last read words it so, no token lookup",
              p["blocked"] == "🥅 Not written · too many completed KRs to read them all"
              and not lazy, (p, lazy))
        api, v2 = at(completed=False)
        p, out = both("task", E, F, api, v2, okind="KR", parent="O2")
        check("C1 blind, but an OPEN item plans it: the hit, on both sides",
              getattr(p["hit"], "id", None) == "K9" and agree(p, out), (p, out))

        api, v2 = at(completed=False, complete_rows=[done_o])
        p, out = both("list", L2, None, api, v2)
        check("C3 a remembered DONE O answers for an incomplete read: hit, both sides",
              getattr(p["hit"], "id", None) == "O5" and agree(p, out), (p, out))
        api, v2 = at(completed=False, complete_rows=[gone_o])
        p, out = both("list", L2, None, api, v2)
        check("C3 only a row gone since (closed or deleted): blocked, both sides",
              p["blocked"] == UNREAD and p["hit"] is None and agree(p, out), (p, out))
        api, v2 = at(completed=False, complete_rows=[gone_o, done_o])
        p, out = both("list", L2, None, api, v2)
        check("C3 ... a known closed one beside it is the answer", getattr(p["hit"], "id", None)
              == "O5" and agree(p, out), (p, out))
        api, v2 = at(completed=False, complete_rows=[])
        p, out = both("list", LF, None, api, v2)
        check("C3 a remembered read and no hit: free, both sides",
              p["hit"] is None and p["blocked"] is None and agree(p, out), (p, out))
        api, v2 = at(completed=False,
                     complete_rows=[D("KX", "🔑 KR • Old - TA", parent="O1", status=2)])
        p, out = both("task", P2, "KX", api, v2, okind="KR", parent="O1")
        check("M24 a closed planning copy known only to okr_complete: the planning-copy "
              "refusal, both sides", p["blocked"] == "🥅 That is a planning copy · add the "
              "original" and agree(p, out), (p, out))

        api, v2 = at()
        put(api, D("O7", f"🥅 O • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        MEM["okr_rows"]["rows"].append(D("O7", f"🥅 O • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        p, out = both("list", L3, None, api, v2)
        check("import_plan: a list whose 📌CTA task is the payload is planned by the O on "
              "the list (the goal's other face), ONE question",
              p["link"] == {"to": "task", "pid": CTA, "tid": CT}
              and getattr(p["hit"], "id", None) == "O7" and agree(p, out), (p, out))
        api, v2 = at()
        put(api, D("KL", f"🔑 KR • [Proj list](ticktick:///webapp/#p/{L3}/tasks)", parent="O2"))
        MEM["okr_rows"]["rows"].append(
            D("KL", f"🔑 KR • [Proj list](ticktick:///webapp/#p/{L3}/tasks)", parent="O2"))
        p, out = both("list", L3, None, api, v2)
        check("C1 ... a KR on the LIST is never asked about through its CTA payload (no "
              "second question): free, both sides",
              p["hit"] is None and p["blocked"] is None and agree(p, out), (p, out))
        api, v2 = at()
        put(api, D("YP", f"🏔️ Y • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        MEM["okr_rows"]["rows"].append(D("YP", f"🏔️ Y • [Proj](ticktick:///webapp/#p/{L3}/tasks)"))
        p, out = both("list", L3, None, api, v2)
        check("C7 ... a Y on the list: hit, its own screen, both sides",
              p["screen"] == "ctx:okr:y:YP" and agree(p, out), (p, out))

        # the source's refusals are the verb's
        api, v2 = at()
        for a, want, why in [
            (("list", PID, None), ow.PLAN_LIST, "the plan list"),
            (("task", PID, "U1"), ow.IN_PLAN_LOOSE, "an unprefixed item of it"),
            (("task", P2, "K2"), ow.IN_PLAN_COPY, "a planning copy under a stale list"),
        ]:
            p, out = both(*a, api, v2, okind="KR", parent="O1")
            check(f"import_plan blocked by the source, the verb agrees: {why}",
                  p["blocked"] == want and p["link"] is None and agree(p, out), (p, out))
        PER = "p" * 24
        areas.PERIODIC_LIST_ID = PER
        MEM["projects"].append({"id": PER, "name": "💫Periodic notes"})
        MEM["all_tasks"].append({"id": "pn1", "projectId": PER, "title": "2026-09-19"})
        for a, why in [(("list", PER, None), "the periodic list"),
                       (("task", PER, "pn1"), "a periodic note"),
                       (("task", P2, "pn1"), "a periodic note under a stale list")]:
            api.calls.clear()
            p, out = both(*a, api, v2, okind="KR", parent="O1")
            check(f"import_plan: {why} stays out, the verb refuses it before any read",
                  p["blocked"] == ow.PERIODIC and agree(p, out) and not api.calls, (p, out))
        areas.PERIODIC_LIST_ID = real_per
        os.environ["okr_list_id"] = ""
        try:
            p, out = both("list", LF, None, api, v2)
        finally:
            os.environ["okr_list_id"] = PID
        check("import_plan: OKRs off, the verb's words",
              p["blocked"] == "🥅 OKRs are off · ⚙️ Settings → OKR List" and agree(p, out),
              (p, out))

        # the plan: the caller's items win; else the hub's cached rows
        api, v2 = at()
        p = ow.import_plan("task", E, F, items=[])
        check("import_plan asks the items it is handed (the screen's snapshot), not the cache",
              p["hit"] is None and p["blocked"] is None, p)
        p = ow.import_plan("task", E, F, items=okr.items_from(fixture()[0]))
        check("... a hit among them", getattr(p["hit"], "id", None) == "K9", p)
        api, v2 = at(last=False)
        p = ow.import_plan("list", L2, None, v2=FakeV2(api))
        check("import_plan: no last read known, a v2 token = the verb's read is predicted "
              "whole (nothing to block on)", p["blocked"] is None and p["hit"] is None, p)
        p = ow.import_plan("list", L2, None, v2=FakeV2(api, token=""))
        check("import_plan: no last read known and NO v2 token = blocked like the verb "
              "(no read is ever complete without it)",
              p["blocked"] == "🥅 Not written · completed KRs need the Attachment Login "
                             "token (⚙️ Settings)", p)
        p = ow.import_plan("list", LF, None, list_id="other", v2=FakeV2(api))
        check("import_plan: another list's okr_rows says nothing about this one",
              p["blocked"] is None, p)
        real_cp = ow.cached_plan
        ow.cached_plan = lambda list_id: 1 / 0
        try:
            p = ow.import_plan("list", LF, None)
        finally:
            ow.cached_plan = real_cp
        check("import_plan never raises: an unreadable plan is a blocked answer, never a "
              "live row", p["blocked"] == "🥅 Unreadable · ZeroDivisionError"
              and p["hit"] is None, p)

        # cached_plan: okr_rows while nothing newer touched project_data;
        # else the synced open rows plus every closed row still known
        api, v2 = at(extra_done=[done_o])
        check("cached_plan: okr_rows as kept (fresh), closed rows in",
              {i.id for i in ow.cached_plan(PID)} >= {"K4", "O3", "O5", "K1"})
        MEM[f"project_data_{PID}"]["tasks"].append(
            D("ON", "🥅 O • Synced since", tags=[]))
        MEM["okr_complete"] = {"list_id": PID, "ts": 1, "rows": [
            D("OQ", f"🥅 O • [Quiet](ticktick:///webapp/#p/{LF}/tasks)", status=2)]}
        MEM["completed_tasks"] = [D("KF", "🔑 KR • From the feed", parent="O1", status=2)]
        try:
            ow._mtime = lambda k: 2 if k.startswith("project_data") else 1
            ids_ = {i.id for i in ow.cached_plan(PID)}
            check("cached_plan: project_data newer than okr_rows = its open rows + the closed "
                  "ones of okr_rows, okr_complete and the feed",
                  {"ON", "O5", "K4", "OQ", "KF"} <= ids_, sorted(ids_))
            p = ow.import_plan("list", LF, None)
            check("... so a closed O only okr_complete still knows is found by the screen too",
                  getattr(p["hit"], "id", None) == "OQ", p)
        finally:
            ow._mtime = lambda key: None
        MEM.clear()
        check("cached_plan: nothing cached = no items", ow.cached_plan(PID) == [])
    finally:
        areas.CTA_LIST_ID, areas.PERIODIC_LIST_ID = real_cta, real_per
        ow._lazy_v2 = real_lazy

    # ── 4. link ──────────────────────────────────────────────────────────────
    print("link")
    api, v2 = world()
    P2, T2 = "b" * 24, "c" * 24
    msg = ow.link({"id": "K1", "to": "task", "pid": P2, "tid": T2}, api, v2)
    up = api.of("update_task")
    new = up[0][3]["title"] if up else ""
    url = f"https://ticktick.com/webapp/#p/{P2}/tasks/{T2}"
    check("a KR links a task: prefix and code OUTSIDE the link",
          new == f"🔑 KR • [Goals wf]({url}) - TA", new)
    check("... reads back", okr.parse_title(new) == ("KR", "Goals wf", url, "TA"))
    check("... posted over a LIVE GET, task id first", up[0][1] == "K1" and up[0][2] == PID
          and ("get_task", PID, "K1") in api.calls)
    check("... only the title changes", set(up[0][3]) == {"title"})
    check("cache: the new title everywhere", all(cached(k, "K1")["title"] == new
          for k in ("all_tasks", f"project_data_{PID}", "okr_rows")))
    msg2 = ow.link({"id": "K1", "to": "task", "pid": P2, "tid": T2}, api, v2)
    check("the same link again writes nothing", msg2.startswith("🔗 Already linked")
          and len(api.of("update_task")) == 1, msg2)

    api, v2 = world()
    ow.link({"id": "K8", "to": "task", "pid": P2, "tid": T2}, api, v2)
    new = api.of("update_task")[0][3]["title"]
    check("trap 14: the SETTLED name - 'Call Anna - Monday' gains no code Monday",
          new == f"🔑 KR • [Call Anna - Monday]({url})", new)

    api, v2 = world()
    L = "d" * 24
    msg = ow.link({"id": "O2", "to": "list", "pid": L, "tid": None}, api, v2)
    new = api.of("update_task")[0][3]["title"]
    check("an O links a list (the app-scheme list form)",
          new == f"🥅 O • [Workflows](ticktick:///webapp/#p/{L}/tasks)", new)
    check("toast names the list from the cache", msg == "🔗 Workflows → 📂 Workflows", msg)

    api, v2 = world()
    r = refused(ow.link, {"id": "K1", "to": "task", "pid": PID, "tid": "K2"}, api, v2)
    check("linking another planning copy is refused, before any read",
          r == "🔗 That is a planning copy · link the original" and not api.calls, r)
    r = refused(ow.link, {"id": "O2", "to": "list", "pid": PID, "tid": None}, api, v2)
    check("W3 linking the plan list itself is refused",
          r == "🔗 That is the plan list · link the real one" and not api.calls, r)
    r = refused(ow.link, {"id": "K1", "to": "task", "pid": P2, "tid": "K2"}, api, v2)
    check("W3 a plan item under a stale list id: still a planning copy (by its id)",
          r == "🔗 That is a planning copy · link the original", r)
    r = refused(ow.link, {"id": "U1", "to": "list", "pid": L}, api, v2)
    check("an unprefixed item is refused", r and "Not an OKR item" in r, r)
    r = refused(ow.link, {"id": "K1", "to": "task", "pid": P2}, api, v2)
    check("a task link without a task id is refused", r == "🔗 Nothing to link", r)
    check("refusals wrote nothing", not api.of("update_task"))

    api, v2 = boom_world()
    r = refused(ow.link, {"id": "K1", "to": "task", "pid": P2, "tid": T2}, api, v2)
    check("W11 v1 down (only the cache answered): link refused, nothing written",
          r and "unreachable" in r and wrote_nothing(api, v2), r)

    # ── 5. retag ─────────────────────────────────────────────────────────────
    print("retag")
    api, v2 = world()
    msg = ow.retag({"id": "O1", "tag": "2️⃣Personal"}, api, v2)
    wrote = {b["id"]: b["tags"] for b in v2.batches[0]}
    check("the O swaps its pool tag", wrote.get("O1") == ["2️⃣personal"], wrote)
    check("its open KRs that carried the O's old tag follow",
          all(wrote.get(k) == ["2️⃣personal"] for k in ("K1", "K2", "K8", "K9")), wrote)
    check("a KR with no pool tag follows too", wrote.get("K3") == ["2️⃣personal"], wrote)
    check("W7 a tag no Y / O carries is not the pool's: kept",
          wrote.get("K7") == ["2️⃣personal", "⭐solo2"], wrote.get("K7"))
    check("a KR tagged into another lane on purpose keeps it (💼adhoc: the DONE O3's)",
          "K5" not in wrote)
    check("a done KR never changes", "K4" not in wrote)
    check("one batch, one toast", len(v2.batches) == 1
          and msg == "🏷 2️⃣Personal · TickAL · 6 KRs too", msg)
    check("cache: tags patched", cached("all_tasks", "K7")["tags"] == ["2️⃣personal", "⭐solo2"])

    api, v2 = world()
    msg = ow.retag({"id": "K5", "tag": "#💼TickAL"}, api, v2)
    wrote = {b["id"]: b["tags"] for b in v2.batches[0]}
    check("a KR alone: replaced, no cascade", wrote == {"K5": ["💼tickal"]}, wrote)

    api, v2 = world()
    msg = ow.retag({"id": "U1", "tag": "1️⃣work"}, api, v2)
    check("an area tag lands, a unique non-pool tag stays",
          v2.batches[0][0]["tags"] == ["1️⃣work", "⭐solo"], v2.batches)

    api, v2 = world()
    msg = ow.retag({"id": "K1", "tag": "💼tickal"}, api, v2)
    check("already carrying it: nothing written", msg.startswith("🏷 Goals wf already")
          and not v2.batches, msg)
    r = refused(ow.retag, {"id": "K1", "tag": "🔥crm"}, api, v2)
    check("a tag outside the pool is refused (no area tag is ever made)",
          r and "not an OKR tag" in r, r)
    r = refused(ow.retag, {"id": "K1", "tag": ""}, api, v2)
    check("no tag is refused", r == "🏷 No tag picked", r)

    check("W7 the pool: 0️⃣Area + every Y / O tag (done ones too), never a KR-only tag",
          ow.tag_pool(okr.items_from(fixture()[0] + fixture()[1]))
          == {"1️⃣work", "2️⃣personal", "💼tickal", "💼workflows", "💼adhoc"})
    r = refused(ow.retag, {"id": "K1", "tag": "⭐solo2"}, api, v2)
    check("W7 a tag only a KR carries is not pickable", r and "not an OKR tag" in r, r)

    api, v2 = world()
    api.store["K7"]["tags"] = ["💼tickal", "💼workflows", "⭐solo2"]
    ow.retag({"id": "O1", "tag": "2️⃣personal"}, api, v2)
    wrote = {b["id"]: b["tags"] for b in v2.batches[0]}
    check("W7 a KR whose pool tags only SHARE one with the O's follows, all its pool tags go",
          wrote.get("K7") == ["2️⃣personal", "⭐solo2"], wrote.get("K7"))

    api, v2 = world()
    api.store["U1"]["tags"] = ["⭐solo", "1️⃣work"]
    msg = ow.retag({"id": "U1", "tag": "1️⃣work"}, api, v2)
    check("W1 the same tags in another order: 'already', nothing written",
          msg == "🏷 Loose note already 1️⃣Work" and wrote_nothing(api, v2), msg)

    api, v2 = boom_world()
    r = refused(ow.retag, {"id": "K5", "tag": "💼tickal"}, api, v2)
    check("W11 v1 down (only the cache answered): retag refused, nothing written",
          r and "unreachable" in r and wrote_nothing(api, v2), r)

    api, v2 = world(ok=False)
    msg = ow.retag({"id": "K5", "tag": "💼tickal"}, api, v2)
    up = api.of("update_task")
    check("v2 refuses the batch: tags go v1", len(up) == 1
          and up[0][3] == {"tags": ["💼tickal"]}, up)

    api, v2 = world(token="")
    msg = ow.retag({"id": "K1", "tag": "1️⃣work"}, api, v2)
    up = api.of("update_task")
    check("no v2 token at all: a retag needs only a live read, and goes v1",
          len(up) == 1 and up[0][3] == {"tags": ["1️⃣work"]}, up)

    # ── 6. heal_and_tick ─────────────────────────────────────────────────────
    print("heal_and_tick")
    api, v2 = world()
    seen = []

    def is_done(p, t):
        seen.append((p, t))
        return True if t == "f" * 24 else None

    r = ow.heal_and_tick(api, v2, is_done=is_done)
    check("heals the stale O and ticks the KR whose original is done",
          (r.healed, r.ticked) == (1, 1), r)
    check("the done lookup is asked about the LINKED original only",
          seen == [("e" * 24, "f" * 24)], seen)
    check("complete_task is LIST id first (trap 2)", api.of("complete_task") == [
          ("complete_task", PID, "K9")], api.of("complete_task"))
    i_get = api.calls.index(("get_task", PID, "K9")) if ("get_task", PID, "K9") in api.calls else 99
    check("W6 the KR is RE-READ in the second hold, right before its tick",
          i_get < api.calls.index(("complete_task", PID, "K9")), api.calls[-3:])
    check("chip", r.chip == "🥅 1 span healed · 🔑 1 KR ticked · original done", r.chip)
    check("cache: the ticked KR leaves the open pools",
          cached("all_tasks", "K9") is None and cached(f"project_data_{PID}", "K9") is None)
    check("cache: okr_rows keeps it, as done (progress counts it)",
          cached("okr_rows", "K9")["status"] == 2)
    check("cache: okr_rows is still the WHOLE list, the heal's span in it (spans, then ticks)",
          len(MEM["okr_rows"]["rows"]) == 14
          and okr.span(cached("okr_rows", "O1")) == (d(9, 19), d(10, 14)),
          len(MEM["okr_rows"]["rows"]))
    check("cache: completed_tasks gets it first", MEM["completed_tasks"][0]["id"] == "K9"
          and MEM["completed_tasks"][0]["status"] == 2)

    api, v2 = world()
    r = ow.heal_and_tick(api, v2, is_done=lambda p, t: None)
    check("unknown (None) never ticks", r.ticked == 0 and not api.of("complete_task"), r)

    # W11 the tick race: heal B runs start to end while heal A sits between
    # its two holds (A's done lookups) - A's re-read sees B's tick
    api, v2 = world()
    inner = []

    def racing(p, t):
        if not inner:
            inner.append(ow.heal_and_tick(api, v2, is_done=is_done))
        return is_done(p, t)

    r = ow.heal_and_tick(api, v2, is_done=racing)
    check("W6 two overlapping heals tick a KR ONCE",
          len(api.of("complete_task")) == 1 and inner and inner[0].ticked == 1
          and r.ticked == 0, (api.of("complete_task"), inner, r))
    check("... the late one counts and banners only what it did",
          r.chip == "🥅 1 span healed" and "no longer open 1" in r.note, r)

    api, v2 = world()
    real_get = api.get_task                     # K9 ticked by hand after the read
    api.get_task = lambda p, t: dict(real_get(p, t), status=2) if t == "K9" else real_get(p, t)
    r = ow.heal_and_tick(api, v2, is_done=is_done)
    check("W6 a candidate no longer open at the re-read is not ticked",
          r.ticked == 0 and not api.of("complete_task") and "🔑" not in r.chip, r)
    for why, patch in (("won't do", lambda t: dict(t, status=-1)),
                       ("deleted", lambda t: dict(t, deleted=1)),
                       ("unreadable", None)):
        api, v2 = world()
        real_get = api.get_task

        def reread(p, t, _patch=patch, _real=real_get):
            if t != "K9":
                return _real(p, t)
            if _patch is None:
                raise RuntimeError("timeout")
            return _patch(_real(p, t))

        api.get_task = reread
        r = ow.heal_and_tick(api, v2, is_done=is_done)
        check(f"W6 a candidate {why} at the re-read is never ticked",
              r.ticked == 0 and not api.of("complete_task") and "🔑" not in r.chip, r)
    api, v2 = world()

    def complete_fails(pid, tid):
        api.calls.append(("complete_task", pid, tid))
        raise RuntimeError("500")

    api.complete_task = complete_fails
    r = ow.heal_and_tick(api, v2, is_done=is_done)
    check("W6 a tick whose complete_task FAILED is not counted, bannered or mirrored",
          r.ticked == 0 and "🔑" not in r.chip and cached("all_tasks", "K9") is not None
          and cached("okr_rows", "K9")["status"] == 0, (r, cached("okr_rows", "K9")))

    api, v2 = world()

    def hub_rewrites(p, t):
        MEM["okr_rows"] = {"list_id": PID, "name": "x", "rows": []}   # another writer
        return is_done(p, t)

    r = ow.heal_and_tick(api, v2, is_done=hub_rewrites)
    check("okr_rows left by ANOTHER writer between the holds: dropped, never overwritten "
          "with the older read", r.ticked == 1 and "okr_rows" not in MEM
          and cached("all_tasks", "K9") is None, (r, sorted(MEM)))

    api, v2 = world(completed=False)
    r = ow.heal_and_tick(api, v2, is_done=is_done)
    check("not writable: silent refusal, nothing written",
          r.chip == "" and r.note.startswith("refused") and not v2.batches
          and not api.of("complete_task"), r)

    api, v2 = world()
    with open(ow.LOCK_FILE, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        t0 = time.monotonic()
        r = ow.heal_and_tick(api, v2, is_done=is_done)
        waited = time.monotonic() - t0
        fcntl.flock(held, fcntl.LOCK_UN)
    check("the lock busy: skipped AT ONCE (never waits), nothing read",
          r.note.startswith("busy") and waited < 0.3
          and not api.calls, r)

    api, v2 = world()
    os.environ["okr_list_id"] = ""
    try:
        r = ow.heal_and_tick(api, v2, is_done=is_done)
    finally:
        os.environ["okr_list_id"] = PID
    check("OKRs off: nothing", r.note == "okr list off" and not api.calls, r)

    api, v2 = world()
    api.store["O1"] = cp(dict(api.store["O1"], **okr.write_fields(
        okr.from_task(api.store["O1"]), d(9, 19), d(10, 14))))
    MEM.pop("okr_complete", None)
    r = ow.heal_and_tick(api, v2, is_done=lambda p, t: False)
    check("nothing stale, nothing done: an empty chip", r.chip == "" and not v2.batches, r)
    check("C3 ... and its complete read is kept as okr_complete all the same",
          cached("okr_complete", "K4") is not None
          and len(MEM["okr_complete"]["rows"]) == len(fixture()[0]) + len(fixture()[1]),
          MEM.get("okr_complete"))

    b, bv2 = boom_world()
    r = ow.heal_and_tick(b, bv2, is_done=is_done)
    check("v1 down: the cache answers, which is never writable", r.chip == ""
          and r.note.startswith("refused"), r)

    # ── 7. spawn_heal ────────────────────────────────────────────────────────
    print("spawn_heal")
    spawned = []

    class _Sub:
        DEVNULL = -3

        @staticmethod
        def Popen(args, **kw):
            spawned.append((args, kw))

    real_sub = ow.subprocess
    ow.subprocess = _Sub
    try:
        if os.path.exists(ow.HEAL_STAMP):
            os.remove(ow.HEAL_STAMP)
        first = ow.spawn_heal()
        second = ow.spawn_heal()
        os.environ["okr_list_id"] = ""
        os.remove(ow.HEAL_STAMP)
        off = ow.spawn_heal()
        os.environ["okr_list_id"] = PID
        fresh = ow.spawn_heal(debounce_s=0.0001)
    finally:
        ow.subprocess = real_sub
        os.environ["okr_list_id"] = PID
    check("first open spawns, the next keystroke does not (debounce)",
          first is True and second is False, (first, second))
    check("OKRs off: no spawn", off is False)
    args, kw = spawned[0]
    check("the child: py.sh + xact.py xact:okr_heal",
          args[0] == "/bin/bash" and args[1].endswith("Scripts/py.sh")
          and args[2].endswith("Scripts/xact.py") and args[3] == "xact:okr_heal", args)
    check("detached: own session, TICKAL_DETACHED=1",
          kw.get("start_new_session") is True and kw["env"].get("TICKAL_DETACHED") == "1")
    check("never the render's stdout: a log file, stdin /dev/null (trap 9)",
          kw["stdout"] not in (None, sys.stdout) and hasattr(kw["stdout"], "write")
          and kw["stdin"] == _Sub.DEVNULL)
    check("spawns counted", len(spawned) == 2 and fresh is True, len(spawned))

    # ── 8. patch_cache, parse_list_answer ────────────────────────────────────
    print("patch_cache")
    api, v2 = world()
    snap = snapshot(api, v2)
    new = {"id": "n1", "projectId": PID, "title": "🔑 KR • n - TA", "parentId": "O1"}
    ow.patch_cache(snap, add=[new])
    ow.patch_cache(snap, add=[new])
    check("adding twice leaves one copy", sum(1 for t in MEM["all_tasks"] if t["id"] == "n1") == 1
          and sum(1 for t in MEM["okr_rows"]["rows"] if t["id"] == "n1") == 1)
    MEM["all_notes"] = [{"id": "K2", "title": "a note twin"}]
    ow.patch_cache(snap, done=["K2"])
    check("done leaves BOTH open pools", cached("all_tasks", "K2") is None
          and not MEM["all_notes"])
    check("... okr_rows keeps it as done, and the earlier add (the snap was folded)",
          cached("okr_rows", "K2")["status"] == 2 and cached("okr_rows", "n1") is not None)

    api, v2 = world()
    snap = snapshot(api, v2)
    MEM["okr_rows"] = {"list_id": PID, "name": "old", "rows": [
        {"id": "GONE", "title": "deleted in the app since"},
        dict(cached("okr_rows", "K2"), title="🔑 KR • stale title - TA")]}
    ow.patch_cache(snap, patches={"K1": {"title": "changed"}})
    rc = MEM["okr_rows"]
    check("W5 an older okr_rows is never patched: rebuilt from the live read",
          cached("okr_rows", "GONE") is None and cached("okr_rows", "K2")["title"]
          == "🔑 KR • Hub - TA" and rc["name"] == "🏆Goals Planning"
          and {t["id"] for t in rc["rows"]} == {i.id for i in snap.items}, rc["rows"][:2])
    check("... with the write over it", cached("okr_rows", "K1")["title"] == "changed")
    MEM["okr_rows"] = {"list_id": "other", "rows": [{"id": "K1", "title": "keep"}]}
    ow.patch_cache(snap, patches={"K1": {"title": "again"}})
    check("okr_rows of another list is replaced by this list's live read",
          MEM["okr_rows"]["list_id"] == PID and cached("okr_rows", "K1")["title"] == "again")
    ow.patch_cache(snap, patches={"K1": {"title": "x"}}, rebuild=False)
    check("rebuild=False drops okr_rows (the heal's second hold, a newer copy about)",
          "okr_rows" not in MEM and cached("all_tasks", "K1")["title"] == "x")

    # C3 okr_complete in the mirror
    api, v2 = world()
    snap = snapshot(api, v2)
    MEM["okr_complete"] = {"list_id": PID, "ts": 7, "rows": [
        dict(cp(fixture()[0][2]), status=0),                       # K2, open
        {"id": "NEWER", "title": "🔑 KR • another writer's", "status": 0}]}
    ow.patch_cache(snap, done=["K2"], rebuild=False)
    check("C3 rebuild=False: okr_complete is not replaced (a newer read may be about); "
          "only this write's tick goes in",
          MEM["okr_complete"]["ts"] == 7 and cached("okr_complete", "K2")["status"] == 2
          and cached("okr_complete", "NEWER")["status"] == 0, MEM["okr_complete"])
    MEM["okr_complete"]["list_id"] = "other"
    before = cp(MEM["okr_complete"])
    ow.patch_cache(snap, done=["NEWER"], rebuild=False)
    check("C3 ... another list's okr_complete is left alone", MEM["okr_complete"] == before)
    api, v2 = world(completed=False)
    isnap = snapshot(api, v2)
    MEM["okr_complete"] = {"list_id": PID, "ts": 7, "rows": [{"id": "OLD", "status": 2}]}
    before = cp(MEM["okr_complete"])
    ow.patch_cache(isnap, patches={"K1": {"title": "t"}}, add=[new])
    check("C3 a read missing completed KRs never writes okr_complete (its mirror rebuilds "
          "okr_rows only)", MEM["okr_complete"] == before
          and MEM["okr_rows"]["done_complete"] is False, MEM["okr_complete"])

    b, bv2 = boom_world()
    csnap = snapshot(b, bv2)
    ow.patch_cache(csnap, patches={"K1": {"title": "y"}})
    check("a CACHE read never becomes okr_rows", csnap.source == "cache"
          and "okr_rows" not in MEM, sorted(MEM))

    MEM.clear()
    ow.patch_cache(snap, patches={"K1": {"title": "x"}}, done=["K2"], add=[new])
    check("no caches at all: no crash, nothing invented but the rebuilt okr_rows "
          "and okr_complete (the snap is a complete read)",
          "all_tasks" not in MEM and "project_data_" + PID not in MEM
          and cached("okr_rows", "n1") is not None
          and cached("okr_complete", "n1") is not None, sorted(MEM))
    ow.patch_cache("not a snap", patches={"K1": {"title": "x"}})
    check("junk in: never raises, okr_rows dropped", "okr_rows" not in MEM)

    # W11 file-backed: the real cache module on a temp CACHE_DIR, so the
    # order and the mtimes browse._okr_fresh reads are the real ones
    mem_fns = (cache.get, cache.set, cache.invalidate, cache.age_seconds)
    real_dir = cache.CACHE_DIR
    order = []
    cache.get, _real_set, cache.invalidate, cache.age_seconds = _orig
    cache.set = lambda k, v: (order.append(k), _real_set(k, v))[1]
    cache.CACHE_DIR = os.path.join(TMP, "cache")
    try:
        o, dn = fixture()
        seed_cache(o, dn)
        for k, v in MEM.items():
            _real_set(k, v)
        stale = dict(MEM["okr_rows"], rows=[{"id": "GONE", "title": "x"}] + MEM["okr_rows"]["rows"])
        _real_set("okr_rows", stale)
        time.sleep(0.01)
        api = FakeAPI(o, dn)
        ow.schedule({"id": "K2", "action": "extend", "arg": 3}, api, FakeV2(api), today=TODAY)

        def mt(k):
            return os.stat(os.path.join(cache.CACHE_DIR, f"{k}.json")).st_mtime_ns
        check("file cache: okr_rows is the LAST write", order and order[-1] == "okr_rows"
              and order.count("okr_rows") == 1, order)
        check("file cache: okr_rows not older than any pool browse._okr_fresh compares",
              all(mt("okr_rows") >= mt(k) for k in ("all_tasks", f"project_data_{PID}",
                                                    "completed_tasks")))
        rc = cache.get("okr_rows")
        k2 = next((t for t in rc["rows"] if t["id"] == "K2"), {})
        check("file cache: rebuilt fresh - the stale row gone, the write in, the shape",
              all(t["id"] != "GONE" for t in rc["rows"]) and rc["done_complete"] is True
              and okr.span(k2) == (d(10, 5), d(10, 17)), (rc.get("done_complete"), okr.span(k2)))
    finally:
        cache.get, cache.set, cache.invalidate, cache.age_seconds = mem_fns
        cache.CACHE_DIR = real_dir

    check("list answer: blank = OFF", ow.parse_list_answer("  ") == "")
    check("list answer: a 24-hex id", ow.parse_list_answer(" " + "Ab" * 12 + " ") == "Ab" * 12)
    check("list answer: anything else = None", ow.parse_list_answer("my list") is None)

    # ── 9. the xact verbs ────────────────────────────────────────────────────
    print("xact")
    import xact
    trig, said = [], []
    real = (xact._run_trigger, xact._crm_say)
    xact._run_trigger = lambda name, arg=None: trig.append((name, arg))
    xact._crm_say = lambda m: said.append(m)

    def run(fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*a)
        return buf.getvalue()

    def b64(dct):
        return base64.b64encode(json.dumps(dct).encode()).decode()

    try:
        def refusing(spec):
            raise ow.Refusal("📅 nope")
        out = run(xact._okr_run, b64({"id": "x", "back": "ctx:okr:o:O1"}), refusing)
        check("a refusal: printed ONCE, never bannered", out == "📅 nope\n" and not said, out)
        check("... and the screen reopens via BrowseCtx (clean bar)",
              trig == [("BrowseCtx", "ctx:okr:o:O1")], trig)

        def crashing(spec):
            raise RuntimeError("boom")
        trig.clear()
        out = run(xact._okr_run, b64({"id": "x", "back": "okr"}), crashing)
        check("a crash: one toast, no banner", out == "🥅 Not written · RuntimeError: boom\n"
              and not said, out)
        check("a back that is not a ctx is never fired", not trig, trig)
        out = run(xact._okr_run, "not-b64!", crashing)
        check("a bad payload", out == "🥅 Bad payload · nothing written\n", out)

        real_sched = ow.schedule
        ow.schedule = lambda spec: f"📅 got {spec['id']}"
        old_argv = sys.argv
        try:
            sys.argv = ["xact.py", "xact:okr_sched:" + b64({"id": "K2", "action": "extend",
                                                             "arg": 1})]
            out = run(xact.main)
        finally:
            sys.argv = old_argv
            ow.schedule = real_sched
        check("main routes xact:okr_sched", out == "📅 got K2\n", out)

        # phase 3: xact:okr_add, and where a write may land instead of back
        real_add = ow.add_items
        trig.clear()
        ow.add_items = lambda spec: ow.Outcome(f"🥅 got {spec['names'][0]}",
                                               "ctx:okrtag:n1", ["n1"])
        try:
            sys.argv = ["xact.py", "xact:okr_add:" + b64({"kind": "O", "names": ["A"],
                                                           "back": "ctx:okr"})]
            out = run(xact.main)
        finally:
            sys.argv = old_argv
            ow.add_items = real_add
        check("main routes xact:okr_add; an Outcome prints its toast ONCE",
              out == "🥅 got A\n" and not said, (out, said))
        check("... and lands where the Outcome says (the tag picker), not the back",
              trig == [("BrowseCtx", "ctx:okrtag:n1")], trig)

        trig.clear()
        out = run(xact._okr_run, b64({"back": "ctx:okr:y:Y1"}),
                  lambda spec: ow.Outcome("🥅 ok", None, []))
        check("an Outcome with no reopen: the payload's back",
              out == "🥅 ok\n" and trig == [("BrowseCtx", "ctx:okr:y:Y1")], (out, trig))

        def planned_already(spec):
            raise ow.Refusal("🥅 Already in the plan · 🔑 Ship it", reopen="ctx:okr:o:O1")
        trig.clear()
        out = run(xact._okr_run, b64({"back": "ctx:okrimport:task:p:t"}), planned_already)
        check("a Refusal that names a landing: toasted once, lands THERE",
              out == "🥅 Already in the plan · 🔑 Ship it\n" and not said
              and trig == [("BrowseCtx", "ctx:okr:o:O1")], (out, trig))

        def odd_reopen(spec):
            raise ow.Refusal("🥅 no", reopen="okr")
        trig.clear()
        run(xact._okr_run, b64({"back": "ctx:okr"}), odd_reopen)
        check("a reopen that is not a ctx is never fired: the back instead",
              trig == [("BrowseCtx", "ctx:okr")], trig)

        # end to end over the fakes: the real writer through the real wrapper
        api, v2 = world()
        trig.clear()
        out = run(xact._okr_run, b64({"kind": "O", "parent": None, "names": ["Travel plans"],
                                      "code": None, "link": None, "then": "tag",
                                      "back": "ctx:okr"}),
                  lambda spec: ow.add_items(spec, api, v2))
        check("okr_add end to end: one toast, the new O's tag picker",
              out == "🥅 Added · 🥅 Travel plans · code TP\n"
              and trig == [("BrowseCtx", "ctx:okrtag:new1")] and not said, (out, trig))
        trig.clear()
        out = run(xact._okr_run, b64({"kind": "KR", "parent": "O2", "names": ["Ship"],
                                      "link": {"to": "task", "pid": "e" * 24, "tid": "f" * 24},
                                      "back": "ctx:okrimport:task:x:y"}),
                  lambda spec: ow.add_items(spec, api, v2))
        check("okr_add end to end, already planned: one toast, K9's screen",
              out == "🥅 Already in the plan · 🔑 Ship it\n"
              and trig == [("BrowseCtx", "ctx:okr:o:O1")], (out, trig))
        api, v2 = world()
        trig.clear()
        out = run(xact._okr_run, b64({"kind": "KR", "parent": "O2", "names": ["Zapier"],
                                      "link": {"to": "task", "pid": "b" * 24, "tid": "c" * 24},
                                      "back": "ctx:okr:o:O2"}),
                  lambda spec: ow.add_items(spec, api, v2))
        check("B4 okr_add end to end, an imported KR: the other levels' toast, the O's "
              "new code stamped, back to the O",
              out == "🥅 Added · 🔑 Zapier under Workflows · code W\n"
              and trig == [("BrowseCtx", "ctx:okr:o:O2")] and not said, (out, trig))

        real_krs = ow.add_krs
        trig.clear()
        ow.add_krs = lambda spec: f"🔑 got {spec['oid']}"
        try:
            sys.argv = ["xact.py", "xact:okr_addkr:" + b64({"oid": "O1", "names": ["a"],
                                                             "back": "ctx:okr:o:O1"})]
            out = run(xact.main)
        finally:
            sys.argv = old_argv
            ow.add_krs = real_krs
        check("xact:okr_addkr still routes (phase-2 rows), a plain toast, the back",
              out == "🔑 got O1\n" and trig == [("BrowseCtx", "ctx:okr:o:O1")], (out, trig))

        real_heal = ow.heal_and_tick
        ow.heal_and_tick = lambda: ow.HealResult(1, 0, "🥅 1 span healed", "healed 1")
        try:
            os.environ["TICKAL_DETACHED"] = "1"
            out = run(xact.okr_heal)
            check("detached heal: a log line, and ONE banner for the change",
                  "okr_heal: healed 1" in out and said == ["🥅 1 span healed"], (out, said))
            os.environ.pop("TICKAL_DETACHED")
            said.clear()
            out = run(xact.okr_heal)
            check("on an Alfred road: the chip is the toast, no banner",
                  out == "🥅 1 span healed\n" and not said, (out, said))
            ow.heal_and_tick = lambda: ow.HealResult(0, 0, "", "refused")
            out = run(xact.okr_heal)
            check("nothing changed: silent (no toast)", out == "" and not said, out)
            os.environ["TICKAL_DETACHED"] = "1"
            out = run(xact.okr_heal)
            check("detached, nothing changed: a log line, NO banner",
                  "okr_heal: refused" in out and not said, (out, said))
        finally:
            ow.heal_and_tick = real_heal
            os.environ.pop("TICKAL_DETACHED", None)

        saved = {}
        real_cfg = (xact.cfg.load, xact.cfg.save, xact._ask, xact._api)
        xact.cfg.load = lambda: dict(saved)
        xact.cfg.save = lambda data: saved.update(data)
        # RECORD, never raise: a raise inside the verb's own try/except (the
        # people_setlist kanban flip swallows everything) would pass silently
        touched = []

        class _NoFlip:
            def __getattr__(self, name):
                return lambda *a, **k: touched.append((name, a, k))
        xact._api = lambda: (touched.append(("_api",)), _NoFlip())[1]
        try:
            said.clear()
            xact._ask = lambda *a, **k: "b" * 24
            out = run(xact.okr_setlist)
            check("setlist: an id is saved, no viewMode flip, no client at all",
                  saved.get("okr_list_id") == "b" * 24 and not touched, touched)
            check("W9 setlist PRINTS its outcome (its road ends at End), no banner",
                  out.startswith("🥅 OKR list set · " + "b" * 24) and not said, (out, said))
            xact._ask = lambda *a, **k: ""
            out = run(xact.okr_setlist)
            check("setlist: blank saves OFF", saved.get("okr_list_id") == ""
                  and out.startswith("🥅 OKRs off") and not said, out)
            saved["okr_list_id"] = "keep"
            xact._ask = lambda *a, **k: "not an id"
            out = run(xact.okr_setlist)
            check("setlist: junk saves nothing", saved["okr_list_id"] == "keep"
                  and "nothing saved" in out and not said, out)
            xact._ask = lambda *a, **k: None
            out = run(xact.okr_setlist)
            check("setlist: Esc cancels", saved["okr_list_id"] == "keep"
                  and out == "🥅 Cancelled\n" and not said, out)
            check("setlist: no client was built or used on any road", not touched, touched)
        finally:
            xact.cfg.load, xact.cfg.save, xact._ask, xact._api = real_cfg
    finally:
        xact._run_trigger, xact._crm_say = real

    # ── 10. phase 5: ⏳ countdowns ───────────────────────────────────────────
    print("countdowns")
    SEP20 = d(9, 20)
    items = okr.items_from(fixture()[0] + fixture()[1])
    n = [0]

    def nid():
        n[0] += 1
        return f"{n[0]:024x}"

    def ours(iid, name, date_int, status=0, cid=None, **kw):
        c = {"id": cid or ("c" + iid.lower()).ljust(24, "0"), "type": 4, "name": name,
             "date": date_int, "remark": ow.CD_MARK + iid, "status": status,
             "sortOrder": -5, "etag": "et", "showRemark": False}
        c.update(kw)
        return c

    check("targets: an open O that has STARTED, on its wanted end; not-yet-started, "
          "done and undated ones have none",
          [(it.id, e) for it, e in okr.countdown_targets(items, SEP20)]
          == [("O1", d(10, 14))], okr.countdown_targets(items, SEP20))
    check("targets: the day before the start there is none",
          okr.countdown_targets(items, d(9, 18)) == [])
    check("targets: one running late keeps it (counts the days since)",
          [it.id for it, _e in okr.countdown_targets(items, d(11, 1))] == ["O1", "O2"])

    p = ow.countdown_plan(items, [{"id": "x" * 24, "name": "Mama", "sortOrder": 100}],
                          {}, SEP20, nid)
    a = p.add[0] if p.add else {}
    check("plan: mints ONE for the started O - ⏳ kind 4, its inclusive end, named with its glyph",
          len(p.add) == 1 and not p.update and not p.archive
          and a["name"] == "🥅 TickAL" and a["date"] == 20261014 and a["type"] == 4
          and a["repeatFlag"] is None, p)
    check("plan: marked as ours in the remark, the remark hidden, no reminders, on top",
          a.get("remark") == ow.CD_MARK + "O1" and a.get("showRemark") is False
          and a.get("reminders") == [] and a.get("sortOrder") == 100 - ow.CD_STEP
          and ow.cd_owner(a) == "O1", a)
    check("plan: the registry remembers what was minted",
          p.registry == {"O1": {"cid": a.get("id"), "by_us": False}}, p.registry)
    mama = {"id": "x" * 24, "name": "Mama", "remark": "", "status": 0}
    p = ow.countdown_plan(items, [mama, ours("O1", "🥅 TickAL", 20261014)], {}, SEP20, nid)
    check("plan: in step = nothing to write", not (p.add or p.update or p.archive), p)
    p = ow.countdown_plan(items, [ours("O1", "🥅 Old name", 20261001)], {}, SEP20, nid)
    check("plan: a moved end or a new name updates the WHOLE listed entity",
          p.update == [ours("O1", "🥅 TickAL", 20261014)] and not p.add, p)
    p = ow.countdown_plan(items, [ours("O2", "🥅 Workflows", 20261001)], {}, SEP20, nid)
    check("plan: one not started yet is kept in step, never archived for being early",
          [c["date"] for c in p.update] == [20261020] and not p.archive
          and [c["name"] for c in p.add] == ["🥅 TickAL"], p)
    p = ow.countdown_plan(items, [ours("O3", "🥅 Other things", 20260830)], {}, SEP20, nid)
    check("plan: a DONE objective's countdown is archived, by us",
          [(c["id"], c["status"]) for c in p.archive] == [(ours("O3", "", 0)["id"], 1)]
          and p.registry.get("O3", {}).get("by_us") is True, p)
    p = ow.countdown_plan(items, [ours("GONE", "🥅 Deleted", 20261201)], {}, SEP20, nid)
    check("plan: one whose objective left the plan is archived too",
          [c["name"] for c in p.archive] == ["🥅 Deleted"], p)
    p = ow.countdown_plan(items, [ours("O4", "🥅 ✨", 20261201)], {}, SEP20, nid)
    check("plan: an objective that lost its dates loses its countdown",
          [c["name"] for c in p.archive] == ["🥅 ✨"], p)
    p = ow.countdown_plan(items, [], {"O1": {"cid": "9" * 24, "by_us": False}}, SEP20, nid)
    check("plan: minted before and gone now = Vex removed it: never minted again",
          not p.add, p)
    p = ow.countdown_plan(items, [], {"O1": {"cid": "9" * 24, "by_us": True}}, SEP20, nid)
    check("plan: archived by US and no longer listed: minted afresh",
          [c["name"] for c in p.add] == ["🥅 TickAL"]
          and p.registry["O1"]["by_us"] is False, p)
    arch = ours("O1", "🥅 TickAL", 20261001, status=1)
    p = ow.countdown_plan(items, [arch], {"O1": {"cid": arch["id"], "by_us": True}}, SEP20, nid)
    check("plan: archived by us and still listed: brought back, on the new end",
          [(c["status"], c["date"]) for c in p.update] == [(0, 20261014)] and not p.add, p)
    p = ow.countdown_plan(items, [arch], {}, SEP20, nid)
    check("plan: archived by VEX (no by_us record): left alone, nothing minted beside it",
          not (p.add or p.update or p.archive), p)
    edited = dict(ours("O1", "🥅 TickAL", 20261001), remark="my words")
    p = ow.countdown_plan(items, [edited], {"O1": {"cid": edited["id"], "by_us": False}},
                          SEP20, nid)
    check("plan: a remark Vex edited: the registry still knows it is ours",
          [c["id"] for c in p.update] == [edited["id"]] and not p.add, p)
    live1 = ours("O1", "🥅 TickAL", 20261014)
    p = ow.countdown_plan(items, [live1], {}, SEP20, nid)
    check("plan: a live countdown of ours the registry lost (a failed save) is back-filled",
          p.known == {"O1": {"cid": live1["id"], "by_us": False}}
          and p.registry == p.known and not (p.add or p.update or p.archive), p)
    p = ow.countdown_plan(items, [live1], {"O1": {"cid": live1["id"], "by_us": True}},
                          SEP20, nid)
    check("plan: a stale by_us on a LIVE countdown is cleared (a later archive by Vex holds)",
          p.known["O1"]["by_us"] is False, p)
    p2 = ow.countdown_plan(items, [dict(live1, status=1)], p.known, SEP20, nid)
    check("... and Vex archiving it then is respected: nothing un-archived, nothing minted",
          not (p2.add or p2.update or p2.archive), p2)
    p = ow.countdown_plan(items, [], {}, SEP20, nid)
    check("plan: an add waits for the ack - it is in registry, not in known",
          "O1" in p.registry and "O1" not in p.known, p)
    retitled = okr.items_from([D("O1", "TickAL (retitled)", d(9, 19), d(10, 14))]
                              + fixture()[0][1:] + fixture()[1])
    p = ow.countdown_plan(retitled, [live1], {}, SEP20, nid)
    check("plan: an objective retitled into a plain task (or a KR) loses its countdown",
          [c["id"] for c in p.archive] == [live1["id"]]
          and p.known["O1"] == {"cid": live1["id"], "by_us": True}, p)

    api, v2 = world()
    snap = snapshot(api, v2)
    v2.cds = []
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: writes the plan, says so", r[0] == "⏳ 1 countdown added"
          and len(v2.cds) == 1 and v2.cds[0]["name"] == "🥅 TickAL", r)
    reg = json.load(open(ow.CD_REGISTRY))
    check("sync: the registry is saved after the write", list(reg) == ["O1"], reg)
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: a second pass is quiet", r[0] == "" and "in step" in r[1], r)
    os.remove(ow.CD_REGISTRY)
    api, v2 = world()
    snap = snapshot(api, v2)
    v2.cds, v2.cd_ok = [], False
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: a refused batch saves NO add record (it would block the mint for good)",
          r[0] == "" and "refused" in r[1] and not os.path.exists(ow.CD_REGISTRY), r)
    api, v2 = world()
    snapd = snapshot(api, v2)
    v2.cds = [ours("O3", "🥅 Other things", 20260830)]
    v2.cd_ok = False
    r = ow.sync_countdowns(snapd, v2, SEP20)
    reg = json.load(open(ow.CD_REGISTRY)) if os.path.exists(ow.CD_REGISTRY) else {}
    check("sync: a refused batch still saves its ARCHIVE records (by_us - safe either way)",
          reg.get("O3", {}).get("by_us") is True and "O1" not in reg, reg)
    os.remove(ow.CD_REGISTRY)
    v2.cd_ok = True
    v2.cds = [ours("O1", "🥅 TickAL", 20261014)]
    r = ow.sync_countdowns(snapd, v2, SEP20)
    reg = json.load(open(ow.CD_REGISTRY)) if os.path.exists(ow.CD_REGISTRY) else {}
    check("sync: in step, but the registry lacked the live one: saved anyway",
          r[0] == "" and "in step" in r[1] and reg.get("O1", {}).get("by_us") is False, (r, reg))
    os.remove(ow.CD_REGISTRY)
    api, v2 = world()
    snap = snapshot(api, v2)
    v2.cds, v2.cd_ok = [], True
    v2.cds, v2.cd_ok = None, True
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: an unreadable list writes nothing", r[0] == "" and "unreadable" in r[1]
          and not v2.cd_batches, r)
    v2.cds = []
    snap.done_complete = False
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: a read missing completed items writes nothing (THE WRITER RULE)",
          r[0] == "" and not v2.cd_batches, r)
    snap.done_complete = True
    v2.token = ""
    r = ow.sync_countdowns(snap, v2, SEP20)
    check("sync: no v2 token, no countdowns", r[0] == "" and "token" in r[1], r)
    MEM["countdowns"] = [{"id": "x" * 24, "name": "Mama", "status": 0}]
    api, v2 = world()
    MEM["countdowns"] = [{"id": "x" * 24, "name": "Mama", "status": 0},
                         ours("O3", "🥅 Other things", 20260830)]
    v2.cds = cp(MEM["countdowns"])
    r = ow.sync_countdowns(snapshot(api, v2), v2, SEP20)
    check("sync: the countdowns cache follows - the new one in, the archived one out",
          sorted(c["name"] for c in MEM["countdowns"]) == ["Mama", "🥅 TickAL"], MEM["countdowns"])
    os.remove(ow.CD_REGISTRY)

    api, v2 = world()
    v2.cds = []
    r = ow.heal_and_tick(api, v2, is_done=lambda p_, t: None, today=SEP20)
    check("heal: the countdown rides the heal pass, off the HEALED span, in the chip",
          r.chip == "🥅 1 span healed · ⏳ 1 countdown added"
          and v2.cds[0]["date"] == 20261014 and "countdowns: " in r.note, (r, v2.cds))
    os.remove(ow.CD_REGISTRY)
    api, v2 = world()
    v2.cds = [ours("O1", "🥅 TickAL", 20261014)]
    out = attempt(ow.schedule, {"id": "K2", "action": "extend", "arg": 2}, api, v2, SEP20)
    check("schedule: an extend that moves the O's end moves its countdown, said in the toast",
          isinstance(out, str) and out.endswith("· ⏳ 1 countdown updated")
          and v2.cds[0]["date"] == 20261016, (out, v2.cds))
    if os.path.exists(ow.CD_REGISTRY):
        os.remove(ow.CD_REGISTRY)

    # ── 11. phase 5: ↪️ the quarter carry-over ────────────────────────────────
    print("carry")
    check("closing quarter: inside the last two weeks = the quarter now ending",
          okr.closing_quarter(d(9, 17)).start == d(7, 1))
    check("closing quarter: earlier = the quarter before (a late review still closes it)",
          okr.closing_quarter(d(10, 3)).start == d(7, 1)
          and okr.closing_quarter(d(9, 16)).start == d(4, 1))
    check("closing quarter: a pin wins", okr.closing_quarter(d(9, 17), d(2, 3)).start == d(1, 1))
    check("carry start: the next quarter's first day, or today when that is gone",
          okr.carry_start(d(9, 30), d(9, 20)) == d(10, 1)
          and okr.carry_start(d(9, 30), d(10, 3)) == d(10, 3))
    left = okr.carry_candidates(items, d(9, 30))
    check("candidates: open dated LEAVES ending by the quarter's end, end order "
          "(no parent with dated KRs, no done, no undated)",
          [x.id for x in left] == ["K5", "K7"], [x.id for x in left])
    solo = okr.items_from([D("OX", "🥅 O • Hand dated", d(9, 1), d(9, 2))])
    check("candidates: a Y/O dated by hand with no dated child IS a leaf",
          [x.id for x in okr.carry_candidates(solo, d(9, 30))] == ["OX"])

    api, v2 = world()
    out = attempt(ow.carry, {"id": "K5", "action": "carry", "arg": "2026-10-01"},
                  api, v2, SEP20)
    check("carry: rides schedule's date move (ripple, heals, its toast)",
          out == "📅 Side quest → Oct 1 - Oct 2 · 2 moved along · 1 healed"
          and okr.span(api.store["K5"]) == (d(10, 1), d(10, 2))
          and okr.span(api.store["K7"]) == (d(10, 3), d(10, 4))
          and okr.span(api.store["O1"]) == (d(9, 19), d(10, 25)),
          (out, {k: okr.span(api.store[k]) for k in ("K5", "K7", "K2", "O1")}))
    api, v2 = world()
    out = attempt(ow.carry, {"id": "K7", "action": "wontdo"}, api, v2, SEP20)
    ab = v2.abandoned[0] if v2.abandoned else {}
    check("won't do: v2 abandon of the LIVE object with a stamped completedTime",
          isinstance(out, str) and out.startswith("🚫 Won't do: Stray")
          and ab.get("id") == "K7" and ab.get("completedTime", "").endswith(".000+0000"), out)
    check("won't do: the wontdo log gets it; the open pools lose it",
          (MEM.get("wontdo_tasks") or [{}])[0].get("id") == "K7"
          and MEM["wontdo_tasks"][0]["status"] == -1
          and cached("all_tasks", "K7") is None and cached(f"project_data_{PID}", "K7") is None)
    check("won't do: okr_rows shows it 🚫 until the next live read (⇧ undo on the hub)",
          cached("okr_rows", "K7")["status"] == -1)
    api, v2 = world()
    out = attempt(ow.carry, {"id": "K2", "action": "wontdo"}, api, v2, SEP20)
    check("won't do: the last KR gone, its O heals in the same hold",
          isinstance(out, str) and "1 parent healed" in out
          and okr.span(api.store["O1"]) == (d(9, 19), d(10, 4)), (out, api.store.get("O1")))
    api, v2 = world(token="")
    check("won't do: no v2 token = refused, nothing written",
          "Attachment Login" in (refused(ow.carry, {"id": "K7", "action": "wontdo"},
                                         api, v2, SEP20) or "") and wrote_nothing(api, v2))
    api, v2 = world()
    v2.abandon_ok = False
    check("won't do: TickTick refusing = refused, no mirror",
          "refused" in (refused(ow.carry, {"id": "K7", "action": "wontdo"}, api, v2, SEP20) or "")
          and cached("all_tasks", "K7") is not None)
    trip = [D("OT", "🥅 O • Trip", d(9, 1), d(9, 10)),
            D("KT", "🔑 KR • Book it", parent="OT")]
    api, v2 = world()
    for t in trip:
        api.store[t["id"]] = cp(t)
    check("won't do: a hand-dated O with open (undated) KRs is refused - they would be stranded",
          "1 open item under it" in (refused(ow.carry, {"id": "OT", "action": "wontdo"},
                                               api, v2, SEP20) or "")
          and not v2.abandoned, v2.abandoned)
    step = okr.items_from([D("OS", "🥅 O • Stepped", d(9, 1), d(9, 10)),
                           D("ST", "Book flights", d(9, 1), d(9, 10), "OS")])
    check("candidates: an unprefixed step under an O is a leftover (pace counts it)",
          [x.id for x in okr.carry_candidates(step, d(9, 30))] == ["ST"])
    api, v2 = world()
    check("a parent with dated KRs is not decided on its own",
          "follows its KRs" in (refused(ow.carry, {"id": "O1", "action": "wontdo"},
                                         api, v2, SEP20) or "") and wrote_nothing(api, v2))
    check("a done item is closed already",
          "closed already" in (refused(ow.carry, {"id": "K4", "action": "someday"},
                                        api, v2, SEP20) or ""))
    check("an unknown action is refused",
          refused(ow.carry, {"id": "K7", "action": "later"}, api, v2, SEP20) == "↪️ Nothing to decide")
    api, v2 = world()
    out = attempt(ow.carry, {"id": "K2", "action": "someday"}, api, v2, SEP20)
    up = api.of("update_task")[0] if api.of("update_task") else ()
    check("someday: v1 nulls both dates (the proven clear)",
          up and up[1] == "K2" and up[3] == {"startDate": None, "dueDate": None}, up)
    check("someday: toast + the O heals onto what is left",
          isinstance(out, str) and out.startswith("💤 Hub → someday")
          and "1 parent healed" in out
          and okr.span(api.store["O1"]) == (d(9, 19), d(10, 4)), (out, api.store.get("O1")))
    check("someday: the caches show it undated",
          cached("all_tasks", "K2")["startDate"] is None
          and cached("okr_rows", "K2")["dueDate"] is None)
    api, v2 = world()
    check("someday: an undated one is off the timeline already",
          "already" in (refused(ow.carry, {"id": "K3", "action": "someday"}, api, v2, SEP20) or ""))

    # ── 12. phase 5: okr.capacity ─────────────────────────────────────────────
    print("capacity")
    rows = [D("C1", "🔑 KR • a", d(9, 21), d(9, 22)),
            D("C2", "🔑 KR • b", d(10, 10), d(10, 12)),
            D("C3", "🔑 KR • c", d(10, 18), d(10, 20)),
            D("C4", "🔑 KR • d", d(9, 1), d(9, 2), status=2,
              completedTime="2026-09-10T08:00:00.000+0000"),
            D("C5", "🔑 KR • e", d(8, 1), d(8, 2), status=2,
              completedTime="2026-08-01T08:00:00.000+0000"),
            D("C6", "🔑 KR • f", d(9, 25), d(9, 26), status=-1),
            D("C7", "🥅 O • not a KR", d(9, 21), d(9, 30))]
    c = okr.capacity(okr.items_from(rows), SEP20)
    check("capacity: due in the next 4 wks (won't-do and non-KRs out) vs ticked in the last 4",
          (c.planned, c.done, c.weeks) == (2, 1, 4), c)
    check("capacity: rates read like a person says them",
          (okr.rate_txt(2, 4), okr.rate_txt(4, 4), okr.rate_txt(0, 4), okr.rate_txt(7, 4))
          == ("0.5/wk", "1/wk", "0/wk", "1.8/wk"))

    # ── 13. the xact carry verb ──────────────────────────────────────────────
    print("xact carry")
    trig, said = [], []
    real = (xact._run_trigger, xact._crm_say)
    xact._run_trigger = lambda name, arg=None: trig.append((name, arg))
    xact._crm_say = lambda m: said.append(m)
    real_carry = ow.carry
    ow.carry = lambda spec: f"↪️ got {spec['action']}"
    old_argv = sys.argv
    try:
        sys.argv = ["xact.py", "xact:okr_carry:" + b64({"id": "K7", "action": "wontdo",
                                                         "back": "ctx:okrcarry:2026-07-01"})]
        out = run(xact.main)
        check("main routes xact:okr_carry, lands back on the pinned list (BrowseCtx)",
              out == "↪️ got wontdo\n" and trig == [("BrowseCtx", "ctx:okrcarry:2026-07-01")]
              and not said, (out, trig))
    finally:
        sys.argv = old_argv
        ow.carry = real_carry
        xact._run_trigger, xact._crm_say = real
finally:
    cache.get, cache.set, cache.invalidate, cache.age_seconds = _orig


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
