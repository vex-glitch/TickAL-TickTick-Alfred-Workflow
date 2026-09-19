#!/usr/bin/env python3
"""The 🔮 plan rows on every goal picker (HANDOFF_OKR section 4, phase 4).

Vex 2026-09-19: "We could when setting goals have two rows: 1. First row
could say something like: '<mimic objective or key result for respective
period>', enter would set that as goal. 2. Second row could say something
like: 'Pick a goal' and open goal picker as is."

Rendered the way everything_search runs them (periodic_rows.tier_goal_rows /
goal_rows, the `pn goals <tier> ` and `pn goal ` screens) against a FAKE
cache in a temp dir. No network and no write anywhere real: okr.load and
the api raise if touched, periodic_engine.period_goals is a stub that
records what it was asked, okr_list_id and periodic_list_id ride env.
The dates are built around today, so every period is stable on any day.

What it pins down:
  * the plan comes from the CACHE (okr_write.cached_plan), only on an
    empty bar, through okr_notes.goal_choices (the notes' own selection)
  * the period is the screen's own: today's, the next one while a journal
    handoff runs ahead, the journal's for_day on the handoff screen
  * a 🔮 pick targets the LINKED ORIGINAL, never the planning copy: a
    daily goal from a task MOVES that task onto the day
  * done / won't-do items and goals already set are not offered
  * 📋 Pick a goal follows the 🔮 rows, and the pool is exactly as before
  * every row carries the screen's own chords (_mods)

    python3 tests/test_okr_pickers.py
"""
import base64
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
os.environ["TICKAL_NO_SETTLE"] = "1"

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


PID = "5eed00000000000000000a01"          # the fake OKR list
PNP = "5eed00000000000000000a02"          # the fake periodic list
REALP, REALT, REALT2 = "5eed00000000000000000b01", "5eed00000000000000000b02", "5eed00000000000000000b03"
OLDP = "5eed00000000000000000b09"         # where REALT lived when its link was pasted
MISSP, MISST = "5eed00000000000000000c01", "5eed00000000000000000c02"
LISTP = "5eed00000000000000000d01"
OTHERP, OTHERT = "5eed00000000000000000e01", "5eed00000000000000000e02"
TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


def day(n):
    return TODAY + timedelta(days=n)


def T(tid, title, s=None, e=None, parent=None, status=0, pid=PID, **kw):
    st = f"{s.isoformat()}T00:00:00+0000" if s else None
    du = f"{(e + timedelta(days=1)).isoformat()}T00:00:00+0000" if s else None
    t = {"id": tid, "projectId": pid, "title": title, "startDate": st, "dueDate": du,
         "timeZone": "", "isAllDay": True, "status": status, "parentId": parent,
         "childIds": [], "tags": [], "_projectId": pid}
    t.update(kw)
    return t


def link(pid, tid):
    return f"https://ticktick.com/webapp/#p/{pid}/tasks/{tid}"


# The plan. A Y over an O whose KRs sit on today / tomorrow / next week, in
# every link shape: a task link (to a task that moved lists since), a text
# KR, a link to a task the cache does not know, a link pointing back INTO
# the plan list (a copy of a copy), a done KR and a won't-do KR on today;
# a loose O linking a LIST, and a done O.
Y1, O1, O2, ODONE = "y1", "o1", "o2", "odone"
KLINK, KTEXT, KDONE, KGONE, KCOPY, KWONT = "klink", "ktext", "kdone", "kgone", "kcopy", "kwont"
KTMRW, KNEXT, KNEXTL = "ktmrw", "knext", "knextl"
PLAN = [
    T(Y1, "🏔️ Y • Productivity System"),
    T(O1, "🥅 O • TickAL", parent=Y1),
    T(KLINK, f"🔑 KR • [Goals wf]({link(OLDP, REALT)}) - TA", day(0), day(2), parent=O1),
    T(KTEXT, "🔑 KR • Review - TA", day(0), day(0), parent=O1),
    T(KDONE, "🔑 KR • Kickoff - TA", day(-1), day(0), parent=O1, status=2),
    T(KGONE, f"🔑 KR • [Lost thing]({link(MISSP, MISST)}) - TA", day(0), day(0), parent=O1),
    T(KCOPY, f"🔑 KR • [Copy of review]({link(PID, KTEXT)}) - TA", day(0), day(0), parent=O1),
    T(KWONT, "🔑 KR • Dropped - TA", day(0), day(0), parent=O1, status=-1),
    T(KTMRW, "🔑 KR • Tomorrow only - TA", day(1), day(1), parent=O1),
    T(KNEXT, "🔑 KR • Next week thing - TA", day(7), day(7), parent=O1),
    T(KNEXTL, f"🔑 KR • [Ship the second]({link(REALP, REALT2)}) - TA", day(7), day(7), parent=O1),
    T(O2, f"🥅 O • [Onboard](ticktick:///webapp/#p/{LISTP}/tasks)", day(0), day(3)),
    T(ODONE, "🥅 O • Closed thing", day(-2), day(0), status=2),
]
PLAN_IDS = {t["id"] for t in PLAN}
OTHERS = [
    T(REALT, "Goals workflow (the real one)", pid=REALP),
    T(REALT2, "Second real thing", pid=REALP),
    T(OTHERT, "Buy stamps", pid=OTHERP),
]


def day_note(d, goal_line):
    title = f"{d.isoformat()} · {('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.weekday()]}"
    content = ("#### 🏆 Goals\n- 🗓️ Weekly\n\t- _(mirrors this week's weekly note - edit goals there)_\n\n"
               f"- ☀️ Daily\n\t{goal_line}\n---\n#### ⚔️ Workbench\n- ✅ Tasks\n")
    return {"id": f"pn-{d.isoformat()}", "projectId": PNP, "title": title,
            "content": content, "kind": "NOTE", "status": 0}


def payload(arg, prefix="xact:pn_setgoal:"):
    assert arg.startswith(prefix), arg
    return json.loads(base64.b64decode(arg[len(prefix):]).decode("utf-8"))


def plan_rows(rows):
    return [r for r in rows if r["title"].startswith("🔮 ")]


def names(rows):
    """"🔑 Goals wf" of "🔮 🔑 Goals wf": the glyph says the level."""
    return {r["title"][len("🔮 "):] for r in plan_rows(rows)}


def by_name(rows, name):
    return next((r for r in plan_rows(rows) if r["title"][len("🔮 "):] == name), None)


tmp = tempfile.mkdtemp(prefix="okr_pickers_")
_env = dict(os.environ)
try:
    os.environ["okr_list_id"] = PID
    os.environ["periodic_list_id"] = PNP
    import cache                                           # noqa: E402
    cache.CACHE_DIR = os.path.join(tmp, "cache")
    os.makedirs(cache.CACHE_DIR, exist_ok=True)
    cache.set("all_tasks", PLAN + OTHERS)
    cache.set(f"project_data_{PID}", {"project": {"id": PID}, "tasks": [t for t in PLAN
                                                                         if t["status"] == 0]})
    cache.set("completed_tasks", [t for t in PLAN if t["status"] in (2, -1)])
    cache.set("all_notes", [])

    import okr                                             # noqa: E402

    def _no_network(*a, **k):
        raise AssertionError("the goal screens never read the network for the plan")
    okr.load = _no_network
    import api                                             # noqa: E402
    api.TickTickAPI.__init__ = _no_network

    import okr_write                                       # noqa: E402
    PLAN_READS = []
    _cached_plan = okr_write.cached_plan

    def counting_plan(list_id):
        PLAN_READS.append(list_id)
        return _cached_plan(list_id)
    okr_write.cached_plan = counting_plan

    import okr_notes                                       # noqa: E402
    CHOICES = []
    _goal_choices = okr_notes.goal_choices

    def spy_choices(kind, start, end, items, today):
        CHOICES.append((kind, start, end, len(items), today))
        return _goal_choices(kind, start, end, items, today)
    okr_notes.goal_choices = spy_choices

    import periodic_model as pm                            # noqa: E402
    import periodic_engine as pe                           # noqa: E402
    HAVE = {}
    GOAL_ASKS = []

    def fake_period_goals(kind, ahead=False, day=None):
        GOAL_ASKS.append((kind, ahead))
        return list(HAVE.get((kind, ahead), []))
    pe.period_goals = fake_period_goals

    import periodic_rows as pr                             # noqa: E402
    pr._goalseq_active = lambda kind=None: None

    WANT_MODS = pr._mods()

    def check_chords(screen, rows):
        bad = [r["title"] for r in rows if set((r.get("mods") or {})) != set(WANT_MODS)]
        check(f"{screen}: every row spells out the screen's chords", not bad, bad)
        bad = [r["title"] for r in plan_rows(rows) + [r for r in rows if r["title"] == "📋 Pick a goal"]
               if r["mods"] != WANT_MODS]
        check(f"{screen}: 🔮 and 📋 rows carry exactly _mods()", not bad, bad)
        ids = [id(m) for r in rows for m in r["mods"].values()] + [id(r["mods"]) for r in rows]
        check(f"{screen}: no mods dict shared between rows", len(ids) == len(set(ids)))
        bad = [r["title"] for r in rows if r["mods"]["ctrl"].get("arg") != ""]
        check(f"{screen}: ⌃ is the empty-arg back on every row", not bad, bad)

    def check_originals(screen, rows):
        pays = [payload(r["arg"]) for r in plan_rows(rows)]
        bad = [p for p in pays if p.get("tid") in PLAN_IDS or p.get("pid") == PID]
        check(f"{screen}: no 🔮 row ever targets a planning copy", not bad, bad)

    # ── ☀️ daily, today ──────────────────────────────────────────────────────
    os.environ["okr_list_id"] = ""
    BASE_DAILY = [r["title"] for r in pr.tier_goal_rows("daily", "")]
    os.environ["okr_list_id"] = PID
    PLAN_READS.clear()
    CHOICES.clear()
    rows = pr.tier_goal_rows("daily", "")
    check("daily: the plan is read once, from the cache", PLAN_READS == [PID], PLAN_READS)
    check("daily: through okr_notes.goal_choices for today",
          CHOICES == [("daily", TODAY, TODAY, len(PLAN), TODAY)], CHOICES)
    check("daily: one 🔮 per OPEN KR on today, nothing done, won't-do, later or above",
          names(rows) == {"🔑 Goals wf", "🔑 Review", "🔑 Lost thing", "🔑 Copy of review"},
          names(rows))
    check("daily: the 🔮 rows lead the screen", rows[0]["title"].startswith("🔮 "), rows[0])
    n = len(plan_rows(rows))
    pick = rows[n]
    check("daily: 📋 Pick a goal right after them, invalid",
          pick["title"] == "📋 Pick a goal" and pick["valid"] is False
          and pick["subtitle"] == "Type to search every task", pick)
    # the pool as it is with OKRs off, minus the planning copies: with OKRs
    # on they never enter it (a daily goal would MOVE the copy onto the day)
    COPY = ("📋 🏔️", "📋 🥅", "📋 🔑")
    check("daily: then the screen as it is with OKRs off, the planning copies left out",
          [r["title"] for r in rows[n + 1:]] == [x for x in BASE_DAILY if not x.startswith(COPY)]
          and any(t.startswith("📋 Buy stamps") for t in BASE_DAILY), ([r["title"] for r in rows], BASE_DAILY))
    r = by_name(rows, "🔑 Goals wf")
    p = payload(r["arg"])
    check("daily: a task-linked KR sets the LINKED ORIGINAL (its list today, its cached title)",
          (p["kind"], p["text"], p["pid"], p["tid"], p["title"])
          == ("daily", "", REALP, REALT, "Goals workflow (the real one)"), p)
    check("daily: the subtitle says the span, the plan, and what ⏎ does",
          r["subtitle"] == f"{okr.span_txt(day(0), day(2), TODAY)} · the plan  |  ⏎ The ☀️ Daily goal",
          r["subtitle"])
    p = payload(by_name(rows, "🔑 Review")["arg"])
    check("daily: a text-only KR sets a text goal with its name",
          p["text"] == "Review" and "tid" not in p, p)
    p = payload(by_name(rows, "🔑 Lost thing")["arg"])
    check("daily: a link the cache does not know still targets it, titled by the plan",
          (p["pid"], p["tid"], p["title"], p["text"]) == (MISSP, MISST, "Lost thing", ""), p)
    p = payload(by_name(rows, "🔑 Copy of review")["arg"])
    check("daily: a link back INTO the plan list is a text goal, never the copy",
          p["text"] == "Copy of review" and "tid" not in p, p)
    check_chords("daily", rows)
    check_originals("daily", rows)

    # typed: no plan, no network, no 🔮 / 📋
    PLAN_READS.clear()
    typed = pr.tier_goal_rows("daily", "stamps")
    check("typed bar: the plan is not even read", PLAN_READS == [], PLAN_READS)
    check("typed bar: no 🔮 and no 📋 Pick a goal",
          not plan_rows(typed) and not any(r["title"] == "📋 Pick a goal" for r in typed))

    # the day's goal is already a plan item: not offered again
    cache.set("all_notes", [day_note(TODAY, f"- [ ] [Goals workflow]({link(REALP, REALT)})")])
    rows = pr.tier_goal_rows("daily", "")
    check("daily: today's goal (by its task link) is not offered again",
          "🔑 Goals wf" not in names(rows) and "🔑 Review" in names(rows), names(rows))
    cache.set("all_notes", [day_note(TODAY, "- [ ] Review")])
    rows = pr.tier_goal_rows("daily", "")
    check("daily: nor a text goal by its words", "🔑 Review" not in names(rows), names(rows))
    cache.set("all_notes", [])

    # ── ♻️ weekly: this week, then ahead ────────────────────────────────────
    wk = pm.period_for("weekly", TODAY)
    HAVE.clear()
    GOAL_ASKS.clear()
    CHOICES.clear()
    rows = pr.tier_goal_rows("weekly", "")
    want = {"🔑 Goals wf", "🔑 Review", "🔑 Lost thing", "🔑 Copy of review"}
    if TOMORROW <= wk.end:
        want.add("🔑 Tomorrow only")
    check("weekly: the open KRs overlapping this week", names(rows) == want, names(rows))
    check("weekly: goal_choices asked for this week",
          CHOICES and CHOICES[0][:3] == ("weekly", wk.start, wk.end), CHOICES)
    check("weekly: 'have' read for this week", GOAL_ASKS == [("weekly", False)], GOAL_ASKS)
    check_chords("weekly", rows)
    check_originals("weekly", rows)

    pr._goalseq_active = lambda kind=None: {"kind": "weekly", "remaining": None}
    HAVE[("weekly", True)] = [("Next week thing", "\t- [ ] Next week thing")]
    CHOICES.clear()
    rows = pr.tier_goal_rows("weekly", "")
    nxt = pm.next_period(wk)
    check("ahead: goal_choices asked for NEXT week",
          CHOICES and CHOICES[0][:3] == ("weekly", nxt.start, nxt.end), CHOICES)
    # "Goals wf" runs today..+2 and "Tomorrow only" is +1: on a Saturday or
    # a Sunday they reach into next week, and then they ARE its plan
    spill = ({"🔑 Goals wf"} if day(2) >= nxt.start else set()) \
        | ({"🔑 Tomorrow only"} if day(1) >= nxt.start else set())
    check("ahead: next week's plan, minus the goal already set there",
          names(rows) == {"🔑 Ship the second"} | spill, names(rows))
    have_i = [i for i, r in enumerate(rows) if r["title"].startswith("🎯 ")]
    done_i = [i for i, r in enumerate(rows) if r["title"] == "✅ Done"]
    plan_i = [i for i, r in enumerate(rows) if r["title"].startswith("🔮 ")]
    check("ahead: 🎯 have rows, ✅ Done, then 🔮",
          have_i and done_i and plan_i and max(have_i) < done_i[0] < min(plan_i),
          [r["title"] for r in rows])
    p = payload(by_name(rows, "🔑 Ship the second")["arg"])
    check("ahead: the payload is aimed ahead, at the original",
          p.get("ahead") is True and (p["pid"], p["tid"]) == (REALP, REALT2), p)
    check("ahead: the tier label says next",
          by_name(rows, "🔑 Ship the second")["subtitle"].endswith("⏎ The ♻️ Weekly · next goal"))
    check_chords("weekly ahead", rows)
    pr._goalseq_active = lambda kind=None: None
    HAVE.clear()

    # ── 🗓️ monthly: O's + KRs; goals already set are skipped ───────────────
    HAVE[("monthly", False)] = [
        ("Goals workflow (the real one)",
         f"\t- [ ] [Goals workflow (the real one)]({link(REALP, REALT)})"),
        ("Review", "\t- [ ] Review")]
    rows = pr.tier_goal_rows("monthly", "")
    nm = names(rows)
    check("monthly: the O's and the KRs of the month",
          {"🥅 TickAL", "🥅 Onboard", "🔑 Lost thing"} <= nm, nm)
    check("monthly: no Y, no done O", not any(x.startswith("🏔️") for x in nm)
          and "🥅 Closed thing" not in nm, nm)
    check("monthly: goals already set (a task, a text) are not offered again",
          "🔑 Goals wf" not in nm and "🔑 Review" not in nm, nm)
    p = payload(by_name(rows, "🥅 Onboard")["arg"])
    check("monthly: an O that links a LIST is a text goal", p["text"] == "Onboard" and "tid" not in p, p)
    p = payload(by_name(rows, "🥅 TickAL")["arg"])
    check("monthly: a text-only O is a text goal", p["text"] == "TickAL" and "tid" not in p, p)
    check_chords("monthly", rows)
    check_originals("monthly", rows)
    # a goal set from the project's 📌CTA task reads "💼 P • Onboard 🔗": read
    # the way an import names a plan item, it IS the O that links the list
    HAVE[("monthly", False)] = [("💼 P • Onboard 🔗",
                                 f"\t- [ ] [💼 P • Onboard 🔗]({link(OTHERP, OTHERT)})")]
    rows = pr.tier_goal_rows("monthly", "")
    check("monthly: a 💼 P • … 🔗 goal is read like a plan name (the O is not offered again)",
          "🥅 Onboard" not in names(rows) and "🥅 TickAL" in names(rows), names(rows))
    HAVE.clear()

    # ── 🌓 quarterly: O's only ───────────────────────────────────────────────
    rows = pr.tier_goal_rows("quarterly", "")
    nm = names(rows)
    check("quarterly: the O's overlapping it, no KR, no Y",
          {"🥅 TickAL", "🥅 Onboard"} <= nm and not any(x.startswith(("🔑", "🏔️")) for x in nm)
          and "🥅 Closed thing" not in nm, nm)
    check_chords("quarterly", rows)

    # ── 🎉 yearly: Y's + O's ────────────────────────────────────────────────
    rows = pr.tier_goal_rows("yearly", "")
    nm = names(rows)
    check("yearly: the Y and the O's, no KR",
          {"🏔️ Productivity System", "🥅 TickAL", "🥅 Onboard"} <= nm
          and not any(x.startswith("🔑") for x in nm), nm)
    check_chords("yearly", rows)
    check_originals("yearly", rows)

    # ── the evening journal's handoff: tomorrow's plan, the handoff carried ─
    jnl = {"slot": "evening", "mode": "set", "note_day": TODAY, "for_day": TOMORROW}
    CHOICES.clear()
    rows = pr.tier_goal_rows("daily", "", jnl=jnl)
    check("journal: goal_choices asked for the day the goal is FOR",
          CHOICES and CHOICES[0][:3] == ("daily", TOMORROW, TOMORROW), CHOICES)
    check("journal: tomorrow's open KRs, not today's",
          names(rows) == {"🔑 Goals wf", "🔑 Tomorrow only"}, names(rows))
    r = by_name(rows, "🔑 Goals wf")
    p = payload(r["arg"])
    check("journal: the pick carries the handoff and targets the original",
          p["jnl"] == {"slot": "evening", "mode": "set", "note_day": TODAY.isoformat(),
                       "for_day": TOMORROW.isoformat()} and p["tid"] == REALT, p)
    check("journal: the label names the day", r["subtitle"].endswith(
        f"⏎ The ☀️ Tomorrow ({TOMORROW.strftime('%a %d %b')}) goal"), r["subtitle"])
    check("journal: ⏭ No goal tonight still closes the screen",
          rows[-1]["title"] == "⏭ No goal tonight", rows[-1])
    check_chords("journal", rows)
    check_originals("journal", rows)

    # the morning's Change…: the goal being changed is not offered back
    cache.set("all_notes", [day_note(TODAY, "- [ ] Review")])
    rows = pr.tier_goal_rows("daily", "", jnl=dict(jnl, slot="morning", mode="changed",
                                                   for_day=TODAY))
    check("Change…: today's plan minus the goal being changed",
          "🔑 Review" not in names(rows) and "🔑 Goals wf" in names(rows), names(rows))
    check("Change…: ↩️ Keep the current goal still closes it",
          rows[-1]["title"] == "↩️ Keep the current goal", rows[-1])
    cache.set("all_notes", [])

    # ── the weekly journal's three-things screen (pn goal) ──────────────────
    pr._goalseq_active = lambda kind=None: {"kind": "weekly", "remaining": 3}
    rows = pr.goal_rows("")
    check("pn goal: next week's plan on the weekly journal's screen",
          names(rows) == {"🔑 Next week thing", "🔑 Ship the second"} | spill, names(rows))
    check("pn goal: a task-linked KR uses the screen's own task verb",
          by_name(rows, "🔑 Ship the second")["arg"] == f"xact:pn_goal:{REALP}:{REALT2}",
          by_name(rows, "🔑 Ship the second")["arg"])
    check("pn goal: a text KR uses its own text verb",
          payload(by_name(rows, "🔑 Next week thing")["arg"], "xact:pn_goal_text:")
          == {"text": "Next week thing"})
    n = len(plan_rows(rows))
    check("pn goal: 📋 Pick a goal, then the pool",
          rows[n]["title"] == "📋 Pick a goal"
          and any(r["title"].startswith("📋 Buy stamps") for r in rows[n + 1:]),
          [r["title"] for r in rows])
    check("pn goal: typed = the picker as it was", not plan_rows(pr.goal_rows("stamps")))
    check_chords("pn goal", rows)
    pr._goalseq_active = lambda kind=None: None

    # ── OKRs off, nothing cached, a broken selection: the screen as before ──
    base = [r["title"] for r in pr.tier_goal_rows("weekly", "")
            if not r["title"].startswith(("🔮", "📋 Pick"))]
    os.environ["okr_list_id"] = ""
    rows = pr.tier_goal_rows("weekly", "")
    off = [r["title"] for r in rows]
    check("OKRs off: no 🔮, no 📋, the screen as it was (the plan list is just a list then)",
          not any(x.startswith(("🔮", "📋 Pick")) for x in off)
          and [x for x in off if not x.startswith(COPY)] == base, off)
    os.environ["okr_list_id"] = "5eed00000000000000000fff"
    rows = pr.tier_goal_rows("weekly", "")
    check("nothing cached for the list: the screen exactly as with OKRs off",
          [r["title"] for r in rows] == off, [r["title"] for r in rows])
    os.environ["okr_list_id"] = PID
    rows = pr.tier_goal_rows("daily", "goals")
    check("typed, OKRs on: the pool never offers a planning copy",
          not any(r["title"].startswith(COPY) for r in rows), [r["title"] for r in rows])

    def boom(*a, **k):
        raise RuntimeError("selection broke")
    okr_notes.goal_choices = boom
    rows = pr.tier_goal_rows("daily", "")
    check("a broken plan selection costs the 🔮 rows, never the screen",
          not plan_rows(rows) and any(r["title"].startswith("📋 Buy stamps") for r in rows))
    okr_notes.goal_choices = spy_choices

    # ── the pick, end to end through the verb (engine faked) ────────────────
    import xact                                            # noqa: E402

    class FakePE:
        def __init__(self):
            self.calls = []

        def set_period_goal(self, kind, text, pid, tid, title, ahead=False, day=None):
            self.calls.append((kind, text, pid, tid, title, ahead, day))
            return "🎯 ok"

        def journal_answer_key(self, slot, key, text, day):
            return True

    fake = FakePE()
    xact._pn = lambda: fake
    xact._pn_gate = lambda: True
    xact._run_trigger = lambda *a, **k: None
    xact._pn_bg = lambda *a, **k: None
    xact._goalseq_load = lambda kind=None: None
    import goal_handoff as gh                              # noqa: E402
    gh._PATH = os.path.join(tmp, "goaljnl.json")
    rows = pr.tier_goal_rows("daily", "")
    with contextlib.redirect_stdout(io.StringIO()):     # the verb's toast
        xact.pn_setgoal(by_name(rows, "🔑 Goals wf")["arg"][len("xact:pn_setgoal:"):])
    check("verb: the daily goal lands on the ORIGINAL task (the one that moves)",
          fake.calls == [("daily", "", REALP, REALT, "Goals workflow (the real one)", False, None)],
          fake.calls)
    fake.calls.clear()
    with contextlib.redirect_stdout(io.StringIO()):     # the verb's toast
        xact.pn_setgoal(by_name(rows, "🔑 Copy of review")["arg"][len("xact:pn_setgoal:"):])
    check("verb: a copy-of-a-copy link sets text, moves nothing",
          fake.calls == [("daily", "Copy of review", None, None, None, False, None)], fake.calls)
    fake.calls.clear()
    rows = pr.tier_goal_rows("daily", "", jnl=jnl)
    with contextlib.redirect_stdout(io.StringIO()):     # the verb's toast
        xact.pn_setgoal(by_name(rows, "🔑 Tomorrow only")["arg"][len("xact:pn_setgoal:"):])
    check("verb: the evening journal's pick lands on tomorrow",
          fake.calls == [("daily", "Tomorrow only", None, None, None, False, TOMORROW)], fake.calls)
finally:
    os.environ.clear()
    os.environ.update(_env)
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    sys.exit(1)
