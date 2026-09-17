#!/usr/bin/env python3
"""The quarterly note (Vex 2026-09-17: "kill it all, adhere to our existing
logic") and the head links generalised across all four tiers.

The monthly's shape counted by MONTH. What this guards:

  * child_spans / span_label for every tier - days under a week, weeks under a
    month, months under a quarter, quarters under a year
  * the pyramid's next storey: a quarter reads its months' notes, and an
    unfilled one is unknown rather than a quarter-month of zero
  * a month never straddles a quarter, so nothing needs clipping
  * the quarterly journal's two fixed questions route to their own keys and
    not to the month's or the week's

No network: the notes are rendered from the shipped templates into a fake
index.

    python3 tests/test_quarterly_note.py
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_sections as ps
import periodic_model as pm
import periodic_engine as pe
import periodic_journal as pj

P = F = 0


def check(n, c, d=""):
    global P, F
    if c:
        P += 1
    else:
        F += 1
        print("  FAIL", n, d)


Q3 = pm.period_for("quarterly", date(2026, 9, 17))
Y = pm.period_for("yearly", date(2026, 9, 17))

# ── the head, four tiers, one function ─────────────────────────────────────
check("a week holds seven days", len(pm.child_spans(pm.period_for(
    "weekly", date(2026, 9, 17)))) == 7)
check("a quarter holds three months", len(pm.child_spans(Q3)) == 3)
check("a year holds four quarters", len(pm.child_spans(Y)) == 4)
check("a daily has no children", pm.child_spans(pm.period_for(
    "daily", date(2026, 9, 17))) == [])
check("month labels name the month",
      [pm.span_label("quarterly", n, a, b) for n, _c, a, b in pm.child_spans(Q3)]
      == ["M1 · July", "M2 · August", "M3 · September"])
check("quarter labels carry their months",
      [pm.span_label("yearly", n, a, b) for n, _c, a, b in pm.child_spans(Y)]
      == ["Q1 · Jan-Mar", "Q2 · Apr-Jun", "Q3 · Jul-Sep", "Q4 · Oct-Dec"])
# a month never straddles a quarter, a quarter never straddles a year
for per in (Q3, Y):
    for _n, cp, a, b in pm.child_spans(per):
        check(f"{pm.title(cp)} sits whole inside {pm.title(per)}",
              (a, b) == (cp.start, cp.end), (a, b, cp))
# every day of the parent is covered exactly once
days = set()
for _n, _c, a, b in pm.child_spans(Q3):
    d = a
    while d <= b:
        check("no day is covered twice", d not in days, d)
        days.add(d)
        d += timedelta(days=1)
check("every day of the quarter is covered",
      len(days) == (Q3.end - Q3.start).days + 1, len(days))

# ── the pyramid's next storey ──────────────────────────────────────────────
SEP = pm.period_for("monthly", date(2026, 9, 17))
mdoc = ps.parse_sections(pm.render_template(
    pe._load_template("monthly"), {"breadcrumbs": "C", "monthlinks": "- x"}))
pe._set_headed(mdoc, pm.SEC_COMPLETED, "466 · 🔴 ▼ 12 (−3%)",
               pm.ind(["- 🗂 📌CTA · 116"]), pm.SEC_WK_STATS)
pe._set_headed(mdoc, pm.SEC_CREATED, "1129",
               pm.ind(["- 🗂 🌅 Routines · 379"]), pm.SEC_WK_STATS)
ps.set_body(mdoc, pm.SEC_TOP_LIST, ["\t- 📌CTA · 13 done · 14 added"],
            pm.SEC_WK_STATS)
ps.set_body(mdoc, pm.SEC_TOP_TASKS, ["\t- Commute · 4×"], pm.SEC_WK_STATS)
idx = {("monthly", pm.title_key(SEP)): {"id": "M", "projectId": "P",
                                        "content": ps.serialize_sections(mdoc)}}
st = pe._month_stats_of(idx, SEP)
check("a month's Completed reads back", st["done"] == 466, st)
check("…with its breakdown", st["by_proj"] == {"📌CTA": 116}, st)
check("a month's Created reads back", st["created"] == 1129, st)
check("its rankings read back",
      st["top_lists"] == {"📌CTA": (13, 14)} and st["top_tasks"] == {"Commute": 4})
check("a month with no note is None", pe._month_stats_of({}, SEP) is None)
# an UNFILLED monthly note is not a month of zero
fresh = pm.render_template(pe._load_template("monthly"),
                           {"breadcrumbs": "C", "monthlinks": "- x"})
check("an unfilled monthly note reads as unknown",
      pe._month_stats_of({("monthly", pm.title_key(SEP)):
                          {"id": "E", "projectId": "P", "content": fresh}},
                         SEP) is None)
check("the routines list is dropped by name here too",
      pe._month_stats_of(idx, SEP, {"📌CTA"})["by_proj"] == {})

# ── the note itself ────────────────────────────────────────────────────────
qdoc = ps.parse_sections(pm.render_template(
    pe._load_template("quarterly"),
    {"breadcrumbs": "C", "monthlinks": "\n".join(pe._child_links(Q3, idx))}))
for a in pm.WRITER_ANCHORS["quarterly"]:
    check(f"template resolves {a}",
          ps.find_prefix(qdoc, a, pm.scope_of("quarterly", a)) is not None, a)
check("the month that has a note is linked",
      any(l.startswith("- [M3 · September](") for l in qdoc.lead), qdoc.lead)
check("the rest are plain", "- M1 · July" in qdoc.lead, qdoc.lead)
before = [l for l in qdoc.lead if l.startswith(("- M", "- [M"))]
pe._compose_lead(qdoc, Q3, idx, refetch=False)
check("mint and refresh agree",
      [l for l in qdoc.lead if l.startswith(("- M", "- [M"))] == before)
pe._compose_lead(qdoc, Q3, idx, refetch=False)
check("refresh never doubles the block",
      len([l for l in qdoc.lead if l.startswith(("- M", "- [M"))]) == 3
      and sum(1 for l in qdoc.lead if l.strip() == "---") == 2, qdoc.lead)
check("the OKR skeleton is gone",
      not any(x in ps.serialize_sections(qdoc)
              for x in ("OKR review", "Next-Q OKRs", "Decision log",
                        "Energy audit", "Observations")))

# ── its journal ────────────────────────────────────────────────────────────
fx = pm.journal_fixed("quarterly", {"goals": "G"})
check("two fixed questions", [k for k, _q in fx] == ["qhighlight", "qgoals"], fx)
for key, q in (fx + pm.journal_fixed("monthly", {"goals": "G"})
               + pm.journal_fixed("weekly", {"goals": "G"})):
    check(f"'{q[:30]}' routes to {key}", pm.journal_key(q) == key, pm.journal_key(q))
check("its pool is its own", len(pj.load_pool("quarterly")["random"]) >= 20)
check("its draw is not the month's",
      pm.select_prompts(pj.load_pool("quarterly"), date(2026, 7, 1), "quarterly")
      != pm.select_prompts(pj.load_pool("monthly"), date(2026, 7, 1), "monthly"))
check("the journal writes the quarterly note",
      pe._journal_target("quarterly", date(2026, 9, 17)).kind == "quarterly"
      and pe._JOURNAL_SECTIONS["quarterly"] == pm.SEC_QTR_JNL)
check("the goal question reads the quarter's own goal",
      pe.journal_ctx("quarterly", qdoc)["goals"] == "")

print(f"quarterly note: {P} passed, {F} failed")
sys.exit(1 if F else 0)
