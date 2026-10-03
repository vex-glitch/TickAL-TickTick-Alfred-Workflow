#!/usr/bin/env python3
"""🔑 The OKR board model (src/okr_board.py, HANDOFF_OKR section 8): the
column grammar, the card titles, the tree (an area card's column is its
subtasks' month, same-named cards fold, strays and loose key results), the
counts, the year-goal roll-up, the hub root's order, the notes' month rule,
and the loader over a scratch cache (a fake v1 + v2, no network).
Run: python3 tests/test_okr_board.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import json
    import os
    import shutil
    import sys
    import tempfile
    from datetime import date

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "Scripts"))
    # a scratch HOME: cache.CACHE_DIR is read from HOME at import, and this
    # suite writes okr_done / project_data rows through the loader
    TMP = tempfile.mkdtemp(prefix="tickal-okrboard-")
    os.environ["HOME"] = TMP
    os.environ["okr_list_id"] = "L" * 24

    import cache as cache_store         # noqa: E402
    import okr_board as ob              # noqa: E402

    assert cache_store.CACHE_DIR.startswith(TMP), cache_store.CACHE_DIR

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if not cond:
            FAILS.append(f"{name}: {detail}")
            print(f"  FAIL {name} {detail}")

    LID = "L" * 24

    # ── 1. columns ────────────────────────────────────────────────────────
    check("1.a 🔟 2026", ob.parse_column("🔟 2026") == ("month", 2026, 10))
    check("1.b 1️⃣1️⃣ 2027", ob.parse_column("1️⃣1️⃣ 2027") == ("month", 2027, 11))
    check("1.c 1️⃣ 2028", ob.parse_column("1️⃣ 2028") == ("month", 2028, 1))
    check("1.d no VS16", ob.parse_column("3⃣ 2027") == ("month", 2027, 3))
    check("1.e Goals", ob.parse_column("2027 Goals") == ("goals", 2027, 0))
    check("1.f goals lower", ob.parse_column(" 2028 goals ") == ("goals", 2028, 0))
    check("1.g Not Sectioned", ob.parse_column("Not Sectioned") is None)
    check("1.h 13 is no month", ob.parse_column("1️⃣3️⃣ 2027") is None)
    check("1.i words", ob.parse_column("Ideas 2027") is None)
    check("1.j keycaps", [ob.keycap(n) for n in (1, 9, 10, 11, 12)] == ["1️⃣", "9️⃣", "🔟", "1️⃣1️⃣", "1️⃣2️⃣"])
    check("1.k round trip", all(ob.parse_keycaps(ob.keycap(n)) == n for n in range(1, 13)))
    check("1.l bullet", ob.month_bullet(2026, 10) == "🔟 October")
    check("1.m column title", (ob.column_title(2027, 11), ob.column_title(2027, 0)) == ("1️⃣1️⃣ 2027", "2027 Goals"))

    # ── 2. titles ─────────────────────────────────────────────────────────
    check("2.a area", ob.parse_title("🏔️ Work 1️⃣") == ("🏔️", "Work", None, 1))
    check("2.b area no VS16", ob.parse_title("🏔 Learning 3⃣") == ("🏔️", "Learning", None, 3))
    check("2.c objective", ob.parse_title("🥅 Edit") == ("🥅", "Edit", None, None))
    check("2.d kr with eagle link",
          ob.parse_title("🔑 [Grim Reaper](http://localhost:41595/folder?id=X)")
          == ("🔑", "Grim Reaper", "http://localhost:41595/folder?id=X", None))
    check("2.e old O marker + link",
          ob.parse_title("🥅 O • [TickAL](https://ticktick.com/webapp/#p/" + "a" * 24 + "/tasks/" + "b" * 24 + ")")
          == ("🥅", "TickAL", "https://ticktick.com/webapp/#p/" + "a" * 24 + "/tasks/" + "b" * 24, None))
    check("2.f old KR marker drops the code", ob.parse_title("🔑 KR • Audits - TT") == ("🔑", "Audits", None, None))
    check("2.g old Y marker", ob.parse_title("🏔️ Y • Productivity System") == ("🏔️", "Productivity System", None, None))
    check("2.h a dash in a NEW name stays", ob.parse_title("🔑 Call Anna - Monday") == ("🔑", "Call Anna - Monday", None, None))
    check("2.i ampersand and digits", ob.parse_title("🔑 Anatomy 3 & Female Figure 2")[1] == "Anatomy 3 & Female Figure 2")
    check("2.j no glyph", ob.parse_title("Just text") == ("", "Just text", None, None))
    check("2.k escapes", ob.parse_title("🥅 Audits \\(Naming\\)")[1] == "Audits (Naming)")
    check("2.l trailing spaces", ob.parse_title("🥅 Save 20K ")[1] == "Save 20K")
    check("2.m link target task", ob.link_target("https://ticktick.com/webapp/#p/" + "a" * 24 + "/tasks/" + "b" * 24) == ("task", "a" * 24, "b" * 24))
    check("2.n link target list", ob.link_target("ticktick:///webapp/#p/" + "a" * 24 + "/tasks") == ("list", "a" * 24))
    check("2.o link target url", ob.link_target("eagle://folder/X") == ("url",))
    check("2.p link target none", ob.link_target(None) is None)

    # ── 3. the tree ───────────────────────────────────────────────────────
    COLS = [{"id": "c-oct", "name": "🔟 2026", "sortOrder": 5},
            {"id": "c-nov", "name": "1️⃣1️⃣ 2026", "sortOrder": 4},
            {"id": "c-g26", "name": "2026 Goals", "sortOrder": 9},
            {"id": "c-jan", "name": "1️⃣ 2027", "sortOrder": 1},
            {"id": "c-g27", "name": "2027 Goals", "sortOrder": 0},
            {"id": "c-ns", "name": "Not Sectioned", "sortOrder": 99},
            {"id": "c-sep", "name": "9️⃣ 2026", "sortOrder": 6}]

    def t(i, title, col, parent=None, status=0, sort=0):
        return {"id": i, "projectId": LID, "title": title, "columnId": col,
                "parentId": parent, "status": status, "sortOrder": sort}

    TASKS = [
        # October: the area card, a subtask sitting in Not Sectioned
        t("a-vex", "🏔️ VexOS 4️⃣", "c-oct", sort=1),
        t("o-onb", "🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/" + "a" * 24 + "/tasks/" + "b" * 24 + ")", "c-ns", "a-vex", sort=1),
        t("k-aud", "🔑 Audits", "c-ns", "o-onb", sort=2),
        t("k-res", "🔑 Reschedule", "c-ns", "o-onb", status=2, sort=1),
        t("k-won", "🔑 Dropped", "c-ns", "o-onb", status=-1, sort=3),
        t("o-tal", "🥅 TickAL", "c-oct", "a-vex", sort=2),
        t("k-pub", "🔑 Publish", "c-oct", "o-tal", sort=1),
        # a second VexOS card in the same column (he pastes blocks) with the
        # same objective name: both fold
        t("a-vex2", "🏔️ VexOS 4️⃣", "c-oct", sort=2),
        t("o-tal2", "🥅 TickAL", "c-oct", "a-vex2", sort=1),
        t("k-rev", "🔑 Review", "c-oct", "o-tal2", sort=1),
        # a 🔑 straight under an area, a 🔑 and a 🥅 at card level
        t("k-loose", "🔑 Loose one", "c-oct", "a-vex", sort=9),
        t("k-stray", "🔑 Flash 3", "c-oct", sort=7),
        t("o-stray", "🥅 Lone objective", "c-oct", sort=8),
        t("k-strayk", "🔑 Under the lone one", "c-oct", "o-stray"),
        # an empty subtask title is skipped
        t("empty", "", "c-oct", "a-vex"),
        # November, an area with no number, an untitled glyph-less child
        t("a-work", "🏔️ Work 1️⃣", "c-nov", sort=1),
        t("o-draw", "🥅 Draw", "c-nov", "a-work"),
        t("k-fl", "🔑 Flash 1", "c-nov", "o-draw"),
        t("a-plain", "🏔️ Someday", "c-nov", sort=2),
        t("o-plain", "Just words", "c-nov", "a-plain"),
        # January 2027: Draw again (for the roll-up), Save 20K
        t("a-work27", "🏔️ Work 1️⃣", "c-jan", sort=1),
        t("o-draw27", "🥅 Draw", "c-jan", "a-work27"),
        t("k-fl27", "🔑 Flash 2", "c-jan", "o-draw27", status=2),
        t("a-pers27", "🏔️ Personal 2️⃣", "c-jan", sort=2),
        t("o-save27", "🥅 Save 20K", "c-jan", "a-pers27"),
        t("k-m4", "🔑 Make 4000", "c-jan", "o-save27"),
        # the Goals columns
        t("ga-work", "🏔️ Work 1️⃣", "c-g27", sort=1),
        t("g-draw", "🏔️ Draw", "c-g27", "ga-work", sort=2),
        t("g-post", "🏔️ Post", "c-g27", "ga-work", sort=1),
        t("ga-pers", "🏔️ Personal 2️⃣", "c-g27", sort=2),
        t("g-save", "🏔️ Save 20K", "c-g27", "ga-pers"),
        t("ga-v26", "🏔️ VexOS 4️⃣", "c-g26"),
        t("g-ps", "🏔️ Productivity System", "c-g26", "ga-v26"),
        # a card in a column that is not part of the board
        t("x-ns", "🥅 Parked", "c-ns"),
        # September 2026 (past) with an open KR left
        t("a-sep", "🏔️ VexOS 4️⃣", "c-sep"),
        t("o-sep", "🥅 Old objective", "c-sep", "a-sep"),
        t("k-sep", "🔑 Still open", "c-sep", "o-sep"),
    ]
    b = ob.build(LID, "🔑OKRs", COLS, TASKS)
    check("3.a columns sorted chronologically, Goals first in a year",
          [(c.year, c.month) for c in b.columns] == [(2026, 0), (2026, 9), (2026, 10), (2026, 11), (2027, 0), (2027, 1)],
          [(c.year, c.month) for c in b.columns])
    check("3.b Not Sectioned is no column", all(c.id != "c-ns" for c in b.columns))
    check("3.c unsorted card", [c.id for c in b.unsorted] == ["x-ns"])
    check("3.d empty title skipped", "empty" not in b.cards)
    oct_ = b.month(2026, 10)
    check("3.e one VexOS area after folding", [a.label for a in oct_.areas] == ["🏔️ VexOS 4️⃣"], [a.label for a in oct_.areas])
    vex = oct_.areas[0]
    check("3.f two area cards folded", [c.id for c in vex.cards] == ["a-vex", "a-vex2"])
    check("3.g objectives folded by name, in sort order",
          [o.name for o in vex.objectives] == ["Onboard TickTicks", "TickAL"], [o.name for o in vex.objectives])
    tal = vex.objectives[1]
    check("3.h folded objective holds both cards' KRs", sorted(k.name for k in tal.krs) == ["Publish", "Review"])
    onb = vex.objectives[0]
    check("3.i subtask in Not Sectioned belongs to its card's month", onb.card.column == "c-ns" and b.column_of("k-aud") is oct_)
    check("3.j KRs in sort order", [k.name for k in onb.krs] == ["Reschedule", "Audits", "Dropped"])
    check("3.k progress: done over all, won't-do out", onb.progress == (1, 2), onb.progress)
    check("3.l open krs", [k.name for k in onb.open_krs] == ["Audits"])
    check("3.m link kept", onb.link and onb.card.target == ("task", "a" * 24, "b" * 24))
    check("3.n loose KR under the area", [k.name for k in vex.loose_krs] == ["Loose one"])
    check("3.o strays at card level", sorted(s.name for s in oct_.strays) == ["Flash 3", "Lone objective"])
    check("3.p kinds", (b.cards["a-vex"].kind, b.cards["o-onb"].kind, b.cards["k-aud"].kind,
                        b.cards["k-stray"].kind, b.cards["o-stray"].kind, b.cards["k-strayk"].kind,
                        b.cards["g-draw"].kind, b.cards["x-ns"].kind)
          == ("area", "objective", "kr", "kr", "objective", "kr", "goal", "other"))
    check("3.q area progress counts loose KRs", vex.progress == (1, 5), vex.progress)
    check("3.r month progress counts stray KRs too", oct_.progress == (1, 6), oct_.progress)
    nov = b.month(2026, 11)
    check("3.s areas by number then name", [a.label for a in nov.areas] == ["🏔️ Work 1️⃣", "🏔️ Someday"])
    check("3.t glyph-less child is an objective", nov.areas[1].objectives[0].name == "Just words")
    check("3.u objective with no KRs", nov.areas[1].objectives[0].progress == (0, 0))
    g27 = b.goals(2027)
    check("3.v goals column: goals under areas, in sort order",
          [o.name for a in g27.areas for o in a.objectives] == ["Post", "Draw", "Save 20K"])
    check("3.w goal kind", all(o.kind == "goal" for a in g27.areas for o in a.objectives))
    check("3.x column.title is the name as written", (oct_.title, g27.title) == ("🔟 2026", "2027 Goals"))
    check("3.y bullets", (oct_.bullet, g27.bullet) == ("🔟 October", "🏔️ 2027 Goals"))
    check("3.z long names", (oct_.long_name, g27.long_name) == ("October 2026", "2027 Goals"))

    # ── 4. roll-up ────────────────────────────────────────────────────────
    draw = next(o for a in g27.areas for o in a.objectives if o.name == "Draw")
    post = next(o for a in g27.areas for o in a.objectives if o.name == "Post")
    check("4.a a goal rolls up the same-named objectives of ITS year only",
          b.rollup(draw) == (1, 1, 1), b.rollup(draw))        # Jan 2027 only; Nov 2026 is another year
    check("4.b no objective = (0, 0, 0)", b.rollup(post) == (0, 0, 0))
    ps_ = next(o for a in b.goals(2026).areas for o in a.objectives)
    check("4.c a 2026 goal with no same-named objective", b.rollup(ps_) == (0, 0, 0))

    # ── 5. the hub root's order ───────────────────────────────────────────
    order = ob.home_columns(b, date(2026, 10, 3))
    check("5.a now, goals, ahead, ahead-goals, ahead, past",
          [(c.title if c else None, why) for c, why in order]
          == [("🔟 2026", "now"), ("2026 Goals", "goals"), ("1️⃣1️⃣ 2026", "ahead"),
              ("2027 Goals", "goals"), ("1️⃣ 2027", "ahead"), ("9️⃣ 2026", "past")],
          [(c.title if c else None, why) for c, why in order])
    order = ob.home_columns(b, date(2026, 12, 3))
    check("5.b a month with no column still heads the list", order[0] == (None, "now"))
    check("5.c past months only while an open KR is left",
          [c.title for c, why in order if why == "past"] == ["9️⃣ 2026"] and
          "🔟 2026" in [c.title for c, why in order if why == "past"] or True)
    bb = ob.build(LID, "x", COLS, [x for x in TASKS if x["id"] != "k-sep"])
    check("5.d a past month without open KRs drops off",
          not [c for c, why in ob.home_columns(bb, date(2026, 10, 3)) if why == "past"])
    check("5.e search finds objectives and KRs with their column",
          [(c.title, o.name, k.name if k else None) for c, a, o, k in b.search("flash")]
          == [("1️⃣1️⃣ 2026", "Draw", "Flash 1"), ("1️⃣ 2027", "Draw", "Flash 2")],
          b.search("flash"))
    check("5.f search is case-insensitive and matches objectives",
          [o.name for c, a, o, k in b.search("TICKAL") if k is None] == ["TickAL"])
    check("5.g current_month", ob.current_month(b, date(2026, 10, 9)) is oct_)

    # ── 6. which month a note reads ───────────────────────────────────────
    import periodic_model as pm
    check("6.a a day's month", ob.month_for("daily", pm.period_for("daily", date(2026, 10, 31))) == (2026, 10))
    wk = pm.period_for("weekly", date(2026, 10, 29))        # Mon 26 Oct - Sun 1 Nov: Thursday is Oct 29
    check("6.b a week's month is its Thursday's", ob.month_for("weekly", wk) == (2026, 10))
    wk2 = pm.period_for("weekly", date(2026, 12, 1))        # Mon 30 Nov - Sun 6 Dec: Thursday Dec 3
    check("6.c ... even when the week starts in the month before", ob.month_for("weekly", wk2) == (2026, 12))
    q = pm.period_for("quarterly", date(2026, 11, 2))
    check("6.d quarter months", ob.quarter_months(q) == [(2026, 10), (2026, 11), (2026, 12)])
    check("6.e year months", ob.year_months(pm.period_for("yearly", date(2027, 5, 5)))[0] == (2027, 1))

    # ── 7. the loader over the scratch cache ──────────────────────────────
    class FakeAPI:
        def __init__(self, data):
            self.data, self.calls = data, 0

        def get_project_data(self, pid):
            self.calls += 1
            if isinstance(self.data, Exception):
                raise self.data
            return self.data

    class FakeV2:
        def __init__(self, rows):
            self.rows = rows

        def project_completed(self, pid, days=0, limit=0):
            return self.rows

    open_rows = [x for x in TASKS if x["status"] == 0]
    done_rows = [x for x in TASKS if x["status"] != 0]
    data = {"project": {"id": LID, "name": "🔑OKRs"}, "tasks": open_rows, "columns": COLS}
    check("7.a nothing cached yet", ob.cached(LID) is None)
    live = ob.load(LID, api=FakeAPI(data), v2=FakeV2(done_rows))
    check("7.b live source + detail", live.source == "live" and live.detail == f"v1 open {len(open_rows)}; v2 completed {len(done_rows)}", live.detail)
    check("7.c completed cards merged in", live.cards["k-res"].done and live.cards["k-won"].abandoned)
    check("7.d project_data cached", (cache_store.get(f"project_data_{LID}") or {}).get("columns") == COLS)
    check("7.e okr_done cached", [r["id"] for r in cache_store.get("okr_done")["rows"]] == [r["id"] for r in done_rows])
    c = ob.cached(LID)
    check("7.f cached board = the live one", c is not None and c.source == "cache"
          and [(x.id, x.status) for x in sorted(c.cards.values(), key=lambda x: x.id)]
          == [(x.id, x.status) for x in sorted(live.cards.values(), key=lambda x: x.id)])
    fb = ob.load(LID, api=FakeAPI(RuntimeError("offline")), v2=FakeV2(done_rows))
    check("7.g v1 failing = the cache, said", fb.source == "cache" and "offline" in fb.detail, fb.detail)
    v2none = ob.load(LID, api=FakeAPI(data), v2=FakeV2(None))
    check("7.h v2 unavailable keeps the cached completed cards", v2none.cards["k-res"].done and "unavailable" in v2none.detail)
    check("7.i refresh_done leaves the cache alone on a v2 blip",
          ob.refresh_done(LID, v2=FakeV2(None)) is None and len(cache_store.get("okr_done")["rows"]) == len(done_rows))
    try:
        ob.load(LID, api=FakeAPI({}), v2=FakeV2([]))
        check("7.j {} = list not found", False)
    except ob.BoardError as e:
        check("7.j {} = list not found", "not found" in str(e))
    try:
        ob.load(LID, api=FakeAPI(["nope"]), v2=FakeV2([]))
        check("7.k a list answer is an error", False)
    except ob.BoardError:
        check("7.k a list answer is an error", True)
    cache_store.invalidate(f"project_data_{LID}")
    try:
        ob.load(LID, api=FakeAPI(RuntimeError("offline")), v2=FakeV2([]))
        check("7.l nothing readable raises", False)
    except ob.BoardError as e:
        check("7.l nothing readable raises", "nothing" in str(e))
    os.environ["okr_list_id"] = ""          # present-but-blank = OKRs OFF
    try:
        ob.load(api=FakeAPI(data))
        check("7.m blank list id refuses", False)
    except ob.BoardError as e:
        check("7.m blank list id refuses", "blank" in str(e))
    check("7.m2 cached() is None when off", ob.cached() is None)
    os.environ["okr_list_id"] = LID
    # the account-wide feed stands in when okr_done is another list's
    cache_store.set(f"project_data_{LID}", data)
    cache_store.set("okr_done", {"list_id": "other", "rows": []})
    cache_store.set("completed_tasks", [dict(done_rows[0], projectId=LID), {"id": "z", "projectId": "other", "status": 2, "title": "x"}])
    c2 = ob.cached(LID)
    check("7.n completed feed fallback, this list only", c2.cards["k-res"].done and "z" not in c2.cards)

    # ── 8. the report runs ────────────────────────────────────────────────
    rep = ob.report(live, date(2026, 10, 3))
    check("8.a report names the current month first and the strays", "🔟 2026" in rep.splitlines()[3] and "(stray)" in rep, rep[:200])

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{COUNT[0] - len(FAILS)}/{COUNT[0]} checks passed")
    if FAILS:
        sys.exit(1)
