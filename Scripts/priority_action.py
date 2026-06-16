#!/usr/bin/env python3
"""
priority_action.py — Alfred Run Script
Sets the priority on a task.
$1 = "{task_list_id}:{task_id}:{priority_int}" (Arg-and-Vars node prepends the
ids to the bare value emitted by change_priority.py). Env vars are a fallback.
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

task_title = os.environ.get("task_title", "Task")
arg        = sys.argv[1] if len(sys.argv) > 1 else ""

# Wiring delivers "pid:tid:value"; parse it, preferring parsed ids but
# falling back to env vars (priority has no ':' so maxsplit=2 is safe).
parts = arg.split(":", 2)
if len(parts) == 3:
    pid, tid, value = parts
else:
    pid   = os.environ.get("task_list_id", "")
    tid   = os.environ.get("task_id", "")
    value = arg
pid = pid or os.environ.get("task_list_id", "")
tid = tid or os.environ.get("task_id", "")

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

try:
    priority = int(value)
except (ValueError, TypeError):
    print(f"Error: invalid priority value: {value!r}")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=cache_store.find_task(tid), priority=priority)

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
