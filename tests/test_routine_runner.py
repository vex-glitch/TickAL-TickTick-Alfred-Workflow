#!/usr/bin/env python3
"""Unit suite for src/routine_runner.py (the KM-free routine step model).
Run: python3 tests/test_routine_runner.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
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

    # ── the missed occurrence (⏪ on the confirm screen, Vex 2026-10-02) ──────
    LASTDAY = "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=-1"
    QLAST = "RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=-1"
    OCT2 = _dt.date(2026, 10, 2)
    SEP30 = _dt.date(2026, 9, 30)


    def TB(day, rule, born="2026-09-12"):
        t = T(day, rule, "06:00")
        t["dueDate"] = f"{day}T10:00:00.000+0000"
        t["createdTime"] = f"{born}T09:14:30.000+0000"
        return t


    MISS = rt.missed_occurrence
    check("the dragged monthly: series on 31 Oct, 30 Sep never finished = missed 30 Sep",
          MISS(TB("2026-10-31", LASTDAY), (), OCT2) == SEP30)
    check("the dragged quarterly: series on 31 Dec = missed 30 Sep",
          MISS(TB("2026-12-31", QLAST), (), OCT2) == SEP30)
    check("finished on its day = nothing missed",
          MISS(TB("2026-10-31", LASTDAY), {SEP30}, OCT2) is None)
    check("finished late, two days after = nothing missed",
          MISS(TB("2026-10-31", LASTDAY), {_dt.date(2026, 10, 2)}, OCT2) is None)
    check("a record BEFORE the occurrence does not count",
          MISS(TB("2026-10-31", LASTDAY), {_dt.date(2026, 8, 31)}, OCT2) == SEP30)
    check("due today = nothing to offer (today's run is the road)",
          MISS(TB("2026-10-02", DAILY), (), OCT2) is None)
    check("overdue = nothing to offer (⌃ Start runs it as it is)",
          MISS(TB("2026-09-30", LASTDAY), (), OCT2) is None)
    check("a daily one day ahead with no record: prev is today, not missed",
          MISS(TB("2026-10-03", DAILY), (), OCT2) is None)
    check("the weekly on a Friday, last Sunday unticked = missed Sunday",
          MISS(TB("2026-10-04", SUNDAY), (), OCT2) == _dt.date(2026, 9, 27))
    check("the weekly on a Friday, last Sunday ticked = nothing",
          MISS(TB("2026-10-04", SUNDAY), {_dt.date(2026, 9, 27)}, OCT2) is None)
    check("before birth is no occurrence",
          MISS(TB("2026-12-31", "RRULE:FREQ=MONTHLY;INTERVAL=12;BYMONTHDAY=-1", born="2026-09-27"),
               (), OCT2) is None)
    check("a completed one-off is never missed",
          MISS(dict(TB("2026-10-31", LASTDAY), status=2), (), OCT2) is None)
    check("no repeat = never missed",
          MISS({"startDate": "2026-10-31T06:00:00.000+0000"}, (), OCT2) is None)
    check("no task is safe", MISS(None, (), OCT2) is None and MISS({}, (), OCT2) is None)

    # ── which period does a LATE review belong to (late_day, 2026-10-02) ──────
    LD = rt.late_day
    check("the September monthly run on 2 Oct belongs to September",
          LD("monthly", TB("2026-09-30", LASTDAY), OCT2) == SEP30)
    check("the Q3 quarterly run on 2 Oct belongs to Q3",
          LD("quarterly", TB("2026-09-30", QLAST), OCT2) == SEP30)
    check("on its day it is not late", LD("monthly", TB("2026-09-30", LASTDAY), SEP30) is None)
    check("a weekly run on the Monday after belongs to the week that ended",
          LD("weekly", TB("2026-09-27", SUNDAY), _dt.date(2026, 9, 28)) == _dt.date(2026, 9, 27))
    check("overdue inside the same period is not late (a monthly two days late, same month)",
          LD("monthly", TB("2026-10-29", "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=29"),
             _dt.date(2026, 10, 31)) is None)
    check("ahead is never late", LD("monthly", TB("2026-10-31", LASTDAY), OCT2) is None)
    check("not a review slot = never late", LD("startup", TB("2026-09-30", DAILY), OCT2) is None)
    check("no task = never late", LD("monthly", None, OCT2) is None)
    check("journal_pin is late_day as a string",
          rt.journal_pin("monthly", TB("2026-09-30", LASTDAY), OCT2) == "@2026-09-30"
          and rt.journal_pin("monthly", TB("2026-10-31", LASTDAY), OCT2) == "")

    SH = rt.shift_iso_days
    check("the series moves back with its clock kept",
          SH("2026-10-31T06:00:00.000+0000", -31) == "2026-09-30T06:00:00.000+0000")
    check("the quarterly moves back a quarter",
          SH("2026-12-31T06:00:00.000+0000", (SEP30 - _dt.date(2026, 12, 31)).days)
          == "2026-09-30T06:00:00.000+0000")
    check("the due date keeps its own clock",
          SH("2026-10-31T10:00:00.000+0000", -31) == "2026-09-30T10:00:00.000+0000")
    check("a missing or odd stamp moves nothing",
          SH(None, -1) is None and SH("", -1) is None and SH("soon", -1) is None)

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

    # ── a routine's id can move: the split series (2026-10-06) ─────────────────
    # Vex moved 🌅 Startup to 05:30 for the days ahead; TickTick ended the old
    # series (UNTIL=that day), minted a successor with repeatTaskId = the old
    # id, and copied the twelve steps as loose parentless tasks. The registry
    # named the old id, and the next morning ran on a finished task.
    import json as _json
    import tempfile as _tf
    OLD, NEW, PID = "6a9faa51635ed1022425af34", "6ac351e161562864d514cb67", "6a268ea18f081f1de80eaeb5"
    GRAND = "6a9c0901b0db910232dea1bb"
    check("split_end: completed + UNTIL",
          rt.split_end({"status": 2, "repeatFlag": "RRULE:FREQ=DAILY;UNTIL=20261005;INTERVAL=1"}))
    check("split_end: an open series with UNTIL is still running",
          not rt.split_end({"status": 0, "repeatFlag": "RRULE:FREQ=DAILY;UNTIL=20261005"}))
    check("split_end: a completed one-off is not a split",
          not rt.split_end({"status": 2, "repeatFlag": None})
          and not rt.split_end({"status": 2, "repeatFlag": "RRULE:FREQ=DAILY;INTERVAL=1"}))
    check("split_end survives None", not rt.split_end(None))

    OLD_T = {"id": OLD, "projectId": PID, "createdTime": "2026-09-05T14:20:17+0200",
             "status": 2, "repeatFlag": "RRULE:FREQ=DAILY;UNTIL=20261005;INTERVAL=1",
             "childIds": ["s1", "s2", "dead"]}
    SUCC = {"id": NEW, "projectId": PID, "createdTime": "2026-10-05T09:29:37+0200",
            "status": 0, "repeatFlag": "RRULE:FREQ=DAILY;INTERVAL=1"}
    GYM = {"id": "6ac3527c61562864d514ce83", "projectId": PID, "createdTime": "2026-10-05T09:32:28+0200",
           "status": 0, "repeatFlag": "RRULE:FREQ=DAILY;INTERVAL=1"}
    SHUT = {"id": "6a268ea28f081f1de80eb10b", "projectId": PID, "createdTime": "2026-03-15T14:55:17+0100",
            "status": 0, "repeatFlag": "RRULE:FREQ=DAILY;INTERVAL=1"}
    STEP = {"id": "s1", "projectId": PID, "parentId": OLD, "status": 0,
            "title": f"[Finish Startup](alfred://runtrigger/com.vex.tickal/Link/?argument=done%3A{OLD}%3A{PID})",
            "createdTime": "2026-09-12T13:31:00+0200"}
    STEP2 = {"id": "s2", "projectId": PID, "parentId": OLD, "status": 0, "title": "[Calendar](x)",
             "createdTime": "2026-09-08T09:15:00+0200", "childIds": ["s2a"]}
    GRANDKID = {"id": "s2a", "projectId": PID, "parentId": "s2", "status": 0, "title": "Check todays schedule"}
    COPY1 = {"id": "c1", "projectId": PID, "status": 0, "title": STEP["title"],
             "createdTime": "2026-10-05T09:29:37+0200"}
    COPY2 = {"id": "c2", "projectId": PID, "status": 0, "title": "Check todays schedule",
             "createdTime": "2026-10-05T09:29:38+0200"}
    LATER = {"id": "l1", "projectId": PID, "status": 0, "title": "Buy milk",
             "createdTime": "2026-10-05T09:31:00+0200"}
    ELSEWHERE = {"id": "e1", "projectId": "other", "status": 0, "repeatFlag": "RRULE:FREQ=DAILY",
                 "createdTime": "2026-10-05T09:29:37+0200"}
    DONE_COPY = {"id": "a1", "projectId": PID, "status": 2, "repeatTaskId": OLD,
                 "createdTime": "2026-10-04T08:40:56+0200", "childIds": ["a1s"]}
    BAG = [OLD_T, SUCC, GYM, SHUT, STEP, STEP2, GRANDKID, COPY1, COPY2, LATER, ELSEWHERE, DONE_COPY]

    cands = rt.successor_candidates(OLD_T, BAG)
    check("successor candidates: open repeating parentless, same list, born after, newest first",
          [c["id"] for c in cands] == [GYM["id"], NEW], [c["id"] for c in cands])
    check("successor candidates: a series born before the old one is skipped (Shutdown)",
          SHUT["id"] not in [c["id"] for c in cands])
    check("successor candidates: an old task without a birth stamp keeps every series",
          SHUT["id"] in [c["id"] for c in rt.successor_candidates({"id": OLD, "projectId": PID}, BAG)])
    check("successor candidates: across tz formats",
          [c["id"] for c in rt.successor_candidates(dict(OLD_T, createdTime="2026-09-05T12:20:17.000+0000"), BAG)]
          == [GYM["id"], NEW])
    check("successor candidates: None bag", rt.successor_candidates(OLD_T, None) == [])
    check("is_successor: repeatTaskId points at the old id, open, kept, repeating",
          rt.is_successor({"repeatTaskId": OLD, "status": 0, "deleted": 0, "repeatFlag": "RRULE:FREQ=DAILY"}, OLD))
    check("is_successor: a deleted or completed or non-repeating pointer is not",
          not rt.is_successor({"repeatTaskId": OLD, "status": 0, "deleted": 1, "repeatFlag": "RRULE:FREQ=DAILY"}, OLD)
          and not rt.is_successor({"repeatTaskId": OLD, "status": 2, "repeatFlag": "RRULE:FREQ=DAILY"}, OLD)
          and not rt.is_successor({"repeatTaskId": OLD, "status": 0, "repeatFlag": None}, OLD)
          and not rt.is_successor({"repeatTaskId": GRAND, "status": 0, "repeatFlag": "RRULE:FREQ=DAILY"}, OLD)
          and not rt.is_successor(None, OLD))

    tree = rt.tree_ids(OLD, BAG)
    check("tree_ids: childIds and parentId both walked, grandchildren in, root out, dead ids kept",
          tree == {"s1", "s2", "s2a", "dead"}, tree)
    check("tree_ids: an archived occurrence is skipped whole",
          "a1" not in tree and "a1s" not in tree)
    check("tree_ids: a cycle cannot hang the walk",
          rt.tree_ids("r", [{"id": "r", "childIds": ["a"]}, {"id": "a", "parentId": "r", "childIds": ["r", "a"]}]) == {"a"})
    check("tree_ids: empty", rt.tree_ids(OLD, []) == set() and rt.tree_ids(OLD, None) == set())

    loose = rt.loose_copy_candidates(SUCC, BAG)
    check("loose copies: parentless non-repeating open tasks born in the successor's batch",
          sorted(c["id"] for c in loose) == ["c1", "c2"], [c["id"] for c in loose])
    check("loose copies: a task made minutes later, a series, a step with a parent, another list are not",
          not {LATER["id"], GYM["id"], "s1", "e1"} & {c["id"] for c in loose})
    check("loose copies: a successor without a birth stamp yields nothing",
          rt.loose_copy_candidates({"id": NEW}, BAG) == [])
    check("is_loose_copy: repeatTaskId names a step of the old tree",
          rt.is_loose_copy({"repeatTaskId": "s1", "status": 0}, tree)
          and rt.is_loose_copy({"repeatTaskId": "s2a", "status": 0}, tree))
    check("is_loose_copy: a copy of something else, a parented or completed or deleted one is not",
          not rt.is_loose_copy({"repeatTaskId": "zzz", "status": 0}, tree)
          and not rt.is_loose_copy({"repeatTaskId": "s1", "status": 0, "parentId": NEW}, tree)
          and not rt.is_loose_copy({"repeatTaskId": "s1", "status": 2}, tree)
          and not rt.is_loose_copy({"repeatTaskId": "s1", "status": 0, "deleted": 1}, tree)
          and not rt.is_loose_copy({"status": 0}, tree) and not rt.is_loose_copy(None, tree))
    check("retitle: the Finish link carries the live id",
          rt.retitle(STEP["title"], OLD, NEW) == STEP["title"].replace(OLD, NEW)
          and NEW in rt.retitle(STEP["title"], OLD, NEW) and OLD not in rt.retitle(STEP["title"], OLD, NEW))
    check("retitle: no id, no change", rt.retitle("x", "", NEW) == "x" and rt.retitle(None, OLD, NEW) == "")

    # the overlay: a private registry, never the module's
    REG = [{"key": "startup", "label": "🌅", "tid": OLD, "pid": PID},
           {"key": "shutdown", "label": "🌆", "tid": SHUT["id"], "pid": PID}]
    m = rt.adopt({}, "startup", NEW, OLD)
    check("adopt: the new mapping names the successor and keeps the old id",
          m == {"startup": {"tid": NEW, "was": [OLD]}}, m)
    m2 = rt.adopt(m, "startup", "6ad000000000000000000001", NEW)
    check("adopt twice: every earlier id stays, newest first",
          m2["startup"] == {"tid": "6ad000000000000000000001", "was": [NEW, OLD]}, m2)
    check("adopt leaves the other entries", rt.adopt(m, "shutdown", NEW, SHUT["id"])["startup"] == m["startup"])
    reg = [dict(r) for r in REG]
    changed = rt.apply_overlay(m, reg)
    check("apply_overlay: the live id moves, the constant joins was, the key is reported",
          changed == ["startup"] and reg[0]["tid"] == NEW and reg[0]["was"] == [OLD], (changed, reg[0]))
    check("apply_overlay: the other routine is untouched", reg[1]["tid"] == SHUT["id"] and "was" not in reg[1])
    check("apply_overlay twice changes nothing more",
          rt.apply_overlay(m, reg) == [] and reg[0]["was"] == [OLD])
    reg = [dict(r) for r in REG]
    check("apply_overlay: a malformed entry is skipped whole",
          rt.apply_overlay({"startup": {"tid": "nope"}, "shutdown": "x"}, reg) == []
          and reg[0]["tid"] == OLD and "was" not in reg[0])
    check("apply_overlay: a constant that already carries was keeps it",
          (lambda r: (rt.apply_overlay(m, [r]), r["was"])[1])(
              {"key": "startup", "tid": OLD, "pid": PID, "was": [GRAND]}) == [OLD, GRAND])
    check("apply_overlay: None mapping", rt.apply_overlay(None, [dict(r) for r in REG]) == [])
    reg = [dict(r) for r in REG]
    rt.apply_overlay(m, reg)
    check("by_tid finds a routine by an id it had", rt.by_tid(OLD, reg)["key"] == "startup"
          and rt.by_tid(NEW, reg)["key"] == "startup" and rt.by_tid(GRAND, reg) is None)
    check("current_tid maps an old id to the live one, a stranger to itself",
          rt.current_tid(OLD, reg) == NEW and rt.current_tid(NEW, reg) == NEW
          and rt.current_tid(GRAND, reg) == GRAND)
    check("the shipped registry: Startup's earlier ids still find it",
          rt.by_tid("6a9faa51635ed1022425af34")["key"] == "startup"
          and rt.current_tid("6a9faa51635ed1022425af34") == rt.by_key("startup")["tid"])
    with _tf.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", rt.OVERLAY_NAME)
        check("load_overlay: absent is {}", rt.load_overlay(path) == {})
        check("save_overlay makes the dir and lands", rt.save_overlay(m, path) and os.path.exists(path))
        check("load_overlay round trip", rt.load_overlay(path) == m)
        with open(path, "w") as f:
            f.write("[1, 2]")
        check("load_overlay: not a dict is {}", rt.load_overlay(path) == {})
        with open(path, "w") as f:
            f.write("{broken")
        check("load_overlay: unreadable is {}", rt.load_overlay(path) == {})
        os.environ["TICKAL_RUN_DIR"] = d
        check("overlay_path follows TICKAL_RUN_DIR", rt.overlay_path() == os.path.join(d, rt.OVERLAY_NAME))

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if __name__ == "__main__":
        sys.exit(1 if FAILS else 0)
    if FAILS:
        raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
