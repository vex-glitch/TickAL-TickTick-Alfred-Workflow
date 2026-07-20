#!/usr/bin/env python3
"""
ensure_task_context.py - Alfred Run Script
Ensures task_list_id and task_id are set as Alfred variables before
a List Filter that needs them. Reads from env vars (first run) or
temp file (second run). Passes the incoming arg through unchanged.
"""
import os, json, sys

pid        = os.environ.get("task_list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "")
itype      = os.environ.get("item_type", "")

# Recover task context (go-back path) for task-like items only. For a list/section
# there is no task, so never pull a stale task_id from the temp file.
if itype not in ("list", "section") and (not pid or not tid):
    try:
        with open("/tmp/ticktick_reattribute.txt") as f:
            parts = f.read().strip().split(":", 1)
            if len(parts) == 2:
                pid, tid = parts[0], parts[1]
    except Exception:
        pass

# Temp-file entries carry no title - recover it from cache so downstream
# pickers say the real task name, not the "task" placeholder.
if itype not in ("list", "section") and tid and not task_title:
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
        import cache
        t = cache.find_task(tid)
        if t:
            task_title = t.get("title") or ""
    except Exception:
        pass

print(json.dumps({
    "alfredworkflow": {
        "arg": sys.argv[1] if len(sys.argv) > 1 else "",
        "variables": {
            "task_list_id": pid,
            "task_id":      tid,
            "task_title":   task_title,
            "item_type":    itype,
            "list_id":      os.environ.get("list_id", ""),
            "section_id":   os.environ.get("section_id", ""),
        }
    }
}))