#!/usr/bin/env python3
"""
rename_task.py — Alfred Script Filter
Text input for renaming a task. Whatever is typed becomes the new title.
Reads task_id, task_list_id, task_title from env vars.
Outputs arg: attr_rename:{list_id}:{task_id}:{new_title}
"""
import sys
import os
import json
import traceback

# ── Fallback error output ────────────────────────────────────────────────────
def emit(items):
    print(json.dumps({"items": items}))

def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

try:
    import alfred
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    try:
        new_name = query.strip()

        if not new_name:
            items = [alfred.item(
                title=f"Rename: {task_title}",
                subtitle="Type the new task name",
                valid=False,
            )]
        else:
            items = [alfred.item(
                title=f"Rename to: {new_name}",
                subtitle=f"Was: {task_title}  Confirm",
                arg=new_name,
                variables={"task_list_id": list_id, "task_id": tid},
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
