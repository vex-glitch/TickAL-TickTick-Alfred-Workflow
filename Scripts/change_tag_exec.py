#!/usr/bin/env python3
"""
change_tag_exec.py — Alfred Run Script
Replaces one tag with another on a task.
$1 format: pid:tid:old_tag:new_tag  (built by Arg and Vars node)
"""
import sys
import os

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions
bootstrap()

import config as cfg
import cache as cache_store
from api import TickTickAPI
from dispatch import _norm_tags, _patch_task_cache, _ensure_tags_exist


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
        # Remove old tag, add new tag, preserve everything else. Lowercase —
        # TickTick's server-side tag-name case (labels keep theirs).
        updated = _norm_tags([t for t in tags if t.lower() != old_tag.lower()]
                             + [new_tag])
        _ensure_tags_exist([new_tag])   # R4.2 — a ➕ picker row may coin it
        api.update_task(tid, pid, current=current, tags=updated)
        # all_tasks + the per-list project_data mirror in one call
        _patch_task_cache(tid, tags=updated)
        task_title = os.environ.get("task_title", "Task")
        if old_tag:
            print(f"{task_title} #{old_tag} → #{new_tag}")
        else:
            print(f"{task_title} tagged #{new_tag}")
        # Act-again: reopen ⌘ Actions with fresh values — the change path
        # bypasses dispatch's ACT_AGAIN tail (it ends on ET End), so the
        # executor loops itself, same as the other *_action.py executors.
        reopen_actions(pid, tid)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
