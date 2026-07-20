#!/usr/bin/env python3
"""
Action dispatcher - called by Alfred after item selection.

Arg format (from Script Filter items):
  open:<url>              → open TickTick deep link
  copy:<url>              → copy to clipboard, print confirmation
  complete:<pid>:<tid>:<title>  → complete task via API, print confirmation
  create:<base64json>     → create task via API, print confirmation
"""
import sys
import os
import re
import json
import base64
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

import config as cfg
from api import TickTickAPI, RateLimitError
import cache as cache_store
import areas
import reminders as rem
from dateutil import utc_to_local_display, utc_to_long_display
from script_base import run_path

# CRM booking flow - a new CRM task carrying a booking tag auto-prefills a
# "Prepare for …" follow-up (a 🔥prepare task has no booking tag → never loops).
CRM_ID       = areas.CRM_ID   # Configure panel; empty = booking flow dormant
BOOKING_TAGS = areas.BOOKING_TAGS   # single source (add_task gates chords on it)
ALFRED_APP   = "com.runningwithcrayons.Alfred"
WF_BUNDLE    = "com.vex.tickal"


def _fire_add_prefill(query):
    """Open the workflow's Add window pre-typed with `query` via Alfred's external
    trigger (no extra wiring). Shared by the CRM booking auto-flow and the manual
    "Add Prepare" action so both open the same prefilled window."""
    osa = ('on run argv\n'
           f'tell application id "{ALFRED_APP}" to run trigger "Add" '
           f'in workflow "{WF_BUNDLE}" with argument (item 1 of argv)\n'
           'end run')
    subprocess.run(["osascript", "-e", osa, query], check=False)


# Act-again: attribute changes reopen the ⌘ Actions menu for the same
# task - fresh values on every row, esc dismisses. Alfred is closed by the time
# dispatch runs, so the external-trigger fire opens a live window (same timing
# pattern as the CRM prepare prefill above).
ACT_AGAIN = ("attr_date:", "attr_span:", "attr_cleardate:", "attr_priority:",
             "attr_tag:", "attr_tags_multi:", "attr_tag_remove:",
             "attr_tag_clear:", "attr_move:", "attr_rename:")


def _reopen_actions(pid, tid):
    """Write the task context (dispatch is the temp file's ONLY writer;
    ensure_task_context is its only reader) and fire the Actions trigger."""
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as f:
            f.write(f"{pid}:{tid}")
    except OSError:
        return
    osa = (f'tell application id "{ALFRED_APP}" to run trigger "Actions" '
           f'in workflow "{WF_BUNDLE}"')
    subprocess.run(["osascript", "-e", osa], check=False)


def _ensure_tags_exist(tags, parents=None):
    """Tags unknown to the cache become REAL entities before the task write
    (the pickers offer ➕ new-tag rows; `parents` maps lowercase name →
    parent tag for the nest-under-parent flow). NOTE: a plain v1 task write
    does NOT create the tag entity - without a v2 token the label still
    attaches to the task, the entity just waits for the app/token.
    Best-effort, never blocks the write."""
    try:
        from display import tag_match_key
        # emoji-blind, like the ➕ picker guards - a hand-typed '#logbook'
        # must not coin a bald twin of '📓Logbook'
        known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
        fresh, seen_l = [], set()
        for t in (tags or []):
            tl = tag_match_key(t)
            if tl not in known and tl not in seen_l:   # ci intra-batch dedup
                fresh.append(str(t))
                seen_l.add(tl)
        if not fresh:
            return
        import api_v2
        v2 = api_v2.TickTickV2()
        created = [t for t in fresh
                   if v2.create_tag(t, (parents or {}).get(str(t).lower()))]
        if created:
            cache_store.set("tags", (cache_store.get("tags") or []) + created)
    except Exception:
        pass


def _pd_key(pid):
    """project_data cache key for a pid. The API reports the inbox as
    'inbox<digits>' but sync stores it under the literal 'inbox' key -
    map it, or every inbox mirror silently misses (fresh inbox adds/changes
    stay invisible in the inbox screens until the hourly sync)."""
    return ("project_data_inbox" if str(pid).startswith("inbox")
            else f"project_data_{pid}")


def _norm_tags(tags):
    """Deduped lowercase tags. TickTick lowercases tag names server-side
    (labels keep their case) - caching as-typed case splits the tag screens
    into ✅Todo/✅todo duplicate groups until the next sync."""
    return list(dict.fromkeys(str(t).lower() for t in (tags or [])))


def _patch_project_data(tid, fields=None, pid_old=None, pid_new=None, remove=False):
    """Mirror a task patch into the project_data_{pid} caches. The per-list
    browse screens (incl. the CRM drill) read project_data, NOT all_tasks -
    without this mirror a fresh change is invisible there until the hourly
    sync. No-op for lists whose project_data was never cached."""
    try:
        if pid_old and pid_old != pid_new:
            pd = cache_store.get(_pd_key(pid_old))
            if pd:
                pd = dict(pd)
                pd["tasks"] = [t for t in pd.get("tasks", []) if t.get("id") != tid]
                cache_store.set(_pd_key(pid_old), pd)
        pid = pid_new or pid_old
        if not pid:
            return
        key = _pd_key(pid)
        pd = cache_store.get(key)
        if pd is None:
            return
        pd = dict(pd)
        tasks = list(pd.get("tasks", []))
        if remove:
            tasks = [t for t in tasks if t.get("id") != tid]
        else:
            hit = False
            for i, t in enumerate(tasks):
                if t.get("id") == tid:
                    nt = dict(t)
                    nt.update(fields or {})
                    tasks[i] = nt
                    hit = True
            if not hit:
                src = _cached_task(tid)
                if src:
                    tasks.append(dict(src))
        pd["tasks"] = tasks
        cache_store.set(key, pd)
    except Exception:
        pass


def _buffer_apply(fn):
    """Run fn(pid, tid, cached_task) over every buffered task (🧺).
    Skips strays that error; clears the buffer afterwards. Returns count."""
    done = 0
    try:
        with open(run_path("tickal_buffer.txt")) as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        lines = []
    for ln in lines:
        try:
            bpid, btid = ln.split(":", 1)
            fn(bpid, btid, _cached_task(btid) or {})
            done += 1
        except Exception:
            pass
    try:
        open(run_path("tickal_buffer.txt"), "w").close()
    except OSError:
        pass
    return done


def _patch_task_cache(tid, **fields):
    """Update specific fields on a task in the all_tasks cache without a full
    wipe, then mirror into the per-list project_data cache."""
    try:
        cached = cache_store.get("all_tasks")
        if cached is None:
            return
        pid_old = pid_new = None
        updated = []
        for t in cached:
            if t.get("id") == tid:
                pid_old = t.get("projectId") or t.get("_projectId")
                t = dict(t)
                t.update(fields)
                pid_new = t.get("projectId") or t.get("_projectId")
            updated.append(t)
        cache_store.set("all_tasks", updated)
        _patch_project_data(tid, fields, pid_old, pid_new)
    except Exception:
        cache_store.invalidate("all_tasks")


def _cached_task(tid):
    """Cached task/note for tid (avoids a live GET), or None. See cache.find_task."""
    return cache_store.find_task(tid)


def _split_reminders(raw):
    """Pull a trailing ';R:tok1,tok2' off an attr arg → (raw_without, [tokens])."""
    if ";R:" in raw:
        base, rempart = raw.split(";R:", 1)
        return base, [t for t in rempart.split(",") if t]
    return raw, []


def _merge_reminders(api, pid, tid, current, tokens):
    """Merge reminder tokens (→ TRIGGER strings) into the task's existing
    reminders. Returns (merged_list, resolved_current). Dedup, order preserved."""
    if current is None:
        try:
            current = api.get_task(pid, tid)
        except Exception:
            current = {}
    existing = (current or {}).get("reminders") or []
    triggers = [t for t in (rem.trigger(tok) for tok in tokens) if t]
    merged = list(dict.fromkeys(list(existing) + triggers))
    return merged, current


def main():
    if len(sys.argv) < 2:
        return

    arg = sys.argv[1]

    try:
        if arg.startswith("open:"):
            url = arg[5:]
            subprocess.run(["open", url], check=False)
            # no output → notification node shows nothing

        elif arg.startswith("docsopen:"):
            # docsopen:<notification text>|<url> - like open:, but tells the
            # user what just opened (the docs browser rows ride this).
            text, _, url = arg[9:].partition("|")
            if url:
                subprocess.run(["open", url], check=False)
            print(text)

        elif arg.startswith("copy:"):
            payload = arg[5:]
            subprocess.run(["pbcopy"], input=payload.encode(), check=False)
            task_title = os.environ.get("task_title", "")
            # Bare TickTick ids ride the same verb as URLs (Copy id rows)
            what = "URL" if "://" in payload else "id"
            title = (f"{task_title} · {what} Copied" if task_title
                     else f"{what} Copied")
            print(f"{title}\n{payload}")

        elif arg.startswith("complete:"):
            # complete:projectId:taskId:title
            parts = arg[9:].split(":", 2)
            if len(parts) < 2:
                print("Error: malformed complete arg")
                return
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"

            # Snapshot the task before completing so we can add it to the
            # local completed-tasks log (the Open API doesn't expose completed tasks)
            try:
                all_tasks = cache_store.get("all_tasks") or []
                snap = next((t for t in all_tasks if t["id"] == tid), None)
                if snap:
                    from datetime import datetime, timezone
                    snap = dict(snap)
                    snap["status"] = 2
                    snap["completedTime"] = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S+0000"
                    )
                    completed = cache_store.get("completed_tasks") or []
                    completed = [t for t in completed if t.get("id") != tid]
                    completed.insert(0, snap)
                    cache_store.set("completed_tasks", completed[:200])
            except Exception:
                pass

            # Complete-guard: completing the CURRENT focus task also ends
            # its session (sweep + note + record) - BEFORE the complete,
            # while the task is guaranteed still GET-able. A matching pomo
            # sidecar is left alone (the app's pomo keeps running).
            guard_note = ""
            try:
                with open(run_path("tickal_focus.json")) as _ff:
                    _fst = json.load(_ff)
                if _fst.get("tid") == tid:
                    import io
                    import contextlib
                    _xdir = os.path.join(os.path.dirname(SCRIPT_DIR), "Scripts")
                    if _xdir not in sys.path:
                        sys.path.insert(0, _xdir)
                    import xact as _xact
                    _buf = io.StringIO()
                    with contextlib.redirect_stdout(_buf):
                        _xact.focus_stop()
                    _out = _buf.getvalue().strip()
                    if _out:
                        guard_note = "\n" + _out
            except Exception:
                pass

            api = TickTickAPI(cfg.get_token())
            api.complete_task(pid, tid)
            # Remove task from all_tasks in-place (no full cache wipe),
            # and from the per-list cache the browse screens read
            try:
                cached = cache_store.get("all_tasks")
                if cached is not None:
                    cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
                _patch_project_data(tid, pid_old=pid, remove=True)
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} completed{guard_note}")

        elif arg.startswith("attr_date:"):
            # attr_date:projectId:taskId:isoDate[;R:tok,tok]
            raw = arg[10:]
            raw, rem_tokens = _split_reminders(raw)
            parts = raw.split(":", 2)
            pid, tid, due = parts[0], parts[1], parts[2]

            # Snapshot old date before overwriting (for "rescheduled" notification)
            had_date = os.environ.get("has_date", "0") == "1"
            old_due = None
            if had_date:
                try:
                    all_tasks = cache_store.get("all_tasks") or []
                    snap = next((t for t in all_tasks if t["id"] == tid), None)
                    if snap:
                        old_due = snap.get("dueDate") or snap.get("startDate")
                except Exception:
                    pass

            api = TickTickAPI(cfg.get_token())
            current = _cached_task(tid)
            fields = {"startDate": due, "dueDate": due}
            if rem_tokens:
                fields["reminders"], current = _merge_reminders(api, pid, tid, current, rem_tokens)
            api.update_task(tid, pid, current=current, **fields)
            _patch_task_cache(tid, **fields)

            task_title = os.environ.get("task_title", "Task")
            verb = "Rescheduled" if had_date else "Scheduled"
            rem_line = f"\n🔔 {', '.join(rem.human(t) for t in rem_tokens)}" if rem_tokens else ""
            new_display = utc_to_long_display(due)
            if had_date and old_due:
                old_display = utc_to_long_display(old_due)
                print(f"{verb} · {task_title}\n🟢 {new_display}\n🔴 {old_display}{rem_line}")
            else:
                print(f"{verb} · {task_title}\n{new_display}{rem_line}")

        elif arg.startswith("attr_span:"):
            # attr_span:projectId:taskId:startIso|endIso[;R:tok,tok]  → schedule with duration
            raw = arg[10:]
            raw, rem_tokens = _split_reminders(raw)
            parts = raw.split(":", 2)
            pid, tid = parts[0], parts[1]
            start_iso, end_iso = parts[2].split("|", 1)

            had_date = os.environ.get("has_date", "0") == "1"
            api = TickTickAPI(cfg.get_token())
            current = _cached_task(tid)
            fields = {"startDate": start_iso, "dueDate": end_iso}
            if rem_tokens:
                fields["reminders"], current = _merge_reminders(api, pid, tid, current, rem_tokens)
            api.update_task(tid, pid, current=current, **fields)
            _patch_task_cache(tid, **fields)

            task_title = os.environ.get("task_title", "Task")
            verb = "Rescheduled" if had_date else "Scheduled"
            start_disp = utc_to_long_display(start_iso)
            end_disp   = utc_to_local_display(end_iso)[11:16]  # HH:MM
            # Duration label from the two timestamps
            from datetime import datetime
            s = datetime.strptime(start_iso[:19], "%Y-%m-%dT%H:%M:%S")
            e = datetime.strptime(end_iso[:19], "%Y-%m-%dT%H:%M:%S")
            mins = int((e - s).total_seconds() // 60)
            h, m = divmod(mins, 60)
            dur = (f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m")
            print(f"{verb} · {task_title}\n🟢 {start_disp} → {end_disp}  ({dur})")

        elif arg.startswith("attr_cleardate:"):
            # attr_cleardate:projectId:taskId
            raw = arg[15:]
            pid, tid = raw.split(":", 1)
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, current=_cached_task(tid), startDate=None, dueDate=None)
            _patch_task_cache(tid, startDate=None, dueDate=None)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} · Unscheduled")

        elif arg.startswith("attr_priority:"):
            # attr_priority:projectId:taskId:priorityInt
            raw = arg[14:]
            parts = raw.split(":", 2)
            pid, tid, pval = parts[0], parts[1], int(parts[2])
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, current=_cached_task(tid), priority=pval)
            _patch_task_cache(tid, priority=pval)
            labels = {0: "None", 1: "Low", 3: "Medium", 5: "High"}
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} → {labels.get(pval, pval)}")

        elif arg.startswith("attr_tag:"):
            # attr_tag:projectId:taskId:tagName
            raw = arg[9:]
            parts = raw.split(":", 2)
            pid, tid, tag = parts[0], parts[1], parts[2]
            _ensure_tags_exist([tag])
            api = TickTickAPI(cfg.get_token())
            # Prefer the cached task (no live GET); fetch only if not cached
            task = _cached_task(tid)
            if task is None:
                try:
                    task = api.get_task(pid, tid)
                except Exception:
                    task = {}
            existing = task.get("tags") or []
            merged = _norm_tags(existing + [tag])  # deduplicated, lowercase (server case)
            api.update_task(tid, pid, current=(task or None), tags=merged)
            _patch_task_cache(tid, tags=merged)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} tagged #{tag}")

        elif arg.startswith("attr_tags_multi:"):
            # attr_tags_multi:projectId:taskId:tag1,tag2,tag3
            raw = arg[16:]
            parts = raw.split(":", 2)
            pid, tid, tags_csv = parts[0], parts[1], parts[2]
            new_tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
            _ensure_tags_exist(new_tags)
            api = TickTickAPI(cfg.get_token())
            if tid == "BUFFER":
                # 🧺 apply to every buffered task
                done = _buffer_apply(lambda bpid, btid, cur:
                    (api.update_task(btid, bpid, current=cur,
                                     tags=_norm_tags((cur.get("tags") or []) + new_tags)),
                     _patch_task_cache(btid, tags=_norm_tags((cur.get("tags") or []) + new_tags))))
                print(f"🅿️ {done} tasks tagged {'  '.join('#'+t for t in new_tags)}")
                return
            current = _cached_task(tid) or api.get_task(pid, tid)
            existing = current.get("tags") or []
            merged = _norm_tags(existing + new_tags)
            api.update_task(tid, pid, current=current, tags=merged)
            _patch_task_cache(tid, tags=merged)
            task_title = os.environ.get("task_title", "Task")
            tags_display = "  ".join(f"#{t}" for t in new_tags)
            print(f"{task_title} tagged {tags_display}")

        elif arg.startswith("attr_tag_remove:"):
            # attr_tag_remove:projectId:taskId:tagName
            raw = arg[16:]
            parts = raw.split(":", 2)
            pid, tid, tag = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            current = _cached_task(tid) or api.get_task(pid, tid)
            updated = [t for t in (current.get("tags") or []) if t.lower() != tag.lower()]
            api.update_task(tid, pid, current=current, tags=updated)
            _patch_task_cache(tid, tags=updated)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} tag #{tag} removed")

        elif arg.startswith("attr_tag_clear:"):
            # attr_tag_clear:projectId:taskId
            raw = arg[15:]
            pid, tid = raw.split(":", 1)
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, current=_cached_task(tid), tags=[])
            _patch_task_cache(tid, tags=[])
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} · all tags removed")

        elif arg.startswith("attr_move:"):
            # attr_move:oldProjectId:taskId:newProjectId
            raw = arg[10:]
            parts = raw.split(":", 2)
            old_pid, tid, new_pid = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            if tid == "BUFFER":
                # 🧺 move every buffered task
                projects = cache_store.get("projects") or []
                new_list = next((p["name"] for p in projects if p["id"] == new_pid), "")
                def _mv(bpid, btid, cur):
                    api.move_task(btid, bpid, new_pid)
                    _patch_task_cache(btid, projectId=new_pid, _projectId=new_pid,
                                      _projectName=new_list, columnId=None,
                                      _columnName="", parentId=None)
                done = _buffer_apply(_mv)
                print(f"🅿️ {done} tasks moved to {new_list or 'list'}")
                return
            api.move_task(tid, old_pid, new_pid)
            task_title = os.environ.get("task_title", "Task")
            projects = cache_store.get("projects") or []
            new_list = next((p["name"] for p in projects if p["id"] == new_pid), "")
            _patch_task_cache(tid,
                              projectId=new_pid,
                              _projectId=new_pid,
                              _projectName=new_list,
                              columnId=None,
                              _columnName="",
                              parentId=None)
            print(f"{task_title} moved to {new_list}" if new_list else f"{task_title} moved")

        elif arg.startswith("attr_rename:"):
            # attr_rename:projectId:taskId:newTitle
            raw = arg[12:]
            parts = raw.split(":", 2)
            pid, tid, new_title = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, current=_cached_task(tid), title=new_title)
            _patch_task_cache(tid, title=new_title)
            print(f"{new_title} renamed")

        elif arg.startswith("uncomplete:"):
            # uncomplete:projectId:taskId:title
            parts = arg[11:].split(":", 2)
            if len(parts) < 2:
                print("Error: malformed uncomplete arg")
                return
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, status=0)
            # Remove from local completed log and restore to all_tasks in-place
            try:
                completed = cache_store.get("completed_tasks") or []
                snap = next((t for t in completed if t.get("id") == tid), None)
                completed = [t for t in completed if t.get("id") != tid]
                cache_store.set("completed_tasks", completed)
                cached = cache_store.get("all_tasks")
                if cached is not None and snap is not None:
                    restored = dict(snap)
                    restored["status"] = 0
                    restored.pop("completedTime", None)
                    cached = [t for t in cached if t.get("id") != tid]
                    cached.append(restored)
                    cache_store.set("all_tasks", cached)
                    _patch_project_data(tid, pid_old=pid)
                elif snap is None or cached is None:
                    # no snap to restore - invalidate, or the reopened task
                    # stays invisible until the hourly sync
                    cache_store.invalidate("all_tasks")
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} uncompleted")

        elif arg.startswith("attr_delete:"):
            # attr_delete:projectId:taskId:title
            raw = arg[12:]
            parts = raw.split(":", 2)
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"
            api = TickTickAPI(cfg.get_token())
            api.delete_task(pid, tid)
            try:
                # all_notes too - the CRM records pickers read it, and a
                # deleted customer/logbook otherwise haunts them until the
                # next sync (smoke finding 2026-07-17).
                for key in ("all_tasks", "all_notes"):
                    cached = cache_store.get(key)
                    if cached is not None:
                        cache_store.set(key, [t for t in cached
                                              if t.get("id") != tid])
                _patch_project_data(tid, pid_old=pid, remove=True)
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} deleted")

        elif arg.startswith("create_project_meta:"):
            # create_project_meta:<base64 {name, tag, emoji}>
            # Creates a project list in the Projects folder, then re-opens the Add
            # window prefilled with its 📌CTA task (same driver's-seat flow as the
            # CRM prepare follow-up) so the CTA gets SCHEDULED before it's created.
            raw = arg[20:]
            payload = json.loads(base64.b64decode(raw))
            name  = payload.get("name", "").strip()
            tag   = payload.get("tag", "")
            emoji = payload.get("emoji", "")
            if not name:
                print("Error: project has no name")
                return

            folder_id = areas.PROJECTS_FOLDER_ID   # "" → project lands ungrouped
            cta_list  = areas.CTA_LIST_ID

            api = TickTickAPI(cfg.get_token())
            list_name = f"💼P • {name} {emoji}".rstrip()
            proj = api.create_project(list_name, group_id=folder_id)
            pid = proj.get("id") if isinstance(proj, dict) else None
            if not pid:
                cache_store.invalidate("projects")
                print("Error: list created but no id returned · CTA skipped")
                return

            # Update the projects cache in-place so the new list resolves at once
            try:
                projects_cache = cache_store.get("projects")
                if projects_cache is not None:
                    projects_cache.append(proj)
                    cache_store.set("projects", projects_cache)
            except Exception:
                cache_store.invalidate("projects")

            url = f"ticktick:///webapp/#p/{pid}/tasks"
            cta_title = f"💼 P • [{name}]({url}) 🔗"
            if not cta_list:
                # No 📌CTA list configured - the project stands alone.
                print(f"💼 {name} created")
            elif tag:
                # Token order (~l … then #tag) keeps the multi-word ~l from
                # swallowing the title - same trick as the CRM prepare prefill.
                # The CTA itself is created by the normal create: path on ⏎,
                # which also handles the all_tasks cache.
                _fire_add_prefill(f"~l {areas.cta_list_name()} #{tag} {cta_title}")
                print(f"💼 {name} created · schedule its 📌CTA")
            else:
                # No tag to close the ~l token safely - create the CTA directly.
                api.create_task(title=cta_title, project_id=cta_list)
                cache_store.invalidate("all_tasks")
                print(f"💼 {name} created")

        elif arg.startswith("create_list:"):
            raw = arg[12:]
            payload = json.loads(base64.b64decode(raw))
            name = payload.get("name", "").strip()
            if not name:
                print("Error: list has no name")
                return
            api = TickTickAPI(cfg.get_token())
            api.create_project(name, group_id=payload.get("groupId"))
            cache_store.invalidate("projects")
            cache_store.invalidate("all_tasks")
            print(f"{name} created")

        elif arg.startswith("cta:"):
            # cta:<base64 {mode, pid, tid, title}> - the one dynamic "Add CTA /
            # Prepare" Actions row. Every mode opens the Add window prefilled (via
            # the shared helper) so the CTA/Prepare task can be SCHEDULED before it
            # is created - same "back in the driver's seat" flow as CRM bookings.
            spec   = json.loads(base64.b64decode(arg[4:]))
            action = areas.build_action(spec.get("mode"), spec.get("pid", ""),
                                        spec.get("tid", ""), spec.get("title", ""))
            # Emit the prefill query as this node's OUTPUT. The canvas routes it to a
            # Call-External-Trigger → "Add" (pass input as argument = Yes), so the Add
            # window opens NATIVELY and stays interactive (schedule via *, / menu…).
            # osascript-ing "Add" from inside an Actions action yields a non-focused
            # window; that path (_fire_add_prefill) is only safe post-create, which is
            # why the CRM booking auto-flow still uses it.
            sys.stdout.write(action["query"])

        elif arg.startswith("create:"):
            raw = arg[7:]
            payload = json.loads(base64.b64decode(raw))
            title = payload.get("title", "").strip()
            if not title:
                print("Error: task has no title")
                return
            _ensure_tags_exist(payload.get("tags"), payload.get("_tag_parents"))
            # CRM calendar tasks are always high priority (Vex ruling
            # 2026-07-20); an explicit ! token still wins.
            if CRM_ID and payload.get("projectId") == CRM_ID \
                    and not payload.get("priority"):
                payload["priority"] = 5
            api = TickTickAPI(cfg.get_token())
            result = api.create_task(
                title=title,
                project_id=payload.get("projectId"),
                due_date=payload.get("dueDate"),
                start_date=payload.get("startDate"),
                content=payload.get("content"),
                priority=payload.get("priority", 0),
                tags=_norm_tags(payload.get("tags")) or None,
                column_id=payload.get("columnId", None),
                parent_id=payload.get("parentId"),
                kind=payload.get("kind"),
                repeat_flag=payload.get("repeatFlag"),
                reminders=payload.get("reminders"),
            )
            # Update all_tasks in-place so searches work immediately after create
            proj_id = payload.get("projectId", "")
            if result and result.get("id"):
                try:
                    projects_cache = cache_store.get("projects") or []
                    proj = next((p for p in projects_cache if p["id"] == proj_id), None)
                    new_entry = dict(result)
                    if new_entry.get("tags"):
                        new_entry["tags"] = _norm_tags(new_entry["tags"])
                    new_entry["_projectId"]   = proj_id or "inbox"
                    new_entry["_projectName"] = (proj.get("name", "") if proj
                                                 else ("Inbox" if not proj_id else ""))
                    new_entry["_columnName"]  = ""
                    cached_tasks = cache_store.get("all_tasks") or []
                    cached_tasks = [t for t in cached_tasks if t.get("id") != result["id"]]
                    cached_tasks.append(new_entry)
                    cache_store.set("all_tasks", cached_tasks)

                    # Mirror into the per-list cache the browse screens read
                    # (CRM drill etc.) - else the fresh add is invisible there
                    # until the hourly sync.
                    real_pid = result.get("projectId") or proj_id
                    pd_key = _pd_key(real_pid)
                    pd = cache_store.get(pd_key)
                    if pd is not None:
                        pd = dict(pd)
                        pd["tasks"] = ([t for t in pd.get("tasks", [])
                                        if t.get("id") != result["id"]] + [new_entry])
                        cache_store.set(pd_key, pd)

                    # Inject into all_notes for any kind=NOTE item (any project)
                    if result.get("kind") == "NOTE":
                        all_notes = cache_store.get("all_notes") or []
                        all_notes = [n for n in all_notes if n.get("id") != result["id"]]
                        all_notes.insert(0, new_entry)
                        cache_store.set("all_notes", all_notes)
                except Exception:
                    cache_store.invalidate("all_tasks")  # fallback

            # / add-flow "🖼️ Add image": upload the clipboard image as a real
            # attachment to the task we just created (needs its id + projectId).
            attach_note = ""
            if payload.get("_attach_image") and result and result.get("id"):
                try:
                    import clipboard as clip_util
                    import api_v2
                    img = clip_util.png_bytes()
                    if not img:
                        attach_note = "\n🖼️ no image on clipboard · task created without it"
                    else:
                        up_pid = result.get("projectId") or proj_id
                        api_v2.TickTickV2().upload_attachment(
                            up_pid, result["id"], img, "screenshot.png")
                        attach_note = "\n🖼️ image attached"
                except Exception as e:
                    attach_note = f"\n🖼️ image not attached · {e}"

            # CRM booking → auto-prefill a "Prepare for …" follow-up. Fires only
            # when the new task carries a booking tag, so the 🔥prepare follow-up
            # itself (and any non-booking CRM add) never re-triggers it - loop-proof.
            # Re-opens the Add window pre-typed via osascript (no extra wiring); the
            # booking is already in the all_tasks cache above, so [[title]] resolves
            # to its link on the next ⏎. Token order (~l … then #) keeps the multi-
            # word ~l from swallowing the title and lands on the preview, not a picker.
            tags_lc = {str(t).lower() for t in (payload.get("tags") or [])}
            # S2+ titles are session-done-chained continuation sessions
            # (records flow; marker is a SUFFIX, legacy prefix tolerated) -
            # session 5 of a sleeve needs no fresh Prepare. S1 / unnumbered
            # bookings keep the follow-up.
            _s = re.search(r"^S(\d+)\s|\bS(\d+)\s*$", title or "")
            _continuation = bool(_s and int(_s.group(1) or _s.group(2)) >= 2)
            if (CRM_ID and proj_id == CRM_ID and result and result.get("id")
                    and (tags_lc & BOOKING_TAGS) and not _continuation):
                # Link-bearing titles (records S1/Consult bookings) must NOT
                # be wrapped raw in [[ ]] - the Prepare gets the LOGBOOK as
                # its reference instead (see areas.prepare_wikilink_target).
                _tgt, _wl = areas.prepare_wikilink_target(title)
                _ref = f"[[{_tgt}]]" if _wl else _tgt
                _fire_add_prefill(
                    f"~l {areas.crm_list_name()} #{areas.PREPARE_TAG} "
                    f"Prepare for {_ref}")

            notif = payload.get("_notif_text") or f"Task added to {payload.get('listName') or 'Inbox'}"
            print(notif + attach_note)

            # Post-create chaining (the / menu's +stage / +focus rows; the
            # preview row's ⌘/⇧⌘ chords add _post_fstart): stage
            # the new task, push it into the running focus block, or open the
            # ⏱/🍅 start flow on it, so add → search → stage collapses into
            # one flow. CRM's Prepare window keeps priority; act-again yields
            # to an explicit chain.
            _crm_chained = bool(CRM_ID and proj_id == CRM_ID
                                and tags_lc & BOOKING_TAGS and not _continuation)
            _post_done = False
            if (result and result.get("id") and not _crm_chained
                    and (payload.get("_post_stage") or payload.get("_post_fx")
                         or payload.get("_post_fstart"))):
                try:
                    _xdir = os.path.join(os.path.dirname(SCRIPT_DIR), "Scripts")
                    if _xdir not in sys.path:
                        sys.path.insert(0, _xdir)
                    import xact as _xact
                    _new_pid = result.get("projectId") or proj_id
                    if payload.get("_post_fx"):
                        import io as _io
                        import contextlib as _ctx
                        _buf = _io.StringIO()
                        with _ctx.redirect_stdout(_buf):
                            _xact.fx_add(_new_pid, result["id"])
                        _out = _buf.getvalue().strip()
                        if _out:
                            print(_out)   # success line OR the no-session guard
                        _post_done = "No task-linked" not in _out
                    if payload.get("_post_fstart"):
                        _xact.focus_open(_new_pid, result["id"])
                        _post_done = True
                    if payload.get("_post_stage"):
                        _xact.stage_open(_new_pid, result["id"])
                        _post_done = True
                except Exception:
                    # _post_done stays False → act-again still runs
                    print("⚠ post-create focus step failed · task created fine")

            # Act-again: a subtask added from the ⌘ Actions menu loops back to
            # the parent's Actions menu (CRM bookings take the Prepare window
            # instead - the two never overlap).
            _parent = payload.get("parentId")
            if _parent and not _crm_chained and not _post_done:
                _reopen_actions(result.get("projectId") or proj_id, _parent)

        elif arg.startswith("xact:"):
            # Add-window rows can carry xact verbs (the T tag scope) -
            # the raw-URL fallback below would open() them. In-process like
            # the _post_stage chain; stdout still lands in the notification.
            _xdir = os.path.join(os.path.dirname(SCRIPT_DIR), "Scripts")
            if _xdir not in sys.path:
                sys.path.insert(0, _xdir)
            import xact as _xact
            _argv = sys.argv
            sys.argv = [_argv[0] if _argv else "xact", arg]
            try:
                _xact.main()
            finally:
                sys.argv = _argv

        else:
            # Fallback: treat as raw URL
            subprocess.run(["open", arg], check=False)

        # Act-again: after any attribute change, reopen ⌘ Actions on the task.
        # attr args are prefix:pid:tid:…; a move's destination becomes the pid.
        if arg.startswith(ACT_AGAIN):
            _parts = arg.split(":")
            if len(_parts) >= 3 and _parts[1] and _parts[2]:
                _pid, _tid = _parts[1], _parts[2]
                if arg.startswith("attr_move:") and len(_parts) >= 4 and _parts[3]:
                    _pid = _parts[3]
                _reopen_actions(_pid, _tid)

    except RateLimitError as e:
        print(f"⏳ {e}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
