#!/usr/bin/env python3
"""
change_priority.py - Alfred Script Filter
Priority picker for a task.
Reads task_id, task_list_id from env vars.
Outputs arg: attr_priority:{list_id}:{task_id}:{priority_int}
"""
import sys
import os
import json
import traceback

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

try:
    import alfred
    import fuzzy as fuzz
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

PRIORITIES = [
    (5, "🔴", "High"),
    (3, "🟠", "Medium"),
    (1, "🟡", "Low"),
    (0, "⚫️", "No priority"),
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
        # ⌃⇧ back must work even on invalid rows - a mod-level valid=True
        # overrides the row's valid=False (Alfred ignores action chords on
        # invalid rows; that's why back never fired from "No match").
        back_mod = {"ctrl": {"valid": True, "arg": "",
                                   "subtitle": "🔙 Back to ⌘ Actions",
                                   "variables": {"task_list_id": list_id,
                                                 "task_id": tid}}}
        items = []
        for val, circle, name in PRIORITIES:
            items.append(alfred.item(
                title=f"{circle} {name}",
                subtitle=f"{circle} {task_title}  ⌃ 🔙",
                arg=str(val),
                mods=back_mod,
                variables={"task_list_id": list_id, "task_id": tid},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(title="No match", valid=False, mods=back_mod))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
