"""test_journal_pools.py - the daily journal redesign (Vex 2026-09-24).

Set prompts: morning mood, bridge echo, goal check, FORECAST, mind; evening
bridge, highlight, tomorrow's goal, daily goal, KR (when planned), monthly
objectives (when any), forecast check, money, rating, mind.
Random block: six prompts, two per category; morning = prepare, people,
perspective every day; evening = three of six categories, looping one step a
day; Friday evening = one chain, in order. [person] filled from the People
list, family weighted, never the same name two days running. The quote line
comes from the local Stoic pool, no network.

Pure: HOME is a temp dir, nothing real is touched.
"""
import os
import sys
import tempfile
import re
from datetime import date, timedelta

_TMP = tempfile.mkdtemp(prefix="tickal_jp_")
os.environ["HOME"] = _TMP
os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import periodic_model as pm      # noqa: E402
import periodic_journal as pj    # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


# ── 1. the loader: category sections and chain blocks ────────────────────────
SAMPLE = """# comment
## prepare
- P one?
- P two?
- P three?

## control
- C one?
- C two?
### chain: worry sort
1. W step one
2. W step two
3. W step three
- W step four (a bullet is a step too)

## open
- O one?
### chain: repair
1. R one
2. R two
"""
parsed = pj._parse(SAMPLE)
check("1.sections", list(parsed["sections"]) == ["prepare", "control", "open"], parsed)
check("1.prompts", parsed["sections"]["prepare"] == ["P one?", "P two?", "P three?"]
      and parsed["sections"]["control"] == ["C one?", "C two?"], parsed["sections"])
chains = parsed["chains"]
check("1.chains", [(c["category"], c["name"], len(c["prompts"])) for c in chains]
      == [("control", "worry sort", 4), ("open", "repair", 2)], chains)
check("1.chain-order", chains[0]["prompts"][0] == "W step one" and chains[0]["prompts"][3].startswith("W step four"))
legacy = pj._parse("## random\n- A?\n- B?\n## constants\n- K?\n")
check("1.legacy-random", legacy["sections"].get("random") == ["A?", "B?"]
      and legacy["sections"].get("constants") == ["K?"], legacy)

# user override wins per SECTION, a missing or empty user section falls back
_repo, _user = pj.REPO_DIR, pj.USER_DIR
pj.REPO_DIR = os.path.join(_TMP, "repo"); pj.USER_DIR = os.path.join(_TMP, "user")
os.makedirs(pj.REPO_DIR); os.makedirs(pj.USER_DIR)
with open(os.path.join(pj.REPO_DIR, "morning.md"), "w", encoding="utf-8") as f:
    f.write(SAMPLE)
with open(os.path.join(pj.USER_DIR, "morning.md"), "w", encoding="utf-8") as f:
    f.write("## prepare\n- USER one?\n- USER two?\n## control\n")
pool = pj.load_pool("morning")
check("1.override-section", pool["categories"]["prepare"] == ["USER one?", "USER two?"], pool["categories"])
check("1.override-fallback", pool["categories"]["control"] == ["C one?", "C two?"], pool["categories"])
check("1.random-compat", sorted(pool["random"]) == sorted(["USER one?", "USER two?", "C one?", "C two?", "O one?"]), pool["random"])
check("1.chains-kept", [c["name"] for c in pool["chains"]] == ["worry sort", "repair"], pool["chains"])
pj.REPO_DIR, pj.USER_DIR = _repo, _user

# ── 2. the shipped pools ─────────────────────────────────────────────────────
MP, EP = pj.load_pool("morning"), pj.load_pool("evening")
check("2.morning-categories", list(MP["categories"]) == list(pm.MORNING_CATEGORIES), list(MP["categories"]))
check("2.evening-categories", list(EP["categories"]) == list(pm.EVENING_CATEGORIES), list(EP["categories"]))
thin = {c: len(v) for c, v in {**MP["categories"], **EP["categories"]}.items() if len(v) < 10}
check("2.pools-not-thin", not thin, thin)
check("2.evening-chains", len(EP["chains"]) >= 4 and EP["chains"][0]["name"] == "worry sort"
      and len(EP["chains"][0]["prompts"]) == 7, [(c["name"], len(c["prompts"])) for c in EP["chains"]])
DASH = re.compile("[\\u2013\\u2014]")     # written as escapes: the file itself must pass the scan
alltxt = [q for p in (MP, EP) for v in p["categories"].values() for q in v] \
    + [q for p in (MP, EP) for c in p["chains"] for q in c["prompts"]]
check("2.no-dashes", not any(DASH.search(q) for q in alltxt), [q for q in alltxt if DASH.search(q)][:3])
hits = [q for q in alltxt if pm.journal_key(q) != "free"]
check("2.no-pool-prompt-is-fixed", not hits, hits)
check("2.kinder-morning-gone", not any("kinder" in q for q in alltxt))
check("2.vex-prompts-in", any(q.startswith("What is the one obstacle most likely") for q in MP["categories"]["prepare"])
      and any(q.startswith("Where did I fall short today?") for q in EP["categories"]["review"])
      and any("[person]" in q for q in MP["categories"]["people"]))
WP = pj.load_pool("weekly")
check("2.weekly-categories", list(WP["categories"]) == list(pm.WEEKLY_CATEGORIES)
      and all(len(v) >= 10 for v in WP["categories"].values()) and not WP["chains"], {k: len(v) for k, v in WP["categories"].items()})
MOP = pj.load_pool("monthly")
check("2.monthly-categories", list(MOP["categories"]) == list(pm.MONTHLY_CATEGORIES)
      and all(len(v) >= 10 for v in MOP["categories"].values()) and not MOP["chains"], {k: len(v) for k, v in MOP["categories"].items()})
check("2.monthly-no-pool-prompt-is-fixed", not [q for v in MOP["categories"].values() for q in v if pm.journal_key(q) != "free"])
check("2.monthly-no-dashes", not any(DASH.search(q) for v in MOP["categories"].values() for q in v))
check("2.weekly-vex-prompts-in", any(q.startswith("Read your last seven days of entries") for q in WP["categories"]["retrospect"])
      and any(q.startswith("Write next week's intention in a single sentence") for q in WP["categories"]["priorities"]))
QP = pj.load_quotes()
check("2.quotes-pool", len(QP["stoic"]) >= 300 and len(QP["others"]) >= 500
      and all(a and q for q, a in QP["stoic"]), (len(QP.get("stoic", [])), len(QP.get("others", []))))
check("2.quotes-no-dash", not any(DASH.search(q + a) for q, a in QP["stoic"] + QP["others"]))

# ── 3. the morning draw: two per category, every category, cycling ───────────
EPOCH = pm.POOL_EPOCH
d0 = EPOCH
m0 = pm.select_prompts(MP, d0, "morning")
check("3.six", len(m0) == 6, m0)
cats = pm.journal_categories("morning", d0)
check("3.all-three", cats == list(pm.MORNING_CATEGORIES), cats)
by_cat = {c: MP["categories"][c] for c in pm.MORNING_CATEGORIES}
check("3.two-per-category", all(sum(1 for q in m0 if q in by_cat[c]) == 2 for c in pm.MORNING_CATEGORIES)
      and [c for c in pm.MORNING_CATEGORIES for _ in range(2)]
      == [next(c for c in pm.MORNING_CATEGORIES if q in by_cat[c]) for q in m0], m0)
check("3.deterministic", pm.select_prompts(MP, d0, "morning") == m0)
n = min(len(v) for v in by_cat.values()) // 2
seen = []
for i in range(n):
    seen += pm.select_prompts(MP, d0 + timedelta(days=i), "morning")
check("3.no-repeat-within-cycle", len(seen) == len(set(seen)), f"{len(seen)} vs {len(set(seen))}")
old = pm.select_prompts({"random": [f"R{i}?" for i in range(30)]}, date(2026, 7, 11), "morning")
check("3.legacy-pool-still-samples", len(old) == 3, old)

# ── 4. the evening draw: three categories looping, Friday = a chain ──────────
def _cats(d):
    return pm.journal_categories("evening", d)
mon = date(2026, 9, 28)        # Monday
check("4.monday-three", len(_cats(mon)) == 3 and all(c in pm.EVENING_CATEGORIES for c in _cats(mon)), _cats(mon))
tue = mon + timedelta(days=1)
check("4.loops-one-step", _cats(tue)[:2] == _cats(mon)[1:] and _cats(tue) != _cats(mon), (_cats(mon), _cats(tue)))
fri = date(2026, 9, 25)
check("4.friday-chain-night", _cats(fri) == [] and pm.is_chain_night("evening", fri)
      and not pm.is_chain_night("evening", mon) and not pm.is_chain_night("morning", fri))
thu2, sat2 = date(2026, 10, 1), date(2026, 10, 3)       # around the second Friday
check("4.friday-does-not-advance", _cats(sat2)[:2] == _cats(thu2)[1:], (_cats(thu2), _cats(sat2)))
e_mon = pm.select_prompts(EP, mon, "evening")
check("4.six", len(e_mon) == 6, e_mon)
ecat = {c: EP["categories"][c] for c in pm.EVENING_CATEGORIES}
check("4.two-per-drawn-category",
      all(sum(1 for q in e_mon if q in ecat[c]) == 2 for c in _cats(mon))
      and all(sum(1 for q in e_mon if q in ecat[c]) == 0 for c in pm.EVENING_CATEGORIES if c not in _cats(mon)), e_mon)
f1 = pm.select_prompts(EP, fri, "evening")
check("4.first-friday-is-the-worry-sort", f1 == EP["chains"][0]["prompts"], f1)
f2 = pm.select_prompts(EP, fri + timedelta(days=7), "evening")
check("4.next-friday-next-chain", f2 == EP["chains"][1]["prompts"], f2)
fN = pm.select_prompts(EP, fri + timedelta(days=7 * len(EP["chains"])), "evening")
check("4.chains-wrap", fN == EP["chains"][0]["prompts"])
# a category appears on 3 of 6 evenings: its pool cycles without repeats
review_seen = []
d = EPOCH                      # from position 0: one full cycle, no repeat
while len(review_seen) < len(ecat["review"]) - 1:
    if "review" in _cats(d):
        review_seen += [q for q in pm.select_prompts(EP, d, "evening") if q in ecat["review"]]
    d += timedelta(days=1)
check("4.category-cycles-no-repeat", len(review_seen) == len(set(review_seen)), f"{len(review_seen)} vs {len(set(review_seen))}")
wk = pm.select_prompts(WP, pm.WEEK_EPOCH, "weekly")
check("4.weekly-ten", len(wk) == 10 and len(set(wk)) == 10, wk)
wcat = {c: WP["categories"][c] for c in pm.WEEKLY_CATEGORIES}
check("4.weekly-two-per-category", all(sum(1 for q in wk if q in wcat[c]) == 2 for c in pm.WEEKLY_CATEGORIES)
      and [c for c in pm.WEEKLY_CATEGORIES for _ in range(2)] == [next(c for c in pm.WEEKLY_CATEGORIES if q in wcat[c]) for q in wk], wk)
wk2 = pm.select_prompts(WP, pm.WEEK_EPOCH + timedelta(days=7), "weekly")
check("4.weekly-next-week-differs", not set(wk) & set(wk2) and len(wk2) == 10, set(wk) & set(wk2))
check("4.weekly-same-week-same-picks", pm.select_prompts(WP, pm.WEEK_EPOCH + timedelta(days=3), "weekly") == wk)
old_wk = pm.select_prompts(WP, date(2026, 9, 21), "weekly")
check("4.weekly-pre-epoch-old-style", len(old_wk) == 5 and old_wk != wk[:5], old_wk)
seen_w = []
for i in range(5):
    seen_w += [q for q in pm.select_prompts(WP, pm.WEEK_EPOCH + timedelta(days=7 * i), "weekly") if q in wcat["people"]]
check("4.weekly-category-cycles", len(seen_w) == len(set(seen_w)) == 10, seen_w)

# ── 5. the fixed heads ───────────────────────────────────────────────────────
mo = pm.journal_fixed("morning", {"ybridge": "b", "goal": "g"})
check("5.morning-order", [k for k, _ in mo] == ["mood", "ybridge", "gcheck", "forecast", "free"], mo)
check("5.forecast-wording", mo[3][1].startswith("🔮 What is the intention for today?")
      and "Forecast the best scenario" in mo[3][1], mo[3])
ev = pm.journal_fixed("evening", {"goal": "Ship it"})
check("5.evening-order-plain", [k for k, _ in ev] == ["bridge", "dhighlight", "tgoal", "goal", "fcheck",
                                                      "money", "rating", "free"], [k for k, _ in ev])
check("5.fcheck-no-forecast", ev[4][1] == "🔮 How did the day go compared to what you expected this morning?", ev[4])
ev2 = pm.journal_fixed("evening", {"goal": "Ship it", "kr": "Finish periodic notes",
                                   "objectives": "Onboard TickTicks 0/5 · TickAL 1/6",
                                   "forecast": "A calm build day, tests green by six"})
check("5.evening-order-full", [k for k, _ in ev2] == ["bridge", "dhighlight", "tgoal", "goal", "kr", "objectives",
                                                      "fcheck", "money", "rating", "free"], [k for k, _ in ev2])
check("5.kr-wording", ev2[4][1] == "🔑 Did you achieve or make progress on today's key result, Finish periodic notes?", ev2[4])
check("5.kr-plural", "key results, A · B?" in pm.journal_fixed("evening", {"kr": "A · B"})[4][1])
check("5.objectives-wording", ev2[5][1] == "🥅 How are you progressing on this month's objectives, Onboard TickTicks 0/5 · TickAL 1/6?", ev2[5])
check("5.objective-singular", "this month's objective, TickAL 1/6?" in pm.journal_fixed("evening", {"objectives": "TickAL 1/6"})[4][1])
check("5.fcheck-wording", ev2[6][1] == "🔮 How did the day go compared to your morning forecast: A calm build day, tests green by six?", ev2[6])
check("5.mind-last", ev2[-1] == ("free", "What is on your mind?") and mo[-1] == ("free", "What is on your mind?"))
variants = (pm.journal_fixed("evening", {}) + ev2 + mo + pm.journal_fixed("morning", {})
            + pm.journal_fixed("weekly", {}) + pm.journal_fixed("monthly", {}) + pm.journal_fixed("quarterly", {}))
wrong = [(k, q) for k, q in variants if pm.journal_key(q) != k]
check("5.every-key-recognised", not wrong, wrong)
check("5.keys-distinct", pm.journal_key("🔮 What is the intention for today? x") == "forecast"
      and pm.journal_key("🔮 How did the day go compared to your morning forecast: x?") == "fcheck"
      and pm.journal_key("🔑 Did you achieve or make progress on today's key result, x?") == "kr"
      and pm.journal_key("🥅 How are you progressing on this month's objectives, x?") == "objectives")
# an old evening note gets the forecast check right after the goal question, and only that
OLD = ["\t- *Q1 · 🌉 Daily bridge - what should tomorrow-you know? (saves to the Bridges board + tomorrow's note)*", "\t\t- A: b",
       "\t- *Q2 · ✨ What was the highlight of the day? Think of one thing that stands out.*", "\t\t- A: ",
       "\t- *Q3 · 🎯 What is the goal for tomorrow? The one thing that, if done, makes the day a success?*", "\t\t- A: ",
       "\t- *Q4 · What is on your mind?*", "\t\t- A: ",
       "\t- *Q5 · Did you achieve your daily goal, X? Describe success/failure factors.*", "\t\t- A: ",
       "\t- *Q6 · How much money did you earn today?*", "\t\t- A: ",
       "\t- *Q7 · Rate the day, 1-5 stars*", "\t\t- A: ",
       "\t- *Q8 · A pool prompt?*", "\t\t- A: "]
body, added = pm.insert_fixed_questions(OLD, pm.journal_fixed("evening", {"goal": "X"}))
qs = [q for _n, q, _a, _i in pm.journal_pairs(body)]
check("5.old-note-gets-fcheck-after-goal", added == ["fcheck"] and qs[4].startswith("Did you achieve your daily goal")
      and qs[5].startswith("🔮 How did the day go") and qs[6].startswith("How much money"), (added, qs))
body2, added2 = pm.insert_fixed_questions(OLD, pm.journal_fixed("evening", {"goal": "X", "kr": "K", "objectives": "O 0/1"}))
qs2 = [q for _n, q, _a, _i in pm.journal_pairs(body2)]
check("5.old-note-gets-kr-objectives-in-order", added2 == ["kr", "objectives", "fcheck"]
      and [pm.journal_key(q) for q in qs2] == ["bridge", "dhighlight", "tgoal", "free", "goal", "kr", "objectives",
                                               "fcheck", "money", "rating", "free"], [pm.journal_key(q) for q in qs2])

# ── 6. the OKR context off the note's 🥅 OKRs section ────────────────────────
OKR_BODY = [
    "- 🎉 2026 • 1/41 KRs",
    "\t- 🏔️ [Productivity System](https://ticktick.com/webapp/#p/6aac/tasks/6aae) 1/41",
    "- 🌓 Q3 • 1/7 KRs",
    "\t- 🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/6aac/tasks/6aac1) 0/5",
    "\t- 🥅 [TickAL](https://ticktick.com/webapp/#p/6aac/tasks/6aac2) 1/6",
    "- 🗓️ Sep • 1/7 KRs",
    "\t- 🥅 [Onboard TickTicks](https://ticktick.com/webapp/#p/6aac/tasks/6aac1) 0/5",
    "\t- 🥅 [TickAL](https://ticktick.com/webapp/#p/6aac/tasks/6aac2) 1/6 🔴 3d",
    "- ♻️ W39 • 1/5 KRs",
    "\t- ✅ [Goals wf](https://ticktick.com/webapp/#p/6aac/tasks/6aac3)",
    "\t- 🔑 [Finish periodic notes](https://ticktick.com/webapp/#p/6aac/tasks/6aac4)",
    "- ☀️ Thu 24 • 0/1 KRs",
    "\t- 🔑 [Finish periodic notes](https://ticktick.com/webapp/#p/6aac/tasks/6aac4) 🔴 1d",
    "---",
]
kr, objs = pm.okr_journal_ctx(OKR_BODY)
check("6.day-kr", kr == "Finish periodic notes", kr)
check("6.month-objectives", objs == "Onboard TickTicks 0/5 · TickAL 1/6", objs)
kr2, objs2 = pm.okr_journal_ctx(OKR_BODY[:11] + ["- ☀️ Fri 25 • no plan", "---"])
check("6.no-plan-day", kr2 == "" and objs2 == "Onboard TickTicks 0/5 · TickAL 1/6", (kr2, objs2))
kr3, _o = pm.okr_journal_ctx(["- ☀️ Sat 26 • 2/2 KRs", "\t- ✅ [A](u)", "\t- 🔑 [B](u)"])
check("6.done-kr-still-named", kr3 == "A · B", kr3)
check("6.empty-section", pm.okr_journal_ctx([]) == ("", "") and pm.okr_journal_ctx(["- 🎉 2026 • no plan"]) == ("", ""))

# ── 7. journal_ctx reads the morning forecast and the OKR lines off the note ─
import periodic_engine as pe          # noqa: E402
import periodic_sections as ps        # noqa: E402
NOTE = "\n".join([
    "#### 🥅 OKRs",
] + OKR_BODY + [
    "#### ☀️ Daily",
    "- [ ] [Ship it](https://ticktick.com/webapp/#p/x/tasks/y)",
    "---",
    "#### 📓 Journals",
    "- 🌅 Morning journal",
    "\t- *Q1 · Mood 1-5 (1 😢 · 3 😐 · 5 😁), optional note after ·*", "\t\t- A: 4",
    "\t- *Q2 · ☀️ Does your goal for today still align with: Ship it?*", "\t\t- A: kept",
    "\t- *Q3 · 🔮 What is the intention for today? How will this day go, what will you achieve? Forecast the best scenario.*",
    "\t\t- A: A calm build day, tests green by six",
    "\t- *Q4 · What is on your mind?*", "\t\t- A: ",
    "- 🌙 Evening journal",
    "\t- *Q1 · 🌉 Daily bridge - what should tomorrow-you know? (saves to the Bridges board + tomorrow's note)*", "\t\t- A: ",
])
doc = ps.parse_sections(NOTE)
ctx = pe.journal_ctx("evening", doc)
check("7.ctx-forecast", ctx.get("forecast") == "A calm build day, tests green by six", ctx)
check("7.ctx-kr", ctx.get("kr") == "Finish periodic notes", ctx)
check("7.ctx-objectives", ctx.get("objectives") == "Onboard TickTicks 0/5 · TickAL 1/6", ctx)
check("7.ctx-goal-kept", ctx.get("goal") == "Ship it", ctx)
mctx = pe.journal_ctx("morning", doc)
check("7.morning-ctx-has-no-forecast", "forecast" not in mctx and "kr" not in mctx, mctx)
doc2 = ps.parse_sections(NOTE.replace("\t\t- A: A calm build day, tests green by six", "\t\t- A: "))
check("7.ctx-forecast-unanswered", pe.journal_ctx("evening", doc2).get("forecast", "") == "")

# ── 8. [person] from the People list, weighted, never the same two days ──────
cands = [("Mum", 3), ("Dad", 3), ("Ana", 2), ("Boss", 1)]
p0 = pm.pick_person(cands, d0)
check("8.picks-a-name", p0 in ("Mum", "Dad", "Ana", "Boss") and pm.pick_person(cands, d0) == p0, p0)
runs = [pm.pick_person(cands, d0 + timedelta(days=i)) for i in range(60)]
check("8.never-two-days-running", all(a != b for a, b in zip(runs, runs[1:])), runs[:10])
from collections import Counter
cnt = Counter(runs)
check("8.family-weighs-more", cnt["Mum"] + cnt["Dad"] > cnt["Ana"] + cnt["Boss"], cnt)
check("8.single-candidate", pm.pick_person([("Solo", 1)], d0) == "Solo" and pm.pick_person([], d0) == "")
filled = pm.fill_person("What value has [person] added to my life? What part of this [person's] character do I admire?", "Ana")
check("8.fill", filled == "What value has Ana added to my life? What part of this Ana's character do I admire?".replace("this Ana's", "Ana's"), filled)
check("8.fill-none", pm.fill_person("What value has [person] added?", "") == "What value has someone close to me added?")
check("8.fill-untouched", pm.fill_person("No placeholder here?", "Ana") == "No placeholder here?")

# ── 9. the quote line comes from the local pool ──────────────────────────────
import periodic_fetch as pf          # noqa: E402
class _NoNet:
    def get(self, *a, **k):
        raise AssertionError("network call")
_req = pf.requests
pf.requests = _NoNet()
try:
    q1 = pf.get_quote(d0)
    q2 = pf.get_quote(d0)
    q3 = pf.get_quote(d0 + timedelta(days=1))
finally:
    pf.requests = _req
stoic_authors = {a for _q, a in QP["stoic"]}
check("9.quote-shape", q1 and q1.startswith("> “") and " · " in q1, q1)
check("9.quote-deterministic-per-day", q1 == q2 and q1 != q3, (q1, q3))
check("9.quote-is-stoic", q1 and q1.rsplit(" · ", 1)[-1] in stoic_authors, q1)
check("9.quote-no-dash", not DASH.search(q1 or ""))


# ── 10. the review's regressions (2026-09-24, three Opus reviewers) ──────────
# a. a draw that straddles an odd category's cycle never repeats a prompt, in
#    the block or on the category's next draw
# (guaranteed from six prompts per category; the shipped pools carry ten or more)
ODD = {"categories": {"prepare": [f"P{i}?" for i in range(7)], "people": [f"Q{i}?" for i in range(9)],
                      "perspective": [f"R{i}?" for i in range(11)]}, "chains": []}
dups, overlaps, prev = 0, 0, {}
for i in range(60):
    blk = pm.select_prompts(ODD, EPOCH + timedelta(days=i), "morning")
    dups += len(blk) - len(set(blk))
    for c, lst in ODD["categories"].items():
        mine = [q for q in blk if q in lst]
        if prev.get(c) and set(mine) & set(prev[c]):
            overlaps += 1
        prev[c] = mine
check("10a.no-duplicate-in-block", dups == 0, dups)
check("10a.no-repeat-on-next-draw", overlaps == 0, overlaps)
allp = [q for lst in ODD["categories"].values() for q in lst]
seen60 = {q for i in range(60) for q in pm.select_prompts(ODD, EPOCH + timedelta(days=i), "morning")}
check("10a.every-prompt-still-comes-round", seen60 == set(allp), set(allp) - seen60)
# b. a day before the epoch keeps its own old-style picks
pre_m = pm.select_prompts(MP, date(2026, 9, 24), "morning")
check("10b.pre-epoch-own-picks", len(pre_m) == 3 and pre_m != pm.select_prompts(MP, date(2026, 9, 10), "morning")[:3]
      and pre_m != m0[:3], pre_m)
pre_e = pm.select_prompts(EP, date(2026, 9, 18), "evening")           # a Friday before the epoch
check("10b.pre-epoch-friday-no-chain", len(pre_e) == 5 and pre_e != EP["chains"][0]["prompts"], pre_e)
# c. a chainless pool: Friday draws something of its own, not Saturday's block
nochain = dict(EP, chains=[])
f_nc, s_nc = pm.select_prompts(nochain, date(2026, 10, 2), "evening"), pm.select_prompts(nochain, date(2026, 10, 3), "evening")
check("10c.chainless-friday-differs", len(f_nc) == 6 and f_nc != s_nc, (f_nc[:2], s_nc[:2]))
check("10c.k-zero-is-empty", pm.select_prompts(EP, mon, "evening", k=0) == [])
# d. OKR lines the app escaped, and a hand-typed line without a glyph
ESC = ["- 🗓️ Sep • 1/7 KRs", "\t- 🥅 \\[Onboard TickTicks\\]\\(https://x/1\\) 0/5",
       "- ☀️ Thu 24 • 1/1 KRs", "\t- 🔑 \\[Finish \\(soon\\)\\]\\(https://x/2\\) 🔴 1d", "\t- Call Ana"]
kr_e, ob_e = pm.okr_journal_ctx(ESC)
check("10d.escaped-okr-lines", kr_e == "Finish (soon) · Call Ana" and ob_e == "Onboard TickTicks 0/5", (kr_e, ob_e))
# e. the person pick does not depend on the cache's row order
rev = list(reversed(cands))
check("10e.order-free-pick", all(pm.pick_person(cands, d0 + timedelta(days=i)) == pm.pick_person(rev, d0 + timedelta(days=i)) for i in range(30)))
# f. a comment inside a chain does not end it; another header does
par = pj._parse("## open\n- a?\n### chain: c\n1. s1\n# a comment\n2. s2\n#### note\n- after?\n")
check("10f.comment-inside-chain", par["chains"][0]["prompts"] == ["s1", "s2"] and par["sections"]["open"] == ["a?", "after?"], par)
# g. an unanswered KR question is dropped when the plan no longer has it; an answered one stays
class _Sec:
    def __init__(self, body): self.body = body
seeded = pm.seed_journal_lines([q for _k, q in pm.journal_fixed("evening", {"goal": "G", "kr": "Old KR", "objectives": "O 0/1"})])
sec_ = _Sec(seeded)
pe._refresh_fixed_q(sec_, pm.journal_fixed("evening", {"goal": "G"}))
keys_after = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(sec_.body)]
check("10g.stale-kr-dropped", "kr" not in keys_after and "objectives" not in keys_after
      and [n for n, *_ in pm.journal_pairs(sec_.body)] == list(range(1, len(keys_after) + 1)), keys_after)
seeded2 = pm.seed_journal_lines([q for _k, q in pm.journal_fixed("evening", {"goal": "G", "kr": "Old KR"})])
kr_line = next(i for i, ln in enumerate(seeded2) if "key result" in ln)
seeded2[kr_line + 1] = "\t- A: made progress"
sec2 = _Sec(seeded2)
pe._refresh_fixed_q(sec2, pm.journal_fixed("evening", {"goal": "G"}))
check("10g.answered-kr-stays", any(pm.journal_key(q) == "kr" and a == "made progress" for _n, q, a, _i in pm.journal_pairs(sec2.body)))
# h. a forecast that mentions "rate the day" is not the rating
FDOC = ps.parse_sections("\n".join([
    "#### 📓 Journals", "- 🌙 Evening journal",
    "\t- *Q1 · 🔮 How did the day go compared to your morning forecast: I will rate the day by the gig, the highlight of the day too?*",
    "\t\t- A: it went fine",
    "\t- *Q2 · Rate the day, 1-5 stars*", "\t\t- A: ",
    "\t- *Q3 · ✨ What was the highlight of the day? Think of one thing that stands out.*", "\t\t- A: "]))
check("10h.reader-skips-quoting-keys", pe._answer_in(FDOC, pm.SEC_EVENING, "rate the day") == ""
      and pe._answer_in(FDOC, pm.SEC_EVENING, "highlight of the day") == "")
# i. the goal check survives a phone edit that drops the sun's VS16
check("10i.gcheck-without-vs16", pm.journal_key("☀ Does your goal for today still align with: X?") == "gcheck"
      and pm.journal_key("☀️ What is today's goal?") == "gcheck")


# ── 12. the weekly set block (Vex 2026-09-24: objectives before the KRs, habits, mind last) ──
W0 = pm.journal_fixed("weekly", {"goals": "TickTick"})
check("12.weekly-plain-order", [k for k, _ in W0] == ["highlight", "wgoals", "wfcheck", "wrating", "wforecast", "free"], W0)
check("12.weekly-mind-last", W0[-1] == ("free", "What is on your mind?"))
WCTX = {"goals": "TickTick", "objectives": "Onboard TickTicks 0/5 · TickAL 1/6",
        "kr": "✅ Goals wf · 🔑 Finish periodic notes · 🔑 Curriculums",
        "habits": "Weekly Review 0/1 · Call mum 0/1 · 🌅 Startup 3/7 · 🌆 Shutdown 2/7",
        "days": "Mon · tattooing; Wed · Meal I prepped yesterday"}
W1 = pm.journal_fixed("weekly", WCTX)
check("12.weekly-full-order", [k for k, _ in W1] == ["highlight", "wgoals", "objectives", "kr", "habits", "wfcheck", "wrating", "wforecast", "free"], [k for k, _ in W1])
check("12.wfcheck-plain", W1[5][1] == "🔮 How did the week go compared to what you expected?", W1[5])
check("12.wfcheck-quotes-last-week", pm.journal_fixed("weekly", {"wforecast": "Ship the weekly"})[2][1]
      == "🔮 How did the week go compared to last week's forecast: Ship the weekly?")
check("12.wrating-wording", W1[6] == ("wrating", "Rate the week, 1-5 stars"))
check("12.wforecast-wording", W1[7][1].startswith("🔮 What is the intention for next week?") and "Forecast the best scenario" in W1[7][1])
check("12.weekly-keys-apart-from-daily", pm.journal_key("🔮 What is the intention for next week? x") == "wforecast"
      and pm.journal_key("🔮 How did the week go compared to what you expected?") == "wfcheck"
      and pm.journal_key("Rate the week, 1-5 stars") == "wrating" and pm.journal_key("Rate the day, 1-5 stars") == "rating")
check("12.stars", pm.stars_answer("4") == "★★★★" and pm.stars_answer("5 great") == "★★★★★" and pm.stars_answer("10") is None and pm.stars_answer("ok") is None)
check("12.highlight-shows-the-days", W1[0][1].startswith("What was the highlight of the week? Think of one thing that stands out.")
      and "Your days: Mon · tattooing; Wed · Meal I prepped yesterday" in W1[0][1], W1[0])
check("12.objectives-wording", W1[2][1] == "🥅 How are you progressing on this month's objectives, Onboard TickTicks 0/5 · TickAL 1/6?", W1[2])
check("12.kr-wording", W1[3][1] == "🔑 Did you achieve or make progress on this week's key results, ✅ Goals wf · 🔑 Finish periodic notes · 🔑 Curriculums?", W1[3])
check("12.habits-wording", W1[4][1] == "🔄 Habit consistency this week: Weekly Review 0/1 · Call mum 0/1 · 🌅 Startup 3/7 · 🌆 Shutdown 2/7. Which habit earned its keep, which did not, and why?", W1[4])
check("12.weekly-keys-recognised", all(pm.journal_key(q) == k for k, q in W1), [(k, pm.journal_key(q)) for k, q in W1])
check("12.weekly-kr-singular", "this week's key result, 🔑 A?" in pm.journal_fixed("weekly", {"kr": "🔑 A"})[2][1])
# the OKR reader on the WEEK bullet keeps the ✅/🔑 state
wkr, wobj = pm.okr_journal_ctx(OKR_BODY, kr_tier="weekly", keep_state=True)
check("12.week-krs-with-state", wkr == "✅ Goals wf · 🔑 Finish periodic notes" and wobj == "Onboard TickTicks 0/5 · TickAL 1/6", (wkr, wobj))
# children of a labelled bullet inside a group section
STATS = ["- Top lists:", "\t- 📌CTA · 11 done · 10 added", "", "- Habit consistency", "\t- Weekly Review · 0/1 · 0%",
         "\t- Call mum · 0/1 · 0%", "\t- 🌅 Startup · 3/7 · 42%", "\t- 🌆 Shutdown · 2/7 · 28%", "---"]
check("12.bullet-children", pm.bullet_children(STATS, "Habit consistency") == ["Weekly Review · 0/1 · 0%", "Call mum · 0/1 · 0%", "🌅 Startup · 3/7 · 42%", "🌆 Shutdown · 2/7 · 28%"]
      and pm.bullet_children(STATS, "Nothing") == [], pm.bullet_children(STATS, "Habit consistency"))
check("12.habit-summary", pm.habit_summary(pm.bullet_children(STATS, "Habit consistency")) == "Weekly Review 0/1 · Call mum 0/1 · 🌅 Startup 3/7 · 🌆 Shutdown 2/7")
DATA = ["- ✨ Highlights", "\t- Wed · Meal I prepped yesterday", "\t- Mon · tattooing", "", "- 📨 Entries", "\t- **❗️ Reminders**"]
check("12.days-summary", pm.days_summary(pm.bullet_children(DATA, "✨ Highlights")) == "Wed · Meal I prepped yesterday; Mon · tattooing")
# the weekly ctx off a weekly note
WNOTE = "\n".join(["#### 🥅 OKRs"] + OKR_BODY + [
    "#### 🏆 Goals", "- 🌓 Quarterly", "\t- _(mirrors this quarter's note - set it there)_", "", "- 🗓️ Monthly",
    "\t- _(mirrors this month's note - set it there)_", "", "- ♻️ Weekly", "\t- [ ] [TickTick](https://ticktick.com/webapp/#p/x/tasks/y)", "",
    "#### ✨ Highlight", "---", "#### 📌 This Week", "##### 📊 Stats"] + STATS + ["##### 💿 Data"] + DATA + ["---",
    "##### ⏪ Last week", "- Completed: 195", "- 🔮 Forecast: Ship the weekly", "- Rating: ★★★★", "---",
    "##### 📔 Weekly journal", "\t- *Q1 · What was the highlight of the week? Think of one thing that stands out.*", "\t\t- A: ",
    "\t- *Q2 · Did you achieve your weekly goals, TickTick? Describe success/fail factors on each.*", "\t\t- A: ",
    "\t- *Q3 · Which system broke this week - and what is its two-minute patch?*", "\t\t- A: ", "---"])
wdoc = ps.parse_sections(WNOTE)
wctx = pe.journal_ctx("weekly", wdoc)
check("12.ctx-goals", wctx.get("goals") == "TickTick", wctx)
check("12.ctx-objectives", wctx.get("objectives") == "Onboard TickTicks 0/5 · TickAL 1/6", wctx)
check("12.ctx-kr", wctx.get("kr") == "✅ Goals wf · 🔑 Finish periodic notes", wctx)
check("12.ctx-habits", wctx.get("habits") == "Weekly Review 0/1 · Call mum 0/1 · 🌅 Startup 3/7 · 🌆 Shutdown 2/7", wctx)
check("12.ctx-days", wctx.get("days") == "Wed · Meal I prepped yesterday; Mon · tattooing", wctx)
check("12.ctx-wforecast-off-last-week", wctx.get("wforecast") == "Ship the weekly", wctx)
# an already-seeded W39 layout gets objectives, kr, habits and mind inserted after the goals question, in order
wsec = ps.find(wdoc, pm.SEC_WEEKLY_JNL)
wbody, wadded = pm.insert_fixed_questions(wsec.body, pm.journal_fixed("weekly", wctx))
wkeys = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(wbody)]
# (the trailing free is W39's legacy Q3; "What is on your mind?" itself is a free key and is never inserted)
check("12.old-weekly-gains-the-set", wadded == ["objectives", "kr", "habits", "wfcheck", "wrating", "wforecast"]
      and wkeys == ["highlight", "wgoals", "objectives", "kr", "habits", "wfcheck", "wrating", "wforecast", "free"], (wadded, wkeys))
check("12.bullet-label-with-emoji", pm.bullet_children(["- 🔄 Habit consistency", "\t- A · 1/1 · 100%"], "Habit consistency") == ["A · 1/1 · 100%"]
      and pm.bullet_children(["- ✨ Highlight", "\t- x"], "✨ Highlights") == [])
tiny = {"categories": {"prepare": ["A?", "B?", "C?"], "people": [f"Q{i}?" for i in range(10)], "perspective": [f"R{i}?" for i in range(10)]}, "chains": []}
check("12.tiny-category-never-doubles", all(len(set(b)) == len(b) for b in (pm.select_prompts(tiny, EPOCH + timedelta(days=i), "morning") for i in range(40))))


# ── 13. the monthly set block (Vex 2026-09-24, late: the OKR checkpoint, money rephrased, mind last) ──
M0 = pm.journal_fixed("monthly", {"goals": "TickAL"})
check("13.monthly-plain-order", [k for k, _ in M0] == ["mhighlight", "mgoals", "mgrateful", "mlearned", "mkeep", "mchange", "mdrained", "mtime", "free"], M0)
MCTX = {"goals": "TickAL", "objectives": "Onboard TickTicks 0/5 · TickAL 1/6", "quarter": "Onboard TickTicks 0/5 · TickAL 1/6",
        "months_left": 0, "habits": "🌅 Startup 12/13 · 🌆 Shutdown 10/13", "weeks": "W3 · 14th-20th Sep · Situation with Ivona",
        "money": "1845 · 🔴 ▼ 200 (−26%)"}
M1 = pm.journal_fixed("monthly", MCTX)
check("13.monthly-full-order", [k for k, _ in M1] == ["mhighlight", "mgoals", "mobjectives", "qcheck", "habits", "mmoney", "mgrateful", "mlearned", "mkeep", "mchange", "mdrained", "mtime", "free"], [k for k, _ in M1])
check("13.vex-six-wording", M1[6][1] == "🙏 What three things, moments or people are you most grateful for over the past month?"
      and M1[7][1] == "📚 What have you learned this month? Think of the challenges."
      and M1[8][1].startswith("♻️ What would you like to keep doing next month") and M1[9][1] == "🔧 What must change next month? What can you improve?"
      and M1[10][1] == "🪫 What drained your energy this month?" and M1[11][1] == "⏳ How do you want to spend your time next month?", M1[6:12])
check("13.six-recognised-without-vs16", pm.journal_key("♻ What would you like to keep doing next month exactly as you did this month?") == "mkeep")
check("13.highlight-shows-the-weeks", M1[0][1].startswith("What was the highlight of the month? Think of one thing that stands out.")
      and "Your weeks: W3 · 14th-20th Sep · Situation with Ivona" in M1[0][1], M1[0])
check("13.objectives-wording", M1[2][1] == "🥅 Objective by objective, Onboard TickTicks 0/5 · TickAL 1/6: what moved, what stalled, and why?", M1[2])
check("13.quarter-last-month", M1[3][1] == "🌓 The quarter's objectives, Onboard TickTicks 0/5 · TickAL 1/6: this was its last month. Which carry into next quarter, and which stop here?", M1[3])
check("13.quarter-months-left", pm.journal_fixed("monthly", {"quarter": "A 0/1", "months_left": 2})[2][1]
      == "🌓 The quarter's objectives, A 0/1, with 2 months left: still the right ones? What to cut, add or move in the timeline?"
      and "with 1 month left" in pm.journal_fixed("monthly", {"quarter": "A 0/1", "months_left": 1})[2][1]
      and "with the quarter still running" in pm.journal_fixed("monthly", {"quarter": "A 0/1"})[2][1])
check("13.habits-wording", M1[4][1] == "🔄 Habit consistency this month: 🌅 Startup 12/13 · 🌆 Shutdown 10/13. Which held all month, which only held for a week?", M1[4])
check("13.money-wording", M1[5][1] == "💰 Income this month: 1845 · 🔴 ▼ 200 (−26%). Does this align with your forecast? What could you do to improve it?", M1[5])
check("13.mind-last", M1[-1] == ("free", "What is on your mind?"))
check("13.monthly-keys-recognised", all(pm.journal_key(q) == k for k, q in M1), [(k, pm.journal_key(q)) for k, q in M1])
check("13.quarterly-has-its-own-branch", [k for k, _ in pm.journal_fixed("quarterly", {"goals": "G"})][:3] == ["qhighlight", "qlowlights", "qgoals"])
check("13.months-left", [pm.months_left_in_quarter(date(2026, m, 1)) for m in (7, 8, 9, 10, 12)] == [2, 1, 0, 2, 0])
check("13.quarter-items", pm.okr_tier_items(OKR_BODY, "quarterly") == ["Onboard TickTicks 0/5", "TickAL 1/6"]
      and pm.okr_tier_items(OKR_BODY, "yearly") == ["Productivity System 1/41"] and pm.okr_tier_items([], "monthly") == [])
MDATA = ["- ✨ Highlights", "\t- W3 · 14th-20th Sep · Situation with Ivona", "", "- 😊 Moods: Average 3.3",
         "\t- W2 · 7th-13th Sep · 🙂 3.7", "", "- 💰 Income: 1845 · 🔴 ▼ 200 (−26%)", "\t- W2 · 7th-13th Sep • 495",
         "\t\t- **Total = 1845**", "", "- 👽 People"]
check("13.bullet-head", pm.bullet_head(MDATA, "💰 Income") == "1845 · 🔴 ▼ 200 (−26%)" and pm.bullet_head(["- 💰 Income: 1845"], "💰 Income") == "1845"
      and pm.bullet_head(MDATA, "🔥 Nothing") == "" and pm.bullet_head(["- 👽 People"], "👽 People") == "", pm.bullet_head(MDATA, "💰 Income"))
MSTATS = ["- Top lists:", "\t- 📌CTA · 11 done", "", "- Habit consistency", "\t- 🌅 Startup · 12/13 · 92%", "\t- 🌆 Shutdown · 10/13 · 76%", "---"]
MNOTE = "\n".join(["#### 🥅 OKRs"] + OKR_BODY + [
    "#### 🏆 Goals", "- 🌓 Quarterly goal", "\t- _(mirrors this quarter's note - set it there)_", "", "- 🗓️ Monthly goal",
    "\t- [ ] [TickAL](https://ticktick.com/webapp/#p/x/tasks/y)", "",
    "#### ✨ Highlight", "---", "#### 📌 This Month", "##### 📊 Stats"] + MSTATS + ["##### 💿 Data"] + MDATA + ["---",
    "##### ⏪ Last month", "- Completed: 305", "---",
    "##### 📔 Monthly journal", "\t- *Q1 · What was the highlight of the month? Think of one thing that stands out.*", "\t\t- A: ",
    "\t- *Q2 · Did you achieve your monthly goals, TickAL? Describe success/fail factors on each.*", "\t\t- A: ",
    "\t- *Q3 · What did you carry all month without finishing?*", "\t\t- A: ", "---"])
mdoc = ps.parse_sections(MNOTE)
mctx = pe.journal_ctx("monthly", mdoc, date(2026, 9, 1))
check("13.ctx-goals", mctx.get("goals") == "TickAL", mctx)
check("13.ctx-objectives-quarter", mctx.get("objectives") == "Onboard TickTicks 0/5 · TickAL 1/6" and mctx.get("quarter") == "Onboard TickTicks 0/5 · TickAL 1/6", mctx)
check("13.ctx-months-left", mctx.get("months_left") == 0 and "months_left" not in pe.journal_ctx("monthly", mdoc), mctx)
check("13.ctx-habits-weeks-money", mctx.get("habits") == "🌅 Startup 12/13 · 🌆 Shutdown 10/13"
      and mctx.get("weeks") == "W3 · 14th-20th Sep · Situation with Ivona" and mctx.get("money") == "1845 · 🔴 ▼ 200 (−26%)", mctx)
msec = ps.find(mdoc, pm.SEC_MONTHLY_JNL)
mbody, madded = pm.insert_fixed_questions(msec.body, pm.journal_fixed("monthly", mctx))
mkeys = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(mbody)]
check("13.old-monthly-gains-the-set", madded == ["mobjectives", "qcheck", "habits", "mmoney", "mgrateful", "mlearned", "mkeep", "mchange", "mdrained", "mtime"]
      and mkeys == ["mhighlight", "mgoals", "mobjectives", "qcheck", "habits", "mmoney", "mgrateful", "mlearned", "mkeep", "mchange", "mdrained", "mtime", "free"], (madded, mkeys))
MPOOL = {"categories": {c: [f"{c}{i}?" for i in range(10)] for c in pm.MONTHLY_CATEGORIES}, "chains": []}
mo1 = pm.select_prompts(MPOOL, pm.MONTH_EPOCH, "monthly")
check("13.monthly-ten", len(mo1) == 10 and len(set(mo1)) == 10
      and [c for c in pm.MONTHLY_CATEGORIES for _ in range(2)] == [next(c for c in pm.MONTHLY_CATEGORIES if q in MPOOL["categories"][c]) for q in mo1], mo1)
check("13.monthly-same-month-same-picks", pm.select_prompts(MPOOL, date(2026, 10, 31), "monthly") == mo1)
mo2 = pm.select_prompts(MPOOL, date(2026, 11, 1), "monthly")
check("13.monthly-next-month-differs", len(mo2) == 10 and not set(mo1) & set(mo2), set(mo1) & set(mo2))
check("13.monthly-year-boundary", len(pm.select_prompts(MPOOL, date(2027, 1, 1), "monthly")) == 10
      and pm.select_prompts(MPOOL, date(2027, 1, 15), "monthly") == pm.select_prompts(MPOOL, date(2027, 1, 1), "monthly"))
check("13.monthly-pre-epoch-old-style", len(pm.select_prompts(dict(MPOOL, random=[f"r{i}" for i in range(20)]), date(2026, 9, 1), "monthly")) == 5)

# ── 14. the quarterly set block (Vex 2026-09-24, late night: his findings + the OKR checkpoint, ten drawn) ──
Q0 = pm.journal_fixed("quarterly", {"goals": "G"})
check("14.quarterly-plain-order", [k for k, _ in Q0] == ["qhighlight", "qlowlights", "qgoals", "qeffort", "qenergy", "qpriorities", "qforecast", "free"], [k for k, _ in Q0])
QCTX = {"goals": "G", "objectives": "Onboard TickTicks 0/5 · TickAL 1/6", "year": "Productivity System 1/41", "quarters_left": 1,
        "habits": "Weekly Review 1/2 · 🌆 Shutdown 10/13", "months": "M1 · July · Readme; M3 · September · OKRs",
        "wins": "Did weekly review; readme done", "nags": "Journal exits after highlight prompt.",
        "moods": "M1 · July · 🙂 4.0; M3 · September · 😐 3.3 (Average 3.5)",
        "money": "2955 (M1 · July • 1110; M2 · August • no notes; M3 · September • 1845)",
        "focus": "97h 11m (M1 · July · 30h 54m · CRM Testing; M3 · September · 66h 17m · Onboard TickTick)",
        "compare": "Completed 665 vs 500 · Focus 97h 11m vs 49h 00m · Mood 3.5 vs 3.4 · Income 2955 vs 2100",
        "wanted": "TickAL shipped and ten customers onboarded"}
Q1 = pm.journal_fixed("quarterly", QCTX)
QKEYS = [k for k, _ in Q1]
check("14.quarterly-full-order", QKEYS == ["qhighlight", "qlowlights", "qgoals", "qobjectives", "ycheck", "qcompare", "habits", "qmoney",
                                          "qeffort", "qenergy", "qpriorities", "qforecast", "free"], QKEYS)
QT = dict(Q1)
check("14.highlights-wording", QT["qhighlight"] == "✨ What are the three biggest highlights of the quarter? Your months: M1 · July · Readme; M3 · September · OKRs. Your wins: Did weekly review; readme done.", QT["qhighlight"])
check("14.lowlights-wording", QT["qlowlights"] == "🔴 What are the three biggest lowlights? Your nags: Journal exits after highlight prompt. Moods: M1 · July · 🙂 4.0; M3 · September · 😐 3.3 (Average 3.5).", QT["qlowlights"])
check("14.goals-as-is", QT["qgoals"] == "Did you achieve your quarterly goals, G? Describe success/fail factors on each.", QT["qgoals"])
check("14.objectives-wording", QT["qobjectives"] == "🥅 Objective by objective, Onboard TickTicks 0/5 · TickAL 1/6: hit, partial or miss, and the factor that decided it? Was the bar set too high or too low?", QT["qobjectives"])
check("14.year-one-left", QT["ycheck"] == "🎉 The year's goal, Productivity System 1/41, with 1 quarter left: ahead, on track or behind, and what must next quarter deliver? Has this review given you information that alters your yearly goals?", QT["ycheck"])
check("14.year-last-quarter", dict(pm.journal_fixed("quarterly", {"year": "Y 1/4", "quarters_left": 0}))["ycheck"]
      == "🎉 The year's goal, Y 1/4: this was its last quarter. Which carry into next year, and which stop here?")
check("14.year-still-running", "with the year still running" in dict(pm.journal_fixed("quarterly", {"year": "Y 1/4"}))["ycheck"]
      and "with 3 quarters left" in dict(pm.journal_fixed("quarterly", {"year": "Y 1/4", "quarters_left": 3}))["ycheck"])
check("14.compare-both", QT["qcompare"] == "⏪ How does this quarter compare to last quarter? Completed 665 vs 500 · Focus 97h 11m vs 49h 00m · Mood 3.5 vs 3.4 · Income 2955 vs 2100. Last quarter you wanted: TickAL shipped and ten customers onboarded. Did you get there?", QT["qcompare"])
check("14.compare-numbers-only", dict(pm.journal_fixed("quarterly", {"compare": "Completed 1 vs 2"}))["qcompare"] == "⏪ How does this quarter compare to last quarter? Completed 1 vs 2.")
check("14.compare-wanted-only", dict(pm.journal_fixed("quarterly", {"wanted": "x"}))["qcompare"] == "⏪ How does this quarter compare to last quarter? Last quarter you wanted: x. Did you get there?")
check("14.habits-wording", QT["habits"] == "🔄 Habit consistency this quarter: Weekly Review 1/2 · 🌆 Shutdown 10/13. Which held, which broke, and which habits do you want to build next quarter?", QT["habits"])
check("14.money-wording", QT["qmoney"] == "💰 Income this quarter: 2955 (M1 · July • 1110; M2 · August • no notes; M3 · September • 1845). Does this align with your forecast? What could you do to improve it? Can you cut down on any expense category?", QT["qmoney"])
check("14.effort-wording", QT["qeffort"] == "⏱ What effort is not worth your time, what are you spending your time on that is not leading towards the desired outcome? Your focus: 97h 11m (M1 · July · 30h 54m · CRM Testing; M3 · September · 66h 17m · Onboard TickTick)."
      and dict(Q0)["qeffort"].endswith("desired outcome?"), QT["qeffort"])
check("14.vex-three-wording", QT["qenergy"] == "🔥 When did you feel most passionate this quarter, and why then? When did you feel bored or resentful, and why?"
      and QT["qpriorities"] == "🧭 What are your top three priorities, and why do they matter?"
      and QT["qforecast"] == "🔮 If you continue at this pace, where will you be in three months? Where do you want to be in 3 months? What do you want to achieve?", (QT["qenergy"], QT["qpriorities"], QT["qforecast"]))
check("14.mind-last", Q1[-1] == ("free", "What is on your mind?"))
check("14.quarterly-keys-recognised", all(pm.journal_key(q) == k for k, q in Q1), [(k, pm.journal_key(q)) for k, q in Q1])
check("14.old-highlight-still-qhighlight", pm.journal_key("What was the highlight of the quarter? Think of one thing that stands out.") == "qhighlight")
check("14.monthly-objectives-still-mobjectives", pm.journal_key("🥅 Objective by objective, A 0/1: what moved, what stalled, and why?") == "mobjectives"
      and pm.journal_key("⏱️ What effort is not worth your time, x?") == "qeffort")
check("14.no-rule-hits-a-pool-prompt", all(pm.journal_key(q) == "free" for c in pj.load_pool("quarterly")["categories"].values() for q in c))
check("14.conditional-and-quoting", {"qobjectives", "ycheck", "qcompare", "qmoney", "habits"} <= set(pm.CONDITIONAL_KEYS)
      and {"qobjectives", "ycheck", "qcompare", "qmoney", "qeffort", "qlowlights", "qhighlight"} <= set(pm.QUOTING_KEYS)
      and "qenergy" not in pm.CONDITIONAL_KEYS)
check("14.quarters-left", [pm.quarters_left_in_year(date(2026, m, 1)) for m in (1, 3, 4, 6, 7, 9, 10, 12)] == [3, 3, 2, 2, 1, 1, 0, 0])
QDATA = ["- ✨ Highlights", "\t- M1 · July · Readme", "\t- M3 · September · OKRs", "",
         "- 📨 Entries", "\t- **🟢 Wins**", "\t\t- Did weekly review · Sun 20 Sep 09:58", "\t\t- readme done · Wed 15 Jul 19:44", "",
         "\t- **🔴 Nags**", "\t\t- Journal exits after highlight prompt. · Sun 20 Sep 22:05", "", "\t- **💭 Thoughts**", "\t\t- m4 tests · Sat 11 Jul 21:45", "",
         "- 😊 Moods: Average 3.5", "\t- M1 · July · 🙂 4.0", "\t- M3 · September · 😐 3.3", "",
         "- 💰 Income: 2955", "\t- M1 · July • 1110", "\t- M2 · August • no notes", "\t- M3 · September • 1845", "\t\t- **Total = 2955**", "",
         "- 👽 People", "\t- 🎂 Andres · in 64d"]
check("14.entry-children", pm.entry_children(QDATA, "📨 Entries", "🟢 Wins") == ["Did weekly review · Sun 20 Sep 09:58", "readme done · Wed 15 Jul 19:44"]
      and pm.entry_children(QDATA, "📨 Entries", "🔴 Nags") == ["Journal exits after highlight prompt. · Sun 20 Sep 22:05"]
      and pm.entry_children(QDATA, "📨 Entries", "🔗 Links") == [] and pm.entry_children([], "📨 Entries", "🟢 Wins") == [], pm.entry_children(QDATA, "📨 Entries", "🟢 Wins"))
check("14.entries-summary", pm.entries_summary(pm.entry_children(QDATA, "📨 Entries", "🟢 Wins")) == "Did weekly review; readme done"
      and pm.entries_summary([f"w{i} · Mon 1 Sep 10:00" for i in range(10)]) == "; ".join(f"w{i}" for i in range(8)) + " (+2 more)"
      and pm.entries_summary(["Journal exits after highlight prompt. · Sun 20 Sep 22:05", "Late again. · Mon 21 Sep 09:00"]) == "Journal exits after highlight prompt; Late again"
      and pm.entries_summary([]) == "")
check("14.quarter-compare", pm.quarter_compare({"Completed": "665 · 🟢 ▲ 12 (+2%)", "Focus": "97h 11m · 🟢 ▲ 47h 37m (+96%)", "Mood": "Average 3.5", "Income": "2955"},
                                                {"Completed": "500", "Focus": "49h 00m", "Mood": "3.4 avg", "Income": "2100"})
      == "Completed 665 vs 500 · Focus 97h 11m vs 49h 00m · Mood 3.5 vs 3.4 · Income 2955 vs 2100"
      and pm.quarter_compare({"Completed": "665"}, {"Focus": "1h"}) == "" and pm.quarter_compare({}, {}) == "")
check("14.quarter-compare-partial-dropped", pm.quarter_compare({"Completed": "665 · 1 of 3 months", "Income": "2955"}, {"Completed": "500", "Income": "2100"}) == "Income 2955 vs 2100"
      and pm.quarter_compare({"Completed": "700"}, {"Completed": "665 · 1 of 3 months", "Income": "1"}) == "")
QSTATS = ["- Top lists:", "\t- 📌CTA · 84 done", "", "- Completed: 665 · 1 of 3 months", "\t- 🗂 📌CTA · 187", "",
          "- Focus: 97h 11m · 🟢 ▲ 47h 37m (+96%)", "\t- M1 · July · 30h 54m · CRM Testing", "\t- M3 · September · 66h 17m · Onboard TickTick", "\t\t- **Total = 97h 11m**", "",
          "- Habit consistency", "\t- Weekly Review · 1/2 · 50%", "\t- 🌆 Shutdown · 10/13 · 76%", "---"]
QNOTE = "\n".join(["#### 🥅 OKRs"] + OKR_BODY + [
    "#### 🏆 Goals", "- 🎉 Yearly goal", "\t- [ ] [💼 P • Productivity System 🔗](https://ticktick.com/webapp/#p/x/tasks/y)", "",
    "- 🌓 Quarterly goal", "\t- [ ] [TickAL](https://ticktick.com/webapp/#p/x/tasks/z)", "",
    "#### ✨ Highlight", "---", "##### 📊 Stats"] + QSTATS + ["##### 💿 Data"] + QDATA + ["---",
    "##### ⏪ Last quarter", "- Completed: 500", "- Created: 900", "- Focus: 49h 00m", "- Mood: 3.4 avg", "- Income: 2100",
    "- 🔮 Wanted: TickAL shipped and ten customers onboarded", "", "- Top Tasks:", "\t- x · 3×", "---",
    "##### 📔 Quarterly journal", "\t- *Q1 · What was the highlight of the quarter? Think of one thing that stands out.*", "\t\t- A: Readme week",
    "\t- *Q2 · Did you achieve your quarterly goals? Describe success/fail factors on each.*", "\t\t- A: ",
    "\t- *Q3 · Which month of this quarter would you live again, and what made it that one?*", "\t\t- A: ", "---"])
qdoc = ps.parse_sections(QNOTE)
qctx = pe.journal_ctx("quarterly", qdoc, date(2026, 7, 1))
check("14.ctx-goals-objectives-year", qctx.get("goals") == "TickAL" and qctx.get("objectives") == "Onboard TickTicks 0/5 · TickAL 1/6"
      and qctx.get("year") == "Productivity System 1/41", qctx)
check("14.ctx-quarters-left", qctx.get("quarters_left") == 1 and "quarters_left" not in pe.journal_ctx("quarterly", qdoc)
      and pe.journal_ctx("quarterly", qdoc, date(2026, 10, 1)).get("quarters_left") == 0, qctx)
check("14.ctx-habits-months", qctx.get("habits") == "Weekly Review 1/2 · 🌆 Shutdown 10/13" and qctx.get("months") == "M1 · July · Readme; M3 · September · OKRs", qctx)
check("14.ctx-wins-nags-moods", qctx.get("wins") == "Did weekly review; readme done" and qctx.get("nags") == "Journal exits after highlight prompt"
      and qctx.get("moods") == "M1 · July · 🙂 4.0; M3 · September · 😐 3.3 (Average 3.5)", qctx)
check("14.ctx-money-focus", qctx.get("money") == "2955 (M1 · July • 1110; M2 · August • no notes; M3 · September • 1845)"
      and qctx.get("focus") == "97h 11m · 🟢 ▲ 47h 37m (+96%) (M1 · July · 30h 54m · CRM Testing; M3 · September · 66h 17m · Onboard TickTick)", qctx)
check("14.ctx-compare-wanted", qctx.get("compare") == "Focus 97h 11m vs 49h 00m · Mood 3.5 vs 3.4 · Income 2955 vs 2100"
      and qctx.get("wanted") == "TickAL shipped and ten customers onboarded", qctx)
qctx_np = pe.journal_ctx("quarterly", ps.parse_sections(QNOTE.replace("##### ⏪ Last quarter\n- Completed: 500\n- Created: 900\n- Focus: 49h 00m\n- Mood: 3.4 avg\n- Income: 2100\n- 🔮 Wanted: TickAL shipped and ten customers onboarded\n", "##### ⏪ Last quarter\n\t_(pending)_\n")), date(2026, 7, 1))
check("14.ctx-no-last-quarter", not qctx_np.get("compare") and not qctx_np.get("wanted"), qctx_np)
check("14.highlight-read-by-key", pe._tier_highlight_of(qdoc, "quarterly") == "Readme week"
      and pe._tier_highlight_of(mdoc, "monthly") == "" and pe._tier_highlight_of(ps.parse_sections("#### ✨ Highlight\n- Best\n---\n##### 📔 Quarterly journal\n\t- *Q1 · ✨ What are the three biggest highlights of the quarter? Your wins: x.*\n\t\t- A: y\n"), "quarterly") == "Best"
      and pe._tier_highlight_of(ps.parse_sections("##### 📔 Quarterly journal\n\t- *Q1 · ✨ What are the three biggest highlights of the quarter? Your wins: highlight of the quarter.*\n\t\t- A: three things\n"), "quarterly") == "three things")
QPREV = ps.parse_sections("##### 📔 Quarterly journal\n\t- *Q12 · 🔮 If you continue at this pace, where will you be in three months? Where do you want to be in 3 months? What do you want to achieve?*\n\t\t- A: [Shipped](https://x) and calm\n")
check("14.wanted-line", pe._quarter_words(QPREV) == ["- 🔮 Wanted: Shipped and calm"] and pe._quarter_words(ps.parse_sections("##### 📔 Quarterly journal\n\t- *Q1 · x?*\n\t\t- A: \n")) == [])
check("14.compare-wanted-no-double-stop", dict(pm.journal_fixed("quarterly", {"wanted": "Shipped and calm."}))["qcompare"]
      == "⏪ How does this quarter compare to last quarter? Last quarter you wanted: Shipped and calm. Did you get there?"
      and dict(pm.journal_fixed("quarterly", {"wanted": "Ten customers!"}))["qcompare"].endswith("Ten customers! Did you get there?"))
QBLOCK = ["\t- *Q11 · 🔮 If you continue at this pace, where will you be in three months? Where do you want to be in 3 months? What do you want to achieve?*",
          "\t\t- A: At this pace: half the backlog, tired.", "\t\t- Where I want to be: TickAL 3.0 shipped, five customers onboarded.",
          "\t\t- *Achieve: the OKR loop running weekly.*", "", "\t- *Q12 · What is on your mind?*", "\t\t- A: nothing"]
check("14.whole-answer", pm.journal_answer_text(QBLOCK, 1) == "At this pace: half the backlog, tired. Where I want to be: TickAL 3.0 shipped, five customers onboarded. Achieve: the OKR loop running weekly."
      and pm.journal_answer_text(QBLOCK, 6) == "nothing" and pm.journal_answer_text(QBLOCK, 0) == "" and pm.journal_answer_text(["\t- *Q1 · x?*", "\t\t- A: "], 1) == "")
check("14.wanted-line-whole-wish", pe._quarter_words(ps.parse_sections("##### 📔 Quarterly journal\n" + "\n".join(QBLOCK)))
      == ["- 🔮 Wanted: At this pace: half the backlog, tired. Where I want to be: TickAL 3.0 shipped, five customers onboarded. Achieve: the OKR loop running weekly."])
check("14.months-lose-their-stops", pe.journal_ctx("quarterly", ps.parse_sections("##### 💿 Data\n- ✨ Highlights\n\t- M1 · July · Shipped the workflow.\n\t- M2 · August · Rest\n"), date(2026, 7, 1)).get("months")
      == "M1 · July · Shipped the workflow; M2 · August · Rest")
check("14.entries-flatten-markdown", pm.entries_summary(["Shipped [TickAL](https://x/y) · Sun 20 Sep 09:58", "**Big** win · Mon 21 Sep 10:00"]) == "Shipped TickAL; Big win")
check("14.rule-anchor-monthly-title", pm.journal_key("🥅 Objective by objective, hit, partial or miss 0/1: what moved, what stalled, and why?") == "mobjectives"
      and pm.journal_key("🥅 Objective by objective, hit, partial or miss 0/1: hit, partial or miss, and the factor that decided it? Was the bar set too high or too low?") == "qobjectives")
check("14.highlight-body", pm.highlight_body("Nap") == ["Nap"] and pm.highlight_body("One\n\nTwo [x](https://u)\n- Three") == ["- One", "- Two x", "- Three"]
      and pm.highlight_body("") == [""])
qsec = ps.find(qdoc, pm.SEC_QTR_JNL)
qbody, qadded = pm.insert_fixed_questions(qsec.body, pm.journal_fixed("quarterly", qctx))
qkeys = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(qbody)]
check("14.old-quarterly-gains-the-set", qadded == ["qlowlights", "qobjectives", "ycheck", "qcompare", "habits", "qmoney", "qeffort", "qenergy", "qpriorities", "qforecast"]
      and qkeys == ["qhighlight", "qlowlights", "qgoals", "qobjectives", "ycheck", "qcompare", "habits", "qmoney", "qeffort", "qenergy", "qpriorities", "qforecast", "free"], (qadded, qkeys))
QPOOL = {"categories": {c: [f"{c}{i}?" for i in range(10)] for c in pm.QUARTERLY_CATEGORIES}, "chains": []}
qo1 = pm.select_prompts(QPOOL, pm.QUARTER_EPOCH, "quarterly")
check("14.quarterly-ten", len(qo1) == 10 and len(set(qo1)) == 10
      and [c for c in pm.QUARTERLY_CATEGORIES for _ in range(2)] == [next(c for c in pm.QUARTERLY_CATEGORIES if q in QPOOL["categories"][c]) for q in qo1], qo1)
check("14.quarterly-same-quarter-same-picks", pm.select_prompts(QPOOL, date(2026, 9, 30), "quarterly") == qo1 and pm.select_prompts(QPOOL, date(2026, 8, 15), "quarterly") == qo1)
qo2 = pm.select_prompts(QPOOL, date(2026, 10, 1), "quarterly")
check("14.quarterly-next-quarter-differs", len(qo2) == 10 and not set(qo1) & set(qo2), set(qo1) & set(qo2))
check("14.quarterly-year-boundary", len(pm.select_prompts(QPOOL, date(2027, 1, 1), "quarterly")) == 10
      and pm.select_prompts(QPOOL, date(2027, 3, 31), "quarterly") == pm.select_prompts(QPOOL, date(2027, 1, 1), "quarterly")
      and not set(pm.select_prompts(QPOOL, date(2027, 1, 1), "quarterly")) & set(pm.select_prompts(QPOOL, date(2026, 12, 31), "quarterly")))
check("14.quarterly-pre-epoch-old-style", len(pm.select_prompts(dict(QPOOL, random=[f"r{i}" for i in range(20)]), date(2026, 4, 1), "quarterly")) == 5)
QSHIP = pj.load_pool("quarterly")
check("14.shipped-pool-shape", set(QSHIP["categories"]) == set(pm.QUARTERLY_CATEGORIES) and all(len(v) == 6 for v in QSHIP["categories"].values())
      and not QSHIP.get("chains"), {k: len(v) for k, v in QSHIP["categories"].items()})
check("14.shipped-pool-clean", all(not re.search("[\\u2013\\u2014]", q) and q.strip()[-1] in "?." and q[0].isupper() for v in QSHIP["categories"].values() for q in v)
      and len({q for v in QSHIP["categories"].values() for q in v}) == 30)
QS = {q for v in QSHIP["categories"].values() for q in v}
check("14.shipped-pool-no-set-twins", not any("highlight" in q.casefold() or "lowlight" in q.casefold() or "three months" in q.casefold() and "want to be" in q.casefold() for q in QS))
qship = [pm.select_prompts(QSHIP, d, "quarterly") for d in (pm.QUARTER_EPOCH, date(2026, 10, 1), date(2027, 1, 1), date(2027, 4, 1))]
check("14.shipped-three-quarters-cover-all", all(len(x) == 10 for x in qship) and set().union(*qship[:3]) == QS
      and not (set(qship[0]) & set(qship[1]) or set(qship[1]) & set(qship[2]) or set(qship[2]) & set(qship[3])), len(set().union(*qship[:3])))

# ── 15. a note minted a day early gets its bridge and journals (Vex 2026-09-24: "literally nothing in there") ──
_real_today, _real_bridge = pe._today, pe._bridge_text
try:
    pe._today = lambda: date(2026, 9, 24)
    pe._bridge_text = lambda d: "Finished OKRs and debugged Periodics.\nQuarterly journal is next." if d == date(2026, 9, 24) else ""
    def shell(day):
        p = pm.period_for("daily", day)
        tpl = pe._load_template("daily")
        content = pm.render_template(tpl, {"breadcrumbs": "x", "daylinks": "", "weeklinks": "", "monthlinks": "", "quarterlinks": ""})
        return p, ps.parse_sections(content)
    p25, d25 = shell(date(2026, 9, 25))
    pe._fill_daily(d25, p25, {}, False)
    b = ps.find(d25, pm.SEC_YBRIDGE)
    mj, ej = ps.find(d25, pm.SEC_MORNING), ps.find(d25, pm.SEC_EVENING)
    mk = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(mj.body)]
    ek = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(ej.body)]
    check("15.tomorrow-gets-the-bridge", b is not None and [ln for ln in b.body if ln.strip()] == ["> Finished OKRs and debugged Periodics.", "> Quarterly journal is next."], b.body if b else None)
    # Fri 25 Sep is a chain night: the evening block is the chain's seven steps, the date's own draw either way
    ev_n = len(pm.select_prompts(pj.load_pool("evening"), date(2026, 9, 25), "evening"))
    check("15.tomorrow-gets-both-journals", mk[:4] == ["mood", "ybridge", "gcheck", "forecast"] and len(mk) == 5 + 6
          and ek[:4] == ["bridge", "dhighlight", "tgoal", "goal"] and len(ek) == 8 + ev_n and ev_n == 7, (mk, ek, ev_n))
    check("15.bridge-echo-in-the-morning-question", any("Yesterday's bridge: Finished OKRs and debugged Periodics." in q for _n, q, _a, _i in pm.journal_pairs(mj.body)))
    check("15.numbers-stay-pending", any("_(pending)_" in ln for ln in ps.find(d25, pm.SEC_HABITS).body), ps.find(d25, pm.SEC_HABITS).body)
    p26, d26 = shell(date(2026, 9, 26))
    pe._fill_daily(d26, p26, {}, False)
    check("15.day-after-tomorrow-stays-a-shell", not any(pm.JOURNAL_Q_RE.match(ln) for ln in ps.find(d26, pm.SEC_MORNING).body)
          and not any(pm.JOURNAL_Q_RE.match(ln) for ln in ps.find(d26, pm.SEC_EVENING).body))
finally:
    pe._today, pe._bridge_text = _real_today, _real_bridge

# ── 16. a chain step shows the earlier answers (Vex 2026-09-25: "I CANNOT SEE IT") ──
ev_chains = pj.load_pool("evening")["chains"]
worry = next(c for c in ev_chains if c["name"].lower() == "worry sort")
check("16.worry-nothing-to-circle", not any(w in s.lower() for s in worry["prompts"] for w in ("circle", "underline")))
check("16.worry-refers-by-number", "shown below" in worry["prompts"][1] and "your answer to 3" in worry["prompts"][3]
      and "items from 2" in worry["prompts"][6] and len(worry["prompts"]) == 7)
CH = [{"category": "review", "name": "t", "prompts": ["List A.", "From that list, name B.", "Pick one from 2."]}]
seen = [("List A.", "rent, the car, mum"), ("From that list, name B.", "the car")]
r = pm.chain_recap(CH, "Pick one from 2.", seen)
check("16.recap-shows-earlier-answers", r == "Your answers so far:\n1. rent, the car, mum\n2. the car", repr(r))
check("16.recap-step-one-empty", pm.chain_recap(CH, "List A.", seen) == "")
check("16.recap-not-a-chain-step", pm.chain_recap(CH, "What is on your mind?", seen) == "")
check("16.recap-skipped-step-named", pm.chain_recap(CH, "Pick one from 2.", [("List A.", "rent")]) == "Your answers so far:\n1. rent\n2. (not answered)")
check("16.recap-nothing-answered-yet", pm.chain_recap(CH, "Pick one from 2.", []) == "")
check("16.recap-whole-answer-one-line", pm.chain_recap(CH, "From that list, name B.", [("List A.", "rent\nthe car\n\nmum")]) == "Your answers so far:\n1. rent the car mum")
WB = ["\t- *Q1 · List A.*", "\t\t- A: rent, the car", "\t\t\t- and mum", "\t- *Q2 · From that list, name B.*", "\t\t- A: ", "\t- *Q3 · Pick one from 2.*", "\t\t- A: the car"]
wa = pm.journal_whole_answers(WB)
check("16.whole-answers", wa == {1: "rent, the car and mum", 3: "the car"}, repr(wa))
check("16.recap-escaped-question", pm.chain_recap(CH, "Pick one from 2\\.", seen).startswith("Your answers so far:"))

print(f"journal pools: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
