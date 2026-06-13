#!/usr/bin/env python3
"""
change_attributes.py — Alfred Script Filter
"Task details" view: each row shows the task's CURRENT value for an attribute
in the title, with the action in the subtitle. Selecting a row emits the same
positional arg (1-…6-) the downstream conditional already routes:

  1- → Reschedule   2- → Move   3- → Tags
  4- → Priority     5- → Delete  6- → Rename

Delete is shown last (it has no value to display).
task_id / task_list_id / task_title flow downstream as Alfred variables.
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
    import cache as cache_store
    from display import fmt_date, fmt_tags, join_breadcrumb
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

PRIORITY_LABEL = {0: "⚫️ No priority", 1: "🟡 Low", 3: "🟠 Medium", 5: "🔴 High"}


def find_task(tid):
    for t in (cache_store.get("all_tasks") or []):
        if t.get("id") == tid:
            return t
    return None


def section_name(task):
    """Resolve the task's column (section) name from project_data, if any."""
    col_id = task.get("columnId")
    if not col_id:
        return task.get("_columnName", "") or ""
    pid = task.get("_projectId") or task.get("projectId", "")
    pdata = cache_store.get(f"project_data_{pid}") if pid else None
    if pdata:
        for col in pdata.get("columns", []):
            if col.get("id") == col_id:
                nm = col.get("name", "").strip()
                return "" if nm.lower() == "not sectioned" else nm
    return ""


def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    query      = sys.argv[1] if len(sys.argv) > 1 else ""

    # Fresh session (e.g. "change another attribute" loop) — recover from temp file
    if not list_id or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                _parts = _f.read().strip().split(":", 1)
                if len(_parts) == 2:
                    list_id, tid = _parts[0], _parts[1]
        except Exception:
            pass

    vars_ = {"task_id": tid, "task_list_id": list_id, "task_title": task_title}

    try:
        task = find_task(tid) or {}

        # ── Current values ────────────────────────────────────────────────────
        sched = fmt_date(task) or "Not scheduled"
        sched_verb = "Change schedule…" if fmt_date(task) else "Schedule…"

        lname = task.get("_projectName", "") or ""
        crumb = join_breadcrumb(lname, section_name(task)) or (lname or "Inbox")

        tags_str = fmt_tags(task.get("tags"))
        tags_title = tags_str or "No tags"
        tags_verb  = "Change tags…" if tags_str else "Add tags…"

        prio = task.get("priority", 0)
        prio_title = PRIORITY_LABEL.get(prio, PRIORITY_LABEL[0])
        prio_verb  = "Change priority…" if prio else "Set priority…"

        name = task.get("title") or task_title

        # ── Rows: (title, subtitle, arg, search_keyword) — Delete last ─────────
        rows = [
            (sched,       sched_verb,    "1-", "schedule reschedule date time"),
            (crumb,       "Move…",       "2-", "move list section"),
            (tags_title,  tags_verb,     "3-", "tags tag"),
            (prio_title,  prio_verb,     "4-", "priority"),
            (name,        "Rename…",     "6-", "rename title name"),
            ("🗑️ Delete", "Delete task…", "5-", "delete remove"),
        ]

        items = [
            alfred.item(title=t, subtitle=s, arg=a, variables=vars_,
                        # match on keyword + value so typing narrows sensibly
                        match=f"{kw} {t}")
            for (t, s, a, kw) in rows
        ]

        if query:
            items = fuzz.filter_and_score(
                query, items, key_fn=lambda x: x.get("match", x["title"]))

        if not items:
            items = [alfred.item(title=f'No options matching "{query}"', valid=False)]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
