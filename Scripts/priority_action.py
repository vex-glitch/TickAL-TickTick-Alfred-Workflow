#!/usr/bin/env python3
"""
priority_action.py - Alfred Run Script
Sets the priority on a task.
$1 = "{task_list_id}:{task_id}:{priority_int}" (Arg-and-Vars node prepends the
ids to the bare value emitted by change_priority.py). Env vars are a fallback.
"""
import sys
import os

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions, run_path
bootstrap()

import config as cfg
import cache as cache_store
from api import TickTickAPI
from dispatch import _patch_task_cache

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

# 🧺 BUFFER sentinel: apply the picked priority to every buffered task
if tid == "BUFFER":
    try:
        from dispatch import _buffer_apply, _buffer_toast
        api = TickTickAPI(cfg.get_token())
        # dispatch._buffer_apply reads every buffered task LIVE first (one
        # list read per list), skips what changed in the app, keeps the
        # buffer on a failed read or a rate limit (review 2026-09-24)
        res = _buffer_apply(lambda bpid, btid, cur:
                            (api.update_task(btid, bpid, current=cur, priority=priority),
                             _patch_task_cache(btid, priority=priority)))
        print(_buffer_toast(res, f"→ priority {LABELS.get(priority, priority)}"))
    except Exception as e:
        print(f"Priority update failed: {e}")
        sys.exit(1)
    sys.exit(0)

try:
    api = TickTickAPI(cfg.get_token())
    api.update_task(tid, pid, current=cache_store.find_task(tid), priority=priority)

    # all_tasks + the per-list project_data mirror in one call
    _patch_task_cache(tid, priority=priority)

    label = LABELS.get(priority, str(priority))
    print(f"{task_title} → priority {label}")
    reopen_actions(pid, tid)

except Exception as e:
    print(f"Priority update failed: {e}")
    sys.exit(1)
