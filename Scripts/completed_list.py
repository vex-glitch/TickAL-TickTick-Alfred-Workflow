#!/usr/bin/env python3
"""
completed_list.py — Alfred Script Filter
Browses tasks completed via Alfred (tracked locally — the TickTick Open API
does not expose completed tasks).

Reads from the completed_tasks cache populated by dispatch.py whenever a task
is completed with ⇧⏎.

Usage:
  /opt/homebrew/bin/python3 ".../Scripts/completed_list.py" "$1"
"""
import sys
import os
import json
import traceback
from datetime import datetime, timezone

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from display import join_breadcrumb, search_key, PRIORITY, MODS_COMPLETED
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Helpers ──────────────────────────────────────────────────────────────────
def fmt_completed_time(task):
    """Return 'DD/MM/YYYY HH:MM' from completedTime field."""
    ct = task.get("completedTime", "")
    if not ct:
        return "unknown date"
    try:
        clean  = ct[:19]
        dt_utc = datetime(
            int(clean[0:4]), int(clean[5:7]),  int(clean[8:10]),
            int(clean[11:13]), int(clean[14:16]), int(clean[17:19]),
            tzinfo=timezone.utc,
        )
        local = dt_utc.astimezone()
        return local.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ct[:10]

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        tasks = cache_store.get("completed_tasks") or []

        items = []
        for t in tasks:
            tid  = t.get("id", "")
            pid  = t.get("_projectId", t.get("projectId", ""))
            name = t.get("title", "Untitled")

            priority_dot = PRIORITY.get(t.get("priority", 0), "⚫️")
            tags         = t.get("tags") or []
            tag_str      = " # " + " ".join(tags) if tags else ""

            # Breadcrumb: List>Section
            lname      = t.get("_projectName", "")
            col_name   = t.get("_columnName", "")
            breadcrumb = join_breadcrumb(lname, col_name)

            completed_str = fmt_completed_time(t)
            subtitle_parts = [f"✅ {completed_str}"]
            if breadcrumb:
                subtitle_parts.append(breadcrumb)
            subtitle_parts.append(MODS_COMPLETED)
            subtitle = "  ".join(subtitle_parts)

            link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

            items.append(alfred.item(
                uid=f"done-{tid}",
                title=f"{name} {priority_dot}{tag_str}",
                subtitle=subtitle,
                arg=f"open:{link}",
                mods={
                    "shift": {
                        "arg":      f"uncomplete:{pid}:{tid}:{name}",
                    },
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": pid},
            ))

        if query:
            items = fuzz.filter_and_score(
                query, items, key_fn=lambda x: search_key(x["title"])
            )

        if not items:
            if query:
                items = [alfred.item(
                    title=f'No completed tasks matching "{query}"',
                    valid=False,
                )]
            else:
                items = [alfred.item(
                    title="No completed tasks recorded yet",
                    subtitle="Complete tasks with ⇧ and they'll appear here",
                    valid=False,
                )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
