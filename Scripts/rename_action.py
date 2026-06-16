#!/usr/bin/env python3
"""
rename_action.py — Alfred Run Script
Renames a task to the new title provided by rename_task.py.
$1 = "{task_list_id}:{task_id}:{new_title}" (Arg-and-Vars node prepends the ids
to the bare title). Titles may contain ':', so parse with maxsplit=2.
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

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

if not new_title:
    print("Error: new title is empty")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=cache_store.find_task(tid), title=new_title)

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
