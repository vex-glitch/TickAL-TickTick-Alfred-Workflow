#!/usr/bin/env python3
"""
note_clear.py - Alfred Run Script

Clears a task's description (sets content=""). A dedicated "delete the note" node,
separate from note_save.py. Ignores the input text; acts on the task_list_id /
task_id session vars.

Wire e.g.  Text View ⌃↩ → this → End.  Prints a confirmation for the toast.
"""
import sys
import os

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap
bootstrap()

import config as cfg
import cache as cache_store
from api import TickTickAPI
from dispatch import _patch_task_cache

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
    api.update_task(tid, pid, current=cache_store.find_task(tid), content="")

    # all_tasks + per-list mirror in one call; all_notes patched inline
    _patch_task_cache(tid, content="")
    try:
        notes = cache_store.get("all_notes")
        if notes:
            cache_store.set("all_notes",
                            [dict(n, content="") if n.get("id") == tid else n
                             for n in notes])
    except Exception:
        cache_store.invalidate("all_notes")

    print(f"{task_title} · Note cleared")

except Exception as e:
    print(f"Note clear failed: {e}")
    sys.exit(1)
