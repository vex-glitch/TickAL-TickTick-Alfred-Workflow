#!/usr/bin/env python3
"""
link.py - Alfred Run Script behind ET "Link", the ONE TickAL trigger a
clickable URL can fire (grammar + threat model: src/routine_link.py).

$1 = the decoded argument, e.g. "focus:<tid>:<pid>". stdout → the End
notification: one honest line (nothing printed = no toast).

Link-road rules (research 2026-09-10 against xact sticky/focus_start):
  • focus starts the timer EVEN IF no new sticky appears. The natural
    click comes FROM the task's own sticky, where xact focus_sticky's
    "only if a sticky newly appeared" gate would silently do nothing.
  • a timer on ANOTHER task is never auto-closed (focus_start would log
    and swap it): refuse with a toast, touch nothing. Same task = keeps
    its original start; same task PAUSED = resume it.
  • a completed instance's id (a link minted from Completed before the
    generator healed it) resolves to the repeating series.
  • TickTick is launched and awaited before the sticky's window count,
    and the row-click retry is skipped (Vex's hand is in the app).
  • every sticky step runs through _sticky_call (routine_link.sticky_step
    over TickTick's window snapshots): the FIRST sticky after a TickTick
    launch fails whichever task it is, so while TickTick is younger than
    COLD_S a "No new sticky" gets ONE retry (not when focus moved onto an
    already-open sticky); and TICKAL_STICKY_FRAME="x,y,w,h" in the
    environment (KM shell steps only; a URL can't set env) moves the
    step's sticky there, so routine macros land every sticky on Vex's
    layout (2026-09-11, Shutdown • Start). TICKAL_BAR_AT="x,y" does the
    same for the focus bar on focus/timer steps (_bar_call).
  • a WINDOW step needs none of that snapshot machinery: a floating task
    window carries its task's title, so it is found, raised and placed by
    NAME (TICKAL_WIN_FRAME="x,y,w,h", the window twin of the sticky frame).
  • xact runs in-process on this node's own queue, never re-fired
    through the sequential ET XAct. Exception: journal dialog runs spawn
    DETACHED (xact._pn_bg, output → /tmp/tickal_periodic.log) so minutes
    of dialogs never hold this node.
  • the same argument within 5 s of the last run's START or FINISH is
    dropped (double clicks queue behind a slow sticky run on this
    sequential node); a refusal clears the stamp so a retry goes through.
  • every call lands in run/tickal_link.log (arg → outcome).
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, run_path
bootstrap()

import routine_link as rl

STAMP = run_path("tickal_link_last.json")
LOG = run_path("tickal_link.log")
DEBOUNCE_S = 5
LOG_MAX = 64 * 1024


def _log(arg, out):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            with open(LOG) as f:
                tail = f.readlines()[-200:]
            with open(LOG, "w") as f:
                f.writelines(tail)
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{arg[:200]!r}\t{out}\n")
    except OSError:
        pass


def _recent(arg):
    """The same argument started or finished under DEBOUNCE_S ago."""
    try:
        with open(STAMP) as f:
            last = json.load(f)
        return last.get("arg") == arg and 0 <= time.time() - last.get("ts", 0) < DEBOUNCE_S
    except (OSError, ValueError, AttributeError):
        return False


def _stamp(arg):
    try:
        with open(STAMP, "w") as f:
            json.dump({"arg": arg, "ts": time.time()}, f)
    except OSError:
        pass


def _unstamp():
    try:
        os.remove(STAMP)
    except OSError:
        pass


def _quiet(fn, *a, **kw):
    """Run an xact verb, capturing its toast line(s) instead of printing."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **kw)
    return " · ".join(ln.strip() for ln in buf.getvalue().splitlines() if ln.strip())


def _finish_guard(xact, pid, tid):
    """A refusal line when this Finish must not complete, else "" (go).

    A repeating routine keeps its id and rolls its date forward when it is
    completed, so a second Finish would complete TOMORROW's occurrence. The
    verdict is routines.finish_verdict, read with the same 04:00 day as the
    ⌃ Start guard:
      go      today's (or a late, or undated) occurrence is open -> complete
      closed  a one-off task already completed -> "✅ Already done"
      done    rolled past today AND the records show it finished today ->
              "✅ Already done · next <day>", no question
      early   the next occurrence is a later day and nothing says it was
              finished today - a Finish a day early (the Sunday review on
              Saturday), or one right after the focus bar's ● that the
              records have not caught up with. It ASKS, naming the day (Vex
              2026-09-24: "Ask first"), with Cancel as the default button:
              a reflexive ⏎ must never complete the wrong occurrence.

    It compared a 'YYYY-MM-DD' string with a date until 2026-09-24, so it
    raised, fell into the except, and let every click through (review).
    Still fails OPEN on a live read that errors: a missed refusal costs one
    extra completion, a false refusal costs the routine."""
    try:
        t = xact._api().get_task(pid, tid)
    except Exception:
        return ""
    if not t:
        return ""
    try:
        import routines as rt
        done = rt.finished_days(tid, xact.cache_store.get("completed_tasks"))
        verdict, day = rt.finish_verdict(t, done)
        when = day.strftime("%a %d %b") if day else ""
    except Exception:
        return ""
    if verdict == "closed":
        return "✅ Already done"
    if verdict == "done":
        return f"✅ Already done · next {when}"
    if verdict == "early":
        name = ((rt.by_tid(tid) or {}).get("label") or t.get("title") or "This routine").strip()
        try:
            b = xact._dialog(f"{name} is next due {when}. Finish it now?",
                             ["Cancel", "Finish it"], "Cancel")
        except Exception:
            b = ""
        if b != "Finish it":
            return f"↩️ Not finished · next due {when}"
    return ""


def _complete(pid, tid, title):
    """Tick a task off through the SAME road the ⇧ chord uses (src/dispatch.py
    "complete:"), so the caches, the session guards and the routine habit
    ripple stay ONE implementation. Its toast is captured, not printed: this
    node's stdout is the End banner."""
    import dispatch
    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ["dispatch", f"complete:{pid}:{tid}:{title or 'Task'}"]
    try:
        with contextlib.redirect_stdout(buf):
            dispatch.main()
    except Exception as e:
        return f"✅ Complete failed · {type(e).__name__}"
    finally:
        sys.argv = argv
    return " · ".join(ln.strip() for ln in buf.getvalue().splitlines()
                      if ln.strip()) or "✅ Done"


def _resolve(xact, tid, pid_hint):
    """(tid, pid, title): the cache first (its real projectId beats the
    link's hint and the 'inbox' alias), else a LIVE read with the hint.
    A completed/won't-do INSTANCE of a repeating task heals to its series.
    None when nothing knows the task."""
    cs = xact.cache_store
    tid = rl.series_id(tid, cs.get("completed_tasks"), cs.get("wontdo_tasks")) or tid
    t = cs.find_task(tid)
    if t:
        return (tid, t.get("projectId") or t.get("_projectId") or pid_hint,
                t.get("title") or "")
    if pid_hint:
        try:
            t = xact._api().get_task(pid_hint, tid)
        except Exception:
            t = None
        if t and t.get("id") == tid and not t.get("deleted"):
            return (rl.series_id(tid, [t]) or tid, t.get("projectId") or pid_hint,
                    t.get("title") or "")
    return None


def _timer_clash(xact, tid):
    st = xact._focus_state()
    if st and st.get("tid") != tid:
        who = rl._MD_LINK.sub(r"\1", st.get("title") or "Focus").strip()
        return f"⏱ Timer running on {who[:40]} · stop it first"
    return None


def _tt_ready(xact, timeout=8.0):
    """TickTick up with a readable window list (a cold deep link would
    skew sticky()'s before-count)."""
    if xact._sticky_count() >= 0:
        return True
    subprocess.run(["open", "-a", "TickTick"], check=False)
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.5)
        if xact._sticky_count() >= 0:
            time.sleep(1.0)            # process up ≠ main window drawn
            return True
    return False


COLD_S = 60        # TickTick younger than this (s) = still warming up
COLD_WAIT = 1.5    # pause before the one cold-start retry


def _tt_age():
    """Seconds since TickTick launched; None when it isn't running."""
    try:
        pid = subprocess.run(["pgrep", "-x", "TickTick"], capture_output=True,
                             text=True).stdout.split()[0]
        et = subprocess.run(["ps", "-o", "etime=", "-p", pid], capture_output=True,
                            text=True).stdout.strip()        # [[dd-]hh:]mm:ss
        days, _, hms = et.rpartition("-")
        secs = 0
        for part in hms.split(":"):
            secs = secs * 60 + int(part)
        return secs + (int(days) * 86400 if days else 0)
    except (IndexError, ValueError, OSError):
        return None


def _window_call(call):
    """Run a window-opening call with the ONE thing it shares with the sticky
    road: the cold-start retry. A routine QUITS and relaunches TickTick and
    asks for a window a few steps later, and on a cold app the board has not
    rendered - the row is not there to double click, so task_window burns its
    own retries and says it could not find it. While TickTick is younger than
    COLD_S that answer gets ONE more go after COLD_WAIT.

    It needs none of the sticky road's snapshot machinery: a window is found
    by NAME, so placement and verification are already exact. A LIST-VIEW
    refusal is never retried - waiting will not turn a list into a kanban."""
    out = call() or ""
    if "No window" in out and "list view" not in out:
        age = _tt_age()
        if age is not None and age < COLD_S:
            time.sleep(COLD_WAIT)
            out = call() or ""
    return out


def _sticky_call(call):
    """Run a sticky-opening call (xact.sticky / pn_sticky / the money
    sticky) with two KM-routine extras, both driven by TickTick's window
    snapshots around the step (rl.sticky_step):
      COLD RETRY - the FIRST sticky after a TickTick launch fails whichever
        task it is (TickTick still loading; cold-start tests 2026-09-11,
        old code 0/2, retry 2/2). While TickTick is younger than COLD_S a
        "No new sticky" gets ONE retry after COLD_WAIT - unless focus moved
        onto a sticky that was already there (TickTick reopens stickies
        left open at quit; retrying those only cost ~10 s a step).
      PLACEMENT - TICKAL_STICKY_FRAME="x,y,w,h" (only a KM shell step can
        set env; a clicked link can't) moves the step's sticky there: the
        one new sticky, or the already-open one TickTick focused. Nothing
        identifiable = nothing moved.
    A warm TickTick without the env var takes no snapshots at all."""
    frame = _frame_env()
    age0 = _tt_age()
    watch = frame is not None or age0 is None or age0 < COLD_S
    before = _dialogs() if watch else []
    out = call() or ""
    kind, target = rl.sticky_step(before, _dialogs()) if watch else (None, None)
    if "No new sticky" in out and kind != "open":
        age = _tt_age()
        if age is not None and age < COLD_S:
            time.sleep(COLD_WAIT)
            out = call() or ""
            kind, target = rl.sticky_step(before, _dialogs())
    if frame and target:
        try:
            subprocess.run(["osascript", "-e", _MOVE_OSA, *map(str, target + frame)],
                           capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return out


FRAME_ENV = "TICKAL_STICKY_FRAME"   # "x,y,w,h": where a KM routine macro wants the sticky

_DIALOGS_OSA = '''
tell application "System Events"
	if not (exists process "TickTick") then return ""
	tell process "TickTick"
		set fp to {-99999, -99999}
		set fs to {0, 0}
		try
			set fw to value of attribute "AXFocusedWindow"
			set fp to position of fw
			set fs to size of fw
		end try
		set out to ""
		repeat with w in (every window whose subrole is "AXSystemDialog")
			try
				set p to position of w
				set s to size of w
				set t to ""
				try
					set t to (value of attribute "AXTitle" of w) as text
				end try
				set k to 0
				if t is "" or t is "missing value" then set k to 1
				set f to 0
				if ((item 1 of p) as integer) = ((item 1 of fp) as integer) and ((item 2 of p) as integer) = ((item 2 of fp) as integer) and ((item 1 of s) as integer) = ((item 1 of fs) as integer) and ((item 2 of s) as integer) = ((item 2 of fs) as integer) then set f to 1
				set out to out & ((item 1 of p) as integer) & "," & ((item 2 of p) as integer) & "," & ((item 1 of s) as integer) & "," & ((item 2 of s) as integer) & "," & k & "," & f & linefeed
			end try
		end repeat
		return out
	end tell
end tell'''

_MOVE_OSA = '''on run argv
	set v to {}
	repeat with a in argv
		set end of v to (a as integer)
	end repeat
	tell application "System Events"
		tell process "TickTick"
			repeat with w in (every window whose subrole is "AXSystemDialog")
				set p to position of w
				set s to size of w
				if ((item 1 of p) as integer) = (item 1 of v) and ((item 2 of p) as integer) = (item 2 of v) and ((item 1 of s) as integer) = (item 3 of v) and ((item 2 of s) as integer) = (item 4 of v) then
					set position of w to {item 5 of v, item 6 of v}
					set size of w to {item 7 of v, item 8 of v}
					set position of w to {item 5 of v, item 6 of v}
					return "placed"
				end if
			end repeat
		end tell
	end tell
	return "not found"
end run'''


def _frame_env():
    """TICKAL_STICKY_FRAME as (x, y, w, h), or None. Only a KM shell step
    can set it: a clicked alfred:// link never carries env, so clicks keep
    TickTick's own remembered sticky spot."""
    try:
        x, y, w, h = (int(float(p)) for p in os.environ.get(FRAME_ENV, "").split(","))
        return (x, y, w, h) if w > 0 and h > 0 else None
    except ValueError:
        return None


def _dialogs():
    """TickTick's AXSystemDialog windows: [(x, y, w, h, buttons, focused)]."""
    try:
        r = subprocess.run(["osascript", "-e", _DIALOGS_OSA], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for ln in r.stdout.splitlines():
        try:
            rows.append(tuple(int(p) for p in ln.split(",")))
        except ValueError:
            pass
    return [r for r in rows if len(r) == 6]


BAR_ENV = "TICKAL_BAR_AT"           # "x,y": where a KM routine macro wants the focus bar


def _bar_at():
    """TICKAL_BAR_AT as (x, y), the bar's TOP-left in AX coords (main
    screen top-left = 0,0, y down), or None. KM shell steps only, like
    FRAME_ENV."""
    try:
        x, y = (int(float(p)) for p in os.environ.get(BAR_ENV, "").split(","))
        return x, y
    except ValueError:
        return None


def _main_h():
    """Main display height in points (Cocoa y runs UP from its bottom)."""
    import ctypes
    import ctypes.util

    class _Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                    ("w", ctypes.c_double), ("h", ctypes.c_double)]
    cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayBounds.restype = _Rect
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    return cg.CGDisplayBounds(cg.CGMainDisplayID()).h


def _bar_call(xact, call):
    """Run focus_start / focus_resume; with TICKAL_BAR_AT set the focus bar
    lands there (Vex 2026-09-11: it came up wherever he last dragged it,
    not on the Shutdown layout). The spot goes into the bar's state file
    (Cocoa, y up from the main screen's bottom) as place_at, a one-shot: a
    spawning bar tries it before its saved top_left (_restore_origin), a
    RUNNING bar applies it on its next 1 s state tick, shown or hidden;
    either way it is then cleared (focus_bar _place_at). A spot on no
    screen changes nothing, and the saved top_left is never overwritten
    here. Then _bar_wake, so a hidden or dead bar comes back even when the
    timer was already running. No pid, no AX, no race with a bar in its
    idle grace (reviews 2026-09-11)."""
    at = _bar_at()
    if at is None:
        return call()
    try:
        xact._bar_write(place_at=[float(at[0]), _main_h() - at[1]])
    except Exception:
        pass
    out = call()
    try:
        xact._bar_wake()
    except Exception:
        pass
    return out


# view:<slot> → the Alfred screen BrowseCtx opens (calendar rides OpenCalendar)
VIEW_CTX = {"countdowns": "ctx:countdowns",   # the ⏳ hub
            "crmcal": "ctx:crmcal",           # exactly what CRM home > Calendar opens
            # 🥅 the OKR steps in the routines' checklists (HANDOFF_OKR phase 5)
            "okr": "ctx:okr",
            "okrdaily": "ctx:okrpace:daily",
            "okrweekly": "ctx:okrpace:weekly",
            "okrmonthly": "ctx:okrpace:monthly",
            "okrquarterly": "ctx:okrpace:quarterly",
            "okrcarry": "ctx:okrcarry",
            # 🥘 the meal-prep hub (a routine step "[Plan the week]" can carry it)
            "meal": "ctx:meal"}


def _money(xact, as_sticky=False, as_window=False):
    """Open THIS month's money note (routine_link.money_note): the cache
    first, a LIVE read of the list when the cache has no current-month note
    (made within the last sync hour), else the newest one, said out loud.
    as_sticky = the same note as a desktop sticky (no row-click retry);
    as_window = the same note in its live floating window."""
    import dayroll
    today = dayroll.today()
    pid, cs = rl.MONEY_LIST, xact.cache_store
    pool = [t for k in ("all_tasks", "all_notes") for t in (cs.get(k) or [])
            if t.get("projectId") == pid]
    cur, newest = rl.money_note(pool, today.year, today.month)
    live_ok = True                # only a read that WORKED may say "no note yet"
    if not cur:
        try:
            live = xact._api().get_project_data(pid).get("tasks") or []
        except Exception:         # rate limit, offline, token: say so, never "missing"
            live, live_ok = [], False
        if live:
            cur, live_newest = rl.money_note(live, today.year, today.month)
            newest = live_newest or newest
    target = cur or newest
    if not target:
        return "💰 No money note found" if live_ok else "💰 Live read failed · sync, then retry"
    month = rl.MONTHS[today.month - 1]
    why = ("" if cur else
           f"No {month} note yet" if live_ok else f"{month} not cached, live read failed")
    if as_sticky or as_window:
        if not _tt_ready(xact):
            return ("🗒️ TickTick not up · no sticky" if as_sticky
                    else "🪟 TickTick not up · no window")
        os.environ["task_title"] = target.get("title") or "Money"
        done = (_quiet(xact.task_window, pid, target["id"]) if as_window else
                _quiet(xact.sticky, pid, target["id"], assist=False))
        return f"💰 {why} · {done}" if why else done
    subprocess.run(["open", f"ticktick:///webapp/#p/{pid}/tasks/{target['id']}"],
                   check=False)
    if cur:
        return f"💰 {month} open"
    return f"💰 {why} · opened {(target.get('title') or '')[:30]}"


def run(verb, tid, pid_hint):
    """→ (toast, acted). acted=False = refused before touching anything,
    so main() lets an immediate retry through."""
    if verb == "ping":
        return "🔗 Link works", True
    import xact
    if verb == "pause":
        return _quiet(xact.focus_pause), True
    if verb == "resume":
        return _quiet(xact.focus_resume), True
    if verb == "routine":                # tid carries the routine key
        # through the SAME guard as the ⌃ chord: a click on "Startup • Start"
        # when today's is already done opens the confirm screen (which
        # occurrence?) instead of quietly running tomorrow's
        return _quiet(xact.routine_start, tid), True
    if verb == "journal":                # tid carries the (allowlisted) slot
        # DETACHED: the dialog run can last minutes and must never hold
        # this sequential node (a focus/pause click would queue behind it)
        xact._pn_bg(f"xact:pn_journal:{tid}")
        return "", True
    if verb == "note":                   # the CURRENT period's note: resolve /
        return _quiet(xact.pn_open, tid), True    # lazy-mint, open, bg refresh
    if verb == "notesticky":             # same note as a sticky, no row-click retry
        if not _tt_ready(xact):
            return "🗒️ TickTick not up · no sticky", False
        return _sticky_call(lambda: _quiet(xact.pn_sticky, tid, assist=False)), True
    if verb == "notewindow":             # same note, LIVE - none of the
        if not _tt_ready(xact):          # snapshot machinery: a window is
            return "🪟 TickTick not up · no window", False   # found by NAME
        return _window_call(lambda: _quiet(xact.pn_window, tid)), True
    if verb == "view":                   # no ticktick:// route for these
        if tid == "calendar":
            xact._run_trigger("OpenCalendar")                 # its List-menu flow
        else:
            xact._run_trigger("BrowseCtx", VIEW_CTX[tid])     # an Alfred screen
        return "", True
    if verb in ("money", "moneysticky", "moneywindow"):
        if verb == "moneysticky":        # TickTick up BEFORE the snapshots (like notesticky):
            if not _tt_ready(xact):      # else stickies it reopens at launch look new
                return "🗒️ TickTick not up · no sticky", False
            return _sticky_call(lambda: _money(xact, as_sticky=True)), True
        if verb == "moneywindow":        # no snapshots: a window is found by NAME
            if not _tt_ready(xact):
                return "🪟 TickTick not up · no window", False
            return _window_call(lambda: _money(xact, as_window=True)), True
        return _money(xact), True
    got = _resolve(xact, tid, pid_hint)
    if not got:
        return "🔗 Task not found · sync, then retry", False
    tid, pid, title = got                # tid: a completed instance → its series
    os.environ["task_title"] = title     # sticky()/focus_start() read it
    if verb == "done":                   # the "Finish <routine>" step
        # ET Link is URL-fired and Alfred never prompts, so this verb is
        # gated TWICE. (1) It completes a REGISTERED ROUTINE only: every
        # other verb in this grammar navigates, opens or starts a timer,
        # and a link that ticks off any task by id is a different animal -
        # a shared list or a web page could carry one. (2) A routine
        # already finished today is refused, because a repeating task rolls
        # forward under the SAME id: a second click would complete
        # TOMORROW's occurrence (the 5 s debounce does not cover a click a
        # minute later, or a re-walk of the routine's steps); one whose next
        # occurrence is a later day ASKS first (_finish_guard).
        import routines as rt
        if not rt.by_tid(tid):
            return "🔗 Not a routine", False
        refused = _finish_guard(xact, pid, tid)
        if refused:
            # a deliberate Cancel on the early-Finish question counts as a
            # handled click, so a double-click queued behind the dialog is
            # debounced instead of asking again (review 2026-09-24)
            return refused, refused.startswith("↩️")
        return _complete(pid, tid, title), True
    if verb in ("focus", "focuswindow", "timer"):
        clash = _timer_clash(xact, tid)
        if clash:
            return clash, False
    if verb == "window":                 # the live twin of sticky
        if not _tt_ready(xact):
            return "🪟 TickTick not up · no window", False
        return _window_call(lambda: _quiet(xact.task_window, pid, tid)), True
    parts = []
    if verb in ("focus", "sticky"):
        if _tt_ready(xact):
            parts.append(_sticky_call(lambda: _quiet(xact.sticky, pid, tid, assist=False)))
        elif verb == "sticky":
            return "🗒️ TickTick not up · no sticky", False
        else:
            parts.append("🗒️ TickTick not up · no sticky")
    if verb == "focuswindow":            # the window twin: the timer still
        if _tt_ready(xact):              # starts even if no window opens
            parts.append(_window_call(lambda: _quiet(xact.task_window, pid, tid)))
        else:
            parts.append("🪟 TickTick not up · no window")
    if verb in ("focus", "focuswindow", "timer"):
        st = xact._focus_state()
        if st and st.get("tid") == tid and st.get("paused_at"):     # "focus" on a paused timer = resume it
            parts.append(_bar_call(xact, lambda: _quiet(xact.focus_resume)))
        else:
            parts.append(_bar_call(xact, lambda: _quiet(xact.focus_start, pid, tid)))
    return " · ".join(p for p in parts if p), True


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        verb, tid, pid = rl.parse(arg)
    except ValueError as e:
        out = f"🔗 Link refused · {e}"
        print(out)
        _log(arg, out)
        return
    if _recent(arg):
        _log(arg, "debounced")
        return
    _stamp(arg)          # start stamp: a concurrent twin sees it
    try:
        out, acted = run(verb, tid, pid)
    except Exception as e:
        out, acted = f"🔗 Link failed · {type(e).__name__}", False
    if acted:
        _stamp(arg)      # finish stamp: a twin QUEUED behind a slow run lands inside the window
    else:
        _unstamp()       # a refusal never eats the retry
    if out:              # a bare "\n" would still post a blank End banner
        print(out)
    _log(arg, out)


if __name__ == "__main__":
    main()
