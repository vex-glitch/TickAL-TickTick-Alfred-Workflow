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

        # ⌘⇧ back must work even on the invalid prompt row — a mod-level
        # valid=True overrides the row's valid=False (this was why "back from
        # a picker" never fired: Alfred ignores actions on invalid rows).
        back_mod = {"ctrl": {"valid": True, "arg": "",
                                  "subtitle": "🔙 Back to ⌘ Actions",
                                  "variables": {"task_list_id": list_id,
                                                "task_id": tid}}}
        if not new_name:
            items = [alfred.item(
                title=f"Rename: {task_title}",
                subtitle="Type new name",
                valid=False,
                mods=back_mod,
            )]
        else:
            items = [alfred.item(
                title=f"Rename to: {new_name}",
                subtitle=f"Was: {task_title}  Confirm",
                arg=new_name,
                mods=back_mod,
                variables={"task_list_id": list_id, "task_id": tid},
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
