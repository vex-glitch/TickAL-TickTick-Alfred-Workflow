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

# ── the multi-goal editor (Vex 2026-09-17) ─────────────────────────────────
def _goal_doc(kind):
    d = ps.parse_sections(pm.render_template(
        pe._load_template(kind), {"breadcrumbs": "C", "monthlinks": "- x",
                                  "weeklinks": "- x", "daylinks": "- x"}))
    return d


for kind, anchor in (("monthly", pm.SEC_MTH_MONTH),
                     ("quarterly", pm.SEC_QTR_QTR),
                     ("weekly", pm.SEC_WK_WEEK)):
    d = _goal_doc(kind)
    check(f"{kind}: the editor finds its goal home",
          pe._goal_sec_of(d, kind) is not None)
    pe._goal_append(d, anchor, "\t- [ ] First")
    pe._goal_append(d, anchor, "\t- [ ] Second")
    body = pe._goal_sec_of(d, kind).body
    check(f"{kind}: a tier carries several goals", len(body) == 2, body)
    keep = [l for l in body if pm.unescape_md(l.strip()) != "- [ ] First"]
    check(f"{kind}: removal matches by text, not position",
          keep == ["\t- [ ] Second"], keep)

# a note minted under the OLD name is still the goal home
oldshape = ps.parse_sections("C\n---\n##### 🎯 OKR review\n\t- [ ] Old goal\n")
check("the quarterly's old goal section still answers",
      pe._goal_sec_of(oldshape, "quarterly") is not None)
oldm = ps.parse_sections("C\n---\n##### 🎯 Month goal\n\t- [ ] Old goal\n")
check("the monthly's old goal section still answers",
      pe._goal_sec_of(oldm, "monthly") is not None)
check("a tier with no goal section resolves to nothing",
      pe._goal_sec_of(ps.parse_sections("C\n---\n### Nothing\n"), "monthly") is None)

# the screen: what is there, removable, plus Done
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
import periodic_rows as pr                                       # noqa: E402
import base64, json                                              # noqa: E402
rows = pr.tier_goal_rows("monthly", "")
kinds = [r["title"].split(" ")[0] for r in rows[:2]]
check("the editor lists before it adds", "🎯" in kinds[0] or "📋" in kinds[0], kinds)
addrow = next((r for r in rows if r["arg"].startswith("xact:pn_setgoal:")), None)
check("the add rows are still there", addrow is not None)
# an aimed-ahead payload reaches the verb
pay = json.loads(base64.b64decode(addrow["arg"].split(":", 2)[2]))
check("the payload names its tier", pay["kind"] == "monthly", pay)
check("and is not aimed ahead by default", not pay.get("ahead"), pay)

# ── what the 2026-09-17 review found ───────────────────────────────────────
check("the quarterly review sweeps its ticks",
      pm.SEC_QREVIEW in pe._SWEEP_SECTIONS["quarterly"])
# a partial roll-up says how partial it is, and draws no chip
qdoc2 = ps.parse_sections(pm.render_template(
    pe._load_template("quarterly"), {"breadcrumbs": "C", "monthlinks": "- x"}))
one = {("monthly", pm.title_key(SEP)): {"id": "M", "projectId": "P",
                                        "content": ps.serialize_sections(mdoc)}}
pe._fill_quarterly(qdoc2, Q3, one)
head = ps.find_prefix(qdoc2, pm.SEC_COMPLETED, pm.SEC_WK_STATS).name
check("a partial quarter says so", head.endswith("1 of 3 months"), head)
check("…and draws no vs-last-quarter chip", "▲" not in head and "▼" not in head, head)
bars = ps.find(qdoc2, pm.SEC_QBARS, pm.SEC_WK_STATS).body
check("a month with no note says no note",
      any("M1 · July · no note" in l for l in bars), bars)
# a month whose note EXISTS but has no numbers is a different fact
noneidx = dict(one)
noneidx[("monthly", pm.title_key(pm.period_for("monthly", date(2026, 7, 1))))] = {
    "id": "J", "projectId": "P",
    "content": pm.render_template(pe._load_template("monthly"),
                                  {"breadcrumbs": "C", "weeklinks": "- x"})}
qdoc3 = ps.parse_sections(pm.render_template(
    pe._load_template("quarterly"), {"breadcrumbs": "C", "monthlinks": "- x"}))
pe._fill_quarterly(qdoc3, Q3, noneidx)
bars3 = ps.find(qdoc3, pm.SEC_QBARS, pm.SEC_WK_STATS).body
check("a note with no numbers is not a missing note",
      any("M1 · July · no numbers" in l for l in bars3), bars3)
# money never invents a zero for a span with no daily notes
inc = ps.find_prefix(qdoc3, pm.SEC_INCOME, pm.SEC_WK_DATA)
check("income says 'no notes' where there are none",
      any("no notes" in l for l in inc.body), inc.body)
# the layout guard
oldq = ps.parse_sections("C\n---\n##### 🎯 OKR review\n_(score)_\n"
                         "##### 📈 Stats\n_(pending)_\n")
pe._fill_quarterly(oldq, Q3, one)
check("a pre-2026-09-17 quarterly is left alone",
      "_(pending)_" in ps.serialize_sections(oldq)
      and "Monthly Completed" not in ps.serialize_sections(oldq))
# the goal kill switch stops the WRITER too
killed = ps.parse_sections(ps.serialize_sections(_goal_doc("weekly")).replace(
    "- ♻️ Weekly\n", ""))
check("deleting ♻️ Weekly leaves nowhere to append",
      pe._week_goal_home(killed) is None)
check("…and an old-shape note still appends to the section",
      pe._week_goal_home(ps.parse_sections("C\n---\n#### 🏆 Goals\n\t- [ ] x\n"))
      == pm.SEC_GOALS)
# an app escape never travels down the mirror chain
check("mirrored lines are unescaped",
      pm.unescape_md_lines(["\t- [ ] \\[Goal\\]\\(u\\)"])
      == ["\t- [ ] [Goal](u)"])
# the highlight answer routes to ITS tier's question
check("the highlight fallback knows each tier's key",
      pm.journal_key("What was the highlight of the quarter? x") == "qhighlight"
      and pm.journal_key("What was the highlight of the month? x") == "mhighlight")

print(f"quarterly note: {P} passed, {F} failed")
sys.exit(1 if F else 0)
