#!/usr/bin/env python3
"""The weekly note's HEAD and its goals (Vex 2026-09-17).

Two things the pure suite (tests/test_periodic.py) cannot reach, because it
deliberately imports no engine: the mint-then-refresh invariant for the day
links under the breadcrumb, and the tiered 🏆 Goals.

Tiered goals (Vex 2026-09-17: "under goals … quarter goal, month
goal and week goal", the daily note's shape one tier up).

🏆 Goals holds 🌓 Quarterly and 🗓️ Monthly - MIRRORS of their own notes, reset
to their pointer when the parent has none - plus ♻️ Weekly, the week's own,
which is the only one that may travel into the daily note or into the weekly
journal's "did you achieve your weekly goals?".

No network: the parent notes are rendered from the shipped templates into a
fake index.

    python3 tests/test_weekly_goals.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import sys
    from datetime import date

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import periodic_sections as ps, periodic_model as pm, periodic_engine as pe

    P = F = 0
    def check(n, c, d=""):
        global P, F
        if c: P += 1
        else:
            F += 1
            print("  FAIL", n, d)

    TPL = open(os.path.join(ROOT, "src", "periodic_templates", "weekly.md"),
                encoding="utf-8").read()
    doc = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))

    # 1. the three bullets resolve, scoped to 🏆 Goals
    for a in (pm.SEC_WK_QTR, pm.SEC_WK_MONTH, pm.SEC_WK_WEEK):
        check(f"resolves {a}", ps.find(doc, a, pm.SEC_GOALS) is not None)

    # 2. a fresh note has no week goals, and the home is the bullet
    check("no goals at mint", pe._week_goals_of(doc)[0] == [])
    check("home is the bullet", pe._week_goal_home(doc) == pm.SEC_WK_WEEK)

    # 3. the mirrors only carry REAL goals
    idx = {}
    def parent(kind, body):
        tpl = pe._load_template(kind)
        d = ps.parse_sections(pm.render_template(tpl, {"breadcrumbs": "C"}))
        if body:
            ps.set_body(d, pm.GOAL_SECTION[kind], body)
        idx[(kind, pm.title_key(pm.period_for(kind, date(2026, 9, 14))))] = {
            "content": ps.serialize_sections(d), "id": "X", "projectId": "P"}

    parent("monthly", ["\t- [ ] Onboard TickTick"])
    parent("quarterly", None)          # ships "_(score last quarter's OKRs…)_"
    pe._mirror_goal(doc, pm.SEC_WK_MONTH, "monthly", idx, date(2026, 9, 14), pm.HINT_WK_MONTH)
    pe._mirror_goal(doc, pm.SEC_WK_QTR, "quarterly", idx, date(2026, 9, 14), pm.HINT_WK_QTR)
    mb = ps.find(doc, pm.SEC_WK_MONTH, pm.SEC_GOALS).body
    qb = ps.find(doc, pm.SEC_WK_QTR, pm.SEC_GOALS).body
    check("month goal mirrored", any("Onboard TickTick" in l for l in mb), mb)
    check("an empty parent keeps the pointer", any("mirrors this quarter" in l for l in qb), qb)
    check("a bare '- [ ]' is not a goal",
          "Onboard" not in "".join(qb))

    # 4. a cleared parent RESETS the mirror - never a stale copy
    parent("monthly", ["\t- [ ]"])
    pe._mirror_goal(doc, pm.SEC_WK_MONTH, "monthly", idx, date(2026, 9, 14), pm.HINT_WK_MONTH)
    mb = ps.find(doc, pm.SEC_WK_MONTH, pm.SEC_GOALS).body
    check("cleared parent resets the mirror",
          any("mirrors this month" in l for l in mb) and "Onboard" not in "".join(mb), mb)

    # 4b. every tier above mirrors in (Vex 2026-10-04: "make sure every goal
    # level is shown in notes"): the weekly's 🎉 Yearly, the monthly's 🎉 Yearly
    # goal, the daily's 🎉 Yearly / 🌓 Quarterly / 🗓️ Monthly - each a template
    # bullet, filled by _mirror_goal from the parent's own goal, the pointer
    # when the parent has none
    parent("yearly", ["\t- [ ] Productivity System"])
    check("weekly template carries 🎉 Yearly", ps.find(doc, pm.SEC_WK_YEAR, pm.SEC_GOALS) is not None)
    pe._mirror_goal(doc, pm.SEC_WK_YEAR, "yearly", idx, date(2026, 9, 14), pm.HINT_YEAR)
    yb = ps.find(doc, pm.SEC_WK_YEAR, pm.SEC_GOALS).body
    check("the year's goal mirrored into the weekly", any("Productivity System" in l for l in yb), yb)
    mdoc = ps.parse_sections(pm.render_template(pe._load_template("monthly"), {"breadcrumbs": "C"}))
    check("monthly template carries 🎉 Yearly goal above 🌓 Quarterly goal",
          [b for b in (pm.SEC_MTH_YEAR, pm.SEC_MTH_QTR, pm.SEC_MTH_MONTH) if ps.find(mdoc, b, pm.SEC_GOALS) is not None]
          == [pm.SEC_MTH_YEAR, pm.SEC_MTH_QTR, pm.SEC_MTH_MONTH])
    pe._mirror_goal(mdoc, pm.SEC_MTH_YEAR, "yearly", idx, date(2026, 9, 14), pm.HINT_YEAR)
    check("the year's goal mirrored into the monthly", any("Productivity System" in l for l in ps.find(mdoc, pm.SEC_MTH_YEAR, pm.SEC_GOALS).body))
    ddoc = ps.parse_sections(pm.render_template(pe._load_template("daily"), {"breadcrumbs": "C"}))
    order = [b for b in (pm.SEC_DAY_YEAR, pm.SEC_DAY_QTR, pm.SEC_DAY_MONTH, pm.SEC_WEEK_GOALS, pm.SEC_DAY_GOAL)
             if ps.find(ddoc, b, pm.SEC_GOALS) is not None]
    check("daily template: year, quarter, month, week, day", order == [pm.SEC_DAY_YEAR, pm.SEC_DAY_QTR, pm.SEC_DAY_MONTH, pm.SEC_WEEK_GOALS, pm.SEC_DAY_GOAL], order)
    pe._mirror_goal(ddoc, pm.SEC_DAY_YEAR, "yearly", idx, date(2026, 9, 14), pm.HINT_YEAR)
    pe._mirror_goal(ddoc, pm.SEC_DAY_QTR, "quarterly", idx, date(2026, 9, 14), pm.HINT_WK_QTR)
    pe._mirror_goal(ddoc, pm.SEC_DAY_MONTH, "monthly", idx, date(2026, 9, 14), pm.HINT_WK_MONTH)
    check("the daily mirrors the year, the quarter's pointer, the month",
          any("Productivity System" in l for l in ps.find(ddoc, pm.SEC_DAY_YEAR, pm.SEC_GOALS).body)
          and any("mirrors this quarter" in l for l in ps.find(ddoc, pm.SEC_DAY_QTR, pm.SEC_GOALS).body)
          and any("mirrors this month" in l for l in ps.find(ddoc, pm.SEC_DAY_MONTH, pm.SEC_GOALS).body),
          [ps.find(ddoc, b, pm.SEC_GOALS).body for b in (pm.SEC_DAY_YEAR, pm.SEC_DAY_QTR, pm.SEC_DAY_MONTH)])
    check("a daily without the bullet is left alone (the kill switch)",
          pe._mirror_goal(ps.parse_sections("#### 🏆 Goals\n- ☀️ Daily\n\t- [ ] x\n"), pm.SEC_DAY_YEAR, "yearly", idx, date(2026, 9, 14), pm.HINT_YEAR) is None)
    check("the week's own goals are still only ♻️ Weekly's", pe._week_goals_of(doc)[0] == [])
    # the shared filler fills a weekly's three mirrors in one call - for a week that has
    # not started too (Vex 2026-10-04: next week's note said "set it there" all Sunday)
    fdoc = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
    pe._fill_goal_mirrors(fdoc, pm.period_for("weekly", date(2026, 9, 21)), idx)
    check("a future week's mirrors fill: the year's goal, the month's pointer, the quarter's pointer",
          any("Productivity System" in l for l in ps.find(fdoc, pm.SEC_WK_YEAR, pm.SEC_GOALS).body)
          and any("mirrors this month" in l for l in ps.find(fdoc, pm.SEC_WK_MONTH, pm.SEC_GOALS).body)
          and any("mirrors this quarter" in l for l in ps.find(fdoc, pm.SEC_WK_QTR, pm.SEC_GOALS).body),
          [ps.find(fdoc, b, pm.SEC_GOALS).body for b in (pm.SEC_WK_YEAR, pm.SEC_WK_MONTH, pm.SEC_WK_QTR)])
    d2 = ps.parse_sections(pm.render_template(pe._load_template("daily"), {"breadcrumbs": "C"}))
    pe._fill_goal_mirrors(d2, pm.period_for("daily", date(2026, 9, 21)), idx)
    check("the daily's week mirror rides the same filler, pointer when the week has none",
          any("mirrors this week" in l for l in ps.find(d2, pm.SEC_WEEK_GOALS, pm.SEC_GOALS).body)
          and any("Productivity System" in l for l in ps.find(d2, pm.SEC_DAY_YEAR, pm.SEC_GOALS).body))
    check("the dependents table covers the four tiers that mirror down",
          set(pe._MIRROR_DEPENDENTS) == {"yearly", "quarterly", "monthly", "weekly"})
    # 4c. a week's month, quarter and year are its THURSDAY's (ISO), the rule its
    # 🥅 OKRs section reads the board by. W40 2026 runs 28 Sep to 4 Oct: it shows
    # October's board, so it mirrors October's and Q4's goals - not September's and
    # Q3's, which it did while the mirrors read the Monday (Vex 2026-10-04: Q4's goal
    # set, this week's note still said "set it there")
    def parent_on(kind, day, body):
        d = ps.parse_sections(pm.render_template(pe._load_template(kind), {"breadcrumbs": "C"}))
        ps.set_body(d, pm.GOAL_SECTION[kind], body)
        idx[(kind, pm.title_key(pm.period_for(kind, day)))] = {
            "content": ps.serialize_sections(d), "id": "X", "projectId": "P"}
    parent_on("monthly", date(2026, 9, 14), ["\t- [ ] September goal"])
    parent_on("monthly", date(2026, 10, 1), ["\t- [ ] October goal"])
    parent_on("quarterly", date(2026, 9, 14), ["\t- [ ] Q3 goal"])
    parent_on("quarterly", date(2026, 10, 1), ["\t- [ ] Q4 goal"])
    w40 = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
    pe._fill_goal_mirrors(w40, pm.period_for("weekly", date(2026, 9, 28)), idx)
    mb40 = ps.find(w40, pm.SEC_WK_MONTH, pm.SEC_GOALS).body
    qb40 = ps.find(w40, pm.SEC_WK_QTR, pm.SEC_GOALS).body
    check("a straddling week mirrors its Thursday's month (W40 -> October)",
          any("October goal" in l for l in mb40) and "September" not in "".join(mb40), mb40)
    check("and its Thursday's quarter (W40 -> Q4)",
          any("Q4 goal" in l for l in qb40) and "Q3" not in "".join(qb40), qb40)
    w38 = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
    pe._fill_goal_mirrors(w38, pm.period_for("weekly", date(2026, 9, 14)), idx)
    check("a week inside one month mirrors that month (W38 -> September)",
          any("September goal" in l for l in ps.find(w38, pm.SEC_WK_MONTH, pm.SEC_GOALS).body))
    # 29 Dec 2025 to 4 Jan 2026 is W1 of 2026: its year is 2026's
    parent_on("yearly", date(2025, 6, 1), ["\t- [ ] 2025 goal"])
    parent_on("yearly", date(2026, 6, 1), ["\t- [ ] 2026 goal"])
    w1 = ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
    pe._fill_goal_mirrors(w1, pm.period_for("weekly", date(2025, 12, 29)), idx)
    yb1 = ps.find(w1, pm.SEC_WK_YEAR, pm.SEC_GOALS).body
    check("a week straddling the year mirrors its Thursday's year (W1 2026 -> 2026)",
          any("2026 goal" in l for l in yb1) and "2025" not in "".join(yb1), yb1)
    parent("monthly", ["\t- [ ]"])          # back to the state section 5 expects

    # 4d. the BOARD fills into a note whose period has not started (Vex 2026-10-04,
    # Sunday: "Why are OKRs now pending?" - W41, minted that morning, read
    # "_(pending)_" under 🥅 OKRs all day because refresh_period ran _fill_okr only
    # inside the live window); a sealed week keeps the board it had; and mint_ahead
    # refreshes the week ahead on Sunday. refresh_period is driven with its I/O
    # stubbed, the way tests/test_pn_sync.py drives it.
    import okr_board as ob
    import tempfile
    LID = "a" * 24
    BOARD = ob.build(LID, "🔑OKRs", [{"id": "oct", "name": "🔟 2026"}], [
        {"id": "ar", "projectId": LID, "title": "🏔️ VexOS 4️⃣", "columnId": "oct", "parentId": None, "status": 0, "sortOrder": 1},
        {"id": "ob1", "projectId": LID, "title": "🥅 KeyCue", "columnId": "oct", "parentId": "ar", "status": 0, "sortOrder": 1},
        {"id": "kr1", "projectId": LID, "title": "🔑 TickTick", "columnId": "oct", "parentId": "ob1", "status": 0, "sortOrder": 1}])
    saved = {n: getattr(pe, n) for n in ("_today", "_api", "_pn_rmw", "_compose_lead", "_fill_weekly",
                                          "_heal_own_goals", "_okr_board", "_completed_between",
                                          "_swept_load", "_swept_add", "LOG_FILE", "SWEPT_FILE")}
    tmpd = tempfile.mkdtemp()
    pe.LOG_FILE = os.path.join(tmpd, "periodic.log")
    pe.SWEPT_FILE = os.path.join(tmpd, "swept.json")
    pe._today = lambda: date(2026, 10, 4)                 # Sunday, W40's last day
    pe._api = lambda: object()
    pe._compose_lead = lambda doc, p, index, refetch: None
    pe._fill_weekly = lambda *a, **k: None
    pe._heal_own_goals = lambda *a, **k: None
    pe._completed_between = lambda a, b: None
    pe._okr_board = lambda: (LID, BOARD)
    DOCS = {}
    def fake_rmw(pid, tid, mutate):
        d = DOCS[tid]
        return mutate(d, {}), d
    pe._pn_rmw = fake_rmw
    def fresh_weekly():
        return ps.parse_sections(pm.render_template(TPL, {"breadcrumbs": "C", "daylinks": "- d"}))
    DOCS["W41"] = fresh_weekly()
    DOCS["W40"] = fresh_weekly()
    DOCS["W38"] = fresh_weekly()
    IDX = {("weekly", pm.title_key(pm.period_for("weekly", date(2026, 10, 5)))): {"id": "W41", "projectId": "P"},
           ("weekly", pm.title_key(pm.period_for("weekly", date(2026, 9, 28)))): {"id": "W40", "projectId": "P"},
           ("weekly", pm.title_key(pm.period_for("weekly", date(2026, 9, 14)))): {"id": "W38", "projectId": "P"}}
    check("a fresh weekly ships 🥅 OKRs as _(pending)_",
          any("_(pending)_" in l for l in ps.find(DOCS["W41"], pm.SEC_OKR).body))
    pe.refresh_period(pm.period_for("weekly", date(2026, 10, 5)), index=IDX)
    okr41 = ps.find(DOCS["W41"], pm.SEC_OKR).body
    check("next week's note gets the board on Sunday (the fill runs before the period starts)",
          any("KeyCue" in l for l in okr41) and not any("_(pending)_" in l for l in okr41), okr41)
    pe.refresh_period(pm.period_for("weekly", date(2026, 9, 28)), index=IDX)
    check("this week's note fills too", any("KeyCue" in l for l in ps.find(DOCS["W40"], pm.SEC_OKR).body))
    pe.refresh_period(pm.period_for("weekly", date(2026, 9, 14)), index=IDX)
    check("a sealed week keeps what it had (W38 ended 20 Sep)",
          any("_(pending)_" in l for l in ps.find(DOCS["W38"], pm.SEC_OKR).body))
    # mint_ahead on a Sunday refreshes the coming week's note as well as today's periods
    seen = []
    saved2 = {n: getattr(pe, n) for n in ("refresh_period", "build_index", "create_note", "_read_stamp", "STAMP_FILE")}
    pe.refresh_period = lambda p, index=None, force=False: seen.append(pm.title_key(p))
    pe.build_index = lambda force=False: {("x", "y"): {}}
    pe.create_note = lambda p, index: None
    pe._read_stamp = lambda: ""
    pe.STAMP_FILE = os.path.join(tmpd, "stamp")
    pe.lookup = (lambda _orig: (lambda index, p: {"id": "any"}))(pe.lookup)
    pe.mint_ahead(force=True)
    check("Sunday's mint_ahead refreshes the week ahead (W41) too",
          pm.title_key(pm.period_for("weekly", date(2026, 10, 5))) in seen, seen)
    check("…and still refreshes the running week", pm.title_key(pm.period_for("weekly", date(2026, 10, 4))) in seen, seen)
    pe._today = lambda: date(2026, 10, 3)                 # a Saturday: no week-ahead refresh
    seen.clear()
    pe.mint_ahead(force=True)
    check("on a Saturday only the running week is refreshed",
          pm.title_key(pm.period_for("weekly", date(2026, 10, 5))) not in seen, seen)
    import importlib
    pe = importlib.reload(pe)

    # 5. the week's own goals: appended into ♻️ Weekly, and ONLY those travel
    ps.append_body(doc, pe._week_goal_home(doc), ["\t- [ ] Ship the monthly note"])
    parent("monthly", ["\t- [ ] Onboard TickTick"])
    pe._mirror_goal(doc, pm.SEC_WK_MONTH, "monthly", idx, date(2026, 9, 14), pm.HINT_WK_MONTH)
    own, sec = pe._week_goals_of(doc)
    check("own goal lands in the week bullet",
          len(own) == 1 and "Ship the monthly note" in own[0], own)
    check("the mirrors never travel", "Onboard" not in "".join(own), own)
    check("the journal asks about the week's goals only",
          pm.goal_titles(own) == ["Ship the monthly note"], pm.goal_titles(own))

    # 6. the OLD shape still works end to end (notes minted before today)
    old = ps.parse_sections("C\n---\n#### 🏆 Goals\n\t- [ ] Old style goal\n"
                            "#### ✨ Highlight\n")
    o_own, _ = pe._week_goals_of(old)
    check("old shape reads the section", [l.strip() for l in o_own] == ["- [ ] Old style goal"], o_own)
    check("old shape appends to the section", pe._week_goal_home(old) == pm.SEC_GOALS)

    # 7. the kill switch: delete ♻️ Weekly and NOTHING leaks into the daily
    killed = ps.parse_sections(ps.serialize_sections(doc).replace("- ♻️ Weekly\n", ""))
    k_own, k_sec = pe._week_goals_of(killed)
    check("deleting the bullet stops the mirror", k_own == [] and k_sec is None, k_own)
    check("...and does NOT fall back to the whole section",
          "Onboard" not in "".join(k_own))

    # ── the head: mint and refresh must agree, or the note grows a second block ──
    _ix = {("daily", "2026-09-14"): {"id": "D1", "projectId": "PID"}}
    _p = pm.period_for("weekly", date(2026, 9, 17))
    _mint = ps.parse_sections(pm.render_template(
        TPL, {"breadcrumbs": pe._crumb(_p, _ix),
              "daylinks": "\n".join(pe._day_links(_p, _ix))}))
    check("mint writes seven day bullets",
          sum(1 for l in _mint.lead if pm.DAY_LINK_RE.match(l)) == 7, _mint.lead)
    check("mint links the day that has a note",
          "- [Mon, 14th Sep](https://ticktick.com/webapp/#p/PID/tasks/D1)" in _mint.lead,
          _mint.lead)
    check("mint leaves the rest plain",
          "- Tue, 15th Sep" in _mint.lead, _mint.lead)
    _before = list(_mint.lead)
    pe._compose_lead(_mint, _p, _ix, refetch=False)
    check("a refresh right after mint changes nothing", _mint.lead == _before,
          (_before, _mint.lead))
    pe._compose_lead(_mint, _p, _ix, refetch=False)
    check("refresh never doubles the block",
          sum(1 for l in _mint.lead if pm.DAY_LINK_RE.match(l)) == 7
          and sum(1 for l in _mint.lead if l.strip() == "---") == 2, _mint.lead)
    _ix[("daily", "2026-09-15")] = {"id": "D2", "projectId": "PID"}
    pe._compose_lead(_mint, _p, _ix, refetch=False)
    check("a day minted later heals into a link",
          "- [Tue, 15th Sep](https://ticktick.com/webapp/#p/PID/tasks/D2)" in _mint.lead
          and sum(1 for l in _mint.lead if pm.DAY_LINK_RE.match(l)) == 7, _mint.lead)
    check("the note below the head is untouched",
          ps.find(_mint, pm.SEC_GOALS) is not None
          and ps.find(_mint, pm.SEC_WK_WEEK, pm.SEC_GOALS) is not None)
    # every other tier: no block, no stray divider
    for _k in ("daily", "monthly", "quarterly", "yearly"):
        _d = ps.parse_sections(pm.render_template(
            pe._load_template(_k), {"breadcrumbs": "C"}))
        pe._compose_lead(_d, pm.period_for(_k, date(2026, 9, 17)), {}, refetch=False)
        check(f"{_k} lead has no day block",
              not any(pm.DAY_LINK_RE.match(l) for l in _d.lead), _d.lead)

    print(f"weekly note: {P} passed, {F} failed")
    sys.exit(1 if F else 0)
