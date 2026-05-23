#!/usr/bin/env python3
"""
priority_action.py — Alfred Run Script
Sets the priority on a task.
$1 = priority int (0=none, 1=low, 3=medium, 5=high) from change_priority.py
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

LABELS = {0: "None", 1: "Low", 3: "Medium", 5: "High"}

pid        = os.environ.get("task_list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "Task")
arg        = sys.argv[1] if len(sys.argv) > 1 else ""

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

try:
    priority = int(arg)
except (ValueError, TypeError):
    print(f"Error: invalid priority value: {arg!r}")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, priority=priority)

    # Patch cache in-place
    try:
        cached = cache_store.get("all_tasks")
        if cached is not None:
            patched = []
            for t in cached:
                if t.get("id") == tid:
                    t = dict(t)
                    t["priority"] = priority
                patched.append(t)
            cache_store.set("all_tasks", patched)
    except Exception:
        cache_store.invalidate("all_tasks")

    label = LABELS.get(priority, str(priority))
    print(f"{task_title} → priority {label}")

except Exception as e:
    print(f"Priority update failed: {e}")
    sys.exit(1)
