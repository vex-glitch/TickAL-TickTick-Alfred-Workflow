#!/usr/bin/env python3
"""The yearly round (Vex 2026-09-27, 🟢 on the Yearly Note Round page): the
note, its journal and its review's plumbing.

The note is the quarterly's shape counted by QUARTER: 🥅 OKRs, 🏆 Goals with
his own 🎉 Yearly goal (moved out of the 🎯 Goals scorecard, which stays as
the plan's own section), ✨ Highlight, 📊 Stats, 💿 Data, ⏪ Last year, the
journal, the review. The old skeleton's seven sections that never had a
filler are gone; four of them live on as journal questions.

What this guards:
  * the template resolves every anchor a writer targets, in its scope
  * the pyramid's top storey: a year reads its quarters' notes, an unfilled
    or missing one is unknown, and a quarter summed out of some of its months
    makes the year partial too
  * the goal home moved, and a note minted under the old skeleton still answers
  * the set block: sixteen questions in his order, each routing to its key,
    the quarterly's and the monthly's own keys untouched
  * the draw: ten a year, two per category, cycling by year
  * the relayout of a note minted under the old skeleton loses nothing typed

No network and nothing real: HOME is a temp dir, today is pinned.

    python3.13 tests/test_yearly_note.py
"""
import os
import re
import sys
import tempfile
from datetime import date

_TMP = tempfile.mkdtemp(prefix="tickal_yr_")
os.environ["HOME"] = _TMP
os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, os.path.join(ROOT, "tools", "pnrepair"))

import periodic_sections as ps      # noqa: E402
import periodic_model as pm         # noqa: E402
import periodic_engine as pe        # noqa: E402
import periodic_journal as pj       # noqa: E402
import config as cfg                # noqa: E402

pe.LOG_FILE = os.path.join(_TMP, "periodic.log")        # never the real log
pe._today = lambda: date(2026, 9, 27)                   # the year is running
os.environ["TT_V2_TOKEN"] = ""


class FakeT2:
    """Tier-2 without the v2 API: the fillers' focus, habit, birthday and
    date readers, answering from the lists below and keeping the order the
    focus spans were asked in."""
    asked = []
    minutes = {}            # {(start, end): (minutes, top task)}

    @classmethod
    def focus_by_span(cls, a, b):
        cls.asked.append(("span", a, b))
        return cls.minutes.get((a, b), (0, None))

    @classmethod
    def focus_minutes(cls, a, b):
        cls.asked.append(("minutes", a, b))
        return (cls.minutes.get((a, b)) or (0, None))[0]

    @staticmethod
    def habit_lines_weekly(a, b):
        return ["- Weekly Review · 2/3 · 66%"]

    @staticmethod
    def dates_in_span(a, b):
        return ["- 🎂 Tata · Mon 5th Jan"]

    @staticmethod
    def bday_lines(days=14):
        return [f"- 🎂 Andres · window {days}d"]


pe._tier2 = lambda: FakeT2          # never the v2 API (review 2026-09-27)

P = F = 0
DASH = re.compile("[\\u2013\\u2014]")     # written as escapes: this file must pass the scan


def check(n, c, d=""):
    global P, F
    if c:
        P += 1
    else:
        F += 1
        print("  FAIL", n, d)


def need(name, obj=None):
    """A name the build has to add; a missing one is one red line, not a crash."""
    ok = hasattr(obj or pm, name)
    check(f"{(obj or pm).__name__}.{name} exists", ok)
    return ok


Y = pm.period_for("yearly", date(2026, 9, 27))
Q3 = pm.period_for("quarterly", date(2026, 9, 27))
LINKS = {"breadcrumbs": "C", "quarterlinks": "- x", "monthlinks": "- x",
         "weeklinks": "- x", "daylinks": "- x"}


def fresh(kind):
    return ps.parse_sections(pm.render_template(pe._load_template(kind), LINKS))


# ── 1. names ────────────────────────────────────────────────────────────────
NAMES = all([need(n) for n in ("SEC_YR_GOAL", "SEC_YBARS", "SEC_LAST_YEAR", "SEC_YR_JNL",
                               "SEC_YREVIEW", "YEARLY_CATEGORIES", "YEAR_EPOCH",
                               "year_index", "scorecard_objectives")])
ENGINE = all([need(n, pe) for n in ("_quarter_stats_of", "_year_quarter_data", "_fill_yearly",
                                    "_yearly_ctx", "_year_words")])
check("config reads the yearly review id", hasattr(cfg, "get_yearly_review_id"))
if not (NAMES and ENGINE):
    print(f"yearly note: {P} passed, {F} failed (the build has not landed)")
    sys.exit(1)

check("1.section names", (pm.SEC_YR_GOAL, pm.SEC_YBARS, pm.SEC_LAST_YEAR, pm.SEC_YR_JNL, pm.SEC_YREVIEW)
      == ("🎉 Yearly goal", "Quarterly Completed", "⏪ Last year", "📔 Yearly journal", "♻️ Yearly Review"))
check("1.the goal home moved", pm.GOAL_SECTION["yearly"] == pm.SEC_YR_GOAL
      and pm.goal_section_names("yearly") == [pm.SEC_YR_GOAL, pm.SEC_SCORECARD], pm.goal_section_names("yearly"))
check("1.the other tiers' homes did not", pm.GOAL_SECTION["quarterly"] == pm.SEC_QTR_QTR
      and pm.GOAL_SECTION["monthly"] == pm.SEC_MTH_MONTH and pm.GOAL_SECTION["daily"] == pm.SEC_DAY_GOAL)

# ── 2. the template ─────────────────────────────────────────────────────────
ydoc = fresh("yearly")
ytext = ps.serialize_sections(ydoc)
for a in pm.WRITER_ANCHORS["yearly"]:
    check(f"2.template resolves {a}",
          ps.find_prefix(ydoc, a, pm.scope_of("yearly", a)) is not None, a)
check("2.anchors cover the layout", {pm.SEC_OKR, pm.SEC_YR_GOAL, pm.SEC_SCORECARD, pm.SEC_HIGHLIGHT, pm.SEC_TOP_LIST,
                                     pm.SEC_TOP_TASKS, pm.SEC_CREATED, pm.SEC_COMPLETED, pm.SEC_YBARS, pm.SEC_FOCUS_WEEK,
                                     pm.SEC_HABIT_WEEK, pm.SEC_HL_WEEK, pm.SEC_ENTRIES, pm.SEC_MOODS, pm.SEC_INCOME,
                                     pm.SEC_MDATES, pm.SEC_PEOPLE, pm.SEC_LAST_YEAR, pm.SEC_YR_JNL, pm.SEC_YREVIEW}
      <= set(pm.WRITER_ANCHORS["yearly"]), set(pm.WRITER_ANCHORS["yearly"]))
OLD_NAMES = ("📊 Dashboard", "🏆 Top 10 wins", "📝 Year in one paragraph", "⭐ Best of", "🧭 Theme of the year",
             "🚫 Anti-goals", "🧪 December test", "💰 Money")
check("2.the old skeleton is gone", not any(s.name in OLD_NAMES for s in ydoc.sections)
      and not any(x in ytext for x in OLD_NAMES), [s.name for s in ydoc.sections])
check("2.the two groups are there", ps.find(ydoc, pm.SEC_WK_STATS) is not None and ps.find(ydoc, pm.SEC_WK_DATA) is not None)
check("2.the scorecard is a section of its own", ps.find(ydoc, pm.SEC_SCORECARD) is not None
      and ps.find(ydoc, pm.SEC_SCORECARD).name == pm.SEC_SCORECARD)
order = [s.name.split(":")[0] for s in ydoc.sections]
check("2.section order", order == [pm.SEC_OKR, pm.SEC_GOALS, pm.SEC_SCORECARD, pm.SEC_HIGHLIGHT, pm.SEC_WK_STATS,
                                   pm.SEC_WK_DATA, pm.SEC_LAST_YEAR, pm.SEC_YR_JNL, pm.SEC_YREVIEW], order)
check("2.no dashes in the template", not DASH.search(ytext))
check("2.scopes", pm.scope_of("yearly", pm.SEC_YR_GOAL) == pm.SEC_GOALS
      and pm.scope_of("yearly", pm.SEC_YBARS) == pm.SEC_WK_STATS
      and pm.scope_of("yearly", pm.SEC_INCOME) == pm.SEC_WK_DATA
      and pm.scope_of("yearly", pm.SEC_MDATES) == pm.SEC_WK_DATA)

# ── 3. the pyramid's top storey ─────────────────────────────────────────────
qdoc = fresh("quarterly")
pe._set_headed(qdoc, pm.SEC_COMPLETED, "680 · 🟢 ▲ 12 (+2%)", pm.ind(["- 🗂 📌CTA · 195"]), pm.SEC_WK_STATS)
pe._set_headed(qdoc, pm.SEC_CREATED, "1555", pm.ind(["- 🗂 🌅 Routines · 403"]), pm.SEC_WK_STATS)
ps.set_body(qdoc, pm.SEC_TOP_LIST, ["\t- 📌CTA · 92 done · 142 added"], pm.SEC_WK_STATS)
ps.set_body(qdoc, pm.SEC_TOP_TASKS, ["\t- Commute · 9×", "\t- Paint it · 4×"], pm.SEC_WK_STATS)
idx = {("quarterly", pm.title_key(Q3)): {"id": "Q", "projectId": "P", "content": ps.serialize_sections(qdoc)}}
st = pe._quarter_stats_of(idx, Q3)
check("3.a quarter's Completed reads back", st and st["done"] == 680, st)
check("3.with its breakdown", st and st["by_proj"] == {"📌CTA": 195}, st)
check("3.a quarter's Created reads back", st and st["created"] == 1555, st)
check("3.its rankings read back", st and st["top_lists"] == {"📌CTA": (92, 142)} and st["top_tasks"] == {"Paint it": 4}, st)
check("3.a whole quarter is not partial", st and st["partial"] is False, st)
check("3.no note is None", pe._quarter_stats_of({}, Q3) is None)
check("3.an unfilled quarterly note is unknown", pe._quarter_stats_of(
    {("quarterly", pm.title_key(Q3)): {"id": "E", "projectId": "P", "content": ps.serialize_sections(fresh("quarterly"))}}, Q3) is None)
check("3.the routines list is dropped by name", pe._quarter_stats_of(idx, Q3, {"📌CTA"})["by_proj"] == {})
pdoc = fresh("quarterly")
pe._set_headed(pdoc, pm.SEC_COMPLETED, "680 · 1 of 3 months", [], pm.SEC_WK_STATS)
pidx = {("quarterly", pm.title_key(Q3)): {"id": "Q", "projectId": "P", "content": ps.serialize_sections(pdoc)}}
check("3.a quarter summed out of some months says so", pe._quarter_stats_of(pidx, Q3)["partial"] is True)

# ── 4. the filler ───────────────────────────────────────────────────────────
y1 = fresh("yearly")
pe._fill_yearly(y1, Y, idx)
head = ps.find_prefix(y1, pm.SEC_COMPLETED, pm.SEC_WK_STATS).name
check("4.a partial year says so", head == "Completed: 680 · 1 of 4 quarters", head)
check("4.and draws no chip", "▲" not in head and "▼" not in head, head)
chead = ps.find_prefix(y1, pm.SEC_CREATED, pm.SEC_WK_STATS).name
check("4.created is summed the same way", chead == "Created: 1555 · 1 of 4 quarters", chead)
bars = ps.find(y1, pm.SEC_YBARS, pm.SEC_WK_STATS).body
check("4.a quarter with no note says no note", any("Q1 · Jan-Mar · no note" in l for l in bars), bars)
check("4.the quarter that has numbers draws its bar", any("Q3 · Jul-Sep" in l and "680" in l for l in bars), bars)
check("4.a quarter that has not started is not listed", not any("Q4" in l for l in bars), bars)
tl = ps.find(y1, pm.SEC_TOP_LIST, pm.SEC_WK_STATS).body
check("4.top lists come off the quarters", any("📌CTA" in l and "92 done" in l for l in tl), tl)
inc = ps.find_prefix(y1, pm.SEC_INCOME, pm.SEC_WK_DATA)
check("4.income says 'no notes' where there are none", any("no notes" in l for l in inc.body), inc.body)
check("4.income lines are labelled by quarter", any("Q1 · Jan-Mar" in l for l in inc.body), inc.body)
check("4.the journal is seeded", any(pm.JOURNAL_Q_RE.match(l) for l in ps.find(y1, pm.SEC_YR_JNL).body))
# a quarter whose note exists but has no numbers is a different fact
e_idx = dict(idx)
Q1 = pm.period_for("quarterly", date(2026, 2, 1))
e_idx[("quarterly", pm.title_key(Q1))] = {"id": "J", "projectId": "P", "content": ps.serialize_sections(fresh("quarterly"))}
y2 = fresh("yearly")
pe._fill_yearly(y2, Y, e_idx)
bars2 = ps.find(y2, pm.SEC_YBARS, pm.SEC_WK_STATS).body
check("4.a note with no numbers is not a missing note", any("Q1 · Jan-Mar · no numbers" in l for l in bars2), bars2)
# a partial quarter inside the year: the bar says so
y3 = fresh("yearly")
pe._fill_yearly(y3, Y, pidx)
bars3 = ps.find(y3, pm.SEC_YBARS, pm.SEC_WK_STATS).body
check("4.a partial quarter's bar says how partial", any("Q3 · Jul-Sep" in l and l.rstrip().endswith("680 · 1 of 3 months") for l in bars3), bars3)
head3 = ps.find_prefix(y3, pm.SEC_COMPLETED, pm.SEC_WK_STATS).name
check("4.and the year counts in months then", head3 == "Completed: 680 · 1 of 12 months", head3)
check("4.which the compare question drops as partial", pm.quarter_compare({"Completed": head3.split(": ", 1)[1]}, {"Completed": "500"}) == "")
# the layout guard: a note minted under the old skeleton is left alone
OLD = "\n".join([
    "◀ 2025 · 2027 ▶", "---", "- Q1 · Jan-Mar", "- Q2 · Apr-Jun", "- Q3 · Jul-Sep", "- Q4 · Oct-Dec", "---",
    "##### 🥅 OKRs", "- 🎉 2026 • 1/41 KRs • 🔴 1d",
    "\t- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/aa/tasks/bb) 1/41 🔴 1d", "---",
    "##### 📊 Dashboard", "_(pending)_", "", "##### 🏆 Top 10 wins", "",
    "##### 🎯 Goals scorecard",
    "- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/aa/tasks/bb) ▰▱▱▱▱ 1/41 • Sep 23 - Dec 25 • 🔴 1d",
    "\t- 🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/aa/tasks/cc) 0/5 • Sep 24 - Sep 28",
    "\t- 🥅 [TickAL](https://ticktick.com/webapp/#p/aa/tasks/dd) 1/6 • Sep 29 - Oct 14",
    "- [ ] [💼 P • Productivity System 🔗](https://ticktick.com/webapp/#p/ee/tasks/ff)", "",
    "##### 📝 Year in one paragraph", "", "##### ⭐ Best of", "- Best book:", "- Best trip:", "- Best purchase:",
    "- Best meal:", "- Best day:", "", "##### 🧭 Theme of the year", "", "##### 🚫 Anti-goals",
    "_(what you will NOT do)_", "", "##### 🧪 December test", "Would December-you be proud of this plan?", "",
    "##### 💰 Money", "- 2026-Q1 • 0", "- 2026-Q2 • 0", "- 2026-Q3 • 2955", "- 2026-Q4 • 0", "\t\t- **Total = 2955**"])
old = ps.parse_sections(OLD)
pe._fill_yearly(old, Y, idx)
check("4.a note minted under the old skeleton is left alone",
      "Quarterly Completed" not in ps.serialize_sections(old) and "##### 📊 Dashboard" in ps.serialize_sections(old))
# a sealed year is not refilled
y4 = fresh("yearly")
pe._fill_yearly(y4, pm.period_for("yearly", date(2024, 6, 1)), idx)
check("4.a closed year is not refilled", ps.find_prefix(y4, pm.SEC_COMPLETED, pm.SEC_WK_STATS).name == "Completed")
check("4.the review sweeps its ticks", pm.SEC_YREVIEW in pe._SWEEP_SECTIONS.get("yearly", ()))
# focus: read quarter by quarter, NEWEST first, and summed (the timeline is
# paged 40 pages a call at most; one call for the whole year stopped short)
FakeT2.asked = []
FakeT2.minutes = {(date(2026, 1, 1), date(2026, 3, 31)): (600, "A"), (date(2026, 4, 1), date(2026, 6, 30)): (60, "B"),
                  (date(2026, 7, 1), date(2026, 9, 27)): (90, "C"),
                  (date(2025, 10, 1), date(2025, 12, 31)): (30, None), (date(2025, 1, 1), date(2025, 3, 31)): (30, None)}
y5 = fresh("yearly")
pe._fill_yearly(y5, Y, idx)
fsec = ps.find_prefix(y5, pm.SEC_FOCUS_WEEK, pm.SEC_WK_STATS)
check("4.focus is the sum of its quarters", fsec.name.startswith("Focus: 12h 30m") and any("Total = 12h 30m" in l for l in fsec.body), (fsec.name, fsec.body))
check("4.focus chips against last year's quarters, summed", "▲" in fsec.name and "1h 00m" not in fsec.name, fsec.name)
spans_asked = [x for x in FakeT2.asked if x[0] == "span"]
check("4.focus never asks the whole year in one call", (date(2026, 1, 1), date(2026, 9, 27)) not in [(a, b) for _k, a, b in FakeT2.asked], FakeT2.asked)
check("4.focus asks the newest quarter first", [a for _k, a, _b in spans_asked] == [date(2026, 7, 1), date(2026, 4, 1), date(2026, 1, 1)], spans_asked)
check("4.last year is asked after this year, newest first",
      [a for k, a, _b in FakeT2.asked if k == "minutes"][:4] == [date(2025, 10, 1), date(2025, 7, 1), date(2025, 4, 1), date(2025, 1, 1)]
      and FakeT2.asked.index(("minutes", date(2025, 10, 1), date(2025, 12, 31))) > FakeT2.asked.index(("span", date(2026, 1, 1), date(2026, 3, 31))), FakeT2.asked)
check("4.focus lines are in calendar order", [l.strip().split(" · ")[0] for l in fsec.body[:3]] == ["- Q1", "- Q2", "- Q3"], fsec.body)
FakeT2.minutes = {}
# people: the block the quarterly carries (three months), the year's dates under it
check("4.people look three months ahead, like the quarterly", ps.find(y5, pm.SEC_PEOPLE, pm.SEC_WK_DATA).body[0].strip() == "- 🎂 Andres · window 92d",
      ps.find(y5, pm.SEC_PEOPLE, pm.SEC_WK_DATA).body)
# a quarter's THREE highlights stay three
hq = fresh("quarterly")
ps.set_body(hq, pm.SEC_HIGHLIGHT, pm.highlight_body("Shipped TickAL v3\nGot the flat\nFinished the book"))
pe._set_headed(hq, pm.SEC_COMPLETED, "680", [], pm.SEC_WK_STATS)
y6 = fresh("yearly")
pe._fill_yearly(y6, Y, {("quarterly", pm.title_key(Q3)): {"id": "Q", "projectId": "P", "content": ps.serialize_sections(hq)}})
hl6 = ps.find(y6, pm.SEC_HL_WEEK, pm.SEC_WK_DATA).body
check("4.a quarter's three highlights are kept apart", [l.strip() for l in hl6 if l.strip()] == ["- Q3 · Jul-Sep · Shipped TickAL v3 / Got the flat / Finished the book"], hl6)
check("4.and the journal quotes them that way", pe.journal_ctx("yearly", y6, Y.start).get("quarters") == "Q3 · Jul-Sep · Shipped TickAL v3 / Got the flat / Finished the book",
      pe.journal_ctx("yearly", y6, Y.start).get("quarters"))
check("4.the week's and the month's highlight read as before", pe._tier_highlight_of(hq, "quarterly") == "Shipped TickAL v3 Got the flat Finished the book")
# ⏪ Last year keeps its partial marker when THIS year has no quarter to read yet (1 January)
_t = pe._today
pe._today = lambda: date(2027, 1, 3)
y7 = fresh("yearly")
pe._fill_yearly(y7, pm.period_for("yearly", date(2027, 1, 3)), pidx)
ly7 = [l.strip() for l in ps.find(y7, pm.SEC_LAST_YEAR).body]
pe._today = _t
check("4.last year says how partial it is on 1 January", "- Completed: 680 · 1 of 12 months" in ly7, ly7)
# the 💰 Money roll-up writes its OWN section only
ym = fresh("yearly")
ps.set_body(ym, pm.SEC_HIGHLIGHT, pm.highlight_body("Money\nThe flat\nTickAL shipped"))
before = ps.serialize_sections(ym)
_ds = pe._day_sums
pe._day_sums = lambda index: {date(2026, 9, 1): 485}
pe._fill_rollup_money(ym, Y, {})
check("4.the money roll-up leaves a highlight called Money alone", ps.serialize_sections(ym) == before, ps.find(ym, pm.SEC_HIGHLIGHT).body)
oldm = ps.parse_sections(OLD)
pe._fill_rollup_money(oldm, Y, {})
check("4.and still fills a note that has the section", any("Total = 485" in l for l in ps.find(oldm, pm.SEC_MONEY).body), ps.find(oldm, pm.SEC_MONEY).body)
for kind in ("monthly", "quarterly"):
    dk = fresh(kind)
    ps.set_body(dk, pm.SEC_HIGHLIGHT, pm.highlight_body("Money\nThe flat"))
    bk = ps.serialize_sections(dk)
    pe._fill_rollup_money(dk, pm.period_for(kind, date(2026, 9, 27)), {})
    check(f"4.the same for the {kind} note", ps.serialize_sections(dk) == bk)
pe._day_sums = _ds

# ── 5. the goal home ────────────────────────────────────────────────────────
g = fresh("yearly")
check("5.the editor finds its goal home", pe._goal_sec_of(g, "yearly") is not None
      and pe._goal_sec_of(g, "yearly").name == pm.SEC_YR_GOAL)
pe._goal_append(g, pm.SEC_YR_GOAL, "\t- [ ] First")
pe._goal_append(g, pm.SEC_YR_GOAL, "\t- [ ] Second")
check("5.a year carries several goals", pe._goal_sec_of(g, "yearly").body[:2] == ["\t- [ ] First", "\t- [ ] Second"],
      pe._goal_sec_of(g, "yearly").body)
check("5.the scorecard did not take them", not any("First" in l for l in ps.find(g, pm.SEC_SCORECARD).body))
check("5.the old skeleton's scorecard still answers", pe._goal_sec_of(ps.parse_sections(OLD), "yearly") is not None
      and pm.goal_titles(pe._goal_sec_of(ps.parse_sections(OLD), "yearly").body) == ["💼 P • Productivity System 🔗"],
      pm.goal_titles(pe._goal_sec_of(ps.parse_sections(OLD), "yearly").body))
# the kill switch: a NEW layout note whose 🎉 bullet is gone or renamed has no
# goal home; the scorecard is the plan's there, never the fallback
for label, dead in (("deleted", ps.serialize_sections(fresh("yearly")).replace("- 🎉 Yearly goal\n", "")),
                    ("renamed", ps.serialize_sections(fresh("yearly")).replace("- 🎉 Yearly goal\n", "- 🎉 Yearly goals\n\t- [ ] Kept\n"))):
    kd = ps.parse_sections(dead)
    check(f"5.bullet {label}: no goal home", pe._goal_sec_of(kd, "yearly") is None and pe._goal_names(kd, "yearly") == [pm.SEC_YR_GOAL],
          pe._goal_sec_of(kd, "yearly"))
    check(f"5.bullet {label}: the journal quotes no goal", pe.journal_ctx("yearly", kd, Y.start).get("goals") == "")
    kq = fresh("quarterly")
    pe._mirror_goal(kq, pm.SEC_QTR_YEAR, "yearly", {("yearly", "2026"): {"id": "Y", "projectId": "P", "content": dead}},
                    date(2026, 9, 27), "- _(mirrors this year's note - set it there)_")
    check(f"5.bullet {label}: the quarterly mirrors nothing", not pm.goal_titles(ps.find(kq, pm.SEC_QTR_YEAR, pm.SEC_GOALS).body))
check("5.an old skeleton note still answers from the scorecard", pe._goal_names(ps.parse_sections(OLD), "yearly") == [pm.SEC_YR_GOAL, pm.SEC_SCORECARD])
check("5.the other tiers' names are untouched", pe._goal_names(fresh("quarterly"), "quarterly") == pm.goal_section_names("quarterly")
      and pe._goal_names(fresh("monthly"), "monthly") == pm.goal_section_names("monthly"))
# the quarterly's 🎉 mirror follows the goal wherever it lives
for label, src in (("new layout", ps.serialize_sections(g)), ("old skeleton", OLD)):
    q = fresh("quarterly")
    pe._mirror_goal(q, pm.SEC_QTR_YEAR, "yearly", {("yearly", "2026"): {"id": "Y", "projectId": "P", "content": src}},
                    date(2026, 9, 27), "- _(mirrors this year's note - set it there)_")
    body = ps.find(q, pm.SEC_QTR_YEAR, pm.SEC_GOALS).body
    want = ["First", "Second"] if label == "new layout" else ["💼 P • Productivity System 🔗"]
    check(f"5.the quarterly mirrors the year's goals ({label})", pm.goal_titles(body) == want, body)
    check(f"5.and never a plan line ({label})", not any(pm.is_plan_line(l) for l in body), body)

# ── 6. the set block ────────────────────────────────────────────────────────
PLAIN = ["yhighlight", "qlowlights", "ygoals", "qeffort", "qenergy", "ystory", "ybest", "ytheme", "yanti",
         "qpriorities", "qforecast", "free"]
FULL = ["yhighlight", "qlowlights", "ygoals", "yobjectives", "ycompare", "habits", "ymoney", "qeffort", "qenergy",
        "ystory", "ybest", "ytheme", "yanti", "qpriorities", "qforecast", "free"]
Y0 = pm.journal_fixed("yearly", {"goals": "G"})
check("6.plain order, mind last", [k for k, _ in Y0] == PLAIN and Y0[-1] == ("free", "What is on your mind?"), [k for k, _ in Y0])
YCTX = {"goals": "G", "quarters": "Q3 · Jul-Sep · Shipped the workflow", "wins": "a; b", "nags": "n", "moods": "Q3 · Jul-Sep · 😐 3.5 (Average 3.5)",
        "objectives": "Onboard TickTicks 0/5 · TickAL 1/6", "compare": "Income 2955 vs 20000", "wanted": "A flat of my own",
        "habits": "Weekly Review 1/2", "money": "2955 (Q3 · Jul-Sep • 2955)", "focus": "174h 41m (Q3 · Jul-Sep · 174h 41m)"}
Y1 = pm.journal_fixed("yearly", YCTX)
YT = dict(Y1)
check("6.full order", [k for k, _ in Y1] == FULL, [k for k, _ in Y1])
check("6.sixteen with the border", len(Y1) == 16)
check("6.highlight quotes the quarters and the wins", YT.get("yhighlight") ==
      "✨ What are the three biggest highlights of the year? Your quarters: Q3 · Jul-Sep · Shipped the workflow. Your wins: a; b.", YT.get("yhighlight"))
check("6.lowlights quote the nags and the moods", YT.get("qlowlights") ==
      "🔴 What are the three biggest lowlights? Your nags: n. Moods: Q3 · Jul-Sep · 😐 3.5 (Average 3.5).", YT.get("qlowlights"))
check("6.goals", YT.get("ygoals") == "Did you achieve your yearly goals, G? Describe success/fail factors on each."
      and dict(pm.journal_fixed("yearly", {}))["ygoals"] == "Did you achieve your yearly goals? Describe success/fail factors on each.", YT.get("ygoals"))
check("6.objectives", YT.get("yobjectives") == "🏔️ Objective by objective, Onboard TickTicks 0/5 · TickAL 1/6: hit, partial or miss, "
      "and the factor that decided it? Was the bar set too high or too low?", YT.get("yobjectives"))
check("6.compare", YT.get("ycompare") == "⏪ How does this year compare to last year? Income 2955 vs 20000. "
      "Last year you wanted: A flat of my own. Did you get there?", YT.get("ycompare"))
check("6.compare numbers only", dict(pm.journal_fixed("yearly", {"compare": "Completed 1 vs 2"})).get("ycompare")
      == "⏪ How does this year compare to last year? Completed 1 vs 2.")
check("6.compare wanted only", dict(pm.journal_fixed("yearly", {"wanted": "Calm."})).get("ycompare")
      == "⏪ How does this year compare to last year? Last year you wanted: Calm. Did you get there?")
check("6.habits", YT.get("habits") == "🔄 Habit consistency this year: Weekly Review 1/2. Which held, which broke, "
      "and which habits do you want to build next year?", YT.get("habits"))
check("6.money", YT.get("ymoney") == "💰 Income this year: 2955 (Q3 · Jul-Sep • 2955). Does this align with your forecast? "
      "What could you do to improve it? Can you cut down on any expense category?", YT.get("ymoney"))
check("6.effort is his wording, with the focus", YT.get("qeffort") == "⏱ What effort is not worth your time, what are you spending "
      "your time on that is not leading towards the desired outcome? Your focus: 174h 41m (Q3 · Jul-Sep · 174h 41m).", YT.get("qeffort"))
check("6.energy", YT.get("qenergy") == "🔥 When did you feel most passionate this year, and why then? "
      "When did you feel bored or resentful, and why?", YT.get("qenergy"))
check("6.the four from the note", (YT.get("ystory"), YT.get("ybest"), YT.get("ytheme"), YT.get("yanti")) == (
    "📝 Tell the year in one paragraph.", "⭐ Best of the year: book, trip, purchase, meal, day.",
    "🧭 What is next year's theme, in a few words?", "🚫 What will you NOT do next year?"), YT)
check("6.priorities", YT.get("qpriorities") == "🧭 What are your top three priorities for next year, and why do they matter?", YT.get("qpriorities"))
check("6.forecast", YT.get("qforecast") == "🔮 If you continue at this pace, where will you be in a year? "
      "Where do you want to be in 12 months? What do you want to achieve?", YT.get("qforecast"))
check("6.no December test", not any("December" in q for _k, q in Y1))
check("6.every question routes to its key", all(pm.journal_key(q) == k for k, q in Y1), [(k, pm.journal_key(q)) for k, q in Y1 if pm.journal_key(q) != k])
check("6.no dashes in the set block", not any(DASH.search(q) for _k, q in Y1))
QCTX = {"goals": "G", "objectives": "O 1/2", "year": "Y 1/4", "quarters_left": 1, "compare": "Completed 1 vs 2", "wanted": "w",
        "habits": "h", "money": "m", "months": "M1 · July · x", "wins": "w", "nags": "n", "moods": "mo", "focus": "f"}
others = (pm.journal_fixed("quarterly", QCTX) + pm.journal_fixed("monthly", {"goals": "G", "objectives": "O", "quarter": "Q", "months_left": 1, "habits": "h", "money": "m", "weeks": "w"})
          + pm.journal_fixed("weekly", {"goals": "G"}) + pm.journal_fixed("morning", {"goal": "g"}) + pm.journal_fixed("evening", {"goal": "g"}))
check("6.no other tier's question lost its key", all(pm.journal_key(q) == k for k, q in others), [(k, pm.journal_key(q)) for k, q in others if pm.journal_key(q) != k])
check("6.the quarterly still says quarter", dict(pm.journal_fixed("quarterly", QCTX))["qenergy"].startswith("🔥 When did you feel most passionate this quarter")
      and "three months" in dict(pm.journal_fixed("quarterly", QCTX))["qforecast"]
      and dict(pm.journal_fixed("quarterly", QCTX))["qpriorities"] == "🧭 What are your top three priorities, and why do they matter?")
check("6.conditional and quoting", {"yobjectives", "ycompare", "ymoney", "habits"} <= set(pm.CONDITIONAL_KEYS)
      and {"yobjectives", "ycompare", "ymoney", "yhighlight", "qeffort", "qlowlights"} <= set(pm.QUOTING_KEYS)
      and not {"ystory", "ybest", "ytheme", "yanti"} & set(pm.CONDITIONAL_KEYS))
check("6.a phone's apostrophe and star still route", pm.journal_key("🧭 What is next year’s theme, in a few words?") == "ytheme"
      and pm.journal_key("⭐️ Best of the year: book, trip, purchase, meal, day.") == "ybest"
      and pm.journal_key("🏔 Objective by objective, X 1/2: hit, partial or miss, and the factor that decided it? "
                         "Was the bar set too high or too low?") == "yobjectives")
check("6.the highlight has its own key per tier", pm.journal_key("✨ What are the three biggest highlights of the quarter? x") == "qhighlight"
      and pm.journal_key("✨ What are the three biggest highlights of the year? x") == "yhighlight")

# ── 7. the context off the note ─────────────────────────────────────────────
YNOTE = "\n".join([
    "#### 🥅 OKRs", "- 🎉 2026 • 1/41 KRs • 🔴 1d",
    "\t- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/aa/tasks/bb) 1/41 🔴 1d", "---",
    "#### 🏆 Goals", "- 🎉 Yearly goal", "\t- [ ] [💼 P • Productivity System 🔗](https://ticktick.com/webapp/#p/x/tasks/y)", "",
    "#### 🎯 Goals scorecard",
    "- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/aa/tasks/bb) ▰▱▱▱▱ 1/41 • Sep 23 - Dec 25 • 🔴 1d",
    "\t- 🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/aa/tasks/cc) 0/5 • Sep 24 - Sep 28",
    "\t- 🥅 [TickAL](https://ticktick.com/webapp/#p/aa/tasks/dd) 1/6 • Sep 29 - Oct 14", "",
    "#### ✨ Highlight", "---",
    "##### 📊 Stats", "- Top lists:", "\t- 📌CTA · 92 done · 142 added", "", "- Completed: 680 · 1 of 4 quarters", "\t- 🗂 📌CTA · 195", "",
    "- Focus: 174h 41m", "\t- Q3 · Jul-Sep · 174h 41m · Publish run", "\t\t- **Total = 174h 41m**", "",
    "- Habit consistency", "\t- Weekly Review · 1/2 · 50%", "\t- 🌆 Shutdown · 11/14 · 78%", "---",
    "##### 💿 Data", "- ✨ Highlights", "\t- Q3 · Jul-Sep · Shipped the workflow.", "",
    "- 📨 Entries", "\t- **🟢 Wins**", "\t\t- Did weekly review · Sun 20 Sep 09:58", "\t\t- readme done · Wed 15 Jul 19:44", "",
    "\t- **🔴 Nags**", "\t\t- Journal exits after highlight prompt. · Sun 20 Sep 22:05", "",
    "- 😊 Moods: Average 3.5", "\t- Q3 · Jul-Sep · 😐 3.5", "",
    "- 💰 Income: 2955", "\t- Q1 · Jan-Mar • no notes", "\t- Q3 · Jul-Sep • 2955", "\t\t- **Total = 2955**", "---",
    "##### ⏪ Last year", "- Completed: 2000", "- Created: 4000", "- Focus: 300h 00m", "- Mood: 3.2 avg", "- Income: 20000",
    "- 🔮 Wanted: A flat of my own and the studio", "---",
    "##### 📔 Yearly journal",
    "\t- *Q1 · ✨ What are the three biggest highlights of the year? Your wins: x.*", "\t\t- A: The flat, the studio, TickAL",
    "\t- *Q2 · 🔮 If you continue at this pace, where will you be in a year? Where do you want to be in 12 months? What do you want to achieve?*",
    "\t\t- A: Booked out three months ahead", "---"])
yn = ps.parse_sections(YNOTE)
c = pe.journal_ctx("yearly", yn, date(2026, 1, 1))
check("7.goals", c.get("goals") == "💼 P • Productivity System 🔗", c.get("goals"))
check("7.objectives come off the scorecard", c.get("objectives") == "Onboard TickTicks 0/5 · TickAL 1/6", c.get("objectives"))
check("7.quarters, wins, nags", c.get("quarters") == "Q3 · Jul-Sep · Shipped the workflow" and c.get("wins") == "Did weekly review; readme done"
      and c.get("nags") == "Journal exits after highlight prompt", c)
check("7.moods and money", c.get("moods") == "Q3 · Jul-Sep · 😐 3.5 (Average 3.5)"
      and c.get("money") == "2955 (Q1 · Jan-Mar • no notes; Q3 · Jul-Sep • 2955)", c)
check("7.habits and focus", c.get("habits") == "Weekly Review 1/2 · 🌆 Shutdown 11/14"
      and c.get("focus") == "174h 41m (Q3 · Jul-Sep · 174h 41m · Publish run)", c)
check("7.compare drops the partial side, wanted is quoted", c.get("compare") == "Focus 174h 41m vs 300h 00m · Mood 3.5 vs 3.2 · Income 2955 vs 20000"
      and c.get("wanted") == "A flat of my own and the studio", c)
check("7.the set block from the note is whole", [k for k, _ in pm.journal_fixed("yearly", c)] == FULL, [k for k, _ in pm.journal_fixed("yearly", c)])
# kill switches: no scorecard falls back to the 🥅 OKRs year line, no OKRs at all drops the question
nosc = ps.parse_sections(YNOTE.replace("#### 🎯 Goals scorecard", "#### Renamed"))
check("7.no scorecard: the year's plan line", pe.journal_ctx("yearly", nosc, date(2026, 1, 1)).get("objectives") == "Productivity System 1/41",
      pe.journal_ctx("yearly", nosc, date(2026, 1, 1)).get("objectives"))
noplan = ps.parse_sections(YNOTE.replace("#### 🥅 OKRs", "#### Gone").replace("#### 🎯 Goals scorecard", "#### Renamed"))
check("7.no plan at all: no objectives question", "yobjectives" not in [k for k, _ in pm.journal_fixed("yearly", pe.journal_ctx("yearly", noplan, date(2026, 1, 1)))])
check("7.the scorecard reader", pm.scorecard_objectives(ps.find(yn, pm.SEC_SCORECARD).body) == ["Onboard TickTicks 0/5", "TickAL 1/6"]
      and pm.scorecard_objectives(["- 🥅 [Solo](u) ▰▰▱▱▱ 2/6 • Jan 5 - Mar 1 • 🔴 3d", "- [ ] a goal"]) == ["Solo 2/6"]
      and pm.scorecard_objectives(["- 🏔️ [Only a year](u) ▱▱▱▱▱ 0/3 • Jan 5 - Dec 20"]) == ["Only a year 0/3"]
      and pm.scorecard_objectives(["_(pending)_"]) == [] and pm.scorecard_objectives([]) == [],
      pm.scorecard_objectives(ps.find(yn, pm.SEC_SCORECARD).body))
check("7.a name with a count of its own keeps it", pm.scorecard_objectives([
    "- 🏔️ [Read 12/24 books](https://x) ▰▰▱▱▱ 3/5 \u2022 Jan 5 - Dec 20 \u2022 🔴 3d",
    "\t- 🥅 [Ship 24/7 support](https://x) 0/6 \u2022 Sep 29 - Oct 14"]) == ["Ship 24/7 support 0/6"]
      and pm.scorecard_objectives(["- 🥅 [Read 12/24 books](https://x) ▱▱▱▱▱ 0/5 \u2022 Jan 5 - Mar 1"]) == ["Read 12/24 books 0/5"],
      pm.scorecard_objectives(["- 🥅 [Read 12/24 books](https://x) ▱▱▱▱▱ 0/5 \u2022 Jan 5 - Mar 1"]))
check("7.a 🏔️ with nothing under it stands for itself beside one that has", pm.scorecard_objectives([
    "- 🏔️ [Productivity System](u) ▰▱▱▱▱ 1/41 \u2022 Sep 23 - Dec 25", "\t- 🥅 [TickAL](u) 1/6 \u2022 Sep 29 - Oct 14",
    "- 🏔️ [Health](u) ▱▱▱▱▱ 0/3 \u2022 Jan 5 - Dec 20"]) == ["TickAL 1/6", "Health 0/3"])
check("7.the app's escapes read", pm.scorecard_objectives(["- 🥅 \\[Solo\\]\\(u\\) ▰▰▱▱▱ 2/6 \u2022 Jan 5 - Mar 1"]) == ["Solo 2/6"],
      pm.scorecard_objectives(["- 🥅 \\[Solo\\]\\(u\\) ▰▰▱▱▱ 2/6 \u2022 Jan 5 - Mar 1"]))
check("7.the journal writes the yearly note", pe._journal_target("yearly", date(2026, 9, 27)).kind == "yearly"
      and pe._journal_target("yearly", date(2026, 12, 31)) == Y
      and pe._JOURNAL_SECTIONS.get("yearly") == pm.SEC_YR_JNL)
check("7.the highlight is read by key", pe._HL_KEY.get("yearly") == "yhighlight"
      and pe._tier_highlight_of(yn, "yearly") == "The flat, the studio, TickAL", pe._tier_highlight_of(yn, "yearly"))
check("7.next year's note quotes this year's wish", pe._year_words(yn) == ["- 🔮 Wanted: Booked out three months ahead"], pe._year_words(yn))
check("7.a year that never answered has no wish", pe._year_words(fresh("yearly")) == [])

# ── 8. the draw ─────────────────────────────────────────────────────────────
check("8.categories and epoch", pm.YEARLY_CATEGORIES == ("lookback", "lessons", "people", "letting go", "direction")
      and pm.YEAR_EPOCH == date(2026, 1, 1))
check("8.year index", [pm.year_index(date(y, 6, 1)) for y in (2026, 2027, 2029)] == [0, 1, 3])
FAKE = {"categories": {cat: [f"{cat} {i}?" for i in range(1, 7)] for cat in pm.YEARLY_CATEGORIES}, "chains": [],
        "random": [], "constants": []}
d26 = pm.select_prompts(FAKE, date(2026, 12, 31), "yearly")
check("8.ten, two per category, in category order", len(d26) == 10 and len(set(d26)) == 10
      and all(d26[2 * i].startswith(cat + " ") and d26[2 * i + 1].startswith(cat + " ") for i, cat in enumerate(pm.YEARLY_CATEGORIES)), d26)
check("8.any day of the year gives the year's picks", pm.select_prompts(FAKE, date(2026, 1, 1), "yearly") == d26
      and pm.select_prompts(FAKE, date(2026, 9, 27), "yearly") == d26)
d27, d28, d29 = (pm.select_prompts(FAKE, date(y, 12, 31), "yearly") for y in (2027, 2028, 2029))
check("8.three years cover the pool, no prompt two years running", not set(d26) & set(d27) and not set(d27) & set(d28)
      and not set(d28) & set(d29) and len(set(d26) | set(d27) | set(d28)) == 30 and len(d29) == 10, (d27[:2], d28[:2], d29[:2]))
check("8.a date before the epoch keeps the old draw", len(pm.select_prompts(dict(FAKE, random=[f"r{i}" for i in range(20)]), date(2025, 6, 1), "yearly")) == 5)
POOL = pj.load_pool("yearly")
check("8.the shipped pool's shape", list(POOL["categories"]) == list(pm.YEARLY_CATEGORIES)
      and all(len(v) == 6 for v in POOL["categories"].values()) and not POOL["chains"], {k: len(v) for k, v in POOL["categories"].items()})
allq = [q for v in POOL["categories"].values() for q in v]
check("8.the shipped pool is clean", len(set(allq)) == 30 and all(q.strip()[-1] in "?." and not DASH.search(q) for q in allq),
      [q for q in allq if DASH.search(q) or q.strip()[-1] not in "?."][:3])
check("8.no pool prompt is a set question", not [q for q in allq if pm.journal_key(q) != "free"], [q for q in allq if pm.journal_key(q) != "free"])
check("8.no pool prompt asks a person's name the list has to fill", not any("[person" in q for q in allq))
_pool_file = os.path.join(ROOT, "src", "periodic_prompts", "yearly.md")
check("8.the pool file ships", os.path.exists(_pool_file))
if os.path.exists(_pool_file):
    with open(_pool_file, encoding="utf-8") as fh:
        check("8.no dashes anywhere in the pool file", not DASH.search(fh.read()))
ship = [pm.select_prompts(POOL, date(y, 12, 31), "yearly") for y in (2026, 2027, 2028)]
check("8.the shipped draw covers the pool in three years", all(len(x) == 10 for x in ship) and set().union(*ship) == set(allq), len(set().union(*ship)))
seeded = pm.journal_pairs(ps.find(y1, pm.SEC_YR_JNL).body)
check("8.a fresh note seeds the set block and the ten", len(seeded) == len(pm.journal_fixed("yearly", pe.journal_ctx("yearly", y1, Y.start))) + 10, len(seeded))

# ── 9. the relayout of the live 2026 note ───────────────────────────────────
# tools/pnrepair is local to the maintainer's machine (/tools/ is ignored):
# a checkout without it skips this section, a tool that is there and does
# not import is a red
ry = None
if os.path.exists(os.path.join(ROOT, "tools", "pnrepair", "relayout_yearly.py")):
    try:
        import relayout_yearly as ry
    except Exception as e:                               # noqa: BLE001
        check("9.tools/pnrepair/relayout_yearly.py imports", False, repr(e))
else:
    print("  9. skipped (tools/pnrepair is local to the maintainer's machine)")
if ry:
    typed = OLD.replace("##### 📝 Year in one paragraph\n", "##### 📝 Year in one paragraph\nThe year I built the system.\n")
    o = ps.parse_sections(typed)
    n = ry.build(o, Y, idx)
    text = ps.serialize_sections(n)
    check("9.his goal moved to its new home", pm.goal_titles(ps.find(n, pm.SEC_YR_GOAL, pm.SEC_GOALS).body) == ["💼 P • Productivity System 🔗"],
          ps.find(n, pm.SEC_YR_GOAL, pm.SEC_GOALS).body)
    check("9.the goal is not left in the scorecard", not any("💼 P" in l for l in ps.find(n, pm.SEC_SCORECARD).body), ps.find(n, pm.SEC_SCORECARD).body)
    check("9.the plan lines stay until the next fill", any(pm.is_plan_line(l) for l in ps.find(n, pm.SEC_SCORECARD).body), ps.find(n, pm.SEC_SCORECARD).body)
    check("9.what he typed survives", "The year I built the system." in text and "📝 Year in one paragraph" in text)
    check("9.the empty old sections are gone", [s.name for s in n.sections if s.name.split(":")[0] in OLD_NAMES] == ["📝 Year in one paragraph"],
          [s.name for s in n.sections])
    filled = ry.build(ps.parse_sections(OLD.replace("- Best book:", "- Best book: Dune")), Y, idx)
    check("9.a line he filled in keeps its section", "- Best book: Dune" in ps.serialize_sections(filled)
          and any(s.name == "⭐ Best of" for s in filled.sections))
    check("9.the new layout is filled", "Quarterly Completed" in text and ps.find_prefix(n, pm.SEC_COMPLETED, pm.SEC_WK_STATS).name.startswith("Completed: 680"))
    check("9.nothing of his is lost", ry.verify(o, n) == [], ry.verify(o, n))
    check("9.a second pass changes nothing", ps.serialize_sections(ry.build(ps.parse_sections(text), Y, idx)) == text)
    lost = ps.parse_sections(text.replace("The year I built the system.", ""))
    check("9.verify notices a lost line", ry.verify(o, lost) != [])
    check("9.a note already in the current layout is told apart", ry.in_current_layout(n) and not ry.in_current_layout(o))

    def fate(body, *needles):
        """(kept, refused) for a variant of the old note: every needle is in
        the rebuilt note, or verify() names a loss. Never neither."""
        od = ps.parse_sections(body)
        nd = ry.build(od, Y, idx)
        out = ps.serialize_sections(nd)
        return all(x in out for x in needles), bool(ry.verify(od, nd))

    CASES = {
        "a heading typed in an old section": (OLD.replace("##### 🚫 Anti-goals\n", "##### 🚫 Anti-goals\n## No free work, no 7-day weeks\n"),
                                              ["## No free work, no 7-day weeks"]),
        "a heading above the December test's own line": (OLD.replace("Would December-you", "# Yes, mostly\nWould December-you"), ["# Yes, mostly"]),
        "a heading as the last line of a section": (OLD.replace("##### 📝 Year in one paragraph\n", "##### 📝 Year in one paragraph\nThe year.\n## Chapter two\n"),
                                                    ["The year.", "## Chapter two"]),
        "text in a header": (OLD.replace("##### 🧭 Theme of the year\n", "##### 🧭 Theme of the year: Rebuild\n"), ["🧭 Theme of the year: Rebuild"]),
        "a renamed header": (OLD.replace("##### 🧭 Theme of the year\n", "##### 🧭 Rebuild year\n"), ["🧭 Rebuild year"]),
        "his own aside in italics": (OLD.replace("_(what you will NOT do)_", "_(no more free work)_"), ["_(no more free work)_"]),
        "a filled best-of line": (OLD.replace("- Best book:", "- Best book: Dune"), ["- Best book: Dune"]),
        "text under the Dashboard": (OLD.replace("##### 📊 Dashboard\n_(pending)_", "##### 📊 Dashboard\nMy own numbers"), ["My own numbers"]),
        "a heading inside the scorecard": (OLD.replace("- [ ] [💼 P", "## My own goals\n- [ ] [💼 P"), ["## My own goals", "💼 P • Productivity System"]),
        "a plain text goal": (OLD.replace("- [ ] [💼 P", "Earn 50k\n- [ ] [💼 P"), ["Earn 50k", "💼 P • Productivity System"]),
        "a section named like a generated bullet": (OLD + "\n##### 👽 People\n- Ivona: the year we got engaged\n", ["- Ivona: the year we got engaged"]),
        "the same line under two goals": (OLD.replace("- [ ] [💼 P", "- [ ] Goal A\n\t- [ ] Weekly check\n- [ ] Goal B\n\t- [ ] Weekly check\n- [ ] [💼 P"), []),
    }
    for name, (body, needles) in CASES.items():
        kept, refused = fate(body, *needles)
        check(f"9.{name}: kept, or the tool refuses", kept or refused, (kept, refused))
    two = ry.build(ps.parse_sections(CASES["the same line under two goals"][0]), Y, idx)
    gb = [l.strip() for l in ps.find(two, pm.SEC_YR_GOAL, pm.SEC_GOALS).body]
    check("9.a line repeated under two goals is kept twice", gb.count("- [ ] Weekly check") == 2 or bool(ry.verify(ps.parse_sections(CASES["the same line under two goals"][0]), two)), gb)
    # the kill switches survive: a note he took 🥅 OKRs out of does not get it back
    nokr = OLD.replace("##### 🥅 OKRs\n- 🎉 2026 • 1/41 KRs • 🔴 1d\n\t- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/aa/tasks/bb) 1/41 🔴 1d\n---\n", "")
    nk = ry.build(ps.parse_sections(nokr), Y, idx)
    check("9.a deleted 🥅 OKRs stays deleted", "🥅 OKRs" not in OLD.replace(nokr, "") or not any(s.name == pm.SEC_OKR for s in nk.sections), [s.name for s in nk.sections])
    check("9.and the rest of the layout stands", [s.name.split(":")[0] for s in nk.sections][:3] == [pm.SEC_GOALS, pm.SEC_SCORECARD, pm.SEC_HIGHLIGHT], [s.name for s in nk.sections])
    # a second pass over a note he has since written in: nothing is lost unseen
    written = text.replace("#### ✨ Highlight\n", "#### ✨ Highlight\nThe flat\n").replace(
        "- 🎉 Yearly goal\n", "- 🎉 Yearly goal\n\t- [ ] Earn 50k\n", 1)
    wd = ps.parse_sections(written)
    jb = list(ps.find(wd, pm.SEC_YR_JNL).body)
    ai = next(i for i, l in enumerate(jb) if pm.JOURNAL_A_RE.match(l))
    jb[ai] = jb[ai].rstrip() + " The flat, the studio"
    jb.insert(ai + 1, "\t\t- and TickAL")
    ps.set_body(wd, pm.SEC_YR_JNL, jb)
    wn = ry.build(wd, Y, idx)
    wt = ps.serialize_sections(wn)
    check("9.a second pass keeps answers, goals and the highlight", all(x in wt for x in ("The flat, the studio", "- and TickAL", "- [ ] Earn 50k", "\nThe flat\n"))
          and ry.verify(wd, wn) == [], ry.verify(wd, wn))
    extra = ps.parse_sections(written.replace("#### 🎯 Goals scorecard", "- 🧭 Theme: Rebuild\n\n#### 🎯 Goals scorecard", 1))
    en = ry.build(extra, Y, idx)
    check("9.a bullet of his under 🏆 Goals: kept, or the tool refuses", "- 🧭 Theme: Rebuild" in ps.serialize_sections(en) or bool(ry.verify(extra, en)))

# ── 10. the doors and the routine ───────────────────────────────────────────
import routine_link as rl       # noqa: E402
import routines as rt           # noqa: E402
def parsed(arg):
    try:
        return rl.parse(arg)
    except ValueError as e:
        return str(e)


check("10.journal:yearly is a link", "yearly" in rl.SLOT_VERBS["journal"] and parsed("journal:yearly") == ("journal", "yearly", ""))
check("10.it is offered as a copy-a-link row", any(r[0] == "yearly_journal" and "journal%3Ayearly" in r[3] for r in rl.internal_links()))
y_r = rt.by_key("yearly")
check("10.the routine is registered", bool(y_r) and re.fullmatch(r"[0-9a-f]{24}", (y_r or {}).get("tid", "")) is not None
      and (y_r or {}).get("pid") == rt.ROUTINES_LIST, y_r)
check("10.routine:yearly is a link", parsed("routine:yearly") == ("routine", "yearly", ""), parsed("routine:yearly"))
check("10.its habit is a habit id or nothing", not (y_r or {}).get("habit") or re.fullmatch(r"[0-9a-f]{24}", y_r["habit"]) is not None, y_r)
YRULE = "RRULE:FREQ=MONTHLY;INTERVAL=12;BYMONTHDAY=-1"
check("10.the rule reads as the last day", rt.rule_text(YRULE) == "the last day, every 12 months", rt.rule_text(YRULE))
check("10.the occurrence before 31 Dec 2027 is 31 Dec 2026", rt.prev_occurrence(date(2027, 12, 31), YRULE) == date(2026, 12, 31),
      rt.prev_occurrence(date(2027, 12, 31), YRULE))
# a review run LATE files its journal into the period it is about
_open = {"startDate": "2026-12-31T06:00:00+0000", "repeatFlag": YRULE}
check("10.on its day the journal is not pinned", rt.journal_pin("yearly", _open, date(2026, 12, 31)) == "")
check("10.a day late it is pinned to the year that ended", rt.journal_pin("yearly", _open, date(2027, 1, 1)) == "@2026-12-31", rt.journal_pin("yearly", _open, date(2027, 1, 1)))
check("10.ahead of its day it is not", rt.journal_pin("yearly", _open, date(2026, 9, 27)) == "")
_q = {"startDate": "2026-09-30T05:00:00+0000", "repeatFlag": "RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=-1"}
check("10.the quarterly a day late", rt.journal_pin("quarterly", _q, date(2026, 10, 1)) == "@2026-09-30"
      and rt.journal_pin("monthly", _q, date(2026, 10, 2)) == "@2026-09-30")
_w = {"startDate": "2026-09-27T05:00:00+0000", "repeatFlag": "RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=SU"}
check("10.the weekly on Monday", rt.journal_pin("weekly", _w, date(2026, 9, 28)) == "@2026-09-27"
      and rt.journal_pin("weekly", _w, date(2026, 9, 27)) == "")
check("10.late inside the same period is not late", rt.journal_pin("monthly", {"startDate": "2026-09-15T05:00:00+0000"}, date(2026, 9, 20)) == "")
check("10.the daily journals are never pinned by this", rt.journal_pin("evening", _open, date(2027, 1, 1)) == "" and rt.journal_pin("yearly", None, date(2027, 1, 1)) == "")
import periodic_rows as pr      # noqa: E402
jr = [m for m in pr._FAMILIES["journals"][1] if m[3] == "xact:pn_journal:yearly"]
check("10.the hub has a yearly journal row", len(jr) == 1 and jr[0][1] == "📔 Yearly journal", jr)
import xact                      # noqa: E402
check("10.the journal action knows the slot", xact._JOURNAL_UI.get("yearly") == ("📔", "Yearly"))
check("10.the highlight answer goes to its tier", getattr(xact, "_HL_TIER", {}) == {"mhighlight": "monthly", "qhighlight": "quarterly", "yhighlight": "yearly"},
      getattr(xact, "_HL_TIER", None))
check("10.the goal editor follows the yearly journal", "yearly" in getattr(xact, "_OPEN_GOAL_SLOTS", ()), getattr(xact, "_OPEN_GOAL_SLOTS", None))
check("10.a late journal's goal editor is not aimed a period too far",
      xact._journal_is_late("yearly", pm.period_for("yearly", date(2026, 12, 31)), date(2027, 1, 1)) is True
      and xact._journal_is_late("yearly", pm.period_for("yearly", date(2026, 12, 31)), date(2026, 12, 31)) is False
      and xact._journal_is_late("weekly", pm.period_for("weekly", date(2026, 9, 27)), date(2026, 9, 28)) is True
      and xact._journal_is_late("evening", pm.period_for("daily", date(2026, 9, 26)), date(2026, 9, 27)) is False)
import browse                    # noqa: E402
check("10.a series that never ran has no last one", browse._before_birth({"createdTime": "2026-09-27T12:00:00+0000"}, date(2025, 12, 31)) is True
      and browse._before_birth({"createdTime": "2026-09-27T12:00:00+0000"}, date(2026, 12, 31)) is False
      and browse._before_birth({}, date(2025, 12, 31)) is False)
check("10.the routine opens the yearly note", getattr(xact, "_ROUTINE_SPEC", {}).get("yearly") == "yearly"
      and getattr(xact, "_ROUTINE_SPEC", {}).get("quarterly") == "quarterly" and getattr(xact, "_ROUTINE_SPEC", {}).get("meal") == "weekly",
      getattr(xact, "_ROUTINE_SPEC", None))

print(f"yearly note: {P} passed, {F} failed")
sys.exit(1 if F else 0)
