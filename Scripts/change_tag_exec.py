#!/usr/bin/env python3
"""
change_tag_exec.py — Alfred Run Script
Replaces one tag with another on a task.
$1 format: pid:tid:old_tag:new_tag  (built by Arg and Vars node)
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


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        pid, tid, old_tag, new_tag = arg.split(":", 3)
    except ValueError:
        print(f"Error: unexpected arg format: {arg!r}")
        return

    if not pid or not tid or not new_tag:
        print("Error: missing pid, tid, or new_tag")
        return

    try:
        api     = TickTickAPI(cfg.get_token())
        current = cache_store.find_task(tid) or api.get_task(pid, tid)
        tags    = current.get("tags") or []
        # Remove old tag, add new tag, preserve everything else
        updated = [t for t in tags if t != old_tag]
        if new_tag not in updated:
            updated.append(new_tag)
        api.update_task(tid, pid, current=current, tags=updated)
        # Patch cache in-place — avoids triggering auto-fetch on next search
        try:
            cached = cache_store.get("all_tasks")
            if cached is not None:
                patched = []
                for t in cached:
                    if t.get("id") == tid:
                        t = dict(t)
                        t["tags"] = updated
                    patched.append(t)
                cache_store.set("all_tasks", patched)
        except Exception:
            cache_store.invalidate("all_tasks")
        task_title = os.environ.get("task_title", "Task")
        if old_tag:
            print(f"{task_title} #{old_tag} → #{new_tag}")
        else:
            print(f"{task_title} tagged #{new_tag}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
