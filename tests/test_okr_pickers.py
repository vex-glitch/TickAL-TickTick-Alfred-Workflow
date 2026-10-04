#!/usr/bin/env python3
"""🔮 The goal pickers' board rows (Scripts/periodic_rows.plan_goal_rows,
HANDOFF_OKR section 8) over a FAKE cache in a temp dir: no network, no
write anywhere real. A day's picker offers this month's open key results
then its objectives, each a TEXT goal with the card's name - or, when the
card links a TickTick task, that task (never the card: a daily goal MOVES
its task onto the day). A card already the goal, or already done, is not
offered twice; nothing cached = no rows, the screen as it was.

    python3 tests/test_okr_pickers.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import shutil
    import sys
    import tempfile
    import time
    from datetime import date

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "Scripts"))

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if not cond:
            FAILS.append(name)
            print(f"FAIL  {name}  {detail}")

    PID = "5eed00000000000000000a01"          # the fake OKR list
    PNP = "5eed00000000000000000a02"          # the fake periodic list
    REALP, REALT, OLDP = "5eed00000000000000000b01", "5eed00000000000000000b02", "5eed00000000000000000b09"
    MISSP, MISST = "5eed00000000000000000c01", "5eed00000000000000000c02"
    TODAY = date.today()
    Y, M = TODAY.year, TODAY.month

    tmp = tempfile.mkdtemp(prefix="okr_pickers_")
    _env = dict(os.environ)
    try:
        os.environ["okr_list_id"] = PID
        os.environ["periodic_list_id"] = PNP
        import cache                                           # noqa: E402
        cache.CACHE_DIR = os.path.join(tmp, "cache")
        import okr_board as ob                                 # noqa: E402
        ob.cache_store = cache
        import periodic_model as pm                            # noqa: E402
        import periodic_rows as pr                             # noqa: E402

        def link(pid, tid):
            return f"https://ticktick.com/webapp/#p/{pid}/tasks/{tid}"

        def T(tid, title, col, parent=None, status=0, sort=0, pid=PID):
            return {"id": tid, "projectId": pid, "title": title, "columnId": col, "parentId": parent,
                    "status": status, "sortOrder": sort, "tags": [], "_projectId": pid}

        COLS = [{"id": "c-now", "name": f"{ob.keycap(M)} {Y}"}, {"id": "c-goals", "name": f"{Y} Goals"}]
        OPEN = [
            T("a1", "🏔️ VexOS 4️⃣", "c-now"),
            T("o1", "🥅 TickAL", "c-now", "a1", sort=1),
            T("klink", f"🔑 [Goals wf]({link(OLDP, REALT)})", "c-now", "o1", sort=1),
            T("ktext", "🔑 Review", "c-now", "o1", sort=2),
            T("kgone", f"🔑 [Lost thing]({link(MISSP, MISST)})", "c-now", "o1", sort=3),
            T("kcopy", f"🔑 [Copy of review]({link(PID, 'ktext')})", "c-now", "o1", sort=4),
            T("keagle", "🔑 [Grim Reaper](eagle://folder/X)", "c-now", "o1", sort=5),
            T("o2", "🥅 [Onboard](ticktick:///webapp/#p/{}/tasks)".format("5eed00000000000000000d01"), "c-now", "a1", sort=2),
            T("ga", "🏔️ Work 1️⃣", "c-goals"), T("gdraw", "🏔️ Draw", "c-goals", "ga"),
        ]
        DONE = [T("kdone", "🔑 Kickoff", "c-now", "o1", status=2), T("kwont", "🔑 Dropped", "c-now", "o1", status=-1)]
        cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": "🔑OKRs"}, "tasks": OPEN, "columns": COLS})
        cache.set(ob.DONE_KEY, {"list_id": PID, "ts": time.time(), "rows": DONE})
        cache.set("all_tasks", OPEN + [{"id": REALT, "projectId": REALP, "title": "Goals workflow (the real one)", "status": 0}])
        cache.set("completed_tasks", [{"id": "zzz", "projectId": REALP, "status": 2, "title": "gone"}])

        CALLS = []

        def arg(text, t):
            CALLS.append((text, t))
            return f"ARG:{text}|{(t or {}).get('id', '')}"

        p = pm.period_for("daily", TODAY)
        rows = pr.plan_goal_rows("daily", p, "☀️ Daily", arg)
        titles = [r["title"] for r in rows]
        check("a day: the open key results then the objectives, then the picker divider",
              titles == ["🔮 🔑 Goals wf", "🔮 🔑 Review", "🔮 🔑 Lost thing", "🔮 🔑 Copy of review", "🔮 🔑 Grim Reaper",
                         "🔮 🥅 TickAL", "🔮 🥅 Onboard", "📋 Pick a goal"], titles)
        check("a day: done and won't-do key results are not offered", not any("Kickoff" in t or "Dropped" in t for t in titles))
        # the typed bar keeps the board rows the text finds (a key result is never in the task pool)
        frows = pr.plan_goal_rows("daily", p, "☀️ Daily", arg, query="revi")
        check("a typed bar filters the board rows (the main search's ranking)",
              [r["title"] for r in frows] == ["🔮 🔑 Review", "🔮 🔑 Copy of review", "📋 Pick a goal"], [r["title"] for r in frows])
        check("a typed bar that finds nothing on the board shows no board rows", pr.plan_goal_rows("daily", p, "☀️ Daily", arg, query="zzzz") == [])
        # the cap: October held 24 open items; a screen shows PLAN_ROWS_CAP
        many = [T(f"k{i:02d}", f"🔑 Step {i}", "c-now", "o2", sort=i) for i in range(20)]
        cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": "🔑OKRs"}, "tasks": OPEN + many, "columns": COLS})
        crows = pr.plan_goal_rows("daily", p, "☀️ Daily", arg)
        check("the board rows are capped", len(crows) == pr.PLAN_ROWS_CAP + 1 and crows[-1]["title"] == "📋 Pick a goal", len(crows))
        cache.set(f"project_data_{PID}", {"project": {"id": PID, "name": "🔑OKRs"}, "tasks": OPEN, "columns": COLS})
        by = {r["title"]: r for r in rows}
        check("a linked card sets the REAL task, where the cache says it lives now",
              by["🔮 🔑 Goals wf"]["arg"] == f"ARG:|{REALT}" and any(t and t["projectId"] == REALP for _x, t in CALLS), CALLS)
        check("a text card sets a text goal with its name", by["🔮 🔑 Review"]["arg"] == "ARG:Review|")
        check("a link to a task the cache does not know still sets that task", by["🔮 🔑 Lost thing"]["arg"] == f"ARG:|{MISST}")
        check("a link back into the board is a text goal (a copy of a copy)", by["🔮 🔑 Copy of review"]["arg"] == "ARG:Copy of review|")
        check("an Eagle link is a text goal", by["🔮 🔑 Grim Reaper"]["arg"] == "ARG:Grim Reaper|")
        check("an objective linking a list is a text goal", by["🔮 🥅 Onboard"]["arg"] == "ARG:Onboard|")
        check("every row names the month and the board", all(r["subtitle"].startswith(f"{ob.keycap(M)} {ob.MONTH_NAMES[M]} · the board") for r in rows[:-1]), [r["subtitle"] for r in rows])
        check("the divider is dead", rows[-1]["valid"] is False)
        check("every row carries its mods", all("mods" in r for r in rows))

        # already the goal: by the real task's link, or by its words
        have = [f"- [ ] [Goals workflow (the real one)]({link(REALP, REALT)})", "- [ ] Review"]
        rows = pr.plan_goal_rows("daily", p, "☀️ Daily", arg, have_lines=have)
        titles = [r["title"] for r in rows]
        check("a card whose task or words are the goal already is not offered again",
              "🔮 🔑 Goals wf" not in titles and "🔮 🔑 Review" not in titles and "🔮 🔑 Lost thing" in titles, titles)

        mrows = pr.plan_goal_rows("monthly", pm.period_for("monthly", TODAY), "🗓️ Monthly", arg)
        check("a month: objectives first", [r["title"] for r in mrows][:2] == ["🔮 🥅 TickAL", "🔮 🥅 Onboard"], [r["title"] for r in mrows])
        yrows = pr.plan_goal_rows("yearly", pm.period_for("yearly", TODAY), "🎉 Yearly", arg)
        check("a year: the year goals", [r["title"] for r in yrows] == ["🔮 🏔️ Draw", "📋 Pick a goal"] and yrows[0]["arg"] == "ARG:Draw|", [r["title"] for r in yrows])
        ny = date(Y + 1, 1, 15)
        check("a period the board has no column for: no rows", pr.plan_goal_rows("daily", pm.period_for("daily", ny), "☀️ Daily", arg) == [])

        # the task pool behind every picker: nameless cards out, a blank bar RANKED
        # (tomorrow's own tasks first, then tasks before notes, top-level first)
        tmrw = (TODAY + __import__("datetime").timedelta(days=1)).isoformat()
        cache.set("all_tasks", [
            {"id": "n1", "projectId": REALP, "title": "A note", "kind": "NOTE", "status": 0},
            {"id": "blank", "projectId": REALP, "title": "   ", "status": 0},
            {"id": "sub", "projectId": REALP, "title": "A subtask", "status": 0, "parentId": "t1"},
            {"id": "t1", "projectId": REALP, "title": "A task", "status": 0},
            {"id": "due", "projectId": REALP, "title": "Due tomorrow", "status": 0, "startDate": f"{tmrw}T08:00:00.000+0000"},
            {"id": "pri", "projectId": REALP, "title": "Urgent", "status": 0, "priority": 5},
        ])
        pool = pr._task_pool(include_notes=True, goals=True)
        check("a nameless card is never offered", "blank" not in [t["id"] for t in pool])
        jnl = {"slot": "evening", "mode": "set", "note_day": TODAY, "for_day": TODAY + __import__("datetime").timedelta(days=1)}
        rows = pr.tier_goal_rows("daily", "", jnl=jnl)
        picks = [r["title"] for r in rows if r["title"].startswith("📋 ") and r["title"] != "📋 Pick a goal"]
        names = lambda ps_: [t[2:].split(" ⚫️")[0].split(" 🔴")[0] for t in ps_]
        check("a blank evening picker: tomorrow's task, then tasks by priority, subtasks, notes last",
              names(picks) == ["Due tomorrow", "Urgent", "A task", "A subtask", "A note"], picks)
        rows = pr.tier_goal_rows("daily", "a ", jnl=jnl)
        picks = [r["title"] for r in rows if r["title"].startswith("📋 ") and r["title"] != "📋 Pick a goal"]
        check("a typed bar: the main search's order (word start: task, subtask, note)",
              names(picks)[:3] == ["A task", "A subtask", "A note"], picks)
        os.environ["okr_list_id"] = ""
        check("OKRs off: no rows", pr.plan_goal_rows("daily", p, "☀️ Daily", arg) == [])
        os.environ["okr_list_id"] = PID
        shutil.rmtree(cache.CACHE_DIR, ignore_errors=True)
        check("nothing cached: no rows, no error", pr.plan_goal_rows("daily", p, "☀️ Daily", arg) == [])
    finally:
        os.environ.clear()
        os.environ.update(_env)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{COUNT[0] - len(FAILS)}/{COUNT[0]} checks passed")
    if FAILS:
        sys.exit(1)
