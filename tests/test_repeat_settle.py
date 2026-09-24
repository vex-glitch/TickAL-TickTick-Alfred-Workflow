#!/usr/bin/env python3
"""repeat_settle - resend a repeating task's completed copy so the Mac app keeps it.

2026-09-13: finishing 🌆 Shutdown through our road emptied its calendar slot.
The app drops the server-made completed copy on its first delivery and saves
it on a second one. These tests pin the SAFETY of the resend: it only ever
writes a status-2 copy of the task just completed, never the series.

    python3 tests/test_repeat_settle.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["TICKAL_NO_SETTLE"] = "1"

import repeat_settle as rs  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


SINCE = rs._epoch("2026-09-13T19:42:27")
SERIES = {"id": "S", "projectId": "P", "title": "🌆 Shutdown", "status": 0,
          "repeatFlag": "RRULE:FREQ=DAILY;INTERVAL=1", "startDate": "2026-09-14T20:00:00.000+0000"}
COPY = {"id": "C", "projectId": "P", "title": "🌆 Shutdown", "status": 2, "repeatTaskId": "S",
        "completedTime": "2026-09-13T19:42:27.699+0000", "startDate": "2026-09-13T20:00:00.000+0000",
        "sortOrder": -1152933599234621439, "reminders": [{"id": "r1", "trigger": "TRIGGER:PT0S"}]}
OLD = dict(COPY, id="C0", completedTime="2026-09-12T21:06:22.513+0000")
OTHER = dict(COPY, id="X", repeatTaskId="Z")
REOPENED = dict(COPY, id="C9", status=0)
SELF = dict(COPY, id="S", repeatTaskId="S")

# ── pick_copies
got = rs.pick_copies([COPY, OLD, OTHER, REOPENED, SELF], "S", SINCE)
check("only the copy this complete minted", [c["id"] for c in got] == ["C"], [c["id"] for c in got])
check("an empty or failed feed picks nothing",
      rs.pick_copies(None, "S", SINCE) == [] and rs.pick_copies([], "S", SINCE) == [])
check("a little clock skew still counts",
      [c["id"] for c in rs.pick_copies([dict(COPY, completedTime="2026-09-13T19:41:30.000+0000")], "S", SINCE)] == ["C"])
check("a copy with no completedTime is never guessed",
      rs.pick_copies([dict(COPY, completedTime=None)], "S", SINCE) == [])

# ── nudge_body
b = rs.nudge_body(dict(COPY, _local="x"))
check("the resend is a REAL change (sortOrder by one)", b["sortOrder"] == COPY["sortOrder"] - 1, b["sortOrder"])
check("everything else goes back as it was",
      {k: v for k, v in b.items() if k != "sortOrder"} == {k: v for k, v in COPY.items() if k != "sortOrder"})
check("private cache keys are not sent", "_local" not in b)
check("status stays completed", b["status"] == 2)


class FakeAPI:
    def __init__(self, task):
        self.task, self.gets = task, 0

    def get_task(self, pid, tid):
        self.gets += 1
        return dict(self.task)


class FakeV2:
    def __init__(self, feeds, ok=True):
        self.feeds, self.ok, self.reads, self.writes = list(feeds), ok, 0, []

    def project_completed(self, pid, days=120, limit=500):
        self.reads += 1
        return self.feeds.pop(0) if self.feeds else []

    def update_tasks(self, tasks, fresh=None, **kw):
        import api as _api_mod                 # the real gate, as api_v2 applies it
        if fresh is not True and not all(_api_mod.is_fresh(b) for b in tasks):
            return False
        self.writes.append(tasks)
        return self.ok


naps = []
nap = naps.append

# ── settle: the Shutdown case
api, v2 = FakeAPI(SERIES), FakeV2([[OLD, COPY]])
msg = rs.settle("P", "S", SINCE, api, v2, sleep=nap)
check("the new copy is resent once", len(v2.writes) == 1 and [t["id"] for t in v2.writes[0]] == ["C"], v2.writes)
check("the series is never written", all(t["id"] != "S" for w in v2.writes for t in w))
check("the verdict says so", msg.startswith("resent 1 copy of '🌆 Shutdown'"), msg)

# the copy is not in the feed yet on the first read
api, v2 = FakeAPI(SERIES), FakeV2([[OLD], [], [COPY]])
naps.clear()
rs.settle("P", "S", SINCE, api, v2, sleep=nap)
check("a copy that shows up late is still caught", v2.reads == 3 and len(v2.writes) == 1, (v2.reads, v2.writes))
check("and the reads are spaced out", naps == list(rs.WAITS), naps)

# never there
api, v2 = FakeAPI(SERIES), FakeV2([[], [], []])
msg = rs.settle("P", "S", SINCE, api, v2, sleep=nap)
check("no copy: gives up after the last wait, writes nothing",
      v2.reads == len(rs.WAITS) and not v2.writes and msg.startswith("no copy"), (v2.reads, msg))

# a plain task: one read, nothing else
plain = {"id": "S", "projectId": "P", "status": 2, "repeatFlag": None}
api, v2 = FakeAPI(plain), FakeV2([[COPY]])
msg = rs.settle("P", "S", SINCE, api, v2, sleep=nap)
check("a non-repeating task costs one read and writes nothing",
      api.gets == 1 and v2.reads == 0 and not v2.writes and msg.startswith("skip"), msg)


class Boom(FakeAPI):
    def get_task(self, pid, tid):
        raise RuntimeError("offline")


api, v2 = Boom(SERIES), FakeV2([[COPY]])
logged = []
msg = rs.settle("P", "S", SINCE, api, v2, sleep=nap, log=logged.append)
check("an unreadable series writes nothing", not v2.writes and msg.startswith("skip"), msg)
check("and says why in the log (the only trace of a vanished routine)",
      logged == [msg] and "read failed (RuntimeError)" in msg, logged)

# a plain task stays out of the log
logged = []
rs.settle("P", "S", SINCE, FakeAPI(plain), FakeV2([]), sleep=nap, log=logged.append)
check("a plain completion adds no log line", logged == [], logged)


class FlakyV2(FakeV2):
    def __init__(self, feeds, oks):
        super().__init__(feeds)
        self.oks = list(oks)

    def update_tasks(self, tasks, fresh=None, **kw):
        import api as _api_mod
        if fresh is not True and not all(_api_mod.is_fresh(b) for b in tasks):
            return False
        self.writes.append(tasks)
        return self.oks.pop(0) if self.oks else False


# the first resend fails: the remaining waits try again
v2 = FlakyV2([[COPY], [COPY], [COPY]], [False, True])
msg = rs.settle("P", "S", SINCE, FakeAPI(SERIES), v2, sleep=nap)
check("a failed resend is retried on the next wait", len(v2.writes) == 2 and msg.startswith("resent"), (len(v2.writes), msg))
v2 = FlakyV2([[COPY], [COPY], [COPY]], [False, False, False])
logged = []
msg = rs.settle("P", "S", SINCE, FakeAPI(SERIES), v2, sleep=nap, log=logged.append)
check("only after every wait does it log RESEND FAILED",
      len(v2.writes) == len(rs.WAITS) and msg.startswith("RESEND FAILED") and logged == [msg], (len(v2.writes), msg))
check("every retry still only writes the copy", all(t["id"] == "C" for w in v2.writes for t in w))

# the series moved lists: the feed is read on its live list
seen = []
api = FakeAPI(dict(SERIES, projectId="P2"))
v2 = FakeV2([[COPY]])
v2.project_completed = lambda pid, days=120, limit=500: (seen.append(pid), [COPY])[1]
rs.settle("P", "S", SINCE, api, v2, sleep=nap)
check("the completed feed is read on the series' live list", seen[:1] == ["P2"], seen)

# ── spawn is off under TICKAL_NO_SETTLE and with no ids
check("spawn is off in tests", rs.spawn("P", "S") is False)
del os.environ["TICKAL_NO_SETTLE"]
check("spawn refuses empty ids", rs.spawn("", "S") is False and rs.spawn("P", None) is False)
os.environ["TICKAL_NO_SETTLE"] = "1"

print(f"repeat settle: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
