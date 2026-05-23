#!/usr/bin/env python3
"""
rename_action.py — Alfred Run Script
Renames a task to the new title provided by rename_task.py.
$1 = new task title
task_id and task_list_id come from Alfred env vars.
"""
import sys
import os

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
sys.path.insert(0, SRC_DIR)

import config as cfg
import cache as cache_store
from api import TickTickAPI

pid        = os.environ.get("task_list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "Task")
new_title  = sys.argv[1].strip() if len(sys.argv) > 1 else ""

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

if not new_title:
    print("Error: new title is empty")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, title=new_title)

    # Patch cache in-place
    try:
        cached = cache_store.get("all_tasks")
        if cached is not None:
            patched = []
            for t in cached:
                if t.get("id") == tid:
                    t = dict(t)
                    t["title"] = new_title
                patched.append(t)
            cache_store.set("all_tasks", patched)
    except Exception:
        cache_store.invalidate("all_tasks")

    print(f"Renamed: {task_title} → {new_title}")

except Exception as e:
    print(f"Rename failed: {e}")
    sys.exit(1)
