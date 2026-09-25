#!/usr/bin/env python3
"""The review of 2026-09-24, round 1 (HANDOFF_REVIEW_2026-09-24.md): one
check per fix, every one RED at 340553e and green once its fix lands. The
work order says which fix owns which section. Never edit a check to make it
pass: if a check is wrong, say so in the work order's section 6.

No network, no Alfred, no dialogs, and never Vex's real files: HOME points
at a temp dir BEFORE any repo module is imported, so run_path, the cache dir
and config.json all resolve inside it.

    TICKAL_NO_SETTLE=1 python3.13 tests/test_review_20260924.py
"""
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ["HOME"] = TMP                          # before ANY repo import
os.environ["TICKAL_NO_SETTLE"] = "1"
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

from zoneinfo import ZoneInfo  # noqa: E402

PASS = FAIL = 0
FAILURES = []
ITEMS = {}


def check(name, cond, detail=""):
    """name starts with the item id (R1..R10); the verify script reads ITEM lines."""
    global PASS, FAIL
    item = name.split()[0]
    ITEMS.setdefault(item, True)
    if cond:
        PASS += 1
    else:
        FAIL += 1
        ITEMS[item] = False
        FAILURES.append(f"{name}: {detail}")


BER = ZoneInfo("Europe/Berlin")

# ── R1 the goal pick names the zone ──────────────────────────────────────────
import day_move as dm  # noqa: E402

london = {"id": "T", "startDate": "2026-09-23T23:00:00.000+0000",
          "dueDate": "2026-09-23T23:00:00.000+0000", "isAllDay": True,
          "timeZone": "Europe/London", "status": 0}
fields, how = dm.move_fields(london, date(2026, 9, 25), tz=BER)
check("R1 an all-day goal move names the Mac's zone, so TickTick reads the day in it",
      how == "all-day" and fields == {"startDate": "2026-09-24T22:00:00+0000",
                                      "dueDate": "2026-09-24T22:00:00+0000",
                                      "isAllDay": True, "timeZone": "Europe/Berlin"}, fields)
timed = {"id": "T", "startDate": "2026-09-23T08:00:00.000+0000",
         "dueDate": "2026-09-23T09:00:00.000+0000", "isAllDay": False,
         "timeZone": "Europe/London", "status": 0}
f2, how2 = dm.move_fields(timed, date(2026, 9, 25), tz=BER)
check("R1 a timed move keeps its clock and its span, stays timed",
      how2 == "timed" and f2.get("isAllDay") is False
      and f2["startDate"] == "2026-09-25T08:00:00+0000" and f2["dueDate"] == "2026-09-25T09:00:00+0000", f2)

# ── R2 the buffer's date bulks skip periodic notes ───────────────────────────
import xact  # noqa: E402
import areas  # noqa: E402

areas.PERIODIC_LIST_ID = "PN"
NOTE = {"id": "n1", "projectId": "PN", "kind": "NOTE", "title": "☀️ 2026-09-22 · Tue",
        "startDate": "2026-09-22T02:30:00.000+0000", "dueDate": "2026-09-22T02:30:00.000+0000",
        "isAllDay": False, "status": 0}
TASK = {"id": "t1", "projectId": "L", "title": "Buy milk",
        "startDate": "2026-09-21T22:00:00.000+0000", "dueDate": "2026-09-21T22:00:00.000+0000",
        "isAllDay": True, "status": 0}
xact.buffer_ids = lambda: ["PN:n1", "L:t1"]
_real_find = xact.cache_store.find_task
xact.cache_store.find_task = lambda tid: {"n1": NOTE, "t1": TASK}.get(tid)
tasks, label, rep, crm = xact._date_bulk_pool("buffer")
xact.cache_store.find_task = _real_find
check("R2 a buffered periodic note is exempt from Roll to today and Clear dates",
      [t["id"] for t in (tasks or [])] == ["t1"], (tasks, label, rep, crm))

# ── R3 the ⏭ mark ────────────────────────────────────────────────────────────
import periodic_rows as pr  # noqa: E402
import periodic_model as pm  # noqa: E402
import periodic_engine as pe  # noqa: E402
import cache as cache_store  # noqa: E402

MARK = pm.GOAL_NEXT_MARK
check("R3 the emoji-picker form of the mark (with U+FE0F) is the mark, selector gone",
      pr._split_next(f"{MARK}️ tickal") == (True, "tickal"), pr._split_next(f"{MARK}️ tickal"))
check("R3 the mark alone", pr._split_next(f"{MARK}️") == (True, ""), pr._split_next(f"{MARK}️"))

cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR, exist_ok=True)
POOL = [{"id": "k1", "projectId": "L", "title": "💼 P • TickAL • WF", "status": 0, "priority": 0}]
cache_store.set("all_tasks", POOL)
pe.LOG_FILE = os.path.join(TMP, "periodic.log")
pe.SWEPT_FILE = os.path.join(TMP, "swept.json")
pe.period_goals = lambda kind, ahead=False, day=None: []
pr._goalseq_active = lambda kind=None: {"kind": "weekly", "remaining": 3}
g = pr.goal_rows(f"{MARK} tickal")
add = next((r for r in g if r["title"].startswith("➕")), None)
check("R3 under a live handoff a typed ⏭ is stripped from the goal text",
      add is not None and MARK not in add["title"] and "tickal" in add["title"], add and add["title"])
check("R3 under a live handoff the ⏭ query still finds the task",
      any(r["title"].startswith("📋") and "TickAL" in r["title"] for r in g), [r["title"] for r in g])
rows = pr.tier_goal_rows("weekly", f"{MARK} ship it")
txt = next((r for r in rows if r["title"].startswith("🎯")), None)
pay = json.loads(base64.b64decode(txt["arg"][len("xact:pn_setgoal:"):])) if txt else {}
check("R3 the weekly screen strips it too while the handoff is live",
      txt is not None and pay.get("text") == "ship it" and MARK not in txt["title"], (txt and txt["title"], pay))
pr._goalseq_active = lambda kind=None: None

# ── R4 the grace-day tick window ─────────────────────────────────────────────
import periodic_sections as ps  # noqa: E402

D = date(2026, 9, 23)                                   # the note's day
pe._today = lambda: D + timedelta(days=1)               # its grace day (dayroll)
U = "https://ticktick.com/webapp/#p/P/tasks/"
PLAIN = "b" * 24


def utc(d, hh):
    return f"{d.isoformat()}T{hh}:00:00.000+0000"


# completed at 00:50 local on the 25th: the feed keys it to the CALENDAR 25th
FEED = [((D + timedelta(days=2)).isoformat(), {"id": PLAIN, "completedTime": utc(D + timedelta(days=1), "22")})]
pe._completed_between = lambda d0, d1: [t for ds, t in FEED if d0.isoformat() <= ds <= d1.isoformat()]
doc = ps.parse_sections("#### ⚔️ Workbench\n- ✅ Tasks\n"
                        f"\t\t- [ ] [Buy stamps]({U}{PLAIN}) \n")
pe._fill_daily(doc, pm.period_for("daily", D), {}, False)
out = ps.serialize_sections(doc)
check("R4 a completion in the grace day's night (00:50 the calendar day after) ticks the line",
      f"- [x] [Buy stamps]({U}{PLAIN})" in out, out)

# ── R5 a blank query ranks by the order function ─────────────────────────────
import fuzzy as fuzz  # noqa: E402

items = [{"n": "b", "t": 2}, {"n": "a", "t": 1}, {"n": "c", "t": 0}]
for q in ("   ", "", "\t"):
    out = fuzz.rank(q, items, key_fn=lambda x: x["n"], order_fn=lambda x: (x["t"],))
    check(f"R5 a blank query {q!r} returns the items in order_fn order, not cache order",
          [x["n"] for x in out] == ["c", "a", "b"], [x["n"] for x in out])

# ── R6 done_sync edges ───────────────────────────────────────────────────────
import done_sync  # noqa: E402

p6 = os.path.join(TMP, "ds.json")
done_sync.request(lambda: None, now=100.0, path=p6)            # a spawn that yields no process
sp = []
check("R6 a spawn that yielded no process does not hold the slot: the next completion spawns",
      done_sync.request(lambda: sp.append(1) or True, now=101.0, path=p6) is True and sp == [1], sp)

with open(p6, "w") as f:
    json.dump({"ts": 5000.0, "job": 0}, f)
naps, clock = [], [1000.0]


def nap(s):
    naps.append(s)
    clock[0] += s


ok = done_sync.wait_quiet(sleep=nap, clock=lambda: clock[0], path=p6)
check("R6 a request stamped in the future is re-anchored: the job waits at most one DELAY",
      ok and len(naps) <= 1 and sum(naps) <= done_sync.DELAY, naps)

d6 = os.path.join(TMP, "ds_dir.json")
os.makedirs(d6, exist_ok=True)                                  # an unopenable state file
sp = []
check("R6 an unopenable state file never costs the catch-up: request spawns anyway",
      done_sync.request(lambda: sp.append(1) or True, now=100.0, path=d6) is True and sp == [1], sp)
check("R6 and the job runs at once",
      done_sync.wait_quiet(sleep=lambda s: None, clock=lambda: 100.0, path=d6) is True)


class _Boom:
    def after_done(self):
        raise ConnectionError("offline")


xact._pn_gate = lambda: True
xact._pn = lambda: _Boom()
_real_wait = done_sync.wait_quiet
done_sync.wait_quiet = lambda *a, **k: True
said = []
xact._crm_say = lambda m: said.append(m)
buf = io.StringIO()
raised = None
try:
    with contextlib.redirect_stdout(buf):
        xact.pn_donesync()
except Exception as e:                                          # noqa: BLE001
    raised = e
done_sync.wait_quiet = _real_wait
check("R6 a failing catch-up is one log line, never a banner or a crash",
      raised is None and "done-sync:" in buf.getvalue() and "ConnectionError" in buf.getvalue() and not said,
      (raised, buf.getvalue(), said))

# ── R7 a failed trigger is visible ───────────────────────────────────────────
_real_run = subprocess.run
subprocess.run = lambda *a, **k: subprocess.CompletedProcess(
    a[0], 1, stdout="", stderr="execution error: Alfred got an error: (-1712)")
err = io.StringIO()
try:
    with contextlib.redirect_stderr(err):
        r = xact._run_trigger("Search", "pn goal ")
finally:
    subprocess.run = _real_run
check("R7 a failed trigger leaves its name, rc and stderr on stderr (debugger, periodic log, routine log)",
      getattr(r, "returncode", None) == 1 and "-1712" in err.getvalue() and "Search" in err.getvalue(),
      err.getvalue())

# ── R8 the Finish link ───────────────────────────────────────────────────────
captured = []
_real_osa = xact._osa_dialog
xact._osa_dialog = lambda body: captured.append(body) or subprocess.CompletedProcess([], 0, stdout="Cancel\n", stderr="")
try:
    b = xact._dialog("Finish it now?", ["Cancel", "Finish it"], "Cancel", giveup=60)
except TypeError as e:
    b = f"TypeError: {e}"
finally:
    xact._osa_dialog = _real_osa
check("R8 a dialog can give up: giveup=60 puts 'giving up after 60' in the AppleScript",
      captured and "giving up after 60" in captured[0] and b == "Cancel", (captured, b))
captured = []
xact._osa_dialog = lambda body: captured.append(body) or subprocess.CompletedProcess([], 0, stdout="Roll\n", stderr="")
try:
    b = xact._dialog("Roll?", ["Cancel", "Roll"], "Roll")
finally:
    xact._osa_dialog = _real_osa
check("R8 without giveup nothing changes", captured and "giving up" not in captured[0] and b == "Roll", captured)

import link as _link  # noqa: E402
import routines as rt  # noqa: E402
import dayroll  # noqa: E402


class _Api:
    def __init__(self, t):
        self.t = t

    def get_task(self, pid, tid):
        return self.t


class _Cache:
    def get(self, key):
        return []


class _X:
    """The link's view of xact: an early weekly review, the dialog recorded."""
    def __init__(self, t):
        self.t, self.cache_store, self.asked = t, _Cache(), []

    def _api(self):
        return _Api(self.t)

    def _dialog(self, prompt, buttons, default, **kw):
        self.asked.append((prompt, tuple(buttons), default, kw))
        return ""


_real_today = dayroll.today
dayroll.today = lambda now=None: date(2026, 9, 24) if now is None else _real_today(now)
try:
    x = _X({"id": "W", "title": "♻️ Weekly Review", "status": 0,
            "startDate": "2026-09-27T08:00:00.000+0000", "dueDate": "2026-09-27T09:00:00.000+0000",
            "repeatFlag": "RRULE:FREQ=WEEKLY;BYDAY=SU"})
    out = _link._finish_guard(x, "P", "W")
finally:
    dayroll.today = _real_today
check("R8 the early-Finish question gives up after 60 s, so it cannot hold the Link node all day",
      x.asked and x.asked[0][3].get("giveup") == 60 and out.startswith("↩️"), (x.asked, out))

_real_resolve, _real_by, _real_guard, _real_complete = _link._resolve, rt.by_tid, _link._finish_guard, _link._complete
_link._resolve = lambda x, tid, pid: ("T", "P", "🌆 Shutdown")
rt.by_tid = lambda tid: {"label": "🌆 Shutdown"}
_link._finish_guard = lambda *a: ""
try:
    for text, want in [("Error: boom", False),
                       ("⏳ TickTick rate limit exceeded (300 requests / 5 min). Wait a few minutes and retry.", False),
                       ("✅ Complete failed", False),
                       ("🌆 Shutdown completed · 🔄 ticked", True)]:
        _link._complete = lambda pid, tid, title, _t=text: _t
        o, acted = _link.run("done", "T", "P")
        check(f"R8 a Finish is stamped as acted only when it completed: {text[:14]!r} -> {want}",
              o == text and acted is want, (o, acted))
finally:
    _link._resolve, rt.by_tid, _link._finish_guard, _link._complete = _real_resolve, _real_by, _real_guard, _real_complete

# ── R9 one day roll ──────────────────────────────────────────────────────────
for hm, want in (((0, 30), True), ((3, 59), True), ((4, 0), False), ((4, 10), False), ((4, 29), False), ((4, 30), False), ((22, 30), False)):
    got = xact._before_day_rollover(datetime(2026, 9, 25, *hm))
    check(f"R9 the journal rolls with dayroll: at {hm[0]:02d}:{hm[1]:02d} before-rollover is {want}",
          got is want, got)

# ── R10 tests never touch real files ─────────────────────────────────────────


def T(name):
    with open(os.path.join(ROOT, "tests", name), encoding="utf-8") as f:
        return f.read()


check("R10 test_journal_goal points the cache dir at a temp dir", "CACHE_DIR" in T("test_journal_goal.py"))
for name in ("test_monthly_note.py", "test_quarterly_note.py"):
    src = T(name)
    check(f"R10 {name} never writes the real periodic log", "pe.LOG_FILE =" in src or "pe._log =" in src)
lines = T("test_pn_sync.py").splitlines()
reloads = [i for i, ln in enumerate(lines) if "importlib.reload(pe)" in ln]
ok = bool(reloads) and all("pe.LOG_FILE =" in "\n".join(lines[i:i + 8]) and "pe.SWEPT_FILE =" in "\n".join(lines[i:i + 8])
                           for i in reloads)
check("R10 test_pn_sync re-points LOG_FILE and SWEPT_FILE after every reload", ok, reloads)
with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as f:
    mk = f.read()
check("R10 the Makefile comment tells the truth about which suites set the gate", "each file sets it too" not in mk)

# ── R11 the periodic notes show in Alfred's day views, untouched by bulk verbs ─
# (Vex's ruling 2026-09-24 evening: "Show them")
import filtering  # noqa: E402
from datetime import time as _time  # noqa: E402

_today = date.today()
PNOTE = {"id": "pn1", "projectId": "PN", "kind": "NOTE", "title": f"☀️ {_today.isoformat()} · note",
         "status": 0, **dm.timed_at(_today, _time(4, 30))}
PTASK = {"id": "pt1", "projectId": "L", "title": "Buy milk", "status": 0, **dm.all_day(_today)}
areas.PERIODIC_LIST_ID = "PN"
got = {t["id"] for t in filtering.smart_filter([PNOTE, PTASK], "today")}
check("R11 Today shows the day's periodic note beside the tasks", got == {"pn1", "pt1"}, got)
cache_store.set("all_tasks", [PNOTE, PTASK])
vt, _lab = xact._view_tasks("today")
check("R11 the bulk verbs' view (send all to focus, buffer all, the date rolls) leaves the note out",
      [t["id"] for t in (vt or [])] == ["pt1"], vt)
import browse  # noqa: E402

row = browse.task_item(PNOTE, "PN", 0)
check("R11 a periodic note row in Browse carries no ⇧ Complete",
      row["mods"]["shift"].get("valid") is False, row["mods"]["shift"])
row2 = browse.task_item(PTASK, "L", 0)
check("R11 a task row keeps its ⇧ Complete",
      row2["mods"]["shift"].get("arg", "").startswith("complete:"), row2["mods"]["shift"])
import everything_search as es  # noqa: E402

r3 = es._inline_task_row(PNOTE, "Today", [PNOTE, PTASK])
check("R11 a periodic note row in the search's Today carries no ⇧ Complete",
      r3["mods"]["shift"].get("valid") is False, r3["mods"]["shift"])

# ── R12 the resume after a goal pick is detached again ───────────────────────
# (Vex 2026-09-24 evening: "why not now"; the link log points at the picker half)
BG, INPROC = [], []
_rb, _rj = xact._pn_bg, xact.pn_journal
xact._pn_bg = lambda arg, *a, **k: BG.append(arg)
xact.pn_journal = lambda slot: INPROC.append(slot)
xact.JOURNAL_LOG = os.path.join(TMP, "journal.log")
xact._resume_journal("evening", date(2026, 9, 24))
xact._pn_bg, xact.pn_journal = _rb, _rj
check("R12 the pick reopens the journal detached, pinned to the note, never in its own process",
      BG == ["xact:pn_journal:evening@2026-09-24"] and not INPROC, (BG, INPROC))
check("R12 the log says so", "resume detached" in open(xact.JOURNAL_LOG).read())

# ── R13 the picker half is instrumented ──────────────────────────────────────
import goal_handoff as gh  # noqa: E402

gh.LOG_PATH = os.path.join(TMP, "journal2.log")
gh._SEEN = os.path.join(TMP, "seen.txt")
gh._PATH = os.path.join(TMP, "goaljnl.json")
gh._SKIPS = os.path.join(TMP, "skips.json")
gh.save("evening", date(2026, 9, 24), now=1000.0)
st = gh.load(now=1000.0)
_mr = getattr(gh, "mark_rendered", None) or (lambda *a, **k: None)   # red, not a crash, before round 3
a, b = _mr(st, rows=5), _mr(st, rows=5)
L2 = open(gh.LOG_PATH).read() if os.path.exists(gh.LOG_PATH) else ""
check("R13 the goal screen logs 'screen rendered' ONCE per handoff (it re-renders per keystroke)",
      a is True and b is False and L2.count("screen rendered") == 1 and "rows=5" in L2, (a, b, L2))
gh.save("evening", date(2026, 9, 24), now=2000.0)
check("R13 a new handoff logs again",
      _mr(gh.load(now=2000.0)) is True and os.path.exists(gh.LOG_PATH)
      and open(gh.LOG_PATH).read().count("screen rendered") == 2)
check("R13 the handoff line says which app owns the screen (no AppKit here: says so)",
      getattr(xact, "_activation_trail", lambda: None)() == " appkit=no"
      and getattr(xact, "_yield_activation", lambda: None)() == "no")


class _JPE:
    """The evening journal with the bridge and the highlight answered: the
    next question is the goal handoff."""
    def __init__(self):
        pairs = pm.journal_pairs(pm.seed_journal_lines([q for _k, q in pm.journal_fixed("evening", {})]))
        self.pairs = [(n, q, ("x" if n <= 2 else a), i) for n, q, a, i in pairs]

    def journal_seed(self, slot, day=None):
        class P:
            start = date(2026, 9, 24)
        return pm.journal_keys(self.pairs), self.pairs, P()

    def journal_merge(self, slot, answers, period=None, questions=None):
        return len(answers)

    def day_goal_on(self, day):
        return ""


_rt, _rpn = xact._run_trigger, xact._pn
xact._run_trigger = lambda name, arg=None: subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
xact._pn = lambda: _JPE()
xact._ask = lambda q, title="", multiline=False, detail="": None
with contextlib.redirect_stdout(io.StringIO()):
    xact.pn_journal("evening@2026-09-24")
xact._run_trigger, xact._pn = _rt, _rpn
L3 = open(xact.JOURNAL_LOG).read()
check("R13 the handoff line carries the activation trail",
      any("handoff set" in ln and "appkit=no" in ln for ln in L3.splitlines()), L3)
check("R13 the trigger line carries rc, the yield and stdout",
      any("picker trigger rc=0" in ln and "yielded=no" in ln and "out=ok" in ln for ln in L3.splitlines()), L3)

# ── R14 the picker survives the run that opened it (journal log 2026-09-24 18:00) ─
import types  # noqa: E402


class _FakeApp:
    def __init__(self):
        self.calls = []

    def setActivationPolicy_(self, p):
        self.calls.append(("policy", p))
        return True

    def deactivate(self):
        self.calls.append(("deactivate",))


_app = _FakeApp()
_fake_ak = types.SimpleNamespace(
    NSApplicationActivationPolicyProhibited=2,
    NSApplication=types.SimpleNamespace(sharedApplication=lambda: _app),
    NSRunningApplication=types.SimpleNamespace(currentApplication=lambda: types.SimpleNamespace(isActive=lambda: True)),
    NSWorkspace=types.SimpleNamespace(sharedWorkspace=lambda: types.SimpleNamespace(frontmostApplication=lambda: None)))
sys.modules["AppKit"] = _fake_ak
try:
    y = getattr(xact, "_yield_activation", lambda: None)()
finally:
    del sys.modules["AppKit"]
check("R14 before the trigger the run stops being an app that can be active (policy Prohibited), then deactivates",
      y == "prohibited" and _app.calls == [("policy", 2), ("deactivate",)], (y, _app.calls))

_wfp = getattr(xact, "_wait_for_pick", None)
gh._PATH = os.path.join(TMP, "goaljnl_wait.json")
gh.save("evening", date(2026, 9, 24))
xact.JOURNAL_LOG = os.path.join(TMP, "journal3.log")
naps = []


def _nap(s):
    naps.append(s)
    if len(naps) == 3:
        gh.clear()                      # the pick lands


res = _wfp("evening@2026-09-24", sleep=_nap, clock=lambda: 0.0) if _wfp else None
check("R14 a detached run idles until the pick consumed the handoff, then exits",
      res == "pick" and len(naps) == 3 and "exit after pick" in open(xact.JOURNAL_LOG).read(), (res, naps))
gh.save("evening", date(2026, 9, 24))
clk = [0.0]


def _tick(s):
    clk[0] += 300


res = _wfp("evening@2026-09-24", sleep=_tick, clock=lambda: clk[0]) if _wfp else None
check("R14 and gives up after PICK_WAIT_MAX when nothing is picked",
      res == "wait" and clk[0] >= getattr(xact, "PICK_WAIT_MAX", 10**9)
      and "exit after wait" in open(xact.JOURNAL_LOG).read(), (res, clk))
gh.clear()

WAITED = []
_rw = getattr(xact, "_wait_for_pick", None)
xact._wait_for_pick = lambda tag, *a, **k: WAITED.append(tag) or "pick"
_rt2, _rpn2 = xact._run_trigger, xact._pn
xact._run_trigger = lambda name, arg=None: subprocess.CompletedProcess([], 0, stdout="", stderr="")
xact._pn = lambda: _JPE()
xact._ask = lambda q, title="", multiline=False, detail="": None
os.environ["TICKAL_DETACHED"] = "1"
try:
    with contextlib.redirect_stdout(io.StringIO()):
        xact.pn_journal("evening@2026-09-24")
finally:
    os.environ.pop("TICKAL_DETACHED", None)
    xact._run_trigger, xact._pn = _rt2, _rpn2
    if _rw is not None:
        xact._wait_for_pick = _rw
check("R14 a detached handoff waits for the pick before the run exits", WAITED == ["evening@2026-09-24"], WAITED)

# ── R15 writes never revert the app (tests/test_no_stale_revert.py) ──────────
_r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_no_stale_revert.py")],
                    capture_output=True, text=True, env={**os.environ, "TICKAL_NO_SETTLE": "1"})
_last = (_r.stdout.strip().splitlines() or [""])[-1]
check("R15 the no-revert suite is green (a cached body is never posted, live first, only the named fields)",
      _r.returncode == 0 and "/" in _last and _last.split("/")[0] == _last.split("/")[1].split()[0], _last)

# ── summary ──────────────────────────────────────────────────────────────────
for item in sorted(ITEMS, key=lambda s: int(s[1:])):
    print(f"ITEM {item} {'green' if ITEMS[item] else 'red'}")
print(f"review 2026-09-24: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f[:300])
sys.exit(1 if FAIL else 0)
