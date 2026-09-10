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
    if verb == "journal":                # tid carries the (allowlisted) slot
        # DETACHED: the dialog run can last minutes and must never hold
        # this sequential node (a focus/pause click would queue behind it)
        xact._pn_bg(f"xact:pn_journal:{tid}")
        return "", True
    if verb == "note":                   # TODAY's daily: resolve/lazy-mint, open,
        return _quiet(xact.pn_open, tid), True    # refresh in the background
    if verb == "view":                   # no ticktick:// route for these two
        if tid == "calendar":
            xact._run_trigger("OpenCalendar")                 # its List-menu flow
        else:
            xact._run_trigger("BrowseCtx", "ctx:countdowns")  # the Alfred ⏳ hub
        return "", True
    got = _resolve(xact, tid, pid_hint)
    if not got:
        return "🔗 Task not found · sync, then retry", False
    tid, pid, title = got                # tid: a completed instance → its series
    os.environ["task_title"] = title     # sticky()/focus_start() read it
    if verb in ("focus", "timer"):
        clash = _timer_clash(xact, tid)
        if clash:
            return clash, False
    parts = []
    if verb in ("focus", "sticky"):
        if _tt_ready(xact):
            parts.append(_quiet(xact.sticky, pid, tid, assist=False))
        elif verb == "sticky":
            return "🗒️ TickTick not up · no sticky", False
        else:
            parts.append("🗒️ TickTick not up · no sticky")
    if verb in ("focus", "timer"):
        st = xact._focus_state()
        if st and st.get("tid") == tid and st.get("paused_at"):
            parts.append(_quiet(xact.focus_resume))    # "focus" on a paused timer = resume it
        else:
            parts.append(_quiet(xact.focus_start, pid, tid))
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
