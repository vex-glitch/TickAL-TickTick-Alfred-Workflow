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
fixed_e = pm.journal_fixed("evening", {"goal": "Ship the thing"})
check("14.fixed-evening",
      [k for k, _q in fixed_e] == ["free", "goal", "money", "rating"]
      and "Ship the thing" in fixed_e[1][1])
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
      and "\t\tA: mine" in merged)                  # indent survives
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
check("16.harvest", len(h) == 4 and h[0][1] == "🏆")
check("16.mood-last", pm.day_mood(nb) == (4, "tired but good"))
check("16.delta", pm.fmt_delta(43, 37) == "+6" and pm.fmt_delta(37, 43) == "-6"
      and pm.fmt_delta(680, 745, "duration") == "-1h 05m"
      and pm.fmt_delta(3.8, 3.4, "float") == "+0.4"
      and pm.fmt_delta(43, None) is None)
check("16.statline", pm.stat_line("Completed", "43", "+6") == "- Completed: 43 (Δ +6)"
      and pm.STAT_RE.match("- Completed: 43 (Δ +6)"))
check("16.entryline", pm.make_entry("win", "shipped", "14:32")
      == "- 14:32 🏆 shipped"
      and pm.ENTRY_RE.match("- 14:32 🏆 shipped"))

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
    for a in anchors:
        check(f"18.anchor[{kind}:{a}]", f"### {a}\n" in tpl or tpl.endswith(f"### {a}"),
              f"missing in {kind}.md")
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
    (date(2026, 7, 9), "14:32", "🏆", "Shipped"),
    (date(2026, 7, 10), "09:11", "🏆", "Won"),
    (date(2026, 7, 9), "20:00", "💭", "Hmm"),
    (date(2026, 7, 9), "21:00", "😊", "4 · ok"),    # moods excluded
])
check("19.entries-grouped",
      ents == ["\t\t**🏆 Wins**", "\t\t\t- Won · Fri 09:11",
               "\t\t\t- Shipped · Thu 14:32",
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
print(f"periodic suite: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
