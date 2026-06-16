#!/usr/bin/env python3
"""
smart_list.py — Alfred Script Filter
Browses tasks for a smart list in Alfred.
$1 = smartlist type: today | tomorrow | next7days
"""
import sys
import os
import json
import traceback
from datetime import datetime, timedelta, timezone

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

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from display import build_title, build_subtitle, join_breadcrumb, search_key
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Date helpers ──────────────────────────────────────────────────────────────
def utc_str_to_local_date(date_str):
    """Convert a UTC ISO string to local YYYY-MM-DD."""
    if not date_str:
        return ""
    try:
        clean = date_str[:19]
        dt_utc = datetime(
            int(clean[0:4]), int(clean[5:7]), int(clean[8:10]),
            int(clean[11:13]), int(clean[14:16]), int(clean[17:19]),
            tzinfo=timezone.utc,
        )
        return dt_utc.astimezone().strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10]

def task_local_date(task):
    d = task.get("startDate") or task.get("dueDate") or ""
    return utc_str_to_local_date(d)

def filter_tasks(all_tasks, smartlist):
    today    = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    in7days  = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    incomplete = [t for t in all_tasks
                  if t.get("status", 0) == 0 and not t.get("parentId")]

    if smartlist == "today":
        return [t for t in incomplete if task_local_date(t) == today]
    elif smartlist == "tomorrow":
        return [t for t in incomplete if task_local_date(t) == tomorrow]
    elif smartlist == "next7days":
        tasks = [t for t in incomplete if today <= task_local_date(t) <= in7days]
        return sorted(tasks, key=lambda t: task_local_date(t))
    return []

LABELS = {
    "today":     "Today",
    "tomorrow":  "Tomorrow",
    "next7days": "Next 7 Days",
}

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    smartlist = sys.argv[1] if len(sys.argv) > 1 else ""
    query     = sys.argv[2] if len(sys.argv) > 2 else ""

    try:
        all_tasks = cache_store.get("all_tasks") or []
        tasks     = filter_tasks(all_tasks, smartlist)
        label     = LABELS.get(smartlist, smartlist)

        items = []

        for t in tasks:
            tid  = t["id"]
            pid  = t.get("_projectId", t.get("projectId", ""))
            name = t.get("title", "Untitled")

            # Breadcrumb: List>Section
            lname      = t.get("_projectName", "")
            col_name   = t.get("_columnName", "")
            breadcrumb = join_breadcrumb(lname, col_name)

            sub_count = sum(1 for s in all_tasks
                            if s.get("parentId") == tid and s.get("status", 0) == 0)

            link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

            items.append(alfred.item(
                uid=f"task-{tid}",
                title=build_title(t),
                subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb),
                arg=f"open:{link}",
                mods={
                    "cmd":     {"arg": ""},
                    "shift":   {"arg": f"complete:{pid}:{tid}:{name}"},
                    "alt":     {"arg": ""},
                    "alt+cmd": {"arg": f"copy:{link}"},
                    "ctrl":    {"arg": ""},
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": pid},
            ))

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))

        if not items:
            items.append(alfred.item(
                title=f'No tasks matching "{query}"' if query else f"No tasks in {label}",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
