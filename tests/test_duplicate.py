#!/usr/bin/env python3
"""duplicate.plan / new_dates - "carry this task forward", pure.

Vex 2026-09-13: TickTick's own duplicate appends " Copy" to the task and
every subtask. This one keeps names, copies only the OPEN subtree, lands on
the picked day with the original's duration, and never repeats.

    python3 tests/test_duplicate.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import duplicate as dup  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


ROOT_T = {"id": "R", "projectId": "P", "title": "💼 P • Onboard TickTick 🔗",
          "startDate": "2026-09-13T07:00:00.000+0000",
          "dueDate": "2026-09-13T08:30:00.000+0000", "isAllDay": False,
          "priority": 3, "tags": ["work"], "content": "notes", "columnId": "COL",
          "reminders": ["TRIGGER:-PT15M"], "repeatFlag": "RRULE:FREQ=DAILY",
          "sortOrder": 5}
KIDS = [  # fsub.descendants shape: open only, DFS display order
    {"id": "C", "parentId": "R", "title": "step C", "_depth": 1, "sortOrder": -3},
    {"id": "A", "parentId": "R", "title": "step A", "_depth": 1, "sortOrder": -1,
     "dueDate": "2026-09-13T12:00:00.000+0000"},
    {"id": "A1", "parentId": "A", "title": "step A.1", "_depth": 2, "sortOrder": 0},
]
TOMORROW_8 = "2026-09-14T06:00:00+0000"

steps = dup.plan(ROOT_T, KIDS, TOMORROW_8)
r = steps[0]["fields"]
check("names are untouched - no ' Copy' anywhere",
      [s["fields"]["title"] for s in steps]
      == ["💼 P • Onboard TickTick 🔗", "step C", "step A", "step A.1"],
      [s["fields"]["title"] for s in steps])
check("the copy starts on the picked time", r["start_date"] == TOMORROW_8, r)
check("and keeps the original's 90 minutes", r["due_date"] == "2026-09-14T07:30:00+0000", r)
check("the copy never repeats", "repeat_flag" not in r and "repeatFlag" not in r, r)
check("description, priority, tags, list, section, reminders come along",
      (r["content"], r["priority"], r["tags"], r["project_id"], r["column_id"],
       r["reminders"]) == ("notes", 3, ["work"], "P", "COL", ["TRIGGER:-PT15M"]), r)
check("parents are planned before their children",
      [s["old"] for s in steps] == ["R", "C", "A", "A1"])
check("each child remembers its ORIGINAL parent (run maps it to the new one)",
      [s["parent_old"] for s in steps] == [None, "R", "R", "A"])
check("the originals' sibling order is carried for the restore batch",
      [s["sortOrder"] for s in steps[1:]] == [-3, -1, 0])
check("a dated subtask moves by the same day the parent moved",
      steps[2]["fields"]["due_date"] == "2026-09-14T11:00:00+0000", steps[2]["fields"])
check("an undated subtask stays undated",
      "due_date" not in steps[1]["fields"] and "start_date" not in steps[1]["fields"])

# picking a start AND an end wins over the kept duration
s2 = dup.plan(ROOT_T, [], TOMORROW_8, end_iso="2026-09-14T10:00:00+0000")[0]["fields"]
check("an explicit end wins", (s2["start_date"], s2["due_date"])
      == (TOMORROW_8, "2026-09-14T10:00:00+0000"), s2)

# a date with no time = an all-day copy (only a due date is sent)
s3 = dup.plan(ROOT_T, [], "2026-09-14")[0]["fields"]
check("a date-only pick makes an all-day copy",
      "start_date" not in s3 and s3["due_date"] == "2026-09-14", s3)
check("new_dates reports all-day", dup.new_dates(ROOT_T, "2026-09-14")[2] is True)

# a task that was a single point in time stays a point
point = dict(ROOT_T, dueDate=ROOT_T["startDate"])
s4 = dup.plan(point, [], TOMORROW_8)[0]["fields"]
check("a point-in-time task stays a point", s4["start_date"] == s4["due_date"] == TOMORROW_8, s4)

# an undated original: the copy takes the picked date, dated kids keep theirs
undated = {k: v for k, v in ROOT_T.items() if k not in ("startDate", "dueDate")}
s5 = dup.plan(undated, [KIDS[1]], TOMORROW_8)
check("undated original still lands on the picked day", s5[0]["fields"]["start_date"] == TOMORROW_8)
check("with no shift to measure, a dated kid keeps its own date",
      s5[1]["fields"]["due_date"] == KIDS[1]["dueDate"], s5[1]["fields"])

# reminders picked in the flow join the original's, no duplicates
s6 = dup.plan(ROOT_T, [], TOMORROW_8, extra_reminders=["TRIGGER:PT0S", "TRIGGER:-PT15M"])[0]["fields"]
check("picked reminders join the original's, deduped",
      s6["reminders"] == ["TRIGGER:-PT15M", "TRIGGER:PT0S"], s6["reminders"])

# empty fields are simply not sent
bare = {"id": "R", "projectId": "P", "title": "t"}
s7 = dup.plan(bare, [], TOMORROW_8)[0]["fields"]
check("unset fields are not sent as nulls",
      not any(v in (None, [], "") for v in s7.values()), s7)

print(f"duplicate: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
