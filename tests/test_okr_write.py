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

    def create_task(self, title, project_id=None, parent_id=None, tags=None, **kw):
        self.n += 1
        tid = f"new{self.n}"
        self.calls.append(("create_task", title, project_id, parent_id, tags))
        t = {"id": tid, "projectId": project_id, "title": title,
             "tags": list(tags or []), "parentId": parent_id, "status": 0,
             "sortOrder": 1000 - self.n * 100, "isAllDay": False}
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
    check("okr_rows REBUILT from the live read: its shape, the done KR, no seed detail",
          rc.get("list_id") == PID and rc.get("name") == "🏆Goals Planning"
          and rc.get("done_complete") is True and "detail" not in rc
          and cached("okr_rows", "K4")["status"] == 2, sorted(rc))
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
    r = ow.heal_and_tick(api, v2, is_done=lambda p, t: False)
    check("nothing stale, nothing done: an empty chip", r.chip == "" and not v2.batches, r)

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

    b, bv2 = boom_world()
    csnap = snapshot(b, bv2)
    ow.patch_cache(csnap, patches={"K1": {"title": "y"}})
    check("a CACHE read never becomes okr_rows", csnap.source == "cache"
          and "okr_rows" not in MEM, sorted(MEM))

    MEM.clear()
    ow.patch_cache(snap, patches={"K1": {"title": "x"}}, done=["K2"], add=[new])
    check("no caches at all: no crash, nothing invented but the rebuilt okr_rows",
          "all_tasks" not in MEM and "project_data_" + PID not in MEM
          and cached("okr_rows", "n1") is not None)
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
finally:
    cache.get, cache.set, cache.invalidate, cache.age_seconds = _orig


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
