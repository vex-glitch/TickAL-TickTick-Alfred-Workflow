#!/usr/bin/env python3
"""
rename_action.py — Alfred Run Script
Renames a task to the new title provided by rename_task.py.
$1 = "{task_list_id}:{task_id}:{new_title}" (Arg-and-Vars node prepends the ids
to the bare title). Titles may contain ':', so parse with maxsplit=2.
"""
import sys
import os

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions
bootstrap()

import config as cfg
import cache as cache_store
from api import TickTickAPI
from dispatch import _patch_task_cache

task_title = os.environ.get("task_title", "Task")
arg        = sys.argv[1] if len(sys.argv) > 1 else ""

# Wiring delivers "pid:tid:new_title". Titles may contain ':', so split with
# maxsplit=2 to keep any ':' inside the title. Prefer parsed ids, fall back to env.
parts = arg.split(":", 2)
if len(parts) == 3:
    pid, tid, new_title = parts[0], parts[1], parts[2]
else:
    pid, tid, new_title = os.environ.get("task_list_id", ""), os.environ.get("task_id", ""), arg
pid = pid or os.environ.get("task_list_id", "")
tid = tid or os.environ.get("task_id", "")
new_title = new_title.strip()

if not new_title:
    print("Error: new title is empty")
    sys.exit(1)

# B4 (Run 3): renaming a LIST — same input flow, no task id; item_type rides
# the session vars from the ⌘ menu row. No act-again reopen (task-centric).
if os.environ.get("item_type", "") == "list":
    if not pid:
        print("Error: missing list context")
        sys.exit(1)
    try:
        api = TickTickAPI(cfg.get_token())
        api.update_project(pid, name=new_title)
        try:
            projects = cache_store.get("projects")
            if projects is not None:
                cache_store.set("projects", [
                    dict(p, name=new_title) if p.get("id") == pid else p
                    for p in projects])
            cached = cache_store.get("all_tasks")
            if cached is not None:
                cache_store.set("all_tasks", [
                    dict(t, _projectName=new_title)
                    if (t.get("projectId") or t.get("_projectId")) == pid else t
                    for t in cached])
            cache_store.invalidate(f"project_data_{pid}")
        except Exception:
            cache_store.invalidate("all_tasks")
        print(f"List renamed: {task_title} → {new_title}")
    except Exception as e:
        print(f"Rename failed: {e}")
        sys.exit(1)
    sys.exit(0)

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=cache_store.find_task(tid), title=new_title)

    # all_tasks + the per-list project_data mirror in one call
    _patch_task_cache(tid, title=new_title)

    print(f"Renamed: {task_title} → {new_title}")
    reopen_actions(pid, tid)

except Exception as e:
    print(f"Rename failed: {e}")
    sys.exit(1)
