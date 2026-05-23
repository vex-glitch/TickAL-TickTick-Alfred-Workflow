#!/usr/bin/env python3
"""
change_attributes.py — Alfred Script Filter
Static main menu for task attribute actions.
Each item outputs a plain arg that Alfred uses to branch to the right node.
task_id, task_list_id, task_title flow downstream as Alfred variables.
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

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    # When triggered fresh via osascript (e.g. "change another attribute" loop),
    # env vars don't survive the new session. Read task context from temp file.
    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id = _parts[0]
                    tid     = _parts[1]
        except Exception:
            pass

    # Variables passed through to every downstream node
    vars_ = {"task_id": tid, "task_list_id": list_id, "task_title": task_title}

    try:
        items = [
            alfred.item(
                title="Reschedule",
                subtitle="Set or change due date",
                arg="reschedule",
                variables=vars_,
            ),
            alfred.item(
                title="Move to Other List",
                subtitle="Move task to a different list",
                arg="move_list",
                variables=vars_,
            ),
            alfred.item(
                title="Change Tag",
                subtitle="Add or change a tag",
                arg="change_tag",
                variables=vars_,
            ),
            alfred.item(
                title="Change Priority",
                subtitle="Set priority level",
                arg="change_priority",
                variables=vars_,
            ),
            alfred.item(
                title="Clear Date",
                subtitle=f"Remove due date from \"{task_title}\"",
                arg="clear_date",
                variables=vars_,
            ),
            alfred.item(
                title="Delete Task",
                subtitle=f"Permanently delete \"{task_title}\"",
                arg="delete_task",
                variables=vars_,
            ),
            alfred.item(
                title="Rename Task",
                subtitle="Change the task title",
                arg="rename_task",
                variables=vars_,
            ),
        ]

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items.append(alfred.item(
                title=f'No options matching "{query}"',
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
