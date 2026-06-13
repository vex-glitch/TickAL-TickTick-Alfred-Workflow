#!/usr/bin/env python3
"""
actions.py — Alfred Script Filter (⌘ Actions menu for the selected item).

Reached by pressing ⌘ on a row in any search/browse view. The row's
variables (task_id / task_list_id / task_title, and item_type) ride in via
env, so every action carries context onward through the conditional →
Call-External-Trigger chain (no temp file, no osascript).

Row order matches the conditional:
  open · browse · schedule · tags · priority · move · copy · complete ·
  rename · delete · back

Args:
  • terminal actions carry the full dispatch arg, matched by regex in the
    conditional (open: / copy: / complete:) and forwarded to modOpen /
    modURL / modComplete as the argument.
  • picker actions emit a bare keyword (schedule, tags, …) matched "is equal
    to" and routed to the existing attribute / drill triggers, which read the
    task context from the variables that flow with them.
"""
import sys
import os
import json
import traceback

def emit(items): print(json.dumps({"items": items}))
def emit_error(m): emit([{"title": "TickTick Error", "subtitle": m, "valid": False}])

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

PRIO = {0: "⚫️ No priority", 1: "🟡 Low", 3: "🟠 Medium", 5: "🔴 High"}


def find_task(tid):
    for t in (cache_store.get("all_tasks") or []):
        if t.get("id") == tid:
            return t
    for n in (cache_store.get("all_notes") or []):
        if n.get("id") == tid:
            return n
    return None


def section_name(task):
    cid = task.get("columnId")
    if not cid:
        return task.get("_columnName", "") or ""
    pid = task.get("_projectId") or task.get("projectId", "")
    pd = cache_store.get(f"project_data_{pid}") if pid else None
    if pd:
        for col in pd.get("columns", []):
            if col.get("id") == cid:
                nm = col.get("name", "").strip()
                return "" if nm.lower() == "not sectioned" else nm
    return ""


def main():
    pid    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid    = os.environ.get("task_id", "")
    title  = os.environ.get("task_title", "task")
    itype  = os.environ.get("item_type", "")
    query  = sys.argv[1] if len(sys.argv) > 1 else ""

    if not pid or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as f:
                parts = f.read().strip().split(":", 1)
                if len(parts) == 2:
                    pid, tid = parts
        except Exception:
            pass

    vars_ = {"task_id": tid, "task_list_id": pid, "task_title": title}
    link  = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

    try:
        task = find_task(tid) or {}
        is_note = (task.get("kind") == "NOTE") or itype == "note"

        sched = fmt_date(task) or "📅 Not scheduled"
        crumb = join_breadcrumb(task.get("_projectName", ""), section_name(task)) \
            or (task.get("_projectName", "") or "Inbox")
        tags  = fmt_tags(task.get("tags")) or "🏷️ No tags"
        prio  = PRIO.get(task.get("priority", 0), PRIO[0])
        name  = task.get("title") or title
        has_kids = any(s.get("parentId") == tid and s.get("status", 0) == 0
                       for s in (cache_store.get("all_tasks") or []))

        # (title, subtitle, arg, search keywords, show?)
        rows = [
            ("↗️ Open",      "Open in TickTick",  f"open:{link}", "open",     True),
            ("⤵️ Browse subtasks", "Drill into subtasks", "browse", "browse subtasks", has_kids),
            (sched,          "Schedule…",         "schedule",     "schedule date when", True),
            (tags,           "Tags…",             "tags",         "tags tag",  True),
            (prio,           "Priority…",         "priority",     "priority",  not is_note),
            (crumb,          "Move…",             "move",         "move list section", True),
            ("🔗 Copy link", "Copy item URL",     f"copy:{link}", "copy url",  True),
            ("✔️ Complete",  "Mark this done",    f"complete:{pid}:{tid}:{title}", "complete done", not is_note),
            (name,           "Rename…",           "rename",       "rename title name", True),
            ("🗑️ Delete",    "Delete this item",  "delete",       "delete remove", True),
            ("🔙 Go back",   "Back to search",    "back",         "back",      True),
        ]

        items = [alfred.item(title=t, subtitle=s, arg=a, variables=vars_, match=f"{kw} {t}")
                 for (t, s, a, kw, show) in rows if show]

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x.get("match", x["title"]))
        if not items:
            items = [alfred.item(title=f'No action matching "{query}"', valid=False)]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
