#!/usr/bin/env python3
"""
xact.py - Alfred Run Script: the action executor router.

One canvas branch (`xact:` prefix on the Actions router) fans out here:
    xact:buffer_add:<pid>:<tid>     add task to the buffer, reopen Search
    xact:buffer_remove:<pid>:<tid>  drop one task from the buffer
    xact:buffer_complete            complete every buffered task
    xact:buffer_clear               empty the buffer
    xact:focus_start:<pid>:<tid>    start the workflow focus timer (one at a time)
    xact:focus_start::              …with EMPTY ids: unattributed timer
    xact:focus_pause                pause the workflow timer
    xact:focus_resume               resume a paused timer
    xact:focus_stop                 stop + log a focus record to TickTick
                                    (duration-true: pauses compressed out)
    xact:focus_stop_as:<pid>:<tid>  stop + log ONTO a picked task - the
                                    unattributed stop-twist
    xact:focus_discard              stop without logging
    xact:focus_log:<pid>:<tid>:<m>  retro-log <m> minutes ending now
    xact:pomo:<minutes|default>     start TickTick's REAL pomodoro (hidden
                                    AppleScript command in TickTick.sdef);
                                    "default"/empty = the app's own length
    xact:pomo_task:<pid>:<tid>:<m|default>   select the task in the app (real
                                    row click), then start the pomo
    xact:pomo_sticky:<pid>:<tid>:<m|default> sticky + pomo
    xact:pomo_toggle                pause⟷resume the app's running pomodoro
                                    (the Start/Abandon hotkey toggle)
    xact:pomo_abandon               END the running pomodoro machine-side:
                                    ⌥F8 → AX-click End → auto-confirm
    xact:view_open:<key>            open an app-only TickTick view
                                    (habits/matrix/pomo)
    xact:sticky:<pid>:<tid>         open the task as a desktop sticky note
                                    (deep link + in-app ⌘⌥⇧S shortcut)
    xact:focus_sticky:<pid>:<tid>   sticky + start the focus timer

CRM records (customer notes + tattoo logbooks - src/crm_records.py):
    xact:crmnew_newcust:<kind>      dialogs: name/phone/mail/bday → customer
                                    note, then continue per kind
    xact:crmnew_go:<kind>:<custTid> consult/tattoo: pick-or-create the
                                    logbook (dialogs) → Add window prefilled
    xact:crmnew_go:session::<logTid>  next session → Add prefilled S<n>
    xact:sessiondone:<pid>:<tid>    complete the session task (calendar keeps
                                    the record), dialogs log the entry,
                                    Paid recomputed, clipboard 📷 attached,
                                    archive or chain S<n+1>
    xact:crmlog:<tid>               dialog → timestamped line under ## Notes

Focus session blocks (checkbox staging):
    xact:fx_add:<pid>:<tid>         insert the task as a "- [ ] [title](link)"
                                    checkbox into the CURRENT focus task's
                                    today block (src/focus_blocks.py grammar)
    xact:fx_add_sticky:<pid>:<tid>  fx_add + open the FOCUS task's sticky
    xact:fx_add_to:<tpid>:<ttid>:<spid>:<stid>  insert source into a target
    xact:fx_add_multi:<b64>         batch insert; b64 JSON {tpid,ttid,items:
                                    [[pid,tid,title]…]} - ONE content write
    xact:fx_tick:<pid>:<tid>[:<ctid>]  tick the first unchecked checkbox (or
                                    the one linking ctid). env TICKAL_JSON=1
                                    → block_summary JSON (the focus bar's
                                    channel) instead of the human toast
    xact:fx_sweep[:<pid>:<tid>]     complete every checked+linked+still-open
                                    checkbox task, ALL blocks. No focus
                                    records, no content rewrite
    xact:fx_copy[:<pid>:<tid>]      today's UNTICKED checkboxes → clipboard
                                    as a paste-ready "- Title" bullet list
    xact:convert:<pid>:<tid>        flip the item kind TEXT↔NOTE (⌘ Actions
                                    "🔃 Convert" - v1 full-object update)
    xact:wontdo:<pid>:<tid>         abandon the task (status -1, "Won't Do")
                                    - v2 batch write, v1 fallback
    xact:wontdo_undo:<pid>:<tid>    Won't Do → open again
    xact:tag_create_under:<parent>  ⌘ tag menu "➕ Add nested tag": dialog
                                    asks the name, creates under parent
    xact:fx_link:<pid>:<tid>        attribute a running unattributed session
                                    (timer file or pomo sidecar) to the task
    xact:buffer_focus               buffer → today block (buffer order), clears
    xact:view_focus:<key>           smart view → today block (view order)
    xact:tag_focus:<pid>:<tag>      tag's open tasks → today block
    xact:stage_open:<pid>:<tid>     fire ET Focus prefilled "stage pid:tid "
    xact:bar_show / xact:bar_hide   focus-bar visibility (show also spawns)
    xact:focus_done                 stop+log the session, then complete its task

Periodic notes 💫 (src/periodic_engine; all gated on periodic_list_id):
    xact:pn_open:<spec>             daily|yesterday|weekly|monthly|quarterly|
                                    yearly → lazy-mint + refresh + deep link
    xact:pn_sticky:<spec>           same, then open the note as a sticky
    xact:pn_entry:<b64|plain>       📓 entry into today's daily ({"kind","text"}
                                    or plain "w Shipped it"; kinds w/n/t/k/l/m)
    xact:pn_income:<b64|plain>      💰 "- amt · label" + re-total (plain
                                    "485 label"; empty → dialog)
    xact:pn_journal:<slot>          morning|evening - dialog per unanswered
                                    prompt, partial-save, phone-wins merge
    xact:pn_goal:<pid>:<tid>        task → weekly 🎯 Goals + daily mirror
                                    (three-things seq active → NEXT week)
    xact:pn_goal_text:<b64>         plain-text goal, same write
    xact:pn_day_goal:<pid>:<tid>    ☀️ Day Goal pin + schedule today
    xact:pn_day_goal_text:<b64>     create Inbox task due today, pin it
    xact:pn_mood:<1-5>              face picked → note dialog → 💬 Mood line
    xact:pn_highlight[:<b64|text>]  ✨ weekly Highlight (empty → dialog)
    xact:pn_sched:today|pid|tid[|HH:MM]  ☀️/🌙 Add-to picker commit
    xact:pn_refresh[:<spec>]        rebuild generated sections (bg-open path)
                                    (sweeps ticked ✅ Today boxes first)
    xact:pn_mint                    the 04:30 agent run: mint-ahead + catch-up
                                    + refresh + roll-ups (launchd fires this)

stdout → the End notification. task_title rides the env.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions, run_path, notify as _notify_banner
bootstrap()

import config as cfg
import cache as cache_store
import focus_blocks as fb

BUFFER_FILE = run_path("tickal_buffer.txt")
FOCUS_FILE  = run_path("tickal_focus.json")
POMO_FILE   = run_path("tickal_pomo.json")        # pomo task attribution
BAR_STATE   = run_path("tickal_focus_bar.json")   # bar visibility + position
BAR_LOCK    = run_path("tickal_focus_bar.lock")   # bar singleton flock (pid inside)


def buffer_ids():
    try:
        with open(BUFFER_FILE) as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def _write_buffer(lines):
    with open(BUFFER_FILE, "w") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def _title(default="Task"):
    return os.environ.get("task_title", default)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _run_trigger(name, arg=None):
    if arg is None:
        subprocess.run(["osascript", "-e",
                        f'tell application id "com.runningwithcrayons.Alfred" to '
                        f'run trigger "{name}" in workflow "com.vex.tickal"'],
                       check=False)
    else:
        subprocess.run(["osascript", "-e",
                        ('on run argv\n'
                         f'tell application id "com.runningwithcrayons.Alfred" to '
                         f'run trigger "{name}" in workflow "com.vex.tickal" '
                         'with argument (item 1 of argv)\nend run'),
                        arg], check=False)


def _app_sync():
    """Click TickTick's File ▸ Sync (background-safe SE menu click - the
    refresh-after-add pattern). Makes an OPEN sticky redraw our content
    writes within seconds instead of the app's own ~1 min sync cadence."""
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to tell process "TickTick" '
         'to click menu item "Sync" of menu "File" of menu bar 1'],
        capture_output=True, check=False, timeout=6)


def app_sync_after_write():
    """Post-content-write nudge (a bar tick must show in the sticky
    without waiting). Under Alfred → direct SE click (its
    Accessibility grant); headless (the bar) → ride the XAct ET so Alfred
    does the clicking."""
    try:
        if os.environ.get("alfred_version"):
            _app_sync()
        else:
            _run_trigger("XAct", "xact:app_sync")
    except Exception:
        pass


def buffer_add(pid, tid):
    lines = buffer_ids()
    key = f"{pid}:{tid}"
    if key not in lines:
        lines.append(key)
        _write_buffer(lines)
    print(f"🅿️ {_title()} buffered ({len(lines)} in buffer)")
    _run_trigger("Search")


def buffer_remove(pid, tid):
    lines = [ln for ln in buffer_ids() if ln != f"{pid}:{tid}"]
    _write_buffer(lines)
    print(f"🅿️ removed · {len(lines)} left in buffer")


def buffer_complete():
    import api as api_mod
    api = api_mod.TickTickAPI(cfg.get_token())
    done = skipped = 0
    completed_tids = set()
    for ln in buffer_ids():
        pid, tid = ln.split(":", 1)
        try:
            api.complete_task(pid, tid)
            done += 1
            completed_tids.add(tid)
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
            from dispatch import _patch_project_data
            _patch_project_data(tid, pid_old=pid, remove=True)
        except Exception:
            skipped += 1
    _write_buffer([])
    print(f"🅿️ {done} completed" + (f", {skipped} skipped" if skipped else ""))
    # Complete-guard: completing the focused task ends its session too.
    st = _focus_state()
    if st and st.get("tid") in completed_tids:
        try:
            focus_stop()
        except Exception:
            pass


TT_FMT = "%Y-%m-%dT%H:%M:%S+0000"


def _parse_ts(s):
    return datetime.strptime(s, TT_FMT).replace(tzinfo=timezone.utc)


def _focus_state():
    try:
        with open(FOCUS_FILE) as f:
            return json.load(f)
    except OSError:
        return None


def _write_focus(st):
    with open(FOCUS_FILE, "w") as f:
        json.dump(st, f)


def focus_elapsed(st):
    """True focused seconds of a focus-file state - pauses compressed out.
    Schema v2 {pid,tid,title,start, paused_at?, paused_total=0}; v1 files
    (no paused_* keys) behave unchanged via the .get defaults."""
    ref = _parse_ts(st["paused_at"]) if st.get("paused_at") \
        else datetime.now(timezone.utc)
    return max(0.0, (ref - _parse_ts(st["start"])).total_seconds()
               - st.get("paused_total", 0))


def focus_start(pid, tid):
    # One timer at a time: starting on a
    # DIFFERENT task stops + logs the previous timer; the same task keeps
    # its original start (no accidental reset, no duplicate records).
    # Empty pid+tid = unattributed timer - logs a taskless record.
    st = _focus_state()
    note = ""
    if st and st.get("tid") == tid:
        print(f"⏱ Timer already running on {st['title']}")
        return
    if st:
        # Full session end for the previous timer: sweep + note + record.
        try:
            note = " · " + _close_session(st)
        except Exception:
            note = f" · previous timer on {st['title']} dropped"
        try:
            os.remove(FOCUS_FILE)
        except OSError:
            pass
    if tid:
        title = (os.environ.get("task_title")
                 or (cache_store.find_task(tid) or {}).get("title") or "Task")
    else:
        title = "Focus"
    _write_focus({"pid": pid, "tid": tid, "title": title, "start": _now_iso()})
    if tid:
        _ensure_block_if_history(pid, tid)   # carry-over; no empty-header noise
    _bar_wake()
    print(f"⏱ Timer running on {title}{note}")


def focus_pause():
    st = _focus_state()
    if not st:
        print("No focus timer running")
        return
    if st.get("paused_at"):
        print(f"⏸ Already paused ({st['title']})")
        return
    st["paused_at"] = _now_iso()
    st.setdefault("paused_total", 0)
    _write_focus(st)
    print(f"⏸ Paused · {int(focus_elapsed(st) // 60)}m so far on {st['title']}")


def focus_resume():
    st = _focus_state()
    if not st:
        print("No focus timer running")
        return
    if not st.get("paused_at"):
        print(f"⏱ Not paused · timer running on {st['title']}")
        return
    st["paused_total"] = st.get("paused_total", 0) + (
        datetime.now(timezone.utc) - _parse_ts(st["paused_at"])).total_seconds()
    st["paused_at"] = None
    _write_focus(st)
    print(f"▶️ Resumed {st['title']} · {int(focus_elapsed(st) // 60)}m so far")


def focus_stop(discard=False, as_pid=None, as_tid=None):
    st = _focus_state()
    if not st:
        print("No focus timer running")
        return
    if discard:
        os.remove(FOCUS_FILE)
        mins = max(1, int(focus_elapsed(st) // 60))
        print(f"⏱ discarded ({st['title']} · {mins}m not logged)")
        return
    if as_tid:
        # stop-twist: log onto a picked task instead - sweep/note follow it
        st = dict(st)
        st["tid"] = as_tid
        st["pid"] = as_pid or ((cache_store.find_task(as_tid) or {}).get("projectId")
                               or (cache_store.find_task(as_tid) or {}).get("_projectId"))
        st["title"] = _task_title(as_tid, "task")
    # Duration-true record + sweep + today-block note. The focus file
    # only goes once the record LANDED - a failed stop keeps the timer alive
    # (stop again to retry, or discard) instead of silently losing the session.
    try:
        frag = _close_session(st)
    except Exception as e:
        print(f"🎯 log failed ({type(e).__name__}) · timer kept running; "
              "stop again to retry, or discard")
        return
    try:
        os.remove(FOCUS_FILE)
    except OSError:
        pass
    print("🎯 " + frag)


def focus_log(pid, tid, minutes):
    import api as api_mod
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=int(minutes))
    fmt = "%Y-%m-%dT%H:%M:%S+0000"
    api_mod.TickTickAPI(cfg.get_token()).create_focus(
        start.strftime(fmt), end.strftime(fmt), task_id=tid)
    print(f"🎯 {minutes}m logged on {_title()}")


# ── Focus session blocks ─────────────────────────────────────────────────────
# The parse/serialize grammar lives in src/focus_blocks.py (pure, unit-tested).
# Everything here is the I/O side: LIVE read-modify-write (the sticky/app may
# have ticked boxes since the last cache sync - TickTick merges concurrent
# sticky + API edits (verified against the live app), so RMW is safe even
# with an open sticky), cache mirroring, and the session-end sweep + note.

def _api():
    import api as api_mod
    return api_mod.TickTickAPI(cfg.get_token())


def _today():
    return datetime.now().strftime("%Y-%m-%d")   # LOCAL date, on purpose


def _task_title(tid, default=None, pid=None):
    """Cache title, else (with pid) a LIVE GET - freshly-created tasks aren't
    in the hourly cache yet and a checkbox labeled 'Task' is useless."""
    t = cache_store.find_task(tid)
    if t and t.get("title"):
        return t["title"]
    if pid:
        try:
            live = _api().get_task(pid, tid)
            if live.get("title"):
                return live["title"]
        except Exception:
            pass
    return default or _title()


def _patch_content_cache(tid, content):
    """Mirror a content write into all_tasks/project_data AND all_notes
    (note_save.py pattern - notes render from all_notes)."""
    from dispatch import _patch_task_cache
    _patch_task_cache(tid, content=content)
    try:
        notes = cache_store.get("all_notes")
        if notes:
            cache_store.set("all_notes",
                            [dict(n, content=content) if n.get("id") == tid else n
                             for n in notes])
    except Exception:
        cache_store.invalidate("all_notes")


def _fx_rmw(pid, tid, mutate):
    """LIVE read-modify-write of a task's session blocks. mutate(doc, today)
    → result. ONE live GET, ONE conditional POST + cache mirror.
    Returns (result, doc, live_task)."""
    api = _api()
    live = api.get_task(pid, tid)
    old = live.get("content") or ""
    doc = fb.parse(old)
    result = mutate(doc, _today())
    new = fb.serialize(doc)
    if new != old:
        api.update_task(tid, pid, current=live, content=new)
        _patch_content_cache(tid, new)
        app_sync_after_write()   # open stickies redraw in seconds, not ~1 min
    return result, doc, live


def _complete_cache_patch(pid, tid):
    """The complete-task cache mirror (clone of dispatch's complete: branch)."""
    try:
        cached = cache_store.get("all_tasks")
        if cached is not None:
            cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
        from dispatch import _patch_project_data
        _patch_project_data(tid, pid_old=pid, remove=True)
    except Exception:
        cache_store.invalidate("all_tasks")


def _sweep_from_doc(doc):
    """Complete every checked+linked checkbox task not known to be closed.
    Skip only when the cache POSITIVELY says closed or NOTE-kind; absent from
    cache → attempt anyway (fresh tasks aren't in the hourly cache). NO focus
    records, NO content rewrite. → (done, failed).

    Completes run on a small thread pool (the POSTs are independent and were
    the bulk of the bar-sweep wait) with one API client per call; the cache
    mirror is ONE batched all_tasks write after the pool drains - the old
    per-task full-cache rewrite multiplied a ~1 MB write by N."""
    targets = fb.sweep_targets(doc)
    if not targets:
        return 0, 0
    # wontdo_tasks rides along: an abandoned task left all_tasks, and its
    # ticked checkbox must NOT get re-completed by the sweep (the entries
    # carry status -1, so the skip below catches them)
    known = {t.get("id"): t
             for t in (cache_store.get("all_tasks") or [])
             + (cache_store.get("all_notes") or [])
             + (cache_store.get("wontdo_tasks") or [])}
    work = []
    for pid, tid in targets:
        t = known.get(tid)
        if t and (t.get("status", 0) != 0 or t.get("kind") == "NOTE"):
            continue
        work.append((pid, tid))
    if not work:
        return 0, 0

    def _complete(job):
        pid, tid = job
        try:
            _api().complete_task(pid, tid)
            return pid, tid
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(work))) as pool:
        results = list(pool.map(_complete, work))
    swept = [r for r in results if r]
    failed = len(results) - len(swept)
    if swept:
        try:
            swept_tids = {tid for _, tid in swept}
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set(
                    "all_tasks",
                    [t for t in cached if t.get("id") not in swept_tids])
            from dispatch import _patch_project_data
            for pid, tid in swept:
                _patch_project_data(tid, pid_old=pid, remove=True)
        except Exception:
            cache_store.invalidate("all_tasks")
    return len(swept), failed


def _log_focus_record(start_iso, secs, tid, note=None):
    """Create the focus record (duration-true). The v1 endpoint accepts an
    optional note. Note failure degrades to a plain
    record. Returns note_skipped."""
    end = _parse_ts(start_iso) + timedelta(seconds=max(60, secs))
    api = _api()
    if note:
        note = note[:4000]
    try:
        api.create_focus(start_iso, end.strftime(TT_FMT), task_id=tid, note=note)
        return False
    except TypeError:
        # live api.py without the note param (stale sync) - plain retry
        api.create_focus(start_iso, end.strftime(TT_FMT), task_id=tid)
        return bool(note)
    except Exception:
        if not note:
            raise
        api.create_focus(start_iso, end.strftime(TT_FMT), task_id=tid)
        return True


def _close_session(st):
    """End-of-session bundle for a timer state: sweep the focus task's checked
    checkboxes, capture today's block as the record note, log the record.
    Returns the toast fragment. Raises only if the record itself failed."""
    secs = focus_elapsed(st)
    mins = max(1, int(secs // 60))
    tid = st.get("tid") or None
    pid = st.get("pid") or None
    swept = 0
    note = None
    if tid and pid:
        try:
            doc = fb.parse(_api().get_task(pid, tid).get("content") or "")
            swept, _failed = _sweep_from_doc(doc)
            note = fb.today_note(doc, _today()) or None
        except Exception:
            swept, note = 0, None
    note_skipped = _log_focus_record(st["start"], secs, tid, note)
    frag = f"{mins}m logged" + (f" on {st.get('title', 'Task')}" if tid else " (no task)")
    if swept:
        frag += f" · 🧹 {swept} swept"
    if note_skipped:
        frag += " · note skipped"
    return frag


def _ensure_block_if_history(pid, tid):
    """Session start stamps today's block ONLY when the task already has
    staging history - no '### date/---' noise on plain focuses (carry-over of
    older unchecked lines rides along). Best-effort."""
    try:
        _fx_rmw(pid, tid, lambda doc, today:
                fb.ensure_today(doc, today) if doc.blocks else None)
    except Exception:
        pass


# ── Pomo sidecar - TickTick's pomo can't be task-bound in-app, so we
#    remember the task ourselves; self-heals when the app's pomo is idle. ────

def _pomo_timeline_start():
    """The running pomo segment's startDate (TT_FMT) - sidecar validity tag."""
    import plistlib
    out = subprocess.run(["defaults", "export", "com.TickTick.task.mac", "-"],
                         capture_output=True, check=False).stdout
    try:
        for seg in plistlib.loads(out).get("focus__pomodoro_timeline", []) or []:
            if isinstance(seg, dict) and "startDate" in seg:
                s = seg["startDate"]
                s = s if s.tzinfo else s.replace(tzinfo=timezone.utc)
                return s.strftime(TT_FMT)
    except Exception:
        pass
    return None


def _write_pomo(st):
    with open(POMO_FILE, "w") as f:
        json.dump(st, f)


def _drop_pomo():
    try:
        os.remove(POMO_FILE)
    except OSError:
        pass


def _pomo_sidecar():
    """The pomo attribution sidecar, validated against the app: gone/stale
    when no pomo runs or a DIFFERENT pomo started since it was written."""
    try:
        with open(POMO_FILE) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    state, _ = _pomo_app_state()
    if state == "idle":
        _drop_pomo()
        return None
    ps = st.get("pomo_start")
    if ps:
        cur = _pomo_timeline_start()
        if cur and cur != ps:
            _drop_pomo()
            return None
    return st


def _current_focus_task():
    """(pid, tid, title) of the running session's task - timer file first,
    pomo sidecar second, None when nothing task-bound runs."""
    st = _focus_state()
    if st and st.get("tid"):
        return st["pid"], st["tid"], st.get("title", "Task")
    ps = _pomo_sidecar()
    if ps and ps.get("tid"):
        return ps["pid"], ps["tid"], ps.get("title", "Task")
    return None


# ── Focus bar lifecycle - the bar itself is Scripts/focus_bar.py ────────────

def _bar_read():
    try:
        with open(BAR_STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _bar_write(**patch):
    """Read-merge-atomic-replace: xact only ever touches `visible`; the bar
    owns origin + everything else - merging keeps both writers safe."""
    st = _bar_read()
    st.update(patch)
    st["updated"] = _now_iso()
    tmp = BAR_STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, BAR_STATE)


def _bar_alive():
    import fcntl
    try:
        f = open(BAR_LOCK)
    except OSError:
        return False
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        return False          # we could grab it → nobody holds it
    except OSError:
        return True
    finally:
        f.close()


# Per-user marker (NOT /tmp: world-writable + symlink-followable + first-writer
# ownership would suppress the hint for other users).
_PYOBJC_HINT = os.path.expanduser("~/.ticktick_alfred/pyobjc_hint")
_BAR_PY_CACHE = os.path.expanduser("~/.ticktick_alfred/bar_python")
_BAR_PY = None          # resolved once per process


def _bar_python():
    """A python3 that can import PyObjC (`objc`) - the bar's hard dependency.
    Alfred's own python3 ships without PyObjC, so sys.executable won't do:
    probe Homebrew (arm → Intel) then PATH, each with a real import test."""
    global _BAR_PY
    if _BAR_PY:
        return _BAR_PY
    # Cross-process cache: the probe imports AppKit in a fresh python (1-3s),
    # and every xact invocation is a fresh process - don't re-pay it. Staleness
    # (pyobjc uninstalled later) just means a bar that exits 3 into the log;
    # delete ~/.ticktick_alfred/bar_python to force a re-probe.
    try:
        with open(_BAR_PY_CACHE) as f:
            cached = f.read().strip()
        if cached and os.path.exists(cached):
            _BAR_PY = cached
            return cached
    except OSError:
        pass
    import shutil
    # Probe EVERYTHING focus_bar imports - pyobjc-core alone (a common partial
    # install) would pass an `import objc` probe and then die in the bar.
    probe = "import objc, AppKit, Quartz, PyObjCTools.AppHelper"
    for c in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3",
              shutil.which("python3")):
        if c and os.path.exists(c):
            try:
                if subprocess.run([c, "-c", probe], capture_output=True,
                                  timeout=10).returncode == 0:
                    _BAR_PY = c
                    try:
                        os.makedirs(os.path.dirname(_BAR_PY_CACHE), exist_ok=True)
                        with open(_BAR_PY_CACHE, "w") as f:
                            f.write(c)
                    except OSError:
                        pass
                    return c
            except Exception:
                pass
    return None


def bar_spawn():
    """Detached spawn of the focus bar (singleton via BAR_LOCK flock inside
    the bar itself; racing spawns exit cleanly). stderr → a logfile, NOT
    devnull - a faceless AppKit agent that dies silently is undebuggable."""
    if _bar_alive():
        return
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "focus_bar.py")
    if not os.path.exists(script):
        return
    py = _bar_python()
    if not py:
        # Focus keeps working bar-less; hint at most once an hour (bar_spawn
        # rides many verbs - a banner per keystroke would be noise).
        try:
            import time
            stamp = os.path.getmtime(_PYOBJC_HINT) if os.path.exists(_PYOBJC_HINT) else 0
            if time.time() - stamp > 3600:
                os.makedirs(os.path.dirname(_PYOBJC_HINT), exist_ok=True)
                with open(_PYOBJC_HINT, "w") as f:
                    f.write("")
                from script_base import notify
                notify("Focus bar needs PyObjC · Settings → Install PyObjC")
        except Exception:
            pass
        return
    with open("/tmp/tickal_focus_bar.log", "ab") as log:
        subprocess.Popen([py, script],
                         start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=log)


def _bar_wake():
    """Fresh session ⇒ the bar shows, even if previously minimized."""
    try:
        _bar_write(visible=True)
        bar_spawn()
    except Exception:
        pass


def bar_show():
    _bar_write(visible=True)
    bar_spawn()
    print("👁 Focus bar shown")


def bar_hide():
    _bar_write(visible=False)
    print("🫥 Focus bar hidden")


def _ask(prompt, title="TickAL", hidden=False, default=""):
    """Module-level dialog helper. Returns None on Cancel, "" on
    empty-OK - the journal flow assigns those OPPOSITE meanings (cancel =
    stop + save partial; empty = skip this prompt), so the two must be
    distinguishable. v2login keeps its own nested copy untouched."""
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')
    osa = ('text returned of (display dialog "{}" default answer "{}" '
           'with title "{}"{})').format(esc(prompt), esc(default), esc(title),
                                        " with hidden answer" if hidden else "")
    r = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.rstrip("\n") if hidden else r.stdout.strip()


# ── PyObjC installer (Settings → Install PyObjC) ─────────────────────────────
# Installs PyObjC into THIS interpreter - the one py.sh resolved for every
# keyword - so the focus bar and clipboard-image attach can't land in a python
# the workflow never uses (the classic "plain pip3 hit the wrong python"
# failure from the clean-machine test). Homebrew Pythons are PEP-668
# externally managed: plain install fails, the retry adds
# --break-system-packages (pyobjc has no brew formula and nothing brew
# manages depends on it, so the flag is safe).
def _pyobjc_probe(py):
    """True when the FULL set focus_bar imports is present - pyobjc-core
    alone (a common partial install) must not pass."""
    try:
        return subprocess.run(
            [py, "-c", "import objc, AppKit, Quartz, PyObjCTools.AppHelper"],
            capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def pyobjc_install():
    py = sys.executable
    if _pyobjc_probe(py):
        # Clear the bar-python cache anyway: a stale entry naming a DIFFERENT
        # python that lost pyobjc would keep killing the bar even though this
        # interpreter is fine - and this row is the designated remedy.
        try:
            os.remove(_BAR_PY_CACHE)
        except OSError:
            pass
        _dialog("PyObjC is already installed - the focus bar and "
                "clipboard-image attach are ready.", ["OK"], "OK")
        return
    if _dialog("PyObjC is missing. It powers the floating focus bar and "
               "clipboard-image attach - everything else works without it."
               "\n\nInstall it now? (A ~100 MB download - takes a minute "
               "or two; a banner confirms when done.)",
               ["Cancel", "Install"], "Install") != "Install":
        return
    subprocess.run(["osascript", "-e",
                    'display notification "Takes a minute or two - a banner '
                    'will confirm" with title "TickAL · installing PyObjC"'],
                   capture_output=True)
    cmd = [py, "-m", "pip", "install", "pyobjc"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 and "externally-managed" in (r.stderr + r.stdout):
            r = subprocess.run(cmd + ["--break-system-packages"],
                               capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        print("PyObjC install timed out · slow connection, or pip is "
              "building from source (no wheels for this Python yet)")
        return
    if r.returncode != 0:
        # pip appends [notice] self-update nags AFTER the real error - skip them
        lines = [l for l in (r.stderr or r.stdout).strip().splitlines()
                 if l.strip() and not l.lstrip().startswith("[notice]")]
        tail = lines[-1][:200] if lines else "unknown error"
        print(f"PyObjC install failed · {tail}")
        return
    # The bar launcher caches its probed python across processes - clear it
    # so the next focus session re-probes and finds the fresh install.
    try:
        os.remove(_BAR_PY_CACHE)
    except OSError:
        pass
    if _pyobjc_probe(py):
        print("PyObjC installed · focus bar ready from the next session")
    else:
        print("PyObjC installed but the import probe still fails - "
              "see Troubleshooting in the docs")


# ── Periodic 04:30 mint agent (Settings → Periodic Agent) ────────────────────
# Same toggle shape as Hourly Sync below: plistlib-emitted plist, py.sh as the
# interpreter resolver, launchctl-list verification, twin detection, stale
# Repair. Runs xact:pn_mint at 04:30 (launchd fires missed runs on wake;
# RunAtLoad + the pn_last_mint stamp catch up after a powered-off night).
PN_AGENT_LABEL = "com.tickal.periodic"
PN_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{PN_AGENT_LABEL}.plist")
PN_AGENT_LOG = "/tmp/tickal_periodic.log"


def _pn_agent_dict(wf):
    return {
        "Label": PN_AGENT_LABEL,
        "ProgramArguments": ["/bin/bash",
                             os.path.join(wf, "Scripts", "py.sh"),
                             os.path.join(wf, "Scripts", "xact.py"),
                             "xact:pn_mint"],
        "WorkingDirectory": wf,
        "StartCalendarInterval": {"Hour": 4, "Minute": 30},
        "RunAtLoad": True,
        "StandardOutPath": PN_AGENT_LOG,
        "StandardErrorPath": PN_AGENT_LOG,
    }


def _pn_agent_loaded():
    return subprocess.run(["launchctl", "list", PN_AGENT_LABEL],
                          capture_output=True).returncode == 0


def _twin_pn_agent():
    """A DIFFERENT user-authored periodic-mint agent (e.g. the hand-installed
    pre-2.7 template). Returns its label, or None."""
    import glob
    import plistlib
    for path in glob.glob(os.path.expanduser("~/Library/LaunchAgents/*.plist")):
        if os.path.basename(path) == f"{PN_AGENT_LABEL}.plist":
            continue
        try:
            with open(path, "rb") as f:
                d = plistlib.load(f)
        except Exception:
            continue
        label = str(d.get("Label", ""))
        args = " ".join(str(a) for a in d.get("ProgramArguments", []))
        if "pn_mint" in args or ("periodic" in label.lower()
                                 and "tickal" in label.lower()):
            return label or os.path.basename(path)[:-len(".plist")]
    return None


def _pn_agent_install(wf):
    import plistlib
    os.makedirs(os.path.dirname(PN_AGENT_PLIST), exist_ok=True)
    with open(PN_AGENT_PLIST, "wb") as f:
        plistlib.dump(_pn_agent_dict(wf), f)
    subprocess.run(["launchctl", "unload", PN_AGENT_PLIST],
                   capture_output=True)
    subprocess.run(["launchctl", "load", PN_AGENT_PLIST],
                   capture_output=True)
    return _pn_agent_loaded()


def _pn_agent_state(wf):
    """'' = healthy; otherwise a short reason the install is stale."""
    import plistlib
    try:
        with open(PN_AGENT_PLIST, "rb") as f:
            cur = plistlib.load(f)
    except Exception:
        return "its file is unreadable"
    args = [str(a) for a in cur.get("ProgramArguments", [])] or [""]
    if os.path.basename(args[0]) != "bash" or len(args) < 3:
        return "it predates this workflow version"
    py_sh = args[1]
    if not os.path.exists(py_sh):
        return "it points at a deleted workflow copy"
    if os.path.dirname(os.path.dirname(py_sh)) != wf:
        return "it points at a previous workflow copy"
    if not _pn_agent_loaded():
        return "launchd does not have it loaded"
    return ""


def pn_agent_toggle():
    wf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if not os.path.exists(PN_AGENT_PLIST):
        # The agent reads periodic_list_id from ~/.ticktick_alfred/config.json,
        # mirrored there by the first interactive pn use - gate on that.
        try:
            mirrored = bool(cfg.load().get("periodic_list_id"))
        except Exception:
            mirrored = False
        if not mirrored:
            _dialog("Periodic notes need a first run before the agent can "
                    "work: set the list id in Configure Workflow, then use "
                    "any pn action once (e.g. open today's note). Then come "
                    "back here.", ["OK"], "OK")
            return
        twin = _twin_pn_agent()
        if twin:
            _dialog(f"A periodic mint agent already runs on this Mac via "
                    f"{twin} - nothing to install.", ["OK"], "OK")
            return
        if _dialog("The periodic agent is OFF.\n\nInstall it? Every morning "
                   "at 04:30 (or on wake, if the Mac slept through it) it "
                   "mints the new day's note, refreshes today and recomputes "
                   f"the roll-ups (logs: {PN_AGENT_LOG}).",
                   ["Cancel", "Install"], "Install") != "Install":
            return
        if _pn_agent_install(wf):
            print("Periodic agent on · next mint 04:30")
        else:
            try:
                os.remove(PN_AGENT_PLIST)
            except OSError:
                pass
            print("Install failed · launchctl would not load the agent")
        return

    stale = _pn_agent_state(wf)
    if stale:
        btn = _dialog(f"The periodic agent is installed, but {stale}."
                      "\n\nRepair reinstalls it for this workflow copy; "
                      "Remove deletes it.",
                      ["Cancel", "Remove", "Repair"], "Repair")
        if btn == "Repair":
            print("Periodic agent repaired · next mint 04:30"
                  if _pn_agent_install(wf)
                  else "Repair failed · launchctl would not load the agent")
            return
        if btn != "Remove":
            return
    elif _dialog("The periodic agent is ON.\n\nRemove it? (Notes are still "
                 "minted the moment you open them - this only stops the "
                 "04:30 pre-mint.)",
                 ["Cancel", "Remove"], "Remove") != "Remove":
        return

    subprocess.run(["launchctl", "unload", PN_AGENT_PLIST],
                   capture_output=True)
    try:
        os.remove(PN_AGENT_PLIST)
    except OSError as e:
        print(f"Remove failed · {e}")
        return
    print("Periodic agent removed")


# ── Hourly cache-sync LaunchAgent (Settings → Hourly Sync) ───────────────────
# One toggle verb: a dialog states the current state and offers the valid
# moves. The agent runs src/sync.py THROUGH Scripts/py.sh (never a baked
# interpreter path - sys.executable is version-pinned under Homebrew and rots
# on upgrade), plists are emitted via plistlib (path escaping for free), and
# load success is verified via `launchctl list <label>` because launchctl
# load/unload exit 0 even when they fail. A plist that survives a workflow
# re-import points at the deleted old UUID folder - the ON branch detects
# that and offers Repair.
SYNC_AGENT_LABEL = "com.tickal.cachesync"
SYNC_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{SYNC_AGENT_LABEL}.plist")
SYNC_AGENT_LOG = "/tmp/tickal_cachesync.log"


def _dialog(prompt, buttons, default):
    """display-dialog wrapper; returns the clicked button ('' on Esc)."""
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')
    blist = ", ".join(f'"{esc(b)}"' for b in buttons)
    osa = ('button returned of (display dialog "{}" with title "TickAL" '
           'buttons {{{}}} default button "{}")').format(
               esc(prompt), blist, esc(default))
    r = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _sync_agent_dict(wf):
    return {
        "Label": SYNC_AGENT_LABEL,
        "ProgramArguments": ["/bin/bash",
                             os.path.join(wf, "Scripts", "py.sh"),
                             os.path.join(wf, "src", "sync.py"), "sync"],
        "WorkingDirectory": wf,
        "StartInterval": 3600,
        "RunAtLoad": True,
        "StandardOutPath": SYNC_AGENT_LOG,
        "StandardErrorPath": SYNC_AGENT_LOG,
    }


def _sync_agent_loaded():
    return subprocess.run(["launchctl", "list", SYNC_AGENT_LABEL],
                          capture_output=True).returncode == 0


def _twin_sync_agent():
    """A DIFFERENT user-authored TickAL/TickTick hourly-sync agent (e.g. a
    hand-rolled pre-2.7 one). Returns its label, or None."""
    import glob
    import plistlib
    for path in glob.glob(os.path.expanduser("~/Library/LaunchAgents/*.plist")):
        if os.path.basename(path) == f"{SYNC_AGENT_LABEL}.plist":
            continue
        try:
            with open(path, "rb") as f:
                d = plistlib.load(f)
        except Exception:
            continue
        label = str(d.get("Label", ""))
        args = " ".join(str(a) for a in d.get("ProgramArguments", []))
        if "sync.py" in args and ("tickal" in (label + args).lower()
                                  or "ticktick" in (label + args).lower()):
            return label or os.path.basename(path)[:-len(".plist")]
    return None


def _sync_agent_install(wf):
    """Write + (re)load the agent; True when launchd confirms it's loaded."""
    import plistlib
    os.makedirs(os.path.dirname(SYNC_AGENT_PLIST), exist_ok=True)
    with open(SYNC_AGENT_PLIST, "wb") as f:
        plistlib.dump(_sync_agent_dict(wf), f)
    subprocess.run(["launchctl", "unload", SYNC_AGENT_PLIST],
                   capture_output=True)
    subprocess.run(["launchctl", "load", SYNC_AGENT_PLIST],
                   capture_output=True)
    return _sync_agent_loaded()


def _sync_agent_state(wf):
    """'' = healthy; otherwise a short reason the install is stale."""
    import plistlib
    try:
        with open(SYNC_AGENT_PLIST, "rb") as f:
            cur = plistlib.load(f)
    except Exception:
        return "its file is unreadable"
    args = [str(a) for a in cur.get("ProgramArguments", [])] or [""]
    if os.path.basename(args[0]) != "bash" or len(args) < 3:
        return "it predates this workflow version"
    py_sh = args[1]
    if not os.path.exists(py_sh):
        return "it points at a deleted workflow copy"
    if os.path.dirname(os.path.dirname(py_sh)) != wf:
        return "it points at a previous workflow copy"
    if not _sync_agent_loaded():
        return "launchd does not have it loaded"
    return ""


def cachesync_toggle():
    wf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if not os.path.exists(SYNC_AGENT_PLIST):
        twin = _twin_sync_agent()
        if twin:
            _dialog(f"Hourly sync already runs on this Mac via {twin} - "
                    "nothing to install.", ["OK"], "OK")
            return
        if _dialog("Hourly background sync is OFF.\n\nInstall it? A "
                   "LaunchAgent refreshes the cache every hour in the "
                   f"background (logs: {SYNC_AGENT_LOG}).",
                   ["Cancel", "Install"], "Install") != "Install":
            return
        if _sync_agent_install(wf):
            print("Hourly sync on · first refresh running now")
        else:
            try:
                os.remove(SYNC_AGENT_PLIST)
            except OSError:
                pass
            print("Install failed · launchctl would not load the agent")
        return

    stale = _sync_agent_state(wf)
    if stale:
        btn = _dialog(f"Hourly background sync is installed, but {stale}."
                      "\n\nRepair reinstalls it for this workflow copy; "
                      "Remove deletes it.",
                      ["Cancel", "Remove", "Repair"], "Repair")
        if btn == "Repair":
            print("Hourly sync repaired · running now"
                  if _sync_agent_install(wf)
                  else "Repair failed · launchctl would not load the agent")
            return
        if btn != "Remove":
            return
    elif _dialog("Hourly background sync is ON.\n\nRemove it? (tsy and "
                 "in-place cache updates keep working - this only stops "
                 "the hourly refresh.)",
                 ["Cancel", "Remove"], "Remove") != "Remove":
        return

    subprocess.run(["launchctl", "unload", SYNC_AGENT_PLIST],
                   capture_output=True)
    try:
        os.remove(SYNC_AGENT_PLIST)
    except OSError as e:
        print(f"Remove failed · {e}")
        return
    print("Hourly sync removed")


# ── CRM records (customer notes + tattoo logbooks) ────────────────────────────
# Dialog chains behind the tcr pickers (browse ctx:crmnew/crmdone/crmlog) and
# the ⌘ Actions "✅ Session done" row. Engine + data model: src/crm_records.py.
# Every prompt is Esc-skippable except the two names (Esc there = cancel).
# Feedback goes through _crm_say (script_base.notify → Alfred's XAct chain),
# NEVER print: the picker route (browse ⏎ → modOpen runscript) has no
# downstream, so stdout is silently discarded there.

def _crm_say(msg):
    _notify_banner(msg, title="")


def _choose(prompt, options, title="TickAL", default=None):
    """osascript choose-from-list; the picked string, or None on Cancel.
    default preselects a row - Enter-through for the common case."""
    def esc(s):
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')
    olist = ", ".join(f'"{esc(o)}"' for o in options)
    dflt = f' default items {{"{esc(default)}"}}' if default else ""
    osa = ('choose from list {{{}}} with prompt "{}" with title "{}"{}'
           .format(olist, esc(prompt), esc(title), dflt))
    r = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True)
    out = r.stdout.strip()
    return None if (r.returncode != 0 or out in ("false", "")) else out


def _records_ready():
    import areas
    if not areas.crm_configured():
        _crm_say("CRM needs setup · Configure Workflow → CRM list id")
        return False
    if not areas.records_configured():
        _crm_say("CRM records need setup · Configure Workflow → CRM records list id")
        return False
    return True


def _record_by_id(tid):
    import areas
    import crm_records as cr
    for n in cr.records_notes():
        if n.get("id") == tid:
            return n
    try:   # cache can lag behind a hand-created note - fall back to live
        return cr._api().get_task(areas.RECORDS_ID, tid)
    except Exception:
        return None


def _crm_session_prefill(lb_title, marker):
    """Open the Add window prefilled for this logbook's next task. Token order:
    ~l before # (the tag terminates the multi-word list capture, trap #8);
    [[title]] resolves to the logbook link at create time - a literal URL here
    would trip the # tag trigger on its '#p/' fragment. The S<n>/Consult
    marker is a SUFFIX (Vex ruling): the calendar reads '🎨 Marko • Sleeve S2'.
    Trailing bare '*' auto-opens the schedule picker (Vex ruling 2026-07-19:
    every CRM handoff is a scheduling - don't make him type the star)."""
    import areas
    tag = areas.CONSULT_TAG if marker == "Consult" else areas.SESSION_TAG
    _run_trigger("Add", f"~l {areas.crm_list_name()} #{tag} [[{lb_title}]] {marker} *")


def _crmnew_continue(kind, cust):
    """Customer chosen (or just created) - pick/create the logbook, then hand
    off to the Add window so the session task gets scheduled the normal way.
    A lead converts to customer here - its first booking is the promotion."""
    import areas
    import crm_records as cr
    try:
        cust = cr.convert_lead(cust)
    except Exception:
        pass
    disp = cr.customer_display(cust) or "customer"
    lb = None
    if kind == "tattoo":
        mine = [l for l in cr.records_notes(areas.LOGBOOK_TAG)
                if (cr.parse_first_link(l.get("content") or "") or ("",) * 3)[2]
                == cust.get("id")]
        if mine:   # a consultation logbook may already exist - convert in place
            NEW = "🆕 New logbook"
            pick = _choose(f"{disp} - which logbook?",
                           [NEW] + [l.get("title") or "" for l in mine])
            if pick is None:
                _crm_say("Cancelled")
                return
            if pick != NEW:
                lb = next((l for l in mine if (l.get("title") or "") == pick), None)
    if lb is None:
        tattoo = _ask(f"{disp} - tattoo / project name?")
        if not (tattoo or "").strip():
            _crm_say("Cancelled")
            return
        # The logbook is real from here - these two are skippable, not aborts.
        quoted = _ask(f"{tattoo} - quoted price? (OK or Esc skips)") or ""
        lb = cr.create_logbook(cust, tattoo, quoted=quoted,
                               prep=(kind == "consult"))
        deposit = _ask("Deposit taken? (OK or Esc skips)") or ""
        if deposit.strip():
            cr.append_session(areas.RECORDS_ID, lb["id"], "payment",
                              charged=deposit, text="Deposit.")
    if kind == "consult":
        _crm_session_prefill(lb.get("title") or "", "Consult")
        _crm_say("🗂️ Logbook ready · schedule the consultation")
    else:
        n = cr.next_snum(lb.get("content") or "", lb["id"])
        _crm_session_prefill(lb.get("title") or "", f"S{n}")
        _crm_say(f"🗂️ Logbook ready · schedule S{n}")


def crmnew_newcust(kind):
    if not _records_ready():
        return
    import crm_records as cr
    name = _ask("New customer - name?")
    if not (name or "").strip():
        _crm_say("Cancelled")
        return
    # Esc = ABORT the whole flow (smoke ruling: nothing half-made);
    # plain OK on an empty field = skip it.
    contact = _ask_contact_chain(name)
    if contact is None:
        _crm_say("Cancelled · nothing created")
        return
    cust = cr.create_customer(name, *contact)
    _crmnew_continue(kind, cust)


def crmnew_go(rest):
    """Picker ⏎ lands here. Shapes: consult:<custTid> · tattoo:<custTid> ·
    session::<logTid>."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    parts = (rest or "").split(":")
    kind = parts[0] if parts else ""
    cust_tid = parts[1] if len(parts) > 1 else ""
    log_tid  = parts[2] if len(parts) > 2 else ""
    if kind == "session":
        lb = _record_by_id(log_tid)
        if not lb:
            _crm_say("Logbook not found · run tsy")
            return
        if areas.ARCHIVE_TAG in {str(t).lower() for t in (lb.get("tags") or [])}:
            # Touch-up on a finished tattoo: reopen the logbook first.
            if _dialog(f"{lb.get('title')} is archived - reopen for a touch-up?",
                       ["Cancel", "Reopen"], "Reopen") != "Reopen":
                _crm_say("Cancelled")
                return
            lb = cr.reopen_logbook(areas.RECORDS_ID, log_tid)
        n = cr.next_snum(lb.get("content") or "", log_tid)
        _crm_session_prefill(lb.get("title") or "", f"S{n}")
        return
    cust = _record_by_id(cust_tid)
    if not cust:
        _crm_say("Customer not found · run tsy")
        return
    _crmnew_continue(kind, cust)


def sessiondone(pid, tid):
    """The heart of the records flow: complete today's task (the calendar
    keeps the record - never reschedule), log the entry, recompute Paid,
    attach a clipboard photo, then archive or chain the next session."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    t = cache_store.find_task(tid) or {}
    title = t.get("title") or ""
    if not title:
        try:
            title = (cr._api().get_task(pid, tid) or {}).get("title") or ""
        except Exception:
            pass
    # Shape gate: S<n>/Consult prefix AND a records link. Prepare follow-ups
    # carry the logbook link too - the prefix keeps them (and any hand-made
    # task) from being completed + phantom-logged here.
    if not cr.is_session_task(title):
        _crm_say("Not a session task · only S<n> / Consult tasks log here")
        return
    lb_title, log_pid, log_tid = cr.parse_first_link(title)
    mk = cr.title_marker(title)
    is_s = bool(mk and mk.startswith("S"))
    marker = mk if is_s else "consultation"
    word   = "session" if is_s else "consultation"
    lb_deeplink = f"ticktick:///webapp/#p/{log_pid}/tasks/{log_tid}"

    # What happened? Esc = abort with nothing touched.
    outcome = _choose(f"{lb_title} - what happened?",
                      ["✅ Happened", "👻 No-show", "🚫 Cancelled",
                       "🔁 Rescheduled"], default="✅ Happened")
    if outcome is None:
        _crm_say("Cancelled · task untouched")
        return

    if outcome == "🔁 Rescheduled":
        # Task stays OPEN and keeps its S<n>; a dated trace lands in the
        # logbook, then the ⌘ menu opens on the task to pick the new date.
        try:
            cr.append_session(log_pid, log_tid, "rescheduled",
                              text=f"{marker} rescheduled.")
        except Exception as e:
            _crm_say(f"Trace failed: {type(e).__name__}: {e}")
            return
        _crm_say(f"🔁 {marker} rescheduled · pick the new date")
        # Straight onto the DATE picker (attributeScheduling recovers the ids
        # from the act-again context file) - not the full ⌘ menu.
        try:
            with open("/tmp/ticktick_reattribute.txt", "w") as f:
                f.write(f"{pid}:{tid}")
            _run_trigger("attributeScheduling")
        except OSError:
            reopen_actions(pid, tid)
        return

    if outcome in ("👻 No-show", "🚫 Cancelled"):
        kind_word = "no-show" if outcome == "👻 No-show" else "cancelled"
        kept = _ask("Kept deposit / charged anything? (OK skips · Esc cancels)")
        if kept is None:
            _crm_say("Cancelled · task untouched")
            return
        note = _ask("Note? (OK skips · Esc cancels)")
        if note is None:
            _crm_say("Cancelled · task untouched")
            return
        try:
            _api().complete_task(pid, tid)
            _complete_cache_patch(pid, tid)
        except Exception as e:
            _crm_say(f"Complete failed: {type(e).__name__}: {e}")
            return
        try:
            text = f"{marker} {kind_word}." + (f" {note.strip()}" if note.strip() else "")
            content, money, n, live_title = cr.append_session(
                log_pid, log_tid, kind_word, charged=kept, text=text)
            lb_title = live_title or lb_title
        except Exception as e:
            _crm_say(f"Logged FAILED: {type(e).__name__}: {e}")
            return
        # S<n> stays reserved (non-S entry) - offer the rebook straight away.
        label = f"Rebook {marker}"
        pick = _dialog(f"{lb_title} - rebook {marker}?",
                       ["Open logbook", "Later", label], label)
        if pick == label:
            _crm_session_prefill(lb_title, marker if is_s else "Consult")
        elif pick == "Open logbook":
            subprocess.run(["open", lb_deeplink], check=False)
        _crm_say(f"{'👻' if kind_word == 'no-show' else '🚫'} {marker} "
                 f"{kind_word} logged · {money} / {n} total")
        return

    # ✅ Happened - Esc aborts before anything is completed or written.
    # Smart defaults make the daily close Enter-Enter-Enter: duration =
    # last session's, charged = the open quote remainder.
    lb_cached = _record_by_id(log_tid) or {}
    d_dur = cr.last_duration(lb_cached.get("content") or "")
    d_chg = cr.quote_remainder(lb_cached.get("content") or "")
    d_setup = cr.last_setup(lb_cached.get("content") or "")
    answers = []
    for prompt, dflt in (
            (f"How long was the {word}? (OK skips · Esc cancels)", d_dur),
            ("Charged? (OK skips · Esc cancels)", d_chg),
            ("What did you do? (OK skips · Esc cancels)", ""),
            ("Setup? needles · inks · machine (OK skips)", d_setup)):
        v = _ask(prompt, default=dflt)
        if v is None:
            _crm_say("Cancelled · task NOT completed, nothing logged")
            return
        answers.append(v)
    dur, charged, did, setup = answers
    if (setup or "").strip():
        did = (did.strip() + ("\n" if did.strip() else "")
               + f"Setup: {setup.strip()}")
    final = False
    if is_s:   # the archive question belongs to needle sessions only
        f_ans = _dialog("Final session - archive the logbook?",
                        ["Cancel", "Archive", "More to come"], "More to come")
        if f_ans == "":
            _crm_say("Cancelled · task NOT completed, nothing logged")
            return
        final = f_ans == "Archive"

    try:
        _api().complete_task(pid, tid)
        _complete_cache_patch(pid, tid)
    except Exception as e:
        _crm_say(f"Complete failed: {type(e).__name__}: {e}")
        return
    try:
        content, money, n, live_title = cr.append_session(
            log_pid, log_tid, marker, dur, charged, did)
        lb_title = live_title or lb_title   # renamed logbook → fresh title
    except Exception as e:
        _crm_say(f"✅ done · logbook update FAILED: {type(e).__name__}: {e}")
        return

    photo = ""
    try:   # no PyObjC / empty clipboard = simply no photo, not an error
        import clipboard as clip_util
        img = clip_util.png_bytes()
    except Exception:
        img = None
    if img:
        try:
            import api_v2
            api_v2.TickTickV2().upload_attachment(log_pid, log_tid, img,
                                                  "session.png")
            photo = " · 📷 attached"
        except Exception:
            photo = " · 📷 upload failed"

    if not is_s:
        # Consultation outcome: book / wait / didn't-book (lead lost).
        pick = _choose(f"{lb_title} - consultation outcome?",
                       ["📅 Book the tattoo S1", "⏳ Not yet",
                        "📁 Didn't book · archive"])
        if pick == "📅 Book the tattoo S1":
            _crm_session_prefill(lb_title, "S1")
        elif pick == "📁 Didn't book · archive":
            try:
                cr.finish_logbook(log_pid, log_tid)
                _crm_say(f"📁 Consultation logged · logbook archived{photo}")
                return
            except Exception as e:
                _crm_say(f"Archive FAILED: {type(e).__name__}{photo}")
                return
        _crm_say(f"✅ consultation done · {money} / {n} total{photo}")
        return

    if final:
        try:
            cr.finish_logbook(log_pid, log_tid)
            pick = _dialog(f"✅ {marker} done · {money} total · archived{photo}",
                           ["Healing check", "Open logbook", "Done"], "Done")
            if pick == "Open logbook":
                subprocess.run(["open", lb_deeplink], check=False)
            elif pick == "Healing check":
                # Follow-up task, prepare-tagged (never a session shape) -
                # schedule it ~2 weeks out in the Add window.
                _run_trigger("Add", f"~l {areas.crm_list_name()} "
                             f"#{areas.PREPARE_TAG} [[{lb_title}]] Healing check ")
        except Exception as e:
            _crm_say(f"✅ {marker} done · archive FAILED: {type(e).__name__}{photo}")
        return
    nxt = cr.next_snum(content, log_tid)
    label = f"Schedule S{nxt}"
    pick = _dialog(f"{lb_title} - schedule S{nxt} now?",
                   ["Open logbook", "Later", label], label)
    if pick == label:
        _crm_session_prefill(lb_title, f"S{nxt}")
    elif pick == "Open logbook":
        subprocess.run(["open", lb_deeplink], check=False)
    _crm_say(f"✅ {marker} done · {money} / {n} total{photo}")


def crmlog(tid):
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    note = _record_by_id(tid)
    disp = (note or {}).get("title") or "note"
    text = _ask(f"{disp} - log line?")
    if not (text or "").strip():
        _crm_say("Cancelled")
        return
    section, stamp = "## Notes", True
    tags_lc = {str(t).lower() for t in ((note or {}).get("tags") or [])}
    if tags_lc & {areas.CUSTOMER_TAG, areas.LEAD_TAG}:
        pick = _dialog("Where does it go?",
                       ["Cancel", "Fun fact", "Note"], "Note")
        if pick == "":
            _crm_say("Cancelled")
            return
        if pick == "Fun fact":
            section, stamp = "## Fun facts", False
    try:
        cr.append_note_line(areas.RECORDS_ID, tid, text,
                            section=section, stamp=stamp)
        _crm_say(f"{'💡' if section == '## Fun facts' else '📝'} Logged to {disp}")
    except Exception as e:
        _crm_say(f"📝 Log failed: {type(e).__name__}: {e}")


def _ask_contact_chain(name):
    """TWO prompts (was four): one shape-detecting contact line - @handle =
    instagram, has @ and a dot = mail, digits = phone, space-separate any
    subset - then birthday. None = user cancelled (abort)."""
    import re as _re
    raw = _ask(f"{name} - contact? phone · mail · @instagram "
               "(space-separate · OK skips)")
    if raw is None:
        return None
    phone = mail = insta = ""
    for tok in (raw or "").replace(",", " ").split():
        if tok.startswith("@"):
            insta = tok
        elif "@" in tok and "." in tok:
            mail = tok
        elif _re.sub(r"[+()\-./]", "", tok).isdigit():
            phone = f"{phone} {tok}".strip()
    bday = _ask(f"{name} - birthday? (OK skips · Esc cancels)")
    if bday is None:
        return None
    return [phone, mail, bday, insta]


def crmperson():
    """➕ New lead / customer - standalone (backlog entry, CRM setup, walk-in
    who hasn't booked). Leads live in RECORDS, never on the calendar."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    name = _ask("Name?")
    if not (name or "").strip():
        _crm_say("Cancelled")
        return
    contact = _ask_contact_chain(name)
    if contact is None:
        _crm_say("Cancelled · nothing created")
        return
    kind = _dialog(f"{name} - lead or customer?",
                   ["Cancel", "Lead", "Customer"], "Customer")
    if kind == "":
        _crm_say("Cancelled · nothing created")
        return
    tag = areas.LEAD_TAG if kind == "Lead" else areas.CUSTOMER_TAG
    cr.create_customer(name, *contact, tag=tag)
    _crm_say(f"{'🌱 Lead' if kind == 'Lead' else '👤 Customer'} {name} created")


def _choose_customer(prompt="Which customer?"):
    """choose-from-list over customers + leads, with a 🆕 New customer path.
    Returns the customer dict, or None on cancel."""
    import areas
    import crm_records as cr
    NEW = "🆕 New customer"
    pool = cr.records_notes(areas.CUSTOMER_TAG) + cr.records_notes(areas.LEAD_TAG)
    pick = _choose(prompt, [NEW] + [c.get("title") or "" for c in pool])
    if pick is None:
        return None
    if pick != NEW:
        return next((c for c in pool if (c.get("title") or "") == pick), None)
    name = _ask("New customer - name?")
    if not (name or "").strip():
        return None
    contact = _ask_contact_chain(name)
    if contact is None:
        return None
    return cr.create_customer(name, *contact)


def crmimport():
    """📕 Backlog: import an already-finished tattoo - archived logbook with
    one summary entry, NO calendar task. Sessions count rides the S<k> marker
    (totals read count = max S-number)."""
    if not _records_ready():
        return
    import re as _re
    import areas
    import crm_records as cr
    cust = _choose_customer("Backlog tattoo - which customer?")
    if cust is None:
        _crm_say("Cancelled")
        return
    tattoo = _ask(f"{cr.customer_display(cust)} - tattoo / project name?")
    if not (tattoo or "").strip():
        _crm_say("Cancelled")
        return
    total = _ask("Total paid? (OK skips · Esc cancels)")
    if total is None:
        _crm_say("Cancelled · nothing created")
        return
    k_raw = _ask("How many sessions? (OK = 1 · Esc cancels)")
    if k_raw is None:
        _crm_say("Cancelled · nothing created")
        return
    m = _re.search(r"\d+", k_raw or "")
    k = max(1, int(m.group(0))) if m else 1
    when = _ask_date("When was it? Date or year (OK = today · Esc cancels)")
    if when == "CANCEL":
        _crm_say("Cancelled · nothing created")
        return
    state = _dialog("Tattoo state?", ["Cancel", "Still active", "Finished"],
                    "Finished")
    if state == "":
        _crm_say("Cancelled · nothing created")
        return
    lb = cr.create_logbook(cust, tattoo, started=when)
    cr.append_session(areas.RECORDS_ID, lb["id"], f"S{k}",
                      charged=total, text="Backlog import.", when=when)
    if state == "Finished":
        cr.finish_logbook(areas.RECORDS_ID, lb["id"])
    _crm_say(f"📕 {lb.get('title')} imported · {k} sessions"
             + (" · archived" if state == "Finished" else ""))


def _ask_date(prompt):
    """Lenient date dialog: 2026-7-3 / 3.7.2026 / 3.7. / 2025 all parse;
    empty OK = today (returns None); garbage gets ONE re-prompt then cancels.
    Returns ISO date, None (today), or "CANCEL"."""
    import re as _re
    import datetime as _dt
    for _ in range(2):
        raw = _ask(prompt)
        if raw is None:
            return "CANCEL"
        w = raw.strip()
        if not w:
            return None
        m = _re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", w)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = _re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})?", w)
        if m:
            y = m.group(3) or str(_dt.date.today().year)
            return f"{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        if _re.fullmatch(r"\d{4}", w):
            return f"{w}-01-01"
        prompt = f"'{w}' is not a date · YYYY-MM-DD or D.M.YYYY (OK = today)"
    return "CANCEL"


def crmpast(log_tid):
    """📕 Backlog: log a PAST session into a logbook - dated entry, no task."""
    if not _records_ready():
        return
    import re as _re
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    when = _ask_date("When? (OK = today · Esc cancels)")
    if when == "CANCEL":
        _crm_say("Cancelled")
        return
    n = cr.next_snum(lb.get("content") or "", log_tid)
    marker = _dialog("Log as?", ["Cancel", "Consultation", f"S{n}"], f"S{n}")
    if marker == "":
        _crm_say("Cancelled")
        return
    marker = "consultation" if marker == "Consultation" else f"S{n}"
    answers = []
    for prompt in ("How long? (OK skips · Esc cancels)",
                   "Charged? (OK skips · Esc cancels)",
                   "What did you do? (OK skips · Esc cancels)"):
        v = _ask(prompt)
        if v is None:
            _crm_say("Cancelled · nothing logged")
            return
        answers.append(v)
    dur, charged, did = answers
    _, money, n_total, _t = cr.append_session(
        areas.RECORDS_ID, log_tid, marker, dur, charged, did, when=when)
    _crm_say(f"📕 {marker} logged · {money} / {n_total} total")


def crmsched(pid, tid):
    """📅 Schedule a dormant task: reopen the ⌘ Actions menu on it (act-again
    mechanism) - Schedule and Link to logbook both live there."""
    reopen_actions(pid, tid)


def crmcopy(text):
    """Copy a contact value from a hub row (browse ⏎ can't ride the copy:
    chain - it lives on the ⌥⌘ canvas edge)."""
    subprocess.run(["pbcopy"], input=(text or "").encode())
    _crm_say(f"📋 Copied {text}")


def crmpay(log_tid):
    """💶 Log a payment outside a session (deposit, remainder, refund with a
    minus). A 'payment' entry sums into Paid without touching the session
    count."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    amount = _ask(f"{lb.get('title')} - amount? (minus = refund)")
    if not (amount or "").strip():
        _crm_say("Cancelled")
        return
    note = _ask("Note? (OK skips · Esc cancels)")
    if note is None:
        _crm_say("Cancelled · nothing logged")
        return
    _c, money, n, _t = cr.append_session(
        areas.RECORDS_ID, log_tid, "payment", charged=amount,
        text=(note.strip() or "Payment."))
    _crm_say(f"💶 {amount} logged · {money} / {n} total")


def crmedit(tid):
    """✏️ Open the note in Alfred's text view - the SAME editor as the ⌘
    Actions 📝 Note row, fired directly: write the act-again context file,
    fire ET attributeNote, ensure_task_context recovers the ids."""
    import areas
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as f:
            f.write(f"{areas.RECORDS_ID}:{tid}")
    except OSError as e:
        _crm_say(f"Edit failed: {e}")
        return
    _run_trigger("attributeNote")


AFTERCARE_FILE = os.path.expanduser("~/.ticktick_alfred/aftercare.txt")
AFTERCARE_DEFAULT = """Hey {name}! Quick aftercare guide for your fresh tattoo:
- keep the wrap on for 3-4 hours
- wash gently with lukewarm water + unscented soap, pat dry
- thin layer of aftercare cream 2-3x a day
- no sun, pool, sauna or gym sweat for 2 weeks
- itching is normal - do NOT scratch or pick

Any questions, message me anytime! 🖤"""


def crmaftercare(cust_tid):
    """🩹 Aftercare text → clipboard, {name} substituted. The template lives
    in ~/.ticktick_alfred/aftercare.txt (created on first use - edit it)."""
    if not _records_ready():
        return
    import crm_records as cr
    cust = _record_by_id(cust_tid)
    name = cr.customer_display(cust) if cust else ""
    try:
        with open(AFTERCARE_FILE) as f:
            tpl = f.read()
    except OSError:
        tpl = AFTERCARE_DEFAULT
        try:
            with open(AFTERCARE_FILE, "w") as f:
                f.write(tpl)
        except OSError:
            pass
    text = tpl.replace("{name}", name or "there")
    subprocess.run(["pbcopy"], input=text.encode())
    _crm_say(f"🩹 Aftercare for {name or 'customer'} copied · template: "
             f"~/.ticktick_alfred/aftercare.txt")


def crmbrowse(ctx):
    """Trampoline: reopen the Browse window at a CRM ctx - the crmhub rows
    navigate with this (plain browse rows can't switch ctx on ⏎). Fires
    BrowseCtx, whose Arg&Vars node turns the argument into the browse_ctx
    SESSION variable - firing Browse directly would dump the raw ctx string
    into the search bar as query text (bug, 2026-07-19)."""
    _run_trigger("BrowseCtx", ctx)


def crmphoto(log_tid):
    """🖼 Clipboard image → logbook attachment, anytime (reference sketch,
    session result, healed shot - same mechanism as Session done's photo)."""
    if not _records_ready():
        return
    import areas
    lb = _record_by_id(log_tid)
    try:
        import clipboard as clip_util
        img = clip_util.png_bytes()
    except Exception:
        img = None
    if not img:
        _crm_say("🖼 No image on the clipboard")
        return
    try:
        import api_v2
        api_v2.TickTickV2().upload_attachment(areas.RECORDS_ID, log_tid, img,
                                              "photo.png")
        _crm_say(f"🖼 Photo attached to {(lb or {}).get('title') or 'logbook'}")
    except Exception as e:
        _crm_say(f"🖼 Upload failed: {type(e).__name__}: {e}")


def crmcold(tid):
    """🥶 A lead went cold: one-line reason into ## Notes, retag → archive
    (out of every picker, kanban keeps the corpse)."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    cust = _record_by_id(tid)
    if not cust:
        _crm_say("Not found · run tsy")
        return
    reason = _ask(f"{cr.customer_display(cust)} - why cold? (OK skips · Esc cancels)")
    if reason is None:
        _crm_say("Cancelled")
        return
    try:
        cr.append_note_line(areas.RECORDS_ID, tid,
                            f"cold: {reason.strip() or 'no reason given'}")
        api = cr._api()
        live = api.get_task(areas.RECORDS_ID, tid)
        tags = [t for t in (live.get("tags") or [])
                if str(t).lower() not in (areas.LEAD_TAG, areas.CUSTOMER_TAG,
                                          areas.ARCHIVE_TAG)] \
            + [areas.ARCHIVE_TAG]
        api.update_task(tid, areas.RECORDS_ID, current=live, tags=tags)
        cr._patch_cache(tid, tags=tags)
        _crm_say(f"🥶 {cr.customer_display(cust)} archived")
    except Exception as e:
        _crm_say(f"🥶 Failed: {type(e).__name__}: {e}")


def crmrename(tid):
    """✏️ Rename a customer (👤) or tattoo (🎨) with the full ripple: titles,
    link texts, bullets - everywhere."""
    if not _records_ready():
        return
    import crm_records as cr
    note = _record_by_id(tid)
    if not note:
        _crm_say("Not found · run tsy")
        return
    title = note.get("title") or ""
    if title.startswith("👤"):
        new = _ask(f"{title} - new name?")
        if not (new or "").strip():
            _crm_say("Cancelled")
            return
        nt = cr.rename_customer(tid, new)
        _crm_say(f"✏️ Renamed → {nt} (everywhere)")
    else:
        new = _ask(f"{title} - new tattoo / project name?")
        if not (new or "").strip():
            _crm_say("Cancelled")
            return
        nt = cr.rename_logbook(tid, new)
        _crm_say(f"✏️ Renamed → {nt} (everywhere)")


def crmsummary(log_tid):
    """🧾 The logbook's money story as paste-ready text (invoice, where-we-
    stand DM): sessions, amounts, the Paid/Quoted line."""
    if not _records_ready():
        return
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    lines = [lb.get("title") or "Logbook", ""]
    for m in cr.ENTRY_RE.finditer(lb.get("content") or ""):
        segs = [s.strip() for s in m.group(1).split("·")]
        date = segs[0]
        mk = segs[1] if len(segs) > 1 else ""
        amt = segs[3] if len(segs) > 3 else "-"
        if amt and amt != "-":
            lines.append(f"{date} · {mk} · {amt}")
        else:
            lines.append(f"{date} · {mk}")
    lines += ["", cr.paid_summary(lb.get("content") or "")]
    subprocess.run(["pbcopy"], input="\n".join(lines).encode())
    _crm_say(f"🧾 Summary copied · {lb.get('title')}")


def crmcsv():
    """🧾 Accountant export: every dated charge/deposit/refund of a period as
    CSV rows in ~/Downloads, revealed in Finder."""
    if not _records_ready():
        return
    import crm_records as cr
    from datetime import date as _date
    today = _date.today()
    pick = _choose("Export which period?",
                   ["This month", "Last month", "This year", "Last year",
                    "All time"], default="This year")
    if pick is None:
        _crm_say("Cancelled")
        return
    m0 = today.replace(day=1)
    if pick == "This month":
        start, end = m0.isoformat(), None
    elif pick == "Last month":
        from datetime import timedelta as _td
        lm_end = m0 - _td(days=1)
        start, end = lm_end.replace(day=1).isoformat(), lm_end.isoformat()
    elif pick == "This year":
        start, end = f"{today.year}-01-01", None
    elif pick == "Last year":
        start, end = f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"
    else:
        start = end = None
    import csv
    slug = pick.lower().replace(" ", "-")
    path = os.path.expanduser(
        f"~/Downloads/tickal-crm-{slug}-{today.isoformat()}.csv")
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "customer", "tattoo", "entry", "duration_min",
                    "amount", "currency"])
        for e in sorted(cr.entries_detailed(), key=lambda x: x["date"]):
            if (start and e["date"] < start) or (end and e["date"] > end):
                continue
            if e["amount"] is None and not e["is_s"]:
                continue
            w.writerow([e["date"], e["cust_title"],
                        (e["lb"].get("title") or ""), e["marker"],
                        e["minutes"] or "", e["amount"] if e["amount"] is not None else "",
                        e["sym"] or "€"])
            n += 1
    subprocess.run(["open", "-R", path], check=False)
    _crm_say(f"🧾 {n} rows → {os.path.basename(path)}")


def crmclose(log_tid):
    """📁 Archive a logbook directly - no fake session required."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    title = (lb or {}).get("title") or "logbook"
    if _dialog(f"Archive {title}?", ["Cancel", "Archive"], "Archive") != "Archive":
        _crm_say("Cancelled")
        return
    try:
        cr.finish_logbook(areas.RECORDS_ID, log_tid)
        _crm_say(f"📁 {title} archived")
    except Exception as e:
        _crm_say(f"📁 Archive failed: {type(e).__name__}: {e}")


def crmconvert(tid):
    """🌱 Lead → 👤 customer, explicitly (bookings convert automatically)."""
    if not _records_ready():
        return
    import crm_records as cr
    cust = _record_by_id(tid)
    if not cust:
        _crm_say("Not found · run tsy")
        return
    cr.convert_lead(cust)
    _crm_say(f"👤 {cr.customer_display(cust)} is a customer now")


def crmlink(pid, tid):
    """🔗 Link an existing calendar task to a logbook: the title gains the
    logbook link + S<n>/Consult suffix, making it a records session task."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    NEW = "🆕 New logbook…"
    lbs = cr.records_notes(areas.LOGBOOK_TAG)
    pick = _choose("Link to which logbook?",
                   [NEW] + [l.get("title") or "" for l in lbs])
    if pick is None:
        _crm_say("Cancelled")
        return
    if pick == NEW:
        cust = _choose_customer()
        if cust is None:
            _crm_say("Cancelled")
            return
        tattoo = _ask(f"{cr.customer_display(cust)} - tattoo / project name?")
        if not (tattoo or "").strip():
            _crm_say("Cancelled")
            return
        lb = cr.create_logbook(cust, tattoo)
    else:
        lb = next((l for l in lbs if (l.get("title") or "") == pick), None)
        if lb is None:
            _crm_say("Logbook not found")
            return
    n = cr.next_snum(lb.get("content") or "", lb["id"])
    mk = _dialog("Link as?", ["Cancel", "Consult", f"S{n}"], f"S{n}")
    if mk == "":
        _crm_say("Cancelled")
        return
    api = cr._api()
    live = api.get_task(pid, tid)
    old = cr.LINK_RE.sub("", live.get("title") or "").strip()
    link = cr.task_link(areas.RECORDS_ID, lb["id"], lb.get("title") or "")
    new_title = f"{old} {link} {mk}".strip() if old else f"{link} {mk}"
    api.update_task(tid, pid, current=live, title=new_title)
    try:   # mirror into the task caches so gates/pickers see it immediately
        for key in ("all_tasks",):
            pool = cache_store.get(key) or []
            for t in pool:
                if t.get("id") == tid:
                    t["title"] = new_title
            cache_store.set(key, pool)
        import dispatch as _disp
        _disp._patch_project_data(tid, fields={"title": new_title},
                                  pid_old=pid, pid_new=pid)
    except Exception:
        pass
    _crm_say(f"🔗 Linked · {lb.get('title')} {mk}")


def v2login():
    """One-time TickTick sign-in for the internal v2 API (attachments, the
    Completed view, the tag tree). Two macOS dialogs - the password field is
    MASKED (hidden answer) and the password goes straight to signon, never to
    disk; only the session token is cached (~/.ticktick_alfred/config.json,
    0600 / Keychain). Sign-in-with-Apple accounts have no password → they
    paste a token instead (save_token.py)."""
    def _ask(prompt, hidden=False):
        osa = ('text returned of (display dialog "{}" default answer "" '
               'with title "TickAL"{})').format(
                   prompt, " with hidden answer" if hidden else "")
        r = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True)
        if r.returncode != 0:
            return ""
        # Passwords may legitimately carry edge whitespace - shave only
        # osascript's trailing newline. Emails get a full strip.
        return r.stdout.rstrip("\n") if hidden else r.stdout.strip()
    user = _ask("TickTick email:")
    if not user:
        print("Login cancelled")
        return
    pw = _ask("TickTick password:", hidden=True)
    if not pw:
        print("Login cancelled")
        return
    try:
        import api_v2
        api_v2.TickTickV2().signon(user, pw)
        print("✓ Signed in · attachments, Completed view and tag tree enabled")
    except Exception as e:
        print(f"Login failed · {e}")


# ── Periodic notes 💫 - thin delegators to src/periodic_engine ───────────────
def _pn_gate():
    """Every pn_* verb is externally fireable (Shortcuts) - an unconfigured
    install must get an honest pointer, not a 404 against an empty pid.
    A present-but-BLANK Alfred field means the user turned the feature off:
    clear the config.json mirror too, so the headless agent switches off
    with it (blanking the field must actually disable)."""
    import areas
    if not areas.periodic_configured():
        if os.environ.get("periodic_list_id", None) == "":
            try:
                data = cfg.load()
                if data.pop("periodic_list_id", None) is not None:
                    cfg.save(data)
            except Exception:
                pass
        print("💫 Periodic notes need setup · set periodic_list_id in "
              "Settings (docs 47)")
        return False
    return True


def _pn():
    import periodic_engine
    return periodic_engine


_PN_SPECS = ("daily", "yesterday", "weekly", "monthly", "quarterly", "yearly")
_PN_KINDS = {"w": "win", "n": "nag", "t": "thought",
             "k": "task", "l": "link", "m": "mood"}


def _pn_bg(arg):
    """Detached background xact run - the instant-open path (opens were slow
    when the full refresh + Tier-2 fetches ran BEFORE the app opened). The
    child inherits env (config gate + Alfred vars ride)."""
    wf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open("/tmp/tickal_periodic.log", "a") as logf:
            subprocess.Popen(
                ["/bin/bash", os.path.join(wf, "Scripts", "py.sh"),
                 os.path.join(wf, "Scripts", "xact.py"), arg],
                stdout=logf, stderr=logf, start_new_session=True)
    except Exception:
        pass


def pn_open(spec):
    if not _pn_gate():
        return
    if spec not in _PN_SPECS:
        print(f"💫 Unknown period {spec!r}")
        return
    pe = _pn()
    p, task, minted = pe.resolve(spec)
    if not task:
        print(f"💫 No note for {spec} yet")
        return
    # open FIRST, refresh in the background - the app-sync nudge redraws the
    # open note a few seconds later
    subprocess.run(["open", pe.open_link(task)], check=False)
    if minted or not pe._refresh_fresh(p):
        _pn_bg(f"xact:pn_refresh:{spec}")
    import periodic_model as pm
    print(f"💫 {pm.title(p)} {'minted' if minted else 'open'}")


def pn_sticky(spec):
    if not _pn_gate():
        return
    pe = _pn()
    p, task, minted = pe.resolve(spec)
    if not task:
        print(f"💫 No note for {spec} yet")
        return
    if minted or not pe._refresh_fresh(p):
        _pn_bg(f"xact:pn_refresh:{spec}")     # sticky opens NOW, note catches up
    pid = task.get("projectId") or task.get("_projectId") or ""
    os.environ["task_title"] = task.get("title") or "Note"
    sticky(pid, task.get("id"))


def _pn_decode(rest):
    """b64-JSON dict first, plain-text fallback (the Shortcuts channel).
    Non-dict decodes (a plain word that happens to be valid b64) fall through
    to the plain parser instead of AttributeError-ing."""
    import base64
    try:
        obj = json.loads(base64.b64decode(rest, validate=True).decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def pn_entry(rest):
    if not _pn_gate():
        return
    spec = _pn_decode(rest)
    if spec is None:
        # plain: "w Shipped it" / bare text = thought / bare "l" = clipboard link
        text = rest.strip()
        kind = "thought"
        head, _, tail = text.partition(" ")
        if head.lower() in _PN_KINDS and (tail or head.lower() == "l"):
            kind, text = _PN_KINDS[head.lower()], tail.strip()
        spec = {"kind": kind, "text": text}
    kind = spec.get("kind") or "thought"
    if kind not in _PN_KINDS.values():
        kind = "thought"                      # unknown b64 kind → honest default
    text = (spec.get("text") or "").strip()
    if kind == "link" and not text:
        r = subprocess.run(["pbpaste"], capture_output=True)
        text = r.stdout.decode("utf-8", "replace").strip()
        if not text:
            print("🔗 Clipboard is empty")
            return
    if kind == "mood":
        import re as _re
        m = _re.match(r"^([1-5])(?!\d)\s*·?\s*(.*)$", text)
        if not m:
            print("😊 Mood is 1-5 (e.g. 'pn + m 4 · tired')")
            return
        note = m.group(2).strip()         # normalize: '4 tired' works too
        text = m.group(1) + (f" · {note}" if note else "")
    if not text:
        print("💫 Nothing to log")
        return
    print(_pn().append_entry(kind, text))


def pn_income(rest):
    if not _pn_gate():
        return
    spec = _pn_decode(rest)
    if spec is None:
        raw = rest.strip()
        if not raw:
            raw = _ask("Amount · label  (e.g. 485 groceries)") or ""
            if not raw.strip():
                print("💰 Nothing logged")
                return
        import periodic_model as pm
        head, _, tail = raw.strip().partition(" ")
        amt = pm.parse_amount(head)
        if amt is None:
            print("💰 Amount first · e.g. 485 groceries")
            return
        spec = {"amount": amt, "label": tail.strip()}
    print(_pn().append_income(spec.get("amount") or 0, spec.get("label") or ""))


_JOURNAL_UI = {"morning": ("🌅", "Morning"), "evening": ("🌙", "Evening"),
               "weekly": ("📔", "Weekly")}
_GOALSEQ = run_path("tickal_pn_goalseq.json")


def _goalseq_load():
    """Active three-things sequence (weekly journal handoff) | None."""
    try:
        with open(_GOALSEQ) as f:
            d = json.load(f)
        if time.time() - d.get("ts", 0) < 600 and d.get("remaining", 0) > 0:
            return d
    except Exception:
        pass
    return None


def _goalseq_save(remaining):
    try:
        if remaining > 0:
            with open(_GOALSEQ, "w") as f:
                json.dump({"remaining": remaining, "ts": time.time()}, f)
        elif os.path.exists(_GOALSEQ):
            os.remove(_GOALSEQ)
    except Exception:
        pass


def pn_journal(slot):
    """Dialog run over UNANSWERED prompts. Fixed prompts ROUTE -
    mood → 💬 Mood line, money → 💰 entry, rating → 💬 Day ★, highlight →
    ✨ section - and the run hands off to a picker at the end (morning: the
    ☀️ Day-goal picker when no goal is set; weekly: the three-things picker
    into NEXT week's 🎯 Goals)."""
    if not _pn_gate():
        return
    if slot not in _JOURNAL_UI:
        print(f"💫 Unknown journal slot {slot!r}")
        return
    pe = _pn()
    import re as _re
    keys, pairs, jper = pe.journal_seed(slot)
    if pairs is None:
        print("💫 No journal section in the note (header renamed?)")
        return
    day0 = jper.start          # pin the note - dialog runs can cross midnight
    emoji, label = _JOURNAL_UI[slot]
    open_pairs = [(n, q) for n, q, a, _i in pairs if not a]
    total = len(pairs)
    answers, cancelled, routed = {}, False, []
    for n, q in open_pairs:
        key = keys[n - 1] if n <= len(keys) else "free"
        a = _ask(q, title=f"{label} journal · {n}/{total}")
        if a is None:                     # Cancel: stop, keep what we have
            cancelled = True
            break
        a = a.strip()
        if not a:                         # empty-OK = skip this prompt
            continue
        # (?!\d) - "10" must not prefix-match as mood/rating 1
        if key == "mood":
            m = _re.match(r"^([1-5])(?!\d)(?:\s*·?\s*(.*))?$", a)
            if m:
                import periodic_model as pm
                note = (m.group(2) or "").strip()
                routed.append(pe.set_day_mood(int(m.group(1)), note, day=day0))
                a = pm.mood_line(int(m.group(1)), note)[6:]   # echo "🙂 · note"
        elif key == "money":
            import periodic_model as pm
            head, _, tail = a.partition(" ")
            amt = pm.parse_amount(head)
            if amt is not None:
                routed.append(pe.append_income(amt, tail.strip(), day=day0))
        elif key == "rating":
            m = _re.match(r"^([1-5])(?!\d)", a)
            if m:
                routed.append(pe.set_day_rating(int(m.group(1)), day=day0))
                a = "★" * int(m.group(1))
        elif key == "highlight":
            routed.append(pe.set_highlight(a, day=day0))
        answers[n] = a
    filled = pe.journal_merge(slot, answers, period=jper) if answers else 0
    done_now = (total - len(open_pairs)) + filled
    bits = [f"{emoji} {label} saved {done_now}/{total}"]
    if cancelled:
        bits.append("(cancelled)")
    print(" ".join(bits))
    if cancelled:
        return
    # ── picker handoffs (dialogs can't host pickers)
    if slot == "morning" and not pe.day_goal_now():
        _run_trigger("Search", "pn day ")
    elif slot == "weekly":
        _goalseq_save(3)
        _run_trigger("Search", "pn goal ")


def _goal_seq_step(toast):
    """Three-things sequence bookkeeping: after each pick, re-arm the picker
    until 3 are in (Esc simply doesn't come back; the state file expires)."""
    seq = _goalseq_load()
    if not seq:
        print(toast)
        return "current"
    remaining = seq.get("remaining", 0) - 1
    _goalseq_save(remaining)
    if remaining > 0:
        print(f"🎯 {3 - remaining} of 3 · pick the next")
        _run_trigger("Search", "pn goal ")
    else:
        print("🎯 3 of 3 · next week is set")
    return "next"


def pn_goal(pid, tid):
    if not _pn_gate():
        return
    week = "next" if _goalseq_load() else "current"
    title = _task_title(tid, default="Task", pid=pid)
    toast = _pn().set_goal(pid, tid, title, week=week)
    if week == "next":
        _goal_seq_step(toast)
    else:
        print(toast)


def pn_goal_text(rest):
    if not _pn_gate():
        return
    spec = _pn_decode(rest) or {"text": rest}
    text = (spec.get("text") or "").strip()
    if not text:
        print("🎯 Nothing to set")
        return
    week = "next" if _goalseq_load() else "current"
    toast = _pn().set_goal(text, week=week)
    if week == "next":
        _goal_seq_step(toast)
    else:
        print(toast)


def pn_day_goal(pid, tid):
    if not _pn_gate():
        return
    title = _task_title(tid, default="Task", pid=pid)
    print(_pn().set_day_goal(pid, tid, title))


def pn_day_goal_text(rest):
    if not _pn_gate():
        return
    spec = _pn_decode(rest) or {"text": rest}
    text = (spec.get("text") or "").strip()
    if not text:
        print("☀️ Nothing to set")
        return
    print(_pn().set_day_goal(text))


def pn_mood(rest):
    """Face picked in the pn rows (1-5) → optional-note dialog → 💬 Mood."""
    if not _pn_gate():
        return
    import re as _re
    m = _re.match(r"^[1-5]$", (rest or "").strip())
    if not m:
        print("😊 Mood is 1-5")
        return
    note = _ask("Optional mood note · ⏎ to skip", title="Mood")
    if note is None:                      # Cancel = abort, log nothing
        print("😊 Cancelled")
        return
    print(_pn().set_day_mood(int(m.group(0)), note.strip()))


def pn_highlight(rest):
    """🗓️ Week highlight - text rides in, or a dialog asks."""
    if not _pn_gate():
        return
    spec = _pn_decode(rest) or {"text": rest}
    text = (spec.get("text") or "").strip()
    if not text:
        text = (_ask("Highlight of the week:", title="🗓️ Week highlight") or "").strip()
        if not text:
            print("✨ Nothing saved")
            return
    print(_pn().set_highlight(text))


def pn_sched(rest):
    """today|pid|tid[|HH:MM] - the ☀️/🌙 Add-to pickers' AND ⌘ Actions rows'
    commit (the Actions conditional only routes xact:/bare-verb shapes, so
    attr_date can't ride from there). Plain scheduling -
    deliberately NOT gated on periodic_list_id; only the trailing note-nudge
    is."""
    parts = (rest or "").split("|")
    if len(parts) < 3:
        print("💫 Bad schedule spec")
        return
    when, pid, tid = parts[0], parts[1], parts[2]
    hhmm = parts[3] if len(parts) > 3 else ""
    from datetime import date as _date
    day = _date.today() + timedelta(days=(0 if when == "today" else 1))
    if hhmm:
        import re as _re
        import time as _time
        m = _re.match(r"^(\d{1,2}):(\d{2})$", hhmm)
        if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
            print("⏰ Time is HH:MM")
            return
        loc = datetime(day.year, day.month, day.day,
                       int(m.group(1)), int(m.group(2)))
        iso = datetime.utcfromtimestamp(
            _time.mktime(loc.timetuple())).strftime("%Y-%m-%dT%H:%M:%S+0000")
    else:
        iso = day.strftime("%Y-%m-%dT00:00:00+0000")
    from api import TickTickAPI
    from dispatch import _cached_task, _patch_task_cache
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=_cached_task(tid),
                    startDate=iso, dueDate=iso)
    _patch_task_cache(tid, startDate=iso, dueDate=iso)
    title = _task_title(tid, default="Task", pid=pid)
    label = "today" if when == "today" else "tomorrow"
    print(f"{'☀️' if when == 'today' else '🌙'} {title[:40]} → {label}"
          + (f" {hhmm}" if hhmm else ""))
    import areas
    if areas.periodic_configured():
        _pn_bg("xact:pn_refresh:daily")   # ✅ Today / ⏩ Tomorrow catch up


def pn_refresh(rest=""):
    if not _pn_gate():
        return
    spec = (rest or "").strip() or "daily"
    if spec not in _PN_SPECS:
        spec = "daily"
    print(_pn().refresh_spec(spec))


def pn_mint():
    if not _pn_gate():
        return
    minted = _pn().mint_ahead()
    if minted is None:
        print("💫 Already minted for tomorrow")
        return
    msg = ("💫 Minted " + ", ".join(minted)) if minted else "💫 Refreshed (nothing to mint)"
    print(msg)
    if not os.environ.get("alfred_version") and minted:
        _run_trigger("XAct", f"xact:notify:{msg}")   # launchd → banner


def _pomo_default():
    """TickTick's own default pomo length in minutes (defaults key verified
    live 2026-07-07: focus__pomodoro_pomodoroDuration = 2700 s = 45 m)."""
    r = subprocess.run(["defaults", "read", "com.TickTick.task.mac",
                        "focus__pomodoro_pomodoroDuration"],
                       capture_output=True, text=True, check=False)
    try:
        return max(5, min(180, int(r.stdout.strip()) // 60))
    except ValueError:
        return 25


def _pomo_app_state():
    """(state, remaining_secs) of TickTick's OWN pomodoro. The state key
    flushes LIVE (verified 2026-07-07): 'idle' · 'pomodoroing.1.true' ·
    'pomodoroPaused.1'. Remaining derives from the timeline's startDate +
    pomodoroDuration - it keeps ticking while paused (freeze would need the
    pause segments; good enough for a status row)."""
    r = subprocess.run(["defaults", "read", "com.TickTick.task.mac",
                        "focus__pomodoro_state"],
                       capture_output=True, text=True, check=False)
    state = r.stdout.strip()
    if not state or state == "idle":
        return "idle", 0
    import plistlib
    out = subprocess.run(["defaults", "export", "com.TickTick.task.mac", "-"],
                         capture_output=True, check=False).stdout
    start = dur = None
    try:
        for seg in plistlib.loads(out).get("focus__pomodoro_timeline", []) or []:
            if isinstance(seg, dict):
                if start is None and "startDate" in seg:
                    start = seg["startDate"]
                if "pomodoroDuration" in seg:
                    dur = seg["pomodoroDuration"]
    except Exception:
        pass
    remaining = 0
    if start is not None and dur:
        st = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        remaining = max(0, int(dur) - int(
            (datetime.now(timezone.utc) - st).total_seconds()))
    return state, remaining


# The Pomodoro view's Continue/Pause + End buttons ARE in the AX tree
# (untitled - the web content around them is opaque, the buttons aren't).
# Identify by geometry: the centered stacked pair (same x, 40-90 pt apart,
# lower half); bottom = End. After End, the <5-min case raises the
# "Abandon This Focus?" dialog - its buttons appear as NEW AX buttons;
# rightmost = Abandon. Verified live 2026-07-07.
_POMO_END_OSA = '''
on run
  tell application "System Events" to tell process "TickTick"
    set mw to window 1 whose subrole is "AXStandardWindow"
  end tell
  -- NB: `before`/`after` are RESERVED WORDS in AppleScript (insertion
  -- locators) - using them as variable names kills the whole compile.
  set preBtns to my collect(mw, 0, {})
  set endBtn to my stackBottom(preBtns)
  if endBtn is missing value then return "NOEND"
  -- AXPress, NOT click: SE clicks are synthetic mouse events at coordinates
  -- and silently vanish when another window overlaps; AXPress reaches the
  -- element through the AX API regardless of z-order.
  tell application "System Events" to perform action "AXPress" of (item 3 of endBtn)
  delay 1.2
  tell application "System Events" to tell process "TickTick"
    set mw2 to window 1 whose subrole is "AXStandardWindow"
  end tell
  set postBtns to my collect(mw2, 0, {})
  set newRight to missing value
  set newRightX to -999999
  repeat with b in postBtns
    set bx to item 1 of b
    set by_ to item 2 of b
    set seen to false
    repeat with a in preBtns
      if (item 1 of a) = bx and (item 2 of a) = by_ then set seen to true
    end repeat
    if not seen and bx > newRightX then
      set newRightX to bx
      set newRight to b
    end if
  end repeat
  if newRight is not missing value then
    tell application "System Events" to perform action "AXPress" of (item 3 of newRight)
    return "ENDED+CONFIRM"
  end if
  return "ENDED"
end run

on collect(el, depth, acc)
  tell application "System Events"
    if depth > 7 then return acc
    set r to ""
    try
      set r to role of el
    end try
    if r is "AXButton" then
      set p to {0, 0}
      try
        set p to position of el
      end try
      set end of acc to {item 1 of p, item 2 of p, el}
      return acc
    end if
    if r is "AXStaticText" or r is "AXImage" or r is "AXTextField" or r is "AXTextArea" then return acc
    try
      set kids to every UI element of el
      repeat with c in kids
        set acc to my collect(c, depth + 1, acc)
      end repeat
    end try
    return acc
  end tell
end collect

on stackBottom(btns)
  -- Continue/End: same x, ~64 pt apart, lower half, well right of the left
  -- rail (whose icon stack at x≈56 with 48 pt gaps must NOT match).
  set best to missing value
  repeat with i from 1 to count of btns
    repeat with j from 1 to count of btns
      if i is not j then
        set a to item i of btns
        set b to item j of btns
        if (item 1 of a) = (item 1 of b) and (item 2 of b) > (item 2 of a) then
          set gap to (item 2 of b) - (item 2 of a)
          if gap > 55 and gap < 75 and (item 2 of a) > 380 and (item 1 of a) > 150 then set best to b
        end if
      end if
    end repeat
  end repeat
  return best
end stackBottom
'''


def pomo_abandon():
    """End TickTick's running pomodoro machine-side: the ⌥F8
    Start/Abandon hotkey pauses + drops the app on the End/Continue screen
    (when already paused, navigate there via the List menu instead), then
    AX-click End and auto-confirm the app's <5-min Abandon dialog if raised.
    The app may keep partial work segments - its own End semantics."""
    import time
    import tt_shortcut
    state, remaining = _pomo_app_state()
    if state == "idle":
        print("🍅 No pomodoro running")
        return
    # Bring the app forward FIRST (LaunchServices, no AE): the decision
    # screen is a web view that may not render off-screen/other-Space -
    # the "stop just pauses it" failure mode. No sdef command exists
    # to end a pomo (checked 2026-07-07: `start pomo` only), so the ⌥F8 →
    # AXPress-End dance stays - hardened.
    subprocess.run(["open", "-a", "TickTick"], check=False)
    time.sleep(0.5)
    if state.startswith("pomodoroPaused"):
        _view_menu_click("Pomodoro")
    else:
        err = tt_shortcut.fire("TTStartOrAbandonPomoHotkeyIdentifier")
        if err:
            print(err)
            return
    # Let the web view finish rendering the decision screen: AX nodes are
    # recreated during the transition and a press on a stale node no-ops.
    time.sleep(2.5)
    r = subprocess.run(["osascript", "-"], input=_POMO_END_OSA,
                       capture_output=True, text=True, check=False)
    out = (r.stdout or "").strip()
    time.sleep(0.8)
    state2, _ = _pomo_app_state()
    for _retry in range(2):
        if state2 == "idle" or out == "NOEND":
            break
        # Retries - the first collection can race the render, and the
        # decision screen may need the Pomodoro view brought up explicitly.
        _view_menu_click("Pomodoro")
        time.sleep(1.8)
        r = subprocess.run(["osascript", "-"], input=_POMO_END_OSA,
                           capture_output=True, text=True, check=False)
        out = (r.stdout or "").strip()
        time.sleep(0.8)
        state2, _ = _pomo_app_state()
    m = remaining // 60
    if state2 == "idle":
        _drop_pomo()   # the attribution sidecar dies with the pomo
        print(f"🍅 Pomodoro ended · {m}m was left")
    elif out == "NOEND":
        print("🍅 Couldn't reach the End button · finish in the Pomodoro view")
    elif not out:
        print(f"🍅 End script failed · finish in the Pomodoro view "
              f"({(r.stderr or '').strip()[:60]})")
    else:
        print("🍅 End clicked · check the Pomodoro view")


def pomo_toggle():
    """Pause⟷resume TickTick's running pomodoro. The app's global
    'Start/Abandon Pomo' hotkey is really pause-plus-decision-screen while
    one runs (verified live 2026-07-07: pomodoroing ⟷ pomodoroPaused);
    pomo_abandon drives the full End from there."""
    import tt_shortcut
    state, remaining = _pomo_app_state()
    if state == "idle":
        print("🍅 No pomodoro running")
        return
    err = tt_shortcut.fire("TTStartOrAbandonPomoHotkeyIdentifier")
    if err:
        print(err)
        return
    m = remaining // 60
    if state.startswith("pomodoroPaused"):
        print(f"▶️ Pomodoro resumed · {m}m left")
    else:
        print(f"⏸ Pomodoro paused · {m}m left")


def pomo(minutes):
    if not minutes or minutes == "default":
        m = _pomo_default()
    else:
        m = max(5, min(180, int(minutes)))
    # Hard timeout: TickTick's Apple-event interface can wedge (seen live
    # 2026-07-07 - UI + AX fine, every AE times out until app relaunch);
    # without it this call hangs the Alfred run-script indefinitely.
    try:
        r = subprocess.run(
            ["osascript", "-e",
             f'tell application "TickTick" to start pomo {m} from "tickal"'],
            capture_output=True, text=True, check=False, timeout=15)
    except subprocess.TimeoutExpired:
        print("Pomo didn't start: TickTick isn't answering Apple events "
              "· relaunch TickTick and retry")
        return False
    if r.returncode != 0:
        print(f"Pomo didn't start: {r.stderr.strip()[:80] or 'already running?'}")
        return False
    print(f"▶️ {m}m pomodoro started in TickTick")
    _bar_wake()
    return True


VIEW_MENUS = {"habits": "Habit", "matrix": "Matrix", "pomo": "Pomodoro",
              "summary": "Summary"}   # Summary has no working deep link


def _view_menu_click(menu):
    """Activate + click the app's List ▸ Open "<menu>" item. True on success."""
    subprocess.run(["open", "-a", "TickTick"], check=False)   # LS, no AE (see _select_task)
    r = subprocess.run(
        ["osascript",
         "-e", ('tell application "System Events" to tell process "TickTick" '
                f'to click menu item "Open \\"{menu}\\"" of menu "List" of menu bar 1')],
        capture_output=True, text=True, check=False)
    return r.returncode == 0, r.stderr.strip()[:80]


def view_open(which):
    """Open an app-only TickTick view - ported from the retired ViewPicker
    case-map runscript (System-Events click on the app's List menu)."""
    menu = VIEW_MENUS.get(which)
    if not menu:
        print(f"Unknown view {which!r}")
        return
    ok, err = _view_menu_click(menu)
    if not ok:
        print(f"Couldn't open {menu}: {err}")
    else:
        print(f"↗️ TickTick {menu} opened")


def _sticky_count():
    """Open sticky notes present as AXSystemDialog windows of TickTick."""
    r = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to tell process "TickTick" to '
         'count (windows whose subrole is "AXSystemDialog")'],
        capture_output=True, text=True, check=False)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


# Find the task's row by title in the (native, AX-readable) list outlines and
# return its FRAME - the caller picks an unoccluded point and clicks it with a
# real CGEvent. The deep link alone only reliably navigates to the LIST;
# whether it selects the TASK is a race, and the sticky shortcut fires on
# whatever is selected → wrong-task stickies.
# Investigated alternatives, all dead: task rows never expose AXSelected, the
# detail pane + sticky windows are AX-opaque web views (AXManualAccessibility
# not settable), sticky.displayed.tasks defaults flush lazily. System Events'
# `click rw` is a COORDINATE click at the row's center - a floating sticky
# panel over that point swallows it (focus → sticky, selection unchanged),
# which is why the caller does its own occlusion-aware click instead.
# Outline depth VARIES BY VIEW (project lists nest ≥4 deep, Inbox sits at 2 -
# same as the 72-row sidebar), so no depth filter: collect every outline, scan
# right-to-left by x (content panes sit right of the sidebar; the sidebar only
# matches if a list shares the exact title, and rightmost still wins).
# Row text = static texts AND text-field values: Inbox rows hold the title in
# an inline AXTextField, project rows in AXStaticTexts.
#
# TWO ENGINES (profiled 2026-07-08 on a 61-row view):
#   · _ROW_FIND_JXA - the AX C API in-process via the JXA ObjC bridge
#     (same bridge _cg_click already uses). Miss 0.4s / hit 0.2s.
#     The ObjC.bindFunction lines are LOAD-BEARING: without them the bridge
#     passes AXUIElementRef wrongly and every call returns -25201.
#   · _ROW_FIND_OSA - the original System-Events walk, kept ONLY as the
#     fallback when the JXA bridge itself errors. It costs ~6 Apple-Event
#     round-trips PER ROW ≈ 15-30s on a full miss (the "sticky takes 30s"
#     bug), so it runs hard-bounded by a subprocess timeout.
_ROW_FIND_JXA = '''
ObjC.import('Cocoa');
ObjC.import('ApplicationServices');
ObjC.bindFunction('AXUIElementCreateApplication', ['id', ['unsigned int']]);
ObjC.bindFunction('AXUIElementCopyAttributeValue', ['int', ['id', 'id', 'id*']]);
ObjC.bindFunction('CFCopyDescription', ['id', ['id']]);

function run(argv) {
  var needle = argv[0];
  var apps = $.NSWorkspace.sharedWorkspace.runningApplications;
  var pid = -1;
  for (var i = 0; i < apps.count; i++) {
    var a = apps.objectAtIndex(i);
    if (ObjC.unwrap(a.localizedName) === 'TickTick') { pid = a.processIdentifier; break; }
  }
  if (pid < 0) return 'NOAPP';
  var app = $.AXUIElementCreateApplication(pid);

  function ax(el, name) {
    var ref = Ref();
    return $.AXUIElementCopyAttributeValue(el, name, ref) === 0 ? ref[0] : null;
  }
  function s(cf) {
    if (!cf) return '';
    try { var v = ObjC.unwrap(cf); return (typeof v === 'string') ? v : ''; } catch (e) { return ''; }
  }
  function each(cfArr, fn) {
    if (!cfArr) return;
    try { var n = cfArr.count; for (var i = 0; i < n; i++) fn(cfArr.objectAtIndex(i)); } catch (e) {}
  }

  // window 1 whose subrole is AXStandardWindow - parity with the SE walk
  var SKIP = {AXRow:1, AXCell:1, AXStaticText:1, AXTextArea:1, AXWebArea:1, AXButton:1, AXImage:1, AXTextField:1};
  var outlines = [], seen = false;
  each(ax(app, 'AXWindows'), function (w) {
    if (seen || s(ax(w, 'AXSubrole')) !== 'AXStandardWindow') return;
    seen = true;
    (function collect(el, depth) {
      if (depth > 8) return;
      var r = s(ax(el, 'AXRole'));
      if (r === 'AXOutline') { outlines.push(el); return; }
      if (SKIP[r]) return;
      each(ax(el, 'AXChildren'), function (c) { collect(c, depth + 1); });
    })(w, 0);
  });

  // rightmost outline first (content panes sit right of the sidebar)
  function xpos(el) {
    var v = ax(el, 'AXPosition');
    if (!v) return -1000000;
    var m = s($.CFCopyDescription(v)).match(/x:(-?[\\d.]+)/);
    return m ? parseFloat(m[1]) : -1000000;
  }
  outlines.sort(function (a, b) { return xpos(b) - xpos(a); });

  function geom(el, name, rx) {
    var v = ax(el, name);
    if (!v) return null;
    var m = s($.CFCopyDescription(v)).match(rx);
    return m ? [Math.round(parseFloat(m[1])), Math.round(parseFloat(m[2]))] : null;
  }

  for (var oi = 0; oi < outlines.length; oi++) {
    var found = null;
    each(ax(outlines[oi], 'AXRows'), function (row) {
      if (found) return;
      var text = '';
      each(ax(row, 'AXChildren'), function (cell) {
        each(ax(cell, 'AXChildren'), function (t) {
          var r = s(ax(t, 'AXRole'));
          if (r === 'AXStaticText' || r === 'AXTextField') text += s(ax(t, 'AXValue'));
        });
      });
      if (text.indexOf(needle) >= 0) found = row;
    });
    if (found) {
      var p = geom(found, 'AXPosition', /x:(-?[\\d.]+)\\s+y:(-?[\\d.]+)/);
      var z = geom(found, 'AXSize', /w:(-?[\\d.]+)\\s+h:(-?[\\d.]+)/);
      if (p && z) return 'FOUND|' + p[0] + '|' + p[1] + '|' + z[0] + '|' + z[1];
      return '';
    }
  }
  return '';
}
'''


def _row_find(needle):
    """FOUND|x|y|w|h (or '') for the row containing `needle`. Fast JXA-AX
    engine first; the System-Events walk only if the bridge itself fails,
    and never unbounded."""
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-", needle],
                           input=_ROW_FIND_JXA, capture_output=True,
                           text=True, timeout=8, check=False)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out != "NOAPP":
            return out              # '' is a CLEAN miss - no fallback
    except subprocess.TimeoutExpired:
        pass
    try:
        r = subprocess.run(["osascript", "-", needle],
                           input=_ROW_FIND_OSA, capture_output=True,
                           text=True, timeout=25, check=False)
        return (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return ""


_ROW_FIND_OSA = '''
on run argv
  set needle to item 1 of argv
  tell application "System Events" to tell process "TickTick"
    set mw to window 1 whose subrole is "AXStandardWindow"
  end tell
  set outs to {}
  my collect(mw, 0, outs)
  repeat (count of outs) times
    set bestI to 0
    set bestX to -1000000
    repeat with i from 1 to count of outs
      set rec to item i of outs
      if rec is not missing value then
        if (item 1 of rec) > bestX then
          set bestX to item 1 of rec
          set bestI to i
        end if
      end if
    end repeat
    if bestI is 0 then exit repeat
    set el to item 2 of (item bestI of outs)
    set item bestI of outs to missing value
    set res to my scanFind(el, needle)
    if res is not "" then return res
  end repeat
  return ""
end run

on collect(el, depth, outs)
  tell application "System Events"
    if depth > 8 then return
    set r to ""
    try
      set r to role of el
    end try
    if r is "AXOutline" then
      set px to 0
      try
        set p to position of el
        set px to item 1 of p
      end try
      set end of outs to {px, el}
      return
    end if
    if r is "AXRow" or r is "AXCell" or r is "AXStaticText" or r is "AXTextArea" or r is "AXWebArea" or r is "AXButton" or r is "AXImage" or r is "AXTextField" then return
    try
      set kids to every UI element of el
      repeat with c in kids
        my collect(c, depth + 1, outs)
      end repeat
    end try
  end tell
end collect

on scanFind(el, needle)
  tell application "System Events"
    try
      set rws to every row of el
      repeat with rw in rws
        set rowText to ""
        try
          set cels to every UI element of rw
          repeat with cel in cels
            try
              set sts to every static text of cel
              repeat with k from 1 to count of sts
                set rowText to rowText & (value of item k of sts)
              end repeat
            end try
            try
              set tfs to every text field of cel
              repeat with k from 1 to count of tfs
                set rowText to rowText & (value of item k of tfs)
              end repeat
            end try
          end repeat
        end try
        if rowText contains needle then
          set p to position of rw
          set s to size of rw
          return "FOUND|" & (item 1 of p) & "|" & (item 2 of p) & "|" & (item 1 of s) & "|" & (item 2 of s)
        end if
      end repeat
    end try
    return ""
  end tell
end scanFind
'''


def _sticky_frames():
    """[(x, y, w, h)] of every open sticky panel (AXSystemDialog window)."""
    r = subprocess.run(["osascript", "-e", '''
tell application "System Events" to tell process "TickTick"
  set acc to ""
  repeat with w in (windows whose subrole is "AXSystemDialog")
    set p to position of w
    set s to size of w
    set acc to acc & (item 1 of p) & " " & (item 2 of p) & " " & (item 1 of s) & " " & (item 2 of s) & linefeed
  end repeat
  return acc
end tell'''], capture_output=True, text=True, check=False)
    frames = []
    for ln in (r.stdout or "").strip().splitlines():
        try:
            x, y, w, h = (int(v) for v in ln.split())
            frames.append((x, y, w, h))
        except ValueError:
            pass
    return frames


def _cg_click(x, y):
    """Real left click at global point (x, y) via CGEvent (JXA bridge) -
    reaches points that System Events element clicks can't target."""
    jxa = f'''
ObjC.import('CoreGraphics');
var pt = {{x: {x}, y: {y}}};
var d = $.CGEventCreateMouseEvent($(), $.kCGEventLeftMouseDown, pt, $.kCGMouseButtonLeft);
$.CGEventPost($.kCGHIDEventTap, d);
delay(0.04);
var u = $.CGEventCreateMouseEvent($(), $.kCGEventLeftMouseUp, pt, $.kCGMouseButtonLeft);
$.CGEventPost($.kCGHIDEventTap, u);
'''
    subprocess.run(["osascript", "-l", "JavaScript", "-e", jxa],
                   capture_output=True, check=False)


def _click_task_row(title):
    """Find the row whose text contains `title` and land a REAL click on a
    point of it that no floating sticky panel covers. True once clicked."""
    out = _row_find(title[:60].strip())
    if not out.startswith("FOUND|"):
        return False
    try:
        x, y, w, h = (int(v) for v in out.split("|")[1:5])
    except ValueError:
        return False
    cy = y + h // 2
    frames = _sticky_frames()
    # Candidate points sweep the row past the ~40px complete-checkbox zone,
    # middle first (empty row space for typical titles beats the title text).
    for frac in (0.5, 0.35, 0.65, 0.8, 0.25, 0.92):
        cx = x + max(48, int(w * frac))
        if cx > x + w - 8:
            continue
        if not any(fx <= cx <= fx + fw and fy <= cy <= fy + fh
                   for fx, fy, fw, fh in frames):
            _cg_click(cx, cy)
            return True
    return False   # the whole row is under stickies right now - let caller retry


def _select_task(pid, tid):
    """Find + really CLICK the task's row (the only guaranteed selection).
    FAST PATH: if the row is already on screen -
    common when acting on the current list - click it straight away, no
    deep-link navigation, no settle sleeps. Slow path: deep-link to the
    list, then retry. Returns (clicked, title)."""
    import time
    from display import _MD_LINK_RE
    raw = (cache_store.find_task(tid) or {}).get("title") or _title()
    # The AX row renders a markdown link as its TEXT - a raw
    # '[TickAL • WF](ticktick://…)' needle can never match (the
    # sticky-dead-on-linked-titles bug, root-caused 2026-07-11). An
    # empty strip result must NOT reach _row_find: indexOf('') matches
    # the first row - the wrong task would get the sticky.
    title = _MD_LINK_RE.sub(r"\1", raw).strip() or raw
    if not title.strip():
        return False, raw or "(untitled)"
    subprocess.run(["open", "-a", "TickTick"], check=False)   # LS, no AE
    if _click_task_row(title):
        return True, title
    subprocess.run(["open", f"ticktick:///webapp/#p/{pid}/tasks/{tid}"], check=False)
    time.sleep(0.7)
    for _ in range(3):
        if _click_task_row(title):
            return True, title
        time.sleep(0.4)
    return False, title


def sticky(pid, tid):
    """Open the task as a TickTick desktop sticky note: deep link → navigate
    to the list, then find + CLICK the task's row (guaranteed selection),
    then fire the app's own 'Open as Sticky Note' shortcut
    (hotkey_id_open_as_sticky). If the row can't be located, fail honestly
    WITHOUT firing - a missing sticky beats the wrong task's sticky.

    Final design (all verified 2026-07-11, content-checked the
    right task's sticky): the DEEP LINK both navigates and selects the task
    app-side - the synthetic row click stopped registering selection after
    the Jul-10 reboot, and a keystroke racing it makes the app mint a
    window it never SHOWS (CGWindowList: six phantom stickies,
    onscreen=False, invisible to AX). So: deep link → settle → count →
    raise → fire → VERIFY a new AXSystemDialog exists (AX only enumerates
    actually-shown ones); the click survives only as the retry assist.
    `before` is counted AFTER the link settles - the link opens the task
    DETAIL pane, itself an AXSystemDialog, which would false-positive the
    appeared-check. Toast is honest either way (the old one claimed
    'opened' off a fragile count and lied)."""
    import time
    import tt_shortcut
    from display import _MD_LINK_RE

    raw = (cache_store.find_task(tid) or {}).get("title") or _title()
    title = _MD_LINK_RE.sub(r"\1", raw).strip() or raw
    short = title[:40]

    def _fire_and_wait(settle, before):
        # An open sticky panel HOLDS key-window status - raise the main
        # window so the keystroke reaches it (root-caused 2026-07-07).
        subprocess.run(["osascript", "-e",
                        'tell application "System Events" to tell process "TickTick" '
                        'to perform action "AXRaise" of '
                        '(window 1 whose subrole is "AXStandardWindow")'],
                       capture_output=True, check=False)
        time.sleep(settle)
        err = tt_shortcut.fire("hotkey_id_open_as_sticky")
        if err:
            return err, False
        for _ in range(10):                     # up to 2.5 s
            time.sleep(0.25)
            if _sticky_count() > before >= 0:
                return None, True
        return None, False

    subprocess.run(["open", f"ticktick:///webapp/#p/{pid}/tasks/{tid}"],
                   check=False)
    time.sleep(1.2)
    before = _sticky_count()
    err, shown = _fire_and_wait(0.4, before)
    if err:
        print(err)
        return False
    if not shown:
        # selection assist for views the deep link can't settle (kanban,
        # collapsed subtask), then one slower attempt
        _click_task_row(title)
        time.sleep(0.6)
        err, shown = _fire_and_wait(0.8, before)
        if err:
            print(err)
            return False
    if shown:
        print(f"🗒️ Sticky opened: {short}")
        return True
    print(f"🗒️ No new sticky · “{short}” may already have one open")
    return False


def focus_sticky(pid, tid):
    """The combined focus action: sticky note on the desktop + workflow timer."""
    if sticky(pid, tid):
        focus_start(pid, tid)


def pomo_task(pid, tid, minutes):
    """Open + select the task in the app (real row click - _select_task),
    then start TickTick's pomodoro. VERIFIED 2026-07-07: `start pomo` does
    NOT bind the session to the selection (the ring stays on "Focus >"), so
    rows honestly say "Start pomo + open {task}" - the selected task is on
    screen and one click on Focus > attaches it. Row not found → honest
    failure, no pomo."""
    clicked, title = _select_task(pid, tid)
    if not clicked:
        print(f"🍅 Couldn't locate “{title[:40]}” in the list · pomo not "
              "started (open TickTick and retry)")
        return
    if pomo(minutes):
        _pomo_attribute(pid, tid, title)


def _pomo_attribute(pid, tid, title):
    """Sidecar write after a successful task-pomo start: the bar and
    fx_add resolve the pomo's task from here; validity tag = the timeline's
    startDate (a later, different pomo invalidates it)."""
    import time
    time.sleep(0.5)   # let the timeline segment land in defaults
    _write_pomo({"pid": pid, "tid": tid, "title": title,
                 "start": _now_iso(), "pomo_start": _pomo_timeline_start()})
    _ensure_block_if_history(pid, tid)


def pomo_sticky(pid, tid, minutes):
    """Sticky note on the desktop + TickTick pomodoro on the task."""
    if sticky(pid, tid):
        if pomo(minutes):
            _pomo_attribute(pid, tid, _task_title(tid))


# ── View/tag collectors - feed view_focus / tag_focus ────────────────────────
def _view_tasks(key):
    """Ordered open tasks of a smart view → (tasks, label) - used by the
    focus-block send."""
    from filtering import smart_filter
    all_tasks = cache_store.get("all_tasks") or []
    labels = {"today": "Today", "tomorrow": "Tomorrow",
              "next7": "Next 7 Days", "inbox": "Inbox"}
    if key in ("today", "tomorrow", "next7"):
        kind = {"today": "today", "tomorrow": "tomorrow", "next7": "next7days"}[key]
        tasks = smart_filter(all_tasks, kind)
        if key in ("today", "tomorrow"):   # time order, like the app's view
            tasks = sorted(tasks, key=lambda t: (t.get("startDate")
                                                 or t.get("dueDate") or "~"))
    elif key == "inbox":
        data = cache_store.get("project_data_inbox") or {}
        tasks = [t for t in data.get("tasks", [])
                 if t.get("status", 0) == 0 and not t.get("parentId")]
    else:
        return None, None
    return tasks, labels.get(key, key)


def _tag_tasks(pid, tag):
    """Open tasks carrying a tag - list-scoped when pid set, global when empty.
    Cache order = the order the tag screen renders."""
    all_tasks = cache_store.get("all_tasks") or []
    tl = tag.lower()
    return [t for t in all_tasks
            if t.get("status", 0) == 0
            and tl in [x.lower() for x in (t.get("tags") or [])]
            and (not pid or (t.get("projectId") or t.get("_projectId")) == pid)]


# ── Focus-block staging verbs ────────────────────────────────────────────────

def fx_add(pid, tid, open_sticky=False):
    """Insert the task as a checkbox into the CURRENT focus task's today
    block. ⌥ variant also opens the focus task's sticky (the list lives
    there)."""
    cur = _current_focus_task()
    if not cur:
        print("🎯 No task-linked session running · start or link one first")
        return
    fpid, ftid, ftitle = cur
    if tid == ftid:
        print("🎯 That IS the focus task")
        return
    title = _task_title(tid, pid=pid)
    (added, _skipped), _doc, _live = _fx_rmw(
        fpid, ftid,
        lambda doc, today: fb.insert_checkboxes(doc, today, [(pid, tid, title)]))
    if added:
        print(f"🎯 {title[:40]} → {ftitle[:30]}")
    else:
        print(f"🎯 already staged today on {ftitle[:30]}")
    if open_sticky:
        sticky(fpid, ftid)


def fx_add_to(tpid, ttid, spid, stid):
    """Insert a source task as a checkbox into an EXPLICIT target's today
    block (the Stage-for-Focus '→ link this task to another' direction)."""
    if ttid == stid:
        print("🎯 Can't stage a task into itself")
        return
    title = _task_title(stid, pid=spid)
    (added, _skipped), _doc, live = _fx_rmw(
        tpid, ttid,
        lambda doc, today: fb.insert_checkboxes(doc, today, [(spid, stid, title)]))
    tname = live.get("title") or "target"
    if added:
        print(f"🎯 {title[:40]} → {tname[:30]}")
    else:
        print(f"🎯 already staged today in {tname[:30]}")


def fx_add_multi(b64):
    """Batch insert, ONE content write. b64 JSON:
    {"tpid","ttid","items":[[pid,tid,title],…]} (built by the stage picker)."""
    import base64
    data = json.loads(base64.b64decode(b64))
    tpid, ttid = data["tpid"], data["ttid"]
    items = [(p, t, ti) for p, t, ti in data.get("items", []) if t != ttid]
    if not items:
        print("🎯 Nothing to stage")
        return
    (added, skipped), _doc, live = _fx_rmw(
        tpid, ttid,
        lambda doc, today: fb.insert_checkboxes(doc, today, items))
    tname = live.get("title") or "target"
    msg = f"🎯 {added} staged → {tname[:30]}"
    if skipped:
        msg += f" · {skipped} already there"
    print(msg)


def fx_tick(pid, tid, ctid=None):
    """Tick the first unchecked checkbox (or the one linking ctid) in the
    focus task's current block. TICKAL_JSON=1 → block_summary JSON on stdout
    (the focus bar's reconcile channel); otherwise a human toast."""
    as_json = os.environ.get("TICKAL_JSON") == "1"
    try:
        line, doc, _live = _fx_rmw(
            pid, tid,
            lambda doc, today: fb.tick(doc, today, target_tid=ctid or None))
        summary = fb.block_summary(doc, _today())
        if as_json:
            print(json.dumps({"ok": True, "ticked": bool(line), **summary}))
        elif line:
            print(f"✅ ticked: {fb._display_title(line)[:50]}")
        else:
            print("Nothing to tick today")
    except Exception as e:
        if as_json:
            print(json.dumps({"ok": False,
                              "error": f"{type(e).__name__}: {e}"}))
        else:
            raise


def fx_sweep(pid=None, tid=None):
    """Manual sweep - complete every checked+linked+still-open checkbox task
    across ALL of the task's blocks (the permanent record keeps its lines)."""
    if not (pid and tid):
        cur = _current_focus_task()
        if not cur:
            print("🧹 No focus task to sweep")
            return
        pid, tid = cur[0], cur[1]
    doc = fb.parse(_api().get_task(pid, tid).get("content") or "")
    done, failed = _sweep_from_doc(doc)
    if done or failed:
        print(f"🧹 {done} swept" + (f", {failed} failed" if failed else ""))
    else:
        print("🧹 nothing to sweep")


def fx_copy(pid=None, tid=None):
    """Today's UNTICKED checkboxes → clipboard as a paste-ready bullet list
    (ticked ones are history, not a to-paste list)."""
    if not (pid and tid):
        cur = _current_focus_task()
        if cur:
            pid, tid = cur[0], cur[1]
        else:
            ps = _pomo_sidecar()
            if not (ps and ps.get("tid")):
                print("📋 No task-linked session running")
                return
            pid, tid = ps.get("pid", ""), ps["tid"]
    doc = fb.parse(_api().get_task(pid, tid).get("content") or "")
    blk = fb._current_block(doc, _today())
    lines = [l for l in (blk.lines if blk else [])
             if l.kind == "checkbox" and not l.checked]
    if not lines:
        print("📋 Nothing unticked in today's block")
        return
    text = "\n".join("- " + fb._display_title(l) for l in lines)
    subprocess.run(["pbcopy"], input=text.encode())
    # _current_block falls back to the newest block (midnight-crossing
    # sessions) - disclose when what landed isn't actually today's
    stale = f" (block {blk.date})" if blk.date != _today() else ""
    print(f"📋 {len(lines)} checkbox{'es' if len(lines) != 1 else ''}"
          f" copied as bullets{stale}")


def convert(pid, tid):
    """⌘ Actions '🔃 Convert': flip the item kind TEXT↔NOTE via the
    v1 update (the full-object post carries kind - verified both
    ways). Cache mirror: all_tasks/project_data take the new kind;
    all_notes gains or drops the item (note screens render from it)."""
    api = _api()
    live = api.get_task(pid, tid)
    new_kind = "TEXT" if live.get("kind") == "NOTE" else "NOTE"
    api.update_task(tid, pid, current=live, kind=new_kind)
    from dispatch import _patch_task_cache
    _patch_task_cache(tid, kind=new_kind)
    try:
        notes = [n for n in (cache_store.get("all_notes") or [])
                 if n.get("id") != tid]
        if new_kind == "NOTE":
            entry = cache_store.find_task(tid) or dict(live, _projectId=pid)
            notes.insert(0, dict(entry, kind="NOTE"))
        cache_store.set("all_notes", notes)
    except Exception:
        cache_store.invalidate("all_notes")
    title = (live.get("title") or _title())[:40]
    print(f"🔃 {title} is now a {'note' if new_kind == 'NOTE' else 'task'}")


def wontdo(pid, tid):
    """⌘ Actions '🚫 Won't do': abandon the task - TickTick's third
    status. The write is v2-only: batch update with status -1 + a
    client-stamped completedTime (verified 2026-07-11: without the stamp the
    task never reaches the Won't Do list, and v1 drops the stamp silently -
    a v1 fallback would strand the task in NO view once the next sync
    replaced the wontdo cache with server truth). Order: write
    first, focus-guard after - a failed write must not have killed the
    running session. Cache mirror is the complete: pattern
    with the wontdo_tasks log (completed_tasks purged too - abandoning a
    ✅-view row must not dual-list)."""
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception:
        print("Error: task not found · sync and retry")
        return
    title = (live.get("title") or _title())[:40]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    import api_v2
    v2 = api_v2.TickTickV2()
    if not v2.token:
        print("🚫 Won't do needs the Attachment Login token (Settings)")
        return
    if not v2.abandon_task(dict(live, completedTime=stamp)):
        print(f"Error: TickTick refused to abandon “{title}” · retry")
        return
    # complete-guard AFTER the write sticks: abandoning the
    # focused task ends its session (abandoned tasks stay GET-able)
    st = _focus_state()
    if st and st.get("tid") == tid:
        try:
            focus_stop()
        except Exception:
            pass
    try:
        snap = dict(cache_store.find_task(tid) or live)
        snap["status"] = -1
        snap["completedTime"] = stamp
        log = [t for t in (cache_store.get("wontdo_tasks") or [])
               if t.get("id") != tid]
        log.insert(0, snap)
        cache_store.set("wontdo_tasks", log[:200])
        cached = cache_store.get("all_tasks")
        if cached is not None:
            cache_store.set("all_tasks",
                            [t for t in cached if t.get("id") != tid])
        done = cache_store.get("completed_tasks")
        if done is not None:
            cache_store.set("completed_tasks",
                            [t for t in done if t.get("id") != tid])
        from dispatch import _patch_project_data
        _patch_project_data(tid, pid_old=pid, remove=True)
    except Exception:
        cache_store.invalidate("all_tasks")
    print(f"🚫 Won't do: {title}")


def wontdo_undo(pid, tid):
    """⇧ on a Won't Do row: back to open (v1 status 0 - verified the
    clean revert). Mirror of dispatch's uncomplete: restore, on the
    wontdo_tasks log."""
    api = _api()
    api.update_task(tid, pid, status=0, completedTime=None)
    title = _title()
    try:
        log = cache_store.get("wontdo_tasks") or []
        snap = next((t for t in log if t.get("id") == tid), None)
        cache_store.set("wontdo_tasks",
                        [t for t in log if t.get("id") != tid])
        if snap:
            title = (snap.get("title") or title)[:40]
        cached = cache_store.get("all_tasks")
        if cached is not None and snap is not None:
            restored = dict(snap)
            restored["status"] = 0
            restored.pop("completedTime", None)
            cached = [t for t in cached if t.get("id") != tid]
            cached.append(restored)
            cache_store.set("all_tasks", cached)
            from dispatch import _patch_project_data
            _patch_project_data(tid, pid_old=pid)
        elif snap is None or cached is None:
            # no snap to restore from - invalidate so the reopened task
            # doesn't stay invisible until the hourly sync
            cache_store.invalidate("all_tasks")
    except Exception:
        cache_store.invalidate("all_tasks")
    print(f"↩️ Reopened: {title}")


def fx_link(pid, tid):
    """Attribute a running unattributed session to the task: timer file gets
    pid/tid/title in place (start + pauses kept); an app pomo gets the
    sidecar. The task's block carry-over rides along."""
    title = _task_title(tid)
    st = _focus_state()
    if st:
        if st.get("tid"):
            print(f"🔗 Session already linked to {st['title']}")
            return
        st.update({"pid": pid, "tid": tid, "title": title})
        _write_focus(st)
    else:
        state, _ = _pomo_app_state()
        if state == "idle":
            print("🔗 No running session to link")
            return
        _write_pomo({"pid": pid, "tid": tid, "title": title,
                     "start": _now_iso(), "pomo_start": _pomo_timeline_start()})
    _ensure_block_if_history(pid, tid)
    _bar_wake()
    print(f"🔗 {title[:40]} linked to the running session")


def _fx_send(items, label):
    """Insert [(pid,tid,title)] into the current focus task's today block -
    ONE content write. True when the insert happened."""
    cur = _current_focus_task()
    if not cur:
        print("🎯 No task-linked session running · start or link one first")
        return False
    fpid, ftid, ftitle = cur
    items = [(p, t, ti) for p, t, ti in items if t != ftid]
    if not items:
        print(f"Nothing in {label} to add")
        return False
    (added, skipped), _doc, _live = _fx_rmw(
        fpid, ftid,
        lambda doc, today: fb.insert_checkboxes(doc, today, items))
    msg = f"🎯 {added} from {label} → {ftitle[:30]}"
    if skipped:
        msg += f" · {skipped} already there"
    print(msg)
    return True


def buffer_focus():
    """The whole buffer → today's block, in buffer order (first buffered =
    first checkbox); clears the buffer once sent."""
    lines = buffer_ids()
    if not lines:
        print("🅿️ Buffer is empty")
        return
    items = []
    for ln in lines:
        pid, tid = ln.split(":", 1)
        t = cache_store.find_task(tid) or {}
        items.append((pid, tid, t.get("title", "Untitled")))
    if _fx_send(items, "buffer"):
        _write_buffer([])


def view_focus(key):
    """A whole smart view → today's block, in view order."""
    tasks, label = _view_tasks(key)
    if tasks is None:
        print(f"View {key!r} can't be staged")
        return
    _fx_send([(t.get("projectId") or t.get("_projectId", ""), t.get("id", ""),
               t.get("title", "Untitled")) for t in tasks], label)


def tag_focus(pid, tag):
    """A tag's open tasks → today's block."""
    _fx_send([(t.get("projectId") or t.get("_projectId", ""), t.get("id", ""),
               t.get("title", "Untitled")) for t in _tag_tasks(pid, tag)],
             f"#{tag}")


STAGE_FILE = run_path("tickal_stage.txt")


def _focus_prefill(query, pid, tid):
    """Fire ET Focus prefilled with a SHORT query; the task ids ride the
    handshake file instead of the bar (no id soup in the text field).
    Same temp-file pattern as /tmp/ticktick_reattribute.txt."""
    with open(STAGE_FILE, "w") as f:
        f.write(f"{pid}:{tid}")
    osa = ('on run argv\n'
           'tell application id "com.runningwithcrayons.Alfred" to run trigger '
           '"Focus" in workflow "com.vex.tickal" with argument (item 1 of argv)\n'
           'end run')
    subprocess.run(["osascript", "-e", osa, query], check=False)


def tag_create(b64spec):
    """➕ Create-tag rows (search g-scope): xact:tag_create:<b64> where
    the payload keeps emoji-bearing names intact: {"label": …, "parent": …?}.
    Rides the xact route because search-⏎ reaches only the modOpen shell case
    (xact:*|open:*) - a bare tag_create: arg would be open()'d as a URL."""
    import base64
    spec = json.loads(base64.b64decode(b64spec))
    # , : > never reach TickTick - they'd shred the attr_tags_multi csv,
    # change_tag_exec's colon-split, or the '#name>parent' grammar later.
    label = ((spec.get("label") or "").strip().lstrip("#")
             .replace(",", "").replace(":", "").replace(">", ""))
    parent = (spec.get("parent") or "").strip().lstrip("#") or None
    if not label:
        print("Error: empty tag name")
        return
    import cache as cache_store
    from display import tag_match_key
    known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
    if tag_match_key(label) in known:
        print(f"#{label} already exists")
        return
    import api_v2
    v2 = api_v2.TickTickV2()
    if not v2.token:
        print(f"Creating #{label} needs the Attachment Login token (Settings)")
        return
    if v2.create_tag(label, parent):
        cache_store.set("tags", (cache_store.get("tags") or []) + [label])
        # tags_tree too - else a nested create shows no child until the next
        # sync (pre-existing gap, now closed)
        tree = cache_store.get("tags_tree")
        if tree is not None:
            cache_store.set("tags_tree", tree + [{
                "name": label.lower(), "label": label,
                "parent": (parent or "").lower().lstrip("#") or None}])
        print(f"Tag #{label} created" + (f" under #{parent}" if parent else ""))
    else:
        print(f"TickTick refused #{label}" + (f" under #{parent}" if parent else "")
              + " · it may already exist there")


def tag_delete(name):
    """⌘ tag menu '🗑 Delete tag': removes the tag entity via v2 -
    the tasks that carried it keep living. Caches scrubbed; task-side tag
    strings clear on the next sync (the server already dropped them)."""
    import cache as cache_store
    name = (name or "").strip().lstrip("#")
    if not name:
        print("Error: no tag name")
        return
    import api_v2
    v2 = api_v2.TickTickV2()
    if not v2.token:
        print("Deleting a tag needs the Attachment Login token (Settings)")
        return
    if v2.delete_tag(name):
        low = name.lower()
        cache_store.set("tags", [t for t in (cache_store.get("tags") or [])
                                 if t.lower() != low])
        tree = []
        for t in (cache_store.get("tags_tree") or []):
            if (t.get("name") or "").lower() == low:
                continue
            if (t.get("parent") or "").lower() == low:
                t = {**t, "parent": None}   # children go top-level, no ghosts
            tree.append(t)
        cache_store.set("tags_tree", tree)
        print(f"Tag #{name} deleted")
    else:
        print(f"Could not delete #{name}")


def tag_create_under(parent):
    """⌘ tag menu '➕ Add nested tag': dialog-ask the name, then the
    normal create path with THIS tag as the parent. A dialog because an
    Actions row can't take typed input (v2login's _ask precedent)."""
    import base64
    parent = (parent or "").strip().lstrip("#")
    if not parent:
        print("Error: no parent tag")
        return
    osa = ('text returned of (display dialog "New tag under #{}" '
           'default answer "" with title "TickAL")').format(
               parent.replace("\\", "").replace('"', ""))
    r = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True)
    name = (r.stdout or "").strip() if r.returncode == 0 else ""
    # spaces would shred the '#name' token grammar downstream
    name = "".join(name.split())
    if not name:
        return   # cancelled - silence, not an error toast
    tag_create(base64.b64encode(
        json.dumps({"label": name, "parent": parent}).encode()).decode())


def stage_pick():
    """The Focus menu's 🎯 row: CLEAR any leftover ⌘-handshake, then
    open the stage flow - it lands on the source picker (S0) cleanly. A verb
    (not an autocomplete token) so no typed search can ever collide with it."""
    try:
        os.remove(STAGE_FILE)
    except OSError:
        pass
    osa = ('tell application id "com.runningwithcrayons.Alfred" to run trigger '
           '"Focus" in workflow "com.vex.tickal" with argument "stage "')
    subprocess.run(["osascript", "-e", osa], check=False)


def fx_move(tid, direction):
    """Bar ⤒↑↓⤓ reorder: move the checkbox among the
    unchecked lines of the focus task's today block - up/down one slot,
    top/bottom to the edge. Silent no-op at the edges / unknown direction."""
    cur = _current_focus_task()
    if not cur:
        ps = _pomo_sidecar()
        if not (ps and ps.get("tid")):
            print("🎯 No task-linked session running")
            return
        fpid, ftid = ps.get("pid", ""), ps["tid"]
    else:
        fpid, ftid, _ = cur
    moved, _doc, _live = _fx_rmw(
        fpid, ftid,
        lambda doc, today: fb.move_item(doc, today, tid, direction))
    print("reordered" if moved else "")


def section_focus(pid, sid):
    """A section's open tasks → today's block (bulk add)."""
    data = cache_store.get(f"project_data_{pid}") or {}
    tasks = [t for t in data.get("tasks", [])
             if t.get("status", 0) == 0 and not t.get("parentId")
             and t.get("columnId") == sid]
    name = next((c.get("name", "") for c in (data.get("columns") or [])
                 if c.get("id") == sid), "section")
    _fx_send([(pid, t["id"], t.get("title", "Untitled")) for t in tasks],
             f"§{name}")


def stage_open(pid, tid):
    """⌘ 'Stage for Focus' hop. Silent - the Focus window IS the feedback."""
    _focus_prefill("stage ", pid, tid)


def focus_open(pid, tid):
    """⌘ '🎯 Focus' hop: the task-bound start flow (⏱ timer / 🍅 pomo, each
    with a sticky variant) - replaces the three old start rows. Silent."""
    _focus_prefill("for ", pid, tid)


def focus_done():
    """The bar's ● button: end the session (sweep + note + record land while
    the task is still open), THEN complete the focus task itself."""
    st = _focus_state()
    if st and st.get("tid"):
        pid, tid, title = st["pid"], st["tid"], st["title"]
        focus_stop()
        try:
            _api().complete_task(pid, tid)
            _complete_cache_patch(pid, tid)
            print(f"✅ {title[:40]} completed")
        except Exception as e:
            print(f"✅ complete failed: {type(e).__name__}")
        return
    ps = _pomo_sidecar()
    if ps and ps.get("tid"):
        pid, tid, title = ps["pid"], ps["tid"], ps["title"]
        pomo_abandon()
        try:
            _api().complete_task(pid, tid)
            _complete_cache_patch(pid, tid)
            print(f"✅ {title[:40]} completed")
        except Exception as e:
            print(f"✅ complete failed: {type(e).__name__}")
        return
    print("✅ No task-linked session running")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not arg.startswith("xact:"):
        print(f"Error: not an xact arg: {arg!r}")
        return
    body = arg[5:]
    verb, _, rest = body.partition(":")
    try:
        if verb == "buffer_add":
            pid, tid = rest.split(":", 1); buffer_add(pid, tid)
        elif verb == "buffer_remove":
            pid, tid = rest.split(":", 1); buffer_remove(pid, tid)
        elif verb == "buffer_complete":
            buffer_complete()
        elif verb == "buffer_clear":
            _write_buffer([]); print("🅿️ Buffer cleared")
        elif verb == "focus_start":
            pid, tid = rest.split(":", 1); focus_start(pid, tid)
        elif verb == "focus_pause":
            focus_pause()
        elif verb == "focus_resume":
            focus_resume()
        elif verb == "focus_stop":
            focus_stop()
        elif verb == "focus_stop_as":
            pid, tid = rest.split(":", 1); focus_stop(as_pid=pid, as_tid=tid)
        elif verb == "focus_discard":
            focus_stop(discard=True)
        elif verb == "focus_log":
            pid, tid, m = rest.split(":", 2); focus_log(pid, tid, m)
        elif verb == "pomo":
            pomo(rest)
        elif verb == "pomo_task":
            pid, tid, m = rest.split(":", 2); pomo_task(pid, tid, m)
        elif verb == "pomo_sticky":
            pid, tid, m = rest.split(":", 2); pomo_sticky(pid, tid, m)
        elif verb == "pomo_toggle":
            pomo_toggle()
        elif verb == "pomo_abandon":
            pomo_abandon()
        elif verb == "view_open":
            view_open(rest)
        elif verb == "app_sync":
            _app_sync()   # silent - no stdout, no banner
        elif verb == "v2login":
            v2login()
        elif verb == "cachesync":
            cachesync_toggle()
        elif verb == "pyobjc_install":
            pyobjc_install()
        elif verb == "pn_agent":
            pn_agent_toggle()
        elif verb == "crmnew_newcust":
            crmnew_newcust(rest)
        elif verb == "crmnew_go":
            crmnew_go(rest)
        elif verb == "sessiondone":
            pid, tid = rest.split(":", 1)
            sessiondone(pid, tid)
        elif verb == "crmlog":
            crmlog(rest)
        elif verb == "crmperson":
            crmperson()
        elif verb == "crmimport":
            crmimport()
        elif verb == "crmpast":
            crmpast(rest)
        elif verb == "crmsched":
            pid, tid = rest.split(":", 1)
            crmsched(pid, tid)
        elif verb == "crmlink":
            pid, tid = rest.split(":", 1)
            crmlink(pid, tid)
        elif verb == "crmconvert":
            crmconvert(rest)
        elif verb == "crmcopy":
            crmcopy(rest)
        elif verb == "crmpay":
            crmpay(rest)
        elif verb == "crmedit":
            crmedit(rest)
        elif verb == "crmaftercare":
            crmaftercare(rest)
        elif verb == "crmbrowse":
            crmbrowse(rest)
        elif verb == "crmphoto":
            crmphoto(rest)
        elif verb == "crmcold":
            crmcold(rest)
        elif verb == "crmclose":
            crmclose(rest)
        elif verb == "crmrename":
            crmrename(rest)
        elif verb == "crmsummary":
            crmsummary(rest)
        elif verb == "crmcsv":
            crmcsv()
        elif verb == "notify":
            # pass-through: stdout → the End notification. Lets headless
            # scripts (sync.py) post banners with Alfred's
            # Notification-Center permission instead of launchd osascript's.
            print(rest or "TickAL")
        elif verb == "sticky":
            pid, tid = rest.split(":", 1); sticky(pid, tid)
        elif verb == "focus_sticky":
            pid, tid = rest.split(":", 1); focus_sticky(pid, tid)
        elif verb == "fx_add":
            pid, tid = rest.split(":", 1); fx_add(pid, tid)
        elif verb == "fx_add_sticky":
            pid, tid = rest.split(":", 1); fx_add(pid, tid, open_sticky=True)
        elif verb == "fx_add_to":
            tpid, ttid, spid, stid = rest.split(":", 3)
            fx_add_to(tpid, ttid, spid, stid)
        elif verb == "fx_add_multi":
            fx_add_multi(rest)
        elif verb == "fx_tick":
            parts = rest.split(":")
            fx_tick(parts[0], parts[1], parts[2] if len(parts) > 2 else None)
        elif verb == "fx_sweep":
            if rest:
                pid, tid = rest.split(":", 1); fx_sweep(pid, tid)
            else:
                fx_sweep()
        elif verb == "fx_copy":
            if rest:
                pid, tid = rest.split(":", 1); fx_copy(pid, tid)
            else:
                fx_copy()
        elif verb == "convert":
            pid, tid = rest.split(":", 1); convert(pid, tid)
        elif verb == "wontdo":
            pid, tid = rest.split(":", 1); wontdo(pid, tid)
        elif verb == "wontdo_undo":
            pid, tid = rest.split(":", 1); wontdo_undo(pid, tid)
        elif verb == "tag_create_under":
            tag_create_under(rest)
        elif verb == "fx_link":
            pid, tid = rest.split(":", 1); fx_link(pid, tid)
        elif verb == "buffer_focus":
            buffer_focus()
        elif verb == "view_focus":
            view_focus(rest)
        elif verb == "tag_focus":
            pid, tag = rest.split(":", 1); tag_focus(pid, tag)
        elif verb == "tag_create":
            tag_create(rest)
        elif verb == "tag_delete":
            tag_delete(rest)
        elif verb == "fx_move":
            tid, direction = rest.split(":", 1); fx_move(tid, direction)
        elif verb == "section_focus":
            pid, sid = rest.split(":", 1); section_focus(pid, sid)
        elif verb == "stage_open":
            pid, tid = rest.split(":", 1); stage_open(pid, tid)
        elif verb == "stage_pick":
            stage_pick()
        elif verb == "focus_open":
            pid, tid = rest.split(":", 1); focus_open(pid, tid)
        elif verb == "bar_show":
            bar_show()
        elif verb == "bar_hide":
            bar_hide()
        elif verb == "focus_done":
            focus_done()
        elif verb == "pn_open":
            pn_open(rest)
        elif verb == "pn_sticky":
            pn_sticky(rest)
        elif verb == "pn_entry":
            pn_entry(rest)
        elif verb == "pn_income":
            pn_income(rest)
        elif verb == "pn_journal":
            pn_journal(rest)
        elif verb == "pn_goal":
            pid, tid = rest.split(":", 1); pn_goal(pid, tid)
        elif verb == "pn_goal_text":
            pn_goal_text(rest)
        elif verb == "pn_day_goal":
            pid, tid = rest.split(":", 1); pn_day_goal(pid, tid)
        elif verb == "pn_day_goal_text":
            pn_day_goal_text(rest)
        elif verb == "pn_mood":
            pn_mood(rest)
        elif verb == "pn_highlight":
            pn_highlight(rest)
        elif verb == "pn_sched":
            pn_sched(rest)
        elif verb == "pn_refresh":
            pn_refresh(rest)
        elif verb == "pn_mint":
            pn_mint()
        else:
            print(f"Error: unknown xact verb {verb!r}")
    except Exception as e:
        msg = f"{verb} failed: {type(e).__name__}: {e}"
        print(msg)
        # stdout is DISCARDED on the picker route (browse ⏎ → modOpen) - a
        # crash there was pure silence (the 2026-07-19 "nothing on enter"
        # bug). Banner it too; rare enough that double-notice is fine.
        try:
            _crm_say(msg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
