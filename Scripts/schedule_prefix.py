#!/usr/bin/env python3
"""
schedule_prefix.py — Run Script
Outputs Alfred JSON with:
  arg       → "Reschedule for " or "Schedule for " (pre-fills script filter)
  has_date  → "1" or "0" (workflow variable available to all downstream nodes)
"""
import sys
import os
import json

try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
    import cache as cache_store

    tid = os.environ.get("task_id", "")
    has_date = False
    if tid:
        all_tasks = cache_store.get("all_tasks") or []
        task = next((t for t in all_tasks if t["id"] == tid), None)
        if task and (task.get("startDate") or task.get("dueDate")):
            has_date = True

except Exception:
    has_date = False

payload = {
    "alfredworkflow": {
        "arg": "Reschedule for " if has_date else "Schedule for ",
        "variables": {"has_date": "1" if has_date else "0"},
    }
}
print(json.dumps(payload), end="")
