#!/usr/bin/env python3
"""
read_task_tags.py — Alfred Run Script
Reads current tags from a task and exposes them as an Alfred variable
so they can be shown in a Dialog node message.

Passes the original arg through unchanged — this script is a pure
read-only side-step in the flow.

$1 format: pid:tid:newTag  (same as tag_action.py)
Output:    Alfred JSON with {var:current_tags} set to comma-separated tag list
           (or "none" if the task has no tags)
"""
import sys
import os
import json

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
sys.path.insert(0, SRC_DIR)

import config as cfg
import cache as cache_store
from api import TickTickAPI

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        parts = arg.split(":", 2)
        pid, tid = parts[0], parts[1]
    except (ValueError, IndexError):
        # Can't parse — pass through silently, dialog will show empty
        print(json.dumps({"alfredworkflow": {"arg": arg, "variables": {"current_tags": "none"}}}))
        return

    try:
        # Try cache first, fall back to API
        pdata = cache_store.get(f"project_data_{pid}")
        task  = None
        if pdata:
            task = next((t for t in pdata.get("tasks", []) if t["id"] == tid), None)
        if task is None:
            task = TickTickAPI(cfg.get_token()).get_task(pid, tid)

        tags = task.get("tags") or [] if task else []
        current_tags = ", ".join(tags) if tags else "none"

    except Exception:
        current_tags = "unknown"

    print(json.dumps({
        "alfredworkflow": {
            "arg": arg,                          # pass original arg through untouched
            "variables": {"current_tags": current_tags},
        }
    }))

if __name__ == "__main__":
    main()
