#!/usr/bin/env python3
"""The 🥅 OKRs section of the periodic notes and the yearly scorecard
(HANDOFF_OKR phase 4, src/okr_notes.py + periodic_engine._fill_okr).

Vex 2026-09-19: "We should also then have the OKRs section in periodic notes.
All of them. With all levels. ... hand picked goals ... should appear in the
same line as the forecasted goal for that period". The fixture is his
🏆Goals Planning list as the cache held it on 2026-09-19 (six O's, 41 KRs,
nothing done, no Y yet), trimmed to what the lines read, plus small made-up
plans for what the live list has no example of (a Y, a done KR, a won't-do
one, caps).

No network, no TickTick: the plan is handed in, the index is fake, and the
note write (_pn_rmw) runs its mutate on an in-memory doc.

    python3 tests/test_okr_notes.py
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import mdtext  # noqa: E402
import okr  # noqa: E402
import okr_notes as on  # noqa: E402
import periodic_engine as pe  # noqa: E402
import periodic_model as pm  # noqa: E402
import periodic_sections as ps  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


LIST = "6aac1b808f089e43641f5e90"
CTA = "6a3413e02522110c0d06e678"
TODAY = date(2026, 9, 19)                   # a Saturday, ISO week 38


def d(m, day, y=2026):
    return date(y, m, day)


def D(tid, title, s=None, e=None, parent=None, status=0):
    """A raw plan task from INCLUSIVE dates, the way okr writes a span."""
    st = du = None
    if s is not None:
        st, du = okr.span_raw(s, e or s)
    return {"id": tid, "projectId": LIST, "title": title, "startDate": st,
            "dueDate": du, "timeZone": "", "isAllDay": True, "status": status,
            "parentId": parent, "childIds": [], "tags": []}


def live_plan():
    """The live list on 2026-09-19, the parts the five notes read."""
    rows = [
        D("o_ot", "🥅 O • Onboard TickTicks", d(9, 18), d(9, 28)),
        D("o_ta", "🥅 O • TickAL", d(9, 29), d(10, 14)),   # stale stored span
        D("o_kc", "🥅 O • KeyCue/MIAs/Shared actions", d(10, 15), d(11, 13)),
        D("o_au", "🥅 O • Audits • Execute & Establish (Naming Conventions)",
          d(11, 14), d(11, 25)),
        D("o_wf", "🥅 O • Workflows", d(11, 26), d(12, 24)),
        D("o_ot2", "🥅 O • Other things", d(12, 25), d(12, 25)),
        D("k1", "🔑 KR • Finish periodic notes - TT", d(9, 18), d(9, 18), "o_ot"),
        D("k2", "🔑 KR • Goals wf - TA", d(9, 19), d(9, 21), "o_ta"),
        D("k3", "🔑 KR • Reschedule Goals (used to be OKRs) - TT", d(9, 22), d(9, 22), "o_ot"),
        D("k4", "🔑 KR • Audits - TT", d(9, 23), d(9, 24), "o_ot"),
        D("k5", "🔑 KR • Curriculums - TT", d(9, 25), d(9, 25), "o_ot"),
        D("k6", "🔑 KR • Review - TT", d(9, 26), d(9, 28), "o_ot"),
        D("k7", "🔑 KR • Review/test content pl wf - TA", d(9, 29), d(10, 3), "o_ta"),
        D("k8", "🔑 KR • Figure out bridges wf - TA", d(10, 4), d(10, 5), "o_ta"),
        D("k9", "🔑 KR • Run codebase review skill - TA", d(10, 6), d(10, 8), "o_ta"),
        D("k10", "🔑 KR • ReReadmeadme - TA", d(10, 9), d(10, 11), "o_ta"),
        D("k11", "🔑 KR • Publish - TA", d(10, 12), d(10, 14), "o_ta"),
    ]
    # the rest of the year: 16 + 6 + 7 + 1 KRs, two days each, laid end to end
    day = d(10, 15)
    for oid, code, n in (("o_kc", "Shortcuts", 16), ("o_au", "Audit", 6),
                         ("o_wf", "WF", 7), ("o_ot2", "OT", 1)):
        o = next(r for r in rows if r["id"] == oid)
        s0, e0 = okr.span(o)
        day = s0
        for i in range(n):
            e = min(day + timedelta(days=1), e0)
            rows.append(D(f"{oid}_{i}", f"🔑 KR • {oid} step {i} - {code}", day, e, oid))
            day = min(e + timedelta(days=1), e0)
    return okr.items_from(rows)


ITEMS = live_plan()
BY = okr.index(ITEMS)
P_DAY = pm.period_for("daily", TODAY)


def flat(lines):
    return [mdtext.flatten_links(ln) for ln in lines]


# ── 1. labels: a period's name, true after it is over ────────────────────────
labels = {k: on.tier_label(k, pm.period_for(k, TODAY)) for k in pm.KINDS}
check("1.labels", labels == {"yearly": "🎉 2026", "quarterly": "🌓 Q3",
                             "monthly": "🗓️ Sep", "weekly": "♻️ W38",
                             "daily": "☀️ Sat 19"}, labels)
check("1.never-today", "Today" not in on.tier_label("daily", P_DAY))
check("1.week-two-digits",
      on.tier_label("weekly", pm.period_for("weekly", d(1, 5))) == "♻️ W02")
check("1.tiers-down", on.tiers_down_to("daily") == on.TIERS
      and on.tiers_down_to("yearly") == ("yearly",)
      and on.tiers_down_to("monthly") == ("yearly", "quarterly", "monthly"))

# ── 2. the fixture reads like the live list ──────────────────────────────────
check("2.fixture-41-krs", sum(1 for i in ITEMS if i.kind == "KR") == 41)
check("2.fixture-6-os", sum(1 for i in ITEMS if i.kind == "O") == 6)

# ── 3. the approved mock, daily 2026-09-19 ───────────────────────────────────
GOALS = {
    "yearly": ["\t- [ ] [💼 P • Productivity System 🔗](https://ticktick.com/webapp/#p/"
               f"{CTA}/tasks/6a46057d8f083bb8ddf4bea1)"],
    "quarterly": [],
    "monthly": [f"\t- [ ] [💼 P • TickAL • WF 🔗](https://ticktick.com/webapp/#p/{CTA}"
                "/tasks/6aa31448522fd18314a75e98)"],
    # the app escapes a line edited there (the live W38 note has one)
    "weekly": ["\t" + r"- [ ] \[💼 P • Onboard TickTick 🔗\]\(https://ticktick.com/webapp/"
               f"#p/{CTA}/tasks/6aa5b80c355d7a6c949ea48a\\)"],
    "daily": [f"\t- [ ] [💼 P • Onboard TickTick 🔗](https://ticktick.com/webapp/#p/{CTA}"
              "/tasks/6aad98528f0859df697a4978)"],
}
lines = on.okr_section_lines("daily", P_DAY, ITEMS, GOALS, TODAY, LIST)
B = "\u2022"
YEAR_OS = ["\t- 🥅 Onboard TickTicks 0/5 🔴 1d", "\t- 🥅 TickAL 0/6",
           "\t- 🥅 KeyCue/MIAs/Shared actions 0/16",
           "\t- 🥅 Audits • Execute & Establish (Naming Conventions) 0/6",
           "\t- 🥅 Workflows 0/7", "\t- 🥅 Other things 0/1"]
# Vex 2026-09-19: "too crammed ... Make them like I did W38 ... indented
# bullet points below that periods bullet point" - his hand edit, every tier
want = (
    [f"- 🎉 2026 {B} 0/41 KRs {B} 🔴 1d"] + YEAR_OS + ["\t- 🎯 Productivity System"]
    + [f"- 🌓 Q3 {B} 0/7 KRs {B} 🔴 1d", "\t- 🥅 Onboard TickTicks 0/5 🔴 1d",
       "\t- 🥅 TickAL 0/6", "\t- 🎯 none"]
    + [f"- 🗓️ Sep {B} 0/7 KRs {B} 🔴 1d", "\t- 🥅 Onboard TickTicks 0/5 🔴 1d",
       "\t- 🥅 TickAL 0/6", "\t- 🎯 TickAL • WF"]
    + [f"- ♻️ W38 {B} 0/2 KRs {B} 🔴 1d", "\t- 🔑 Finish periodic notes 🔴 1d",
       "\t- 🔑 Goals wf", "\t- 🎯 Onboard TickTick"]
    + [f"- ☀️ Sat 19 {B} 0/1 KRs", "\t- 🔑 Goals wf", "\t- 🎯 Onboard TickTick"])
check("3.mock", flat(lines) == want, "\n" + "\n".join(flat(lines)))
check("3.never-the-middle-dot", not any("\u00b7" in ln for ln in lines), lines)
check("3.plan-names-link-the-planning-copy",
      any(f"[Goals wf]({okr.task_link(LIST, 'k2')})" in ln for ln in lines)
      and any(f"[TickAL]({okr.task_link(LIST, 'o_ta')})" in ln for ln in lines), lines)
check("3.goal-links-the-original",
      lines[-1] == f"\t- 🎯 [Onboard TickTick](https://ticktick.com/webapp/#p/{CTA}/tasks/"
      "6aad98528f0859df697a4978)", lines[-1])
check("3.escaped-goal-still-links",
      any("tasks/6aa5b80c355d7a6c949ea48a)" in ln for ln in lines), lines)
check("3.stale-stored-span-read-wanted",
      # TickAL is STORED 29 Sep - 14 Oct but its Goals wf KR starts 19 Sep:
      # the quarter sees it (okr.overlapping, wanted span)
      "\t- 🥅 TickAL 0/6" in flat(lines)[9:13])


def blocks(ls):
    """[[a period's bullet + its children], ...]"""
    out = []
    for ln in ls:
        if ln.startswith("- "):
            out.append([ln])
        else:
            out[-1].append(ln)
    return out


for kind, n in (("weekly", 4), ("monthly", 3), ("quarterly", 2), ("yearly", 1)):
    got = on.okr_section_lines(kind, pm.period_for(kind, TODAY), ITEMS, GOALS,
                               TODAY, LIST)
    check(f"3.{kind}-has-{n}-periods", blocks(got) == blocks(lines)[:n], flat(got))
check("3.no-goals-dict", flat(on.okr_section_lines(
    "quarterly", pm.period_for("quarterly", TODAY), ITEMS, None, TODAY, LIST))[-1]
    == "\t- 🎯 none")
check("3.goals-shown-below-have-no-line", flat(on.okr_section_lines(
    "quarterly", pm.period_for("quarterly", TODAY), ITEMS,
    {"yearly": None, "quarterly": None}, TODAY, LIST))
    == [f"- 🎉 2026 {B} 0/41 KRs {B} 🔴 1d"] + YEAR_OS
    + [f"- 🌓 Q3 {B} 0/7 KRs {B} 🔴 1d", "\t- 🥅 Onboard TickTicks 0/5 🔴 1d",
       "\t- 🥅 TickAL 0/6"])

# ── 4. every rule the mock does not show ─────────────────────────────────────
Y = [D("y1", "🏔️ Y • Productivity System"), D("y2", "🏔️ Y • Health"),
     D("y3", "🏔️ Y • Money"), D("y4", "🏔️ Y • Learning"),
     D("o1", "🥅 O • TickAL", parent="y1"), D("o2", "🥅 O • Gym", parent="y2"),
     D("o3", "🥅 O • Budget", parent="y3"), D("o4", "🥅 O • Books", parent="y4"),
     D("r1", "🔑 KR • Ship - TA", d(9, 1), d(9, 5), "o1", status=2),
     D("r2", "🔑 KR • Docs - TA", d(9, 10), d(9, 17), "o1"),
     D("r3", "🔑 KR • Squat - GY", d(9, 19), d(9, 19), "o2"),
     D("r4", "🔑 KR • Plan - BU", d(9, 14), d(9, 20), "o3"),
     D("r5", "🔑 KR • Read - BK", d(9, 16), d(9, 16), "o4", status=2),
     D("r6", "🔑 KR • Dropped - BK", d(9, 16), d(9, 18), "o4", status=-1),
     D("r7", "🔑 KR • Later - BK", d(9, 18), d(9, 18), "o4"),
     D("r8", "🔑 KR • Undated - BK", parent="o4"),
     D("r9", "🔑 KR • Extra - BK", d(9, 19), d(9, 20), "o4")]
YI = okr.items_from(Y)
yl = blocks(flat(on.okr_section_lines("daily", P_DAY, YI, {}, TODAY, LIST)))
check("4.year-lists-the-ys-with-their-pace", yl[0] == [
    f"- 🎉 2026 {B} 2/7 KRs {B} 🔴 2d",
    "\t- 🏔️ Productivity System 1/2 🔴 2d", "\t- 🏔️ Money 0/1",
    "\t- 🏔️ Learning 1/4 🔴 1d", "\t- 🏔️ Health 0/1", "\t- 🎯 none"], yl[0])
check("4.won't-do-counts-nowhere", "\t- 🏔️ Learning 1/4 🔴 1d" in yl[0], yl[0])
check("4.quarter-os-in-plan-order", yl[1] == [
    f"- 🌓 Q3 {B} 2/7 KRs {B} 🔴 2d", "\t- 🥅 TickAL 1/2 🔴 2d", "\t- 🥅 Budget 0/1",
    "\t- 🥅 Books 1/4 🔴 1d", "\t- 🥅 Gym 0/1", "\t- 🎯 none"], yl[1])
check("4.cap-folds-the-rest", on._capped(list("abcdefghij"), 8)
      == list("abcdefgh") + ["+2 more"])
check("4.week-done-and-late", yl[3] == [
    f"- ♻️ W38 {B} 1/6 KRs {B} 🔴 2d", "\t- 🔑 Docs 🔴 2d", "\t- 🔑 Plan",
    "\t- ✅ Read", "\t- 🔑 Later 🔴 1d", "\t- 🔑 Extra", "\t- 🔑 Squat",
    "\t- 🎯 none"], yl[3])
check("4.dropped-kr-not-in-the-week", not any("Dropped" in x for x in yl[3]), yl[3])
check("4.undated-kr-in-no-period",
      not any("Undated" in x for blk in yl for x in blk), yl)
check("4.day", yl[4] == [f"- ☀️ Sat 19 {B} 0/3 KRs", "\t- 🔑 Plan", "\t- 🔑 Extra",
                         "\t- 🔑 Squat", "\t- 🎯 none"], yl[4])
empty = blocks(flat(on.okr_section_lines("daily", pm.period_for("daily", d(3, 3)),
                                         ITEMS, {}, TODAY, LIST)))
check("4.no-plan", all(blk[0].endswith(f"{B} no plan") and blk[1:] == ["\t- 🎯 none"]
                       for blk in empty[1:]), empty)
check("4.year-no-y", blocks(flat(on.okr_section_lines(
    "yearly", pm.period_for("yearly", TODAY), ITEMS, {}, TODAY, LIST)))[0]
    == [f"- 🎉 2026 {B} 0/41 KRs {B} 🔴 1d"] + YEAR_OS + ["\t- 🎯 none"])
# a month with only KRs (no O overlaps) still counts them on its bullet
lone = okr.items_from([D("x1", "🔑 KR • Loose - XX", d(9, 3), d(9, 3))])
check("4.month-krs-only", blocks(flat(on.okr_section_lines(
    "monthly", pm.period_for("monthly", TODAY), lone, {}, TODAY, LIST)))[2]
    == [f"- 🗓️ Sep {B} 0/1 KRs {B} 🔴 16d", "\t- 🎯 none"])

# ── 5. goals on the line ─────────────────────────────────────────────────────
U = f"https://ticktick.com/webapp/#p/{CTA}/tasks/6aa31448522fd18314a75e98"
check("5.cta-lead-and-tail-go",
      on.goal_label(f"- [ ] [💼 P • TickAL • WF 🔗]({U})") == f"[TickAL • WF]({U})")
check("5.nested-cta-link", on.goal_label(
    f"- [ ] [💼 P • [TickAL • WF](ticktick:///webapp/#p/{CTA}/tasks) 🔗]({U})")
    == f"[TickAL • WF]({U})")
check("5.text-goal", on.goal_label("\t- [ ] Ship the thing") == "Ship the thing")
check("5.text-and-task",
      on.goal_label(f"- [ ] Ship it · [Task]({U})") == f"[Ship it · Task]({U})")
check("5.done-goal-still-shows", on.goal_label(f"- [x] [Read]({U})") == f"[Read]({U})")
for junk in ("\t- _(mirrors this week's weekly note - edit goals there)_",
             "\t- _(pick one - ☀️ in search, or the morning journal asks)_",
             r"- \_\(pending\)\_", "- [ ]", "", "_(pending)_"):
    check(f"5.not-a-goal[{junk!r}]", on.goal_label(junk) == "")
check("5.none", on.goal_lines([]) == ["🎯 none"])
check("5.shown-below-no-line", on.goal_lines(None) == [])
check("5.one-per-line-deduped", on.goal_lines(["- [ ] A", "- [ ] B", "- [ ] A"])
      == ["🎯 A", "🎯 B"])

# ── 6. goal_choices: what the 🔮 rows offer (the pickers import this) ────────
def names(xs):
    return [x.name for x in xs]


wk = pm.period_for("weekly", TODAY)
check("6.daily-krs-open", names(on.goal_choices("daily", TODAY, TODAY, YI, TODAY))
      == ["Plan", "Extra", "Squat"])
check("6.weekly-krs-no-done-no-dropped",
      names(on.goal_choices("weekly", wk.start, wk.end, YI, TODAY))
      == ["Docs", "Plan", "Later", "Extra", "Squat"])
mo = pm.period_for("monthly", TODAY)
check("6.monthly-os-then-krs",
      [x.kind for x in on.goal_choices("monthly", mo.start, mo.end, YI)]
      == ["O"] * 4 + ["KR"] * 5)
q = pm.period_for("quarterly", TODAY)
check("6.quarterly-os", {x.kind for x in on.goal_choices("quarterly", q.start, q.end, YI)}
      == {"O"})
yr = pm.period_for("yearly", TODAY)
yc = on.goal_choices("yearly", yr.start, yr.end, YI)
check("6.yearly-ys-then-os", [x.kind for x in yc] == ["Y"] * 4 + ["O"] * 4,
      [x.kind for x in yc])
check("6.returns-items", all(isinstance(x, okr.Item) for x in yc))
check("6.live-daily", names(on.goal_choices("daily", TODAY, TODAY, ITEMS, TODAY))
      == ["Goals wf"])
check("6.same-plan-as-the-note", names(on.plan_for("weekly", wk.start, wk.end, ITEMS))
      == ["Finish periodic notes", "Goals wf"])

# ── 7. the scorecard ─────────────────────────────────────────────────────────
check("7.bar", [on.bar(*x) for x in ((0, 5), (1, 5), (4, 5), (5, 5), (1, 41), (40, 41), (0, 0))]
      == ["▱▱▱▱▱", "▰▱▱▱▱", "▰▰▰▰▱", "▰▰▰▰▰", "▰▱▱▱▱", "▰▰▰▰▱", "▱▱▱▱▱"])
sc = flat(on.scorecard_lines(yr, YI, TODAY, LIST))
check("7.y-then-its-os", sc[:2] == [
    "- 🏔️ Productivity System ▰▰▰▱▱ 1/2 • Sep 1 - Sep 17 • 🔴 2d",
    "\t- 🥅 TickAL 1/2 • Sep 1 - Sep 17"], sc)
check("7.no-behind-when-on-pace", "- 🏔️ Health ▱▱▱▱▱ 0/1 • Sep 19" in sc, sc)
check("7.y-count", sum(1 for s in sc if s.startswith("- 🏔️")) == 4, sc)
sl = flat(on.scorecard_lines(yr, ITEMS, TODAY, LIST))
check("7.no-y-os-on-top", len(sl) == 6 and sl[0]
      == "- 🥅 Onboard TickTicks ▱▱▱▱▱ 0/5 • Sep 18 - Sep 28 • 🔴 1d", sl)
check("7.wanted-span", "- 🥅 TickAL ▱▱▱▱▱ 0/6 • Sep 19 - Oct 14" in sl, sl)
check("7.every-line-is-a-plan-line",
      all(pm.is_plan_line(x) for x in on.scorecard_lines(yr, YI, TODAY, LIST)
          + on.scorecard_lines(yr, ITEMS, TODAY, LIST)))
check("7.empty-year", on.scorecard_lines(pm.period_for("yearly", d(1, 1, 2030)),
                                         ITEMS, TODAY, LIST) == [])
GOAL = f"\t- [ ] [💼 P • Productivity System 🔗]({U})"
plan = on.scorecard_lines(yr, ITEMS, TODAY, LIST)
m1 = on.merge_scorecard([GOAL], plan)
check("7.merge-keeps-the-goal-after-the-plan",
      m1 == plan + [GOAL.lstrip("\t")], m1)
check("7.merge-idempotent", on.merge_scorecard(m1, plan) == m1)
check("7.merge-replaces-old-plan", on.merge_scorecard(
    ["- 🥅 [Gone](x) ▱▱▱▱▱ 0/3 • Jan 1"] + m1, plan) == m1)
check("7.merge-eats-pending", on.merge_scorecard(["_(pending)_"], plan) == plan)
check("7.merge-nothing-left-pending", on.merge_scorecard(plan, []) == ["_(pending)_"])
check("7.merge-no-plan-keeps-goal", on.merge_scorecard([GOAL], []) == [GOAL])
check("7.merge-keeps-hand-text", "Vex wrote this" in on.merge_scorecard(
    ["Vex wrote this"] + plan, plan)[-1])

# ── 8. the goal readers never mistake the plan for a goal ────────────────────
check("8.goal-titles-skip-plan", pm.goal_titles(m1) == ["💼 P • Productivity System 🔗"],
      pm.goal_titles(m1))
check("8.checkbox-goal-with-glyph-is-a-goal",
      pm.goal_titles(["- [ ] 🥅 Win 1/2 races"]) == ["🥅 Win 1/2 races"])
check("8.plain-bullet-without-count-is-a-goal",
      pm.goal_titles(["- 🥅 Get fit"]) == ["🥅 Get fit"])
check("8.escaped-plan-line", pm.is_plan_line(r"- 🏔️ \[Y\]\(u\) ▰▱▱▱▱ 1/5 · Jan 1"))

# ── 9. templates: the section where Vex picked it ────────────────────────────
for kind in pm.KINDS:
    tpl = open(os.path.join(ROOT, "src", "periodic_templates", f"{kind}.md"),
               encoding="utf-8").read()
    doc = ps.parse_sections(tpl)
    names_ = [s.name for s in doc.sections]
    sec = ps.find(doc, pm.SEC_OKR)
    check(f"9.{kind}-has-section", isinstance(sec, ps.Section), names_)
    if not isinstance(sec, ps.Section):
        continue
    i = names_.index(pm.SEC_OKR)
    nxt = names_[i + 1] if i + 1 < len(names_) else None
    hashes = "#####" if kind == "yearly" else "####"
    check(f"9.{kind}-header", sec.header == f"{hashes} {pm.SEC_OKR}", sec.header)
    check(f"9.{kind}-body", sec.body == ["- _(pending)_"], sec.body)
    check(f"9.{kind}-divider-after", doc.sections[i + 1].pre == ["---"])
    if kind == "yearly":
        check("9.yearly-first-above-dashboard",
              i == 0 and nxt == pm.SEC_DASHBOARD and doc.lead[-1] == "---", names_)
    else:
        check(f"9.{kind}-above-goals", nxt == pm.SEC_GOALS, names_)
    if kind == "daily":
        check("9.daily-after-bridge-and-highlight",
              names_[:3] == [pm.SEC_YBRIDGE, pm.SEC_HIGHLIGHT, pm.SEC_OKR], names_)

# ── 10. the engine hook on an in-memory note ─────────────────────────────────
def note(kind, p, goals=None, strip=False):
    """A rendered template for p, goals appended the way the setter writes
    them; strip=True drops the 🥅 OKRs block (a note minted before today)."""
    # the REPO template, never ~/.ticktick_alfred's override (_load_template
    # would prefer one): this suite tests what ships
    tpl = open(os.path.join(ROOT, "src", "periodic_templates", f"{kind}.md"),
               encoding="utf-8").read()
    doc = ps.parse_sections(pm.render_template(tpl, {"breadcrumbs": "C"}))
    if strip:
        i = next(j for j, s in enumerate(doc.sections) if s.name == pm.SEC_OKR)
        doc.sections[i + 1].pre = doc.sections[i].pre
        del doc.sections[i]
    for ln in goals or []:
        if kind == "daily":
            ps.set_body(doc, pm.SEC_DAY_GOAL, [ln])
        elif kind == "weekly":
            pe._goal_append(doc, pe._week_goal_home(doc), ln)
        else:
            nm = next(n for n in pm.goal_section_names(kind) if ps.find(doc, n))
            pe._goal_append(doc, nm, ln)
    return {"id": f"n_{kind}", "projectId": "PN", "content": ps.serialize_sections(doc)}


def index_for(day, goals, skip=()):
    idx = {}
    for kind in pm.KINDS:
        if kind in skip:
            continue
        p = pm.period_for(kind, day)
        idx[(kind, pm.title_key(p))] = note(kind, p, goals.get(kind))
    return idx


_real_today, _real_plan = pe._today, pe._okr_plan
pe._today = lambda: TODAY
pe._okr_plan = lambda: (LIST, ITEMS)
IDX = index_for(TODAY, GOALS)

ddoc = ps.parse_sections(IDX[("daily", TODAY.isoformat())]["content"])
pe._fill_okr(ddoc, P_DAY, IDX)
# the daily note carries 🗓️ Weekly and ☀️ Daily in its 🏆 Goals: those two
# tiers get no 🎯 line ("Remove 🎯 items if we have them in a header below")
want_daily = [x for x in want if x not in ("\t- 🎯 Onboard TickTick",)]
check("10.daily-filled-from-the-tier-notes",
      flat(ps.find(ddoc, pm.SEC_OKR).body) == want_daily, flat(ps.find(ddoc, pm.SEC_OKR).body))
check("10.roundtrip", ps.serialize_sections(ps.parse_sections(ps.serialize_sections(ddoc)))
      == ps.serialize_sections(ddoc))
before = ps.serialize_sections(ddoc)
pe._fill_okr(ddoc, P_DAY, IDX)
check("10.idempotent", ps.serialize_sections(ddoc) == before)
text = ps.serialize_sections(ddoc)
check("10.divider-kept", f"#### {pm.SEC_OKR}\n- 🎉 2026" in text
      and "\n---\n#### 🏆 Goals" in text, text[:600])

# a goal bullet Vex deleted brings its tier's 🎯 line back (the weekly
# mirror gone from the daily note -> W38 shows the week's goal again)
gdoc = ps.parse_sections(IDX[("daily", TODAY.isoformat())]["content"])
gdoc_w = ps.find(gdoc, pm.SEC_WEEK_GOALS)
gsec = ps.find(gdoc, pm.SEC_GOALS)
gsec.body = [ln for ln in gsec.body
             if not ln.strip().startswith("- " + pm.SEC_WEEK_GOALS)
             and "mirrors this week" not in ln]
check("10.fixture-mirror-gone", ps.find(gdoc, pm.SEC_WEEK_GOALS) is None
      or ps.find(gdoc, pm.SEC_WEEK_GOALS).name != pm.SEC_WEEK_GOALS)
pe._fill_okr(gdoc, P_DAY, IDX)
wk = blocks(flat(ps.find(gdoc, pm.SEC_OKR).body))[3]
check("10.deleted-mirror-brings-the-goal-back", wk[-1] == "\t- 🎯 Onboard TickTick", wk)

# a missing tier note reads 🎯 none; the line is still there
idx2 = index_for(TODAY, GOALS, skip=("quarterly",))
wdoc = ps.parse_sections(idx2[("weekly", "2026-W38")]["content"])
pe._fill_okr(wdoc, pm.period_for("weekly", TODAY), idx2)
wl = blocks(flat(ps.find(wdoc, pm.SEC_OKR).body))
check("10.weekly-four-periods", len(wl) == 4 and wl[3][0].startswith("- ♻️ W38"), wl)
check("10.weekly-shows-the-year-goal-only",
      wl[0][-1] == "\t- 🎯 Productivity System"
      and not any(x.startswith("\t- 🎯") for blk in wl[1:] for x in blk), wl)

# kill switch: the section deleted -> nothing written anywhere
kdoc = ps.parse_sections(note("daily", P_DAY, strip=True)["content"])
kb = ps.serialize_sections(kdoc)
pe._fill_okr(kdoc, P_DAY, IDX)
check("10.kill-switch", ps.serialize_sections(kdoc) == kb)

# OKRs off, or nothing cached -> the section stays as it is
for label, plan_ in (("off", ("", [])), ("no-plan", (LIST, []))):
    pe._okr_plan = lambda plan_=plan_: plan_
    odoc = ps.parse_sections(IDX[("daily", TODAY.isoformat())]["content"])
    ob = ps.serialize_sections(odoc)
    pe._fill_okr(odoc, P_DAY, IDX)
    check(f"10.{label}-untouched", ps.serialize_sections(odoc) == ob)
pe._okr_plan = lambda: (LIST, ITEMS)

# the yearly note: section + scorecard, and the yearly goal survives both
ydoc = ps.parse_sections(IDX[("yearly", "2026")]["content"])
pe._fill_okr(ydoc, yr, IDX)
card = ps.find(ydoc, pm.SEC_SCORECARD)
check("10.scorecard-plan-then-goal",
      flat(card.body)[:6] == sl and card.body[6] == GOALS["yearly"][0].lstrip("\t"),
      card.body)
check("10.scorecard-gap-kept", card.body[-1] == "", card.body)
check("10.yearly-goal-reader-sees-only-the-goal",
      pe._okr_goal_lines(ydoc, "yearly") == [GOALS["yearly"][0].lstrip("\t")],
      pe._okr_goal_lines(ydoc, "yearly"))
check("10.year-block-plan-only-its-goal-is-in-the-scorecard-below",
      flat(ps.find(ydoc, pm.SEC_OKR).body)
      == [f"- 🎉 2026 {B} 0/41 KRs {B} 🔴 1d"] + YEAR_OS,
      flat(ps.find(ydoc, pm.SEC_OKR).body))
yb = ps.serialize_sections(ydoc)
pe._fill_okr(ydoc, yr, IDX)
check("10.yearly-idempotent", ps.serialize_sections(ydoc) == yb)
# a yearly goal set AFTER the scorecard was filled lands after it and stays
pe._goal_append(ydoc, pm.SEC_SCORECARD, "\t- [ ] Second goal")
pe._fill_okr(ydoc, yr, IDX)
check("10.new-yearly-goal-kept",
      pe._okr_goal_lines(ydoc, "yearly")[-1] == "- [ ] Second goal"
      and len(pe._okr_goal_lines(ydoc, "yearly")) == 2,
      ps.find(ydoc, pm.SEC_SCORECARD).body)
# the quarterly note's 🎉 Yearly goal mirror copies the goals, never the plan
qidx = dict(IDX)
qidx[("yearly", "2026")] = {"id": "y", "content": ps.serialize_sections(ydoc)}
qdoc = ps.parse_sections(IDX[("quarterly", "2026-Q3")]["content"])
pe._mirror_goal(qdoc, pm.SEC_QTR_YEAR, "yearly", qidx, TODAY, "- _(x)_")
mir = ps.find(qdoc, pm.SEC_QTR_YEAR, pm.SEC_GOALS).body
check("10.quarterly-mirror-no-plan-lines",
      not any(pm.is_plan_line(x) for x in mir) and len(mir) == 2, mir)

# ── 10b. the Workbench is the agenda: OKR copies stay out (Vex 2026-09-19) ──
_real_get = pe.cache_store.get
_env = os.environ.get("okr_list_id")
try:
    os.environ["okr_list_id"] = "okrplan00000000000000000"
    day_iso = TODAY.isoformat()
    rows = [{"id": "real1", "projectId": "work0000000000000000000", "title": "Real work",
             "startDate": f"{day_iso}T08:00:00+0000", "isAllDay": False, "status": 0},
            {"id": "kr1", "projectId": "okrplan00000000000000000", "title": "🔑 KR • Plan - TA",
             "startDate": f"{day_iso}T00:00:00+0000", "isAllDay": True, "status": 0}]
    pe.cache_store.get = lambda k: rows if k == "all_tasks" else _real_get(k)
    got = [r[1] for r in pe._scheduled_today(TODAY)]
    check("10b.workbench-skips-okr-copies", got == ["real1"], got)
    os.environ["okr_list_id"] = ""
    got = [r[1] for r in pe._scheduled_today(TODAY)]
    check("10b.okrs-off-the-list-is-just-a-list", sorted(got) == ["kr1", "real1"], got)
    body = ["\t- [ ] [🔑 KR • Plan - TA](https://ticktick.com/webapp/#p/okrplan00000000000000000/tasks/aaaaaaaaaaaaaaaaaaaaaaa1) ",
            "\t- [x] [🔑 KR • Done - TA](https://ticktick.com/webapp/#p/okrplan00000000000000000/tasks/aaaaaaaaaaaaaaaaaaaaaaa2) ",
            "\t- [ ] [Real work](https://ticktick.com/webapp/#p/work0000000000000000000/tasks/bbbbbbbbbbbbbbbbbbbbbbb1) "]
    kept = pm.drop_checkbox_lines(body, (), {"okrplan00000000000000000"})
    check("10b.old-copy-lines-leave-ticked-ones-stay", kept == body[1:], kept)
finally:
    pe.cache_store.get = _real_get
    if _env is None:
        os.environ.pop("okr_list_id", None)
    else:
        os.environ["okr_list_id"] = _env

# ── 11. refresh_period: LIVE window only, for every tier ─────────────────────
pe._log = lambda msg: None      # never the real /tmp/tickal_periodic.log
STORE = {}


def fake_rmw(pid, tid, mutate):
    doc = ps.parse_sections(STORE[tid])
    res = mutate(doc, {"id": tid, "content": STORE[tid]})
    STORE[tid] = ps.serialize_sections(doc)
    return res, doc


saved = {n: getattr(pe, n) for n in (
    "_pn_rmw", "_fill_daily", "_fill_weekly", "_fill_monthly", "_fill_quarterly",
    "_fill_rollup_money", "_compose_lead", "_swept_load", "_sweep_due")}
pe._pn_rmw = fake_rmw
for n in ("_fill_daily", "_fill_weekly", "_fill_monthly", "_fill_quarterly",
          "_fill_rollup_money", "_compose_lead"):
    setattr(pe, n, lambda *a, **k: None)
pe._swept_load = lambda: {}
pe._sweep_due = lambda pairs, line_day: ([], [])
try:
    for kind in pm.KINDS:
        p = pm.period_for(kind, TODAY)
        t = IDX[(kind, pm.title_key(p))]
        STORE[t["id"]] = t["content"]
        pe.refresh_period(p, IDX)
        body = ps.find(ps.parse_sections(STORE[t["id"]]), pm.SEC_OKR).body
        check(f"11.refresh-fills-{kind}", body and body[0].startswith("- 🎉 2026 \u2022 "), body)
    # the grace day: yesterday's daily still gets its closing pass
    yp = pm.period_for("daily", TODAY - timedelta(days=1))
    yt = note("daily", yp)
    yt["id"] = "n_yday"
    STORE["n_yday"] = yt["content"]
    idx3 = dict(IDX)
    idx3[("daily", yp.start.isoformat())] = yt
    pe.refresh_period(yp, idx3)
    check("11.grace-day-fills", any(ln.startswith("- ☀️ Fri 18") for ln in ps.find(
        ps.parse_sections(STORE["n_yday"]), pm.SEC_OKR).body))
    # a SEALED note keeps the plan it had
    sp = pm.period_for("daily", TODAY - timedelta(days=3))
    st = note("daily", sp)
    st["id"] = "n_sealed"
    STORE["n_sealed"] = st["content"]
    idx3[("daily", sp.start.isoformat())] = st
    pe.refresh_period(sp, idx3)
    check("11.sealed-untouched", ps.find(ps.parse_sections(STORE["n_sealed"]),
                                         pm.SEC_OKR).body == ["- _(pending)_"])
    # the kill switch: 🥅 OKRs deleted + an unrelated "- OKRs" bullet of
    # Vex's under 📓 Notes = nothing written (ps.find's normalized pass
    # would hand that bullet back - review 2026-09-19)
    kp = pm.period_for("daily", TODAY)
    kt = IDX[("daily", TODAY.isoformat())]
    kdoc = ps.parse_sections(kt["content"])
    kdoc.sections = [s for s in kdoc.sections if s.name != pm.SEC_OKR]
    nsec = ps.find(kdoc, pm.SEC_NOTES)
    if nsec is not None:
        ps.set_sec_body(kdoc, nsec, list(nsec.body) + ["\t- OKRs", "\t\t- review them on Sunday"])
    before = ps.serialize_sections(kdoc)
    STORE[kt["id"]] = before
    pe.refresh_period(kp, IDX)
    check("11.kill-switch-exact: a deleted section + a '- OKRs' bullet elsewhere = untouched",
          nsec is None or STORE[kt["id"]] == before,
          [l for l in STORE[kt["id"]].splitlines() if "🎉" in l or "Sunday" in l])
    # an OKR failure never costs the rest of the refresh
    pe._okr_plan = lambda: (_ for _ in ()).throw(RuntimeError("cache torn"))
    STORE[IDX[("daily", TODAY.isoformat())]["id"]] = IDX[("daily", TODAY.isoformat())]["content"]
    res = pe.refresh_period(P_DAY, IDX)
    check("11.okr-failure-is-contained", res.startswith("refreshed"), res)
finally:
    for n, f in saved.items():
        setattr(pe, n, f)
    pe._today, pe._okr_plan = _real_today, _real_plan

# ── 12. the plan read: cache only, OKRs off = nothing ────────────────────────
import config  # noqa: E402
import okr_write  # noqa: E402
_env = os.environ.get("okr_list_id")
_cp = okr_write.cached_plan
calls = []
okr_write.cached_plan = lambda lid: calls.append(lid) or ITEMS
try:
    os.environ["okr_list_id"] = ""
    pe._OKR_PLAN[:] = [0.0, None, []]
    check("12.off", pe._okr_plan() == ("", []) and not calls)
    os.environ["okr_list_id"] = LIST
    check("12.cached", pe._okr_plan() == (LIST, ITEMS) and calls == [LIST])
    pe._okr_plan()
    check("12.held-for-the-run", calls == [LIST], calls)
finally:
    okr_write.cached_plan = _cp
    pe._OKR_PLAN[:] = [0.0, None, []]
    if _env is None:
        os.environ.pop("okr_list_id", None)
    else:
        os.environ["okr_list_id"] = _env

print(f"okr notes: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
