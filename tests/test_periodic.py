#!/usr/bin/env python3
"""Unit suite for the periodic-notes pure engine.

Covers periodic_sections + periodic_model only: no I/O beyond reading the
shipped template files. Run:

    python3 tests/test_periodic.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_sections as ps
import focus_blocks as fb
import periodic_model as pm

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


# ── 1. round-trip corpus ─────────────────────────────────────────────────────
CORPUS = [
    "",
    "plain prose\nno headers at all\n",
    "### 💰 Money\n- 485 · x\n**Total = 485**",
    "lead line\n\n### 🧭 Nav\nlinks  \n\n### 💰 Money\n**Total = 0**\n",
    "trailing spaces  \n### A\nbody  \n\n\n### B\n",
    "\n\n### only header",
]
for i, c in enumerate(CORPUS):
    check(f"1.roundtrip[{i}]", ps.serialize_sections(ps.parse_sections(c)) == c,
          repr(c))

# ── 2. filler isolation ──────────────────────────────────────────────────────
note = ("crumb ◀ x ▶\n\n### 🧭 Nav\nnav stuff\n\n### 📓 Notes\n- 09:00 💭 hi\n"
        "\n### 💰 Money\n- 100 · a\n**Total = 100**\n")
doc = ps.parse_sections(note)
ps.set_body(doc, pm.SEC_MONEY, ["- 100 · a", "- 50 · b", "**Total = 150**"])
out = ps.serialize_sections(doc)
head_orig = note.split("### 💰 Money")[0]
check("2.isolation-head", out.split("### 💰 Money")[0] == head_orig)
check("2.isolation-body", "- 50 · b" in out and "**Total = 150**" in out)

# ── 3. deleted header → silent skip ──────────────────────────────────────────
doc = ps.parse_sections("### 🧭 Nav\nx\n")
check("3.find-none", ps.find(doc, pm.SEC_MONEY) is None)
before = ps.serialize_sections(doc)
check("3.setbody-false", ps.set_body(doc, pm.SEC_MONEY, ["- 1"]) is False)
check("3.unchanged", ps.serialize_sections(doc) == before)

# ── 4. renamed header untouched ──────────────────────────────────────────────
doc = ps.parse_sections("### 💰 Monies\n- 5 · x\n")
check("4.renamed", ps.set_body(doc, pm.SEC_MONEY, ["- 9"]) is False
      and "- 5 · x" in ps.serialize_sections(doc))

# ── 5. CRLF normalization only ───────────────────────────────────────────────
crlf = "### 📓 Notes\r\n- 09:00 💭 hi\r\n"
doc = ps.parse_sections(crlf)
out = ps.serialize_sections(doc)
check("5.crlf", "\r" not in out and "- 09:00 💭 hi" in out)

# ── 6. empty / lead-only / prose-only ────────────────────────────────────────
for i, c in enumerate(["", "\n", "just prose\nlines\n"]):
    d = ps.parse_sections(c)
    check(f"6.leadonly[{i}]", d.sections == [] and ps.serialize_sections(d) == c)

# ── 7. money zoo ─────────────────────────────────────────────────────────────
zoo = {"485": 485.0, "1,250.50": 1250.5, "1.250,50": 1250.5, "€485": 485.0,
       "485 kn": 485.0, "-40": -40.0, "1.250": 1250.0, "0.50": 0.5}
for s, want in zoo.items():
    check(f"7.amt[{s}]", pm.parse_amount(s) == want,
          f"{pm.parse_amount(s)} != {want}")
check("7.amt-garbage", pm.parse_amount("garbage") is None)
check("7.entry-canon", pm.parse_money_entry("- 485 · coaching") == (485.0, "coaching"))
check("7.entry-bare", pm.parse_money_entry("- 485") == (485.0, ""))
check("7.entry-hyphen", pm.parse_money_entry("- 485 - coffee") == (485.0, "coffee"))
check("7.entry-garbage", pm.parse_money_entry("- garbage · x") is None)
check("7.entry-not-total", pm.parse_money_entry("**Total = 485**") is None)
check("7.entry-not-checkbox", pm.parse_money_entry("- [ ] 485 thing") is None)
check("7.entry-not-dayline", pm.parse_money_entry("- Sat 11 Jul 2026 • 485") is None)
body = ["\t\t- 100 · a", "- 50,50 · b", "**Total = 0**"]
new = pm.recompute_money_body(body)
check("7.retotal", new[-1] == "\t\t- **Total = 150.50**", new[-1])
check("7.retotal-idem", pm.recompute_money_body(new) == new)
check("7.total-bullet-not-entry",
      pm.parse_money_entry("\t\t- **Total = 310**") is None)
check("7.indented-entry", pm.parse_money_entry("\t\t- 310") == (310.0, ""))
check("7.fmt", pm.fmt_amount(485.0) == "485" and pm.fmt_amount(485.5) == "485.50")

# ── 8. weekly money EXACT contract ───────────────────────────────────────────
line = pm.money_day_line(date(2026, 7, 11), 485)
check("8.exact", line == "- Sat 11 Jul 2026 • 485", line)
m = pm.WEEK_DAY_RE.match(line)
check("8.reparse", m and m.group("dow") == "Sat" and m.group("amt") == "485")
check("8.single-digit", pm.money_day_line(date(2026, 7, 5), 0)
      == "- Sun 5 Jul 2026 • 0")
tm = pm.MONEY_TOTAL_RE.match("**Total = 3110**")
check("8.total-re", tm and tm.group("amt") == "3110")

# ── 9. straddle week never double-counts ─────────────────────────────────────
# W27-2026 = Mon Jun 29 … Sun Jul 5
sums = {date(2026, 6, 29): 100, date(2026, 6, 30): 100,
        date(2026, 7, 1): 10, date(2026, 7, 5): 10, date(2026, 7, 20): 5}
w27 = pm.period_for("weekly", date(2026, 7, 1))
check("9.week-span", w27.start == date(2026, 6, 29) and w27.end == date(2026, 7, 5))
check("9.week-sum", pm.sum_in_period(sums, w27) == 220)
jul = pm.period_for("monthly", date(2026, 7, 1))
check("9.month-sum", pm.sum_in_period(sums, jul) == 25)

# ── 10. ISO week / year edges ────────────────────────────────────────────────
check("10.w53", pm.title(pm.period_for("weekly", date(2026, 12, 28))) == "2026-W53")
check("10.jan1-week", pm.title(pm.period_for("weekly", date(2027, 1, 1))) == "2026-W53")
started = pm.periods_started_by(date(2027, 1, 1))   # a Friday
kinds = {p.kind for p in started}
check("10.jan1-starts", kinds == {"daily", "monthly", "quarterly", "yearly"}, kinds)
check("10.titles", pm.title(pm.period_for("daily", date(2026, 7, 11))) == "2026-07-11 · Sat"
      and pm.title(pm.period_for("monthly", date(2026, 7, 11))) == "2026-07 July"
      and pm.title(pm.period_for("quarterly", date(2026, 7, 11))) == "2026-Q3"
      and pm.title(pm.period_for("yearly", date(2026, 7, 11))) == "2026")
check("10.parse-title", pm.parse_daily_title("2026-07-11 · Sat") == date(2026, 7, 11)
      and pm.parse_daily_title("2026-99-99 · Xxx") is None)

# ── 11. quarter boundary + week-parent convention ────────────────────────────
check("11.oct1", {p.kind for p in pm.periods_started_by(date(2026, 10, 1))}
      >= {"daily", "monthly", "quarterly"})
wk = pm.period_for("weekly", date(2026, 4, 2))      # week of Mon Mar 30
par = pm.parents(wk)
check("11.week-parent-monday", par[0].start == date(2026, 3, 1)
      and par[1].start == date(2026, 1, 1),
      [str(p.start) for p in par])

# ── 12. mint-targets table ───────────────────────────────────────────────────
check("12.monday", {p.kind for p in pm.periods_started_by(date(2026, 7, 13))}
      == {"daily", "weekly"})
check("12.aug1", {p.kind for p in pm.periods_started_by(date(2026, 8, 1))}
      == {"daily", "monthly"})
check("12.tuesday", {p.kind for p in pm.periods_started_by(date(2026, 7, 14))}
      == {"daily"})
check("12.prevnext", pm.title(pm.prev_period(pm.period_for("weekly", date(2026, 7, 11))))
      == "2026-W27"
      and pm.title(pm.next_period(pm.period_for("monthly", date(2026, 12, 5))))
      == "2027-01 January")

# ── 13. Today merge semantics (dedupe vs ALL lines) ────────────────────
TID_A, TID_B = "a" * 24, "b" * 24
body = [f"- [x] [Done thing](https://ticktick.com/webapp/#p/p1/tasks/{TID_A}) ",
        "- [ ] freehand box",
        "user prose line"]
merged, added = pm.merge_checkboxes(body, [("p1", TID_A, "Done thing"),
                                           ("p2", TID_B, "New thing")])
check("13.dedupe-checked", added == 1 and sum(TID_A in ln for ln in merged) == 1)
check("13.user-survives", "- [ ] freehand box" in merged and "user prose line" in merged)
check("13.checkstate", merged[0].startswith("- [x]"))
check("13.checked-linked", pm.checked_linked(merged) == [("p1", TID_A)])
merged2, added2 = pm.merge_checkboxes(merged, [("p2", TID_B, "New thing")])
check("13.idempotent", added2 == 0 and merged2 == merged)

# ── 14. journal (fixed heads code-owned + routed, pools feed only
# the random tail) ───────────────────────────────────────────────────────────
pool = {"random": [f"R{i}?" for i in range(30)]}
d = date(2026, 7, 11)
p1 = pm.select_prompts(pool, d, "morning")
p2 = pm.select_prompts(pool, d, "morning")
p3 = pm.select_prompts(pool, d, "evening")
check("14.deterministic", p1 == p2 and len(p1) == 3)
check("14.slot-differs", p1 != p3 and len(p3) == 5)
fixed_m = pm.journal_fixed("morning")
check("14.fixed-morning", [k for k, _q in fixed_m] == ["mood", "free", "free"])
fixed_mb = pm.journal_fixed("morning", {"ybridge": "Ship the bridge"})
check("14.fixed-morning-bridge",
      [k for k, _q in fixed_mb] == ["mood", "free", "free", "free"]
      and "Ship the bridge" in fixed_mb[1][1])
fixed_e = pm.journal_fixed("evening", {"goal": "Ship the thing"})
check("14.fixed-evening",                     # bridge FIRST (Vex 2026-09-12)
      [k for k, _q in fixed_e] == ["bridge", "free", "goal", "money",
                                   "rating"]
      and "Ship the thing" in fixed_e[2][1], [k for k, _q in fixed_e])
fixed_w = pm.journal_fixed("weekly", {"goals": "A; B"})
check("14.fixed-weekly", [k for k, _q in fixed_w] == ["highlight", "wgoals"]
      and "A; B" in fixed_w[1][1])
seeded = pm.seed_journal_lines([q for _k, q in fixed_m] + p1)
pairs = pm.journal_pairs(seeded)
check("14.seed-parse", len(pairs) == 6 and all(a == "" for _, _, a, _ in pairs))
seeded[3] = "\t\tA: phone answer"                   # Q2 answered on phone
merged, filled = pm.merge_journal_answers(
    seeded, {1: "mine", 2: "should NOT overwrite", 3: ""})
check("14.phone-wins", filled == 1 and "\t\tA: phone answer" in merged
      and "\t\t- A: mine" in merged, merged)       # indent + shape survive
# a legacy note's plain A-line keeps its plain shape - never half-converted
_old_shape, _f = pm.merge_journal_answers(
    ["\t**Q1 · Old style**", "\t\tA: "], {1: "kept plain"})
check("14.legacy-shape", _f == 1 and _old_shape[1] == "\t\tA: kept plain",
      _old_shape)
check("14.empty-skip", all("should NOT" not in ln for ln in merged))

# ── 15. sparklines ───────────────────────────────────────────────────────────
check("15.zero", pm.spark([0, 0, 0]) == "▁▁▁")
check("15.equal", pm.spark([5, 5, 5]) == "▁▁▁")
check("15.single", pm.spark([7]) == "▄")
check("15.none", pm.spark([1, None, 8]) == "▁·█", pm.spark([1, None, 8]))
ramp = pm.spark([0, 1, 2, 3, 4, 5, 6, 7])
check("15.ramp", ramp[0] == "▁" and ramp[-1] == "█")

# ── 16. harvest / mood / deltas ──────────────────────────────────────────────
nb = ["- 09:12 🏆 closed the deal", "- 10:00 💭 hmm", "- 11:00 😊 3 · meh",
      "- 21:00 😊 4 · tired but good", "not an entry"]
h = pm.harvest_entries(nb)
# a 🏆 written before the 2026-09-12 recolour reads back as the 🟢 it is now
check("16.harvest", len(h) == 4 and h[0][1] == "🟢")
check("16.harvest-new-glyphs",
      [g for _hm, g, _b in pm.harvest_entries(
          ["- 09:00 🟢 win", "- 09:01 🔴 nag", "- 09:02 ❗️ remind"])]
      == ["🟢", "🔴", "❗️"])
check("16.mood-last", pm.day_mood(nb) == (4, "tired but good"))
check("16.delta", pm.fmt_delta(43, 37) == "+6" and pm.fmt_delta(37, 43) == "-6"
      and pm.fmt_delta(680, 745, "duration") == "-1h 05m"
      and pm.fmt_delta(3.8, 3.4, "float") == "+0.4"
      and pm.fmt_delta(43, None) is None)
check("16.statline", pm.stat_line("Completed", "43", "+6") == "- Completed: 43 (Δ +6)"
      and pm.STAT_RE.match("- Completed: 43 (Δ +6)"))
check("16.entryline", pm.make_entry("win", "shipped", "14:32")
      == "- 14:32 🟢 shipped"
      and pm.ENTRY_RE.match("- 14:32 🟢 shipped"))
check("16.entryline-reminder", pm.make_entry("reminder", "bank", "14:32")
      == "- 14:32 ❗️ bank"
      and pm.ENTRY_RE.match("- 14:32 ❗️ bank"))
check("16.entryline-legacy-still-parses",
      bool(pm.ENTRY_RE.match("- 14:32 🏆 shipped"))
      and bool(pm.ENTRY_RE.match("- 14:32 👎 nagged")))

# ── 17. breadcrumb self-heal ─────────────────────────────────────────────────
doc = ps.parse_sections("◀ old · ▲ up · new ▶\n\n### 🧭 Nav\nx\n")
pm.set_breadcrumb(doc, "[◀ 2026-07-10 · Fri](url) · ▲ 2026-W28 · 2026-07-12 · Sun ▶")
check("17.replace", doc.lead[0].startswith("[◀ 2026-07-10")
      and len(doc.lead) == 2)
doc2 = ps.parse_sections("user typed this\n\n### 🧭 Nav\nx\n")
pm.set_breadcrumb(doc2, "◀ a · b ▶")
check("17.insert", doc2.lead[0] == "◀ a · b ▶" and "user typed this" in doc2.lead)
segs = pm.breadcrumb_segments(pm.period_for("daily", date(2026, 7, 11)),
                              lambda p: "URL" if p.kind == "weekly" else None)
crumb = pm.render_breadcrumb(segs)
check("17.render", crumb == "◀ 2026-07-10 · Fri · [▲ 2026-W28](URL) · 2026-07-12 · Sun ▶",
      crumb)

# ── 18. every writer anchor lives in its shipped template ─────────────
for kind, anchors in pm.WRITER_ANCHORS.items():
    tpl_path = os.path.join(ROOT, "src", "periodic_templates", f"{kind}.md")
    tpl = open(tpl_path, encoding="utf-8").read()
    _tdoc = ps.parse_sections(tpl)
    for a in anchors:
        # RESOLVES, rather than "appears as ### a": Vex's 2026-09-12 layout
        # made most anchors bullets, and a few renamed themselves as he
        # dropped emoji - ps.find is the thing every filler actually uses
        check(f"18.anchor[{kind}:{a}]", ps.find(_tdoc, a) is not None,
              f"unreachable in {kind}.md")
    check(f"18.tpl-roundtrip[{kind}]",
          ps.serialize_sections(ps.parse_sections(tpl)) == tpl)

# ── 19. grammars: mood faces, day rating, 💬 merge, 📨 entries,
# vs-last-week chips, day-goal titles ────────────────────────────────────────
check("19.mood-line", pm.mood_line(4, "tired") == "Mood: 🙂 · tired"
      and pm.mood_line(1) == "Mood: 😢")
check("19.rating-line", pm.rating_line(3) == "Day: ★★★"
      and pm.rating_line(9) == "Day: ★★★★★")
qbody = ['> "q" · A', "🌤 16-26°C", "Mood: 🙂 · ok", "Day: ★★★★"]
check("19.quote-mood", pm.quote_mood(qbody) == (4, "ok"))
check("19.quote-rating", pm.quote_rating(qbody) == 4)
mq = pm.merge_quote_body(qbody, '> "new" · B', None)
check("19.merge-quote", mq == ['> "new" · B', "🌤 16-26°C",
                               "Mood: 🙂 · ok", "Day: ★★★★"], mq)
mq2 = pm.merge_quote_body(["_(pending)_"], None, "🌧 10°C")
check("19.merge-pending", mq2 == ["🌧 10°C"], mq2)
nb = pm.set_line_in_body(qbody, pm.MOOD_LINE_RE, pm.mood_line(2))
check("19.set-line-replace", "Mood: 😞" in nb and "Mood: 🙂 · ok" not in nb)
nb2 = pm.set_line_in_body(['> "q" · A'], pm.RATING_LINE_RE, pm.rating_line(5))
check("19.set-line-append", nb2 == ['> "q" · A', "Day: ★★★★★"])
ents = pm.entries_grouped([
    (date(2026, 7, 9), "14:32", "🟢", "Shipped"),
    (date(2026, 7, 10), "09:11", "🟢", "Won"),
    (date(2026, 7, 9), "18:00", "❗️", "Bank"),
    (date(2026, 7, 9), "20:00", "💭", "Hmm"),
    (date(2026, 7, 9), "21:00", "😊", "4 · ok"),    # moods excluded
])
check("19.entries-grouped",
      ents == ["\t\t**🟢 Wins**", "\t\t\t- Won · Fri 09:11",
               "\t\t\t- Shipped · Thu 14:32",
               "\t\t**❗️ Reminders**", "\t\t\t- Bank · Thu 18:00",
               "\t\t**💭 Thoughts**", "\t\t\t- Hmm · Thu 20:00"], ents)
check("19.chip-behind", pm.chip(114, 121) == "🔴 7 tasks behind last week (−6%)")
check("19.chip-ahead", pm.chip(121, 114) == "🟢 7 tasks ahead of last week (+6%)")
check("19.chip-level", pm.chip(5, 5) == "⚪ level with last week")
check("19.chip-zero-prev", pm.chip(10, 0) == "🟢 10 tasks ahead of last week")
check("19.chip-none", pm.chip(10, None) is None)
check("19.goal-titles", pm.goal_titles(
    ["- [ ] [Ship](https://x)", "- plain goal", "_(pending)_", ""])
    == ["Ship", "plain goal"])
check("19.day-goal-title", pm.day_goal_title(
    ["- [x] [Done thing](https://x/y)"]) == "Done thing"
    and pm.day_goal_title(["_(pending)_"]) == "")
check("19.indent", pm.indent(["- a"]) == ["    - a"])

# ── 20. decor engine: --- dividers + # group headers survive fillers,
# data-in-header sections, indented grammars ─────────────────────────────────
DOC = """crumbs
[nav](x)
---

# 🏆 Goals
### 🗓️ Weekly
	- [ ] goal

### ☀️ Daily
	_(pick one)_
---

# ☀️ Today
### ✅ Tasks
		- [ ] [T](https://ticktick.com/webapp/#p/p1/tasks/aaaaaaaaaaaaaaaaaaaaaaaa)

### 💰 Money
		- 310
		- **Total = 310**
---

### 🔥 Top list: old · 1 done
	body
"""
d20 = ps.parse_sections(DOC)
check("20.roundtrip", ps.serialize_sections(d20) == DOC)
check("20.pre-goals", d20.sections[0].pre == ["# 🏆 Goals"],
      d20.sections[0].pre)
check("20.lead-clean", d20.lead == ["crumbs", "[nav](x)", "---", ""], d20.lead)
check("20.pre-group", "# ☀️ Today" in d20.sections[2].pre
      and "---" in d20.sections[2].pre)
ps.set_body(d20, "🗓️ Weekly", ["\t- [ ] new goal"])
out20 = ps.serialize_sections(d20)
check("20.decor-survives", "# ☀️ Today" in out20 and out20.count("---") == 3)
sec20 = ps.find_prefix(d20, "🔥 Top list")
check("20.find-prefix", sec20 is not None and sec20.name.endswith("1 done"))
ps.set_header(sec20, "🔥 Top list: new · 2 done")
check("20.set-header", "### 🔥 Top list: new · 2 done"
      in ps.serialize_sections(d20))
msec20 = ps.find(d20, "💰 Money")
check("20.indented-sum", pm.section_money_sum(msec20.body) == 310.0)
check("20.tasks-swept-tolerant",
      pm.checkbox_tids(ps.find(d20, "✅ Tasks").body)
      == {"aaaaaaaaaaaaaaaaaaaaaaaa": False})
check("20.lead-mood", pm.quote_mood(["crumb", "Mood: 😁 · great"]) == (5, "great"))

# ── report ───────────────────────────────────────────────────────────────────
# ── weekly notes carry their date range (Vex 2026-09-12) ───────────────────
_wk = pm.period_for("weekly", date(2026, 9, 12))
check("weekly name carries the range",
      pm.long_title(_wk) == "2026-W37 • 7th-13th Sep", pm.long_title(_wk))
check("a range crossing a month names both",
      pm.date_range(pm.period_for("weekly", date(2026, 9, 30)))
      == "28th Sep-4th Oct")
check("ordinals: 1st 2nd 3rd 4th",
      [pm._ord(n) for n in (1, 2, 3, 4)] == ["1st", "2nd", "3rd", "4th"])
check("ordinals: the teens are all th",
      [pm._ord(n) for n in (11, 12, 13)] == ["11th", "12th", "13th"])
check("ordinals: 21st 22nd 23rd 31st",
      [pm._ord(n) for n in (21, 22, 23, 31)] == ["21st", "22nd", "23rd", "31st"])
check("the other tiers are unchanged",
      all(pm.long_title(pm.period_for(k, date(2026, 9, 12)))
          == pm.title(pm.period_for(k, date(2026, 9, 12)))
          for k in ("daily", "monthly", "quarterly", "yearly")))
check("the lookup key ignores the range",
      pm.title_key(_wk) == "2026-W37"
      and pm.stable_key("2026-W37 • 7th-13th Sep") == "2026-W37"
      and pm.stable_key("2026-W37") == "2026-W37")
check("a renamed note is still its own period",
      pm.stable_key(pm.long_title(_wk)) == pm.title_key(_wk))

# ── goals on every tier, in Vex's three shapes (2026-09-12) ────────────────
check("every tier has a goal section",
      set(pm.GOAL_SECTION) == {"daily", "weekly", "monthly", "quarterly", "yearly"})
check("goal line: text alone",
      pm.goal_line("Ship the thing") == "- [ ] Ship the thing")
check("goal line: task alone ends in its link",
      pm.goal_line("", "P", "a" * 24, "Onboard").startswith("- [ ] [Onboard](")
      and pm.goal_line("", "P", "a" * 24, "Onboard").count("](") == 1)
_both = pm.goal_line("Ship it", "P", "b" * 24, "Onboard")
check("goal line: text AND task, text first", _both.startswith("- [ ] Ship it · ["), _both)
check("goal line: the link stays last, so the tid still parses",
      pm.checkbox_tids([_both]) == {"b" * 24: False}, _both)
check("goal line: nothing in, nothing out",
      pm.goal_line("") == "" and pm.goal_line(None) == "")
check("goal line: whitespace squeezed",
      pm.goal_line("  Ship   it  ") == "- [ ] Ship it")
check("a link-titled task does not nest in a goal",
      pm.goal_line("x", "P", "c" * 24, "[Money](kmtrigger://m)").count("](") == 1)

# ── 20. Vex's 2026-09-12 round: habits due today, clocks, ordering ─────────
check("20.habit-weekly-byday",
      pm.habit_due("RRULE:FREQ=WEEKLY;BYDAY=SU", 20260913, date(2026, 9, 13))
      and not pm.habit_due("RRULE:FREQ=WEEKLY;BYDAY=SU", 20260913,
                           date(2026, 9, 12)))
check("20.habit-daily-every-day",
      pm.habit_due("RRULE:FREQ=DAILY;INTERVAL=1", 20260913, date(2026, 9, 12)))
check("20.habit-daily-interval",
      pm.habit_due("RRULE:FREQ=DAILY;INTERVAL=7", 20260906, date(2026, 9, 13))
      and not pm.habit_due("RRULE:FREQ=DAILY;INTERVAL=7", 20260906,
                           date(2026, 9, 12)))
check("20.habit-unknown-rule-shows",           # never hide on a parse failure
      pm.habit_due("", None, date(2026, 9, 12))
      and pm.habit_due("RRULE:FREQ=MONTHLY", None, date(2026, 9, 12)))
check("20.stamp", pm.unpack_stamp(20260913) == date(2026, 9, 13)
      and pm.unpack_stamp(None) is None and pm.unpack_stamp("x") is None)
check("20.clock-allday", pm.clock("2026-09-13T05:30:00.000+0000", True) == "")
check("20.timed-title", pm.timed_title("T", "09:00") == "T · 09:00"
      and pm.timed_title("T", "") == "T")
_a = fb.make_line("P", "a" * 24, pm.timed_title("Late", "19:00")).raw
_b = fb.make_line("P", "b" * 24, pm.timed_title("Early", "07:30")).raw
_c = fb.make_line("P", "c" * 24, "Untimed").raw
check("20.sort-by-clock", pm.sort_checkboxes([_a, _b, _c]) == [_b, _a, _c])
check("20.sort-keeps-other-lines",
      pm.sort_checkboxes(["head", _a, _b]) == ["head", _b, _a])
check("20.sort-noop-under-two", pm.sort_checkboxes([_a]) == [_a])
check("20.timed-line-keeps-its-tid",
      pm.checkbox_tids([_a]) == {"a" * 24: False}, _a)

# ── 21. round 3: mood answers, dedupe, italics (Vex 2026-09-12) ────────────
check("21.answer-mood-bare", pm.answer_mood("😐") == (3, ""))
check("21.answer-mood-note", pm.answer_mood("🙂 · slept badly") == (4, "slept badly"))
check("21.answer-mood-full-line", pm.answer_mood("Mood: 😁") == (5, ""))
check("21.answer-mood-junk",
      pm.answer_mood("nonsense") is None and pm.answer_mood("") is None
      and pm.answer_mood(None) is None)
check("21.question-italic-answer-plain",
      pm.seed_journal_lines(["Q?"]) == ["\t- *Q1 · Q?*", "\t\t- A: "],
      pm.seed_journal_lines(["Q?"]))
_s = pm.seed_journal_lines(["Mood?"])
_m, _f = pm.merge_journal_answers(_s, {1: "😐"})
check("21.italic-round-trip",
      _m[1] == "\t\t- A: 😐" and pm.journal_pairs(_m)[0][2] == "😐", _m)

# ── 22. round 4: mood spacing, stars, money from the journal ──────────────
check("22.mood-space", pm.mood_text(4, "slept badly") == "🙂 slept badly"
      and pm.mood_text(3) == "😐")
check("22.mood-space-round-trip",
      pm.answer_mood(pm.mood_text(4, "slept badly")) == (4, "slept badly"))
check("22.mood-old-separator-still-reads",
      pm.answer_mood("🙂 · slept badly") == (4, "slept badly"))
check("22.stars-from-digit", pm.answer_stars("4") == "★★★★")
check("22.stars-from-stars", pm.answer_stars("★★★") == "★★★")
check("22.stars-refuse", pm.answer_stars("0") == "" and pm.answer_stars("x") == ""
      and pm.answer_stars("") == "" and pm.answer_stars(None) == "")
check("22.stars-cap", pm.answer_stars("9") == "")
check("22.money-no-longer-seeded-daily",
      pm.SEC_MONEY not in pm.WRITER_ANCHORS["daily"]
      and pm.SEC_MONEY in pm.WRITER_ANCHORS["monthly"])

# ── 23. append_body into a BULLET block (Vex 2026-09-12: "I tried adding a
# win, it did nothing") - a Block's .body is a COPY, so the old in-place
# extend filled a throwaway list and still reported success.
_DAILY_TPL = open(os.path.join(ROOT, "src", "periodic_templates",
                               "daily.md")).read()


def _tpl_doc():
    return ps.parse_sections(_DAILY_TPL)


_d = _tpl_doc()
_ok = ps.append_body(_d, pm.SEC_NOTES, [pm.T2 + pm.make_entry("win", "shipped", "10:30")])
_out = ps.serialize_sections(_d)
check("23.entry-lands-in-bullet-notes", _ok and "🟢 shipped" in _out,
      repr(_out[:400]))
check("23.entry-kept-one-tab-under-its-bullet",
      "\n\t- 10:30 🟢 shipped" in _out, repr(_out[:400]))

_d = _tpl_doc()
for _k, _t, _hm in (("win", "one", "10:30"), ("nag", "two", "10:40"),
                    ("thought", "three", "11:05")):
    ps.append_body(_d, pm.SEC_NOTES, [pm.T2 + pm.make_entry(_k, _t, _hm)])
_notes = ps.find(_d, pm.SEC_NOTES).body
check("23.entries-are-siblings-not-nested",
      len(_notes) == 3 and {ps._tabs(l) for l in _notes} == {1},
      repr(_notes))

# appending must not disturb the neighbours or the divider below
check("23.append-left-workbench-intact",
      "- ✅ Tasks" in _out and "---\n#### ☀️ Today" in _out, repr(_out[:400]))

# a section (not a bullet) still appends the old way
_d = ps.parse_sections("### A\n- x\n\n### B\n")
check("23.section-append-still-works",
      ps.append_body(_d, "A", ["- y"])
      and ps.find(_d, "A").body[:2] == ["- x", "- y"],
      repr(ps.find(_d, "A").body))
check("23.missing-name-still-false",
      ps.append_body(_d, "nope", ["- y"]) is False)


# ── 24. day-over-day indicator (Vex 2026-09-12: "small indicator compared to
# the day before?"). Arrows, because 🟢/🔴 now mean Win and Nag.
check("24.delta-up", pm.delta_chip(5, 3) == "▲ 2")
check("24.delta-down", pm.delta_chip(3, 5) == "▼ 2")
check("24.delta-level", pm.delta_chip(4, 4) == "▬")
check("24.delta-money", pm.delta_chip(200, 120, "money") == "▲ 80")
check("24.delta-duration", pm.delta_chip(364, 300, "duration") == "▲ 1h 04m")
check("24.delta-no-baseline",
      pm.delta_chip(3, None) is None and pm.delta_chip(None, 3) is None)
check("24.delta-avoids-the-entry-glyphs",
      all(g not in (pm.delta_chip(5, 3) + pm.delta_chip(3, 5))
          for g in ("🟢", "🔴")))

# ── 25. the sweep never completes an occurrence twice (2026-09-13: the 09:34
# refresh re-completed Rise and shine, Startup and Self Care an hour after
# they were done, eating TOMORROW's occurrences - a repeating task keeps its
# id and rolls forward, so a ticked line points at the next occurrence)
_loc = lambda s: s[:10]
_D, _T = date(2026, 9, 13), date(2026, 9, 14)
_rep = "RRULE:FREQ=DAILY;INTERVAL=1"
check("25.plain-open-task-completes",
      pm.sweep_verdict({"status": 0, "dueDate": "2026-09-13T08:00"}, _D, _loc) == "complete")
check("25.already-completed-is-left-alone",
      pm.sweep_verdict({"status": 2}, _D, _loc) == "done")
check("25.repeating-still-on-its-day-completes (ticked in the note first)",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep,
                        "startDate": "2026-09-13T04:30"}, _D, _loc) == "complete")
check("25.THE-BUG: repeating already rolled to tomorrow is NOT completed again",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep,
                        "startDate": "2026-09-14T04:30"}, _D, _loc) == "done")
check("25.a-Tomorrow-line-completes-tomorrows-occurrence",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep,
                        "startDate": "2026-09-14T04:30"}, _T, _loc) == "complete")
check("25.a-Tomorrow-line-rolled-past-tomorrow-is-left-alone",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep,
                        "startDate": "2026-09-15T04:30"}, _T, _loc) == "done")
check("25.dueDate-counts-when-there-is-no-startDate",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep,
                        "dueDate": "2026-09-14T04:30"}, _D, _loc) == "done")
check("25.an-undated-repeating-task-still-completes",
      pm.sweep_verdict({"status": 0, "repeatFlag": _rep}, _D, _loc) == "complete")
check("25.a-plain-task-dated-later-is-not-blocked (not a repeat)",
      pm.sweep_verdict({"status": 0, "dueDate": "2026-09-20T08:00"}, _D, _loc) == "complete")

# ── 26. ticks follow TickTick (Vex 2026-09-13: completing a task in TickTick
# never ticked its line in the daily note, "even when I refresh")
_loc = lambda s: s[:10]
_D, _T = date(2026, 9, 13), date(2026, 9, 14)
_recs = [
    {"id": "PLAIN", "completedTime": "2026-09-13T09:00"},                        # plain task
    {"id": "COPY1", "repeatTaskId": "SERIES", "startDate": "2026-09-13T04:30"},  # today's occurrence
    {"id": "COPY2", "repeatTaskId": "LATER", "startDate": "2026-09-14T04:30"},   # tomorrow's occurrence
]
check("26.a-plain-completed-task-counts", "PLAIN" in pm.done_tids_for(_recs, _D, _loc))
check("26.a-repeating-task-counts-through-its-copy",
      "SERIES" in pm.done_tids_for(_recs, _D, _loc)
      and "COPY1" not in pm.done_tids_for(_recs, _D, _loc))
check("26.a-copy-counts-only-for-its-own-day",
      "LATER" not in pm.done_tids_for(_recs, _D, _loc)
      and "LATER" in pm.done_tids_for(_recs, _T, _loc)
      and "SERIES" not in pm.done_tids_for(_recs, _T, _loc))
_u = "https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/"
_ids = {"PLAIN": "a" * 24, "SERIES": "b" * 24, "OPEN": "c" * 24}
_body = [f"\t- [ ] [Plain · 09:00]({_u}{_ids['PLAIN']}) ",
         f"\t- [ ] [Startup · 06:30]({_u}{_ids['SERIES']}) ",
         f"\t- [ ] [Still open]({_u}{_ids['OPEN']}) ",
         f"\t- [x] [Ticked by hand]({_u}{'d' * 24}) "]
_nb, _hit = pm.tick_lines(_body, {_ids["PLAIN"], _ids["SERIES"]})
check("26.completed-lines-get-ticked", _nb[0].startswith("\t- [x] [Plain")
      and _nb[1].startswith("\t- [x] [Startup"), _nb)
check("26.open-lines-stay-open", _nb[2].startswith("\t- [ ] [Still open"), _nb)
check("26.a-hand-tick-is-never-taken-back", _nb[3] == _body[3], _nb)
check("26.reports-what-it-ticked", sorted(_hit) == sorted([_ids["PLAIN"], _ids["SERIES"]]), _hit)
check("26.a-bracket-in-the-title-is-not-mistaken-for-the-box",
      pm.tick_lines([f"\t- [ ] [Buy [2] cables]({_u}{_ids['PLAIN']}) "], {_ids["PLAIN"]})[0][0]
      == f"\t- [x] [Buy [2] cables]({_u}{_ids['PLAIN']}) ")

print(f"periodic suite: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
