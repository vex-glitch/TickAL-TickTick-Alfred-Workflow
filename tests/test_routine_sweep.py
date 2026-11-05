#!/usr/bin/env python3
"""🧹 A calendar drag's loose copies are swept (Vex 2026-11-05: "Reviews are
still falling apart. Like subtasks are getting out of the review box ... one
monthly review that is like it should be and subtasks from another
ungrouped randomly"). On 30 Oct the app copied the 🗓️ Monthly Review's
64 steps loose when the 31 Oct occurrence was dragged; the split heal of
6 Oct never ran for a drag. xact._routine_sweep over fakes: the title census
off the cache, each candidate confirmed by its v2 read, the confirmed copies
deleted, a decoy left, the cache patched, dry plans only, no candidates =
no v2 call, a dead v2 read skipped; and the roads that carry it: ⌃ Start's
toast, the post-Finish reset's log line, the manual heal. Nothing reaches
the network; HOME is a scratch dir before any repo import.

    python3 tests/test_routine_sweep.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import contextlib
    import io
    import os
    import sys
    import tempfile
    from datetime import date, datetime, timezone

    SCRATCH = tempfile.mkdtemp(prefix="tickal_sweep_")
    os.environ["HOME"] = SCRATCH              # before ANY repo import
    os.environ["TICKAL_NO_SETTLE"] = "1"
    os.environ["TICKAL_RUN_DIR"] = os.path.join(SCRATCH, "run")
    os.environ["TICKAL_NO_PERSIST"] = "1"
    os.environ["token"] = "fake-token"

    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in ("src/lib", "src", "Scripts"):
        sys.path.insert(0, os.path.join(REPO, _p))
    import api_v2                    # noqa: E402
    import cache as cache_store      # noqa: E402
    import routines as rt            # noqa: E402
    import xact                      # noqa: E402

    assert cache_store.CACHE_DIR.startswith(SCRATCH), cache_store.CACHE_DIR
    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
        if not cond:
            FAILS.append(name)

    R = rt.by_key("monthly")
    PID, TID = R["pid"], R["tid"]
    today_noon = datetime.combine(date.today(), datetime.min.time()).replace(hour=12).astimezone(timezone.utc)
    SERIES = {"id": TID, "projectId": PID, "status": 0, "title": "🗓️ Monthly Review",
              "repeatFlag": "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1", "childIds": ["ms1", "ms2"],
              "startDate": today_noon.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
              "createdTime": "2026-09-12T11:14:30+0200"}
    MS1 = {"id": "ms1", "projectId": PID, "parentId": TID, "status": 0, "title": "[Money](kmtrigger://x)"}
    MS2 = {"id": "ms2", "projectId": PID, "parentId": TID, "status": 0, "title": "TickTick", "childIds": ["ms2a"]}
    MS2A = {"id": "ms2a", "projectId": PID, "parentId": "ms2", "status": 0, "title": "MindSweep"}
    C1 = {"id": "c1", "projectId": PID, "status": 0, "title": "[Money](kmtrigger://x)", "createdTime": "2026-10-30T18:49:10+0100"}
    C2 = {"id": "c2", "projectId": PID, "status": 0, "title": "MindSweep", "createdTime": "2026-10-30T18:49:10+0100"}
    DECOY = {"id": "dx", "projectId": PID, "status": 0, "title": "TickTick", "createdTime": "2026-10-30T18:49:10+0100"}
    DRAGP = {"id": "dp", "projectId": PID, "status": 0, "title": "🗓️ Monthly Review", "createdTime": "2026-10-30T18:49:10+0100"}
    GYM = {"id": "gym", "projectId": PID, "status": 0, "title": "💪 Gym", "repeatFlag": "RRULE:FREQ=DAILY"}
    ROWS = [SERIES, MS1, MS2, MS2A, C1, C2, DECOY, DRAGP, GYM]
    V2 = {"c1": {"repeatTaskId": "ms1", "status": 0, "deleted": 0},
          "c2": {"repeatTaskId": "ms2a", "status": 0, "deleted": 0},
          "dx": {"repeatTaskId": "zzz", "status": 0, "deleted": 0}}

    class FakeV2:
        token = "t"
        reads, feed = [], []
        boom = set()
        def project_completed(self, pid, days=120, limit=500):
            return list(FakeV2.feed)
        def get_task(self, tid):
            FakeV2.reads.append(tid)
            if tid in FakeV2.boom:
                raise RuntimeError("v2 boom")
            return dict(V2.get(tid) or {})
    api_v2.TickTickV2 = FakeV2

    class FakeAPI:
        def __init__(self):
            self.deleted = []
        def delete_task(self, pid, tid):
            self.deleted.append(tid)
            return True
        def get_project_data(self, pid):
            return {"tasks": [dict(t) for t in cache_store.get("all_tasks") or [] if t["id"] not in self.deleted]}
        def get_task(self, pid, tid):
            return dict(SERIES)
    API = FakeAPI()
    xact._api = lambda: API
    xact.ROUTINE_LOG = os.path.join(SCRATCH, "routine.log")

    def fresh(rows=ROWS):
        cache_store.set("all_tasks", [dict(t) for t in rows])
        cache_store.set("completed_tasks", [])
        API.deleted.clear(); FakeV2.reads.clear(); FakeV2.boom.clear()

    # ── the sweep itself ────────────────────────────────────────────────────────
    fresh()
    n, note = xact._routine_sweep(R)
    check("S1 the two confirmed copies go, the decoy (a copy of nothing in the tree) and the dragged occurrence stay",
          n == 2 and sorted(API.deleted) == ["c1", "c2"] and note == "🧹 2 copies removed", (n, note, API.deleted))
    check("S1 every candidate was confirmed by a v2 read, nothing else was read",
          sorted(FakeV2.reads) == ["c1", "c2", "dx"], FakeV2.reads)
    left = {t["id"] for t in cache_store.get("all_tasks")}
    check("S1 the cache follows in place", "c1" not in left and "c2" not in left and {"dx", "dp", TID, "ms1"} <= left, left)
    check("S1 one log line", "sweep 🗓️ Monthly Review: 3 candidates, 2 copies, 2 deleted" in open(xact.ROUTINE_LOG).read())

    fresh()
    n, note = xact._routine_sweep(R, dry=True)
    check("S2 dry: the plan, nothing deleted", n == 2 and note == "🧹 2 copies to remove" and not API.deleted, (n, note, API.deleted))

    fresh([SERIES, MS1, MS2, MS2A, GYM])
    n, note = xact._routine_sweep(R)
    check("S3 no candidates: nothing to say and NO v2 read", (n, note) == (0, "") and not FakeV2.reads and not API.deleted)

    fresh()
    FakeV2.boom.add("c1")
    n, note = xact._routine_sweep(R)
    check("S4 a dead v2 read skips that candidate, the rest is swept", n == 1 and API.deleted == ["c2"] and note == "🧹 1 copy removed", (n, note, API.deleted))

    fresh()
    FakeV2.feed = [{"id": "ms3", "parentId": TID, "status": 2, "title": "Work"}]
    cache_store.set("all_tasks", [dict(t) for t in ROWS] + [{"id": "c3", "projectId": PID, "status": 0, "title": "Work"}])
    V2["c3"] = {"repeatTaskId": "ms3", "status": 0, "deleted": 0}
    n, note = xact._routine_sweep(R)
    check("S5 a copy of a step that is ticked right now (in the completed feed, not the open rows) is known too",
          "c3" in API.deleted and n == 3, API.deleted)
    FakeV2.feed = []; V2.pop("c3")

    fresh()
    FakeV2.token = ""
    n, note = xact._routine_sweep(R)
    check("S6 no v2 login: nothing deleted, the routine goes on", (n, note) == (0, "") and not API.deleted)
    FakeV2.token = "t"

    fresh()
    bag = [dict(t) for t in ROWS]
    n, note = xact._routine_sweep(R, bag=bag)
    check("S7 a bag handed in is the census (the heal's live read)", n == 2 and sorted(API.deleted) == ["c1", "c2"])

    # ── the roads ───────────────────────────────────────────────────────────────
    RUN = []
    xact.routine_run = lambda key, note="": RUN.append((key, note))
    xact._run_trigger = lambda *a, **k: RUN.append(("trigger", a))
    xact._routine_live = lambda r: (dict(SERIES), "")
    fresh()
    xact.routine_start("monthly")
    check("R1 ⌃ Start sweeps and its toast says so", RUN == [("monthly", "🧹 2 copies removed")] and sorted(API.deleted) == ["c1", "c2"], (RUN, API.deleted))
    RUN.clear()
    xact._routine_live = lambda r: (dict(SERIES), "🔁 new series adopted")
    fresh()
    xact.routine_start("monthly")
    check("R1 …beside a split's note", RUN == [("monthly", "🔁 new series adopted · 🧹 2 copies removed")], RUN)
    RUN.clear()
    fresh([SERIES, MS1, MS2, MS2A, GYM])
    xact._routine_live = lambda r: (dict(SERIES), "")
    xact.routine_start("monthly")
    check("R1 nothing loose: the toast is as it was", RUN == [("monthly", "")], RUN)

    xact._routine_reset = lambda tid, pid, days=120: "2 reopened"
    fresh()
    open(xact.ROUTINE_LOG, "w").close()
    xact.routine_reset_after("monthly")
    line = open(xact.ROUTINE_LOG).read()
    check("R2 the post-Finish reset sweeps too, its log line carries the chip",
          "finished 🗓️ Monthly Review -> steps back: 2 reopened · 🧹 2 copies removed" in line and sorted(API.deleted) == ["c1", "c2"], line)

    fresh()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        xact.routine_heal("monthly")
    check("R3 the manual heal on a live series sweeps off a live read", buf.getvalue().strip() == "🔁 🗓️ Monthly Review · series live · 🧹 2 copies removed" and sorted(API.deleted) == ["c1", "c2"], buf.getvalue())
    fresh()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        xact.routine_heal("monthly:dry")
    check("R3 …and dry plans only", buf.getvalue().strip() == "🔁 🗓️ Monthly Review · series live · 🧹 2 copies to remove" and not API.deleted, buf.getvalue())

    # ── the hub row names the leftovers ─────────────────────────────────────────
    import browse                    # noqa: E402
    fresh()
    rows = browse.render_routines("")
    row = next(r for r in rows if r.get("uid") == "rt-monthly")
    check("H1 the 🌓 hub row says how many loose copies lie in the column", "🧹 3 loose copies" in row["subtitle"], row["subtitle"])
    import dayroll                   # noqa: E402
    _today = dayroll.today
    dayroll.today = lambda *a, **k: date(2026, 12, 5)   # the series sits on 31 Dec, 30 Nov went by unfinished
    ahead = dict(SERIES, startDate="2026-12-31T07:00:00.000+0000", createdTime="2026-09-12T11:14:30+0200")
    fresh([ahead, MS1, MS2, MS2A, GYM])
    try:
        rows = browse.render_routines("")
    finally:
        dayroll.today = _today
    row = next(r for r in rows if r.get("uid") == "rt-monthly")
    check("H2 …and a missed occurrence (the series rolled past a day never finished)", "⏪ missed Mon 30 Nov" in row["subtitle"] and "🧹" not in row["subtitle"], row["subtitle"])

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
