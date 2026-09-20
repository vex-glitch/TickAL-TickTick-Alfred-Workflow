#!/usr/bin/env python3
"""
delete_action.py - Alfred Run Script
Deletes a task using task_id and task_list_id from env vars.
Called from the Change Attributes → Delete Task flow.
"""
import sys
import os

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, run_path
bootstrap()

import areas
import config as cfg
import cache as cache_store
from api import TickTickAPI
from dispatch import _patch_project_data


def _sweep_ctas(api, pid):
    """The list's open 📌CTA tasks go with it (Vex 2026-09-20: "when we
    delete project, its cta should be deleted as well"). A CTA names its
    list by LINK, never by name: "💼 P • [Name](ticktick:///webapp/#p/<pid>/
    tasks) 🔗" in the title (project / list mode), or the list link in the
    body of a task-mode CTA (whose task is in the Trash with its list). Open
    ones only - a completed CTA is history. Returns how many went."""
    cta = areas.CTA_LIST_ID
    if not cta or cta == pid:
        return 0
    needle = f"#p/{pid}/"
    try:
        tasks = (api.get_project_data(cta) or {}).get("tasks") or []
    except Exception:
        return 0
    gone = []
    for t in tasks:
        if needle not in (t.get("title") or "") and needle not in (t.get("content") or ""):
            continue
        try:
            api.delete_task(cta, t.get("id"))
            gone.append(t.get("id"))
        except Exception:
            pass
    if gone:
        try:
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks",
                                [t for t in cached if t.get("id") not in gone])
        except Exception:
            cache_store.invalidate("all_tasks")
        for tid_ in gone:
            _patch_project_data(tid_, pid_old=cta, remove=True)
    return len(gone)

pid        = os.environ.get("task_list_id", "") or os.environ.get("list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "Task")

# 🧺 BUFFER sentinel: delete every buffered task (typed-confirm row)
if tid == "BUFFER":
    try:
        import xact
        api = TickTickAPI(cfg.get_token())
        done = 0
        for ln in xact.buffer_ids():
            bpid, btid = ln.split(":", 1)
            try:
                api.delete_task(bpid, btid)
                done += 1
                cached = cache_store.get("all_tasks")
                if cached is not None:
                    cache_store.set("all_tasks",
                                    [t for t in cached if t.get("id") != btid])
                _patch_project_data(btid, pid_old=bpid, remove=True)
            except Exception:
                pass
        open(run_path("tickal_buffer.txt"), "w").close()
        print(f"🅿️ {done} tasks deleted · they're in TickTick's Trash")
    except Exception as e:
        print(f"Delete failed: {e}")
        sys.exit(1)
    sys.exit(0)

# Deleting a LIST - reached only via the typed-confirm row in the
# ⌘ menu ("delete list yes"). Tasks land in TickTick's Trash.
if os.environ.get("item_type", "") == "list":
    lname = os.environ.get("list_name", "") or task_title
    if not pid:
        print("Error: missing list context")
        sys.exit(1)
    try:
        api = TickTickAPI(cfg.get_token())
        api.delete_project(pid)
        ctas = _sweep_ctas(api, pid)
        try:
            projects = cache_store.get("projects")
            if projects is not None:
                cache_store.set("projects", [p for p in projects if p.get("id") != pid])
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", [
                    t for t in cached
                    if (t.get("projectId") or t.get("_projectId")) != pid])
            notes = cache_store.get("all_notes")
            if notes is not None:
                cache_store.set("all_notes", [
                    n for n in notes
                    if (n.get("projectId") or n.get("_projectId")) != pid])
            cache_store.invalidate(f"project_data_{pid}")
        except Exception:
            cache_store.invalidate("all_tasks")
        print(f"{lname} deleted · tasks are in TickTick's Trash"
              + (f" · {ctas} 📌CTA" if ctas else ""))
    except Exception as e:
        print(f"Delete failed: {e}")
        sys.exit(1)
    sys.exit(0)

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.delete_task(pid, tid)

    cached = cache_store.get("all_tasks")
    if cached is not None:
        cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
    else:
        cache_store.invalidate("all_tasks")
    _patch_project_data(tid, pid_old=pid, remove=True)

    print(f"{task_title} deleted")

except Exception as e:
    print(f"Delete failed: {e}")
    sys.exit(1)
