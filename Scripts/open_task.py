#!/usr/bin/env python3
"""
open_task.py - Alfred Run Script

Emits `open:<task deep link>` so the existing modOpen ET opens the TASK in
TickTick. Ignores the input text (a Text View sends its body on ↩, which is not
the task link); builds the link from the task_list_id / task_id session vars.

Wire e.g.  Text View ⇧↩ → this → Call External Trigger "modOpen".
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
    print("Error: no task to open")
    sys.exit(1)

# Same deep-link the ⌘ Actions "Open" row uses for a task-like item.
link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"
print(f"open:{link}")
