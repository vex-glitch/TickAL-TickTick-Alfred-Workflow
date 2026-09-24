#!/usr/bin/env python3
"""⏭️ Roll to today across a DST change (review 2026-09-24).

The roll added N x 24 h to the UTC stamp. Across a clock change local
midnight moves by an hour, so an all-day task on 20 Oct rolled on 28 Oct
became a TIMED 23:00 item on the 27th, still overdue. day_move.shift_fields
moves by LOCAL calendar days. Every fixture is Europe/Berlin, passed
explicitly, so the suite reads the same in any time zone.

    python3.13 tests/test_day_shift.py
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
os.environ["TICKAL_NO_SETTLE"] = "1"

import day_move as dm  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


BER = ZoneInfo("Europe/Berlin")


def local(stamp):
    """A '+0000' stamp as Berlin wall-clock 'YYYY-MM-DD HH:MM'."""
    return dm._parse(stamp).astimezone(BER).strftime("%Y-%m-%d %H:%M")


def allday(d):
    s = datetime(d.year, d.month, d.day, tzinfo=BER).astimezone(timezone.utc)
    return s.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def at(d, hh, mm=0):
    s = datetime(d.year, d.month, d.day, hh, mm, tzinfo=BER).astimezone(timezone.utc)
    return s.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def shift(task, days):
    return dm.shift_fields(task, days, tz=BER)


# ── 1. all-day, across the AUTUMN change (DST ends 2026-10-25) ────────────────
T = {"startDate": allday(date(2026, 10, 20)), "dueDate": allday(date(2026, 10, 20)), "isAllDay": True}
check("fixture: 20 Oct all-day is 19T22:00Z (CEST)", T["startDate"] == "2026-10-19T22:00:00.000+0000")
got = shift(T, 8)
check("all-day 20 Oct +8 -> midnight 28 Oct CET (27T23:00Z), not 27T22:00Z",
      got["startDate"] == "2026-10-27T23:00:00+0000" and got["dueDate"] == "2026-10-27T23:00:00+0000", got)
check("…still all-day, the zone named", got["isAllDay"] is True and got["timeZone"] == "Europe/Berlin", got)
old = (dm._parse(T["startDate"]) + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S+0000")
check("the old 8 x 24 h shift was 23:00 on the 27th", local(old) == "2026-10-27 23:00", local(old))
back = shift({"startDate": got["startDate"], "dueDate": got["dueDate"], "isAllDay": True}, -8)
check("all-day 28 Oct -8 -> midnight 20 Oct CEST", back["startDate"] == "2026-10-19T22:00:00+0000", back)

# ── 2. all-day, across the SPRING change (DST starts 2027-03-28) ─────────────
S = {"startDate": allday(date(2027, 3, 25)), "isAllDay": True}
got = shift(S, 5)
check("all-day 25 Mar +5 -> midnight 30 Mar CEST (29T22:00Z)", got["startDate"] == "2027-03-29T22:00:00+0000", got)
check("…no dueDate invented", "dueDate" not in got, got)
back = shift({"startDate": got["startDate"], "isAllDay": True}, -5)
check("all-day 30 Mar -5 -> midnight 25 Mar CET (24T23:00Z)", back["startDate"] == "2027-03-24T23:00:00+0000", back)

# ── 3. timed keeps its WALL-CLOCK time, both changes, both directions ────────
TT = {"startDate": at(date(2026, 10, 20), 9, 30), "dueDate": at(date(2026, 10, 20), 10, 30), "isAllDay": False}
got = shift(TT, 8)
check("timed 09:30-10:30 on 20 Oct +8 -> 09:30-10:30 on 28 Oct (CET)",
      local(got["startDate"]) == "2026-10-28 09:30" and local(got["dueDate"]) == "2026-10-28 10:30", got)
check("…and says so: not all-day, the task's own zone untouched",
      got["isAllDay"] is False and "timeZone" not in got, got)
back = shift({"startDate": got["startDate"], "dueDate": got["dueDate"], "isAllDay": False}, -8)
check("timed back -8 -> 09:30 on 20 Oct (CEST)", local(back["startDate"]) == "2026-10-20 09:30", back)
SP = {"startDate": at(date(2027, 3, 26), 9, 30), "isAllDay": False}
got = shift(SP, 3)
check("timed 09:30 on 26 Mar +3 -> 09:30 on 29 Mar (CEST, 07:30Z)",
      got["startDate"] == "2027-03-29T07:30:00+0000", got)
check("timed spring back -3 -> 09:30 CET (08:30Z)",
      shift({"startDate": got["startDate"], "isAllDay": False}, -3)["startDate"] == "2027-03-26T08:30:00+0000")
N = {"startDate": at(date(2026, 10, 24), 22), "dueDate": at(date(2026, 10, 25), 1), "isAllDay": False}
got = shift(N, 1)
check("a 22:00-01:00 span over the change night keeps both wall times",
      local(got["startDate"]) == "2026-10-25 22:00" and local(got["dueDate"]) == "2026-10-26 01:00", got)

# ── 4. spans, missing fields, odd stamps ──────────────────────────────────────
M = {"startDate": allday(date(2026, 10, 20)), "dueDate": allday(date(2026, 10, 23)), "isAllDay": True}
got = shift(M, 8)
check("a multi-day all-day span keeps its length in days",
      local(got["startDate"]) == "2026-10-28 00:00" and local(got["dueDate"]) == "2026-10-31 00:00", got)
check("no isAllDay field + local midnight = all-day",
      shift({"startDate": allday(date(2026, 10, 20))}, 8)["isAllDay"] is True)
check("no isAllDay field + 09:00 = timed",
      shift({"startDate": at(date(2026, 10, 20), 9)}, 8)["isAllDay"] is False)
got = shift({"dueDate": allday(date(2026, 10, 20)), "isAllDay": True}, 8)
check("only a dueDate: it moves, no startDate invented",
      set(got) >= {"dueDate", "isAllDay"} and "startDate" not in got
      and got["dueDate"] == "2026-10-27T23:00:00+0000", got)
check("a bare '+0000' stamp reads", shift({"startDate": "2026-10-19T22:00:00+0000", "isAllDay": True}, 8)
      ["startDate"] == "2026-10-27T23:00:00+0000")
check("a 'Z' stamp reads", shift({"startDate": "2026-10-19T22:00:00Z", "isAllDay": True}, 8)
      ["startDate"] == "2026-10-27T23:00:00+0000")
check("an unreadable stamp skips the task whole", shift({"startDate": "soon", "dueDate": allday(date(2026, 10, 20))}, 8) is None)
check("no dates at all = nothing to move", shift({"isAllDay": True}, 3) is None)
L = {"startDate": "2026-10-19T23:00:00.000+0000", "isAllDay": True, "timeZone": "Europe/London"}
got = shift(L, 8)
check("an all-day task stamped in London's zone lands on Berlin's midnight, zone named",
      local(got["startDate"]) == "2026-10-28 00:00" and got["timeZone"] == "Europe/Berlin", got)

# ── 4b. a stale cached flag (review 2026-09-24) ───────────────────────────────
# The date picker writes a date-only pick as UTC midnight; the cache used to
# keep the task's OLD isAllDay until the hourly sync.
A = {"startDate": "2026-10-20T00:00:00+0000", "dueDate": "2026-10-20T00:00:00+0000", "isAllDay": False}
got = shift(A, 8)
check("stale False on the picker's all-day shape -> all-day on the new day, not 02:00 timed",
      got["isAllDay"] is True and local(got["startDate"]) == "2026-10-28 00:00", got)
B = {"startDate": at(date(2026, 10, 20), 9), "dueDate": at(date(2026, 10, 20), 10, 30), "isAllDay": True}
got = shift(B, 8)
check("stale True on a 09:00-10:30 stamp -> stays timed, both times kept",
      got["isAllDay"] is False and local(got["startDate"]) == "2026-10-28 09:00"
      and local(got["dueDate"]) == "2026-10-28 10:30", got)
check("a real 00:00 local task (flag False) stays timed at 00:00",
      shift({"startDate": at(date(2026, 10, 20), 0), "isAllDay": False}, 8)["isAllDay"] is False)
check("no flag + UTC midnight = all-day (the api's guess)",
      shift({"startDate": "2026-10-20T00:00:00+0000"}, 8)["isAllDay"] is True)

# the repeated autumn hour: 02:30 CEST (fold 0) to 02:15 CET (fold 1) is 45 min
F = {"startDate": "2026-10-25T00:30:00.000+0000", "dueDate": "2026-10-25T01:15:00.000+0000", "isAllDay": False}
got = shift(F, 3)
s_, d_ = dm._parse(got["startDate"]), dm._parse(got["dueDate"])
check("a span in the repeated hour never ends before it starts; it keeps its 45 minutes",
      d_ > s_ and (d_ - s_) == timedelta(minutes=45), got)

# the cache mirrors the all-day guess update_task posted
import tempfile  # noqa: E402
import cache as cache_store  # noqa: E402
cache_store.CACHE_DIR = tempfile.mkdtemp()
import dispatch  # noqa: E402
cache_store.set("all_tasks", [{"id": "x", "projectId": "P", "isAllDay": False, "startDate": at(date(2026, 10, 1), 9)}])
dispatch._patch_task_cache("x", startDate="2026-10-20T00:00:00+0000", dueDate="2026-10-20T00:00:00+0000")
check("a date-only reschedule leaves the cache all-day, like the server",
      cache_store.get("all_tasks")[0]["isAllDay"] is True, cache_store.get("all_tasks")[0])
dispatch._patch_task_cache("x", startDate="2026-10-20T07:17:00+0000", dueDate="2026-10-20T07:17:00+0000")
check("a timed reschedule leaves it timed", cache_store.get("all_tasks")[0]["isAllDay"] is False)
dispatch._patch_task_cache("x", startDate=None, dueDate=None)
check("a cleared date leaves it not all-day", cache_store.get("all_tasks")[0]["isAllDay"] is False)
dispatch._patch_task_cache("x", startDate="2026-10-20T07:17:00+0000", isAllDay=True)
check("an explicit isAllDay is kept as given", cache_store.get("all_tasks")[0]["isAllDay"] is True)
dispatch._patch_task_cache("x", title="t")
check("a patch without dates never touches the flag", cache_store.get("all_tasks")[0]["isAllDay"] is True)

# ── 5. the roll verb uses it ──────────────────────────────────────────────────
import xact  # noqa: E402
_real_tz = dm._local_tz
dm._local_tz = lambda: BER
try:
    check("xact._shift_dates is the local-day shift", xact._shift_dates(T, 8) == shift(T, 8))
    tasks = [
        {"id": "a", "projectId": "P", "startDate": allday(date.today() - timedelta(days=10)),
         "dueDate": allday(date.today() - timedelta(days=10)), "isAllDay": True},
        {"id": "t", "projectId": "P", "startDate": at(date.today() - timedelta(days=3), 9, 15),
         "isAllDay": False},
    ]
    got = {}
    xact._date_bulk_pool = lambda key: (tasks, "Overdue", 0, 0)
    xact._dialog = lambda prompt, buttons, default: "Roll"
    xact._date_bulk_run = lambda ts, fn, keep=None: (got.update({t["id"]: fn(t) for t in ts}) or (len(ts), 0, 0))
    import filtering  # noqa: E402
    _tld = filtering.task_local_date
    filtering.task_local_date = lambda t: dm._parse(t.get("startDate") or t.get("dueDate")).astimezone(BER).date().isoformat()
    import contextlib  # noqa: E402
    import io  # noqa: E402
    with contextlib.redirect_stdout(io.StringIO()):
        xact.dateroll("overdue")
    filtering.task_local_date = _tld
    td = date.today().isoformat()
    check("roll: the all-day task lands on today's midnight, all-day",
          got.get("a") and local(got["a"]["startDate"]) == f"{td} 00:00" and got["a"]["isAllDay"] is True, got.get("a"))
    check("roll: the timed task lands on today at 09:15",
          got.get("t") and local(got["t"]["startDate"]) == f"{td} 09:15" and got["t"]["isAllDay"] is False, got.get("t"))
finally:
    dm._local_tz = _real_tz

print(f"day shift: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
