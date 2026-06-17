#!/usr/bin/env python3
"""
note_save.py — Alfred Run Script

Saves the edited description / note body from the Text View back to TickTick.
$1 = the full (possibly multi-line) text the Text View emitted on ⏎.
task_list_id / task_id ride along as session variables (env).

Prints a confirmation that flows to End → notification. Mirrors rename_action.py,
but writes the `content` field instead of `title`.
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

content    = sys.argv[1] if len(sys.argv) > 1 else ""
pid        = os.environ.get("task_list_id") or os.environ.get("list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "Task")

if not pid or not tid:
    try:
        with open("/tmp/ticktick_reattribute.txt") as _f:
            _parts = _f.read().strip().split(":", 1)
            if len(_parts) == 2:
                pid, tid = _parts
    except Exception:
        pass

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=cache_store.find_task(tid), content=content)

    # Patch the caches in-place so the change shows immediately (tasks + notes).
    for cache_key in ("all_tasks", "all_notes"):
        try:
            cached = cache_store.get(cache_key)
            if not cached:
                continue
            patched, changed = [], False
            for t in cached:
                if t.get("id") == tid:
                    t = dict(t)
                    t["content"] = content
                    changed = True
                patched.append(t)
            if changed:
                cache_store.set(cache_key, patched)
        except Exception:
            cache_store.invalidate(cache_key)

    print(f"{task_title} · Note saved")

except Exception as e:
    print(f"Note save failed: {e}")
    sys.exit(1)
