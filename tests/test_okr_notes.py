#!/usr/bin/env python3
"""🥅 The board in the periodic notes (src/okr_notes.py, HANDOFF_OKR section
8): the 🥅 OKRs section per tier, the yearly scorecard and its merge, the
goal pickers' choices, and the readers in periodic_model that quote the
section back for the journals - the new shape and the 2026-09 shape both.
Run: python3 tests/test_okr_notes.py
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
    sys.path.insert(0, os.path.join(ROOT, "Scripts"))

    import okr_board as ob              # noqa: E402
    import okr_notes as on              # noqa: E402
    import periodic_model as pm         # noqa: E402

    FAILS, COUNT = [], [0]

    def check(name, cond, detail=""):
        COUNT[0] += 1
        if not cond:
            FAILS.append(f"{name}: {detail}")
            print(f"  FAIL {name} {detail}")

    LID = "a" * 24
    URL = f"ticktick:///webapp/#p/{LID}/tasks/"

    def t(i, title, col, parent=None, status=0, sort=0):
        return {"id": i, "projectId": LID, "title": title, "columnId": col,
                "parentId": parent, "status": status, "sortOrder": sort}

    COLS = [{"id": "g26", "name": "2026 Goals"}, {"id": "oct", "name": "🔟 2026"},
            {"id": "nov", "name": "1️⃣1️⃣ 2026"}, {"id": "dec", "name": "1️⃣2️⃣ 2026"},
            {"id": "sep", "name": "9️⃣ 2026"}, {"id": "g27", "name": "2027 Goals"},
            {"id": "jan", "name": "1️⃣ 2027"}]
    TASKS = [
        t("ga", "🏔️ VexOS 4️⃣", "g26"), t("gps", "🏔️ Productivity System", "g26", "ga"),
        t("a1", "🏔️ VexOS 4️⃣", "oct", sort=1),
        t("o1", "🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/" + "b" * 24 + "/tasks/" + "c" * 24 + ")", "oct", "a1", sort=1),
        t("k1", "🔑 Finish periodic notes", "oct", "o1", status=2, sort=1),
        t("k2", "🔑 Audits", "oct", "o1", sort=2),
        t("k3", "🔑 Dropped", "oct", "o1", status=-1, sort=3),
        t("o2", "🥅 Shortcuts", "oct", "a1", sort=2),
    ] + [t(f"s{i}", f"🔑 App {i}", "oct", "o2", sort=i) for i in range(1, 12)] + [
        t("o3", "🥅 Audits • Execute & Establish", "oct", "a1", sort=3),
        t("k4", "🔑 AnyBox", "oct", "o3"),
        t("a2", "🏔️ Work 1️⃣", "nov", sort=1), t("o4", "🥅 Draw", "nov", "a2"), t("k5", "🔑 Flash 1", "nov", "o4"),
        t("a3", "🏔️ Work 1️⃣", "sep"), t("o5", "🥅 Old", "sep", "a3"), t("k6", "🔑 Left open", "sep", "o5"),
        t("ga7", "🏔️ Work 1️⃣", "g27", sort=1), t("gpost", "🏔️ Post", "g27", "ga7", sort=1), t("gdraw", "🏔️ Draw", "g27", "ga7", sort=2),
        t("a4", "🏔️ Work 1️⃣", "jan"), t("o6", "🥅 Draw", "jan", "a4"), t("k7", "🔑 Flash 2", "jan", "o6", status=2),
    ]
    B = ob.build(LID, "🔑OKRs", COLS, TASKS)

    # ── 1. the daily / weekly section: this month, whole ──────────────────
    p = pm.period_for("daily", date(2026, 10, 3))
    lines = on.okr_section_lines("daily", p, B)
    check("1.a month bullet with the count (won't-do out)", lines[0] == "- 🔟 October • 1/14 KRs", lines[0])
    check("1.b area line", lines[1] == "\t- 🏔️ VexOS 4️⃣ • 1/14 KRs", lines[1])
    check("1.c objective line links the card and counts", lines[2] == f"\t\t- 🥅 [Onboard TickTicks]({URL}o1) 1/2", lines[2])
    check("1.d done KR reads ✅, open 🔑, won't-do gone",
          lines[3] == f"\t\t\t- ✅ [Finish periodic notes]({URL}k1)" and lines[4] == f"\t\t\t- 🔑 [Audits]({URL}k2)"
          and not any("Dropped" in l for l in lines), lines[3:6])
    shortcuts = lines.index(f"\t\t- 🥅 [Shortcuts]({URL}o2) 0/11")
    check("1.e key results capped at 8 then +N more", lines[shortcuts + 9] == "\t\t\t- +3 more"
          and lines[shortcuts + 1] == f"\t\t\t- 🔑 [App 1]({URL}s1)", lines[shortcuts:shortcuts + 11])
    check("1.f a name with the separator in it survives", any(l == f"\t\t- 🥅 [Audits • Execute & Establish]({URL}o3) 1/1".replace("1/1", "0/1") for l in lines), [l for l in lines if "Audits •" in l])
    wk = pm.period_for("weekly", date(2026, 11, 2))         # Mon 2 Nov: Thursday is 5 Nov
    wl = on.okr_section_lines("weekly", wk, B)
    check("1.g a week reads its Thursday's month", wl[0] == "- 1️⃣1️⃣ November • 0/1 KRs" and wl[2] == f"\t\t- 🥅 [Draw]({URL}o4) 0/1", wl)
    wk2 = pm.period_for("weekly", date(2026, 10, 26))       # Mon 26 Oct: Thursday is 29 Oct
    check("1.h ... even when the week ends in November", on.okr_section_lines("weekly", wk2, B)[0].startswith("- 🔟 October"))
    dl = on.okr_section_lines("daily", pm.period_for("daily", date(2026, 12, 5)), B)
    check("1.i an empty month says so", dl == ["- 1️⃣2️⃣ December • nothing planned"], dl)
    dl = on.okr_section_lines("daily", pm.period_for("daily", date(2027, 3, 5)), B)
    check("1.j a missing column says so", dl == ["- 3️⃣ March • no column on the board"], dl)
    check("1.k no board = nothing to write", on.okr_section_lines("daily", p, None) == [])

    # ── 2. the monthly: its month whole, the quarter's other months objectives only ──
    ml = on.okr_section_lines("monthly", pm.period_for("monthly", date(2026, 10, 1)), B)
    tops = [l for l in ml if not l.startswith("\t")]
    check("2.a three month bullets, its own first", tops == ["- 🔟 October • 1/14 KRs", "- 1️⃣1️⃣ November • 0/1 KRs", "- 1️⃣2️⃣ December • nothing planned"], tops)
    nov_at = ml.index("- 1️⃣1️⃣ November • 0/1 KRs")
    check("2.b the other months carry objectives, no key results", ml[nov_at + 2] == f"\t\t- 🥅 [Draw]({URL}o4) 0/1" and not any(l.startswith("\t\t\t") for l in ml[nov_at:]), ml[nov_at:])
    check("2.c its own month carries the key results", any(l.startswith("\t\t\t- 🔑 [Audits]") for l in ml[:nov_at]))

    # ── 3. the quarterly and the yearly: the goals bullet, then the months ──
    ql = on.okr_section_lines("quarterly", pm.period_for("quarterly", date(2026, 11, 1)), B)
    check("3.a goals bullet first, with the area and the goal", ql[:3] == ["- 🏔️ 2026 Goals • 1 goal", "\t- 🏔️ VexOS 4️⃣", f"\t\t- 🏔️ [Productivity System]({URL}gps)"], ql[:3])
    check("3.b then the three months", [l for l in ql if not l.startswith("\t")][1:] == ["- 🔟 October • 1/14 KRs", "- 1️⃣1️⃣ November • 0/1 KRs", "- 1️⃣2️⃣ December • nothing planned"], ql)
    check("3.c objectives only", not any(l.startswith("\t\t\t") for l in ql))
    yl = on.okr_section_lines("yearly", pm.period_for("yearly", date(2027, 6, 1)), B)
    check("3.d the year's goals with the roll-up of same-named objectives",
          yl[:4] == ["- 🏔️ 2027 Goals • 2 goals", "\t- 🏔️ Work 1️⃣", f"\t\t- 🏔️ [Post]({URL}gpost)", f"\t\t- 🏔️ [Draw]({URL}gdraw) 1/1 • 1 month"], yl[:4])
    check("3.e only the planned months follow", [l for l in yl if not l.startswith("\t")][1:] == ["- 1️⃣ January • 1/1 KRs"], yl)
    y26 = on.okr_section_lines("yearly", pm.period_for("yearly", date(2026, 1, 1)), B)
    check("3.f a past month with a key result still open is listed (September)", any(l.startswith("- 9️⃣ September") for l in y26), y26)
    gl = on.goals_lines(B, 2028, LID)
    check("3.g a year without a Goals column", gl == ["- 🏔️ 2028 Goals • no column on the board"], gl)

    # ── 4. the scorecard: flat lines, the bar, the area chip, merge keeps his ──
    sc = on.scorecard_lines(pm.period_for("yearly", date(2027, 1, 1)), B)
    check("4.a a goal with objectives: bar, count, months, area",
          sc[1] == f"- 🏔️ [Draw]({URL}gdraw) ▰▰▰▰▰ 1/1 • 1 month • Work 1️⃣", sc)
    check("4.b a goal without: the chip", sc[0] == f"- 🏔️ [Post]({URL}gpost) • no objectives yet • Work 1️⃣", sc)
    check("4.c both are plan lines", all(pm.is_plan_line(l) for l in sc))
    check("4.d the bar", (on.bar(0, 5), on.bar(1, 2), on.bar(4, 5), on.bar(5, 5), on.bar(3, 3)) == ("▱▱▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰", "▰▰▰▰▰"))
    body = ["- 🏔️ [Old](u) ▱▱▱▱▱ 0/3 • Jan 5 - Dec 20", "- [ ] Earn 50k", "\t- [ ] Weekly check", "_(pending)_"]
    merged = on.merge_scorecard(body, sc)
    check("4.e merge: ours regenerated, his goals kept after, pending gone",
          merged == sc + ["- [ ] Earn 50k", "\t- [ ] Weekly check"], merged)
    check("4.f merge with no plan: his lines, or pending", on.merge_scorecard(body, []) == ["- [ ] Earn 50k", "\t- [ ] Weekly check"]
          and on.merge_scorecard(["_(pending)_"], []) == ["_(pending)_"])
    check("4.g no Goals column = no scorecard lines", on.scorecard_lines(pm.period_for("yearly", date(2028, 1, 1)), B) == [])
    check("4.h the scorecard reader quotes both kinds of line",
          pm.scorecard_objectives(sc) == ["Post", "Draw 1/1"], pm.scorecard_objectives(sc))

    # ── 5. the readers: the new shape round-trips ──────────────────────────
    kr, objs = pm.okr_journal_ctx(lines)
    check("5.a evening: the month's key results off the note (done ones too, won't-do never), capped",
          kr == "Finish periodic notes · Audits · App 1 · App 2 · App 3 · App 4 · App 5 · App 6 · +3 more", kr)
    check("5.b evening: the month's objectives with their counts",
          objs == "Onboard TickTicks 1/2 · Shortcuts 0/11 · Audits • Execute & Establish 0/1", objs)
    wkr, _o = pm.okr_journal_ctx(wl, kr_tier="weekly", keep_state=True)
    check("5.c weekly: the glyphs kept", wkr == "🔑 Flash 1", wkr)
    check("5.d monthly: the first month's objectives, the quarter's every month's (one per name)",
          pm.okr_tier_items(ml, "monthly") == ["Onboard TickTicks 1/2", "Shortcuts 0/11", "Audits • Execute & Establish 0/1"]
          and pm.okr_tier_items(ml, "quarterly") == ["Onboard TickTicks 1/2", "Shortcuts 0/11", "Audits • Execute & Establish 0/1", "Draw 0/1"],
          pm.okr_tier_items(ml, "quarterly"))
    check("5.e yearly: the goals bullet, with the roll-up count", pm.okr_tier_items(yl, "yearly") == ["Post", "Draw 1/1"], pm.okr_tier_items(yl, "yearly"))
    check("5.f quarterly note: year goals off the goals bullet", pm.okr_tier_items(ql, "yearly") == ["Productivity System"], pm.okr_tier_items(ql, "yearly"))
    check("5.g an empty month quotes nothing", pm.okr_journal_ctx(["- 1️⃣2️⃣ December • nothing planned"]) == ("", ""))
    check("5.h a phone's spaces read like tabs", pm.okr_tier_items([l.replace("\t", "    ") for l in ml], "monthly") == pm.okr_tier_items(ml, "monthly"))
    check("5.i the app's escapes read", pm.okr_tier_items([l.replace("(", "\\(").replace(")", "\\)") for l in ml], "monthly")[0] == "Onboard TickTicks 1/2")

    # ── 6. the readers: the 2026-09 shape (closed notes) reads as it did ──
    OLD = ["- 🎉 2026 • 1/41 KRs", "\t- 🏔️ [Productivity System](u) 1/41",
           "- 🌓 Q3 • 1/7 KRs", "\t- 🥅 [Onboard TickTicks](u) 0/5", "\t- 🥅 [TickAL](u) 1/6 🔴 3d",
           "- 🗓️ Sep • 1/7 KRs", "\t- 🥅 [Onboard TickTicks](u) 0/5", "\t- 🥅 [TickAL](u) 1/6",
           "- ♻️ W39 • 1/5 KRs", "\t- ✅ [Goals wf](u)", "\t- 🔑 [Finish periodic notes](u)",
           "- ☀️ Thu 24 • 0/1 KRs", "\t- 🔑 [Finish periodic notes](u) 🔴 1d"]
    check("6.a old day + month", pm.okr_journal_ctx(OLD) == ("Finish periodic notes", "Onboard TickTicks 0/5 · TickAL 1/6"), pm.okr_journal_ctx(OLD))
    check("6.b old week with state", pm.okr_journal_ctx(OLD, "weekly", True)[0] == "✅ Goals wf · 🔑 Finish periodic notes")
    check("6.c old quarter and year", pm.okr_tier_items(OLD, "quarterly") == ["Onboard TickTicks 0/5", "TickAL 1/6"] and pm.okr_tier_items(OLD, "yearly") == ["Productivity System 1/41"])
    check("6.d an old note without the tier quotes nothing", pm.okr_tier_items(OLD[:2], "monthly") == [])

    # ── 7. the goal pickers' choices ───────────────────────────────────────
    names = lambda picks: [getattr(x, "name", None) for _c, x in picks]
    d = on.goal_choices("daily", p, B)
    check("7.a a day: the month's open key results, then its open objectives",
          names(d)[:3] == ["Audits", "App 1", "App 2"] and names(d)[-3:] == ["Onboard TickTicks", "Shortcuts", "Audits • Execute & Establish"]
          and "Finish periodic notes" not in names(d) and "Dropped" not in names(d), names(d))
    check("7.b each choice names its column", {c.title for c, _x in d} == {"🔟 2026"})
    m = on.goal_choices("monthly", pm.period_for("monthly", date(2026, 10, 1)), B)
    check("7.c a month: objectives first", names(m)[:3] == ["Onboard TickTicks", "Shortcuts", "Audits • Execute & Establish"], names(m))
    q = on.goal_choices("quarterly", pm.period_for("quarterly", date(2026, 10, 1)), B)
    check("7.d a quarter: its months' objectives, one per name", names(q) == ["Onboard TickTicks", "Shortcuts", "Audits • Execute & Establish", "Draw"], names(q))
    y = on.goal_choices("yearly", pm.period_for("yearly", date(2027, 1, 1)), B)
    check("7.e a year: its goals", names(y) == ["Post", "Draw"] and all(x.kind == "goal" for _c, x in y), names(y))
    check("7.f no column, no board = nothing", on.goal_choices("daily", pm.period_for("daily", date(2027, 3, 1)), B) == []
          and on.goal_choices("daily", p, None) == [])

    print(f"{COUNT[0] - len(FAILS)}/{COUNT[0]} checks passed")
    if FAILS:
        sys.exit(1)
