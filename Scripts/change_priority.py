#!/usr/bin/env python3
"""
change_priority.py — Alfred Script Filter
Priority picker for a task.
Reads task_id, task_list_id from env vars.
Outputs arg: attr_priority:{list_id}:{task_id}:{priority_int}
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
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

PRIORITIES = [
    (5, "⬆ High",   "Highest priority"),
    (3, "↑ Medium", "Medium priority"),
    (1, "↓ Low",    "Low priority"),
    (0, "— None",   "No priority"),
]

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
        items = []
        for val, label, desc in PRIORITIES:
            items.append(alfred.item(
                title=label,
                subtitle=f"{desc} for \"{task_title}\"  ⌘⇧ 🔙",
                arg=str(val),
                variables={"task_list_id": list_id, "task_id": tid},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(title="No match", valid=False))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
