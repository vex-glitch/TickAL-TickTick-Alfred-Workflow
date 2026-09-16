#!/usr/bin/env python3
"""The daily goal prompts in the journals (Vex 2026-09-15).

Evening: after the bridge, "🎯 What is the goal for tomorrow?" pauses the
dialogs and opens the ☀️ goal picker aimed at tomorrow; the pick creates
tomorrow's note, answers the question and reopens the journal.
Morning: after the bridge, "☀️ Does your goal for today still align with: X?"
with Keep / Change… (Change… and no goal = the picker for today).
A picked task moves to that day keeping its time.

No network, no dialogs, no Alfred: the engine and the UI calls are faked.

    python3 tests/test_journal_goal.py
"""
import base64
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
os.environ["TICKAL_NO_SETTLE"] = "1"

import day_move  # noqa: E402
import goal_handoff as gh  # noqa: E402
import periodic_journal as pj  # noqa: E402
import periodic_model as pm  # noqa: E402
import periodic_engine as pe  # noqa: E402
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


# ── 1. the fixed heads ────────────────────────────────────────────────────────
ev = pm.journal_fixed("evening", {"goal": "Ship it"})
check("evening order: bridge, tomorrow's goal, mind, review, money, rating",
      [k for k, _ in ev] == ["bridge", "tgoal", "free", "goal", "money", "rating"], ev)
mo = pm.journal_fixed("morning", {"ybridge": "Call Anna", "goal": "Ship it"})
check("morning order: mood, bridge, goal check, mind",
      [k for k, _ in mo] == ["mood", "ybridge", "gcheck", "free"], mo)
check("the goal check names last night's goal", "Ship it" in mo[2][1], mo[2])
check("no goal = asks for today's goal",
      pm.journal_fixed("morning", {})[1] == ("gcheck", "☀️ What is today's goal?"))
check("the retired morning question is gone",
      not any("one thing you need to do today" in q for _, q in mo))

# ── 2. every fixed wording is recognised, nothing else is ─────────────────────
variants = (pm.journal_fixed("evening", {}) + pm.journal_fixed("evening", {"goal": "X"})
            + pm.journal_fixed("morning", {}) + pm.journal_fixed("morning", {"ybridge": "b", "goal": "g"})
            + pm.journal_fixed("weekly", {}) + pm.journal_fixed("weekly", {"goals": "A; B"}))
wrong = [(k, q) for k, q in variants if pm.journal_key(q) != k]
check("every fixed question maps to its own key", not wrong, wrong)
retired = "What is the one thing you need to do today? What would, if achieved, make this day count?"
check("retired and plain questions are free",
      pm.journal_key(retired) == "free" and pm.journal_key("What is on your mind?") == "free")
pool_hits = [(s, q, pm.journal_key(q)) for s in ("morning", "evening", "weekly")
             for q in (pj.load_pool(s).get("random") or []) + (pj.load_pool(s).get("constants") or [])
             if pm.journal_key(q) != "free"]
check("no pool prompt is mistaken for a fixed question", not pool_hits, pool_hits)

# the TickTick app backslash-escapes markdown when a note is edited there
# (seen on the 2026-09-14 note)
check("an app-escaped question is still recognised",
      pm.journal_key(r"Mood 1-5 \(1 😢 · 3 😐 · 5 😁\), optional note after ·") == "mood")
check("an app-escaped placeholder is NOT a goal",
      pm.day_goal_title([r"	- \_\(pick one - ☀️ in search, or the morning journal asks\)\_"]) == "")
check("a real goal with escapes reads clean",
      pm.day_goal_title([r"	- [ ] Ship \#1 release"]) == "Ship #1 release")

# ── 3. an evening journal seeded BEFORE the goal question existed ─────────────
OLD_EVENING = [
    "\t- *Q1 · 🌉 Daily bridge - what should tomorrow-you know? (saves to the Bridges board + tomorrow's note)*",
    "\t\t- A: call the printer",
    "\t- *Q2 · What is on your mind?*",
    "\t\t- A: ",
    "\t- *Q3 · Did you achieve your daily goal? Describe success/failure factors.*",
    "\t\t- A: ",
    "\t- *Q4 · How much money did you earn today?*",
    "\t\t- A: 120",
    "\t- *Q5 · Rate the day, 1-5 stars*",
    "\t\t- A: ",
    "\t- *Q6 · A random prompt?*",
    "\t\t- A: yes",
]
body, added = pm.insert_fixed_questions(OLD_EVENING, pm.journal_fixed("evening", {}))
pairs = pm.journal_pairs(body)
check("the goal question is inserted once", added == ["tgoal"], added)
check("right after the bridge", pm.journal_key(pairs[1][1]) == "tgoal", pairs[1])
check("numbered 1..7 in order", [n for n, *_ in pairs] == list(range(1, 8)), [n for n, *_ in pairs])
by_q = {q: a for _n, q, a, _i in pairs}
check("every answer stays under its own question",
      by_q[OLD_EVENING[0][len("\t- *Q1 · "):-1]] == "call the printer"
      and by_q["How much money did you earn today?"] == "120"
      and by_q["A random prompt?"] == "yes" and by_q[pairs[1][1]] == "", by_q)
again, added2 = pm.insert_fixed_questions(body, pm.journal_fixed("evening", {}))
check("a second run inserts nothing", added2 == [] and again == body)
check("routing follows the wording after the insert",
      pm.journal_keys(pairs) == {1: "bridge", 2: "tgoal", 3: "free", 4: "goal", 5: "money", 6: "rating", 7: "free"},
      pm.journal_keys(pairs))

# an old morning journal (mood, mind, the retired one-thing question)
OLD_MORNING = ["\t- *Q1 · Mood 1-5 (1 😢 · 3 😐 · 5 😁), optional note after ·*", "\t\t- A: 4 · ok",
               "\t- *Q2 · What is on your mind?*", "\t\t- A: ",
               f"\t- *Q3 · {retired}*", "\t\t- A: ", "\t- *Q4 · Pool?*", "\t\t- A: "]
mb, madd = pm.insert_fixed_questions(OLD_MORNING, pm.journal_fixed("morning", {"ybridge": "b", "goal": "g"}))
mk = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(mb)]
check("old morning gains the bridge echo and the goal check after mood, in order",
      madd == ["ybridge", "gcheck"] and mk[:3] == ["mood", "ybridge", "gcheck"], (madd, mk))
check("the mood answer is untouched", pm.journal_pairs(mb)[0][2] == "4 · ok")
check("an unseeded journal is left for the seeder",
      pm.insert_fixed_questions(["\t_(pending)_"], pm.journal_fixed("evening", {})) == (["\t_(pending)_"], []))

# a phone answer that runs onto a second bullet is never split by an insert
MULTI = ["\t- *Q1 · 🌉 Daily bridge - what should tomorrow-you know? (x)*", "\t\t- A: call the printer",
         "\t\t- and the bank", "", "\t- *Q2 · What is on your mind?*", "\t\t- A: "]
mbody, _ = pm.insert_fixed_questions(MULTI, pm.journal_fixed("evening", {}))
check("the insert lands after the answer's continuation lines",
      mbody[:3] == MULTI[:3] and "goal for tomorrow" in mbody[3], mbody)

# answers only land under the question they were asked for
FRESH = pm.seed_journal_lines(["Mood 1-5 (x) ·", "🌉 Yesterday's bridge: b - what carries into today?",
                               "☀️ Does your goal for today still align with: g?", "What is on your mind?", "Pool A?"])
STALE = pm.seed_journal_lines(["Mood 1-5 (x) ·", "☀️ Does your goal for today still align with: g?",
                               "What is on your mind?", "Pool A?"])           # a copy saved before the insert
asked = {n: q for n, q, _a, _i in pm.journal_pairs(FRESH)}
ans = {1: "4", 2: "carry on", 3: "✅ Kept: g", 4: "tired", 5: "pool answer"}
merged_s, filled_s = pm.merge_journal_answers(STALE, ans, asked)
got = {q: a for _n, q, a, _i in pm.journal_pairs(merged_s)}
check("on a stale copy each answer still finds its own question",
      got["☀️ Does your goal for today still align with: g?"] == "✅ Kept: g"
      and got["What is on your mind?"] == "tired" and got["Pool A?"] == "pool answer"
      and got["Mood 1-5 (x) ·"] == "4", got)
check("an answer whose question is gone is dropped, not misfiled",
      filled_s == 4 and "carry on" not in "\n".join(merged_s), merged_s)
merged_f, filled_f = pm.merge_journal_answers(FRESH, ans, asked)
check("the normal case fills everything", filled_f == 5, merged_f)

# the background seeder carries the bridge echo, so a run never has to insert it
bdoc = ps.parse_sections("\n".join([
    "#### 🌉 Yesterday's bridge", "> call the printer", "---", "#### 🏆 Goals", "- ☀️ Daily", "\t- [ ] Ship it",
    "---", "#### 📓 Journals", "- 🌅 Morning journal", "", "- 🌙 Evening journal", ""]))
pe._seed_daily_journals(bdoc, date(2026, 9, 16))
mkeys = [pm.journal_key(q) for _n, q, _a, _i in pm.journal_pairs(ps.find(bdoc, pm.SEC_MORNING).body)]
check("a morning seeded in the background already has the bridge echo and the goal check",
      mkeys[:4] == ["mood", "ybridge", "gcheck", "free"], mkeys)
_b2, again_added = pm.insert_fixed_questions(ps.find(bdoc, pm.SEC_MORNING).body,
                                             pm.journal_fixed("morning", pe.journal_ctx("morning", bdoc)))
check("so the morning run inserts nothing (no daily renumbering)", again_added == [], again_added)

# ── 4. refreshing question text is by key, never by position ──────────────────
import periodic_engine as pe  # noqa: E402
import periodic_sections as ps  # noqa: E402

sec = ps.Section("#### 🌙 Evening journal", "🌙 Evening journal", body=list(OLD_EVENING))
pe._refresh_fixed_q(sec, pm.journal_fixed("evening", {"goal": "Ship it"}))
check("an old Q2 'What is on your mind?' is NOT rewritten into the goal question",
      "What is on your mind?" in sec.body[2], sec.body[2])
check("the unanswered review picks up today's goal text", "Ship it" in sec.body[4], sec.body[4])
check("an answered question keeps its words", "Daily bridge" in sec.body[0])
msec = ps.Section("h", "n", body=["\t- *Q1 · ☀️ Does your goal for today still align with: old?*", "\t\t- A: "])
pe._refresh_fixed_q(msec, pm.journal_fixed("morning", {"goal": "new goal"}))
check("the goal check follows a changed goal while unanswered", "new goal" in msec.body[0], msec.body)

# ── 5. moving the goal task, keeping its time ─────────────────────────────────
BER = ZoneInfo("Europe/Berlin")
t16 = {"startDate": "2026-09-15T14:00:00.000+0000", "dueDate": "2026-09-15T15:30:00.000+0000", "isAllDay": False}
f, how = day_move.move_fields(t16, date(2026, 9, 16), BER)
check("a 16:00-17:30 task lands tomorrow 16:00-17:30",
      how == "timed" and f == {"startDate": "2026-09-16T14:00:00+0000", "dueDate": "2026-09-16T15:30:00+0000",
                               "isAllDay": False}, f)
f, _ = day_move.move_fields(t16, date(2026, 10, 26), BER)      # the day after DST ends
check("across the October clock change it is still 16:00 local",
      f["startDate"] == "2026-10-26T15:00:00+0000", f)
allday = {"startDate": "2026-09-14T22:00:00.000+0000", "isAllDay": True}
f, how = day_move.move_fields(allday, date(2026, 9, 16), BER)
check("an all-day task stays all-day on the new day",
      how == "all-day" and f["startDate"] == "2026-09-15T22:00:00+0000" == f["dueDate"], f)
f, how = day_move.move_fields({}, date(2026, 9, 16), BER)
check("an undated task becomes all-day tomorrow", how == "all-day" and f["startDate"] == "2026-09-15T22:00:00+0000", f)
check("a repeating task is left alone",
      day_move.move_fields(dict(t16, repeatFlag="RRULE:FREQ=DAILY"), date(2026, 9, 16), BER) == (None, "repeats"))
f, _ = day_move.move_fields({"startDate": "2026-09-15T14:00:00Z"}, date(2026, 9, 17), BER)
check("a Z-suffixed date parses", f["startDate"] == "2026-09-17T14:00:00+0000", f)
t02 = {"startDate": "2026-09-15T00:00:00.000+0000", "dueDate": "2026-09-15T01:00:00.000+0000", "isAllDay": False}
f, how = day_move.move_fields(t02, date(2026, 9, 16), BER)
check("a 02:00 CEST task (00:00 UTC) stays timed, stated explicitly",
      how == "timed" and f["isAllDay"] is False and f["startDate"] == "2026-09-16T00:00:00+0000", f)
check("an all-day move states isAllDay", day_move.move_fields({}, date(2026, 9, 16), BER)[0]["isAllDay"] is True)
check("a finished task is left alone",
      day_move.move_fields(dict(t16, status=2), date(2026, 9, 16), BER) == (None, "done"))
check("occurs_on reads the local day",
      day_move.occurs_on({"startDate": "2026-09-15T22:30:00.000+0000"}, date(2026, 9, 16), BER))
check("a local-midnight time without the flag counts as untimed",
      not day_move.is_timed({"startDate": "2026-09-14T22:00:00.000+0000"}, BER))

import api as _api_mod  # noqa: E402


class _Resp:
    status_code, text = 200, "{}"

    def json(self):
        return {}

    def raise_for_status(self):
        return None


class _Sess:
    def __init__(self):
        self.posted = None

    def post(self, url, json=None):
        self.posted = json
        return _Resp()


_c = _api_mod.TickTickAPI.__new__(_api_mod.TickTickAPI)
_c.session = _Sess()
_c.update_task("T", "P", current={"id": "T", "projectId": "P"},
               startDate="2026-09-16T00:00:00+0000", dueDate="2026-09-16T01:00:00+0000", isAllDay=False)
check("update_task keeps an explicit isAllDay over its 00:00 UTC guess",
      _c.session.posted["isAllDay"] is False, _c.session.posted)
_c.update_task("T", "P", current={"id": "T", "projectId": "P"}, startDate="2026-09-16T00:00:00+0000")
check("and still guesses when none is given", _c.session.posted["isAllDay"] is True)

# the goal task decisions (API faked)
class _FakeAPI:
    def __init__(self, task):
        self.task, self.posts = task, []

    def get_task(self, pid, tid):
        return dict(self.task)

    def update_task(self, tid, pid, current=None, **fields):
        self.posts.append(fields)
        return dict(self.task, **fields)


_orig_api = pe._api
fa = _FakeAPI({"id": "T", "projectId": "P", "title": "Brief", "status": 0,
               "startDate": "2026-09-15T07:00:00.000+0000", "dueDate": "2026-09-15T08:00:00.000+0000"})
pe._api = lambda: fa
info = pe._goal_task_to_day("P", "T", date(2026, 9, 16), "Brief")
check("a timed goal task moves, goes in Tasks with its clock",
      info["merge"] and info["suffix"] == "" and info["label"].startswith("Brief · ")
      and fa.posts and fa.posts[0]["isAllDay"] is False, info)
fa = _FakeAPI({"id": "T", "projectId": "P", "title": "Review", "status": 0, "repeatFlag": "RRULE:FREQ=WEEKLY",
               "startDate": "2026-09-20T07:00:00.000+0000"})
pe._api = lambda: fa
info = pe._goal_task_to_day("P", "T", date(2026, 9, 16), "Review")
check("a repeat due another day is not moved and stays out of that day's Tasks",
      not info["merge"] and not fa.posts and "not in Tasks" in info["suffix"], info)
fa = _FakeAPI({"id": "T", "projectId": "P", "title": "Done one", "status": 2})
pe._api = lambda: fa
info = pe._goal_task_to_day("P", "T", date(2026, 9, 16), "Done one")
check("a finished task is not moved and not listed", not info["merge"] and not fa.posts
      and "already done" in info["suffix"], info)
pe._api = _orig_api

# ── 6. the handoff state ──────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
gh._PATH = os.path.join(tmp, "goaljnl.json")
st = gh.save("evening", date(2026, 9, 15), now=1000.0)
ld = gh.load(now=1500.0)
check("evening handoff is FOR tomorrow",
      ld and ld["for_day"] == date(2026, 9, 16) and ld["note_day"] == date(2026, 9, 15) and ld["mode"] == "set", ld)
check("it expires", gh.load(now=1000.0 + gh.TTL + 1) is None)
gh.save("morning", date(2026, 9, 16), mode="changed", now=1000.0)
ld = gh.load(now=1001.0)
check("morning handoff is for its own day, mode kept",
      ld["for_day"] == date(2026, 9, 16) and ld["mode"] == "changed", ld)
gh.clear()
check("clear removes it", gh.load(now=1001.0) is None)
gh._SKIPS = os.path.join(tmp, "skips.json")
gh.remember_skips("evening", date(2026, 9, 15), ["Q bridge"], now=1000.0)
gh.remember_skips("evening", date(2026, 9, 15), ["Q bridge", "Q mind"], now=1000.0)
check("skips accumulate per run, deduped, and are taken once",
      gh.take_skips("evening", date(2026, 9, 15), now=1001.0) == ["Q bridge", "Q mind"]
      and gh.take_skips("evening", date(2026, 9, 15), now=1001.0) == [])
check("answer wording", (gh.answer_text("evening", "set", "Ship"), gh.answer_text("morning", "kept", "Ship"),
                         gh.answer_text("morning", "changed", "New"), gh.answer_text("evening", "skip"))
      == ("🎯 Ship", "✅ Kept: Ship", "🔄 Changed to: New", "⏭ No goal set"))

# ── 7. the picker screen a paused journal opens ───────────────────────────────
import periodic_rows as pr  # noqa: E402


def payload(arg):
    return json.loads(base64.b64decode(arg.split(":", 2)[2]))


pr.cache_store.get = lambda k: [{"id": "T1", "projectId": "P", "title": "Write the brief", "status": 0}] \
    if k == "all_tasks" else None
jnl = {"slot": "evening", "mode": "set", "note_day": date(2026, 9, 15), "for_day": date(2026, 9, 16)}
rows = pr.tier_goal_rows("daily", "Ship it", jnl=jnl)
first = rows[0]
check("the text row is aimed at tomorrow", "Tomorrow (Wed 16 Sep)" in first["title"], first["title"])
p0 = payload(first["arg"])
check("each pick carries the handoff",
      p0["jnl"] == {"slot": "evening", "mode": "set", "note_day": "2026-09-15", "for_day": "2026-09-16"}, p0)
check("⇥ to a task keeps the journal screen", first.get("autocomplete") == "pn goals journal Ship it | ")
skip = rows[-1]
check("🔙 Back becomes ⏭ No goal tonight",
      skip["title"] == "⏭ No goal tonight" and skip["arg"].startswith("xact:pn_goal_skip:"), skip)
plain = pr.tier_goal_rows("daily", "Ship it")
check("the ordinary goal screen is unchanged", plain[-1]["title"] == "🔙 Back"
      and "jnl" not in payload(plain[0]["arg"]))
orig_load = gh.load
gh.load = lambda now=None: None
exp = pr.rows("goals journal Ship") if hasattr(pr, "rows") else None
gh.load = orig_load
check("an EXPIRED journal goal screen is one dead row, never the today picker",
      exp is not None and len(exp) == 1 and exp[0]["valid"] is False and "expired" in exp[0]["title"], exp)
chg = pr.tier_goal_rows("daily", "", jnl=dict(jnl, slot="morning", mode="changed", for_day=date(2026, 9, 16)))
check("after Change… the way out keeps the goal", chg[-1]["title"] == "↩️ Keep the current goal", chg[-1])

# ── 8. the journal run itself, with the dialogs faked ─────────────────────────
import xact  # noqa: E402


class FakePE:
    def __init__(self, pairs, goal=""):
        self.pairs, self.goal = pairs, goal
        self.merged, self.goal_calls, self.answers = {}, [], []

    def journal_seed(self, slot, day=None):
        class P:
            start = date(2026, 9, 15)
        return pm.journal_keys(self.pairs), self.pairs, P()

    def journal_merge(self, slot, answers, period=None, questions=None):
        self.merged.update(answers)
        self.asked = questions
        return len(answers)

    def day_goal_on(self, day):
        return self.goal

    def set_period_goal(self, kind, text, pid, tid, title, day=None):
        self.goal_calls.append((kind, text, pid, tid, title, day))
        return "🎯 ☀️ Daily Wed 16 Sep · x"

    def journal_answer_key(self, slot, key, text, day):
        self.answers.append((slot, key, text, day))
        return True


calls = {"ask": [], "dialog": [], "trigger": [], "bg": [], "say": []}
xact._pn_gate = lambda: True
xact._crm_say = lambda m: calls["say"].append(m)
xact._run_trigger = lambda name, arg="": calls["trigger"].append((name, arg))
xact._pn_bg = lambda arg: calls["bg"].append(arg)
xact.bridge_from_answer = lambda a, d: "🌉 bridged"


def run(slot, pairs, answers=None, button="", goal=""):
    for v in calls.values():
        v.clear()
    fake = FakePE(pairs, goal)
    xact._pn = lambda: fake
    queue = list(answers or [])
    xact._ask = lambda q, title="", multiline=False: calls["ask"].append(q) or (queue.pop(0) if queue else None)
    xact._dialog = lambda prompt, buttons, default: calls["dialog"].append(prompt) or button
    saved = []
    orig = gh.save
    gh.save = lambda s, d, mode="set", now=None: saved.append((s, d, mode))
    try:
        xact.pn_journal(slot)
    finally:
        gh.save = orig
    return fake, saved


EV_PAIRS = pm.journal_pairs(pm.seed_journal_lines([q for _k, q in pm.journal_fixed("evening", {})] + ["Pool?"]))
fake, saved = run("evening", EV_PAIRS, answers=["the bridge"])
check("evening: the bridge is asked, then the run stops at tomorrow's goal",
      len(calls["ask"]) == 1 and saved == [("evening", date(2026, 9, 15), "set")], (calls["ask"], saved))
check("the bridge answer is saved before the picker opens", fake.merged == {1: "the bridge"}, fake.merged)
check("the picker opens on the journal goal screen", calls["trigger"] == [("Search", "pn goals journal ")], calls["trigger"])

MO_PAIRS = pm.journal_pairs(pm.seed_journal_lines(
    [q for _k, q in pm.journal_fixed("morning", {"goal": "Ship it"})] + ["Pool?"]))
MO_PAIRS[0] = (1, MO_PAIRS[0][1], "4", MO_PAIRS[0][3])            # mood already answered
fake, saved = run("morning", MO_PAIRS, answers=["mind", "pool"], button="Keep", goal="Ship it")
check("morning Keep: answered as kept, the journal carries on",
      fake.merged.get(2) == "✅ Kept: Ship it" and len(calls["ask"]) == 2 and not saved, (fake.merged, saved))
check("the Keep dialog shows the goal", calls["dialog"] and "Ship it" in calls["dialog"][0])
fake, saved = run("morning", MO_PAIRS, button="Change…", goal="Ship it")
check("morning Change…: stops for the picker in changed mode",
      saved == [("morning", date(2026, 9, 15), "changed")] and calls["trigger"], saved)
fake, saved = run("morning", MO_PAIRS, goal="")
check("morning with no goal: straight to the picker, no dialog",
      saved == [("morning", date(2026, 9, 15), "set")] and not calls["dialog"], saved)
fake, saved = run("morning", MO_PAIRS, button="", goal="Ship it")
check("Esc on the goal check cancels, no picker", not saved and not calls["trigger"], (saved, calls["trigger"]))
fake, saved = run("morning", MO_PAIRS, button="Cancel", goal="Ship it")
check("the goal check has a real Cancel button", not saved and not calls["trigger"]
      and calls["dialog"], (saved, calls["dialog"]))

# a question skipped before the pause stays skipped after the pick reopens the run
gh.take_skips("evening", date(2026, 9, 15))
fake, saved = run("evening", EV_PAIRS, answers=[""])                 # skip the bridge
check("skipping the bridge still pauses at tomorrow's goal", saved and not fake.merged, (saved, fake.merged))
for v in calls.values():
    v.clear()
fake2 = FakePE(EV_PAIRS)
xact._pn = lambda: fake2
xact._ask = lambda q, title="", multiline=False: calls["ask"].append(q) or ""
_saved2 = []
_o = gh.save
gh.save = lambda s_, d, mode="set", now=None: _saved2.append(s_)
try:
    xact.pn_journal("evening@2026-09-15")
finally:
    gh.save = _o
check("the resumed run does not ask the skipped bridge again", calls["ask"] == [], calls["ask"])

# a fresh run supersedes a goal screen an earlier run left open
gh._PATH = os.path.join(tmp, "goaljnl.json")
_o = gh.save
gh.save = _o
gh.save("morning", date(2026, 9, 15), now=None)
run("evening", pm.journal_pairs(pm.seed_journal_lines(["What is on your mind?"])), answers=["x"])
check("a fresh journal run clears an old goal screen", gh.load() is None)

# the pick on that screen
for v in calls.values():
    v.clear()
fake = FakePE([])
xact._pn = lambda: fake
gh.clear()
spec = {"kind": "daily", "text": "Ship it", "pid": "P", "tid": "T1", "title": "Write the brief",
        "jnl": {"slot": "evening", "mode": "set", "note_day": "2026-09-15", "for_day": "2026-09-16"}}
xact.pn_setgoal(base64.b64encode(json.dumps(spec).encode()).decode())
check("the pick sets the ☀️ goal on TOMORROW",
      fake.goal_calls == [("daily", "Ship it", "P", "T1", "Write the brief", date(2026, 9, 16))], fake.goal_calls)
check("and answers tonight's question with it",
      fake.answers == [("evening", "tgoal", "🎯 Ship it · Write the brief", date(2026, 9, 15))], fake.answers)
check("then reopens the journal pinned to tonight's note",
      calls["bg"] == ["xact:pn_journal:evening@2026-09-15"], calls["bg"])

for v in calls.values():
    v.clear()
fake = FakePE([])
xact._pn = lambda: fake
xact.pn_goal_skip(base64.b64encode(json.dumps(
    {"slot": "morning", "mode": "set", "note_day": "2026-09-16", "for_day": "2026-09-16"}).encode()).decode())
check("⏭ answers the morning check and resumes",
      fake.answers == [("morning", "gcheck", "⏭ No goal set", date(2026, 9, 16))]
      and calls["bg"] == ["xact:pn_journal:morning@2026-09-16"], (fake.answers, calls["bg"]))

for v in calls.values():
    v.clear()
fake = FakePE([])
xact._pn = lambda: fake
spec["jnl"] = {"slot": "bogus"}
xact.pn_setgoal(base64.b64encode(json.dumps(spec).encode()).decode())
check("a broken handoff writes nothing", not fake.goal_calls and not fake.answers and not calls["bg"])

# the goal did not land: the question stays open, nothing resumes
for v in calls.values():
    v.clear()
fake = FakePE([])
fake.set_period_goal = lambda *a, **k: "💫 No ☀️ Daily section in the daily note"
xact._pn = lambda: fake
spec["jnl"] = {"slot": "evening", "mode": "set", "note_day": "2026-09-15", "for_day": "2026-09-16"}
xact.pn_setgoal(base64.b64encode(json.dumps(spec).encode()).decode())
check("a failed goal write leaves the journal question open", not fake.answers and not calls["bg"], fake.answers)

# Change… then the way out: the goal stays and the answer says kept
for v in calls.values():
    v.clear()
fake = FakePE([], goal="Ship it")
xact._pn = lambda: fake
xact.pn_goal_skip(base64.b64encode(json.dumps(
    {"slot": "morning", "mode": "changed", "note_day": "2026-09-16", "for_day": "2026-09-16"}).encode()).decode())
check("Change… then keep answers 'Kept', not 'No goal'",
      fake.answers == [("morning", "gcheck", "✅ Kept: Ship it", date(2026, 9, 16))], fake.answers)

# ── 9. the review of the 04:30 run ────────────────────────────────────────────
tasks = ["\t- [ ] [Write the brief · 18:00](https://ticktick.com/webapp/#p/P/tasks/aaaaaaaaaaaaaaaaaaaaaaaa)"]
merged, n = pm.merge_checkboxes(tasks, [("P", "bbbbbbbbbbbbbbbbbbbbbbbb", "Dentist · 08:00")], indent=pm.T2)
check("04:30's tasks land beside the evening goal line, not a tab deeper",
      n == 1 and all(ln.startswith("\t- [ ]") and not ln.startswith("\t\t") for ln in merged), merged)
check("an empty list still takes the caller's indent",
      pm.merge_checkboxes([], [("P", "cccccccccccccccccccccccc", "X")], indent=pm.T2)[0][0].startswith("\t\t- [ ]"))
check("00:30 is still the day that is ending", xact._before_day_rollover(datetime(2026, 9, 16, 0, 30)))
check("04:30 is the new day", not xact._before_day_rollover(datetime(2026, 9, 16, 4, 30)))
check("22:30 is the same day", not xact._before_day_rollover(datetime(2026, 9, 15, 22, 30)))
seen = {}


class _PinPE(FakePE):
    def journal_seed(self, slot, day=None):
        seen["day"] = day
        return FakePE.journal_seed(self, slot, day)


_ro = xact._before_day_rollover
xact._before_day_rollover = lambda now=None: True
xact._pn = lambda: _PinPE(pm.journal_pairs(pm.seed_journal_lines(["What is on your mind?"])))
xact._ask = lambda q, title="", multiline=False: None
xact.pn_journal("evening")
check("an evening journal started after midnight writes the day that is ending",
      seen.get("day") == date.today() - __import__("datetime").timedelta(days=1), seen)
seen.clear()
xact.pn_journal("morning")
check("the morning journal is never shifted", seen.get("day") is None, seen)
xact._before_day_rollover = _ro

print(f"journal goal: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
