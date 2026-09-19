#!/usr/bin/env python3
"""What the real work gave the plan (HANDOFF_OKR phase 5): src/okr_stats.py
(the aligned join, focus per objective), periodic_fetch.focus_records (the
paged timeline) and the weekly note's 🥅 Aligned line
(periodic_engine._fill_aligned).

No network: the plan and the rows are handed in, the timeline is a fake
_v2_get, the note is the shipped weekly template parsed in memory.

    python3 tests/test_okr_stats.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import okr  # noqa: E402
import okr_stats as st  # noqa: E402
import periodic_engine as pe  # noqa: E402
import periodic_fetch as pf  # noqa: E402
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


PLAN = "a" * 24                 # the OKR list
PROJ = "b" * 24                 # a 💼 project list (the O links its CTA)
CTAL = "c" * 24                 # the 📌CTA list
REAL = "d" * 24                 # a list where one linked task lives
SIDE = "e" * 24                 # a list a KR links whole
OTHER = "f" * 24                # unrelated work
CTA_T, REAL_T, SUB1, SUB2 = "1" * 24, "2" * 24, "3" * 24, "4" * 24
SERIES = "5" * 24


def P(tid, title, parent=None, status=0):
    return {"id": tid, "projectId": PLAN, "title": title, "parentId": parent,
            "status": status, "startDate": None, "dueDate": None, "isAllDay": True}


def task_url(pid, tid):
    return f"https://ticktick.com/webapp/#p/{pid}/tasks/{tid}"


def list_url(pid):
    return f"ticktick:///webapp/#p/{pid}/tasks"


ITEMS = okr.items_from([
    P("Y1", "🏔️ Y • Productivity System"),
    P("O1", f"🥅 O • [TickAL]({task_url(CTAL, CTA_T)})", "Y1"),
    P("K1", f"🔑 KR • [Goals wf]({task_url(REAL, REAL_T)}) - TA", "O1"),
    P("K2", f"🔑 KR • [Side]({list_url(SIDE)}) - TA", "O1"),
    P("K3", "🔑 KR • Unlinked - TA", "O1"),
    P("O2", "🥅 O • Workflows"),
    P("K4", f"🔑 KR • [Series]({task_url(OTHER, SERIES)})", "O2"),
    P("K5", f"🔑 KR • [Dropped]({task_url(OTHER, 'dead' * 6)})", "O2", status=-1),
    P("KX", f"🔑 KR • [Lonely]({task_url(OTHER, '9' * 24)})"),
])


def R(tid, pid, title="t", parent=None, status=2, **kw):
    t = {"id": tid, "projectId": pid, "title": title, "parentId": parent, "status": status}
    t.update(kw)
    return t


ROWS = [
    R(CTA_T, CTAL, f"💼 P • [TickAL]({list_url(PROJ)}) 🔗", status=0),
    R(REAL_T, REAL, "Goals workflow", status=0),
    R(SUB1, REAL, "Step one", parent=REAL_T, status=0),
    R(SUB2, REAL, "Step one a", parent=SUB1),
]

# ── 1. the join ──────────────────────────────────────────────────────────────
al = st.Aligned(ITEMS, ROWS, PLAN)
check("1.any", al.any())
check("1.owner: a KR's link credits its O",
      al.owner(R(REAL_T, REAL)) == "O1", al.owner(R(REAL_T, REAL)))
check("1.owner: a subtask two levels under a linked original",
      al.owner(R(SUB2, REAL, parent=SUB1)) == "O1")
check("1.owner: any task in a list a KR links whole",
      al.owner(R("x" * 24, SIDE)) == "O1")
check("1.owner: the O's CTA task itself (focus lands there)",
      al.owner(R(CTA_T, CTAL)) == "O1")
check("1.owner: any task in the project list the CTA's title links",
      al.owner(R("y" * 24, PROJ)) == "O1")
check("1.owner: a completed COPY of a linked repeating task (repeatTaskId)",
      al.owner(R("z" * 24, OTHER, repeatTaskId=SERIES)) == "O2")
check("1.owner: a won't-do KR's link aligns nothing",
      al.owner(R("dead" * 6, OTHER)) is None)
check("1.owner: a KR under no O owns itself",
      al.owner(R("9" * 24, OTHER)) == "KX")
check("1.owner: unrelated work serves nothing", al.owner(R("q" * 24, OTHER)) is None)
check("1.owner: the plan list's own copies are never work",
      al.owner(R("K1", PLAN, f"🔑 KR • [Goals wf]({task_url(REAL, REAL_T)})")) is None)
check("1.owner: a re-minted CTA (new id, same list link in its title) still counts",
      al.owner(R("w" * 24, CTAL, f"💼 P • [TickAL]({list_url(PROJ)}) 🔗")) == "O1")
check("1.no links = nothing to read (never a 0% that lies)",
      not st.Aligned(okr.items_from([P("O9", "🥅 O • Plain"),
                                     P("K9", "🔑 KR • Plain", "O9")]), ROWS, PLAN).any())
# review 2026-09-19: the old CTA gone from every cache - the kept map answers
al2 = st.Aligned(ITEMS, [r for r in ROWS if r["id"] != CTA_T], PLAN,
                 cta_lists={CTA_T: [PROJ]})
check("1.a CTA gone from the caches still opens its list (the kept CTA map)",
      al2.owner(R("y" * 24, PROJ)) == "O1"
      and al2.owner({"id": "w" * 24}, title=f"💼 P • [TickAL]({list_url(PROJ)}) 🔗") == "O1")
al3 = st.Aligned(ITEMS, [r for r in ROWS if r["id"] != CTA_T], PLAN)
check("1.... and without the map it cannot (why the map is kept)",
      al3.owner(R("y" * 24, PROJ)) is None)
check("1.cta_list_map: CTA rows only, by list or by title shape",
      st.cta_list_map(ROWS + [R("m" * 24, "g" * 24, f"Move notes to [Archive]({list_url(SIDE)})")])
      == {CTA_T: [PROJ]}
      and st.cta_list_map([R("h" * 24, CTAL, f"[x]({list_url(SIDE)})")], CTAL)
      == {"h" * 24: [SIDE]})
NOTCTA = "7" * 24
itn = okr.items_from([P("ON", "🥅 O • Notes"),
                      P("KN", f"🔑 KR • [Move]({task_url(OTHER, NOTCTA)})", "ON")])
aln = st.Aligned(itn, [R(NOTCTA, OTHER, f"Move notes to [Archive]({list_url(SIDE)})", status=0)],
                 PLAN)
check("1.a linked task that is NOT a CTA never hands its title's list to the objective",
      aln.owner(R("x" * 24, SIDE)) is None and aln.owner(R(NOTCTA, OTHER)) == "ON")
itd = okr.items_from([P("OQ2", f"🥅 O • [Old]({list_url(SIDE)})", status=2),
                      P("OQ3", f"🥅 O • [New]({list_url(SIDE)})")])
check("1.two items on one list: the OPEN one gets the work, not last quarter's done one",
      st.Aligned(itd, [], PLAN).owner(R("x" * 24, SIDE)) == "OQ3")
loop = [R("L1", OTHER, parent="L2"), R("L2", OTHER, parent="L1")]
check("1.a parentId loop stops", st.Aligned(ITEMS, loop, PLAN).owner(loop[0]) is None)

done = [R(SUB2, REAL, parent=SUB1), R("x" * 24, SIDE), R("q" * 24, OTHER),
        R("z" * 24, OTHER, repeatTaskId=SERIES)]
served, total, per = st.aligned_counts(done, al)
check("1.counts", (served, total, per) == (3, 4, {"O1": 2, "O2": 1}), (served, total, per))
check("1.pct", (st.pct(3, 4), st.pct(0, 0)) == (75, None))
check("1.pts chip: points, never a relative %",
      (st.pts_chip(68, 61), st.pts_chip(50, 57), st.pts_chip(5, 5), st.pts_chip(5, None),
       st.pts_chip(72, 73))
      == ("🟢 ▲ 7 pts", "🔴 ▼ 7 pts", "⚪ ▬", None, "🔴 ▼ 1 pt"))

# ── 2. focus segments + per owner ────────────────────────────────────────────
one = {"startTime": "2026-09-19T08:00:00.000+0000", "endTime": "2026-09-19T09:00:00.000+0000",
       "pauseDuration": 600, "tasks": [{"taskId": REAL_T, "title": "Goals workflow"}]}
check("2.one task = the record's net minutes (pause in seconds)",
      [(t, round(m)) for t, _ti, m in st.segments(one)] == [(REAL_T, 50)], st.segments(one))
two = {"startTime": "2026-09-19T10:00:00.000+0000", "endTime": "2026-09-19T11:00:00.000+0000",
       "pauseDuration": 0,
       "tasks": [{"taskId": "w" * 24, "title": f"💼 P • [TickAL]({list_url(PROJ)}) 🔗",
                  "startTime": "2026-09-19T10:00:00.000+0000",
                  "endTime": "2026-09-19T10:45:00.000+0000"},
                 {"taskId": "q" * 24, "title": "Other",
                  "startTime": "2026-09-19T10:45:00.000+0000",
                  "endTime": "2026-09-19T11:00:00.000+0000"},
                 {"title": "no id"}]}
segs = st.segments(two)
check("2.several tasks: each its OWN segment, scaled to the net, no-id entries dropped",
      [(t, round(m)) for t, _ti, m in segs] == [("w" * 24, 45), ("q" * 24, 15)], segs)
check("2.focus per owner: by row when cached, else by the segment's title (a CTA re-mint)",
      st.focus_per_owner([one, two], al) == {"O1": 95}, st.focus_per_owner([one, two], al))
check("2.a record with no readable times is skipped", st.segments({"tasks": []}) == [])

# ── 3. focus_records pages back as far as the window needs ───────────────────
def rec(i, ts):
    return {"id": f"r{i}", "startTime": ts, "endTime": ts, "pauseDuration": 0, "tasks": []}


PAGE1 = [rec(i, f"2026-09-{19 - i // 4:02d}T08:00:00.000+0000") for i in range(31)]
PAGE2 = [rec(100 + i, f"2026-09-{11 - i // 8:02d}T08:00:00.000+0000") for i in range(12)]
asked = []


def fake_get(path, params=None):
    asked.append((path, dict(params or {})))
    if path != "pomodoros/timeline":
        return None
    if not params:
        return list(PAGE1)
    return list(PAGE2)


_real_get = pf._v2_get
pf._v2_get = fake_get
pf._TIMELINE = None
pf._TL_MORE[:] = [None, False]
try:
    got = pf.focus_records(date(2026, 9, 14), date(2026, 9, 19))
    check("3.a window page 1 covers: one call", len(asked) == 1 and got is not None
          and all(date(2026, 9, 14) <= pf._rec_local_date(r["startTime"]) <= date(2026, 9, 19)
                  for r in got), asked)
    got = pf.focus_records(date(2026, 9, 7), date(2026, 9, 13))
    check("3.an older window pages back with ?to=<oldest startTime, epoch ms>",
          len(asked) == 2 and "to" in asked[1][1] and got
          and min(pf._rec_local_date(r["startTime"]) for r in got) >= date(2026, 9, 7), asked)
    n = len(asked)
    pf.focus_records(date(2026, 8, 1), date(2026, 8, 31))
    check("3.a short page = the end: no further calls", len(asked) == n, asked[n:])
    # the Focus lines ride the same pages (Vex 2026-09-19: "will it always
    # look at only this week? Fix that")
    pf._TIMELINE = None
    pf._TL_MORE[:] = [None, False]
    WIDE = [dict(r, endTime=r["startTime"][:11] + "08:30:00.000+0000") for r in PAGE1]
    WIDE2 = [dict(r, endTime=r["startTime"][:11] + "08:30:00.000+0000") for r in PAGE2]
    pf._v2_get = lambda path, params=None: list(WIDE2 if params else WIDE)
    old_week = (date(2026, 9, 7), date(2026, 9, 13))
    check("3.an older week's Focus total counts page 2 too (was page 1 only)",
          pf.focus_minutes(*old_week) == 30 * sum(
              1 for r in WIDE + WIDE2
              if old_week[0] <= pf._rec_local_date(r["startTime"]) <= old_week[1]),
          pf.focus_minutes(*old_week))
    check("3.focus_by_day and focus_by_span read the same pages",
          sum(m for m, _t in pf.focus_by_day(*old_week).values())
          == pf.focus_by_span(*old_week)[0] == pf.focus_minutes(*old_week))
    pf._TIMELINE = None
    pf._TL_MORE[:] = [None, False]
    pf._v2_get = lambda path, params=None: None
    check("3.page 1 failing = None (the line is dropped, never a fake zero)",
          pf.focus_records(date(2026, 9, 14), date(2026, 9, 19)) is None)
finally:
    pf._v2_get = _real_get
    pf._TIMELINE = None
    pf._TL_MORE[:] = [None, False]

# ── 4. the weekly 🥅 Aligned line ────────────────────────────────────────────
TODAY = date(2026, 9, 19)
P_WK = pm.period_for("weekly", TODAY)
PREV = pm.prev_period(P_WK)


def week_doc():
    return ps.parse_sections(pe._load_template("weekly").replace("{{breadcrumbs}}", "x")
                             .replace("{{daylinks}}", "y"))


def aligned_line(doc):
    sec = ps.find_prefix(doc, pm.SEC_ALIGNED, pm.scope_of("weekly", pm.SEC_ALIGNED))
    return None if sec is None else (sec.name, sec.body)


class T2:
    def __init__(self, recs):
        self.recs = recs

    def focus_records(self, a, b):
        return self.recs


ROUTINES = __import__("routines").ROUTINES_LIST
cur = [R(SUB2, REAL, parent=SUB1), R("x" * 24, SIDE), R("q" * 24, OTHER),
       R("z" * 24, OTHER, repeatTaskId=SERIES),
       R("r" * 24, ROUTINES, "🌅 Startup"),            # a routine: not work
       R("k" * 24, PLAN, "🔑 KR • ticked copy"),       # the plan: not work
       R("n" * 24, OTHER, status=-1)]                  # won't do: not done work
prev = [R("x" * 24, SIDE), R("q" * 24, OTHER), R("p" * 24, OTHER)]

_real = (pe._okr_plan, pe._okr_rows_known)
pe._okr_plan = lambda: (PLAN, ITEMS)
pe._okr_rows_known = lambda: list(ROWS)
try:
    doc = week_doc()
    lw = pe._fill_aligned(doc, P_WK, TODAY, cur, prev, T2([one, two]),
                          pm.scope_of("weekly", pm.SEC_ALIGNED))
    name, body = aligned_line(doc)
    check("4.header: % • served/work • points chip vs last week (routines, the plan's "
          "copies and won't-do out of the work)",
          name == "🥅 Aligned: 75% • 3/4 • 🟢 ▲ 42 pts", name)
    check("4.body: one line per objective - done count, focus when there is some",
          [ln.strip() for ln in body if ln.strip()]
          == ["- 🥅 TickAL • 2 done • 1h 35m", "- 🥅 Workflows • 1 done"], body)
    check("4.returns last week's line for ⏪ Last week", lw == "- 🥅 Aligned: 33% • 1/3", lw)
    tie = [R("x" * 24, SIDE), R("z" * 24, OTHER, repeatTaskId=SERIES)]
    order = set()
    for _ in range(3):
        dd = week_doc()
        pe._fill_aligned(dd, P_WK, TODAY, tie, None, None, pm.scope_of("weekly", pm.SEC_ALIGNED))
        order.add(tuple(ln.strip() for ln in aligned_line(dd)[1] if ln.strip()))
    check("4.ties come out in plan order, the same every run",
          order == {("- 🥅 TickAL • 1 done", "- 🥅 Workflows • 1 done")}, order)
    check("4.in the shipped template, inside 📊 Stats",
          pm.SEC_ALIGNED in pm.WRITER_ANCHORS["weekly"]
          and pm.scope_of("weekly", pm.SEC_ALIGNED) == pm.SEC_WK_STATS)

    doc = week_doc()
    pe._fill_aligned(doc, P_WK, TODAY, cur, None, None, pm.scope_of("weekly", pm.SEC_ALIGNED))
    name, body = aligned_line(doc)
    check("4.no last week, no focus source: the numbers alone, no chip",
          name == "🥅 Aligned: 75% • 3/4"
          and [ln.strip() for ln in body if ln.strip()]
          == ["- 🥅 TickAL • 2 done", "- 🥅 Workflows • 1 done"], (name, body))

    pe._okr_plan = lambda: (PLAN, okr.items_from([P("O9", "🥅 O • Plain")]))
    doc = week_doc()
    lw = pe._fill_aligned(doc, P_WK, TODAY, cur, prev, None,
                          pm.scope_of("weekly", pm.SEC_ALIGNED))
    check("4.a plan that links nothing says so (a 0% would lie), no last-week line",
          aligned_line(doc)[0] == "🥅 Aligned: no linked OKR items" and lw is None,
          aligned_line(doc))

    pe._okr_plan = lambda: (PLAN, ITEMS)
    calls = []
    doc = week_doc()
    sec = ps.find_prefix(doc, pm.SEC_ALIGNED, pm.scope_of("weekly", pm.SEC_ALIGNED))
    doc_no = ps.parse_sections(ps.serialize_sections(doc).replace("- 🥅 Aligned\n", ""))

    class Spy:
        def focus_records(self, a, b):
            calls.append((a, b))
            return []

    pe._fill_aligned(doc_no, P_WK, TODAY, cur, prev, Spy(),
                     pm.scope_of("weekly", pm.SEC_ALIGNED))
    check("4.the bullet deleted = the kill switch: nothing written, the timeline never paged",
          aligned_line(doc_no) is None and not calls, calls)
    pe._okr_plan = lambda: ("", [])
    doc = week_doc()
    pe._fill_aligned(doc, P_WK, TODAY, cur, prev, None, pm.scope_of("weekly", pm.SEC_ALIGNED))
    check("4.OKRs off: the bullet stays as it is", aligned_line(doc)[0] == "🥅 Aligned")
    pe._okr_plan = lambda: (PLAN, ITEMS)
    doc = week_doc()
    pe._fill_aligned(doc, P_WK, TODAY, [], prev, None, pm.scope_of("weekly", pm.SEC_ALIGNED))
    check("4.nothing done yet this week", aligned_line(doc)[0].startswith(
        "🥅 Aligned: nothing done yet"), aligned_line(doc))
finally:
    pe._okr_plan, pe._okr_rows_known = _real

print(f"okr stats: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
