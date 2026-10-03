#!/usr/bin/env python3
"""The 🔑 OKR screens (Scripts/browse.py ctx:okr*, HANDOFF_OKR section 8),
rendered the way Alfred runs them (main() with the ctx riding env
browse_ctx) against a FAKE board: okr_board.load is a stub that counts its
calls and the caches live in a temp dir. No network, no write anywhere real.

What it pins down (the traps that burned the other hubs):
  * every row spells out all six chords, fresh dicts, ⌃ and ⌥ args empty,
    no xact: on ⌘ or ⌥, ⌘ dead on anything that is not a task, task rows
    carry the full variable set (so ⌘ opens Actions on THE item)
  * a month row navigates through the BrowseCtx trampoline (the bar lands
    clean, iron rule 8), never with a ctx in the bar
  * the network is read only on an empty bar, and not while the last read
    is fresh
  * the month screen is the board's layout: areas as dead separators,
    objectives as rows, key results indented, ⇧ ticks a key result only

    python3 tests/test_okr_screens.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import contextlib
    import io
    import json
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
    REALP, REALT, REALC = "5eed00000000000000000b01", "5eed00000000000000000b02", "5eed00000000000000000b03"
    LISTP = "5eed00000000000000000c01"
    CTAP = "5eed00000000000000000f01"
    NAME = "🔑OKRs"
    TODAY = date.today()
    Y, M = TODAY.year, TODAY.month
    NY, NM = (Y, M + 1) if M < 12 else (Y + 1, 1)
    PY, PM_ = (Y, M - 1) if M > 1 else (Y - 1, 12)

    import okr_board as ob                                     # noqa: E402

    COLS = [{"id": "c-now", "name": f"{ob.keycap(M)} {Y}"},
            {"id": "c-next", "name": f"{ob.keycap(NM)} {NY}"},
            {"id": "c-prev", "name": f"{ob.keycap(PM_)} {PY}"},
            {"id": "c-goals", "name": f"{Y} Goals"},
            {"id": "c-empty", "name": f"{ob.keycap(1)} {Y + 2}"},
            {"id": "c-ns", "name": "Not Sectioned"}]

    def T(tid, title, col, parent=None, status=0, sort=0, pid=PID):
        return {"id": tid, "projectId": pid, "title": title, "columnId": col, "parentId": parent,
                "status": status, "sortOrder": sort, "tags": [], "_projectId": pid}

    OPEN = [
        T("a1", "🏔️ VexOS 4️⃣", "c-now", sort=1),
        T("o1", f"🥅 [Onboard](https://ticktick.com/webapp/#p/{REALP}/tasks/{REALT})", "c-ns", "a1", sort=1),
        T("k1", "🔑 Audits", "c-ns", "o1", sort=2),
        T("o2", "🥅 Shortcuts", "c-now", "a1", sort=2),
        T("k3", "🔑 TickTick", "c-now", "o2", sort=1),
        T("k4", f"🔑 [Plan](ticktick:///webapp/#p/{LISTP}/tasks)", "c-now", "o2", sort=2),
        T("a2", "🏔️ Work 1️⃣", "c-now", sort=2),
        T("o3", "🥅 Draw", "c-now", "a2"),
        T("kloose", "🔑 Loose one", "c-now", "a2", sort=9),
        T("stray", "🔑 Flash 3", "c-now", sort=5),
        T("a3", "🏔️ Work 1️⃣", "c-next"), T("o4", "🥅 Draw", "c-next", "a3"), T("k5", "🔑 Flash 4", "c-next", "o4"),
        T("a4", "🏔️ Work 1️⃣", "c-prev"), T("o5", "🥅 Old", "c-prev", "a4"), T("k6", "🔑 Left open", "c-prev", "o5"),
        T("ga", "🏔️ Work 1️⃣", "c-goals"), T("gdraw", "🏔️ Draw", "c-goals", "ga", sort=2), T("gpost", "🏔️ Post", "c-goals", "ga", sort=1),
        T("x", "🥅 Parked", "c-ns"),
    ]
    DONE = [T("k2", "🔑 Kickoff", "c-ns", "o1", status=2, sort=1),
            T("kw", "🔑 Dropped", "c-ns", "o1", status=-1, sort=3)]

    CH = ("cmd", "shift", "alt", "alt+shift", "alt+cmd", "cmd+shift")
    TASK_VARS = ("task_id", "task_list_id", "list_id", "section_id", "task_title", "item_type")

    def check_rows(screen, rows):
        """The row invariants, one check each per screen (offenders named)."""
        missing = [r["title"] for r in rows
                   if any(k not in (r.get("mods") or {}) for k in CH + ("ctrl",))]
        check(f"{screen}: every row spells out all six chords + ⌃", not missing, missing)
        bad = [r["title"] for r in rows if (r["mods"].get("ctrl") or {}).get("arg") != ""]
        check(f"{screen}: ⌃ arg empty on every row", not bad, bad)
        bad = [r["title"] for r in rows if (r["mods"].get("alt") or {}).get("arg", "") != ""]
        check(f"{screen}: ⌥ arg empty on every row (it would land in the bar)", not bad, bad)
        bad = [r["title"] for r in rows for k in ("cmd", "alt")
               if str((r["mods"].get(k) or {}).get("arg", "")).startswith("xact:")]
        check(f"{screen}: no xact: on ⌘ or ⌥", not bad, bad)
        bad = [r["title"] for r in rows if not (r.get("variables") or {}).get("task_id")
               and (r["mods"].get("cmd") or {}).get("valid") is not False]
        check(f"{screen}: ⌘ dead on every row that is not a task", not bad, bad)
        bad = [r["title"] for r in rows if (r.get("variables") or {}).get("task_id")
               and not all(k in r["variables"] for k in TASK_VARS)]
        check(f"{screen}: task rows carry the full task variables", not bad, bad)
        bad = [r["title"] for r in rows if str(r.get("arg", "")).startswith("ctx:")]
        check(f"{screen}: no ctx in a ⏎ arg (the bar must land clean)", not bad, bad)

    def check_shared(screen, rows):
        ids = [id(m) for r in rows for m in r["mods"].values()] + [id(r["mods"]) for r in rows]
        check(f"{screen}: no mods dict shared between rows", len(ids) == len(set(ids)))

    def by_title(rows, start):
        return next((r for r in rows if r["title"].startswith(start)), None)

    tmp = tempfile.mkdtemp(prefix="okr_screens_")
    _env = dict(os.environ)
    try:
        os.environ["okr_list_id"] = PID
        os.environ["cta_list_id"] = CTAP          # areas reads it at import
        for k in ("browse_ctx", "browse_back"):
            os.environ.pop(k, None)
        import cache                                           # noqa: E402
        cache.CACHE_DIR = os.path.join(tmp, "cache")
        ob.cache_store = cache

        LOADS = []
        real_load = ob.load

        def fake_load(list_id=None, api=None, v2=None):
            LOADS.append(list_id)
            cache.set(f"project_data_{list_id}", {"project": {"id": PID, "name": NAME}, "tasks": OPEN, "columns": COLS})
            cache.set(ob.DONE_KEY, {"list_id": list_id, "ts": time.time(), "rows": DONE})
            b = ob.build(list_id, NAME, COLS, OPEN + DONE)
            b.source, b.detail = "live", "fake"
            return b

        ob.load = fake_load
        cache.set("all_tasks", OPEN + [
            {"id": REALT, "projectId": REALP, "title": "The real one", "status": 0, "_projectName": "Real"},
            {"id": REALC, "projectId": REALP, "title": "A step", "status": 0, "parentId": REALT},
        ])
        cache.set("all_notes", [])
        cache.set("completed_tasks", [])
        cache.set("projects", [{"id": PID, "name": NAME}, {"id": REALP, "name": "Real"}, {"id": LISTP, "name": "Plan list"}])

        import browse                                          # noqa: E402

        def render(ctx, query="", back=""):
            """browse.main() as Alfred runs it: the ctx in env, the bar in $1."""
            os.environ["browse_ctx"] = ctx
            os.environ["browse_back"] = back
            sys.argv = ["browse.py", query]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                browse.main()
            return json.loads(buf.getvalue())["items"]

        def raw(ids, query=""):
            os.environ["browse_ctx"], os.environ["browse_back"] = "", ""
            return browse.render_okr(ids, query)

        import main_menu                                       # noqa: E402
        row = next((r for r in main_menu.build_items() if r.get("uid") == "okr"), None)
        check("main menu: the OKRs row, arg ctx:okr (the leg's matchstring)",
              row is not None and row["arg"] == "ctx:okr", row)
        os.environ["browse_ctx"] = "ctx:okr"
        check("parse_ctx: 'today' typed on the hub stays a search",
              browse.parse_ctx("today") == ("okr", [], "today"), browse.parse_ctx("today"))
        os.environ["browse_ctx"] = f"ctx:okr:m:{Y}-{M:02d}"
        check("parse_ctx: a month ctx", browse.parse_ctx("") == ("okr", ["m", f"{Y}-{M:02d}"], ""), browse.parse_ctx(""))
        os.environ["browse_ctx"] = ""

        # ── the root ──────────────────────────────────────────────────────
        rows = render("ctx:okr")
        check_rows("root", rows)
        check("root: one live read on an empty bar with nothing cached", LOADS == [PID], LOADS)
        titles = [r["title"] for r in rows]
        check("root: head row names the list and the planned months, ⏎ opens the board",
              titles[0] == f"{NAME} · 3 months planned" and rows[0]["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks"
              and "cache" not in rows[0]["subtitle"], rows[0])
        check("root: this month, this year's Goals, the month ahead, then the past month with an open KR",
              titles[1:5] == [f"{ob.keycap(M)} {Y}", f"{Y} Goals", f"{ob.keycap(NM)} {NY}", f"{ob.keycap(PM_)} {PY}"], titles)
        check("root: the empty column is not a row", not any(t == f"{ob.keycap(1)} {Y + 2}" for t in titles), titles)
        now = rows[1]
        check("root: a month row rides the BrowseCtx trampoline, ⌥ the same hop as a variable",
              now["arg"] == f"xact:crmbrowse:ctx:okr:m:{Y}-{M:02d}"
              and now["mods"]["alt"] == {"arg": "", "valid": True, "subtitle": "⤵️",
                                         "variables": {"browse_ctx": f"ctx:okr:m:{Y}-{M:02d}"}}, now)
        check("root: the month's subtitle counts objectives and key results (won't-do out, stray in)",
              now["subtitle"].startswith(f"{ob.MONTH_NAMES[M]} {Y} · 3 objectives · 1/6 KRs"), now["subtitle"])
        check("root: the past month says what is left open", "1 open left" in rows[4]["subtitle"], rows[4]["subtitle"])
        check("root: the Goals row counts the goals and names the areas",
              rows[2]["arg"] == f"xact:crmbrowse:ctx:okr:g:{Y}" and rows[2]["subtitle"].startswith("2 goals · Work"), rows[2])
        check("root: a card in no board column is said", titles[-1].startswith("📥 1 card in no board column") and rows[-1]["valid"] is False, titles[-1])
        check("root: ⌃ goes to the main menu", all(r["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:folders" for r in rows))
        check_shared("root", raw([]))

        # ── freshness ────────────────────────────────────────────────────
        rows = render("ctx:okr")
        check("root again within 45 s: the cached read, no network", LOADS == [PID], LOADS)
        stamp = os.path.join(cache.CACHE_DIR, f"{ob.DONE_KEY}.json")
        os.utime(stamp, (time.time() - 600, time.time() - 600))
        render("ctx:okr")
        check("root after the stamp aged: one more live read", LOADS == [PID, PID], LOADS)
        os.utime(stamp, (time.time() - 600, time.time() - 600))
        render("ctx:okr", "flash")
        check("a typed bar never reads the network", LOADS == [PID, PID], LOADS)

        # ── the month screen ─────────────────────────────────────────────
        rows = render(f"ctx:okr:m:{Y}-{M:02d}")
        check_rows("month", rows)
        titles = [r["title"] for r in rows]
        check("month: the head names the column and the month, ⏎ opens the board",
              titles[0] == f"{ob.keycap(M)} {Y} · {ob.MONTH_NAMES[M]} {Y}" and rows[0]["arg"].startswith("open:ticktick:///webapp/#p/")
              and "1/6 KRs · 3 objectives" in rows[0]["subtitle"], rows[0])
        check("month: the board's layout - areas by number, each a separator, objectives, KRs indented, a loose KR, the strays last",
              titles[1:] == ["🏔️ Work 1️⃣", "🥅 Draw", "      🔑 Loose one",
                             "🏔️ VexOS 4️⃣", "🥅 Onboard 🔗", "      ✅ Kickoff", "      🔑 Audits",
                             "🥅 Shortcuts", "      🔑 TickTick", "      🔑 Plan 🔗",
                             "🏔️ Unsorted", "🔑 Flash 3"], titles)
        sep = by_title(rows, "🏔️ VexOS")
        check("month: an area is a dead separator with its count", sep["valid"] is False and sep["subtitle"] == "1/4 KRs"
              and sep["mods"]["cmd"]["valid"] is False, sep)
        onb = by_title(rows, "🥅 Onboard")
        check("month: an objective row is a task row (⌘ Actions on it), ⏎ opens the card, ⇧ dead",
              onb["variables"]["task_id"] == "o1" and onb["variables"]["task_list_id"] == PID
              and onb["arg"] == f"open:ticktick:///webapp/#p/{PID}/tasks/o1" and onb["mods"]["shift"]["valid"] is False
              and "1/2 KRs" in onb["subtitle"], onb)
        check("month: ⌥ on an objective that links a task with open subtasks goes there",
              onb["mods"]["alt"]["variables"] == {"browse_ctx": f"ctx:subtasks:{REALP}:{REALT}"}, onb["mods"]["alt"])
        kr = by_title(rows, "      🔑 Audits")
        check("month: a key result ticks on ⇧ (the ordinary complete road)",
              kr["mods"]["shift"] == {"arg": f"complete:{PID}:k1:Audits", "valid": True, "subtitle": "✅ Done"}
              and "⇧✅" in kr["subtitle"], kr["mods"]["shift"])
        done = by_title(rows, "      ✅ Kickoff")
        check("month: a done key result reopens on ⇧", done["mods"]["shift"]["arg"] == f"uncomplete:{PID}:k2:Kickoff"
              and done["mods"]["shift"]["subtitle"] == "↩️ Reopen", done["mods"]["shift"])
        check("month: the won't-do key result is not shown", not any("Dropped" in t for t in titles))
        plan = by_title(rows, "      🔑 Plan")
        check("month: ⌥ on a key result linking a list opens that list",
              plan["mods"]["alt"]["variables"] == {"browse_ctx": f"ctx:tasks:{LISTP}"}, plan["mods"]["alt"])
        check("month: ⌥⌘ copies the card's link", kr["mods"]["alt+cmd"]["arg"] == f"copy:ticktick:///webapp/#p/{PID}/tasks/k1")
        check("month: ⌃ goes back to the hub", all(r["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:okr" for r in rows))
        check_shared("month", raw(["m", f"{Y}-{M:02d}"]))
        rows_now = render("ctx:okr:m:now")
        check("month: :now is this month", [r["title"] for r in rows_now] == titles)
        rows = render(f"ctx:okr:m:{Y}-{M:02d}", "tick")
        check("month, typed: the matching cards, no separators",
              [r["title"] for r in rows] == ["      🔑 TickTick"] and rows[0]["valid"] is True, [r["title"] for r in rows])
        rows = render(f"ctx:okr:m:{Y}-{M:02d}", "zzz")
        check("month, typed, no match: one dead row", len(rows) == 1 and rows[0]["valid"] is False and "zzz" in rows[0]["title"], rows)
        rows = render(f"ctx:okr:m:{Y + 2}-01")
        check("an empty month: head + nothing planned", [r["title"] for r in rows][1] == "Nothing planned" and rows[1]["valid"] is False, rows)
        rows = render(f"ctx:okr:m:{Y + 3}-05")
        check("a month with no column says so and goes back to the hub",
              len(rows) == 1 and rows[0]["title"].endswith("· no column on the board")
              and rows[0]["mods"]["ctrl"]["variables"]["browse_back"] == "ctx:okr", rows)

        # ── the goals screen ─────────────────────────────────────────────
        rows = render(f"ctx:okr:g:{Y}")
        check_rows("goals", rows)
        titles = [r["title"] for r in rows]
        check("goals: head, the area, the goals in order", titles == [f"{Y} Goals", "🏔️ Work 1️⃣", "🏔️ Post", "🏔️ Draw"], titles)
        check("goals: a goal with a same-named objective rolls it up, one without says so",
              rows[3]["subtitle"].startswith("0/1 KRs · 2 months") and rows[2]["subtitle"].startswith("no objectives yet"), [r["subtitle"] for r in rows])
        check("goals: a goal row is a task row, ⇧ dead", rows[2]["variables"]["task_id"] == "gpost" and rows[2]["mods"]["shift"]["valid"] is False)

        # ── search at the root ───────────────────────────────────────────
        rows = render("ctx:okr", "flash")
        check_rows("search", rows)
        check("search: every matching card, named with its month, area and objective",
              [(r["title"], r["subtitle"].split("  |")[0]) for r in rows]
              == [("🔑 Flash 4", f"{ob.keycap(NM)} {NY} · Work · Draw")], [(r["title"], r["subtitle"]) for r in rows])
        rows = render("ctx:okr", "draw")
        check("search: the year goal and both objectives, once each, the goal with its roll-up",
              [r["title"] for r in rows] == ["🏔️ Draw", "🥅 Draw", "🥅 Draw"]
              and rows[0]["subtitle"].startswith(f"{Y} Goals · Work · 0/1 KRs · 2 months")
              and {r["subtitle"].split(" ·")[0] for r in rows[1:]} == {f"{ob.keycap(M)} {Y}", f"{ob.keycap(NM)} {NY}"}, [r["subtitle"] for r in rows])
        rows = render("ctx:okr", "nothing here")
        check("search: no match = one dead row", len(rows) == 1 and rows[0]["valid"] is False)

        # ── problems ─────────────────────────────────────────────────────
        os.environ["okr_list_id"] = ""
        rows = render("ctx:okr")
        check("OKRs off: the one row points at Settings", len(rows) == 1 and rows[0]["title"] == "🔑 OKRs need a list"
              and rows[0]["valid"] is False, rows)
        os.environ["okr_list_id"] = PID
        shutil.rmtree(cache.CACHE_DIR, ignore_errors=True)

        def dead_load(list_id=None, api=None, v2=None):
            raise ob.BoardError("offline and nothing cached")
        ob.load = dead_load
        rows = render("ctx:okr")
        check("unreadable, nothing cached: the one row says why", len(rows) == 1 and rows[0]["title"] == "🔑 OKR board unreadable"
              and "offline" in rows[0]["subtitle"], rows)
        ob.load = fake_load
    finally:
        os.environ.clear()
        os.environ.update(_env)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{COUNT[0] - len(FAILS)}/{COUNT[0]} checks passed")
    if FAILS:
        sys.exit(1)
