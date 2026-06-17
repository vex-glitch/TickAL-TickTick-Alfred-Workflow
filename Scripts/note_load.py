#!/usr/bin/env python3
"""
note_load.py — Alfred Run Script

Prints a task's current description / note body (markdown) so it can be loaded
into a Text View for viewing & editing. The stdout of this script becomes the
Text View's editable text.

Flow:  ⌘ Actions "📝 Note" → conditional → ET "attributeNote" →
       ensure_task_context.py → THIS → Text View (editable) → note_save.py → End

Reads task_list_id / task_id from env (with the /tmp/ticktick_reattribute.txt
go-back fallback). Content comes from the cache when present, else a single
api.get_task() fetch. Prints nothing extra — not even a trailing newline — so the
editor opens with exactly the stored text.
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

list_id = os.environ.get("task_list_id") or os.environ.get("list_id", "")
tid     = os.environ.get("task_id", "")

if not list_id or not tid:
    try:
        with open("/tmp/ticktick_reattribute.txt") as _f:
            _parts = _f.read().strip().split(":", 1)
            if len(_parts) == 2:
                list_id, tid = _parts[0], _parts[1]
    except Exception:
        pass

content = ""
task = cache_store.find_task(tid) if tid else None
if task:
    content = task.get("content") or ""
if not content and list_id and tid:
    try:
        full = TickTickAPI(cfg.get_token()).get_task(list_id, tid)
        content = full.get("content") or ""
    except Exception:
        pass  # offline / rate-limited → open an empty editor

# stdout (verbatim) becomes the Text View's editable text
sys.stdout.write(content)
