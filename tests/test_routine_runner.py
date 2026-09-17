#!/usr/bin/env python3
"""Unit suite for src/routine_runner.py (the KM-free routine step model).
Run: python3 tests/test_routine_runner.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import routine_runner as rr  # noqa: E402
import routines as rt        # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


APP = "com.TickTick.task.mac"
GOOD = [
    {"do": "quit", "app": APP, "secs": 15},
    {"do": "activate", "app": APP, "wait": True},
    {"do": "hide_others"},
    {"do": "place", "app": APP, "frame": [10, -20, 800, 600]},
    {"do": "link", "arg": "focus:{tid}:{pid}", "sticky": [1, 2, 3, 4], "bar": [5, 6]},
    {"do": "url", "url": "ticktick:///webapp/#p/inbox/tasks"},
    {"do": "pause", "secs": 3},
    {"do": "key", "key": "escape", "mods": ["shift"]},
]

check("a full list validates", rr.validate(GOOD) == [], rr.validate(GOOD))
check("defaults validate", rr.validate(rr.default_steps()) == [])
check("every period's default validates",
      all(rr.validate(rr.default_steps(s)) == [] for s in
          ("daily", "weekly", "monthly", "quarterly", "yearly")))
check("empty is refused", rr.validate([]) == ["no steps"])
check("not a list is refused", rr.validate({"do": "pause"}) == ["no steps"])
check("unknown step named", "unknown do='dance'" in " ".join(rr.validate([{"do": "dance"}])))
check("place needs a frame", rr.validate([{"do": "place", "app": APP}]))
check("place needs FOUR numbers",
      rr.validate([{"do": "place", "app": APP, "frame": [1, 2, 3]}]))
check("frame rejects text",
      rr.validate([{"do": "place", "app": APP, "frame": [1, 2, 3, "x"]}]))
check("activate needs an app", rr.validate([{"do": "activate"}]))
check("link needs an arg", rr.validate([{"do": "link"}]))
check("sticky must be 4 numbers",
      rr.validate([{"do": "link", "arg": "x", "sticky": [1, 2]}]))
check("bar must be 2 numbers",
      rr.validate([{"do": "link", "arg": "x", "bar": [1, 2, 3]}]))
check("url needs a url", rr.validate([{"do": "url"}]))
check("pause is capped", rr.validate([{"do": "pause", "secs": 999}]))
check("negative pause refused", rr.validate([{"do": "pause", "secs": -1}]))
check("key must be known", rr.validate([{"do": "key", "key": "hyperspace"}]))
check("mods must be real", rr.validate([{"do": "key", "key": "escape", "mods": ["hyper"]}]))
check("a long list is refused", rr.validate([{"do": "hide_others"}] * 61))
check("problems are listed per step", len(rr.validate([{"do": "nope"}, {"do": "url"}])) == 2)

check("expand fills both ids",
      rr.expand({"do": "link", "arg": "focus:{tid}:{pid}"}, "T", "P")["arg"] == "focus:T:P")
check("expand fills a url",
      rr.expand({"do": "url", "url": "x/{pid}/y/{tid}"}, "T", "P")["url"] == "x/P/y/T")
check("expand copies, never mutates",
      (lambda s: (rr.expand(s, "T", "P"), s["arg"])[1] == "focus:{tid}:{pid}")(
          {"do": "link", "arg": "focus:{tid}:{pid}"}))
check("expand leaves other steps alone",
      rr.expand({"do": "place", "app": APP, "frame": [1, 2, 3, 4]}, "T", "P")["frame"]
      == [1, 2, 3, 4])

check("describe covers every step type",
      all(rr.describe(s) and "None" not in rr.describe(s) for s in GOOD))
check("describe names the app", "com.TickTick" in rr.describe(GOOD[0]))
check("describe shows the frame", "800x600" in rr.describe(GOOD[3]))
check("describe shows sticky + bar",
      "sticky" in rr.describe(GOOD[4]) and "bar" in rr.describe(GOOD[4]))

# the shipped registry must be runnable with no config file at all
for r in rt.ROUTINES:
    steps = [rr.expand(s, r["tid"], r["pid"]) for s in rr.default_steps()]
    args = [x.get("arg") for x in steps]
    # focusWINDOW since 2026-09-17: every routine puts its task on screen in
    # TickTick's live floating window, never a sticky (a sticky never
    # re-renders, so a routine's own writes were invisible in it).
    check(f"{r['key']}: default list runs with its own ids",
          rr.validate(steps) == [] and f"focuswindow:{r['tid']}:{r['pid']}" in args)
    check(f"{r['key']}: no sticky verb left in the default list",
          not any((a or "").split(":")[0].endswith("sticky") for a in args), args)
    check(f"{r['key']}: default list resets its own tree first",
          steps[0] == {"do": "reset", "tid": r["tid"], "pid": r["pid"]}, steps[0])

# ── which occurrence? (the ⌃ Start safety net) ─────────────────────────────
import datetime as _dt  # noqa: E402

TODAY = _dt.date(2026, 9, 12)          # a Saturday
DAILY = "RRULE:FREQ=DAILY;INTERVAL=1"
SUNDAY = "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=SU"
M30 = "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=30"
Q30 = "RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=30"


def T(day, rule=DAILY, hhmm="05:00"):
    return {"startDate": f"{day}T{hhmm}:00.000+0000", "repeatFlag": rule}


check("due today", rt.due_state(T("2026-09-12"), TODAY)["state"] == "today")
check("due tomorrow = ahead (today's is done)",
      rt.due_state(T("2026-09-13"), TODAY)["state"] == "ahead")
check("due yesterday = overdue",
      rt.due_state(T("2026-09-11"), TODAY)["state"] == "overdue")
check("no date = undated", rt.due_state({}, TODAY)["state"] == "undated")
check("no task at all is safe", rt.due_state(None, TODAY)["state"] == "undated")
check("days counts forward", rt.due_state(T("2026-09-30", M30), TODAY)["days"] == 18)
check("a weekly ahead names last Sunday",
      rt.due_state(T("2026-09-13", SUNDAY), TODAY)["prev"] == _dt.date(2026, 9, 6))
check("a daily ahead names yesterday",
      rt.due_state(T("2026-09-13"), TODAY)["prev"] == _dt.date(2026, 9, 12))
check("a monthly ahead names last month",
      rt.due_state(T("2026-09-30", M30), TODAY)["prev"] == _dt.date(2026, 8, 30))
check("a quarterly ahead goes back three months",
      rt.due_state(T("2026-09-30", Q30), TODAY)["prev"] == _dt.date(2026, 6, 30))
check("month arithmetic crosses the year",
      rt.prev_occurrence(_dt.date(2026, 1, 30), M30) == _dt.date(2025, 12, 30))
check("a 31st clamps into February",
      rt.prev_occurrence(_dt.date(2026, 3, 31), M30) == _dt.date(2026, 2, 28))
check("a leap February clamps to 29",
      rt.prev_occurrence(_dt.date(2024, 3, 31), M30) == _dt.date(2024, 2, 29))
check("no rule = no previous", rt.prev_occurrence(_dt.date(2026, 9, 12), "") is None)

check("rule words: daily", rt.rule_text(DAILY) == "daily")
check("rule words: Sundays", rt.rule_text(SUNDAY) == "Sundays")
check("rule words: the 30th", rt.rule_text(M30) == "the 30th of every month")
check("rule words: quarterly", rt.rule_text(Q30) == "the 30th, every 3 months")
check("rule words: two weekdays",
      rt.rule_text("RRULE:FREQ=WEEKLY;BYDAY=MO,TH") == "Monday and Thursdays")
check("rule words: every 3 days", rt.rule_text("RRULE:FREQ=DAILY;INTERVAL=3") == "every 3 days")
check("rule words: none", rt.rule_text("") == "" and rt.rule_text(None) == "")

check("a +0000 stamp reads as a local day",
      rt.local_date("2026-09-13T05:00:00.000+0000") is not None)
check("junk stamps are None",
      rt.local_date("not a date") is None and rt.local_date("") is None
      and rt.local_date(None) is None)

# ── the reset step (Vex 2026-09-12: ticked steps vanish from the next
# occurrence, because only the APP resets subtasks - the API road does not) ──
RESET = {"do": "reset", "tid": "{tid}", "pid": "{pid}"}
check("reset is a step type", "reset" in rr.STEP_TYPES)
check("a reset step validates", rr.validate([RESET]) == [])
check("reset needs tid and pid",
      len(rr.validate([{"do": "reset"}])) == 2)
check("reset days is bounded",
      rr.validate([dict(RESET, days=9999)]) and rr.validate([dict(RESET, days=0)]))
check("reset days accepts a quarter", rr.validate([dict(RESET, days=120)]) == [])
check("reset slots expand to the routine's own task",
      rr.expand(RESET, "TID", "PID") == {"do": "reset", "tid": "TID", "pid": "PID"})
check("reset describes itself", rr.describe(RESET) == "reset steps")

# tree: root > a (done) > a1 (done), b (open) > b1 (done); plus an archived
# occurrence copy of the whole thing, which must never be touched.
TREE = [
    {"id": "root", "childIds": ["a", "b"]},
    {"id": "a", "parentId": "root", "status": 2, "childIds": ["a1"]},
    {"id": "a1", "parentId": "a", "status": 2},
    {"id": "b", "parentId": "root", "status": 0, "childIds": ["b1"]},
    {"id": "b1", "parentId": "b", "status": 2},
    {"id": "ghost", "repeatTaskId": "root", "status": 2, "childIds": ["g1"]},
    {"id": "g1", "parentId": "ghost", "status": 2},
]
todo, unknown = rr.completed_descendants("root", TREE)
check("every completed step is found, at any depth",
      sorted(todo) == ["a", "a1", "b1"], todo)
check("the root itself is never reopened", "root" not in todo)
check("open steps are left alone", "b" not in todo)
check("an archived occurrence is skipped whole",
      "ghost" not in todo and "g1" not in todo, todo)
check("nothing unknown in a complete bag", unknown == [], unknown)

todo2, unknown2 = rr.completed_descendants("root", [TREE[0], TREE[3]])
check("a child the bag cannot explain is reported, not guessed",
      unknown2 == ["a", "b1"] and todo2 == [], (todo2, unknown2))
check("a parentId-only link is walked too",
      rr.completed_descendants("root", [{"id": "root"},
                                        {"id": "x", "parentId": "root", "status": 2}])[0] == ["x"])
check("a cycle cannot hang the walk",
      rr.completed_descendants("root", [{"id": "root", "childIds": ["a"]},
                                        {"id": "a", "parentId": "root", "status": 2,
                                         "childIds": ["root", "a"]}])[0] == ["a"])
check("the cap holds",
      len(rr.completed_descendants("root",
          [{"id": "root", "childIds": [str(i) for i in range(50)]}]
          + [{"id": str(i), "parentId": "root", "status": 2} for i in range(50)],
          cap=7)[0]) == 7)
check("an empty bag is survivable",
      rr.completed_descendants("root", []) == ([], [])
      and rr.completed_descendants("root", None) == ([], []))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
