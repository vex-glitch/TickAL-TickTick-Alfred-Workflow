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
