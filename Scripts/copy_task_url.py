#!/usr/bin/env python3
"""
copy_task_url.py — Alfred Run Script

Emits `copy:<task deep link>` so the existing modURL → copy_url_action chain
copies the TASK's URL (not the note body) and shows the "URL Copied" toast.
Ignores the input text; builds the link from the task_list_id / task_id session
vars.

Wire e.g.  Text View ⌥⌘↩ → this → Call External Trigger "modURL".
"""
import sys
import os

pid = os.environ.get("task_list_id") or os.environ.get("list_id", "")
tid = os.environ.get("task_id", "")

if not pid or not tid:
    try:
        with open("/tmp/ticktick_reattribute.txt") as _f:
            _parts = _f.read().strip().split(":", 1)
            if len(_parts) == 2:
                pid, tid = _parts
    except Exception:
        pass

if not tid:
    print("Error: no task")
    sys.exit(1)

link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"
print(f"copy:{link}")
