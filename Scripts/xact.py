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
    xact:focus_backlog:<s>:<e>:<pid>:<tid>  retro record between epochs
                                    <s>..<e> (empty ids = 🎲 unattributed) -
                                    the picker's `log` screen mints these

⏳ Countdowns + 🔄 Habits (hubs 2026-07-24; v2 batch channels, all probed):
    xact:countdown_new[:<b64>]      dialogs (or Add-window C mode payload)
                                    → countdown/batch mint
    xact:countdown_edit:<f>:<id>    name|date|remark dialog, live RMW
    xact:countdown_appear:<id>:<v>  typeOfSmartList (0/-3/-7/-9999/9999)
    xact:countdown_flip:<id>        countdown ⟷ countup (up drops RRULE)
    xact:countdown_archive:<id>     status 1 - off the hub
    xact:countdown_delete:<id>      confirm dialog → batch delete
    xact:habit_tick:<id>            today: Boolean → done · Real → +step;
                                    diary habits ask the note on completion
    xact:habit_tick_past:<id>       dialog day (y · yy · D.M) → retro tick
    xact:habit_untick:<id>          today back to blank (UPDATE status 0 -
                                    checkin DELETE 500s, trap)
    xact:habit_skip:<id>            explicit ⛔ skipped state
    xact:habit_note:<id>            diary note for today (habitRecords)
    xact:habit_new[:<b64name>]      dialogs: section → rhythm → type → diary
    xact:habit_archive:<id>         status 1
    xact:habit_delete:<id>          confirm → delete (checkins cascade)
    xact:task_copy:<pid>:<tid>      📋 task name → clipboard
    xact:task_copy_full:<pid>:<tid> name + '>' blockquoted description
    xact:buffer_copy[:full]         every buffered task as a block,
                                    one per line (no blank separators)
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

Editing pipeline (Photos → Eagle CRM → TV/FM - src/eagle.py):
    xact:cdest:<logTid>[:drain]     🎬 TV|FM|Studio|➖ picker → header line
                                    (:drain reopens the Unclassified list);
                                    TV|FM ensures Eagle skeleton +
                                    mints/moves 📸Raw task, ➖ completes it
    xact:eaglefolder:<logTid>       🦅 ensure per-tattoo skeleton, open
                                    in Eagle (switches to CRM lib first)
    xact:sessphotos:<logTid>[:finished]  📸 Photos selection → originals →
                                    04 Sessions (05 Finished on the
                                    finished road / archived logbook),
                                    rename+tags, ♥ → session-task attach,
                                    '✅ In Eagle' album after verify
    xact:photoattach:<pid>:<tid>    📎 ♥/single Photos pick → attachment
                                    on any task (no Eagle)
    xact:eaglesweep                 🦅 skeletons for every active logbook
                                    missing one
    xact:triage:<logTid>:<stage>[:attach]  🦅 file the Eagle selection
                                    into the stage subfolder (move +
                                    rename + tags; stage = consult|prep|
                                    design|s[<n>]|finished|healed);
                                    :attach → first pick onto the task
    xact:editthis:<logTid>          🎬 whole CRM tree (disk-read, ONE
                                    switch) → dest 02 Edit/{base};
                                    task → 📸Edit, link retargeted
    xact:promotesel                 🎬 Eagle selection (CRM open) →
                                    02 Edit/{base}; tattoo inferred
    xact:filedited                  📥 intake folders → flat 03 Post,
                                    '• Edit • n', 📸Edit→📸Post, ⭐
                                    offer, finished? → tree → Raw/
    xact:portfolio                  ⭐ Eagle selection → Portfolio/{base}
                                    membership (multi-shelf, no move)
    xact:posted:<tid>               📤 leave 03 Post (Portfolio stays,
                                    rest → trash), task completes
    xact:cretire:<tid>              ➖ complete 📸Raw task + logbook 🎬→➖
    xact:eaglego:<lib>:<fid>      ↗️ switch library, open folder

Focus staging (SUBTASKS - revamp 2026-07-21; NOTE targets keep checkboxes):
    xact:fx_add:<pid>:<tid>         stage the task = MOVE it under the
                                    CURRENT focus task as a literal subtask
                                    (cross-list v1 move, then v1 parent-set;
                                    origin recorded in tickal_focus_origins)
    xact:fx_add_sticky:<pid>:<tid>  fx_add + open the FOCUS task's sticky
    xact:fx_add_to:<tpid>:<ttid>:<spid>:<stid>  stage source under an explicit
                                    target task; NOTE target keeps the
                                    checkbox line (focus_blocks grammar)
    xact:fx_add_multi:<b64>         batch stage; b64 JSON {tpid,ttid,items:
                                    [[pid,tid,title]…]}
    xact:fx_tick:<pid>:<tid>[:<ctid>]  COMPLETE the first open subtask (or
                                    ctid) - ticks are real completions now.
                                    env TICKAL_JSON=1 → children_summary
                                    JSON (the focus bar's channel)
    xact:fx_unstage:<pid>:<tid>     remove from focus: v2 detach (v1 can't),
                                    then home per the origins ledger -
                                    needs the v2 token (wontdo precedent)
    xact:fx_oneliner                dialog → "- text" bullet appended to the
                                    focus task's content (the note)
    xact:fx_sweep                   RETIRED stub (ticks complete for real)
    xact:fx_copy[:<pid>:<tid>]      open subtasks → clipboard as a
                                    paste-ready "- Title" bullet list
    xact:convert:<pid>:<tid>        flip the item kind TEXT↔NOTE (⌘ Actions
                                    "🔃 Convert" - v1 full-object update)
    xact:wontdo:<pid>:<tid>         abandon the task (status -1, "Won't Do")
                                    - v2 batch write, v1 fallback
    xact:wontdo_undo:<pid>:<tid>    Won't Do → open again
    xact:tag_create_under:<parent>  ⌘ tag menu "➕ Add nested tag": dialog
                                    asks the name, creates under parent
    xact:fx_link:<pid>:<tid>        attribute a running unattributed session
                                    (timer file or pomo sidecar) to the task
    xact:buffer_focus               buffer → subtasks (buffer order), clears
    xact:view_focus:<key>           smart view → subtasks (view order)
    xact:view_buffer:<key>          scope's tasks → the buffer (dedupe)
    xact:dateclear:<key>            scope-wide date bankruptcy: confirm →
                                    dates cleared, tasks survive (repeating
                                    + CRM-calendar exempt); key incl 'buffer'
    xact:dateroll:<key>             scope's tasks → today, spans shifted
                                    whole days (hours/durations survive),
                                    same exemptions
    xact:inboxempty                 Inbox ⌘/inline row: confirm → every open
                                    inbox item to TickTick's Trash
    xact:tag_focus:<pid>:<tag>      tag's open tasks → subtasks
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
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions, run_path, notify as _notify_banner
bootstrap()

import config as cfg
import cache as cache_store
import focus_blocks as fb          # NOTE targets + legacy content only
import focus_subtasks as fsub      # the subtask staging model (pure)

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
    if key in lines:
        # honest toast - the silent dedupe read as "buffer broken" when
        # the same task was added twice (Vex 2026-07-24)
        print(f"🅿️ {_title()} already in buffer ({len(lines)} total)")
    else:
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
    plogged = []
    for ln in buffer_ids():
        pid, tid = ln.split(":", 1)
        try:
            api.complete_task(pid, tid)
            done += 1
            completed_tids.add(tid)
            _pl = person_autolog(tid)   # before the cache drop below
            if _pl and _pl not in plogged:
                plogged.append(_pl)
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
            from dispatch import _patch_project_data
            _patch_project_data(tid, pid_old=pid, remove=True)
        except Exception:
            skipped += 1
    _write_buffer([])
    print(f"🅿️ {done} completed" + (f", {skipped} skipped" if skipped else "")
          + "".join(plogged))
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
    fresh = {"pid": pid, "tid": tid, "title": title, "start": _now_iso()}
    if tid:
        # done0 = children already completed BEFORE this session, so the
        # record note and toast count only what THIS session finished
        fresh["done0"] = _done_children_snapshot(pid, tid)
    _write_focus(fresh)
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


def focus_backlog(rest):
    """🕰️ Retro focus record - '<start_epoch>:<end_epoch>:<pid>:<tid>'
    (empty ids = 🎲 unattributed). The picker's `log` screen builds the
    epochs from src/focus_backlog's local-time grammar; bounds re-guarded
    here anyway (1m-12h, already over). POST open/v1/focus type 1 - the
    record lands in TickTick's focus list."""
    import focus_backlog as fbk
    try:
        s, e, pid, tid = rest.split(":", 3)
        start = datetime.fromtimestamp(int(s), timezone.utc)
        end = datetime.fromtimestamp(int(e), timezone.utc)
    except ValueError:
        print("🕰️ Bad backlog args · nothing logged")
        return
    secs = (end - start).total_seconds()
    if not 60 <= secs <= fbk.MAX_HOURS * 3600:
        print(f"🕰️ Range must be 1m-{fbk.MAX_HOURS}h · nothing logged")
        return
    if end > datetime.now(timezone.utc) + timedelta(minutes=1):
        print("🕰️ Ends in the future · nothing logged")
        return
    fmt = "%Y-%m-%dT%H:%M:%S+0000"
    try:
        _api().create_focus(start.strftime(fmt), end.strftime(fmt),
                            task_id=tid or None)
    except Exception as ex:
        print(f"🕰️ Log failed ({type(ex).__name__}) · try again")
        return
    what = _task_title(tid, pid=pid) if tid else "🎲 random focus"
    print(f"🕰️ {fbk.fmt_dur(secs)} logged · {what}")


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
    """The complete-task cache mirror (clone of dispatch's complete: branch).

    BOTH pools. An entry in a NOTE-kind list lives in all_tasks AND
    all_notes, and cache.find_task searches all_tasks then all_notes - so
    dropping it from one pool only means the next lookup resurrects the
    completed copy. Concretely: a second ⌥⇧ Posted on the same tattoo would
    re-run the whole Eagle 03 Post sweep instead of refusing. Latent until
    the Content PL lists became NOTE-kind (2026-07-30)."""
    try:
        for key in ("all_tasks", "all_notes"):
            cached = cache_store.get(key)
            if cached is not None:
                cache_store.set(key, [t for t in cached
                                      if t.get("id") != tid])
        from dispatch import _patch_project_data
        _patch_project_data(tid, pid_old=pid, remove=True)
    except Exception:
        cache_store.invalidate("all_tasks")


def _children_state(fpid, ftid):
    """(open_children, child_ids) of a focus task - ONE project-data GET
    (open children live there with titles + sortOrder); get_task fallback
    for childIds when the focus task itself left the data (completed
    mid-session stays GET-able). childIds keeps completed children -
    live-verified 2026-07-21 - so done = childIds minus the open set."""
    api = _api()
    data = api.get_project_data(fpid)
    tasks = data.get("tasks") or []
    open_children = [t for t in tasks if t.get("parentId") == ftid]
    focus = next((t for t in tasks if t.get("id") == ftid), None)
    if focus is None:
        try:
            focus = api.get_task(fpid, ftid)
        except Exception:
            focus = {}
    return open_children, focus.get("childIds") or []


def _done_children_snapshot(pid, tid):
    """Completed-child ids right now - the session-start baseline
    (focus file key done0). Best-effort: [] when the API is down."""
    try:
        open_children, child_ids = _children_state(pid, tid)
        open_ids = {t.get("id") for t in open_children}
        return [c for c in child_ids if c not in open_ids]
    except Exception:
        return []


ORIGINS_FILE = run_path("tickal_focus_origins.json")


def _origins_update(add=None, drop=None):
    """The origins ledger (tid → {pid, parent}): where a staged task lived
    before fx staged it, so fx_unstage can send it home. Returns the
    dropped entry (or None). Best-effort file - a lost ledger only means
    remove-in-place instead of remove-home."""
    try:
        with open(ORIGINS_FILE) as f:
            d = json.load(f) or {}
    except (OSError, ValueError):
        d = {}
    for tid, entry in (add or {}).items():
        d[tid] = entry
    popped = d.pop(drop, None) if drop else None
    try:
        with open(ORIGINS_FILE, "w") as f:
            json.dump(d, f)
    except OSError:
        pass
    return popped


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
    """End-of-session bundle for a timer state: children snapshot becomes
    the record note (ticks completed for real during the session - nothing
    left to sweep), then the record logs. done0 (session-start baseline)
    keeps historical completions out of the note and the toast count.
    Returns the toast fragment. Raises only if the record itself failed."""
    secs = focus_elapsed(st)
    mins = max(1, int(secs // 60))
    tid = st.get("tid") or None
    pid = st.get("pid") or None
    note = None
    session_done = []
    if tid and pid:
        try:
            open_children, child_ids = _children_state(pid, tid)
            open_ids = {t.get("id") for t in open_children}
            before = set(st.get("done0") or [])
            session_done = [c for c in child_ids
                            if c not in open_ids and c not in before]
            # titles for what THIS session finished - completed children
            # stay GET-able; small pooled fetch, capped
            titles = {}
            if session_done:
                from concurrent.futures import ThreadPoolExecutor

                def _t(cid):
                    try:
                        return cid, _api().get_task(pid, cid).get("title", "")
                    except Exception:
                        return cid, ""
                with ThreadPoolExecutor(max_workers=4) as pool:
                    titles = dict(pool.map(_t, session_done[:20]))
            entries = [(titles.get(c, ""), True) for c in session_done
                       if titles.get(c)]
            entries += [(t.get("title", ""), False) for t in
                        sorted(open_children,
                               key=lambda x: x.get("sortOrder") or 0)]
            note = fsub.record_note(_today(), entries) or None
        except Exception:
            note = None
    note_skipped = _log_focus_record(st["start"], secs, tid, note)
    frag = f"{mins}m logged" + (f" on {st.get('title', 'Task')}" if tid else " (no task)")
    if session_done:
        frag += f" · ✅ {len(session_done)} done"
    if note_skipped:
        frag += " · note skipped"
    return frag


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


_DIALOG_MOVER = '''use framework "AppKit"
use scripting additions
set fr to (item 1 of (current application's NSScreen's screens()))'s frame()
set sw to item 1 of item 2 of fr
set sh to item 2 of item 2 of fr
tell application "System Events"
    repeat 75 times
        if (count of windows of process "System Events") > 0 then
            set win to window 1 of process "System Events"
            set {w, h} to size of win
            set position of win to {(sw - w) / 2 as integer, ¬
                                    (sh - h) / 3 as integer}
            exit repeat
        end if
        delay 0.04
    end repeat
end tell'''


def _osa_dialog(body):
    """THE dialog runner: every AppleScript prompt goes through here.

    SYSTEM EVENTS owns the dialog, activated so it opens holding the
    keyboard - arrows and Return work immediately, no mouse click first
    (Vex 2026-07-28) - and macOS hands focus back on dismiss.

    Host choice is a SPEED ruling (Vex 2026-07-30: "it takes 2s for the
    prompt to appear"). Timed, 3 runs each, osascript start to return:
    bare .043s · System Events activate .128s · `tell me to activate`
    2.089s. Activating OUR OWN osascript is what cost the two seconds -
    it is a background-only process, so activation sits in a fixed wait
    that never resolves. System Events is Apple's own always-running
    scripting agent: native, never busy, and not the roll of the dice
    that hosting in the frontmost app was.

    _DIALOG_MOVER fires ALONGSIDE the dialog and parks it on the
    MENU-BAR screen (Vex 2026-07-30: "it always appears on my secondary
    monitor"). System Events centres its panels on ITS notion of the
    main screen, which on this rig is the portrait 1080x1920 to the
    right (measured: position 4170,-419). NSScreen's screens() item 1
    is the menu-bar screen BY DEFINITION and its AX origin is 0,0, so
    the target is just centre-x, one-third-down. The mover reads the
    panel's own size, so a fat `choose from list` centres too. It is a
    separate process because `display dialog` blocks; it polls 75 x
    0.04s then gives up, and a failure (no Accessibility) is silent -
    the dialog still opens, just wherever System Events put it.

    It used to be hosted by the ALREADY-FRONTMOST app instead - `tell
    application (path to frontmost application)` - and that is the
    mechanism being removed (Vex 2026-07-30: ➕ New customer opened a
    box with the buttons stacked at the TOP LEFT, the text field a 40px
    stub, nothing clickable). That render was NOT reproduced here -
    Eagle, Photos, TickTick and Alfred all drew a correct 420x166 panel
    on demand - so the trigger is some state of the host we did not
    catch. It does not matter: what mattered was that the panel's
    layout, its liveness and its response to the keyboard were all
    hostage to whatever app happened to be in front, and the old
    fallback could never save it, because it keyed on a NON-ZERO exit
    and a mangled-but-answered dialog exits 0. Taking the host off the
    street removes the whole class.

    The bare retry stays for the case where the hosted call errors -
    but NEVER on a user cancel (-128), or pressing Esc would re-open
    the dialog in a loop."""
    prog = 'tell application "System Events"\nactivate\n' + body + '\nend tell'
    try:
        mover = subprocess.Popen(["osascript", "-e", _DIALOG_MOVER],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    except Exception:
        mover = None
    try:
        r = subprocess.run(["osascript", "-e", prog],
                           capture_output=True, text=True)
    finally:
        if mover is not None:
            try:
                mover.terminate()
                mover.wait(timeout=2)
            except Exception:
                pass
    if r.returncode == 0 or "-128" in (r.stderr or ""):
        return r
    return subprocess.run(["osascript", "-e", body],
                          capture_output=True, text=True)


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
    r = _osa_dialog(osa)
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
    r = _osa_dialog(osa)
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
    r = _osa_dialog(osa)
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
        content_dest(lb["id"], mandatory=True)   # born classified (Vex rule)
    _crmnew_photos_catch(lb)
    if kind == "consult":
        _crm_session_prefill(lb.get("title") or "", "Consult")
        _crm_say("🗂️ Logbook ready · schedule the consultation")
    else:
        n = cr.next_snum(lb.get("content") or "", lb["id"])
        _crm_session_prefill(lb.get("title") or "", f"S{n}")
        _crm_say(f"🗂️ Logbook ready · schedule S{n}")


def _crmnew_photos_catch(lb):
    """➕ New tattoo / consultation: reference shots are exactly what
    Vex holds at creation time (his ask 2026-07-26) - a Photos
    selection offers itself into 01 Consultation before the schedule
    handoff. Skip or failure never blocks the chain; the ♥ hero lands
    on the logbook note (no session task exists yet)."""
    try:
        import photos_bridge as pb
        n_sel = pb.selection_count() if pb.photos_running() else 0
    except Exception:
        n_sel = 0
    if not n_sel:
        return
    if _dialog(f"📸 {n_sel} selected in Photos - import as consult "
               "references?", ["Skip", "Import"], "Import") == "Import":
        session_photos(lb["id"], "consult")


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


def sessiondone(pid, tid, when=None):
    """The heart of the records flow: complete today's task (the calendar
    keeps the record - never reschedule), log the entry, recompute Paid,
    attach a clipboard photo, then archive or chain the next session.
    when = ISO date for backdated entries (the adopt chain asks); None = today."""
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
                              text=f"{marker} rescheduled.", when=when)
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
                log_pid, log_tid, kind_word, charged=kept, text=text, when=when)
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
    # 📸 Photos-selection catch (Vex ruling 2026-07-26: the wrong order
    # must be impossible). Import BEFORE completing so the ♥ heroes
    # land while the task is still open; a failed import stops the
    # flow with the task untouched. Consultations catch too (Sarah
    # smoke: consult day IS reference-shot day) - they file to
    # 01 Consultation, heroes → the logbook note.
    try:
        import photos_bridge as pb
        n_sel = pb.selection_count() if pb.photos_running() else 0
    except Exception:
        n_sel = 0
    if n_sel:
        pick = _dialog(f"📸 {n_sel} selected in Photos - import to "
                       f"{marker} first?",
                       ["Cancel", "Skip", "Import"], "Import")
        if pick == "":
            _crm_say("Cancelled · task untouched")
            return
        if (pick == "Import"
                and not session_photos(log_tid, "" if is_s else "consult")):
            _crm_say("📸 Import failed · task untouched - fix and "
                     "re-run Session done")
            return
    d_dur = cr.last_duration(lb_cached.get("content") or "")
    d_chg = cr.quote_remainder(lb_cached.get("content") or "")
    d_setup = cr.last_setup(lb_cached.get("content") or "")
    # Consultations skip duration/charged/setup (Vex 2026-07-26) - one
    # question, prep-flavored; needle sessions keep the full four.
    prompts = ((
        (f"How long was the {word}? (OK skips · Esc cancels)", d_dur),
        ("Charged? (gift = free friend · OK skips · Esc cancels)", d_chg),
        ("What did you do? (OK skips · Esc cancels)", ""),
        ("Setup? needles · inks · machine (OK skips)", d_setup),
    ) if is_s else (
        ("What was discussed · anything to remember for the prep? "
         "(OK skips · Esc cancels)", ""),
    ))
    answers = []
    for prompt, dflt in prompts:
        v = _ask(prompt, default=dflt)
        if v is None:
            _crm_say("Cancelled · task NOT completed, nothing logged")
            return
        answers.append(v)
    if is_s:
        dur, charged, did, setup = answers
        if (setup or "").strip():
            did = (did.strip() + ("\n" if did.strip() else "")
                   + f"Setup: {setup.strip()}")
    else:
        dur = charged = setup = ""
        did = answers[0]
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
            log_pid, log_tid, marker, dur, charged, did, when=when)
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
                _eagle_archive_folder(log_tid)
                return
            except Exception as e:
                _crm_say(f"Archive FAILED: {type(e).__name__}{photo}")
                return
        _crm_say(f"✅ consultation done · {money} / {n} total{photo}")
        return

    if final:
        try:
            cr.finish_logbook(log_pid, log_tid)
            _eagle_archive_folder(log_tid)
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


def crmperson(kind=""):
    """➕ New lead / customer - standalone (backlog entry, CRM setup, walk-in
    who hasn't booked). Leads live in RECORDS, never on the calendar.
    kind 'lead'|'customer' skips the which-one dialog: 🎛 Manage offers
    the two as separate rows (Vex unified home 2026-07-28), so asking
    again would be a question he already answered."""
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
    if kind.lower() in ("lead", "customer"):
        kind = kind.capitalize()
    else:
        kind = _dialog(f"{name} - lead or customer?",
                       ["Cancel", "Lead", "Customer"], "Customer")
    if kind == "":
        _crm_say("Cancelled · nothing created")
        return
    tag = areas.LEAD_TAG if kind == "Lead" else areas.CUSTOMER_TAG
    cr.create_customer(name, *contact, tag=tag)
    _crm_say(f"{'🎣 Lead' if kind == 'Lead' else '👤 Customer'} {name} created")


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
    content_dest(lb["id"], mandatory=True)   # born classified (Vex rule)
    cr.append_session(areas.RECORDS_ID, lb["id"], f"S{k}",
                      charged=total, text="Backlog import.", when=when)
    if state == "Finished":
        cr.finish_logbook(areas.RECORDS_ID, lb["id"])
        _eagle_archive_folder(lb["id"])   # TickTick archived → Eagle too
    _crm_say(f"📕 {lb.get('title')} imported · {k} sessions"
             + (" · archived" if state == "Finished" else ""))


def _ask_date(prompt):
    """Lenient date dialog. Day-first with ANY separator (8/7, 08-07, 3.7.,
    08/07/2026, 8-7-26), year-first ISO (2026-7-3), bare year (2025 → Jan 1);
    a missing year means THIS year, 2-digit years get +2000. Empty OK = today
    (returns None); garbage gets re-prompted twice then cancels.
    Returns ISO date, None (today), or "CANCEL"."""
    import re as _re
    import datetime as _dt
    for _ in range(3):
        raw = _ask(prompt)
        if raw is None:
            return "CANCEL"
        w = raw.strip()
        if not w:
            return None
        if _re.fullmatch(r"\d{4}", w):
            return f"{w}-01-01"
        parts = [p for p in _re.split(r"[./\-\s]+", w) if p]
        if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
            if len(parts[0]) == 4:      # year-first: YYYY M [D]
                y, m = parts[0], parts[1]
                d = parts[2] if len(parts) > 2 else "1"
            else:                       # day-first: D M [Y]
                d, m = parts[0], parts[1]
                y = parts[2] if len(parts) > 2 else str(_dt.date.today().year)
            try:
                yi = int(y)
                yi += 2000 if yi < 100 else 0
                return _dt.date(yi, int(m), int(d)).isoformat()
            except ValueError:
                pass                    # month 13, day 32… → re-prompt
        prompt = f"'{w}' is not a date · try 8/7 · 08.07.2026 · 2026-07-08 (OK = today)"
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
    n = cr.next_snum(lb.get("content") or "", log_tid, include_tasks=False)
    marker = _dialog("Log as?", ["Cancel", "Consultation", f"S{n}"], f"S{n}")
    if marker == "":
        _crm_say("Cancelled")
        return
    marker = "consultation" if marker == "Consultation" else f"S{n}"
    answers = []
    for prompt in ("How long? (OK skips · Esc cancels)",
                   "Charged? (gift = free friend · OK skips · Esc cancels)",
                   "What did you do? (OK skips · Esc cancels)"):
        v = _ask(prompt)
        if v is None:
            _crm_say("Cancelled · nothing logged")
            return
        answers.append(v)
    dur, charged, did = answers
    content, money, n_total, live_title = cr.append_session(
        areas.RECORDS_ID, log_tid, marker, dur, charged, did, when=when)
    photo = ""
    try:   # clipboard photo → logbook attachment, same as Session done
        import clipboard as clip_util
        img = clip_util.png_bytes()
    except Exception:
        img = None
    if img:
        try:
            import api_v2
            api_v2.TickTickV2().upload_attachment(areas.RECORDS_ID, log_tid,
                                                  img, "session.png")
            photo = " · 📷 attached"
        except Exception:
            photo = " · 📷 upload failed"
    _crm_say(f"📕 {marker} logged · {money} / {n_total} total{photo}")
    # A linked OPEN task wearing this exact marker is now history (the Bruno
    # strand: adopted as S1, logged here as past S1, task left open forever).
    # Offer the tick before the schedule question so next_snum stays honest.
    want_mk = marker if marker.startswith("S") else "Consult"
    for t in cache_store.get("all_tasks") or []:
        ti = t.get("title") or ""
        if (t.get("status", 0) == 0 and cr.is_session_task(ti)
                and (cr.parse_first_link(ti) or ("", "", ""))[2] == log_tid
                and cr.title_marker(ti) == want_mk):
            if _dialog(f"Open task {want_mk} found - complete it too?",
                       ["Leave open", "Complete"], "Complete") == "Complete":
                try:
                    tp = t.get("_projectId") or t.get("projectId")
                    _api().complete_task(tp, t["id"])
                    _complete_cache_patch(tp, t["id"])
                    _crm_say(f"✅ {want_mk} task completed")
                except Exception as e:
                    _crm_say(f"Complete failed: {type(e).__name__}: {e}")
            break
    # Same close as Session done: offer the next booking (scheduling
    # semantics - open tasks count). Esc/Later = logged, nothing else.
    lb_title = live_title or lb.get("title") or ""
    nxt = cr.next_snum(content, log_tid)
    label = f"Schedule S{nxt}"
    if _dialog(f"{lb_title} - schedule S{nxt} now?",
               ["Later", label], label) == label:
        _crm_session_prefill(lb_title, f"S{nxt}")


_IMG_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff",
             ".gif", ".webp")
# the 📸 Finder source takes RAW + video too - Eagle holds them,
# hero attach skips videos honestly
_MEDIA_EXTS = _IMG_EXTS + (".dng", ".raw", ".mov", ".mp4", ".m4v")


def _finder_selection():
    """POSIX paths of the current Finder selection (files only)."""
    scpt = ('set out to ""\n'
            'tell application "Finder" to set sel to selection\n'
            'repeat with f in sel\n'
            'set out to out & POSIX path of (f as alias) & linefeed\n'
            'end repeat\n'
            'return out')
    r = subprocess.run(["osascript", "-e", scpt],
                       capture_output=True, text=True, timeout=15)
    return [p for p in (r.stdout or "").splitlines()
            if p.strip() and os.path.isfile(p)]


def crmsched(pid, tid):
    """📅 Schedule a dormant task: jump straight into the schedule picker
    (attributeScheduling ET; ensure_task_context re-reads the temp file for
    pid/tid). Link to logbook stays one ⌘ away - Actions menu on the row."""
    if not pid or not tid:
        return
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as f:
            f.write(f"{pid}:{tid}")
    except OSError:
        return
    _run_trigger("attributeScheduling")


def crmprep(pid, tid):
    """🔥 Prepare for an existing booking: open the Add window prefilled with
    the proven Prepare query (same shape as the booking auto-flow and the ⌘
    Add-Prepare row). Trailing '*' auto-opens the schedule picker (Vex ruling
    2026-07-19: every CRM handoff is a scheduling)."""
    import areas
    t = cache_store.find_task(tid)
    title = (t or {}).get("title") or ""
    if not title:
        _crm_say("Task not in cache · run tsy")
        return
    tgt, wl = areas.prepare_wikilink_target(title)
    ref = f"[[{tgt}]]" if wl else tgt
    _run_trigger("Add",
                 f"~l {areas.crm_list_name()} #{areas.PREPARE_TAG} "
                 f"Prepare for {ref} *")


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


def crm_trash(tid):
    """🗑 Delete a records entry AND its trail (Vex ask 2026-07-28:
    'what is the purpose of it then' - the eraser must erase). Confirm
    lists the full inventory FIRST, then: linked calendar tasks (S<n>,
    Consult AND Prepare follow-ups) → TickTick Trash · Eagle items →
    Eagle Trash + folder husk → '🗑 Deleted' bin (_eagle_trash_folder:
    the API cannot delete folders) · the customer bullet line removed.
    A customer/lead delete CASCADES through every logbook first. All
    TickTick pieces restorable from TickTick's Trash, Eagle items from
    Eagle's."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    t = _record_by_id(tid)
    if not t:
        _crm_say("Not found · run tsy")
        return
    title = t.get("title") or "Untitled"
    is_person = title.startswith(("👤", "🎣"))
    lbs = cr.customer_logbooks(tid) if is_person else [t]
    cal = {lb["id"]: cr.calendar_tasks_of(lb["id"]) for lb in lbs}
    n_cal = sum(len(v) for v in cal.values())
    n_fid = sum(1 for lb in lbs
                if cr.eagle_folder_of(lb.get("content") or "")[0])
    also = []
    if is_person and lbs:
        also.append(f"{len(lbs)} logbook{'s' if len(lbs) > 1 else ''}")
    if n_cal:
        also.append(f"{n_cal} calendar task{'s' if n_cal > 1 else ''}")
    if n_fid:
        also.append("Eagle items → Eagle Trash")
    tail = (" Takes along: " + " · ".join(also) + ".") if also else ""
    if _dialog(f"🗑 Delete '{title}' completely?{tail} TickTick Trash "
               "can restore the notes and tasks.",
               ["Cancel", "Delete"], "Cancel") != "Delete":
        _crm_say("Cancelled · nothing deleted")
        return
    api = cr._api()
    killed_cal, done_notes, eagle_bits = 0, 0, []

    def _gone():
        """Mid-cascade abort must not hide what ALREADY went (review
        find 2026-07-28)."""
        return (f" Already deleted: {done_notes} note(s) · "
                f"{killed_cal} task(s).") if (done_notes or killed_cal) \
            else ""

    for lb in lbs:
        lb_pid = (lb.get("_projectId") or lb.get("projectId")
                  or areas.RECORDS_ID)
        try:
            api.delete_task(lb_pid, lb["id"])
        except Exception as e:
            _crm_say(f"Delete failed on '{lb.get('title')}': "
                     f"{type(e).__name__}: {e}.{_gone()}")
            return
        cr.purge_cache(lb["id"])
        done_notes += 1
        for ct in cal.get(lb["id"]) or []:
            ct_pid = (ct.get("_projectId") or ct.get("projectId")
                      or areas.CRM_ID)
            try:
                api.delete_task(ct_pid, ct["id"])
                cr.purge_cache(ct["id"], ct_pid)
                killed_cal += 1
            except Exception:
                pass                      # toast shows killed/planned
        if not is_person:
            cr.drop_customer_bullet(lb)   # cascade kills the whole note
        bit = _eagle_trash_folder(lb)
        if bit:
            eagle_bits.append(bit)
    if is_person:
        pid = t.get("_projectId") or t.get("projectId") or areas.RECORDS_ID
        try:
            api.delete_task(pid, tid)
        except Exception as e:
            _crm_say(f"Delete failed: {type(e).__name__}: {e}.{_gone()}")
            return
        cr.purge_cache(tid)
    bits = [f"🗑 Deleted · {title}"]
    if n_cal:
        bits.append(f"{killed_cal}/{n_cal} tasks" if killed_cal < n_cal
                    else f"{killed_cal} task{'s' if killed_cal > 1 else ''}")
    bits += eagle_bits
    _crm_say(" · ".join(bits))


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
    if title.startswith(("👤", "🎣")):
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
    # The date ask doubles as the confirm - Esc backs out, OK = today.
    # Real finish date matters: monthly "finished" stats key on it.
    when = _ask_date(f"Archive {title} - finished when? "
                     "(OK = today · Esc cancels)")
    if when == "CANCEL":
        _crm_say("Cancelled")
        return
    try:
        cr.finish_logbook(areas.RECORDS_ID, log_tid, when=when)
        _crm_say(f"📁 {title} archived · finished {when or 'today'}")
        _eagle_archive_folder(log_tid)
    except Exception as e:
        _crm_say(f"📁 Archive failed: {type(e).__name__}: {e}")


# ── Editing pipeline: Photos → Eagle CRM → TV/FM (2026-07-25) ─────────────────
# State owner = TickTick (logbook 🎬/🦅 header lines + 📸 tags on the
# Content-PL task); Eagle holds the files. src/eagle.py raises
# toast-ready EagleError - every verb here fails CLOSED.

def _fresher_of(a, b):
    """The fresher of two logbook contents: more ### session entries
    wins; tie → more header fields (🎬/🦅); tie → b. Guards the
    back-to-back-write clobber (review find 2026-07-25: a lagging
    TickTick re-read seconds after the 🎬 write would base the 🦅
    write on pre-🎬 content and silently drop the field)."""
    import crm_records as cr
    ea = len(cr.ENTRY_RE.findall(a or ""))
    eb = len(cr.ENTRY_RE.findall(b or ""))
    if ea != eb:
        return a if ea > eb else b
    ha = sum(1 for p in ("🎬", "🦅")
             if re.search(rf"^{p} ", a or "", re.M))
    hb = sum(1 for p in ("🎬", "🦅")
             if re.search(rf"^{p} ", b or "", re.M))
    return a if ha > hb else b


def _eagle_ensure_logbook_folder(lb):
    """CRM-library folder id for this logbook. First need CREATES the
    whole per-tattoo skeleton (01 Consultation … 06 Healed - consult
    refs get dragged in on day one) and writes the header 🦅 line back
    to the logbook. Returns the folder id.

    Parent follows the note's STATE, not the calling road (Vex smoke
    2026-07-28: creating a folder for an archived tattoo filed it under
    Customers/, so it was born in the wrong place and only a later
    sweep would move it). Archived → Archive/, active → Customers/."""
    import areas
    import crm_records as cr
    import eagle
    fid, _lib = cr.eagle_folder_of(lb.get("content") or "")
    if fid:
        return fid
    eagle.ensure_library("crm")
    tree = eagle.folder_tree()
    parent_name = "Archive" if cr.logbook_archived(lb) else "Customers"
    cust = eagle.find_folder(parent_name, tree=tree)
    base = cr.logbook_base(lb)
    # ADOPT an existing folder of this name from ANYWHERE in the CRM
    # library, not just from the parent we would create under (Vex smoke
    # 2026-07-28: the folder already sat in Archive/, the parent-scoped
    # lookup missed it, and a twin was minted under Customers/ - Eagle
    # has no folder delete, so a twin is permanent manual cleanup).
    tat = eagle.find_folder(base, tree=tree)
    cust_id = cust["id"] if cust else eagle.create_folder(parent_name)
    if tat:
        fid = tat["id"]
        have = {c.get("name") for c in (tat.get("children") or [])}
    else:
        fid = eagle.create_folder(base, parent=cust_id)
        have = set()
    for name in eagle.SKELETON:
        if name not in have:
            eagle.create_folder(name, parent=fid)
    api = cr._api()
    live = api.get_task(areas.RECORDS_ID, lb["id"])
    base_content = _fresher_of(lb.get("content") or "",
                               live.get("content") or "")
    new = cr.set_eagle_folder(base_content, fid)
    api.update_task(lb["id"], areas.RECORDS_ID, current=live, content=new)
    _patch_content_cache(lb["id"], new)
    return fid


def _content_task_for(log_tid):
    """The open Content-PL task whose BODY links this logbook (mint
    writes that link exactly so this lookup works), or None. The
    DISPOSABLE studio errand carries the same link but is NOT the
    content task - one task per tattoo, whatever its list."""
    import areas
    for t in cache_store.get("all_tasks") or []:
        if (t.get("status", 0) == 0
                and (t.get("_projectId") or t.get("projectId"))
                in areas.CONTENT_PIDS
                and f"/tasks/{log_tid})" in (t.get("content") or "")):
            return t
    return None


def _mint_raw_task(lb, dest, fid, tag="📸raw"):
    """📸 task in the dest Content PL list - ONE task carries the
    tattoo's whole content life (📸Raw → 📸Edit → 📸Post → done).
    Title = base + eagle folder link (folder, never an image)."""
    import areas
    import crm_records as cr
    api = cr._api()
    base = cr.logbook_base(lb)
    title = _eagle_title(base, fid)
    body = f"🎨 {cr.task_link(areas.RECORDS_ID, lb['id'], lb.get('title') or '')}"
    pid = areas.CONTENT_DESTS[dest][0]
    t = api.create_task(title=title, project_id=pid, content=body,
                        tags=[tag])
    _person_inject_cache(t, pid)
    return t


def _eagle_title(base, fid):
    """Content-task title: markdown link - TickTick linkifies ONLY
    [text](eagle://…), never the bare scheme (Vex smoke 2026-07-26)."""
    return f"[{base}](eagle://folder/{fid})" if fid else base


def _task_base(title):
    """'{C} - {T}' from a content-task title - markdown of ANY scheme
    (new eagle:// AND the legacy localhost:41595 links Vex's old
    backlog tasks carry) or a bare eagle link stripped."""
    t = (title or "").strip()
    m = re.match(r"^\[(.*?)\]\(\S+?\)$", t)
    if m:
        return m.group(1).strip()
    return re.sub(r"\s*eagle://\S+", "", t).strip()


def _content_retag(t, drop, add, **fields):
    """Swap one 📸 state tag on a content task (others kept); extra
    fields (title retarget) ride the same write and cache patch."""
    import crm_records as cr
    api = cr._api()
    pid = t.get("_projectId") or t.get("projectId")
    live = api.get_task(pid, t["id"])
    tags = [x for x in (live.get("tags") or [])
            if str(x).lower() != drop] + ([add] if add else [])
    api.update_task(t["id"], pid, current=live, tags=tags, **fields)
    try:
        import dispatch as _disp
        _disp._patch_task_cache(t["id"], tags=tags, **fields)
    except Exception:
        cache_store.invalidate("all_tasks")


def content_dest(log_tid, mandatory=False, back=""):
    """🎬 picker on a logbook: TV / FM / Studio / ➖ (third location
    Vex 2026-07-28). A dest writes the header line, ensures the Eagle
    folder (best-effort - field sticks even with Eagle asleep) and
    mints/moves the 📸Raw task into ITS list; ➖ completes an open
    📸Raw task (ONLY that tag - never in-edit work). mandatory=True =
    the at-birth call (Vex: NO logbook may exist unclassified) - Esc
    does not skip, it writes ➖ explicitly.

    back='drain' = came from the 🎬 Unclassified list: after a
    classification the list REOPENS, one entry shorter, so 32 of them
    can be machine-gunned without re-navigating (Vex 2026-07-28).
    Esc is the way OUT of that loop - a cancel never reopens, which is
    also why the at-birth call must never pass back."""
    def _reenter():
        if back == "drain":
            crmbrowse("ctx:lbpick:cdest:unset")
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    cur = cr.content_dest_of(lb.get("content") or "")
    OPTS = ["📺 TV - neotrad", "🖋️ FM - fineline",
            "🏷 Studio - studio account", "➖ None - CRM only"]
    dflt = {"tv": OPTS[0], "fm": OPTS[1], "studio": OPTS[2],
            "-": OPTS[3]}.get(cur)
    pick = _choose("🎬 Content potential?", OPTS, default=dflt)
    if pick is None:
        if not mandatory:
            _crm_say("Cancelled")
            return
        pick = OPTS[3]   # Esc at birth = explicit ➖, never unclassified
    dest = ("tv" if pick.startswith("📺")
            else "fm" if pick.startswith("🖋")
            else "studio" if pick.startswith("🏷") else "-")
    api = cr._api()
    live = api.get_task(areas.RECORDS_ID, log_tid)
    fresh = cr._fresher_content(log_tid, live.get("content") or "")
    new = cr.set_content_dest(fresh, dest)
    api.update_task(log_tid, areas.RECORDS_ID, current=live, content=new)
    _patch_content_cache(log_tid, new)
    lb = dict(lb)
    lb["content"] = new
    if dest == "-":
        t = _content_task_for(log_tid)
        if t and "📸raw" in {str(x).lower() for x in (t.get("tags") or [])}:
            pid = t.get("_projectId") or t.get("projectId")
            api.complete_task(pid, t["id"])
            _complete_cache_patch(pid, t["id"])
            _crm_say("🎬 ➖ set · 📸Raw task completed")
        else:
            _crm_say("🎬 ➖ set · CRM only")
        _reenter()
        return
    note = ""
    fid = ""
    try:
        fid = _eagle_ensure_logbook_folder(lb)
    except Exception as e:
        note = f" · 🦅 folder pending: {e}"
    want_pid = areas.CONTENT_DESTS[dest][0]
    t = _content_task_for(log_tid)
    if t is None:
        _mint_raw_task(lb, dest, fid)
        note += " · 📸Raw minted"
    else:
        pid_old = t.get("_projectId") or t.get("projectId")
        tags_lc = {str(x).lower() for x in (t.get("tags") or [])}
        if pid_old != want_pid and tags_lc & {"📸edit", "📸post"}:
            # in-flight work stays where its Eagle reality lives
            # (review find 2026-07-28: a moved 📸edit task falls out of
            # file_edited's tv/fm scan; a moved 📸post task would
            # complete without its shelf sweep)
            note += " · 📸 task stays (in edit/post · finish first)"
        elif pid_old != want_pid:
            api.move_task(t["id"], pid_old, want_pid)
            try:
                import dispatch as _disp
                # both pools: Content PL is NOTE-kind, so the entry lives
                # in all_notes too and a one-pool patch strands a twin
                # still claiming the OLD list (2026-07-30)
                for _k in ("all_tasks", "all_notes"):
                    pool = cache_store.get(_k) or []
                    for x in pool:
                        if x.get("id") == t["id"]:
                            x["projectId"] = want_pid
                            x["_projectId"] = want_pid
                    cache_store.set(_k, pool)
                _disp._patch_project_data(t["id"], pid_old=pid_old,
                                          pid_new=want_pid)
            except Exception:
                cache_store.invalidate("all_tasks")
            note += " · 📸 task moved"
        # backfill a linkless title once the folder exists, and upgrade
        # legacy bare-scheme titles to the clickable markdown form
        if fid and not (t.get("title") or "").startswith("["):
            _content_retag(t, "", "",
                           title=_eagle_title(cr.logbook_base(lb), fid))
            note += " · link backfilled"
    _crm_say(f"🎬 {dest.upper()} set{note}")
    _reenter()


def eagle_folder(log_tid):
    """🦅 Ensure the logbook's Eagle skeleton exists, then open it in
    Eagle (switches to the CRM library first - raw links can't)."""
    if not _records_ready():
        return
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    if cr.PERSON_RE.match(lb.get("title") or ""):
        # a cold lead carries bare ARCHIVE_TAG and could reach a logbook
        # surface - never mint an Eagle skeleton for a person note
        _crm_say("🦅 Not a logbook")
        return
    had, _ = cr.eagle_folder_of(lb.get("content") or "")
    try:
        import eagle
        fid = _eagle_ensure_logbook_folder(lb)
        eagle.ensure_library("crm")
        subprocess.run(["open", f"eagle://folder/{fid}"], capture_output=True)
    except Exception as e:
        _crm_say(f"🦅 {e}")
        return
    _crm_say("🦅 Folder opened in Eagle" if had
             else "🦅 Skeleton created · opened in Eagle")


_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "heic": "image/heic", "heif": "image/heif", "tif": "image/tiff",
         "tiff": "image/tiff", "webp": "image/webp", "gif": "image/gif"}


def _attach_file_to(pid, tid, path, fname=None):
    """One file → real TickTick attachment. Videos never (spec: they
    pipeline through Eagle). RAW/DNG gets a sips JPEG rendition first,
    3072px max (Vex ruling 2026-07-26: ALL his shots are ProRAW -
    TickTick only takes JPG/HEIC/PNG, and a 48MP upload is pointless
    for a task preview). Probe: ~3s, ~1MB per ProRAW."""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in ("mov", "mp4", "m4v"):
        raise ValueError("video - images only")
    mime = _MIME.get(ext)
    cleanup = None
    if not mime:
        import shutil
        import tempfile
        tmpd = tempfile.mkdtemp(prefix="tickal_att_")
        cleanup = lambda: shutil.rmtree(tmpd, ignore_errors=True)
        out = os.path.join(
            tmpd, os.path.splitext(os.path.basename(path))[0] + ".jpg")
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "3072",
                            path, "--out", out],
                           capture_output=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(out):
            cleanup()
            raise ValueError(f".{ext} not convertible to JPEG")
        path, mime = out, "image/jpeg"
        if fname:
            fname = os.path.splitext(fname)[0] + ".jpg"
    try:
        with open(path, "rb") as f:
            data = f.read()
        import api_v2
        return api_v2.TickTickV2().upload_attachment(
            pid, tid, data, fname or os.path.basename(path), mime)
    finally:
        if cleanup:
            cleanup()


def _pick_heroes(shots):
    """EVERY ♥ favorite becomes a TickTick attachment (Vex 2026-07-26:
    arm shot + reference = two heroes; the old exactly-one rule died);
    a single-item selection counts without a ♥. Video ♥s skipped
    honestly; RAW/DNG fine - _attach_file_to renders JPEGs. Returns
    ([], reason) when nothing is attachable."""
    favs = [s for s in shots if s.get("favorite")]
    if not favs and len(shots) == 1:
        favs = list(shots)
    if not favs:
        return [], "no ♥ in selection"
    out = [s for s in favs
           if os.path.splitext(s["path"] or "")[1].lstrip(".").lower()
           not in ("mov", "mp4", "m4v")]
    if not out:
        return [], "♥ all videos - images only"
    return out, ""


_STAGES = {
    "consult": ("01 Consultation", "Consult", ["consult"]),
    "prep": ("02 Preparation", "Prep", ["prep"]),
    "design": ("03 Design", "Design", ["design"]),
    "finished": ("05 Finished", "Finished", ["finished"]),
    "healed": ("06 Healed", "Healed", ["healed"]),
}


def _is_stage_tag(t):
    """Does this tag encode WHICH stage a shot belongs to? The whole
    vocabulary: the five shelf tags, the 'session' marker and s<k>."""
    t = str(t).lower()
    return (t == "session" or bool(re.fullmatch(r"s\d+", t))
            or any(t in tg for _f, _l, tg in _STAGES.values()))


def _drop_stale_stage_tags(iid, keep):
    """Remove every stage tag the item carries that the NEW stage does
    not want. Best effort: a tag read or removal failure must never
    abort a move that already happened in Eagle."""
    import eagle
    keep_lc = {str(k).lower() for k in keep}
    try:
        cur = (eagle.get_items([iid]) or [{}])[0].get("tags") or []
        stale = [t for t in cur
                 if _is_stage_tag(t) and str(t).lower() not in keep_lc]
        if stale:
            eagle.remove_item_tags([iid], stale)
        return stale
    except Exception:
        return []


def _stage_spec(stage, lb, log_tid):
    """(folder_name, label, stage_tags) for a stage key. '' / 's' =
    the CURRENT session (started tasks only - never a merely-scheduled
    future one); 's<k>' = an explicit older session (backlog roads)."""
    import crm_records as cr
    if stage in _STAGES:
        f, l, t = _STAGES[stage]
        return f, l, list(t)
    m = re.match(r"^s(\d+)$", stage or "")
    n = (int(m.group(1)) if m
         else cr.current_snum(lb.get("content") or "", log_tid))
    return "04 Sessions", f"S{n}", ["session", f"s{n}"]


def session_photos(log_tid, stage=""):
    """📸 THE import action (Vex unification 2026-07-26: 'one action
    for everything, edge cases inside'). Source: Photos selection when
    one exists, else a clipboard image (content-hash named, so
    re-pastes dedupe), else honest toast. ALL shots → Eagle stage
    ('' = current session, s<k> = older, consult|prep|design|
    finished|healed = shelves) - each import annotated 'ph:<photos
    id>' and NEVER reimported; ♥ heroes → TickTick planted (stem
    guard, never duplicated); album + Photos delete for Photos
    sources only. Every surface rides THIS verb."""
    if not _records_ready():
        return False
    import shutil
    import tempfile
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return False
    import eagle
    import photos_bridge as pb
    tmp = tempfile.mkdtemp(prefix="tickal_tph_")
    try:
        src = "photos"
        shots = []
        if pb.photos_running() and pb.selection_count():
            try:
                shots = pb.selection_snapshot_export(tmp)
            except pb.PhotosError as e:
                _crm_say(f"📸 {e}")
                return False
        else:
            try:
                files = [p for p in _finder_selection()
                         if os.path.splitext(p)[1].lower() in _MEDIA_EXTS]
            except Exception:
                files = []
            if files:
                # Finder source (the old backlog roads folded in
                # 2026-07-27): filename = the dedupe identity
                shots = [{"id": "", "path": p,
                          "filename": os.path.basename(p),
                          "favorite": len(files) == 1}
                         for p in files]
                src = "finder"
            else:
                try:
                    import clipboard as clip_util
                    img = clip_util.png_bytes()
                except Exception:
                    img = None
                if img:
                    import hashlib
                    stem = "clip-" + hashlib.sha1(img).hexdigest()[:10]
                    p = os.path.join(tmp, f"{stem}.png")
                    with open(p, "wb") as f:
                        f.write(img)
                    shots = [{"id": "", "path": p,
                              "filename": f"{stem}.png", "favorite": True}]
                    src = "clip"
                else:
                    _crm_say("📸 Nothing to import · no Photos "
                             "selection, no Finder selection, no "
                             "clipboard image")
                    return False
        base = cr.logbook_base(lb)
        tags_lc = {str(t).lower() for t in (lb.get("tags") or [])}
        if not stage and areas.ARCHIVE_TAG in tags_lc:
            stage = "finished"
        try:
            fid = _eagle_ensure_logbook_folder(lb)
            eagle.ensure_library("crm")
            node = eagle.folder_node(fid)
            sub_name, label, stage_tags = _stage_spec(stage, lb, log_tid)
            child = next((c for c in (node or {}).get("children") or []
                          if c.get("name") == sub_name), None)
            sub_id = child["id"] if child else eagle.create_folder(
                sub_name, parent=fid)
            # reimport guard: every import is annotated with its
            # source identity - a re-run must never duplicate
            def _mark(s):
                return f"ph:{s.get('id') or s['filename']}"
            have = {(it.get("annotation") or "")
                    for it in eagle.items_in_folder(sub_id)}
            new_shots = [s for s in shots if _mark(s) not in have]
            esk = len(shots) - len(new_shots)
            start = eagle.next_index(
                eagle.list_item_names(sub_id), base, label)
            cust, _, tat = base.partition(" - ")
            tags = [t for t in (cust.strip(), tat.strip()) if t] + stage_tags
            dest = cr.content_dest_of(lb.get("content") or "")
            if dest in ("tv", "fm", "studio"):
                tags.append(dest)
            specs = [{"path": s["path"],
                      "name": eagle.item_name(base, label, start + i),
                      "tags": tags, "annotation": _mark(s)}
                     for i, s in enumerate(new_shots)]
            if specs:
                ids = eagle.add_items(specs, folder_id=sub_id)
                # background copy MUST finish before the tmp exports die
                eagle.wait_imported(ids)
        except eagle.EagleError as e:
            _crm_say(f"📸 Eagle trouble: {e} · shots safe in Photos")
            return False
        heroes, why = _pick_heroes(shots)
        att = ""
        if heroes:
            # consult refs are PERMANENT logbook material - never on
            # the (about-to-complete) consult task (Sarah smoke)
            nxt = None if label == "Consult" \
                else cr.next_session_task(log_tid)
            if nxt:
                a_pid = (nxt[2].get("_projectId")
                         or nxt[2].get("projectId") or areas.CRM_ID)
                a_tid, target = nxt[2]["id"], nxt[1]
            else:
                a_pid, a_tid, target = areas.RECORDS_ID, log_tid, "logbook"
            ok_n = dup_n = 0
            for i, h in enumerate(heroes):
                if (a_tid == log_tid
                        and _already_on_note(log_tid, h["filename"])):
                    dup_n += 1
                    continue
                try:
                    # ONE naming rule for both targets (Vex 2026-07-28):
                    # the original camera filename was NOT a stable
                    # dedupe key - the same shot imported twice landed
                    # once as IMG_3806.JPG and once as S1.png, so
                    # _already_on_note could not see the twin. The
                    # convention name is derived from the tattoo and the
                    # session, so re-runs collide and dedupe.
                    fname = (f"{base} · {label} · {i + 1}."
                             f"{h['path'].rsplit('.', 1)[-1]}")
                    up = _attach_file_to(a_pid, a_tid, h["path"], fname)
                    ok_n += 1
                    if a_tid == log_tid:   # note target → plant the ref
                        try:
                            _plant_logbook_ref(log_tid, up, label)
                        except Exception:
                            pass
                except Exception as e:
                    why = f"attach failed: {type(e).__name__}"
            att = ((f" · ♥×{ok_n} → {target}" if ok_n else f" · ♥ {why}")
                   + (f" · {dup_n} already there" if dup_n else ""))
        else:
            att = f" · {why}"
        alb = ""
        if src == "photos":
            try:
                pb.file_to_album([s["id"] for s in shots])
                alb = " · ✅ album"
            except pb.PhotosError:
                alb = " · album skipped"
        head = (f"📸 {len(new_shots)} → {base} · {label}"
                + (f" · {esk} already in Eagle" if esk else "")
                + {"clip": " · from clipboard",
                   "finder": " · from Finder"}.get(src, ""))
        _crm_say(f"{head}{att}{alb}")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def photo_attach(pid, tid):
    """📎 Independent attach: ♥ (or single selection) from Photos →
    attachment on ANY task. Eagle not involved."""
    import shutil
    import tempfile
    import photos_bridge as pb
    tmp = tempfile.mkdtemp(prefix="tickal_att_")
    try:
        try:
            shots = pb.selection_snapshot_export(tmp)
        except pb.PhotosError as e:
            _crm_say(f"📎 {e}")
            return
        heroes, why = _pick_heroes(shots)
        if not heroes:
            _crm_say(f"📎 {why}")
            return
        import areas
        _is_lb_note = False
        if pid == areas.RECORDS_ID:
            t = cache_store.find_task(tid) or {}
            _is_lb_note = (t.get("title") or "").startswith(("🎨", "🏛️"))
        _att_log(f"photo_attach pid={pid} tid={tid} lb_note={_is_lb_note} "
                 f"heroes={len(heroes)}")
        ok_n = dup_n = 0
        for h in heroes:
            if _is_lb_note and _already_on_note(tid, h["filename"]):
                dup_n += 1
                _att_log(f"skip dup {h['filename']}")
                continue
            try:
                up = _attach_file_to(pid, tid, h["path"], h["filename"])
                ok_n += 1
                _att_log(f"uploaded {h['filename']} → "
                         f"{(up or {}).get('attid')}")
                if _is_lb_note:   # logbook note → plant, never bottom
                    try:
                        _plant_logbook_ref(tid, up)
                    except Exception as e:
                        import traceback
                        _att_log("plant EXC: "
                                 + traceback.format_exc(limit=3))
            except Exception as e:
                why = f"{type(e).__name__}: {e}"
                _att_log(f"upload EXC {h['filename']}: {why}")
        dup = f" · {dup_n} already there" if dup_n else ""
        if ok_n:
            _crm_say(f"📎 {ok_n} attached{dup}"
                     + ("" if ok_n + dup_n == len(heroes)
                        else f" · rest failed: {why}"))
        elif dup_n:
            _crm_say(f"📎 All {dup_n} already on the note")
        else:
            _crm_say(f"📎 Attach failed: {why}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def eagle_triage(rest):
    """🦅 Apply the triage pick: file the CURRENT Eagle selection into
    <logTid>'s stage subfolder - move (membership REPLACED, so Review/
    Inbox strays leave their old shelf) + rename to convention +
    incremental tags. NEVER switches libraries: a switch would drop the
    selection - the CRM library must already be open (folder creation
    inside it is fine). ':attach' also attaches the FIRST selected item
    (image only) to the open session task / logbook."""
    if not _records_ready():
        return
    parts = rest.split(":")
    if len(parts) < 2:
        _crm_say("🦅 Bad triage arg")
        return
    log_tid, stage = parts[0], parts[1]
    attach = len(parts) > 2 and parts[2] == "attach"
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    import eagle
    base = cr.logbook_base(lb)
    try:
        eagle.ensure_running(launch=False)
        if eagle.current_library() != eagle.LIBS["crm"][0]:
            _crm_say("🦅 Open the CRM library in Eagle first")
            return
        sel = eagle.selected_items()
        if not sel:
            _crm_say("🦅 Nothing selected in Eagle")
            return
        if stage not in _STAGES and not re.match(r"^s(\d+)?$", stage):
            _crm_say(f"🦅 Unknown stage {stage!r}")
            return
        folder_name, label, stage_tags = _stage_spec(
            "" if stage == "s" else stage, lb, log_tid)
        fid = _eagle_ensure_logbook_folder(lb)
        node = eagle.folder_node(fid)
        child = next((c for c in (node or {}).get("children") or []
                      if c.get("name") == folder_name), None)
        sub_id = child["id"] if child else eagle.create_folder(
            folder_name, parent=fid)
        start = eagle.next_index(eagle.list_item_names(sub_id), base, label)
        eagle.update_items([{"id": it["id"],
                             "name": eagle.item_name(base, label, start + i),
                             "folders": [sub_id]}
                            for i, it in enumerate(sel)])
        cust, _, tat = base.partition(" - ")
        tags = [t for t in (cust.strip(), tat.strip()) if t] + stage_tags
        dest = cr.content_dest_of(lb.get("content") or "")
        if dest in ("tv", "fm", "studio"):
            tags.append(dest)
        eagle.add_item_tags([it["id"] for it in sel], tags)
    except eagle.EagleError as e:
        _crm_say(f"🦅 {e}")
        return
    att = ""
    if attach:
        try:
            full = eagle.get_items([sel[0]["id"]])
            path = (full[0] if full else {}).get("filePath") or ""
            nxt = cr.next_session_task(log_tid)
            if nxt:
                a_pid = (nxt[2].get("_projectId")
                         or nxt[2].get("projectId") or areas.CRM_ID)
                a_tid, target = nxt[2]["id"], nxt[1]
            else:
                a_pid, a_tid, target = areas.RECORDS_ID, log_tid, "logbook"
            _attach_file_to(a_pid, a_tid, path)
            att = f" · 📎 → {target}"
        except Exception as e:
            att = f" · 📎 failed: {type(e).__name__}"
    _crm_say(f"🦅 {len(sel)} filed → {base} · {label}{att}")


def _img_id_lib(path):
    """(item_id, lib_key) from an on-disk Eagle media path -
    …/<lib>.library/images/<id>.info/<file>. ('', '') when foreign."""
    import eagle
    m = re.search(r"/images/([^/]+)\.info/", path or "")
    iid = m.group(1) if m else ""
    lib = ""
    for k, (_n, p) in eagle.LIBS.items():
        if (path or "").startswith(p.rstrip("/") + "/"):
            lib = k
            break
    return iid, lib


def img_peek(payload):
    """⏎ on a folder-screen row: trampoline into the Grid View chain
    (ET GridPeek → gridfeed → grid). The whole context rides a b64
    payload because the osascript re-entry starts a FRESH session -
    row variables drop (crmbrowse-style); gridfeed's output envelope
    re-seeds lb_tid / peek_lib / peek_ret for the grid's chords."""
    _run_trigger("GridPeek", payload)


def img_open(path):
    """🖼 grid ⏎: open THIS shot in Eagle - switches to its library
    first (raw eagle:// links can't - probed 2026-07-25)."""
    import eagle
    iid, lib = _img_id_lib(path)
    if not iid:
        _crm_say("🖼 Not an Eagle item path")
        return
    try:
        eagle.ensure_library(lib or "crm")
        subprocess.run(["open", f"eagle://item/{iid}"], capture_output=True)
    except Exception as e:
        _crm_say(f"🦅 {e}")


def img_link(path):
    """🖼 grid ⌥⌘: eagle://item link → clipboard. No switch needed."""
    iid, _lib = _img_id_lib(path)
    if not iid:
        _crm_say("🖼 Not an Eagle item path")
        return
    subprocess.run(["pbcopy"], input=f"eagle://item/{iid}".encode())
    _crm_say("🔗 Eagle link copied")


def _att_log(msg):
    """Attach-road debug trail (Sarah smoke: 7 uploads toasted, note
    untouched, unreproducible from CLI - the next live run logs)."""
    try:
        import datetime
        with open("/tmp/tickal_attach.log", "a") as f:
            f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
    except OSError:
        pass


def _already_on_note(log_tid, fname):
    """True when an ![image] ref with this file's STEM already sits in
    the note - re-runs must never duplicate (Vex rule 2026-07-26).
    Stem match survives the RAW → .jpg rename; the cache is fresh
    enough (insert_session_images patches it per plant)."""
    stem = os.path.splitext(os.path.basename(fname or ""))[0]
    if not stem:
        return False
    c = (_record_by_id(log_tid) or {}).get("content") or ""
    return any(stem in l for l in c.split("\n")
               if l.lstrip().startswith("![image]("))


# label → the note section that mirrors its Eagle folder. Sessions are
# NOT here: they resolve to their own '### <date> · S<n>' entry.
_NOTE_SECTIONS = {"Consult": "## Consultation", "Prep": "## Preparation",
                  "Design": "## Design", "Finished": "## Finished",
                  "Healed": "## Healed"}


def _ensure_note_heading(log_tid, heading, anchor=None):
    """Guarantee `heading` exists in the logbook note, creating it when
    missing. anchor='## Sessions' appends a '### …' entry at the END of
    that section; otherwise a '## …' section is inserted before
    ## Notes so the note keeps reading header → sessions → stages →
    notes. Returns the heading, or None if the write failed."""
    import areas
    import crm_records as cr
    try:
        api = cr._api()
        live = api.get_task(areas.RECORDS_ID, log_tid)
        content = cr._fresher_content(log_tid, live.get("content") or "")
        if re.search(rf"^{re.escape(heading)}\s*$", content, re.M):
            return heading
        lines = content.split("\n")
        if anchor:
            i = next((k for k, l in enumerate(lines)
                      if l.strip() == anchor), len(lines) - 1)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1              # sit right after the last content line
            lines[j:j] = ["", heading]
        else:
            i = next((k for k, l in enumerate(lines)
                      if l.strip() == "## Notes"), len(lines))
            lines[i:i] = [heading, ""]
        new = "\n".join(lines)
        api.update_task(log_tid, areas.RECORDS_ID, current=live, content=new)
        _patch_content_cache(log_tid, new)
        return heading
    except Exception as e:
        _att_log(f"ensure heading failed ({heading!r}): {type(e).__name__}: {e}")
        return None


def _plant_logbook_ref(log_tid, up, label=""):
    """Planted, not just uploaded: bare attachments render at the
    BOTTOM of the note (Vex smoke 2026-07-26: 'ended up in notes').
    The ![image] ref goes under the matching '### <label> ·' entry
    when one exists ('S2' matches '### S2 ·', 'Consult' matches
    '### Consultation ·'), else straight under ## Sessions. False =
    could not place (attachment still on the note)."""
    if not (up or {}).get("attid"):
        _att_log(f"plant skip: no attid in {up!r:.120}")
        return False
    import areas
    import crm_records as cr
    ref = f"![image]({up['attid']}/{up['fname']})"
    content = (_record_by_id(log_tid) or {}).get("content") or ""
    heading = None
    if label:
        for l in content.split("\n"):
            s = l.strip()
            if not s.startswith("### "):
                continue
            # Entries are '### <date> · S1 · 6h · 750' - they start with
            # the DATE, so the old startswith(label) test could never
            # match and EVERY hero silently fell back to ## Sessions
            # (Vex smoke 2026-07-28). Match the label as a · segment.
            segs = [x.strip() for x in s.lstrip("# ").split("·")]
            exact = re.fullmatch(r"S\d+", label or "")
            if any(seg == label or (not exact and seg.startswith(label))
                   for seg in segs):
                heading = s
                break
    # NO '## Sessions' dumping ground (Vex 2026-07-28: "that should not
    # even exist. At all"). The note MIRRORS the Eagle folders: a
    # session photo goes under its exact session entry, a consultation
    # photo under ## Consultation, prep under ## Preparation, and so
    # on - the heading is CREATED when missing rather than the image
    # being dropped into a generic bucket.
    if heading is None:
        sect = _NOTE_SECTIONS.get(label)
        if sect:
            heading = _ensure_note_heading(log_tid, sect)
        elif re.fullmatch(r"S\d+", label or ""):
            heading = _ensure_note_heading(log_tid, f"### {label}",
                                           anchor="## Sessions")
    if heading is None:
        _att_log(f"plant skip: no heading (label={label!r}, "
                 f"content {len(content)}b)")
        return False
    cr.insert_session_image(areas.RECORDS_ID, log_tid, heading, 0, ref)
    _att_log(f"planted under {heading!r}")
    return True


def img_attach(path):
    """🖼 grid ⌥⇧: THIS shot → real attachment on the logbook note,
    PLANTED into the right block (label parsed from the convention
    name '{base} • S2 • 3')."""
    if not _records_ready():
        return
    import areas
    log_tid = os.environ.get("lb_tid") or ""
    if not log_tid:
        _crm_say("🖼 Lost the logbook context · re-enter the grid")
        return
    if _already_on_note(log_tid, os.path.basename(path)):
        _crm_say("📎 Already on the note")
        return
    try:
        up = _attach_file_to(areas.RECORDS_ID, log_tid, path)
    except Exception as e:
        _crm_say(f"📎 {e}")
        return
    import eagle as _eg
    _b, label, _n = _eg.item_base(os.path.splitext(
        os.path.basename(path))[0])
    try:
        planted = _plant_logbook_ref(log_tid, up, label)
    except Exception:
        import traceback
        _att_log("img_attach plant EXC: " + traceback.format_exc(limit=3))
        planted = False
    _crm_say("📎 Attached · " + (f"under {label or 'Sessions'}"
                                 if planted else "note bottom"))


def img_trash(path):
    """🖼 grid ⌃⇧: cull the dud - Eagle trash (recoverable), its
    library switched open first (the API acts on the open library)."""
    import eagle
    iid, lib = _img_id_lib(path)
    if not iid:
        _crm_say("🖼 Not an Eagle item path")
        return
    try:
        eagle.ensure_library(lib or "crm")
        eagle.trash_items([iid])
    except Exception as e:
        _crm_say(f"🦅 {e}")
        return
    _crm_say("🗑 To Eagle trash · recoverable in Eagle")


def img_post(path):
    """🖼 grid ⇧: THIS shot is final → COPY to the dest library's
    03 Post shelf + task → 📸Post (single-shot promote; ⌘ Edit-this
    stays the batch road). The CRM original is never touched - the
    source path lives inside another .library on disk."""
    if not _records_ready():
        return
    import crm_records as cr
    import eagle
    log_tid = os.environ.get("lb_tid") or ""
    lb = _record_by_id(log_tid) if log_tid else None
    if not lb:
        _crm_say("🖼 Lost the logbook context · re-enter the grid")
        return
    dest = cr.content_dest_of(lb.get("content") or "")
    if dest not in areas.CONTENT_DESTS:
        _crm_say("🎬 Set Content potential (TV · FM · Studio) first")
        return
    iid, _slib = _img_id_lib(path)
    base = cr.logbook_base(lb)
    try:
        eagle.ensure_library(dest)
        shelf = _cp_folders(eagle)["Post"]
        # idempotency: the copy's annotation carries the SOURCE item id -
        # a second ⇧ on the same shot must not duplicate (review find)
        mark = f"src:{iid}" if iid else ""
        copied = True
        if mark and any((it.get("annotation") or "") == mark
                        for it in eagle.items_in_folder(shelf)):
            copied = False
        else:
            # name + tags like every other To-post road: convention
            # '{base} • Edit • n' keeps the shot sweepable by Posted
            # and acceptable to ⭐ Portfolio (review find)
            cust, _, tat = base.partition(" - ")
            tags = [x for x in (cust.strip(), tat.strip()) if x] + [dest]
            n = eagle.next_index(eagle.list_item_names(shelf), base, "Edit")
            ids = eagle.add_items(
                [{"path": path, "name": eagle.item_name(base, "Edit", n),
                  "tags": tags, "annotation": mark}], folder_id=shelf)
            eagle.wait_imported(ids)
    except Exception as e:
        _crm_say(f"🦅 {e}")
        return
    fid, _l = cr.eagle_folder_of(lb.get("content") or "")
    t = _content_task_for(log_tid)
    if t is None:
        _mint_raw_task(lb, dest, fid, tag="📸post")
        note = "📸Post task minted"
    else:
        tags = {str(x).lower() for x in (t.get("tags") or [])}
        if "📸post" in tags:
            note = "task already Post"
        else:
            drop = ("📸raw" if "📸raw" in tags
                    else "📸edit" if "📸edit" in tags else "")
            _content_retag(t, drop, "📸post")
            note = "task → Post"
    _crm_say(("📤 Shot → 03 Post · " if copied
              else "📤 Already on 03 Post · ") + note)


def img_move(stage):
    """🖼 grid ⌘⇧ road tail: move ONE shot into a lifecycle stage
    folder + rename to convention + incremental tags (mirrors the
    triage tail, but the item rides img_path env - no Eagle selection
    at stake, so switching libraries is safe here)."""
    if not _records_ready():
        return
    import crm_records as cr
    import eagle
    path = os.environ.get("img_path") or ""
    log_tid = os.environ.get("lb_tid") or ""
    lb = _record_by_id(log_tid) if log_tid else None
    iid, lib = _img_id_lib(path)
    if not (lb and iid):
        _crm_say("🖼 Lost the image context · re-enter the grid")
        return
    if lib and lib != "crm":
        _crm_say("🖼 CRM-library shots only - stages live there")
        return
    base = cr.logbook_base(lb)
    try:
        eagle.ensure_library("crm")
        folder_name, label, stage_tags = _stage_spec(
            "" if stage == "s" else stage, lb, log_tid)
        fid = _eagle_ensure_logbook_folder(lb)
        node = eagle.folder_node(fid)
        child = next((c for c in (node or {}).get("children") or []
                      if c.get("name") == folder_name), None)
        sub_id = child["id"] if child else eagle.create_folder(
            folder_name, parent=fid)
        n = eagle.next_index(eagle.list_item_names(sub_id), base, label)
        eagle.update_items([{"id": iid,
                             "name": eagle.item_name(base, label, n),
                             "folders": [sub_id]}])
        cust, _, tat = base.partition(" - ")
        tags = [t for t in (cust.strip(), tat.strip()) if t] + stage_tags
        dest = cr.content_dest_of(lb.get("content") or "")
        if dest in ("tv", "fm", "studio"):
            tags.append(dest)
        # Drop the tag of the stage it LEFT first - add_item_tags is
        # incremental, so without this a shot moved S3 → S2 answers to
        # both (Vex smoke 2026-07-28, the Luca • Pharaoph mis-numbering:
        # re-staging is exactly the road you walk to repair one).
        _drop_stale_stage_tags(iid, tags)
        eagle.add_item_tags([iid], tags)
    except eagle.EagleError as e:
        _crm_say(f"🦅 {e}")
        return
    _crm_say(f"🖼 → {folder_name} · {label}")


_BUCKET_LABELS = {"unfiled": "unfiled", "s0": "unnumbered"}


def _bucket_label(bucket):
    """Human name for a source bucket key."""
    if bucket in _STAGES:
        return _STAGES[bucket][1]
    if bucket in _BUCKET_LABELS:
        return _BUCKET_LABELS[bucket]
    m = re.fullmatch(r"s(\d+)", bucket or "")
    return f"S{m.group(1)}" if m else (bucket or "?")


def _bucket_items(lib_path, fid, bucket):
    """The shots a folder-screen bucket row stands for, read from DISK
    with the SAME rules render_lbeagle uses - so what the row counts is
    exactly what a bulk move moves. Returns [] for an unknown bucket."""
    import eagle
    root, all_ids = eagle.disk_subtree_ids(lib_path, fid)
    items = eagle.disk_items_in(lib_path, all_ids)

    def sub(node):
        out = {node["id"]}
        for ch in node.get("children") or []:
            out |= sub(ch)
        return out

    def child(name):
        return next((c for c in root.get("children") or []
                     if (c.get("name") or "") == name), None)

    if bucket == "unfiled":
        return [it for it in items if root["id"] in (it.get("folders") or [])]
    if bucket in _STAGES:
        c = child(_STAGES[bucket][0])
        if not c:
            return []
        cset = sub(c)
        return list({it["id"]: it for it in items
                     if set(it.get("folders") or []) & cset}.values())
    m = re.fullmatch(r"s(\d+)", bucket or "")
    if not m:
        return []
    k = int(m.group(1))
    c = child("04 Sessions")
    if not c:
        return []
    cset = sub(c)
    pool = {it["id"]: it for it in items
            if set(it.get("folders") or []) & cset}.values()
    out = []
    for it in pool:
        _b, st, _n = eagle.item_base(it.get("name") or "")
        mm = re.fullmatch(r"S(\d+)", st or "")
        if (int(mm.group(1)) if mm else 0) == k:
            out.append(it)
    return out


def _note_heading_index(lines, label):
    """Index of the note heading a label owns: '### <date> · S3 · …'
    matched per '·' segment (S<n> exactly, so S1 cannot swallow S10),
    or the '## <Section>' that mirrors a shelf folder. None = absent."""
    sect = _NOTE_SECTIONS.get(label)
    exact = re.fullmatch(r"S\d+", label or "")
    for i, l in enumerate(lines):
        s = l.strip()
        if sect and s == sect:
            return i
        if not s.startswith("### "):
            continue
        segs = [x.strip() for x in s.lstrip("# ").split("·")]
        if any(seg == label or (not exact and seg.startswith(label))
               for seg in segs):
            return i
    return None


def _move_note_refs(log_tid, from_label, to_label):
    """Take the note's image refs WITH the shots (Vex green 2026-07-28,
    the whole-trail principle the delete road set). Every ![image] line
    under the source heading belongs to a shot in the bucket being
    emptied, so they all follow. ONE write: the target heading is
    created in memory rather than through _ensure_note_heading, so a
    lagging re-read cannot land between the two edits. Returns how many
    refs moved (0 = nothing to do, which is the common case)."""
    import areas
    import crm_records as cr
    try:
        api = cr._api()
        live = api.get_task(areas.RECORDS_ID, log_tid)
        content = cr._fresher_content(log_tid, live.get("content") or "")
        lines = content.split("\n")
        src = _note_heading_index(lines, from_label)
        if src is None:
            return 0
        end = src + 1
        while end < len(lines) and not lines[end].lstrip().startswith("#"):
            end += 1
        refs = [l for l in lines[src + 1:end]
                if l.lstrip().startswith("![image](")]
        if not refs:
            return 0
        keep = [l for l in lines[src + 1:end]
                if not l.lstrip().startswith("![image](")]
        lines[src + 1:end] = keep
        dst = _note_heading_index(lines, to_label)
        if dst is None:                      # create it, in memory
            if to_label in _NOTE_SECTIONS:
                i = next((k for k, l in enumerate(lines)
                          if l.strip() == "## Notes"), len(lines))
                lines[i:i] = [_NOTE_SECTIONS[to_label], ""]
                dst = i
            elif re.fullmatch(r"S\d+", to_label or ""):
                i = next((k for k, l in enumerate(lines)
                          if l.strip() == "## Sessions"), None)
                if i is None:
                    return 0
                j = i + 1
                while j < len(lines) and not lines[j].startswith("## "):
                    j += 1
                while j > i + 1 and not lines[j - 1].strip():
                    j -= 1
                lines[j:j] = ["", f"### {to_label}"]
                dst = j + 1
            else:
                return 0
        lines[dst + 1:dst + 1] = refs
        new = "\n".join(lines)
        api.update_task(log_tid, areas.RECORDS_ID, current=live, content=new)
        _patch_content_cache(log_tid, new)
        return len(refs)
    except Exception as e:
        _att_log(f"move note refs {from_label}→{to_label} failed: "
                 f"{type(e).__name__}: {e}")
        return 0


def bulk_move(rest):
    """⇧ on a folder-screen bucket row: move EVERY shot in it to another
    stage (Vex ask 2026-07-28, after 'attach to this session' filed 7 of
    Luca's shots as S3 - repairing that one shot at a time was the only
    road). rest = '<log_tid>:<from_bucket>:<to_stage>'. Renames to the
    convention with fresh indices, refiles, retags (dropping the stage
    it left), and the note's image refs follow. No confirm dialog by
    design: picking the target IS the confirmation and a wrong move is
    undone by moving back."""
    if not _records_ready():
        return
    parts = (rest or "").split(":")
    if len(parts) < 3:
        _crm_say("🖼 Bad move request")
        return
    log_tid, src, dst = parts[0], parts[1], ":".join(parts[2:])
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    import crm_records as cr
    import eagle
    base = cr.logbook_base(lb)
    try:
        eagle.ensure_running()
        eagle.ensure_library("crm")
        fid = _eagle_ensure_logbook_folder(lb)
        lib_path = eagle.LIBS["crm"][1]
        shots = _bucket_items(lib_path, fid, src)
        if not shots:
            _crm_say(f"🖼 Nothing in {_bucket_label(src)}")
            return
        folder_name, label, stage_tags = _stage_spec(
            "" if dst == "s" else dst, lb, log_tid)
        if label == _bucket_label(src):
            _crm_say(f"🖼 Already in {label}")
            return
        node = eagle.folder_node(fid)
        child = next((c for c in (node or {}).get("children") or []
                      if c.get("name") == folder_name), None)
        sub_id = child["id"] if child else eagle.create_folder(
            folder_name, parent=fid)
        # names first, all of them, so the batch cannot collide with
        # itself - next_index only sees what is already on disk.
        # Renumber in the ORDER THEY WERE SHOT (the trailing index of
        # the old name), not in whatever order the disk walk returned,
        # so S3 • 4 does not become S2 • 2.
        def _idx(it):
            _b, _s, n = eagle.item_base(it.get("name") or "")
            return (n or 10 ** 6, it.get("name") or "")
        shots = sorted(shots, key=_idx)
        existing = eagle.list_item_names(sub_id)
        payload, ids = [], []
        for it in shots:
            n = eagle.next_index(existing, base, label)
            nm = eagle.item_name(base, label, n)
            existing.append(nm)
            payload.append({"id": it["id"], "name": nm, "folders": [sub_id]})
            ids.append(it["id"])
        eagle.update_items(payload)
        cust, _, tat = base.partition(" - ")
        tags = [t for t in (cust.strip(), tat.strip()) if t] + stage_tags
        dest = cr.content_dest_of(lb.get("content") or "")
        if dest in ("tv", "fm", "studio"):
            tags.append(dest)
        keep = {str(t).lower() for t in tags}
        stale = sorted({t for it in shots for t in (it.get("tags") or [])
                        if _is_stage_tag(t) and str(t).lower() not in keep})
        if stale:
            try:
                eagle.remove_item_tags(ids, stale)
            except Exception:
                pass
        eagle.add_item_tags(ids, tags)
    except eagle.EagleError as e:
        _crm_say(f"🦅 {e}")
        return
    moved = _move_note_refs(log_tid, _bucket_label(src), label)
    _crm_say(f"🖼 {len(shots)} · {_bucket_label(src)} → {label}"
             + (f" · {moved} note ref(s) followed" if moved else ""))


def _eagle_trash_folder(lb):
    """🗑 delete-road Eagle erase for ONE logbook: every item in the
    tattoo folder's subtree → Eagle Trash (restorable in-app), the empty
    husk → a '🗑 Deleted' bin at the CRM library root. Eagle's API has
    NO folder delete (probed 4.0 2026-07-28: folder/delete → 404) - Vex
    empties the bin by hand, same pattern as the ✅ In Eagle album.
    Best-effort AFTER the TickTick delete; Eagle asleep → honest skip
    fragment, no launch (the archive-move precedent). No 🦅 line →
    silent '' no-op."""
    import crm_records as cr
    fid = cr.eagle_folder_of((lb or {}).get("content") or "")[0]
    if not fid:
        return ""
    import eagle
    try:
        eagle.ensure_running(launch=False)   # asleep = honest skip
        eagle.ensure_library("crm")
        tree = eagle.folder_tree()
        node = eagle.folder_node(fid, tree=tree)
        if node is None:
            return "🦅 folder gone already"   # 🦅 line, no such folder
        ids = set()

        def rec(nd):
            ids.update(i["id"] for i in eagle.items_in_folder(nd["id"]))
            for c in nd.get("children") or []:
                rec(c)
        rec(node)
        if ids:
            eagle.trash_items(sorted(ids))
    except Exception as e:                    # raw-API leg failed whole
        return f"🦅 skipped: {e}"
    # Items are ALREADY in Eagle Trash here - the husk move rides the
    # MCP plugin channel and may fail alone (plugin off). Separate try,
    # separate truth (review find 2026-07-28: one blanket except said
    # 'skipped' after the items were long gone).
    try:
        husk = eagle.find_folder("🗑 Deleted", tree=tree)
        husk_id = husk["id"] if husk else eagle.create_folder("🗑 Deleted")
        eagle.move_folder(fid, husk_id)
    except Exception as e:
        return (f"🦅 {len(ids)} → Eagle Trash · husk stayed: {e}" if ids
                else f"🦅 husk stayed: {e}")
    return (f"🦅 {len(ids)} → Eagle Trash" if ids
            else "🦅 husk → 🗑 Deleted")


def _eagle_archive_folder(log_tid, quiet=False):
    """Post-archive weave: tattoo folder → Archive/ + 'archive' tag on
    its items. Best-effort AFTER the TickTick archive (the state owner
    is already right) - Eagle asleep → honest skip toast. No 🦅 line
    (backlog imports) → silent no-op. quiet=True suppresses the toast
    (the sweep speaks once for the whole batch). Returns True only when
    a folder actually MOVED, so callers can count honestly; a folder
    already under Archive/ is a no-op, not a move."""
    import crm_records as cr
    lb = _record_by_id(log_tid)
    fid = cr.eagle_folder_of((lb or {}).get("content") or "")[0]
    if not fid:
        return False
    import eagle
    try:
        eagle.ensure_running(launch=False)   # asleep = honest skip, no launch
        eagle.ensure_library("crm")
        tree = eagle.folder_tree()
        arch = eagle.find_folder("Archive", tree=tree)
        arch_id = arch["id"] if arch else eagle.create_folder("Archive")
        node = eagle.folder_node(fid, tree=tree)
        if node is None:
            return False
        if any(c.get("id") == fid for c in (arch or {}).get("children") or []):
            return False              # already filed - nothing to do
        eagle.move_folder(fid, arch_id)
        ids = set()

        def rec(nd):
            ids.update(i["id"] for i in eagle.items_in_folder(nd["id"]))
            for c in nd.get("children") or []:
                rec(c)
        rec(node)
        if ids:
            eagle.add_item_tags(sorted(ids), ["archive"])
        if not quiet:
            _crm_say("🦅 Eagle folder → Archive")
        return True
    except eagle.EagleError as e:
        if not quiet:
            _crm_say(f"🦅 archive move skipped: {e}")
        return False


def _cp_folders(eagle):
    """{suffix: id} for the OPEN content library's four working folders
    (Vex final shape 2026-07-28: 01 Raw / 02 Edit / 03 Post / 04 Portfolio,
    FLAT - the 'Content pipeline' parent is GONE). Keyed by suffix, so a
    renumbered prefix can never break a caller. 03 Post stays FLAT by
    design: Eagle has no folder-delete API, so per-tattoo post subfolders
    would pile up as empty husks; item names carry identity instead."""
    return eagle.pipeline_folders()


def _portfolio_folder(eagle, base):
    """04 Portfolio/{base} id in the OPEN library, created if new."""
    pid = eagle.pipeline_folders()["Portfolio"]
    node = eagle.folder_node(pid)
    hit = next((c for c in ((node or {}).get("children") or [])
                if c.get("name") == base), None)
    return hit["id"] if hit else eagle.create_folder(base, parent=pid)


def edit_this(log_tid):
    """🎬 Edit this: copy the WHOLE CRM tattoo tree (read from DISK -
    the closed CRM library is never opened, ONE switch total) into
    {dest}/02 Edit/{base}, then slide the content task
    to 📸Edit with its link retargeted to the 02 Edit folder. From that
    folder id on, the link NEVER changes - editing-done re-parents the
    same folder under Raw/, and Eagle re-parenting keeps ids."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    lb = _record_by_id(log_tid)
    if not lb:
        _crm_say("Logbook not found · run tsy")
        return
    import eagle
    base = cr.logbook_base(lb)
    fid, _lib = cr.eagle_folder_of(lb.get("content") or "")
    if not fid:
        _crm_say("🎬 No Eagle folder yet · run 🦅 or 📸 first")
        return
    cur = cr.content_dest_of(lb.get("content") or "")
    OPTS = ["📺 TV - neotrad", "🖋️ FM - fineline",
            "🏷 Studio - studio account"]
    pick = _choose(f"🎬 Edit {base} - where to?", OPTS,
                   default={"tv": OPTS[0], "fm": OPTS[1],
                            "studio": OPTS[2]}.get(cur))
    if pick is None:
        _crm_say("Cancelled")
        return
    dest = ("tv" if pick.startswith("📺")
            else "fm" if pick.startswith("🖋") else "studio")
    if dest != cur:
        api = cr._api()
        live = api.get_task(areas.RECORDS_ID, log_tid)
        fresh = cr._fresher_content(log_tid, live.get("content") or "")
        new = cr.set_content_dest(fresh, dest)
        api.update_task(log_tid, areas.RECORDS_ID, current=live, content=new)
        _patch_content_cache(log_tid, new)
    try:
        crm_path = eagle.LIBS["crm"][1]
        root, sub_ids = eagle.disk_subtree_ids(crm_path, fid)
        items = [i for i in eagle.disk_items_in(crm_path, sub_ids)
                 if i.get("path")]
        eagle.ensure_library(dest)
        cp_kids = _cp_folders(eagle)
        tedit_id = cp_kids["Edit"]
        tree = eagle.folder_tree()
        tenode = eagle.folder_node(tedit_id, tree=tree)
        hit = next((c for c in (tenode or {}).get("children") or []
                    if c.get("name") == base), None)
        base_id = hit["id"] if hit else eagle.create_folder(
            base, parent=tedit_id)
        mapping = {root["id"]: base_id}

        def mirror(src_node, dest_id):
            dnode = eagle.folder_node(dest_id)
            have = {c.get("name"): c["id"]
                    for c in (dnode or {}).get("children") or []}
            for c in src_node.get("children") or []:
                did = have.get(c["name"]) or eagle.create_folder(
                    c["name"], parent=dest_id)
                mapping[c["id"]] = did
                mirror(c, did)
        mirror(root, base_id)
        by_folder = {}
        for it in items:
            tgt = next((mapping[f] for f in it["folders"] if f in mapping),
                       base_id)
            by_folder.setdefault(tgt, []).append(it)
        n = skipped = 0
        for tgt, group in by_folder.items():
            # idempotency: a re-run (or a retry after a mid-run error)
            # must not duplicate already-copied files (review find) -
            # names are per-item unique by convention
            have = set(eagle.list_item_names(tgt))
            fresh_group = [g for g in group if g["name"] not in have]
            skipped += len(group) - len(fresh_group)
            if fresh_group:
                eagle.add_items([{"path": g["path"], "name": g["name"],
                                  "tags": g["tags"]} for g in fresh_group],
                                folder_id=tgt)
            n += len(fresh_group)
    except eagle.EagleError as e:
        _crm_say(f"🎬 {e}")
        return
    want_pid = areas.CONTENT_DESTS[dest][0]
    _content_slide_to_edit(lb, dest, want_pid, base_id)
    extra = f" · {skipped} already staged" if skipped else ""
    _crm_say(f"🎬 {n} files → {dest.upper()} 02 Edit · task → 📸Edit{extra}")


def _content_slide_to_edit(lb, dest, want_pid, base_id):
    """Shared promote tail (editthis + promotesel - review find: the
    selection road skipped all three steps): move the content task to
    the dest list, swap 📸raw→📸edit, retarget the title link to the
    02 Edit folder, patch caches - or mint fresh when none exists."""
    import crm_records as cr
    base = cr.logbook_base(lb)
    t = _content_task_for(lb["id"])
    if t is None:
        _mint_raw_task(lb, dest, base_id, tag="📸edit")
        return
    api = cr._api()
    pid_old = t.get("_projectId") or t.get("projectId")
    if pid_old != want_pid:
        api.move_task(t["id"], pid_old, want_pid)
    live = api.get_task(want_pid, t["id"])
    tags = [x for x in (live.get("tags") or [])
            if str(x).lower() != "📸raw"]
    if "📸edit" not in {str(x).lower() for x in tags}:
        tags.append("📸edit")
    title = _eagle_title(base, base_id)
    api.update_task(t["id"], want_pid, current=live, tags=tags, title=title)
    try:
        import dispatch as _disp
        # both pools - see _content_retag's note; Content PL is NOTE-kind
        for _k in ("all_tasks", "all_notes"):
            pool = cache_store.get(_k) or []
            for x in pool:
                if x.get("id") == t["id"]:
                    x["projectId"] = want_pid
                    x["_projectId"] = want_pid
            cache_store.set(_k, pool)
        _disp._patch_project_data(t["id"], pid_old=pid_old,
                                  pid_new=want_pid)
        _disp._patch_task_cache(t["id"], tags=tags, title=title)
    except Exception:
        cache_store.invalidate("all_tasks")


def promote_selection():
    """🎬 Cherry-pick promote: the Eagle selection (CRM library open,
    never switched before reading - a switch drops it) → 02 Edit/{base}
    flat. The tattoo is inferred from the selection's folders via the
    logbooks' 🦅 lines; spanning two tattoos is an honest refusal."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    import eagle
    try:
        eagle.ensure_running(launch=False)
        if eagle.current_library() != eagle.LIBS["crm"][0]:
            _crm_say("🎬 Open the CRM library + select items first")
            return
        sel = eagle.selected_items()
        if not sel:
            _crm_say("🎬 Nothing selected in Eagle")
            return
        full = eagle.get_items([s["id"] for s in sel])
        paths = [(f.get("name"), f.get("filePath"), f.get("tags") or [])
                 for f in full if f.get("filePath")]
        sel_folders = set()
        for f in full:
            sel_folders.update(f.get("folders") or [])
        crm_path = eagle.LIBS["crm"][1]
        owner = None
        for lb in cr.records_notes(areas.LOGBOOK_TAG) \
                + cr.records_notes(areas.ARCHIVE_TAG):
            f0, _ = cr.eagle_folder_of(lb.get("content") or "")
            if not f0:
                continue
            try:
                _root, ids = eagle.disk_subtree_ids(crm_path, f0)
            except eagle.EagleError:
                continue
            if sel_folders & set(ids):
                if owner and owner.get("id") != lb.get("id"):
                    _crm_say("🎬 Selection spans two tattoos - pick one")
                    return
                owner = lb
        if owner is None:
            _crm_say("🎬 Selection is not inside a tattoo folder")
            return
        base = cr.logbook_base(owner)
        cur = cr.content_dest_of(owner.get("content") or "")
        OPTS = ["📺 TV - neotrad", "🖋️ FM - fineline"]
        pick = _choose(f"🎬 Promote {len(paths)} of {base} - where to?",
                       OPTS, default={"tv": OPTS[0], "fm": OPTS[1]}.get(cur))
        if pick is None:
            _crm_say("Cancelled")
            return
        dest = "tv" if pick.startswith("📺") else "fm"
        eagle.ensure_library(dest)
        cp_kids = _cp_folders(eagle)
        tenode = eagle.folder_node(cp_kids["Edit"])
        hit = next((c for c in (tenode or {}).get("children") or []
                    if c.get("name") == base), None)
        base_id = hit["id"] if hit else eagle.create_folder(
            base, parent=cp_kids["Edit"])
        eagle.add_items([{"path": p, "name": nm, "tags": tg}
                         for nm, p, tg in paths], folder_id=base_id)
    except eagle.EagleError as e:
        _crm_say(f"🎬 {e}")
        return
    import crm_records as cr
    if dest != cur:
        api = cr._api()
        live = api.get_task(areas.RECORDS_ID, owner["id"])
        fresh = cr._fresher_content(owner["id"], live.get("content") or "")
        new = cr.set_content_dest(fresh, dest)
        api.update_task(owner["id"], areas.RECORDS_ID, current=live,
                        content=new)
        _patch_content_cache(owner["id"], new)
    want_pid = areas.CONTENT_DESTS[dest][0]
    _content_slide_to_edit(owner, dest, want_pid, base_id)
    _crm_say(f"🎬 {len(paths)} → {dest.upper()} 02 Edit/{base}")


def file_edited():
    """📥 File edited shots: sweep Eagle's OWN per-library inbox folders
    (eagle.INTAKE - "Eagle Inbox/<library>/", Vex 2026-07-31) → import
    into the right library's flat 03 Post + '{base} • Edit • n' names →
    source files removed → task slides 📸Edit → 📸Post → optional ⭐
    hero to Portfolio → optional 'editing finished' folder move
    02 Edit/{base} → Raw/ (same folder id - task links survive).

    TWIN GUARD: Eagle's auto-import sweep may fire on its own schedule
    (probed: not live in 4.0.0, likely at launch). If a stem already
    exists as an UNFILED live item, Eagle beat us to it - that item is
    adopted (renamed/tagged/filed in place) instead of re-imported, so
    the shot can never double no matter when Eagle's sweep runs."""
    import areas
    import crm_records as cr
    import eagle
    batches = {}
    for lib in ("tv", "fm", "studio"):
        d = eagle.INTAKE[lib]
        try:
            fs = [os.path.join(d, f) for f in sorted(os.listdir(d))
                  if not f.startswith(".")
                  and os.path.isfile(os.path.join(d, f))]
        except OSError:
            fs = []
        if fs:
            batches[lib] = fs
    if not batches:
        _crm_say("📥 All intake folders empty")
        return
    filed = 0
    notes = []
    for lib, files in batches.items():
        pid = areas.CONTENT_DESTS[lib][0]
        cands = {}
        for t in cache_store.get("all_tasks") or []:
            if ((t.get("_projectId") or t.get("projectId")) == pid
                    and t.get("status", 0) == 0):
                tags_lc = {str(x).lower() for x in (t.get("tags") or [])}
                if tags_lc & {"📸edit", "📸post", "📸raw"}:
                    cands[_task_base(t.get("title") or "")] = t
        groups = {}
        for path in files:
            stem = os.path.splitext(os.path.basename(path))[0]
            best, _score, conf = eagle.fuzzy_match(stem, list(cands))
            if not conf:
                pick = _choose(f"📥 {os.path.basename(path)} → which tattoo?",
                               sorted(cands) or ["(no content tasks)"],
                               default=best)
                if pick is None or pick not in cands:
                    notes.append(f"{os.path.basename(path)} skipped")
                    continue
                best = pick
            groups.setdefault(best, []).append(path)
        if not groups:
            continue
        try:
            eagle.ensure_library(lib)
            unfiled = eagle.disk_unfiled(eagle.LIBS[lib][1])
            cp_kids = _cp_folders(eagle)
            tpost_id = cp_kids["Post"]
            existing = eagle.list_item_names(tpost_id)
            for base, paths in groups.items():
                start = eagle.next_index(existing, base, "Edit")
                cust, _, tat = base.partition(" - ")
                tags = [x for x in (cust.strip(), tat.strip()) if x]
                tags.append("edited")
                # twin guard: split Eagle-already-imported from fresh
                adopt, fresh = [], []
                for p in paths:
                    stem = os.path.splitext(os.path.basename(p))[0]
                    eid = unfiled.get(stem.casefold())
                    (adopt if eid else fresh).append((p, eid))
                ids, names = [], []
                if adopt:
                    ups = [{"id": eid,
                            "name": eagle.item_name(base, "Edit",
                                                    start + i),
                            "tags": tags, "folders": [tpost_id]}
                           for i, (_p, eid) in enumerate(adopt)]
                    eagle.update_items(ups)
                    ids += [eid for _p, eid in adopt]
                    names += [u["name"] for u in ups]
                    start += len(adopt)
                    notes.append(f"{len(adopt)} adopted (Eagle beat us)")
                if fresh:
                    specs = [{"path": p,
                              "name": eagle.item_name(base, "Edit",
                                                      start + i),
                              "tags": tags}
                             for i, (p, _e) in enumerate(fresh)]
                    new_ids = eagle.add_items(specs, folder_id=tpost_id)
                    # sources are DELETED below - verify the copy landed
                    eagle.wait_imported(new_ids)
                    ids += new_ids
                    names += [s["name"] for s in specs]
                for p in paths:
                    try:
                        os.remove(p)
                    except OSError:
                        # a stuck source would re-import as a dupe next
                        # run - surface it, never claim clean filing
                        notes.append(f"{os.path.basename(p)} stuck in intake")
                filed += len(ids)
                t = cands.get(base)
                if t and "📸edit" in {str(x).lower()
                                      for x in (t.get("tags") or [])}:
                    _content_retag(t, "📸edit", "📸post")
                hero = _choose(f"⭐ {base}: hero to Portfolio?",
                               ["None"] + names, default="None")
                if hero and hero != "None":
                    eagle.add_to_folders([ids[names.index(hero)]],
                                         [_portfolio_folder(eagle, base)])
                fin = _dialog(f"✅ {base}: editing finished?",
                              ["Not yet", "Finished"], "Not yet")
                if fin == "Finished":
                    tree = eagle.folder_tree()
                    ten = eagle.folder_node(cp_kids["Edit"], tree=tree)
                    bnode = next((c for c in (ten or {}).get("children")
                                  or [] if c.get("name") == base), None)
                    if bnode:
                        # exact find_folder("Raw") would have missed his
                        # "01 Raw" and minted a third one (2026-07-28)
                        eagle.move_folder(bnode["id"], cp_kids["Raw"])
                        time.sleep(0.4)   # Eagle commits a re-parent slowly
                        _heal_double_parents([bnode["id"]], cp_kids["Raw"])
                        notes.append(f"{base} → Raw")
        except eagle.EagleError as e:
            _crm_say(f"📥 {lib.upper()}: {e}")
            return
    extra = (" · " + " · ".join(notes)) if notes else ""
    _crm_say(f"📥 {filed} filed → 03 Post{extra}")


def to_portfolio():
    """⭐ Eagle selection (TV/FM open) → 04 Portfolio/{base}
    membership added - the multi-shelf trick, nothing moves. Base from
    the item names ('{C} - {T} • …' - 03 Post is flat)."""
    import eagle
    try:
        eagle.ensure_running(launch=False)
        lib = eagle.current_library()
        if lib not in (eagle.LIBS[k][0] for k in ("tv", "fm", "studio")):
            _crm_say("⭐ Open the TV, FM or Studio library + "
                     "select edits first")
            return
        sel = eagle.selected_items()
        if not sel:
            _crm_say("⭐ Nothing selected in Eagle")
            return
        by_base = {}
        for it in sel:
            # ONE parser (eagle.item_base) - the old split(" • ")[0] read
            # a base containing " • " as just its first word and would
            # file a whole tattoo onto a shelf named after the client.
            base, _stage, _n = eagle.item_base(it.get("name") or "")
            if base:
                by_base.setdefault(base, []).append(it["id"])
        if not by_base:
            _crm_say("⭐ Names carry no '{C} - {T} • …' base")
            return
        for base, ids in by_base.items():
            eagle.add_to_folders(ids, [_portfolio_folder(eagle, base)])
    except eagle.EagleError as e:
        _crm_say(f"⭐ {e}")
        return
    tot = sum(len(v) for v in by_base.values())
    _crm_say(f"⭐ {tot} → Portfolio · {', '.join(sorted(by_base))}")


def content_posted(tid):
    """📤 Posted: this tattoo's '• Edit •' items leave the flat 03 Post
    shelf - Portfolio members survive there, shelf-only items go to
    Eagle TRASH (recoverable). Task completes; Raw material is
    untouched (round 2 = fresh promote)."""
    import areas
    import crm_records as cr
    t = cache_store.find_task(tid)
    if not t:
        _crm_say("Not found · run tsy")
        return
    pid = t.get("_projectId") or t.get("projectId")
    base = _task_base(t.get("title") or "")
    lib = next((k for k, v in areas.CONTENT_DESTS.items()
                if v[0] == pid), "fm")
    import eagle
    try:
        eagle.ensure_library(lib)
        cp_kids = _cp_folders(eagle)
        tpost_id = cp_kids["Post"]
        data = eagle._raw(f"item/list?limit=400&folders={tpost_id}")
        # exact base, not a prefix: startswith(f"{base} • ") would let a
        # tattoo called "Luka • Anubis" be swept by the task for "Luka"
        mine = [i["id"] for i in (data or [])
                if eagle.item_base(i.get("name") or "")[0] == base]
        kept = trashed = 0
        if mine:
            full = eagle.get_items(mine)
            keep = [f["id"] for f in full
                    if len([x for x in (f.get("folders") or [])
                            if x != tpost_id])]
            drop = [f["id"] for f in full if f["id"] not in set(keep)]
            if keep:
                eagle.remove_from_folders(keep, [tpost_id])
            if drop:
                eagle.trash_items(drop)
            kept, trashed = len(keep), len(drop)
    except eagle.EagleError as e:
        _crm_say(f"📤 {e}")
        return
    api = cr._api()
    api.complete_task(pid, tid)
    _complete_cache_patch(pid, tid)
    _crm_say(f"📤 {base} posted · {kept} kept in Portfolio · "
             f"{trashed} → Eagle trash")


def content_retire(tid):
    """➖ Retire a 📸Raw task: completes it + flips the logbook 🎬 to ➖
    in one stroke."""
    import areas
    import crm_records as cr
    t = cache_store.find_task(tid)
    if not t:
        _crm_say("Not found · run tsy")
        return
    pid = t.get("_projectId") or t.get("projectId")
    api = cr._api()
    api.complete_task(pid, tid)
    _complete_cache_patch(pid, tid)
    hit = cr.parse_first_link(t.get("content") or "")
    if hit:
        try:
            live = api.get_task(areas.RECORDS_ID, hit[2])
            fresh = cr._fresher_content(hit[2], live.get("content") or "")
            new = cr.set_content_dest(fresh, "-")
            api.update_task(hit[2], areas.RECORDS_ID, current=live,
                            content=new)
            _patch_content_cache(hit[2], new)
        except Exception:
            pass
    _crm_say(f"➖ {_task_base(t.get('title') or '')} retired from content")


def eagle_open(rest):
    """↗️ Open an Eagle folder cross-library: switch first, then the
    deep link (raw eagle:// clicks can't switch - this row always can)."""
    lib, _, fid = rest.partition(":")
    import eagle
    # the row only GUESSES the library (Raw rows say crm); the migrated
    # homes live in TV/FM, so find the folder on disk first - one
    # metadata read per library, no switch to look (2026-09-07)
    lib = eagle.lib_of_folder(fid, prefer=lib) or lib
    try:
        eagle.ensure_library(lib)
    except eagle.EagleError as e:
        _crm_say(f"🦅 {e}")
        return
    subprocess.run(["open", f"eagle://folder/{fid}"], capture_output=True)


def note_go(tid):
    """↗️ Open a records note in TickTick - the ⌥⇧ chord on record
    rows (2026-07-26 inversion: ⏎ drills, ⌥⇧ opens; the plain ⌥ edge
    cannot execute args)."""
    import areas
    t = cache_store.find_task(tid)
    pid = ((t or {}).get("_projectId") or (t or {}).get("projectId")
           or areas.RECORDS_ID)
    open_task(pid, tid)


def eagle_sweep():
    """🦅 Backtrack: create Eagle skeletons for every ACTIVE logbook
    still missing its 🦅 line. One switch, N folders."""
    if not _records_ready():
        return
    import areas
    import crm_records as cr
    lbs = cr.records_notes(areas.LOGBOOK_TAG)
    missing = [lb for lb in lbs
               if not cr.eagle_folder_of(lb.get("content") or "")[0]]
    # Re-filing runs on BOTH paths. It used to sit only after the
    # skeleton loop, so a library with nothing missing returned early
    # and never re-filed anything (Vex smoke 2026-07-28: "folder did
    # not move. None did").
    moved, cands, err = _archive_refile()

    def _tail():
        if err:
            return f" · 🗄 skipped: {err}"
        if moved:
            return f" · 🗄 {moved} archived folder(s) filed"
        if cands:
            return f" · 🗄 all {cands} archived already filed"
        return ""

    if not missing:
        _crm_say(f"🦅 All {len(lbs)} active logbooks already linked"
                 + _tail())
        return
    done = 0
    try:
        for lb in missing:
            _eagle_ensure_logbook_folder(lb)
            done += 1
    except Exception as e:
        _crm_say(f"🦅 {done}/{len(missing)} created, then: {e}")
        return
    _crm_say(f"🦅 {done} skeletons created · {len(lbs) - len(missing)} "
             "were already linked" + _tail())


def _archive_refile():
    """Archived in TickTick but the Eagle folder never moved (Vex smoke
    2026-07-28: 14 of them - backlog import archived the note and left
    the folder under Customers/). Returns (moved, candidates, err) so
    the toast can tell 'nothing to do' apart from 'Eagle was asleep' -
    a bare 0 reads like success and hides a dead sweep."""
    import crm_records as cr
    import eagle
    try:                       # probe ONCE - per-folder failures are mute
        eagle.ensure_running(launch=False)
        eagle.ensure_library("crm")
    except eagle.EagleError as e:
        return 0, 0, str(e)
    import time
    n = cands = 0
    touched = []
    for lb in cr.logbook_notes():
        if not cr.logbook_archived(lb):
            continue
        fid = cr.eagle_folder_of(lb.get("content") or "")[0]
        if not fid:
            continue
        cands += 1
        try:
            if _eagle_archive_folder(lb["id"], quiet=True):
                n += 1
                touched.append(fid)
                # Eagle needs a beat to commit a re-parent; firing the
                # next move immediately is what left a folder listed
                # under BOTH parents and wedged its sidebar (Vex smoke
                # 2026-07-28).
                time.sleep(0.4)
        except Exception:
            pass
    _heal_double_parents(touched)
    return n, cands, ""


def _heal_double_parents(fids, parent_id=None):
    """ONE verification pass after a batch of moves: any folder still
    listed under two parents gets its parent re-set, which makes Eagle
    rewrite the entry cleanly (probe-verified 2026-07-28 - the same
    call that raced is the call that repairs it). Cheap: one tree read
    for the whole batch, and a no-op when nothing raced.

    parent_id = where the folder SHOULD live; None keeps the original
    caller's default of CRM's Archive/ (the archive re-file sweep). The
    content libraries have no Archive, so a caller there must pass its
    own target or the pass would silently do nothing."""
    if not fids:
        return 0
    import eagle
    try:
        tree = eagle.folder_tree()
    except eagle.EagleError:
        return 0
    seen = {}

    def walk(nodes, parent=None):
        for f in nodes:
            seen.setdefault(f.get("id"), []).append(parent)
            walk(f.get("children") or [], f.get("id"))
    walk(tree)
    if parent_id is None:
        arch = eagle.find_folder("Archive", tree=tree)
        if not arch:
            return 0
        parent_id = arch["id"]
    healed = 0
    for fid in set(fids):
        if len(seen.get(fid) or []) > 1:
            try:
                eagle.move_folder(fid, parent_id)
                time.sleep(0.4)
                healed += 1
            except Exception:
                pass
    return healed


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
    """🔗 Link an existing calendar task to a logbook: the title is REPLACED
    by the convention - [logbook](link) S<n>/Consult - making it a records
    session task. The old hand-title is dropped (Vex ruling 2026-07-20); the
    logbook name carries the identity, task content/images stay untouched."""
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
        quoted = _ask(f"{tattoo} - quoted price? (OK or Esc skips)") or ""
        lb = cr.create_logbook(cust, tattoo, quoted=quoted)
        content_dest(lb["id"], mandatory=True)   # born classified (Vex rule)
    else:
        lb = next((l for l in lbs if (l.get("title") or "") == pick), None)
        if lb is None:
            _crm_say("Logbook not found")
            return
    n = cr.next_snum(lb.get("content") or "", lb["id"])
    mk = _dialog("Link as?", ["Other S#…", "Consult", f"S{n}"], f"S{n}")
    if mk == "":
        _crm_say("Cancelled")
        return
    if mk == "Other S#…":
        # Adopting mid-project (Lisa case: sessions 1-2 pre-date the logbook,
        # the task is S3) - the next-number default can't know that.
        raw = _ask("Session number? (e.g. 3)")
        num = (raw or "").strip().lstrip("sS")
        if not num.isdigit() or int(num) < 1:
            _crm_say("Cancelled · not a number")
            return
        mk = f"S{int(num)}"
    api = cr._api()
    live = api.get_task(pid, tid)
    link = cr.task_link(areas.RECORDS_ID, lb["id"], lb.get("title") or "")
    new_title = f"{link} {mk}"
    # priority 5: every CRM calendar task is high priority (same ruling the
    # dispatch create hook enforces for new adds).
    api.update_task(tid, pid, current=live, title=new_title, priority=5)
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
    # Adopting an old task forks three ways (Vex ruling 2026-07-20):
    #   Happened          - the backlog case: log it, complete it, offer next
    #   Not yet - schedule - an UPCOMING session (Lisa S3): task stays open,
    #                        straight into the schedule picker
    #   Just link / Esc   - the link stands, nothing else happens
    ans = _dialog(f"🔗 Linked · {lb.get('title')} {mk} - session already "
                  "happened?", ["Just link", "Not yet - schedule", "Happened"],
                  "Happened")
    if ans == "Happened":
        when = _ask_date("When was it? (OK = today)")
        if when == "CANCEL":
            _crm_say(f"🔗 Linked · {lb.get('title')} {mk} · logging skipped")
            return
        sessiondone(pid, tid, when=when)
        return
    if ans == "Not yet - schedule":
        try:
            with open("/tmp/ticktick_reattribute.txt", "w") as f:
                f.write(f"{pid}:{tid}")
            _run_trigger("attributeScheduling")
        except OSError:
            reopen_actions(pid, tid)
        return
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
        r = _osa_dialog(osa)
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
    msg = _pn().append_income(spec.get("amount") or 0, spec.get("label") or "")
    print(msg)
    # The add-to-today route discards stdout - banner or the log is silent.
    try:
        _notify_banner(msg)
    except Exception:
        pass


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
    bridge_said = ""
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
        elif key == "bridge":
            # surfaced in the final banner - a swallowed bridge failure
            # would smile "saved 5/5" while the board got nothing
            bridge_said = bridge_from_answer(a, day0)
            routed.append(bridge_said)
        answers[n] = a
    filled = pe.journal_merge(slot, answers, period=jper) if answers else 0
    done_now = (total - len(open_pairs)) + filled
    bits = [f"{emoji} {label} saved {done_now}/{total}"]
    if bridge_said:
        bits.append(bridge_said)
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


def open_task(pid, tid):
    """Plain deep link to a task (⌘ chord on the picker's subtask rows).
    Silent - the app opening IS the feedback."""
    subprocess.run(["open", f"ticktick:///webapp/#p/{pid}/tasks/{tid}"],
                   check=False)


def view_buffer(key):
    """🅿️ Buffer all: a whole scope's tasks → the buffer (dedupe, view
    order kept). The buffer is the universal bulk gateway - complete /
    move / tag / priority / delete / focus / date verbs all loop it."""
    tasks, label = _view_tasks(key)
    if tasks is None:
        print(f"View {key!r} can't be buffered")
        return
    lines = buffer_ids()
    have = set(lines)
    added = 0
    for t in tasks:
        pid = t.get("projectId") or t.get("_projectId", "")
        k = f"{pid}:{t.get('id')}"
        if t.get("id") and k not in have:
            lines.append(k)
            have.add(k)
            added += 1
    _write_buffer(lines)
    print(f"🅿️ {added} from {label} buffered · {len(lines)} in buffer")


def _shift_dates(t, delta_days):
    """startDate/dueDate shifted by whole days - wall-clock time survives,
    so all-day stays all-day (_is_all_day sees the same local midnight)
    and timed keeps its hour. Tolerates both '.000+0000' (cache/server)
    and bare '+0000' stamps."""
    out = {}
    for f in ("startDate", "dueDate"):
        v = t.get(f)
        if not v:
            continue
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(v, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None      # unparseable stamp - skip the whole task
        out[f] = (dt + timedelta(days=delta_days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000+0000")
    return out or None


def _date_bulk_pool(key):
    """(tasks, label, repeating_kept, crm_kept) - a date-bulk scope with
    the two hard exemptions: repeating tasks (the date IS the recurrence -
    clearing kills the series, shifting re-anchors it unverified) and the
    CRM calendar list (bookings are records the CRM math reads)."""
    tasks, label = _view_tasks(key)
    if tasks is None:
        return None, key, 0, 0
    import areas
    keep, rep, crm = [], 0, 0
    for t in tasks:
        pid = t.get("projectId") or t.get("_projectId", "")
        if areas.CRM_ID and pid == areas.CRM_ID:
            crm += 1
        elif t.get("repeatFlag"):
            rep += 1
        elif t.get("startDate") or t.get("dueDate"):
            keep.append(t)
    return keep, label, rep, crm


def _date_bulk_run(tasks, fields_fn):
    """Pooled updates: fields_fn(task) → update fields (None skips).
    → (done, failed). Cache mirrored per task."""
    from concurrent.futures import ThreadPoolExecutor
    from dispatch import _patch_task_cache

    def _one(t):
        try:
            fields = fields_fn(t)
            if not fields:
                return None
            pid = t.get("projectId") or t.get("_projectId", "")
            _api().update_task(t["id"], pid, current=t, **fields)
            _patch_task_cache(t["id"], **fields)
            return t["id"]
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
        done = [r for r in pool.map(_one, tasks) if r]
    return len(done), len(tasks) - len(done)


def _exempt_bits(rep, crm):
    bits = ""
    if rep:
        bits += f" · {rep} repeating kept"
    if crm:
        bits += f" · {crm} CRM kept"
    return bits


def dateclear(key):
    """📅 Clear all dates on a scope (Overdue's date bankruptcy): the tasks
    survive and sink back into their lists as dateless backlog. ONE
    confirm; repeating + CRM-calendar tasks are exempt."""
    tasks, label, rep, crm = _date_bulk_pool(key)
    if tasks is None:
        print(f"View {key!r} can't be date-cleared")
        return
    if not tasks:
        print(f"📅 Nothing to clear in {label}" + _exempt_bits(rep, crm))
        return
    n = len(tasks)
    if _dialog(f"Clear dates on {n} {label} task{'s' if n != 1 else ''}?\n\n"
               "They stay in their lists, dateless."
               + (f"\nExempt:{_exempt_bits(rep, crm)}" if rep or crm else ""),
               ["Cancel", "Clear"], "Clear") != "Clear":
        print("📅 Dates kept")
        return
    done, failed = _date_bulk_run(
        tasks, lambda t: {"startDate": None, "dueDate": None})
    msg = f"📅 {done} cleared" + _exempt_bits(rep, crm)
    if failed:
        msg += f" · {failed} failed"
    if key == "buffer" and not failed:
        _write_buffer([])           # house rule: a buffer bulk clears it
        msg += " · buffer cleared"
    print(msg)


def dateroll(key):
    """⏭️ Roll a scope's tasks to today: each task's whole span shifts by
    whole days so its day lands TODAY - hour and duration survive, all-day
    stays all-day. Same exemptions as dateclear."""
    from filtering import task_local_date
    tasks, label, rep, crm = _date_bulk_pool(key)
    if tasks is None:
        print(f"View {key!r} can't be rolled")
        return
    today = datetime.now().date()
    tasks = [t for t in tasks if task_local_date(t)
             and task_local_date(t) != today.isoformat()]
    if not tasks:
        print(f"⏭️ Nothing to roll in {label}" + _exempt_bits(rep, crm))
        return
    n = len(tasks)
    if _dialog(f"Roll {n} {label} task{'s' if n != 1 else ''} to today?\n\n"
               "Times and durations survive."
               + (f"\nExempt:{_exempt_bits(rep, crm)}" if rep or crm else ""),
               ["Cancel", "Roll"], "Roll") != "Roll":
        print("⏭️ Dates kept")
        return

    def _fields(t):
        d = task_local_date(t)
        delta = (today - datetime.strptime(d, "%Y-%m-%d").date()).days
        return _shift_dates(t, delta) if delta else None

    done, failed = _date_bulk_run(tasks, _fields)
    msg = f"⏭️ {done} rolled to today" + _exempt_bits(rep, crm)
    if failed:
        msg += f" · {failed} failed"
    if key == "buffer" and not failed:
        _write_buffer([])           # house rule: a buffer bulk clears it
        msg += " · buffer cleared"
    print(msg)


def inboxempty():
    """🗑️ Empty Inbox (the Inbox view's ⌘ menu): every OPEN inbox item →
    TickTick's Trash, ONE confirm dialog first. Trash keeps them
    recoverable - a move, not a purge; completed history stays. LIVE
    project-data read, not cache - emptying the inbox is mostly about
    fresh captures the hourly cache hasn't seen."""
    api = _api()
    data = api.get_project_data("inbox")   # literal id, API-accepted
    tasks = list(data.get("tasks") or [])
    n = len(tasks)
    if not n:
        print("📥 Inbox is already empty")
        return
    if _dialog(f"Delete {n} inbox task{'s' if n != 1 else ''}?\n\n"
               "They land in TickTick's Trash (recoverable).",
               ["Cancel", "Delete"], "Delete") != "Delete":
        print("📥 Inbox kept")
        return
    # children first - a parent delete cascades, and the child's own delete
    # would then 404 into the failed count
    tasks.sort(key=lambda t: 0 if t.get("parentId") else 1)

    def _del(t):
        try:
            _api().delete_task(t.get("projectId") or "inbox", t["id"])
            return t["id"]
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, n)) as pool:
        gone = {r for r in pool.map(_del, tasks) if r}
    try:
        cache_store.set("project_data_inbox",
                        dict(data, tasks=[t for t in tasks
                                          if t["id"] not in gone]))
        for key in ("all_tasks", "all_notes"):
            cached = cache_store.get(key)
            if cached is not None:
                cache_store.set(key, [t for t in cached
                                      if t.get("id") not in gone])
    except Exception:
        cache_store.invalidate("all_tasks")
    left = n - len(gone)
    msg = f"🗑️ {len(gone)} → Trash · Inbox emptied"
    if left:
        msg = f"🗑️ {len(gone)} → Trash · {left} refused, retry"
    print(msg)


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


def pomo_sticky(pid, tid, minutes):
    """Sticky note on the desktop + TickTick pomodoro on the task."""
    if sticky(pid, tid):
        if pomo(minutes):
            _pomo_attribute(pid, tid, _task_title(tid))


# ── View/tag collectors - feed view_focus / view_buffer / date bulks ─────────
def _view_tasks(key):
    """Ordered open tasks of a scope → (tasks, label) - used by the focus
    send, buffer-all and the date bulks. 'buffer' resolves the parked ids
    through the cache."""
    from filtering import smart_filter
    all_tasks = cache_store.get("all_tasks") or []
    labels = {"today": "Today", "tomorrow": "Tomorrow",
              "next7": "Next 7 Days", "inbox": "Inbox",
              "overdue": "Overdue", "buffer": "the buffer"}
    if key in ("today", "tomorrow", "next7", "overdue"):
        kind = {"today": "today", "tomorrow": "tomorrow",
                "next7": "next7days", "overdue": "overdue"}[key]
        tasks = smart_filter(all_tasks, kind)
        if key in ("today", "tomorrow"):   # time order, like the app's view
            tasks = sorted(tasks, key=lambda t: (t.get("startDate")
                                                 or t.get("dueDate") or "~"))
    elif key == "inbox":
        data = cache_store.get("project_data_inbox") or {}
        tasks = [t for t in data.get("tasks", [])
                 if t.get("status", 0) == 0 and not t.get("parentId")]
    elif key == "buffer":
        tasks = []
        for ln in buffer_ids():
            pid, tid = ln.split(":", 1)
            t = cache_store.find_task(tid)
            if t:
                tasks.append(t)
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


# ── Focus staging verbs (subtasks - NOTE targets keep the checkbox path) ─────

def _cache_children(ttid):
    """Open children of a task, cache view - fresh for our own writes via
    the mirror; app-side staging lags one sync. Only feeds sortOrder
    placement, so staleness costs a misplaced row at worst."""
    return [t for t in (cache_store.get("all_tasks") or [])
            if t.get("parentId") == ttid and t.get("status", 0) == 0]


def _stage_into(tpid, ttid, items):
    """The staging engine: MOVE items = [(pid, tid, title)] under the task
    ttid as literal subtasks. Cross-list = v1 move first, THEN the v1
    parent-set (one update can't do both, and v1 can never detach - both
    live-verified 2026-07-21). sortOrder stamps append at the BOTTOM of the
    child list in item order. The origins ledger records each task's old
    home so fx_unstage can send it back. → (staged, skipped, failed)."""
    def _lk(t):
        # hybrid lookup for the cycle walk: cache, else live (fresh anchors
        # aren't cached - and the SERVER ACCEPTS a real parent loop,
        # live-verified, so this guard is the only thing preventing one)
        c = cache_store.find_task(t)
        if c:
            return c
        try:
            return _api().get_task(tpid, t)
        except Exception:
            return None

    todo, skipped = [], 0
    for pid, tid, title in items:
        known = cache_store.find_task(tid)
        if (not tid or tid == ttid
                or (known and known.get("parentId") == ttid)
                or fsub.would_cycle(ttid, tid, _lk)):
            skipped += 1
            continue
        todo.append((pid, tid, title))
    if not todo:
        return 0, skipped, 0
    orders = fsub.stage_orders(
        [t.get("sortOrder") or 0 for t in _cache_children(ttid)], len(todo))

    def _one(job):
        (pid, tid, _title), so = job
        try:
            api = _api()
            live = api.get_task(pid, tid)
            if live.get("parentId") == ttid:
                return "skip"          # already staged (cache was blind)
            fields = {"parentId": ttid, "sortOrder": so}
            if pid != tpid:
                api.move_task(tid, pid, tpid)
                fields["columnId"] = None   # the old list's section id
            api.update_task(tid, tpid, current=live, **fields)
            return tid, pid, live.get("parentId"), so
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(todo))) as pool:
        results = list(pool.map(_one, zip(todo, orders)))
    skipped += sum(1 for r in results if r == "skip")
    ok = [r for r in results if r and r != "skip"]
    failed = len(results) - len(ok) - sum(1 for r in results if r == "skip")
    if ok:
        _origins_update(add={tid: {"pid": pid, "parent": old_parent}
                             for tid, pid, old_parent, _so in ok})
        try:
            from dispatch import _patch_task_cache
            lname = next((p.get("name", "") for p in
                          (cache_store.get("projects") or [])
                          if p.get("id") == tpid), "")
            for tid, pid, _old, so in ok:
                fields = {"parentId": ttid, "sortOrder": so}
                if pid != tpid:
                    fields.update(projectId=tpid, _projectId=tpid,
                                  _projectName=lname,
                                  columnId=None, _columnName="")
                _patch_task_cache(tid, **fields)
        except Exception:
            cache_store.invalidate("all_tasks")
        app_sync_after_write()
    return len(ok), skipped, failed


def _target_kind(tpid, ttid):
    """TEXT/NOTE of a stage target - cache first, live fallback (a NOTE
    can't parent tasks, so it keeps the checkbox grammar)."""
    t = cache_store.find_task(ttid)
    if t and t.get("kind"):
        return t["kind"]
    try:
        return _api().get_task(tpid, ttid).get("kind") or "TEXT"
    except Exception:
        return "TEXT"


def fx_add(pid, tid, open_sticky=False):
    """Stage the task UNDER the current focus task - a literal subtask (the
    task MOVES; fx_unstage sends it home). ⌥ variant also opens the focus
    task's sticky."""
    cur = _current_focus_task()
    if not cur:
        print("🎯 No task-linked session running · start or link one first")
        return
    fpid, ftid, ftitle = cur
    if tid == ftid:
        print("🎯 That IS the focus task")
        return
    title = _task_title(tid, pid=pid)
    staged, _skipped, failed = _stage_into(fpid, ftid, [(pid, tid, title)])
    if staged:
        print(f"🎯 {title[:40]} → {ftitle[:30]}")
    elif failed:
        print("🎯 Staging failed · sync and retry")
    else:
        print(f"🎯 already under {ftitle[:30]}")
    if open_sticky:
        sticky(fpid, ftid)


def fx_add_to(tpid, ttid, spid, stid):
    """Stage a source task under an EXPLICIT target (the Stage-for-Focus
    'Out' direction). Task target = literal subtask; NOTE target keeps the
    checkbox-block line (a CTA note can't parent tasks)."""
    if ttid == stid:
        print("🎯 Can't stage a task into itself")
        return
    title = _task_title(stid, pid=spid)
    if _target_kind(tpid, ttid) == "NOTE":
        (added, _skipped), _doc, live = _fx_rmw(
            tpid, ttid,
            lambda doc, today: fb.insert_checkboxes(doc, today,
                                                    [(spid, stid, title)]))
        tname = live.get("title") or "target"
        print(f"🎯 {title[:40]} → {tname[:30]}" if added
              else f"🎯 already staged today in {tname[:30]}")
        return
    tname = _task_title(ttid, default="target", pid=tpid)
    staged, _skipped, failed = _stage_into(tpid, ttid, [(spid, stid, title)])
    if staged:
        print(f"🎯 {title[:40]} → {tname[:30]}")
    elif failed:
        print("🎯 Staging failed · sync and retry")
    else:
        print(f"🎯 already under {tname[:30]}")


def fx_add_multi(b64):
    """Batch stage under the S3 'In' target. Task target = subtasks (pooled
    move+parent per item); NOTE target = checkbox lines, ONE content write.
    b64 JSON: {"tpid","ttid","items":[[pid,tid,title],…]}."""
    import base64
    data = json.loads(base64.b64decode(b64))
    tpid, ttid = data["tpid"], data["ttid"]
    items = [(p, t, ti) for p, t, ti in data.get("items", []) if t != ttid]
    if not items:
        print("🎯 Nothing to stage")
        return
    if _target_kind(tpid, ttid) == "NOTE":
        (added, skipped), _doc, live = _fx_rmw(
            tpid, ttid,
            lambda doc, today: fb.insert_checkboxes(doc, today, items))
        tname = live.get("title") or "target"
        msg = f"🎯 {added} staged → {tname[:30]}"
        if skipped:
            msg += f" · {skipped} already there"
        print(msg)
        return
    tname = _task_title(ttid, default="target", pid=tpid)
    staged, skipped, failed = _stage_into(tpid, ttid, items)
    msg = f"🎯 {staged} staged → {tname[:30]}"
    if skipped:
        msg += f" · {skipped} already there"
    if failed:
        msg += f" · {failed} failed"
    print(msg)


def fx_tick(pid, tid, ctid=None):
    """COMPLETE the first open subtask (or ctid) of the focus task - ticks
    are real completions now, so there is no sweep step anymore.
    TICKAL_JSON=1 → children_summary JSON on stdout (the focus bar's
    reconcile channel); otherwise a human toast."""
    as_json = os.environ.get("TICKAL_JSON") == "1"
    try:
        open_children, child_ids = _children_state(pid, tid)
        ordered = sorted(open_children, key=lambda t: t.get("sortOrder") or 0)
        if ctid:
            target = next((t for t in ordered if t.get("id") == ctid), None)
        else:
            target = ordered[0] if ordered else None
        done_titles = {}
        plog = ""
        if target:
            cpid = target.get("projectId") or pid
            _api().complete_task(cpid, target["id"])
            _complete_cache_patch(cpid, target["id"])
            plog = person_autolog(target["id"], target)
            open_children = [t for t in open_children
                             if t.get("id") != target["id"]]
            if target["id"] not in child_ids:
                child_ids = child_ids + [target["id"]]
            done_titles[target["id"]] = target.get("title", "")
        summary = fsub.children_summary(open_children, child_ids, done_titles)
        if as_json:
            print(json.dumps({"ok": True, "ticked": bool(target), **summary}))
        elif target:
            print(f"✅ done: {target.get('title', '')[:50]}{plog}")
        else:
            print("Nothing open to tick")
    except Exception as e:
        if as_json:
            print(json.dumps({"ok": False,
                              "error": f"{type(e).__name__}: {e}"}))
        else:
            raise


def fx_sweep(pid=None, tid=None):
    """RETIRED by the subtask revamp - ticking a subtask completes it for
    real, so there is nothing left to sweep. Stub keeps stale UI args calm."""
    print("🧹 Sweep retired · ticking a subtask completes it for real")


def fx_unstage(pid, tid):
    """Remove from focus: v2 detach (the ONLY channel that clears parentId -
    v1 ignores null), then send the task home per the origins ledger (move
    back cross-list, re-adopt by its old parent). No ledger entry = detach
    in place. Order is sacred: detach BEFORE any move - a moved child keeps
    a stale cross-project parent link otherwise (live-verified)."""
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception:
        print("➖ Task not found · sync and retry")
        return
    title = (live.get("title") or _title())[:40]
    parent = live.get("parentId")
    if not parent:
        _origins_update(drop=tid)
        print(f"➖ {title} is not staged")
        return
    import api_v2
    v2 = api_v2.TickTickV2()
    if not v2.token:
        print("➖ Remove needs the Attachment Login token (Settings)")
        return
    if not v2.task_parent([{"taskId": tid, "projectId": pid,
                            "oldParentId": parent}]):
        print(f"➖ TickTick refused to detach {title} · retry")
        return
    origin = _origins_update(drop=tid) or {}
    dest_pid = origin.get("pid") or pid
    if dest_pid != pid:
        try:
            api.move_task(tid, pid, dest_pid)
        except Exception:
            dest_pid = pid          # detached but stuck here - stay honest
    applied_parent = None
    if origin.get("parent") and dest_pid == origin.get("pid"):
        try:
            # `live` from BEFORE the move - a fresh GET from the new project
            # races replication (empty-200); the full-object post with the
            # projectId/parentId overrides is what counts
            api.update_task(tid, dest_pid, current=live,
                            parentId=origin["parent"])
            applied_parent = origin["parent"]
        except Exception:
            pass
    lname = next((p.get("name", "") for p in
                  (cache_store.get("projects") or [])
                  if p.get("id") == dest_pid),
                 "Inbox" if dest_pid.startswith("inbox") else "")
    try:
        from dispatch import _patch_task_cache
        fields = {"parentId": applied_parent}
        if dest_pid != pid:
            fields.update(projectId=dest_pid, _projectId=dest_pid,
                          _projectName=lname, columnId=None, _columnName="")
        _patch_task_cache(tid, **fields)
    except Exception:
        cache_store.invalidate("all_tasks")
    app_sync_after_write()
    if dest_pid != pid:
        home = lname or "its list"
        print(f"➖ {title} → back to {home}")
    else:
        print(f"➖ {title} unstaged")


def fx_oneliner():
    """✏️ One-liner: dialog → '- text' bullet appended to the focus task's
    CONTENT - the note is free again now that staging is subtasks."""
    cur = _current_focus_task()
    if not cur:
        print("✏️ No task-linked session running")
        return
    fpid, ftid, ftitle = cur
    text = " ".join((_ask(f"One line for {ftitle[:30]}") or "").split())
    if not text:
        return   # cancelled or empty - silence, not an error toast
    api = _api()
    live = api.get_task(fpid, ftid)
    old = live.get("content") or ""
    new = (old.rstrip("\n") + "\n" if old.strip() else "") + "- " + text
    api.update_task(ftid, fpid, current=live, content=new)
    _patch_content_cache(ftid, new)
    app_sync_after_write()
    print(f"✏️ noted on {ftitle[:30]}")


def fx_copy(pid=None, tid=None):
    """Open subtasks of the focus task → clipboard as a paste-ready
    "- Title" bullet list (done ones are history, not a to-paste list)."""
    if not (pid and tid):
        cur = _current_focus_task()
        if not cur:
            print("📋 No task-linked session running")
            return
        pid, tid = cur[0], cur[1]
    open_children, _cids = _children_state(pid, tid)
    ordered = sorted(open_children, key=lambda t: t.get("sortOrder") or 0)
    if not ordered:
        print("📋 No open subtasks")
        return
    text = "\n".join("- " + " ".join((t.get("title") or "(untitled)").split())
                     for t in ordered)
    subprocess.run(["pbcopy"], input=text.encode())
    print(f"📋 {len(ordered)} subtask{'s' if len(ordered) != 1 else ''}"
          " copied as bullets")


def _task_copy_block(t, full):
    """'- [ ] Title' (+ '> description' blockquote lines when full) - the
    clipboard shape Vex ruled (2026-07-24; checkbox re-rule same day).
    Completed tasks paste ticked; NOTE items keep a plain title."""
    title = " ".join((t.get("title") or "").split()) or "(untitled)"
    if (t.get("kind") or "").upper() != "NOTE":
        box = "- [x] " if t.get("status", 0) == 2 else "- [ ] "
        title = box + title
    if not full:
        return title, False
    desc = (t.get("content") or "").strip()
    if not desc:
        return title, False
    quoted = "\n".join(f"> {ln}" if ln.strip() else ">"
                       for ln in desc.splitlines())
    return f"{title}\n{quoted}", True


def task_copy(pid, tid, full=False):
    """📋 ⌘ Actions: task name → clipboard; full=True adds the
    description as a '>' blockquote. Cache first, live GET on miss."""
    t = cache_store.find_task(tid)
    if not t or (full and not (t.get("content") or "").strip()):
        try:
            t = _api().get_task(pid, tid)
        except Exception:
            t = t or {}
    if not t:
        _crm_say("📋 Task not found · nothing copied")
        return
    text, had_desc = _task_copy_block(t, full)
    subprocess.run(["pbcopy"], input=text.encode())
    title = " ".join((t.get("title") or "").split())[:40]
    if full and not had_desc:
        _crm_say(f"📋 No description · name copied · {title}")
    else:
        _crm_say("📋 Copied" + (" with description" if full else "")
                 + f" · {title}")


def buffer_copy(full=False):
    """📋 Buffer batch: every buffered task as a block, joined with
    single newlines (Vex 2026-07-25: blank separator lines were weird
    in practice - a pasted batch should read as one tight checklist)."""
    from display import buffer_pairs
    pairs = buffer_pairs()
    if not pairs:
        _crm_say("🅿️ Buffer empty · nothing copied")
        return
    chunks = []
    for pid, tid in pairs:
        t = cache_store.find_task(tid)
        if not t:
            continue
        chunks.append(_task_copy_block(t, full)[0])
    if not chunks:
        _crm_say("🅿️ Buffer empty · nothing copied")
        return
    subprocess.run(["pbcopy"], input="\n".join(chunks).encode())
    _crm_say(f"📋 {len(chunks)} task{'s' if len(chunks) != 1 else ''} "
             "copied" + (" with descriptions" if full else ""))


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
        st.update({"pid": pid, "tid": tid, "title": title,
                   "done0": _done_children_snapshot(pid, tid)})
        _write_focus(st)
    else:
        state, _ = _pomo_app_state()
        if state == "idle":
            print("🔗 No running session to link")
            return
        _write_pomo({"pid": pid, "tid": tid, "title": title,
                     "start": _now_iso(), "pomo_start": _pomo_timeline_start()})
    _bar_wake()
    print(f"🔗 {title[:40]} linked to the running session")


def _fx_send(items, label):
    """Stage [(pid,tid,title)] under the current focus task (subtasks).
    True when anything staged."""
    cur = _current_focus_task()
    if not cur:
        print("🎯 No task-linked session running · start or link one first")
        return False
    fpid, ftid, ftitle = cur
    items = [(p, t, ti) for p, t, ti in items if t != ftid]
    if not items:
        print(f"Nothing in {label} to add")
        return False
    staged, skipped, failed = _stage_into(fpid, ftid, items)
    msg = f"🎯 {staged} from {label} → {ftitle[:30]}"
    if skipped:
        msg += f" · {skipped} already there"
    if failed:
        msg += f" · {failed} failed"
    print(msg)
    # buffer_focus clears the buffer on True - a failure keeps it for retry,
    # all-already-there still clears (nothing left to send)
    return not failed and bool(staged or skipped)


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


# ── 🌉 Bridges (daily board + per-project handoff notes) ─────────────────────
# Model in src/bridges.py. Daily bridges: ONE home list (areas.BRIDGES_ID,
# kanban by YYMM month tag). Project bridges: NOTE in the project's own list,
# tagged 🌉bridge. Surface: browse ctx:bridges. Evening journal routes its
# 🌉 prompt here (bridge_from_answer).

def _pbpaste():
    try:
        r = subprocess.run(["pbpaste"], capture_output=True)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _list_name_of(pid):
    for p in (cache_store.get("projects") or []):
        if p.get("id") == pid:
            return p.get("name") or ""
    return ""


def _bridge_inject_cache(task, pid, list_name):
    """Generic twin of crm_records._inject_cache (that one is records-bound):
    a fresh note shows in search/browse NOW, not at the next hourly sync."""
    try:
        entry = dict(task)
        entry["_projectId"] = pid
        entry["_projectName"] = list_name
        entry["tags"] = [str(t).lower() for t in (task.get("tags") or [])]
        for key, newest_first in (("all_notes", True), ("all_tasks", False)):
            pool = [t for t in (cache_store.get(key) or [])
                    if t.get("id") != task.get("id")]
            pool.insert(0, entry) if newest_first else pool.append(entry)
            cache_store.set(key, pool)
        # project_data mirror too - per-list browse drills read THAT, not
        # all_tasks (dispatch._patch_project_data's law; review catch)
        pd_key = f"project_data_{pid}"
        pd = cache_store.get(pd_key)
        if pd is not None:
            pd = dict(pd)
            pd["tasks"] = [t for t in pd.get("tasks", [])
                           if t.get("id") != task.get("id")] + [entry]
            cache_store.set(pd_key, pd)
    except Exception:
        pass


def _bridge_month_tag(day):
    """Ensure the YYMM month tag ('2607') exists. '' when v2 is unavailable -
    the bridge still saves, just tagless (board files it under No tag)."""
    import bridges as br
    tag = br.month_tag(day)
    try:
        from display import tag_match_key
        known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
        if tag_match_key(tag) in known:
            return tag
        import api_v2
        v2 = api_v2.TickTickV2()
        if not v2.token or not v2.create_tag(tag):
            return ""
        cache_store.set("tags", (cache_store.get("tags") or []) + [tag])
        tree = cache_store.get("tags_tree")
        if tree is not None:
            cache_store.set("tags_tree", tree + [
                {"name": tag, "label": tag, "parent": None}])
        return tag
    except Exception:
        return ""


def _bridge_feed_tomorrow(text, day):
    """Same text lands where tomorrow-morning eyes go: the NEXT day's daily
    note, ### 🌉 Yesterday's bridge. Old notes lack the header - the section
    is inserted right after ⏪ Yesterday. Defensive: periodic is optional."""
    import areas
    if not (text or "").strip() or not areas.periodic_configured():
        return ""
    try:
        import periodic_model as pm
        import periodic_sections as ps
        pe = _pn()
        nxt = pm.period_for("daily", day + timedelta(days=1))
        task, _ = pe.ensure_note(nxt)
        pid = task.get("projectId") or areas.PERIODIC_LIST_ID
        lines = [(pm.T1 + ln) if ln.strip() else "" for ln in text.splitlines()]

        def mutate(doc, live):
            if ps.find(doc, pm.SEC_YBRIDGE) is None:
                sec = ps.Section(f"### {pm.SEC_YBRIDGE}", pm.SEC_YBRIDGE)
                ysec = ps.find(doc, pm.SEC_YESTERDAY)
                at = (doc.sections.index(ysec) + 1) if ysec \
                    else len(doc.sections)
                doc.sections.insert(at, sec)
            return ps.set_body(doc, pm.SEC_YBRIDGE, lines)
        pe._pn_rmw(pid, task.get("id"), mutate)
        return "⏩ fed tomorrow's note"
    except Exception:
        return ""


def _bridge_capture(skel):
    """(text, kind) - typed beats clipboard beats skeleton. (None, '') on
    Esc. Empty-OK deliberately reaches for the clipboard: write the bridge
    in Claude, copy, OK mints it."""
    a = _ask("🌉 Bridge - write it (empty OK = clipboard · Esc cancels)")
    if a is None:
        return None, ""
    a = a.strip()
    if a:
        return a, "typed"
    clip = _pbpaste()
    if clip:
        return clip, "clipboard"
    return skel, "skeleton"


def _bridge_find(api, pid, title):
    """Today's bridge by EXACT title, LIVE (dupe gate - cache lies after
    cross-device writes). Returns the task, None (definitely absent), or
    "ERR" (couldn't look - mint verbs must NOT create blind; failing open
    minted duplicates, review catch)."""
    try:
        pdata = api.get_project_data(pid) or {}
        return next((t for t in pdata.get("tasks", [])
                     if (t.get("title") or "").strip() == title), None)
    except Exception:
        return "ERR"


def bridge_daily():
    """✍️ Daily bridge: one per day in the 🌉 Bridges board. Exists →
    opens. Skeleton mints open too (there is writing to do)."""
    import bridges as br
    import areas
    if not areas.bridges_configured():
        _crm_say("🌉 Bridges list not configured (Settings)")
        return
    day = datetime.now().date()
    api = _api()
    want = br.daily_title(day)
    hit = _bridge_find(api, areas.BRIDGES_ID, want)
    if hit == "ERR":
        _crm_say("🌉 Can't check today's bridge (offline?) · nothing minted")
        return
    if hit:
        open_task(areas.BRIDGES_ID, hit["id"])
        _crm_say("🌉 Today's bridge exists · opening")
        return
    text, srckind = _bridge_capture(br.DAILY_SKEL)
    if text is None:
        _crm_say("🌉 Cancelled")
        return
    tag = _bridge_month_tag(day)
    t = api.create_task(title=want, project_id=areas.BRIDGES_ID,
                        content=text, tags=[tag] if tag else [],
                        kind="NOTE")
    _bridge_inject_cache(t, areas.BRIDGES_ID, _list_name_of(areas.BRIDGES_ID))
    fed = "" if srckind == "skeleton" else _bridge_feed_tomorrow(text, day)
    if srckind == "skeleton":
        open_task(areas.BRIDGES_ID, t.get("id"))
    bits = ["🌉 Daily bridge saved"]
    if tag:
        bits.append(f"#{tag}")
    if srckind == "clipboard":
        bits.append("📋 clipboard")
    if srckind == "skeleton":
        bits.append("opening to write")
    if fed:
        bits.append(fed)
    _crm_say(" · ".join(bits))
    app_sync_after_write()


def bridge_from_answer(text, day):
    """Evening journal 🌉 route: the answer IS the bridge - no dialogs.
    Today's already written → the answer appends to it (second thoughts
    stack, they don't collide)."""
    import bridges as br
    import areas
    text = (text or "").strip()
    if not text:
        return ""
    if not areas.bridges_configured():
        # no board, but the tomorrow-note feed only needs periodic
        fed = _bridge_feed_tomorrow(text, day)
        return "🌉 no Bridges list" + (f" · {fed}" if fed else "")
    api = _api()
    want = br.daily_title(day)
    try:
        hit = _bridge_find(api, areas.BRIDGES_ID, want)
        if hit == "ERR":
            hit = None   # journal answers are precious: mint anyway
        if hit:
            live = api.get_task(areas.BRIDGES_ID, hit["id"])
            old = live.get("content") or ""
            new = (old.rstrip() + "\n\n" + text) if old.strip() else text
            api.update_task(hit["id"], areas.BRIDGES_ID, current=live,
                            content=new)
            _patch_content_cache(hit["id"], new)
            _bridge_feed_tomorrow(new, day)
            return "🌉 bridged (appended)"
        tag = _bridge_month_tag(day)
        t = api.create_task(title=want, project_id=areas.BRIDGES_ID,
                            content=text, tags=[tag] if tag else [],
                            kind="NOTE")
        _bridge_inject_cache(t, areas.BRIDGES_ID,
                             _list_name_of(areas.BRIDGES_ID))
        _bridge_feed_tomorrow(text, day)
        return "🌉 bridged"
    except Exception as e:
        return f"🌉 bridge failed: {e}"


def bridge_proj(pid):
    """➕ Project bridge: NOTE in the project's own list, 🌉bridge tag,
    'P • {Project} • Bridge 🌉 date' title. One per list per day."""
    import bridges as br
    if not pid:
        _crm_say("Error: bridge_proj needs a list id")
        return
    day = datetime.now().date()
    lname = _list_name_of(pid)
    want = br.project_title(lname, day)
    api = _api()
    hit = _bridge_find(api, pid, want)
    if hit == "ERR":
        _crm_say("🌉 Can't check today's bridge (offline?) · nothing minted")
        return
    if hit:
        open_task(pid, hit["id"])
        _crm_say("🌉 Today's bridge exists · opening")
        return
    text, srckind = _bridge_capture(br.PROJ_SKEL)
    if text is None:
        _crm_say("🌉 Cancelled")
        return
    t = api.create_task(title=want, project_id=pid, content=text,
                        tags=[br.BRIDGE_TAG], kind="NOTE")
    _bridge_inject_cache(t, pid, lname)
    if srckind == "skeleton":
        open_task(pid, t.get("id"))
    bits = [f"🌉 Bridge saved · {lname or 'list'}"]
    if srckind == "clipboard":
        bits.append("📋 clipboard")
    if srckind == "skeleton":
        bits.append("opening to write")
    _crm_say(" · ".join(bits))
    app_sync_after_write()


def bridge_tidy():
    """🗄️ Old-month collapse: daily bridges from BEFORE last month get
    COMPLETED (live-verified 2026-07-21: a completed NOTE leaves project
    data, so the board's columns stay lean; completed history keeps it).
    Current + previous month always stay. Asks first."""
    import bridges as br
    import areas
    if not areas.bridges_configured():
        _crm_say("🌉 Bridges list not configured")
        return
    api = _api()
    today = datetime.now().date()
    keep = {br.month_tag(today),
            br.month_tag(today.replace(day=1) - timedelta(days=1))}
    try:
        pdata = api.get_project_data(areas.BRIDGES_ID) or {}
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    old = []
    for t in pdata.get("tasks", []):
        if not br.is_daily(t.get("title", "")):
            continue
        d = br.title_date(t.get("title"))
        if d is not None and br.month_tag(d) not in keep:
            old.append(t)
    if not old:
        _crm_say("🗄️ Nothing older than last month")
        return
    if _dialog(f"Complete {len(old)} old daily bridge(s)? "
               "They leave the board · history keeps them",
               ["Cancel", "Complete"], "Complete") != "Complete":
        _crm_say("🗄️ Cancelled")
        return
    done, ids = 0, set()
    for t in old:
        try:
            api.complete_task(areas.BRIDGES_ID, t["id"])
            ids.add(t["id"])
            done += 1
        except Exception:
            pass
    for key in ("all_notes", "all_tasks"):
        pool = cache_store.get(key)
        if pool is not None:
            cache_store.set(key, [x for x in pool
                                  if x.get("id") not in ids])
    from dispatch import _patch_project_data
    for tid in ids:   # list drills read project_data, not all_tasks
        _patch_project_data(tid, pid_old=areas.BRIDGES_ID, remove=True)
    _crm_say(f"🗄️ {done} old bridges off the board")
    app_sync_after_write()


def search_pre(prefix):
    """Jump into Search prefilled with a scope prefix ('bd' → 'bd ') -
    the pn_journal picker-handoff pattern, generalized."""
    _run_trigger("Search", (prefix or "").strip() + " ")


def bridge_setlist():
    """⚙️ Settings → 🌉 Bridges list: paste the home list's id (⌘ Copy id
    on any list row mints it). Saves config bridges_list_id + flips the
    list to kanban (grouping and edit-sort stay one in-app tap - client
    view settings)."""
    import re as _re
    cur = cfg.get_bridges_list_id()
    a = _ask("🌉 Bridges list id (⌘ Copy id on any list · Esc cancels)",
             default=cur)
    if a is None:
        _crm_say("🌉 Cancelled")
        return
    a = a.strip()
    if not _re.fullmatch(r"[0-9a-fA-F]{24}", a or ""):
        _crm_say("🌉 That does not look like a list id · nothing saved")
        return
    data = cfg.load()
    data["bridges_list_id"] = a
    cfg.save(data)
    try:
        _api().update_project(a, viewMode="kanban")
    except Exception:
        pass
    _crm_say(f"🌉 Bridges home set · {_list_name_of(a) or a}")


def bridge_copy(rest):
    """⌥ on a bridge row: title + content → clipboard, ready to paste into
    the next Claude session (the whole point of a bridge)."""
    pid, _, tid = rest.partition(":")
    api = _api()
    t = api.get_task(pid, tid)
    body = f"{t.get('title') or ''}\n\n{t.get('content') or ''}".strip()
    subprocess.run(["pbcopy"], input=body.encode())
    _crm_say("🌉 Bridge copied · paste it to Claude")


# ── 👽 People (cards + CTAs + log) ───────────────────────────────────────────
# Model in src/people.py. A person is a TASK in areas.PEOPLE_ID (CTAs nest
# under it as real schedulable subtasks - notes can't have children), card
# content = 📇 Card / 🎁 Ideas / 🧾 Log sections, kanban by circle tag.
# CTA composing is NOT a verb - the Add window does it natively via the
# ~p parent token (add_pre prefills it; the parent's list is inherited).


def _person_find(api, title):
    """A person card by EXACT title, LIVE (dupe gate - same fail-CLOSED
    contract as _bridge_find: task, None, or "ERR")."""
    import areas
    try:
        pdata = api.get_project_data(areas.PEOPLE_ID) or {}
        return next((t for t in pdata.get("tasks", [])
                     if (t.get("title") or "").strip() == title), None)
    except Exception:
        return "ERR"


def _person_inject_cache(task, pid):
    """Task twin of _bridge_inject_cache (which also feeds all_notes -
    wrong pool for a TASK card): all_tasks + project_data only."""
    try:
        entry = dict(task)
        entry["_projectId"] = pid
        entry["_projectName"] = _list_name_of(pid)
        entry["tags"] = [str(t).lower() for t in (task.get("tags") or [])]
        pool = [t for t in (cache_store.get("all_tasks") or [])
                if t.get("id") != task.get("id")]
        pool.append(entry)
        cache_store.set("all_tasks", pool)
        pd_key = f"project_data_{pid}"
        pd = cache_store.get(pd_key)
        if pd is not None:
            pd = dict(pd)
            pd["tasks"] = [t for t in pd.get("tasks", [])
                           if t.get("id") != task.get("id")] + [entry]
            cache_store.set(pd_key, pd)
    except Exception:
        pass


def _person_circle_pick():
    """Circle tag for a new card. None = Cancel (abort the mint),
    '' = deliberately uncircled."""
    import people as pe
    opts = [f"{chip} {label}" for _, chip, label in pe.CIRCLES]
    opts.append("⚪️ No circle")
    got = _choose("👽 Circle for this person", opts)
    if got is None:
        return None
    for tag, chip, label in pe.CIRCLES:
        if got == f"{chip} {label}":
            return tag
    return ""


def _person_circle_tag(tag, parent="__circle__"):
    """Ensure ONE tag exists - circles nest under 👽people (the default),
    parent=None mints a flat tag (#archive). '' when v2 is unavailable -
    the card still mints, just untagged. Mirrors _bridge_month_tag."""
    import people as pe
    if parent == "__circle__":
        parent = pe.PARENT_TAG
    try:
        from display import tag_match_key
        known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
        if tag_match_key(tag) in known:
            return tag
        import api_v2
        v2 = api_v2.TickTickV2()
        if not v2.token or not v2.create_tag(tag, parent=parent):
            return ""
        cache_store.set("tags", (cache_store.get("tags") or []) + [tag])
        tree = cache_store.get("tags_tree")
        if tree is not None:
            cache_store.set("tags_tree", tree + [
                {"name": tag, "label": tag, "parent": parent}])
        return tag
    except Exception:
        return ""


def person_new(rest=""):
    """➕ New person card: 👽H • {Name}, circle tag, 📇/🎁/🧾 skeleton.
    Opens right away - the card wants its birthday + phone. rest is an
    optional b64 name (the Add H-mode row passes the typed fragment)."""
    import base64
    import people as pe
    import areas
    if not areas.people_configured():
        _crm_say("👽 People list not configured (Settings)")
        return
    name = ""
    if rest:
        try:
            name = base64.b64decode(rest).decode("utf-8", "replace").strip()
        except Exception:
            name = ""
    if not name:
        a = _ask("👽 Person name (Esc cancels)")
        if a is None or not a.strip():
            _crm_say("👽 Cancelled")
            return
        name = a
    import re as _re
    # ':' breaks xact args; the rest are ~p span terminators in the Add
    # parser - a name carrying one truncates the parent match (review catch)
    name = " ".join(_re.sub(r"[~#!*@/>=&%:]", " ", name).split())
    want = pe.person_title(name)
    api = _api()
    hit = _person_find(api, want)
    if hit == "ERR":
        _crm_say("👽 Can't check for a twin (offline?) · nothing minted")
        return
    if hit:
        open_task(areas.PEOPLE_ID, hit["id"])
        _crm_say(f"👽 {name} exists · opening")
        return
    circle = _person_circle_pick()
    if circle is None:
        _crm_say("👽 Cancelled")
        return
    tag = _person_circle_tag(circle) if circle else ""
    skel, bfrom = pe.CARD_SKEL, ""
    try:                       # an existing countdown seeds the 📇 Birthday
        import api_v2
        cds = api_v2.TickTickV2().get_countdowns()
        cd = next((c for c in (cds or [])
                   if (c.get("name") or "").strip().lower() == name.lower()
                   and c.get("type") == 2), None)
        if cd and cd.get("date"):
            n = int(cd["date"])
            val = (f"{n % 10000 // 100:02d}/{n % 100:02d}"
                   if cd.get("ignoreYear")
                   else f"{n // 10000}/{n % 10000 // 100:02d}/{n % 100:02d}")
            skel = skel.replace("Birthday: ", f"Birthday: {val}")
            bfrom = f"🎂 {val}"
    except Exception:
        pass
    t = api.create_task(title=want, project_id=areas.PEOPLE_ID,
                        content=skel, tags=[tag] if tag else [])
    _person_inject_cache(t, areas.PEOPLE_ID)
    open_task(areas.PEOPLE_ID, t.get("id"))
    bits = [f"👽 {name} · card minted · fill the 📇"]
    if bfrom:
        bits.append(f"{bfrom} from countdowns")
    if tag:
        bits.append(f"#{tag}")
    elif circle == "":
        bits.append("uncircled")
    _crm_say(" · ".join(bits))
    app_sync_after_write()


def person_log(rest):
    """🧾 Timestamped line onto the card, newest on top (private meeting
    notes). Typed beats clipboard; both empty = nothing to log."""
    import people as pe
    pid, _, tid = rest.partition(":")
    a = _ask("🧾 Log entry (empty OK = clipboard · Esc cancels)")
    if a is None:
        _crm_say("🧾 Cancelled")
        return
    text = a.strip() or _pbpaste()
    if not text:
        _crm_say("🧾 Nothing to log (empty + empty clipboard)")
        return
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    new = pe.log_insert(live.get("content") or "", pe.log_line(text))
    api.update_task(tid, pid, current=live, content=new)
    _patch_content_cache(tid, new)
    _crm_say(f"🧾 Logged · {pe.person_name(live.get('title') or '')}")
    app_sync_after_write()


def person_idea(rest):
    """🎁 Gift idea onto the card's Ideas stash (typed beats clipboard)."""
    import people as pe
    pid, _, tid = rest.partition(":")
    a = _ask("🎁 Idea (empty OK = clipboard · Esc cancels)")
    if a is None:
        _crm_say("🎁 Cancelled")
        return
    text = a.strip() or _pbpaste()
    if not text:
        _crm_say("🎁 Nothing to stash (empty + empty clipboard)")
        return
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    new = pe.ideas_insert(live.get("content") or "", f"- {text}")
    api.update_task(tid, pid, current=live, content=new)
    _patch_content_cache(tid, new)
    _crm_say(f"🎁 Stashed · {pe.person_name(live.get('title') or '')}")
    app_sync_after_write()


def person_edit(rest):
    """📇 One card field via dialog, current value prefilled.
    rest = field:pid:tid (field from people.CARD_FIELDS)."""
    import people as pe
    field, _, r2 = rest.partition(":")
    pid, _, tid = r2.partition(":")
    if field not in pe.CARD_FIELDS:
        _crm_say(f"📇 Unknown field: {field}")
        return
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    cur = pe.card_field(live.get("content") or "", field)
    a = _ask(f"📇 {field} (Esc cancels · empty clears)", default=cur)
    if a is None:
        _crm_say("📇 Cancelled")
        return
    new = pe.card_field_set(live.get("content") or "", field, a.strip())
    api.update_task(tid, pid, current=live, content=new)
    _patch_content_cache(tid, new)
    shown = a.strip() or "cleared"
    _crm_say(f"📇 {field} · {shown} · "
             f"{pe.person_name(live.get('title') or '')}")
    app_sync_after_write()


def person_fact(rest):
    """💬 Conversation starter onto the card ('Has a cat named Garfield').
    Typed beats clipboard; bare bullet, no timestamp - facts don't age."""
    import people as pe
    pid, _, tid = rest.partition(":")
    a = _ask("💬 Fact (empty OK = clipboard · Esc cancels)")
    if a is None:
        _crm_say("💬 Cancelled")
        return
    text = a.strip() or _pbpaste()
    if not text:
        _crm_say("💬 Nothing to note (empty + empty clipboard)")
        return
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    new = pe.facts_insert(live.get("content") or "", f"- {text}")
    api.update_task(tid, pid, current=live, content=new)
    _patch_content_cache(tid, new)
    _crm_say(f"💬 Noted · {pe.person_name(live.get('title') or '')}")
    app_sync_after_write()


def person_idea_from(rest):
    """🎁 The acted-on item BECOMES the idea: its title (+ first link)
    lands on the chosen card's Ideas. rest = person_tid:src_pid:src_tid.
    The source stays where it is - this is a reference, not a move."""
    import people as pe
    import areas
    ptid, _, r2 = rest.partition(":")
    spid, _, stid = r2.partition(":")
    api = _api()
    try:
        src = api.get_task(spid, stid)
        card = api.get_task(areas.PEOPLE_ID, ptid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    title = (src.get("title") or "").strip()
    if not title:
        _crm_say("🎁 Nothing to stash")
        return
    line = f"- {title}"
    try:
        import links as links_util
        found = links_util.extract_links(f"{title} {src.get('content') or ''}")
        if found and found[0][1] not in title:
            line += f" · {found[0][1]}"
    except Exception:
        pass
    new = pe.ideas_insert(card.get("content") or "", line)
    api.update_task(ptid, areas.PEOPLE_ID, current=card, content=new)
    _patch_content_cache(ptid, new)
    _crm_say(f"🎁 {title[:40]} → {pe.person_name(card.get('title') or '')}")
    app_sync_after_write()


def add_pre(rest):
    """Jump into the Add window prefilled ('~p 👽H • Goga ' → CTA composer
    with native *date @time scheduling; 'H' → the person picker mode).
    search_pre's twin for the Add ET."""
    _run_trigger("Add", (rest or "").rstrip() + " ")


def _bday_date_int(y, mo, d):
    """YYYYMMDD int for the countdown. Year unknown → current year; a
    Feb-29 in a non-leap year clamps to 28 (the RRULE keeps BYMONTHDAY=29,
    so leap years still land on the 29th)."""
    yy = y or datetime.now().year
    try:
        datetime(yy, mo, d)
    except ValueError:
        d = 28
    return int(f"{yy}{mo:02d}{d:02d}")


def person_bday(rest):
    """🎂 Card's Birthday field → a TickTick countdown in Vex's exact
    grammar (bare name, birthday icon, 9:00 day-of + 2-days-before
    reminders; birth year known → age shown). Idempotent by name."""
    import people as pe
    import api_v2
    pid, _, tid = rest.partition(":")
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    name = pe.person_name(live.get("title") or "")
    bd = pe.parse_birthday(pe.card_field(live.get("content") or "",
                                         "Birthday"))
    if not bd:
        _crm_say("🎂 No parsable Birthday on the card · 1993/06/27 · "
                 "27.06.1993 · 06/27")
        return
    y, mo, d = bd
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🎂 Needs the v2 login (Settings → Attachment Login)")
        return
    have = v2.get_countdowns()
    if have is None:
        _crm_say("🎂 Can't check countdowns (offline?) · nothing minted")
        return
    if any((c.get("name") or "").strip().lower() == name.lower()
           for c in have):
        _crm_say(f"🎂 Countdown already exists · {name}")
        return
    ent = {
        "id": api_v2.new_object_id(), "type": 2,
        "iconRes": "countdown_birthday", "color": "#A0EFED",
        "name": name, "date": _bday_date_int(y, mo, d),
        "ignoreYear": not y, "showCalendarType": 1,
        "reminders": ["TRIGGER:P0DT9H0M0S", "TRIGGER:-P2DT15H0M0S"],
        "repeatFlag": f"RRULE:FREQ=YEARLY;INTERVAL=1;BYMONTH={mo};"
                      f"BYMONTHDAY={d}",
        "remark": "", "status": 0, "style": "cartoon",
        "styleColor": ["#2B2B2B", "#E4E4E4"], "dateDisplayFormat": "day",
        "timerMode": 0, "showAge": bool(y), "daysOption": 0,
        "sortOrder": min([c.get("sortOrder", 0) for c in have] or [0])
        - 1048576,
    }
    if v2.countdown_batch(add=[ent]):
        _crm_say(f"🎂 {name} · countdown minted"
                 + (" · age shown" if y else ""))
    else:
        _crm_say("🎂 Countdown mint failed (offline?)")


def person_archive(rest):
    """🗄️ Big log → split off: the old 🧾 Log becomes an archive NOTE
    (👽H • {Name} · 🗄️ date, #archive, no circle - a second grouped tag
    would double cards), the LIVE card keeps its id/subtasks/circle and
    gets a fresh empty log. Asks first."""
    import people as pe
    import areas
    pid, _, tid = rest.partition(":")
    api = _api()
    try:
        live = api.get_task(pid, tid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    name = pe.person_name(live.get("title") or "")
    log = pe.log_body(live.get("content") or "")
    if not log.strip():
        _crm_say("🗄️ Log is empty · nothing to archive")
        return
    n = sum(1 for ln in log.splitlines() if ln.strip())
    if _dialog(f"Archive {name}'s log ({n} lines)? Old entries move to a "
               "dated note · the card starts a fresh log",
               ["Cancel", "Archive"], "Archive") != "Archive":
        _crm_say("🗄️ Cancelled")
        return
    day = datetime.now().date()
    want = pe.archive_title(name, day)
    hit = _person_find(api, want)        # retry-safe: same-day rerun reuses
    if hit == "ERR":
        _crm_say("🗄️ Can't check for today's archive (offline?) · nothing minted")
        return
    if hit:
        note = hit
    else:
        _person_circle_tag(pe.ARCHIVE_TAG, parent=None)   # plain #archive
        note = api.create_task(title=want,
                               project_id=areas.PEOPLE_ID, content=log,
                               tags=[pe.ARCHIVE_TAG], kind="NOTE")
        _bridge_inject_cache(note, areas.PEOPLE_ID,
                             _list_name_of(areas.PEOPLE_ID))
    new = pe.log_reset(live.get("content") or "")
    api.update_task(tid, pid, current=live, content=new)
    _patch_content_cache(tid, new)
    _crm_say(f"🗄️ {name} · log archived ({n} lines) · card reset")
    app_sync_after_write()


def person_attach(rest):
    """👽 Any task → a CTA under a person (fx_unstage's sacred order:
    v2 detach if parented → move list → v1 adopt). rest =
    person_tid:src_pid:src_tid."""
    import people as pe
    import areas
    ptid, _, r2 = rest.partition(":")
    spid, _, stid = r2.partition(":")
    if not (ptid and spid and stid) or stid == ptid:
        _crm_say("👽 Can't attach that")
        return
    api = _api()
    try:
        live = api.get_task(spid, stid)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    if live.get("childIds"):
        _crm_say("👽 It has subtasks · move them out first")
        return
    old_parent = live.get("parentId")
    if old_parent:
        import api_v2
        v2 = api_v2.TickTickV2()
        if not (v2.token and v2.task_parent([{
                "taskId": stid, "projectId": spid,
                "oldParentId": old_parent}])):
            _crm_say("👽 It's someone's subtask and the detach needs the "
                     "v2 login · not moved")
            return
    try:
        if spid != areas.PEOPLE_ID:
            api.move_task(stid, spid, areas.PEOPLE_ID)
        api.update_task(stid, areas.PEOPLE_ID, current=live,
                        parentId=ptid, columnId=None)
    except Exception as e:
        _crm_say(f"Error: {e}")
        return
    from dispatch import _patch_project_data
    _patch_project_data(stid, pid_old=spid, remove=True)
    pool = cache_store.get("all_tasks")
    if pool is not None:
        for x in pool:
            if x.get("id") == stid:
                x["projectId"] = areas.PEOPLE_ID
                x["_projectId"] = areas.PEOPLE_ID
                x["_projectName"] = _list_name_of(areas.PEOPLE_ID)
                x["parentId"] = ptid
        cache_store.set("all_tasks", pool)
    pd_key = f"project_data_{areas.PEOPLE_ID}"
    pd = cache_store.get(pd_key)
    if pd is not None:
        entry = dict(live)
        entry["projectId"] = areas.PEOPLE_ID
        entry["parentId"] = ptid
        pd = dict(pd)
        pd["tasks"] = [t for t in pd.get("tasks", [])
                       if t.get("id") != stid] + [entry]
        cache_store.set(pd_key, pd)
    pname = pe.person_name(next(
        (x.get("title", "") for x in (cache_store.get("all_tasks") or [])
         if x.get("id") == ptid), ""))
    _crm_say(f"👽 {(live.get('title') or 'Task').strip()} → {pname or 'person'}")
    app_sync_after_write()


def person_autolog(tid, snap=None):
    """Completing a person's CTA writes the card's log itself
    ('- ts - ✅ …'). Returns a toast suffix (' · 🧾 Goga') or ''.
    NEVER raises - completion must not break on a logging nicety."""
    try:
        import people as pe
        import areas
        if not areas.people_configured():
            return ""
        pool = cache_store.get("all_tasks") or []
        t = snap or next((x for x in pool if x.get("id") == tid), None)
        if not t or not t.get("parentId"):
            return ""
        par = next((x for x in pool if x.get("id") == t["parentId"]), None)
        if not par:
            return ""
        ppid = par.get("_projectId") or par.get("projectId")
        if ppid != areas.PEOPLE_ID or not pe.is_person(par.get("title", "")):
            return ""
        api = _api()
        live = api.get_task(areas.PEOPLE_ID, par["id"])
        new = pe.log_insert(live.get("content") or "",
                            pe.log_line(f"✅ {(t.get('title') or '').strip()}"))
        api.update_task(par["id"], areas.PEOPLE_ID, current=live,
                        content=new)
        _patch_content_cache(par["id"], new)
        return f" · 🧾 {pe.person_name(par.get('title') or '')}"
    except Exception:
        return ""


def person_setup():
    """⚙️ One shot: seed the five circle tags (nested under 👽people) +
    flip the People list to kanban. Idempotent - reruns just report."""
    import people as pe
    import areas
    if not areas.people_configured():
        _crm_say("👽 People list not configured (Settings)")
        return
    made, have = [], []
    for tag, _, _ in pe.CIRCLES:
        from display import tag_match_key
        known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
        if tag_match_key(tag) in known:
            have.append(tag)
        elif _person_circle_tag(tag):
            made.append(tag)
    try:
        _api().update_project(areas.PEOPLE_ID, viewMode="kanban")
    except Exception:
        pass
    if made:
        _crm_say(f"👽 Circles seeded · {len(made)} new · board kanban "
                 "(group by tag = one in-app tap)")
    elif len(have) == len(pe.CIRCLES):
        _crm_say("👽 All circles exist · board kanban")
    else:
        _crm_say("👽 Some circles failed (v2 login?) · retry from the hub")


def people_setlist():
    """⚙️ Settings → 👽 People list: paste the home list's id. Saves
    config people_list_id + flips the list to kanban."""
    import re as _re
    cur = cfg.get_people_list_id()
    a = _ask("👽 People list id (⌘ Copy id on any list · Esc cancels)",
             default=cur)
    if a is None:
        _crm_say("👽 Cancelled")
        return
    a = a.strip()
    if not _re.fullmatch(r"[0-9a-fA-F]{24}", a or ""):
        _crm_say("👽 That does not look like a list id · nothing saved")
        return
    data = cfg.load()
    data["people_list_id"] = a
    cfg.save(data)
    try:
        _api().update_project(a, viewMode="kanban")
    except Exception:
        pass
    _crm_say(f"👽 People home set · {_list_name_of(a) or a}")


# ── ⏳ Countdowns + 🔄 Habits verbs (hubs 2026-07-24; all API-clean:
#    countdown/batch · habits/batch · habitCheckins/batch · habitRecords,
#    every one probe-verified; caches patched after each write) ─────────────

def _op_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _cd_patch(entity=None, delete_id=None):
    """Mirror a countdown write into the 'countdowns' cache."""
    try:
        cds = cache_store.get("countdowns") or []
        if delete_id:
            cds = [c for c in cds if c.get("id") != delete_id]
        elif entity:
            hit = False
            cds = [entity if c.get("id") == entity["id"] else c for c in cds]
            hit = any(c.get("id") == entity["id"] for c in cds)
            if not hit:
                cds.append(entity)
        cache_store.set("countdowns", cds)
    except Exception:
        cache_store.invalidate("countdowns")


def _hb_patch(entity=None, delete_id=None):
    try:
        hs = cache_store.get("habits") or []
        if delete_id:
            hs = [h for h in hs if h.get("id") != delete_id]
        elif entity:
            if any(h.get("id") == entity["id"] for h in hs):
                hs = [entity if h.get("id") == entity["id"] else h
                      for h in hs]
            else:
                hs.append(entity)
        cache_store.set("habits", hs)
        if delete_id:
            checks = cache_store.get("habit_checkins") or {}
            checks.pop(delete_id, None)
            cache_store.set("habit_checkins", checks)
    except Exception:
        cache_store.invalidate("habits")


def _ck_patch(hid, entry):
    """Upsert one checkin into the 'habit_checkins' cache (keyed by day)."""
    try:
        checks = cache_store.get("habit_checkins") or {}
        arr = [c for c in (checks.get(hid) or [])
               if c.get("checkinStamp") != entry.get("checkinStamp")]
        arr.append(entry)
        checks[hid] = arr
        cache_store.set("habit_checkins", checks)
    except Exception:
        cache_store.invalidate("habit_checkins")


def _cd_live(v2, cid):
    """Live countdown entity by id - None = offline/missing (fail closed)."""
    cds = v2.get_countdowns()
    if cds is None:
        return None
    return next((c for c in cds if c.get("id") == cid), None)


def countdown_new(rest=""):
    """➕ New countdown. rest = b64 {"name","date","yearless"} from the Add
    window's C mode, else dialogs all the way: name → date (dot grammar) →
    kind → appearance (typeOfSmartList) → anniversary count direction."""
    import base64
    import countdowns as cdm
    import api_v2
    name = date_int = None
    yearless = False
    if rest:
        try:
            spec = json.loads(base64.b64decode(rest))
            name = (spec.get("name") or "").strip()
            date_int, yearless = spec.get("date"), spec.get("yearless")
        except Exception:
            pass
    if not name:
        name = (_ask("Countdown name:", title="⏳ New countdown") or "").strip()
        if not name:
            return
    if not date_int:
        raw = _ask(f"Date for {name}: · 28.7 · 27.06.1993 · 1993/06/27",
                   title="⏳ New countdown")
        if raw is None:
            return
        parsed = cdm.parse_cd_date(raw)
        if not parsed:
            _crm_say("⏳ Can't read that date · 28.7 · 27.06.1993")
            return
        date_int, yearless = parsed[0], not parsed[1]
    kinds = ["⏳ Countdown", "🎂 Birthday", "💞 Anniversary", "🎉 Holiday"]
    kmap = {"⏳ Countdown": 4, "🎂 Birthday": 2, "💞 Anniversary": 3,
            "🎉 Holiday": 1}
    k = _choose("What kind?", kinds, title="⏳ New countdown",
                default=kinds[0])
    if k is None:
        return
    kind = kmap.get(k, 4)
    labels = [lbl for _v, lbl in cdm.APPEAR]
    ap = _choose("Appears in calendar + smart lists:", labels,
                 title="⏳ New countdown", default="On the day")
    if ap is None:
        return
    appear = next((v for v, lbl in cdm.APPEAR if lbl == ap), 0)
    countup = False
    if kind == 3:
        d = _choose("Counting?", ["⬇️ Down to the date", "⬆️ Up since it"],
                    title="💞 Anniversary", default="⬇️ Down to the date")
        if d is None:
            return
        countup = d.startswith("⬆️")
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("⏳ Needs the v2 login (Settings → Attachment Login)")
        return
    have = v2.get_countdowns()
    if have is None:
        _crm_say("⏳ Can't reach countdowns (offline?) · nothing minted")
        return
    ent = cdm.new_entity(
        api_v2.new_object_id(), name, date_int, kind, appear=appear,
        countup=countup, yearless=yearless,
        sort_order=min([c.get("sortOrder", 0) for c in have] or [0])
        - 1048576)
    if not v2.countdown_batch(add=[ent]):
        _crm_say("⏳ Mint failed (offline?)")
        return
    _cd_patch(entity=ent)
    _crm_say(f"{cdm.kind_chip(ent)} {name} · "
             f"{cdm.distance_label(ent)} · minted")


def countdown_edit(field, cid):
    """✏️ name / 📅 date / 💬 remark - dialog prefilled, live RMW."""
    import countdowns as cdm
    import api_v2
    v2 = api_v2.TickTickV2()
    cd = _cd_live(v2, cid) if v2.token else None
    if cd is None:
        _crm_say("⏳ Can't fetch it (offline?) · nothing changed")
        return
    if field == "date":
        raw = _ask("New date: · 28.7 · 27.06.1993 · 1993/06/27",
                   title=f"⏳ {cd.get('name', '')}")
        if raw is None or not raw.strip():
            return
        parsed = cdm.parse_cd_date(raw)
        if not parsed:
            _crm_say("⏳ Can't read that date")
            return
        date_int, had_year = parsed
        if not had_year and not cd.get("ignoreYear") \
                and (cd.get("date") or 0) // 10000:
            # yearless edit on a year-bearing entity KEEPS the stored
            # year (a birth year must survive a day tweak - review catch)
            from datetime import date as _dd
            y0 = cd["date"] // 10000
            mo, d = date_int // 100 % 100, date_int % 100
            try:
                _dd(y0, mo, d)
            except ValueError:
                _crm_say(f"⏳ {d}.{mo} doesn't exist in {y0}")
                return
            date_int, had_year = y0 * 10000 + mo * 100 + d, True
        cd["date"] = date_int
        if cd.get("type") == 2:
            cd["ignoreYear"] = not had_year
            cd["showAge"] = had_year
        if cd.get("repeatFlag") and "FREQ=YEARLY" in cd["repeatFlag"]:
            mo, d = date_int // 100 % 100, date_int % 100
            cd["repeatFlag"] = (f"RRULE:FREQ=YEARLY;INTERVAL=1;"
                                f"BYMONTH={mo};BYMONTHDAY={d}")
    elif field in ("name", "remark"):
        cur = cd.get(field) or ""
        val = _ask(f"{'Name' if field == 'name' else 'Remark'}:",
                   title=f"⏳ {cd.get('name', '')}", default=cur)
        if val is None:
            return
        if field == "name" and not val.strip():
            return
        cd[field] = val.strip()
    else:
        _crm_say(f"⏳ Unknown field {field!r}")
        return
    if not v2.countdown_batch(update=[cd]):
        _crm_say("⏳ Save failed (offline?)")
        return
    _cd_patch(entity=cd)
    _crm_say(f"⏳ {cd.get('name', '')} · saved")


def countdown_appear(cid, val):
    import countdowns as cdm
    import api_v2
    v2 = api_v2.TickTickV2()
    cd = _cd_live(v2, cid) if v2.token else None
    if cd is None:
        _crm_say("⏳ Can't fetch it (offline?) · nothing changed")
        return
    cd["typeOfSmartList"] = int(val)
    if not v2.countdown_batch(update=[cd]):
        _crm_say("⏳ Save failed (offline?)")
        return
    _cd_patch(entity=cd)
    _crm_say(f"👁️ {cd.get('name', '')} · "
             + cdm.APPEAR_LABEL.get(int(val), "?"))


def countdown_flip(cid):
    """⏱️ countdown ⟷ countup. Up drops the yearly RRULE (a count-up
    counts since ONE date); down restores it for dated kinds."""
    import api_v2
    v2 = api_v2.TickTickV2()
    cd = _cd_live(v2, cid) if v2.token else None
    if cd is None:
        _crm_say("⏳ Can't fetch it (offline?) · nothing changed")
        return
    if (cd.get("timerMode") or 0) == 0:
        cd["timerMode"] = 1
        cd["repeatFlag"] = None
        word = "up"
    else:
        cd["timerMode"] = 0
        if cd.get("type") in (1, 2, 3):
            n = cd.get("date") or 0
            mo, d = n // 100 % 100, n % 100
            cd["repeatFlag"] = (f"RRULE:FREQ=YEARLY;INTERVAL=1;"
                                f"BYMONTH={mo};BYMONTHDAY={d}")
        word = "down"
    if not v2.countdown_batch(update=[cd]):
        _crm_say("⏳ Save failed (offline?)")
        return
    _cd_patch(entity=cd)
    _crm_say(f"⏱️ {cd.get('name', '')} · counting {word}")


def countdown_archive(cid):
    import api_v2
    v2 = api_v2.TickTickV2()
    cd = _cd_live(v2, cid) if v2.token else None
    if cd is None:
        _crm_say("⏳ Can't fetch it (offline?) · nothing changed")
        return
    cd["status"] = 1
    if not v2.countdown_batch(update=[cd]):
        _crm_say("⏳ Archive failed (offline?)")
        return
    _cd_patch(delete_id=cid)
    _crm_say(f"🗄️ {cd.get('name', '')} · archived")


def countdown_delete(cid):
    import api_v2
    v2 = api_v2.TickTickV2()
    cd = _cd_live(v2, cid) if v2.token else None
    if cd is None:
        _crm_say("⏳ Can't fetch it (offline?) · nothing deleted")
        return
    if _dialog(f"Delete countdown {cd.get('name', '')!r}?",
               ["Cancel", "Delete"], "Cancel") != "Delete":
        return
    if not v2.countdown_batch(delete=[cid]):
        _crm_say("⏳ Delete failed (offline?)")
        return
    _cd_patch(delete_id=cid)
    _crm_say(f"🗑️ {cd.get('name', '')} · deleted")


def _habit_by_id(hid):
    """Cache habit, else a live GET (fail closed → None)."""
    h = next((x for x in (cache_store.get("habits") or [])
              if x.get("id") == hid), None)
    if h:
        return h
    import api_v2
    v2 = api_v2.TickTickV2()
    if not v2.token:
        return None
    live = v2.get_habits()
    return next((x for x in live or [] if x.get("id") == hid), None)


def _habit_day_checkin(v2, hid, day_stamp):
    """LIVE checkin for one habit+day - (checkin|None, ok). ok False =
    the query itself failed (offline) → callers bail, never double-add."""
    j = v2.habit_checkins([hid], day_stamp - 1)
    if j is None:
        return None, False
    import habits_model as hm
    return hm.checkin_for(j.get(hid), day_stamp), True


def _habit_parse_day(raw):
    """'y' · 'yy' · 'D.M' / 'D.M.YYYY' → YYYYMMDD int (past days only),
    None when unreadable."""
    from datetime import date as _d, timedelta as _td
    t = (raw or "").strip().lower().rstrip(".")
    today = _d.today()
    if t in ("y", "yy"):
        d = today - _td(days=len(t))
        return d.year * 10000 + d.month * 100 + d.day
    import re as _re
    m = _re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", t)
    if not m:
        return None
    day, mo = int(m.group(1)), int(m.group(2))
    explicit_year = bool(m.group(3))
    y = int(m.group(3)) if explicit_year else today.year
    try:
        d = _d(y, mo, day)
    except ValueError:
        return None
    if d > today:
        if explicit_year:
            return None          # a typed future year is a typo, not -1y
        try:
            d = d.replace(year=d.year - 1)
        except ValueError:
            return None          # Feb 29 with no leap twin last year
    return d.year * 10000 + d.month * 100 + d.day


def _habit_tick_core(hid, day_stamp, retro=False):
    """Shared tick: live day-checkin read (fail closed) → tick_payload →
    batch write → cache patches + streak bump → note dialog when the habit
    keeps a diary and the day just completed (today only)."""
    import habits_model as hm
    import api_v2
    h = _habit_by_id(hid)
    if h is None:
        _crm_say("🔄 Habit not found (offline?)")
        return
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🔄 Needs the v2 login (Settings → Attachment Login)")
        return
    existing, ok = _habit_day_checkin(v2, hid, day_stamp)
    if not ok:
        _crm_say("🔄 Can't read checkins (offline?) · nothing ticked")
        return
    payload = hm.tick_payload(h, day_stamp, existing, _op_iso())
    if payload is None:
        _crm_say(f"✅ {h.get('name', '')} · already done")
        return
    entry, done, value = payload
    if existing:
        ok2 = v2.habit_checkins_batch(update=[entry])
    else:
        entry["id"] = api_v2.new_object_id()
        ok2 = v2.habit_checkins_batch(add=[entry])
    if not ok2:
        _crm_say("🔄 Tick failed (offline?)")
        return
    _ck_patch(hid, entry)
    name = h.get("name", "")
    was_done = existing and existing.get("status") == hm.DONE
    if done and not was_done and not retro:
        h2 = dict(h)
        h2["currentStreak"] = (h.get("currentStreak") or 0) + 1
        h2["totalCheckIns"] = (h.get("totalCheckIns") or 0) + 1
        _hb_patch(entity=h2)
        h = h2
    noted = ""
    if done and not was_done and not retro and h.get("recordEnable"):
        txt = _ask(f"Note for {name}? (optional)", title="🔄 Habit diary")
        if txt and txt.strip():
            rec = hm.record_payload(api_v2.new_object_id(), hid, day_stamp,
                                    txt.strip(), _op_iso())
            if v2.habit_records_batch(add=[rec]):
                noted = " · 📝"
    if hm.is_real(h) and not done:
        goal = h.get("goal") or 1
        _crm_say(f"🔄 {name} · {value:g}/{goal:g} {h.get('unit') or ''}"
                 .rstrip())
    else:
        streak = h.get("currentStreak") or 0
        chip = f" · 🔥{streak}" if streak > 1 else ""
        when = "" if not retro else " · ⏪"
        _crm_say(f"✅ {name}{chip}{when}{noted}")


def habit_tick(hid):
    import habits_model as hm
    from datetime import date as _d
    _habit_tick_core(hid, hm.stamp(_d.today()))


def habit_tick_past(hid):
    raw = _ask("Which day? · y · yy · 22.7 · 22.7.2026",
               title="⏪ Tick a past day")
    if raw is None or not raw.strip():
        return
    day = _habit_parse_day(raw)
    if not day:
        _crm_say("⏪ Can't read that day · y · yy · 22.7")
        return
    _habit_tick_core(hid, day, retro=True)


def habit_untick(hid):
    import habits_model as hm
    import api_v2
    from datetime import date as _d
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🔄 Needs the v2 login")
        return
    ts = hm.stamp(_d.today())
    existing, ok = _habit_day_checkin(v2, hid, ts)
    if not ok:
        _crm_say("🔄 Can't read checkins (offline?)")
        return
    entry = hm.untick_payload(existing, _op_iso())
    if entry is None:
        _crm_say("↩️ Nothing to un-tick today")
        return
    if not v2.habit_checkins_batch(update=[entry]):
        _crm_say("🔄 Un-tick failed (offline?)")
        return
    _ck_patch(hid, entry)
    h = _habit_by_id(hid) or {}
    was_done = existing.get("status") == hm.DONE
    if was_done and h.get("currentStreak"):
        # only a cleared DONE undoes the tick's heuristic bump - clearing
        # a partial value or a skip never counted (review catch)
        h2 = dict(h)
        h2["currentStreak"] = max(0, h["currentStreak"] - 1)
        h2["totalCheckIns"] = max(0, (h.get("totalCheckIns") or 1) - 1)
        _hb_patch(entity=h2)
    _crm_say(f"↩️ {h.get('name', '')} · blank again")


def habit_skip(hid):
    import habits_model as hm
    import api_v2
    from datetime import date as _d
    h = _habit_by_id(hid)
    if h is None:
        _crm_say("🔄 Habit not found (offline?)")
        return
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🔄 Needs the v2 login")
        return
    ts = hm.stamp(_d.today())
    existing, ok = _habit_day_checkin(v2, hid, ts)
    if not ok:
        _crm_say("🔄 Can't read checkins (offline?)")
        return
    entry = hm.skip_payload(h, ts, existing, _op_iso())
    if existing:
        ok2 = v2.habit_checkins_batch(update=[entry])
    else:
        entry["id"] = api_v2.new_object_id()
        ok2 = v2.habit_checkins_batch(add=[entry])
    if not ok2:
        _crm_say("🔄 Skip failed (offline?)")
        return
    _ck_patch(hid, entry)
    _crm_say(f"⛔ {h.get('name', '')} · skipped today")


def habit_note(hid):
    import habits_model as hm
    import api_v2
    from datetime import date as _d
    h = _habit_by_id(hid)
    if h is None:
        _crm_say("🔄 Habit not found (offline?)")
        return
    txt = _ask(f"Note for {h.get('name', '')}:", title="🔄 Habit diary")
    if txt is None or not txt.strip():
        return
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🔄 Needs the v2 login")
        return
    rec = hm.record_payload(api_v2.new_object_id(), hid,
                            hm.stamp(_d.today()), txt.strip(), _op_iso())
    if not v2.habit_records_batch(add=[rec]):
        _crm_say("🔄 Note failed (offline?)")
        return
    _crm_say(f"📝 {h.get('name', '')} · noted")


def habit_new(rest=""):
    """➕ New habit: name (b64 from the Add window's R mode, else dialog) →
    section → rhythm preset → done-or-amount (goal + unit) → diary flag."""
    import base64
    import habits_model as hm
    import api_v2
    from datetime import date as _d
    name = ""
    if rest:
        try:
            name = (base64.b64decode(rest).decode() or "").strip()
        except Exception:
            name = ""
    if not name:
        name = (_ask("Habit name:", title="🔄 New habit") or "").strip()
        if not name:
            return
    secs = cache_store.get("habit_sections") or []
    sec_labels = [s.get("name", "").lstrip("_").capitalize()
                  for s in secs if s.get("name")]
    pick = _choose("Section:", ["None"] + sec_labels, title="🔄 New habit",
                   default="None")
    if pick is None:
        return
    sec_id = "-1"
    for s in secs:
        if s.get("name", "").lstrip("_").capitalize() == pick:
            sec_id = s["id"]
            break
    labels = [lbl for lbl, _r in hm.RULE_PRESETS]
    rl = _choose("How often?", labels, title="🔄 New habit",
                 default=labels[0])
    if rl is None:
        return
    rule = dict(hm.RULE_PRESETS).get(rl)
    kind = _choose("Tick type:", ["✅ Done / not done", "🔢 An amount"],
                   title="🔄 New habit", default="✅ Done / not done")
    if kind is None:
        return
    real, goal, unit = False, 1, "Count"
    if kind.startswith("🔢"):
        real = True
        g = _ask("Daily goal (number):", title="🔄 New habit", default="8")
        if g is None:
            return
        try:
            goal = float(g)
        except ValueError:
            _crm_say("🔄 Goal must be a number · nothing minted")
            return
        u = _ask("Unit:", title="🔄 New habit", default="Count")
        if u is None:
            return               # Esc = cancel, not 'Count' (review catch)
        unit = u.strip() or "Count"
    diary = _choose("Diary note on tick?", ["No", "Yes"],
                    title="🔄 New habit", default="No")
    if diary is None:
        return
    v2 = api_v2.TickTickV2()
    if not v2.token:
        _crm_say("🔄 Needs the v2 login (Settings → Attachment Login)")
        return
    today = _d.today()
    ent = hm.new_entity(api_v2.new_object_id(), name, section_id=sec_id,
                        rule=rule, goal=goal, unit=unit, real=real,
                        record=(diary == "Yes"),
                        start_stamp=today.year * 10000 + today.month * 100
                        + today.day)
    if not v2.habits_batch(add=[ent]):
        _crm_say("🔄 Mint failed (offline?)")
        return
    _hb_patch(entity=ent)
    _crm_say(f"🔄 {name} · minted · {rl}")


def habit_archive(hid):
    """Live RMW like countdown_archive - the cached entity is up to an
    hour stale AND carries the tick verbs' heuristic streak bumps; pushing
    it whole would clobber newer server state (review catch)."""
    import api_v2
    v2 = api_v2.TickTickV2()
    live = v2.get_habits() if v2.token else None
    h = next((x for x in live or [] if x.get("id") == hid), None) \
        if live is not None else None
    if h is None:
        _crm_say("🔄 Can't fetch it (offline?) · nothing archived")
        return
    h2 = dict(h)
    h2["status"] = 1
    if not v2.habits_batch(update=[h2]):
        _crm_say("🔄 Archive failed (offline?)")
        return
    _hb_patch(delete_id=hid)
    _crm_say(f"🗄️ {h.get('name', '')} · archived")


def habit_delete(hid):
    import api_v2
    h = _habit_by_id(hid)
    if h is None:
        _crm_say("🔄 Habit not found (offline?)")
        return
    if _dialog(f"Delete habit {h.get('name', '')!r} and its history?",
               ["Cancel", "Delete"], "Cancel") != "Delete":
        return
    v2 = api_v2.TickTickV2()
    if not v2.token or not v2.habits_batch(delete=[hid]):
        _crm_say("🔄 Delete failed (offline?)")
        return
    _hb_patch(delete_id=hid)
    _crm_say(f"🗑️ {h.get('name', '')} · deleted")


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
    r = _osa_dialog(osa)
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
    """Bar ⤒↑↓⤓ reorder: restamp the subtask's sortOrder among the OPEN
    children (midpoint insertion; a collapsed gap re-spreads the lot -
    sortOrder IS the display order, childIds is creation order). Prints
    "reordered" on success - the bar greps stdout for it."""
    cur = _current_focus_task()
    if not cur:
        print("🎯 No task-linked session running")
        return
    fpid, ftid = cur[0], cur[1]
    open_children, _cids = _children_state(fpid, ftid)
    ordered = sorted(open_children, key=lambda t: t.get("sortOrder") or 0)
    pos = next((i for i, t in enumerate(ordered) if t.get("id") == tid), None)
    if pos is None:
        print("")
        return
    orders = [t.get("sortOrder") or 0 for t in ordered]
    new = fsub.move_order(orders, pos, direction)
    if new is None:
        print("")
        return
    api = _api()
    from dispatch import _patch_task_cache
    if new == fsub.RESPREAD:
        seq = list(ordered)
        tgt = {"up": pos - 1, "down": pos + 1, "top": 0,
               "bottom": len(seq) - 1}[direction]
        seq.insert(tgt, seq.pop(pos))
        for t, so in zip(seq, fsub.respread(len(seq),
                                            min(orders) - fsub.SORT_STEP)):
            api.update_task(t["id"], t.get("projectId") or fpid,
                            current=t, sortOrder=so)
            _patch_task_cache(t["id"], sortOrder=so)
    else:
        t = ordered[pos]
        api.update_task(tid, t.get("projectId") or fpid, current=t,
                        sortOrder=new)
        _patch_task_cache(tid, sortOrder=new)
    print("reordered")


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
            plog = person_autolog(tid)
            _complete_cache_patch(pid, tid)
            print(f"✅ {title[:40]} completed{plog}")
        except Exception as e:
            print(f"✅ complete failed: {type(e).__name__}")
        return
    ps = _pomo_sidecar()
    if ps and ps.get("tid"):
        pid, tid, title = ps["pid"], ps["tid"], ps["title"]
        pomo_abandon()
        try:
            _api().complete_task(pid, tid)
            plog = person_autolog(tid)
            _complete_cache_patch(pid, tid)
            print(f"✅ {title[:40]} completed{plog}")
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
        elif verb == "focus_backlog":
            focus_backlog(rest)
        elif verb == "countdown_new":
            countdown_new(rest)
        elif verb == "countdown_edit":
            f, _, cid = rest.partition(":"); countdown_edit(f, cid)
        elif verb == "countdown_appear":
            cid, _, val = rest.partition(":"); countdown_appear(cid, val)
        elif verb == "countdown_flip":
            countdown_flip(rest)
        elif verb == "countdown_archive":
            countdown_archive(rest)
        elif verb == "countdown_delete":
            countdown_delete(rest)
        elif verb == "habit_tick":
            habit_tick(rest)
        elif verb == "habit_tick_past":
            habit_tick_past(rest)
        elif verb == "habit_untick":
            habit_untick(rest)
        elif verb == "habit_skip":
            habit_skip(rest)
        elif verb == "habit_note":
            habit_note(rest)
        elif verb == "habit_new":
            habit_new(rest)
        elif verb == "habit_archive":
            habit_archive(rest)
        elif verb == "habit_delete":
            habit_delete(rest)
        elif verb == "task_copy":
            pid, tid = rest.split(":", 1); task_copy(pid, tid)
        elif verb == "task_copy_full":
            pid, tid = rest.split(":", 1); task_copy(pid, tid, full=True)
        elif verb == "buffer_copy":
            buffer_copy(full=(rest == "full"))
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
            crmperson(rest)
        elif verb == "crmimport":
            crmimport()
        elif verb == "crmpast":
            crmpast(rest)
        elif verb == "crmsched":
            pid, tid = rest.split(":", 1)
            crmsched(pid, tid)
        elif verb == "crmprep":
            pid, tid = rest.split(":", 1)
            crmprep(pid, tid)
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
        elif verb == "cdest":
            _lb, _, _back = rest.partition(":")
            content_dest(_lb, back=_back)
        elif verb == "eaglefolder":
            eagle_folder(rest)
        elif verb == "sessphotos":
            log_tid, _, stage = rest.partition(":")
            session_photos(log_tid, stage)
        elif verb == "photoattach":
            pid, tid = rest.split(":", 1)
            photo_attach(pid, tid)
        elif verb == "eaglesweep":
            eagle_sweep()
        elif verb == "notego":
            note_go(rest)
        elif verb == "triage":
            eagle_triage(rest)
        elif verb == "editthis":
            edit_this(rest)
        elif verb == "promotesel":
            promote_selection()
        elif verb == "filedited":
            file_edited()
        elif verb == "portfolio":
            to_portfolio()
        elif verb == "posted":
            content_posted(rest)
        elif verb == "cretire":
            content_retire(rest)
        elif verb == "eaglego":
            eagle_open(rest)
        elif verb == "peek":
            img_peek(rest)
        elif verb == "imgopen":
            img_open(rest)
        elif verb == "imglink":
            img_link(rest)
        elif verb == "imgpost":
            img_post(rest)
        elif verb == "imgattach":
            img_attach(rest)
        elif verb == "imgtrash":
            img_trash(rest)
        elif verb == "imgmove":
            img_move(rest)
        elif verb == "bulkmove":
            bulk_move(rest)
        elif verb == "crmbrowse":
            crmbrowse(rest)
        elif verb == "bridge_daily":
            bridge_daily()
        elif verb == "bridge_proj":
            bridge_proj(rest)
        elif verb == "bridge_copy":
            bridge_copy(rest)
        elif verb == "bridge_tidy":
            bridge_tidy()
        elif verb == "bridge_setlist":
            bridge_setlist()
        elif verb == "search_pre":
            search_pre(rest)
        elif verb == "person_new":
            person_new(rest)
        elif verb == "person_log":
            person_log(rest)
        elif verb == "person_bday":
            person_bday(rest)
        elif verb == "person_archive":
            person_archive(rest)
        elif verb == "person_attach":
            person_attach(rest)
        elif verb == "person_idea":
            person_idea(rest)
        elif verb == "person_fact":
            person_fact(rest)
        elif verb == "person_edit":
            person_edit(rest)
        elif verb == "person_idea_from":
            person_idea_from(rest)
        elif verb == "person_setup":
            person_setup()
        elif verb == "people_setlist":
            people_setlist()
        elif verb == "add_pre":
            add_pre(rest)
        elif verb == "crmtrash":
            crm_trash(rest)
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
        elif verb == "fx_unstage":
            pid, tid = rest.split(":", 1); fx_unstage(pid, tid)
        elif verb == "fx_oneliner":
            fx_oneliner()
        elif verb == "open_task":
            pid, tid = rest.split(":", 1); open_task(pid, tid)
        elif verb == "inboxempty":
            inboxempty()
        elif verb == "view_buffer":
            view_buffer(rest)
        elif verb == "dateclear":
            dateclear(rest)
        elif verb == "dateroll":
            dateroll(rest)
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
