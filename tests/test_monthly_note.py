#!/usr/bin/env python3
"""The monthly note (Vex 2026-09-17: "more or less the same as weekly note").

The weekly's shape one tier up, counted by WEEK. What this guards:

  * a month's weeks: numbered within the month and CLIPPED to it, so a week
    straddling two months contributes only the days that are in this one
  * every W1 carries its date range ("Everywhere you write W1 add date range")
  * the completions pyramid: a month cannot recount its own completions (the
    feed reaches back about nine days), so it reads them off the weekly notes,
    including notes written under the pre-2026-09-17 weekly layout
  * "top 5 of the month" for entries = one per week, newest first, then fill
  * moods by week with the month average in the header

No network: the notes are rendered from the shipped templates into a fake
index.

    python3 tests/test_monthly_note.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_sections as ps
import periodic_model as pm
import periodic_engine as pe

P = F = 0


def check(n, c, d=""):
    global P, F
    if c:
        P += 1
    else:
        F += 1
        print("  FAIL", n, d)


SEP = pm.period_for("monthly", date(2026, 9, 17))

# ── the month's weeks ───────────────────────────────────────────────────────
spans = pm.month_week_spans(SEP)
check("five weeks touch September", len(spans) == 5, spans)
check("numbered within the month", [n for n, _w, _a, _b in spans] == [1, 2, 3, 4, 5])
check("the first week is clipped to the 1st",
      spans[0][2] == date(2026, 9, 1) and spans[0][3] == date(2026, 9, 6),
      spans[0])
check("the last week is clipped to the 30th",
      spans[4][2] == date(2026, 9, 28) and spans[4][3] == date(2026, 9, 30),
      spans[4])
check("each points at a real ISO week",
      pm.title(spans[0][1]) == "2026-W36" and pm.title(spans[2][1]) == "2026-W38")
check("every label carries its range",
      pm.week_span_label(*((spans[0][0],) + spans[0][2:])) == "W1 · 1st-6th Sep"
      and pm.week_span_label(*((spans[4][0],) + spans[4][2:])) == "W5 · 28th-30th Sep")
check("a one-day tail is not a range",
      pm.week_span_label(5, date(2026, 8, 31), date(2026, 8, 31)) == "W5 · 31st Aug")
# a month that starts on a Monday has no straddle at either end
_feb = pm.period_for("monthly", date(2026, 6, 15))
check("a month can start clean",
      pm.month_week_spans(_feb)[0][2] == date(2026, 6, 1))

# ── bars: None is not zero ──────────────────────────────────────────────────
rows = [("W1 · 1st-6th Sep", None), ("W2 · 7th-13th Sep", 387),
        ("W3 · 14th-20th Sep", 79), ("W4 · 21st-27th Sep", 0)]
bars = pm.done_span_lines(rows)
check("a week with no note says so", bars[0] == "- W1 · 1st-6th Sep · no note", bars)
check("the biggest known week gets the full bar", bars[1].count("▇") == 7, bars)
check("a real zero is a zero", bars[3] == "- W4 · 21st-27th Sep 0", bars)
check("the total counts only what is known", bars[-1] == "**Month: 466**", bars)

# ── moods by week ───────────────────────────────────────────────────────────
ml = pm.mood_span_lines([("W1 · 1st-6th Sep", None),
                         ("W2 · 7th-13th Sep", 3.66),
                         ("W3 · 14th-20th Sep", 2.7)])
check("a week with no mood is left out", len(ml) == 2, ml)
check("the face follows the average", ml[0].endswith("🙂 3.7"), ml)

# ── top 5 of the month ──────────────────────────────────────────────────────
items = []
for d in range(1, 26):                      # a win every day, 25 of them
    items.append((date(2026, 9, d), f"{d:02d}:00", "🟢", f"win {d}"))
week_of = {}
for n, _wp, a, b in spans:
    for i in range((b - a).days + 1):
        week_of[a + __import__("datetime").timedelta(days=i)] = n
top = pm.top_entries(items, lambda d: week_of.get(d, 0))
check("five a kind", len(top) == 5, top)
check("one from every week, not five from the last",
      sorted({week_of[it[0]] for it in top}) == [1, 2, 3, 4], top)
check("the newest of each week is the one that survives",
      {it[3] for it in top} == {"win 25", "win 20", "win 13", "win 6", "win 24"},
      [it[3] for it in top])
# fewer than five: everything survives, nothing is invented
few = [(date(2026, 9, 2), "09:00", "💭", "a"), (date(2026, 9, 3), "09:00", "💭", "b")]
check("a quiet month keeps what it has",
      len(pm.top_entries(few, lambda d: week_of.get(d, 0))) == 2)

# ── reading a sealed week back ──────────────────────────────────────────────
WK = pm.period_for("weekly", date(2026, 9, 14))
wdoc = ps.parse_sections(pm.render_template(
    pe._load_template("weekly"), {"breadcrumbs": "C", "daylinks": "- d"}))
ps.set_body(wdoc, pm.SEC_WBARS, pm.ind(["- Mon ▇ 12", "- Tue ▇ 5",
                                        "- Wed ▇▇▇▇▇▇▇ 60", "- Thu ▇ 2",
                                        "- Fri 0", "- Sat 0", "- Sun 0"]),
            pm.SEC_WK_STATS)
pe._set_headed(wdoc, pm.SEC_COMPLETED, "79 · 🔴 ▼ 308 (−80%)",
               pm.ind(["- 🗂 📌CTA · 13", "- 🗂 💰Money · 8"]), pm.SEC_WK_STATS)
ps.set_body(wdoc, pm.SEC_TOP_LIST, ["\t- 📌CTA · 13 done · 14 added"],
            pm.SEC_WK_STATS)
ps.set_body(wdoc, pm.SEC_TOP_TASKS, ["\t- Commute · 4×", "\t- Ship it"],
            pm.SEC_WK_STATS)
idx = {("weekly", pm.title_key(WK)): {"id": "W", "projectId": "P",
                                      "content": ps.serialize_sections(wdoc)}}
st = pe._week_stats_of(idx, WK)
check("bars read back as dates", st["per_day"][date(2026, 9, 16)] == 60, st["per_day"])
check("the whole week reads back", sum(st["per_day"].values()) == 79, st["per_day"])
check("the breakdown reads back", st["by_proj"] == {"📌CTA": 13, "💰Money": 8}, st)
check("top lists read back", st["top_lists"] == {"📌CTA": (13, 14)}, st)
check("top tasks read back", st["top_tasks"] == {"Commute": 4, "Ship it": 1}, st)
check("a week with no note is None", pe._week_stats_of({}, WK) is None)

# the PRE-2026-09-17 weekly layout still gives up its numbers
LEGACY = """C
---
##### 🔥 Top list: 🌅 Routines · 186 done · 335 added

##### 🚀 Top tasks: 🌆 Shutdown, Before wrap up

##### 📈 Stats
\t\t- Mon ▇▇▇ 44
\t\t- Tue ▇▇▇▇ 55

##### ✅ Completed: 387 · 🟢 284 tasks ahead of last week
\t\t- 🗂 🌅 Routines · 186
"""
W37 = pm.period_for("weekly", date(2026, 9, 7))
lst = pe._week_stats_of({("weekly", pm.title_key(W37)):
                         {"id": "L", "projectId": "P", "content": LEGACY}}, W37)
check("legacy bars read", lst["per_day"][date(2026, 9, 8)] == 55, lst["per_day"])
check("legacy breakdown reads", lst["by_proj"] == {"🌅 Routines": 186}, lst)
check("legacy top list reads", lst["top_lists"] == {"🌅 Routines": (186, 335)}, lst)
check("legacy top tasks read",
      lst["top_tasks"] == {"🌆 Shutdown": 1, "Before wrap up": 1}, lst)

# ── the month total sums only its own days ──────────────────────────────────
data = {WK.start: st, W37.start: lst}
check("a straddling week contributes only this month's days",
      pe._month_done({W37.start: lst}, SEP) == 99, pe._month_done({W37.start: lst}, SEP))
check("an unreadable month reports nothing, not zero",
      pe._month_done({WK.start: None}, SEP) is None)

# ── the head: weeks linked, other tiers untouched ───────────────────────────
mdoc = ps.parse_sections(pm.render_template(
    pe._load_template("monthly"),
    {"breadcrumbs": "C", "weeklinks": "\n".join(pe._week_links(SEP, idx))}))
def _wk_bullets(lines):
    return [l for l in lines if l.startswith("- W") or l.startswith("- [W")]


lead = mdoc.lead
check("one bullet per week", len(_wk_bullets(lead)) == 5, lead)
check("the week that has a note is linked",
      any(l.startswith("- [W3 · 14th-20th Sep](") for l in lead), lead)
check("the rest are plain", "- W1 · 1st-6th Sep" in lead, lead)
before = _wk_bullets(lead)
pe._compose_lead(mdoc, SEP, idx, refetch=False)
# line 0 is the crumb, which the template render faked as "C"
check("mint and refresh agree on the block", _wk_bullets(mdoc.lead) == before,
      (before, mdoc.lead))
pe._compose_lead(mdoc, SEP, idx, refetch=False)
check("refresh never doubles the block",
      len(_wk_bullets(mdoc.lead)) == 5
      and sum(1 for l in mdoc.lead if l.strip() == "---") == 2, mdoc.lead)
check("weekly notes get day links, not week links",
      pe._week_links(WK, idx) == [] and pe._day_links(SEP, idx) == [])

# ── the layout guard ────────────────────────────────────────────────────────
old_shape = ps.parse_sections("C\n---\n##### 🎯 Month goal\n- [ ]\n"
                              "##### 📈 Stats\n_(pending)_\n")
pe._fill_monthly(old_shape, SEP, idx)
check("a note minted under the old skeleton is left alone",
      "_(pending)_" in ps.serialize_sections(old_shape)
      and "Weekly Completed" not in ps.serialize_sections(old_shape))

print(f"monthly note: {P} passed, {F} failed")
sys.exit(1 if F else 0)
