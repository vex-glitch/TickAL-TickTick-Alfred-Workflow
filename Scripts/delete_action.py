#!/usr/bin/env python3
"""
delete_action.py — Alfred Run Script
Deletes a task using task_id and task_list_id from env vars.
Called from the Change Attributes → Delete Task flow.
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

    print(f"{task_title} deleted")

except Exception as e:
    print(f"Delete failed: {e}")
    sys.exit(1)
