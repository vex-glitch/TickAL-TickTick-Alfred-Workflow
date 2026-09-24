#!/usr/bin/env python3
"""The periodic round of 2026-09-24 (Vex's "Periodics" list, HANDOFF_ROUTINES
section 14): the daily note's ticks follow every completion TickAL makes,
yesterday's note included (src/done_sync.py, periodic_engine.after_done /
tick_pass / the grace branch of _fill_daily).

No network, no Alfred, no dialogs: the engine's I/O is faked.

    python3 tests/test_pn_sync.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
os.environ["TICKAL_NO_SETTLE"] = "1"

import done_sync  # noqa: E402
import periodic_model as pm  # noqa: E402
import periodic_sections as ps  # noqa: E402
import periodic_engine as pe  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


tmp = tempfile.mkdtemp()
STATE = os.path.join(tmp, "donesync.json")
pe.LOG_FILE = os.path.join(tmp, "periodic.log")          # never the real log

# ── 1. the trailing debounce ──────────────────────────────────────────────────
spawned = []
spawn = lambda: spawned.append(1)                          # noqa: E731
check("first completion spawns the catch-up job",
      done_sync.request(spawn, now=1000.0, path=STATE) and spawned == [1])
check("a second one while the job waits only moves the deadline",
      not done_sync.request(spawn, now=1005.0, path=STATE) and spawned == [1])

clock = [1010.0]
naps = []


def nap(secs):
    naps.append(secs)
    clock[0] += secs


check("the job runs once the LAST completion has been quiet for DELAY",
      done_sync.wait_quiet(sleep=nap, clock=lambda: clock[0], path=STATE)
      and abs(clock[0] - (1005.0 + done_sync.DELAY)) < 1e-6, (clock, naps))
check("it slept, it did not spin", naps and all(0 < n <= done_sync.DELAY for n in naps), naps)
check("a completion after the job freed its slot spawns the next job",
      done_sync.request(spawn, now=clock[0] + 1, path=STATE) and spawned == [1, 1])

# a completion that lands WHILE the job sleeps pushes it further
STATE2 = os.path.join(tmp, "donesync2.json")
done_sync.request(lambda: None, now=0.0, path=STATE2)
clock2 = [5.0]


def nap2(secs):
    clock2[0] += secs
    if clock2[0] < 30 and not getattr(nap2, "hit", False):
        nap2.hit = True
        done_sync.request(lambda: None, now=clock2[0], path=STATE2)    # mid-sleep tick


done_sync.wait_quiet(sleep=nap2, clock=lambda: clock2[0], path=STATE2)
check("a tick during the wait moves the run past it", clock2[0] >= 15.0 + done_sync.DELAY - 1e-6, clock2)

# a job that died leaves a stale heartbeat: the next completion still gets one
STATE3 = os.path.join(tmp, "donesync3.json")
got = []
done_sync.request(lambda: got.append("a"), now=0.0, path=STATE3)
check("a dead job's slot frees after JOB_TTL",
      done_sync.request(lambda: got.append("b"), now=done_sync.JOB_TTL + 1, path=STATE3)
      and got == ["a", "b"], got)

# a broken state file never costs a completion its catch-up
STATE4 = os.path.join(tmp, "donesync4.json")
with open(STATE4, "w") as f:
    f.write("{not json")
got = []
check("a corrupt stamp still spawns", done_sync.request(lambda: got.append(1), now=5.0, path=STATE4) and got == [1])
check("a spawn that raises never escapes",
      done_sync.request(lambda: 1 / 0, now=5.0, path=os.path.join(tmp, "x.json")) is False)

# ── 2. the tick pass on yesterday's note ──────────────────────────────────────
TODAY = date(2026, 9, 23)
YDAY = TODAY - timedelta(days=1)
pe._today = lambda: TODAY
pe.SWEPT_FILE = os.path.join(tmp, "swept.json")
U = "https://ticktick.com/webapp/#p/P/tasks/"
SHUT, PLAIN, LATE = "a" * 24, "b" * 24, "c" * 24


def note_body():
    return ("#### ⚔️ Workbench\n- ✅ Tasks\n"
            f"\t\t- [ ] [🌆 Shutdown · 22:00]({U}{SHUT}) \n"
            f"\t\t- [ ] [Buy stamps]({U}{PLAIN}) \n"
            "#### 🔎 Summaries\n- Tomorrow\n"
            f"\t\t- [ ] [Later]({U}{LATE}) \n")


def utc(d, hh="20"):
    return f"{d.isoformat()}T{hh}:00:00.000+0000"


# the Shutdown of the 22nd, completed at 00:00:31 on the 23rd: a copy of the
# series with repeatTaskId, its occurrence on the 22nd
FEED = [{"id": "copy1", "repeatTaskId": SHUT, "startDate": utc(YDAY),
         "completedTime": utc(TODAY, "22")},
        {"id": PLAIN, "completedTime": utc(TODAY, "08")}]
pe._completed_between = lambda d0, d1: list(FEED)

doc = ps.parse_sections(note_body())
pe._fill_daily(doc, pm.period_for("daily", YDAY), {}, False)
out = ps.serialize_sections(doc)
check("grace day: yesterday's Shutdown line ticks from its copy",
      f"- [x] [🌆 Shutdown · 22:00]({U}{SHUT})" in out, out)
check("grace day: a plain task done today ticks there too", f"- [x] [Buy stamps]({U}{PLAIN})" in out, out)
check("grace day: nothing else ticks", f"- [ ] [Later]({U}{LATE})" in out, out)
check("the ticks go into the sweep's ledger, so the sweep never completes them again",
      {SHUT, PLAIN} <= set(pe._swept_load().get(YDAY.isoformat(), [])), pe._swept_load())

old = date(2026, 9, 20)
doc = ps.parse_sections(note_body())
pe._fill_daily(doc, pm.period_for("daily", old), {}, False)
check("a note older than yesterday keeps its lines as they were",
      "- [x]" not in ps.serialize_sections(doc))

pe._completed_between = lambda d0, d1: None
doc = ps.parse_sections(note_body())
check("no completed feed = no change, never a guess",
      pe._sync_ticks(doc, pm.period_for("daily", YDAY), YDAY) == []
      and "- [x]" not in ps.serialize_sections(doc))
pe._completed_between = lambda d0, d1: list(FEED)

# tick_pass: one RMW, only on a live or grace-day daily note
RMW = []
LIVE = {"content": note_body()}


def fake_rmw(pid, tid, mutate):
    RMW.append(tid)
    d = ps.parse_sections(LIVE["content"])
    res = mutate(d, dict(LIVE))
    LIVE["content"] = ps.serialize_sections(d)
    return res, d


pe._pn_rmw = fake_rmw
IDX = {("daily", YDAY.isoformat()): {"id": "NOTE_Y", "projectId": "PN"},
       ("daily", TODAY.isoformat()): {"id": "NOTE_T", "projectId": "PN"}}
got = pe.tick_pass(pm.period_for("daily", YDAY), index=IDX)
check("tick_pass ticks yesterday's note in ONE write", RMW == ["NOTE_Y"] and set(got) == {SHUT, PLAIN}, (RMW, got))
RMW.clear()
check("tick_pass leaves an old note alone",
      pe.tick_pass(pm.period_for("daily", old), index={("daily", old.isoformat()): {"id": "O"}}) == []
      and not RMW)
check("tick_pass never touches a weekly", pe.tick_pass(pm.period_for("weekly", TODAY), index=IDX) == [])
check("tick_pass never mints", pe.tick_pass(pm.period_for("daily", YDAY), index={}) == [] and not RMW)

# after_done: today's refresh + yesterday's tick pass, nothing minted
calls = []
pe.build_index = lambda force=False: IDX
pe.refresh_period = lambda p, index=None, force=False: calls.append(("refresh", p.start)) or "refreshed"
pe._stamp_refresh = lambda p: calls.append(("stamp", p.start))
pe.tick_pass = lambda p, index=None: calls.append(("ticks", p.start)) or ["x"]
line = pe.after_done()
check("after_done refreshes TODAY's note, stamps it, then ticks YESTERDAY's",
      calls == [("refresh", TODAY), ("stamp", TODAY), ("ticks", YDAY)], calls)
check("and says what it did", "refreshed" in line and "ticked 1" in line, line)
calls.clear()
pe.build_index = lambda force=False: {}
check("no note = nothing refreshed, nothing minted", pe.after_done() == "no note to catch up" and not calls)
check("an open refreshes after one minute, not ten", pe.REFRESH_TTL == 60, pe.REFRESH_TTL)

# ── 3. every completion road asks for the catch-up ────────────────────────────
import xact  # noqa: E402
xact.JOURNAL_LOG = os.path.join(tmp, "journal.log")
_real_nudge = xact.pn_done_nudge
_spawned = []
_real_bg = xact._pn_bg
xact._pn_bg = lambda arg: _spawned.append(arg)
_real_nudge()
check("under the tests' switch (TICKAL_NO_SETTLE) a completion never spawns a catch-up",
      os.environ.get("TICKAL_NO_SETTLE") == "1" and _spawned == [], _spawned)
xact._pn_bg = _real_bg
asked = []
xact.pn_done_nudge = lambda: asked.append(1)
import cache as cache_store  # noqa: E402
cache_store.CACHE_DIR = os.path.join(tmp, "cache")
os.makedirs(cache_store.CACHE_DIR, exist_ok=True)
xact._complete_cache_patch("P", "T")
check("xact's completion cache mirror queues the note catch-up", asked == [1], asked)

src = open(os.path.join(ROOT, "src", "dispatch.py")).read()
check("dispatch's complete: road (⇧ and the Finish link) queues it too",
      "_xact.pn_done_nudge()" in src.split('arg.startswith("complete:")')[1].split("elif arg.startswith")[0])
xsrc = open(os.path.join(ROOT, "Scripts", "xact.py")).read()
body = xsrc.split("def buffer_complete():")[1].split("\ndef ")[0]
check("the buffer's bulk complete queues it", "pn_done_nudge()" in body)
check("the router knows the detached half", 'verb == "pn_donesync"' in xsrc)

# ── 4. every pn picker ranks like the search engine (Vex 2026-09-22) ──────────
import base64  # noqa: E402
import json  # noqa: E402
import fuzzy  # noqa: E402
import areas  # noqa: E402
import periodic_rows as pr  # noqa: E402

check("strength: whole name", fuzzy.strength("tickal", "TickAL") == 0)
check("strength: word start", fuzzy.strength("tickal", "💼 P • TickAL • WF") == 1)
check("strength: inside a word", fuzzy.strength("rest", "interests") == 2)
check("strength: scatter", fuzzy.strength("tst", "the best") == 3)
_items = [{"t": "notes on tickal", "k": 2}, {"t": "tickal task", "k": 1}, {"t": "t i c k a l spread", "k": 1}]
_r = fuzzy.rank("tickal", _items, key_fn=lambda x: x["t"], order_fn=lambda x: (x["k"],))
check("rank: a task before a note of the same strength, scatter dropped",
      [x["t"] for x in _r] == ["tickal task", "notes on tickal"], [x["t"] for x in _r])
check("rank: an empty query keeps the order", fuzzy.rank("", _items, key_fn=lambda x: x["t"]) == _items)
check("rank: scatter survives when nothing better exists",
      [x["t"] for x in fuzzy.rank("tkl", [{"t": "the kettle"}], key_fn=lambda x: x["t"])] == ["the kettle"])

BRL, CTA = "b" * 24, "c" * 24
areas.BRIDGES_ID = BRL
areas.PERIODIC_LIST_ID = "p" * 24
os.environ["okr_list_id"] = ""                                  # OKRs off: no 🔮 rows here


def task(tid, title, pid=CTA, **kw):
    t = {"id": tid, "projectId": pid, "title": title, "status": 0, "tags": [], "kind": "TEXT"}
    t.update(kw)
    return t


POOL = [
    task("n1", "P • TickAL • WF • Bridge 🌉 2026/09/19", pid="x" * 24, kind="NOTE", tags=["🌉bridge"]),
    task("n2", "D • Bridge 🌉 2026/09/21 TickAL", pid=BRL, kind="NOTE"),
    task("s1", "[CRM](alfred://runtrigger/com.vex.tickal/Link/?argument=view%3Acrmcal)"),
    task("n3", "TickAL research notes", kind="NOTE"),
    task("sub", "TickAL subtask", parentId="t1"),
    task("t1", "💼 P • [TickAL • WF](ticktick:///webapp/#p/6a2ab4686b8e917957000a71/tasks) 🔗"),
]
cache_store.set("all_tasks", POOL)
pr._goalseq_active = lambda kind=None: None
pe.period_goals = lambda kind, ahead=False, day=None: []


def titles(rows):
    return [r["title"] for r in rows]


rows = pr.tier_goal_rows("daily", "tickal")
picks = [t for t in titles(rows) if t.startswith("📋 ")]
check("daily goal picker: the task first, not a bridge note", picks and "TickAL" in picks[0]
      and "Bridge" not in picks[0] and "💼" in picks[0], picks)
check("daily goal picker: no bridge note at all, tagged or in the Bridges list",
      not any("Bridge" in t for t in picks), picks)
check("daily goal picker: a top-level task before a subtask, tasks before notes",
      picks.index(next(t for t in picks if "subtask" in t)) > 0
      and picks.index(next(t for t in picks if "research notes" in t)) == len(picks) - 1, picks)
check("a link's URL never matches: com.vex.tickal inside a routine step's link",
      not any("CRM" in t for t in picks), picks)
k = pr.task_rows("tickal")
check("☑️ Task (not a goal picker) keeps bridge notes, AFTER the tasks",
      "💼" in k[0]["title"] and any("Bridge" in r["title"] for r in k)
      and not any("Bridge" in r["title"] for r in k[:3]), titles(k))
g = pr.goal_rows("tickal")
check("🎯 pn goal: the task first", "💼" in g[0]["title"] or "TickAL" in g[0]["title"], titles(g))
d = pr.day_goal_rows("tickal")
check("☀️ day goal: no bridge note", not any("Bridge" in t for t in titles(d)), titles(d))

# ── 5. ⏭ Next week on the weekly goal screens (Vex 2026-09-20) ────────────────
MARK = pm.GOAL_NEXT_MARK
wk = pm.period_for("weekly", pr._pn_today())
rows = pr.tier_goal_rows("weekly", "")
sw = [r for r in rows if r["title"].startswith("⏭ Next week")]
check("weekly screen: one ⏭ Next week row naming next week",
      len(sw) == 1 and pm.title(pm.next_period(wk)) in sw[0]["title"], titles(rows))
check("⏭ autocompletes into next-week mode, never runs anything",
      sw and sw[0]["valid"] is False and sw[0]["autocomplete"] == f"pn goals weekly {MARK} ", sw)
check("⏭ carries the screen's chords", sw and set(sw[0]["mods"]) == set(pr._mods()))
rows = pr.tier_goal_rows("weekly", f"{MARK} ")
check("next-week mode: 🔙 This week takes its place",
      any(r["title"].startswith("🔙 This week") and r["autocomplete"] == "pn goals weekly "
          for r in rows) and not any(r["title"].startswith("⏭") for r in rows), titles(rows))
rows = pr.tier_goal_rows("weekly", f"{MARK} ship it")
txt = next(r for r in rows if r["title"].startswith("🎯"))
pay = json.loads(base64.b64decode(txt["arg"][len("xact:pn_setgoal:"):]))
check("next-week mode: a typed goal is aimed ahead, the ⏭ is not part of it",
      pay.get("ahead") is True and pay.get("text") == "ship it" and "· next" in txt["title"], (pay, txt["title"]))
check("next-week mode: ⇥ keeps the mode", txt.get("autocomplete", "").startswith(f"pn goals weekly {MARK} "), txt)
tk = [r for r in pr.tier_goal_rows("weekly", f"{MARK} tickal") if r["title"].startswith("📋 ")]
check("next-week mode: picked tasks are aimed ahead too",
      tk and all(json.loads(base64.b64decode(r["arg"][len("xact:pn_setgoal:"):])).get("ahead") for r in tk))
pe.period_goals = lambda kind, ahead=False, day=None: ([("Next thing", "\t- [ ] Next thing")] if ahead else [])
rows = pr.tier_goal_rows("weekly", f"{MARK} ")
dele = next(r for r in rows if r["title"] == "🎯 Next thing")
done = next(r for r in rows if r["title"] == "✅ Done")
check("next-week mode lists NEXT week's goals, remove and ✅ Done aimed there",
      json.loads(base64.b64decode(dele["arg"].split(":", 2)[2])).get("ahead") is True
      and json.loads(base64.b64decode(done["arg"].split(":", 2)[2])).get("ahead") is True)
pe.period_goals = lambda kind, ahead=False, day=None: []
check("the monthly screen has no week switch",
      not any(r["title"].startswith(("⏭", "🔙 This week")) for r in pr.tier_goal_rows("monthly", "")))
pr._goalseq_active = lambda kind=None: {"kind": "weekly", "remaining": 3}
check("the weekly journal's own handoff is next week already: no switch",
      not any(r["title"].startswith(("⏭", "🔙 This week")) for r in pr.tier_goal_rows("weekly", ""))
      and not any(r["title"].startswith(("⏭", "🔙 This week")) for r in pr.goal_rows("")))
pr._goalseq_active = lambda kind=None: None

g = pr.goal_rows("")
check("🎯 pn goal: ⏭ Next week leads", g[0]["title"].startswith("⏭ Next week")
      and g[0]["autocomplete"] == f"pn goal {MARK} ", titles(g))
g = pr.goal_rows(f"{MARK} tickal")
check("🎯 pn goal ⏭: task rows carry :next", all(r["arg"].endswith(":next") for r in g if r["title"].startswith("📋 ")), [r["arg"] for r in g])
add = next(r for r in g if r["title"].startswith("➕"))
check("🎯 pn goal ⏭: a plain-text goal carries next",
      json.loads(base64.b64decode(add["arg"][len("xact:pn_goal_text:"):])) == {"text": "tickal", "next": True})
check("🎯 pn goal (this week): no :next", not any(r.get("arg", "").endswith(":next") for r in pr.goal_rows("tickal")))

# the verbs honour it
xact._pn_gate = lambda: True
xact._goalseq_load = lambda kind=None: None
trig = []
xact._run_trigger = lambda name, arg=None: trig.append((name, arg))


class GoalPE:
    def __init__(self):
        self.calls = []

    def set_goal(self, pid_or_text, tid=None, title=None, week="current"):
        self.calls.append(("set_goal", pid_or_text, tid, week))
        return "🎯 ok"

    def set_period_goal(self, kind, text, pid, tid, title, ahead=False, day=None):
        self.calls.append(("set_period_goal", kind, ahead))
        return "🎯 ok"

    def remove_period_goal(self, kind, line, ahead=False, day=None):
        self.calls.append(("remove", kind, ahead))
        return "🗑 ok"

    def period_goals(self, kind, ahead=False, day=None):
        self.calls.append(("count", kind, ahead))
        return [1, 2] if ahead else [1]


gp = GoalPE()
xact._pn = lambda: gp
xact._task_title = lambda tid, default="Task", pid=None: "Ship"
import contextlib  # noqa: E402
import io  # noqa: E402


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return buf.getvalue().strip()


src_x = open(os.path.join(ROOT, "Scripts", "xact.py")).read()
check("router: pn_goal reads an optional :next",
      'pn_goal(pid, tid, nxt=(flag == "next"))' in src_x)
quiet(xact.pn_goal, "P", "T", True)
check("pn_goal ⏭ writes NEXT week", gp.calls[-1] == ("set_goal", "P", "T", "next"), gp.calls)
quiet(xact.pn_goal, "P", "T")
check("pn_goal without it writes this week", gp.calls[-1] == ("set_goal", "P", "T", "current"), gp.calls)
quiet(xact.pn_goal_text, base64.b64encode(json.dumps({"text": "Ship", "next": True}).encode()).decode())
check("pn_goal_text ⏭ writes NEXT week", gp.calls[-1] == ("set_goal", "Ship", None, "next"), gp.calls)
trig.clear()
quiet(xact.pn_setgoal, base64.b64encode(json.dumps({"kind": "weekly", "text": "Ship", "ahead": True}).encode()).decode())
check("a ⏭ pick lands next week and reopens the screen IN ⏭ mode",
      gp.calls[-1] == ("set_period_goal", "weekly", True) and trig == [("Search", f"pn goals weekly {MARK} ")], (gp.calls, trig))
trig.clear()
quiet(xact.pn_setgoal, base64.b64encode(json.dumps({"kind": "weekly", "text": "Ship"}).encode()).decode())
check("a this-week pick reopens the plain screen", trig == [("Search", "pn goals weekly ")], trig)
trig.clear()
quiet(xact.pn_goaldel, base64.b64encode(json.dumps({"kind": "weekly", "line": "x", "ahead": True}).encode()).decode())
check("a ⏭ remove edits next week and stays in ⏭ mode",
      gp.calls[-1] == ("remove", "weekly", True) and trig == [("Search", f"pn goals weekly {MARK} ")], (gp.calls, trig))
out = quiet(xact.pn_goaldone, base64.b64encode(json.dumps({"kind": "weekly", "ahead": True}).encode()).decode())
check("✅ Done in ⏭ mode counts NEXT week's goals", gp.calls[-1] == ("count", "weekly", True) and "2 goals" in out, (gp.calls, out))

# ── 6. the notes sit on their day (Vex 2026-09-19) ────────────────────────────
import day_move  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
BER = ZoneInfo("Europe/Berlin")
for kind, title, want in [("daily", "☀️ 2026-09-23 · Wed", date(2026, 9, 23)),
                          ("weekly", "♻️ 2026-W39 • 21st-27th Sep", date(2026, 9, 27)),
                          ("weekly", "2026-W53", date(2027, 1, 3)),
                          ("monthly", "🗓️ 2026-09 September", date(2026, 9, 30)),
                          ("monthly", "2027-02 February", date(2027, 2, 28)),
                          ("quarterly", "🌓 2026-Q4", date(2026, 12, 31)),
                          ("yearly", "🎉 2026", date(2026, 12, 31))]:
    p = pm.period_from_title(kind, title)
    check(f"{kind} {title!r} sits on {want}", p is not None and pm.note_day(p) == want, p)
check("a title that names no period is None", pm.period_from_title("weekly", "Notes") is None)
check("an unknown tier is None", pm.period_from_title("hourly", "2026") is None)
f = day_move.all_day(date(2026, 9, 30), tz=BER)
check("all-day on a CEST day = local midnight in UTC, zone named",
      f == {"startDate": "2026-09-29T22:00:00+0000", "dueDate": "2026-09-29T22:00:00+0000",
            "isAllDay": True, "timeZone": "Europe/Berlin"}, f)
check("all-day on a CET day (after the clocks change)",
      day_move.all_day(date(2026, 10, 31), tz=BER)["dueDate"] == "2026-10-30T23:00:00+0000")


class MintAPI:
    def __init__(self):
        self.kw = None

    def create_task(self, **kw):
        self.kw = kw
        return {"id": "new", "projectId": kw.get("project_id")}


mint = MintAPI()
pe._api = lambda: mint
pe._ensure_tags = lambda: None
pe._load_template = lambda kind: "{{breadcrumbs}}\n"
pe._child_links = lambda p, index: []
pe._crumb = lambda p, index: "crumb"
import datetime as _dtm  # noqa: E402
check("the daily note sits at 04:30", pm.note_time(pm.period_for("daily", date(2026, 9, 25))) == _dtm.time(4, 30))
for _k in ("weekly", "monthly", "quarterly", "yearly"):
    check(f"the {_k} note sits at 05:00", pm.note_time(pm.period_for(_k, date(2026, 9, 25))) == _dtm.time(5, 0))
f = day_move.timed_at(date(2026, 9, 27), _dtm.time(5, 0), tz=BER)
check("05:00 on a CEST Sunday = 03:00Z, timed, zone named",
      f == {"startDate": "2026-09-27T03:00:00+0000", "dueDate": "2026-09-27T03:00:00+0000",
            "isAllDay": False, "timeZone": "Europe/Berlin"}, f)
check("05:00 after the clocks change = 04:00Z",
      day_move.timed_at(date(2026, 10, 31), _dtm.time(5, 0), tz=BER)["dueDate"] == "2026-10-31T04:00:00+0000")
pe.create_note(pm.period_for("weekly", date(2026, 9, 21)), {})
want = day_move.timed_at(date(2026, 9, 27), _dtm.time(5, 0))
check("a weekly note is minted on its Sunday at 05:00, not all-day",
      mint.kw and mint.kw.get("due_date") == want["dueDate"] and mint.kw.get("start_date") == want["startDate"]
      and mint.kw.get("time_zone") == want.get("timeZone") and mint.kw.get("kind") == "NOTE", mint.kw)
pe.create_note(pm.period_for("daily", date(2026, 9, 25)), {})
check("a daily note is minted on its own day at 04:30",
      mint.kw.get("due_date") == day_move.timed_at(date(2026, 9, 25), _dtm.time(4, 30))["dueDate"], mint.kw)
import api as _api_mod  # noqa: E402
check("…and the api posts it as timed, not all-day",
      _api_mod._is_all_day(mint.kw["due_date"]) is False)

# ── 7. what the review of 2026-09-24 caught ───────────────────────────────────
# (a) ⏭ then a word: the space after the mark is not part of the query
cache_store.set("all_tasks", POOL + [task("r1", "TickAL release notes")])
pr._goalseq_active = lambda kind=None: None
g = [r["title"] for r in pr.goal_rows(f"{MARK} tickal")]
check("🎯 ⏭ tickal still finds a title that STARTS with the word",
      any("TickAL release notes" in t for t in g), g)
check("_split_next leaves no leading space", pr._split_next(f"{MARK} tickal") == (True, "tickal"))
check("_rank collapses the query's whitespace",
      [t["id"] for t in pr._rank("  tickal  release ", [task("r1", "TickAL release notes")])] == ["r1"])

# (b) the smart lists never carry a periodic note (their bulk verbs act on every row)
import filtering  # noqa: E402
from datetime import datetime as _dt  # noqa: E402
_today_utc = _dt.now().strftime("%Y-%m-%dT12:00:00+0000")
_sm = [task("pn1", "☀️ today's note", pid=areas.PERIODIC_LIST_ID, kind="NOTE", startDate=_today_utc),
       task("w1", "real work", startDate=_today_utc)]
got = [t["id"] for t in filtering.smart_filter(_sm, "today")]
check("Today keeps the work and drops the periodic note", got == ["w1"], got)
got = [t["id"] for t in filtering.smart_filter(_sm, "next7days")]
check("Next 7 Days drops it too", got == ["w1"], got)

# (c) after midnight the day that is ending keeps its weather, quote and
# countdowns: they are fetched for the CALENDAR day, and after_done now
# refreshes "today" (dayroll's) right after a Shutdown finished at 00:18
import importlib  # noqa: E402
pe = importlib.reload(pe)                     # the real engine again (section 2 stubbed it)
pe.LOG_FILE = os.path.join(tmp, "periodic.log")      # a reload re-reads the real paths
pe.SWEPT_FILE = os.path.join(tmp, "swept2.json")
_real_date = pe.date


def calendar(d):
    class _Cal(date):
        @classmethod
        def today(cls):
            return d
    pe.date = _Cal


LEADS = []
pe._today = lambda: date(2026, 9, 22)
pe._api = lambda: object()
pe._pn_rmw = lambda pid, tid, mutate: (mutate(ps.parse_sections("crumb\n---\n"), {}),
                                        ps.parse_sections("crumb\n---\n"))
pe._compose_lead = lambda doc, p, index, refetch: LEADS.append(refetch)
pe._fill_daily = lambda *a, **k: None
pe._fill_okr = lambda *a, **k: None
pe._heal_own_goals = lambda *a, **k: None
IDX22 = {("daily", "2026-09-22"): {"id": "N22", "projectId": "PN"}}
calendar(date(2026, 9, 23))
pe.refresh_period(pm.period_for("daily", date(2026, 9, 22)), index=IDX22)
calendar(date(2026, 9, 22))
pe.refresh_period(pm.period_for("daily", date(2026, 9, 22)), index=IDX22)
check("00:18 on the 23rd: the 22nd's note does NOT refetch weather and quote; on the 22nd it does",
      LEADS == [False, True], LEADS)

pe = importlib.reload(pe)
pe.LOG_FILE = os.path.join(tmp, "periodic.log")      # never the real log or ledger
pe.SWEPT_FILE = os.path.join(tmp, "swept3.json")
pe._today = lambda: date(2026, 9, 22)
pe._completed_between = lambda a, b: None
CD = []


class T2:
    def countdown_lines(self):
        CD.append(1)
        return ["- Weekend · 3d"]

    def habit_lines_daily(self):
        return None


pe._tier2 = lambda: T2()
p22 = pm.period_for("daily", date(2026, 9, 22))
calendar(date(2026, 9, 23))
pe._fill_daily(ps.parse_sections("#### ⏳ Countdowns\n"), p22, {}, True)
calendar(date(2026, 9, 22))
pe._fill_daily(ps.parse_sections("#### ⏳ Countdowns\n"), p22, {}, True)
check("the countdowns are recounted on the calendar day only", CD == [1], CD)
pe.date = _real_date

print(f"test_pn_sync: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
