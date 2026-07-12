#!/usr/bin/env python3
"""
change_reminder.py — Alfred Script Filter
Reminder picker for an existing task. Reached from the ⌘ Actions / change-attributes
menu (conditional after actions.py listens for arg "reminder").

Reads task_id, task_list_id, task_title from env vars (temp-file fallback for the
go-back loop). Each preset / custom offset ADDS a reminder (deduped); "Clear" removes
all. Free-typed offsets work too: 45 → 45 min before, 2h, 3d.

Emits a BARE token as arg (at / 5 / 15 / 30 / 1h / 1d / 45m …); the Arg-and-Vars
node prepends {task_list_id}:{task_id}: → reminder_action.py consumes "pid:tid:token".
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
    import cache as cache_store
    import reminders as rem
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)


def find_task(tid):
    for t in (cache_store.get("all_tasks") or []):
        if t.get("id") == tid:
            return t
    return None


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
        task     = find_task(tid) or {}
        current  = task.get("reminders") or []
        has_date = bool(task.get("dueDate") or task.get("startDate"))
        back     = "  ⌃ 🔙"
        no_date  = "  ⚠️ No date, won't fire" if not has_date else ""
        vars_    = {"task_list_id": list_id, "task_id": tid}
        frag     = query.strip().lower()

        # ⌃⇧ back must work even on invalid rows — a mod-level valid=True
        # overrides the row's valid=False (Alfred ignores action chords on
        # invalid rows; that's why back never fired from "No reminder matching").
        back_mod = {"ctrl": {"valid": True, "arg": "",
                                   "subtitle": "🔙 Back to ⌘ Actions",
                                   "variables": vars_}}

        items = []

        # Any typed token that resolves → one direct "Add" row (covers free-typed
        # offsets and preset tokens like 2d/7d/7am whose labels don't contain them).
        if frag and rem.trigger(frag):
            items.append(alfred.item(
                title=f"🔔 Add {rem.human(frag)}",
                subtitle=f"Reminder offset{no_date}{back}",
                arg=frag,
                mods=back_mod,
                variables=vars_,
            ))
        else:
            for tok, label, hint in rem.PRESETS:
                already = rem.trigger(tok) in current
                items.append(alfred.item(
                    title=f"🔔 {'✓ ' if already else ''}{label}",
                    subtitle=(f"Already set{back}" if already else f"{hint}{no_date}{back}"),
                    arg=tok,
                    mods=back_mod,
                    variables=vars_,
                    match=f"{tok} {label}",
                ))
            if query:
                items = fuzz.filter_and_score(query, items, key_fn=lambda x: x.get("match", x["title"]))

        if not items:
            items = [alfred.item(title=f'No reminder matching "{query}"', valid=False,
                                 mods=back_mod)]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
