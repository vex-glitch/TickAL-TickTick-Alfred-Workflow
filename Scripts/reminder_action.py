#!/usr/bin/env python3
"""
reminder_action.py — Alfred Run Script
Adds a reminder to a task (merge + dedup).
$1 = "{task_list_id}:{task_id}:{token}" (Arg-and-Vars node prepends the ids to
the bare token emitted by change_reminder.py). Env vars are a fallback.
token = at / 5 / 15 / 30 / 1h / 1d / 45m … (resolved to an RFC5545 TRIGGER).

The Open API can't clear reminders to empty, so this only adds — removal of the
last reminder must be done in the TickTick app.
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
import reminders as rem

task_title = os.environ.get("task_title", "Task")
arg        = sys.argv[1] if len(sys.argv) > 1 else ""

# Wiring delivers "pid:tid:token"; tokens have no ':' so maxsplit=2 is safe.
parts = arg.split(":", 2)
if len(parts) == 3:
    pid, tid, token = parts
else:
    pid   = os.environ.get("task_list_id", "")
    tid   = os.environ.get("task_id", "")
    token = arg
pid = pid or os.environ.get("task_list_id", "")
tid = tid or os.environ.get("task_id", "")

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

trigger = rem.trigger(token)
if not trigger:
    print(f"Error: unrecognised reminder: {token!r}")
    sys.exit(1)

try:
    api = TickTickAPI(cfg.get_token())
    current = cache_store.find_task(tid)
    if current is None:
        try:
            current = api.get_task(pid, tid)
        except Exception:
            current = {}
    existing = (current or {}).get("reminders") or []
    merged = list(dict.fromkeys(list(existing) + [trigger]))   # dedup, order preserved
    api.update_task(tid, pid, current=current, reminders=merged)

    # all_tasks + the per-list project_data mirror in one call
    _patch_task_cache(tid, reminders=merged)

    print(f"{task_title} · 🔔 {rem.human(token)}")
    reopen_actions(pid, tid)

except Exception as e:
    print(f"Reminder update failed: {e}")
    sys.exit(1)
