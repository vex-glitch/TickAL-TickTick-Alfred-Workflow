#!/usr/bin/env python3
"""
filter_view.py — Alfred Script Filter
Shows tasks matching a user-defined filter from filters_config.py.
$1 = filter index (from filters_list.py)
"""
import sys
import os
import json
import traceback
from datetime import datetime, timedelta, timezone
import calendar

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
    sys.path.insert(0, WORKFLOW_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from filters_config import FILTERS
    from display import build_title, build_subtitle, join_breadcrumb, search_key
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Date helpers ──────────────────────────────────────────────────────────────
def utc_str_to_local_date(date_str):
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
    return utc_str_to_local_date(task.get("startDate") or task.get("dueDate") or "")

# ── Filter matching ───────────────────────────────────────────────────────────
def matches(task, f, project_name_to_id):
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    next7    = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    next14   = (now + timedelta(days=14)).strftime("%Y-%m-%d")

    # Week boundaries (Mon–Sun)
    wd = now.weekday()
    week_start      = (now - timedelta(days=wd)).strftime("%Y-%m-%d")
    week_end        = (now + timedelta(days=6 - wd)).strftime("%Y-%m-%d")
    next_week_start = (now + timedelta(days=7 - wd)).strftime("%Y-%m-%d")
    next_week_end   = (now + timedelta(days=13 - wd)).strftime("%Y-%m-%d")

    # Month boundaries
    month_start     = now.replace(day=1).strftime("%Y-%m-%d")
    month_end       = now.replace(day=calendar.monthrange(now.year, now.month)[1]).strftime("%Y-%m-%d")
    nm_year         = now.year + (1 if now.month == 12 else 0)
    nm_month        = 1 if now.month == 12 else now.month + 1
    next_month_start = datetime(nm_year, nm_month, 1).strftime("%Y-%m-%d")
    next_month_end   = datetime(nm_year, nm_month, calendar.monthrange(nm_year, nm_month)[1]).strftime("%Y-%m-%d")

    DATE_MAP = {"today": today, "tomorrow": tomorrow, "next7days": next7, "next14days": next14}

    # Include — title must contain this string (case-insensitive)
    if f.get("include"):
        if f["include"].lower() not in task.get("title", "").lower():
            return False

    # Tags — ALL must match
    tags_filter = f.get("tags")
    if tags_filter is not None:
        task_tags = [tg.lower() for tg in (task.get("tags") or [])]
        if tags_filter == "untagged":
            if task_tags:
                return False
        elif tags_filter == "any":
            if not task_tags:
                return False
        elif tags_filter == "any_or_untagged":
            pass  # no filtering — tagged or untagged both pass
        elif isinstance(tags_filter, list):
            if not all(tag.lower() in task_tags for tag in tags_filter):
                return False

    # Any tags — at least ONE must match
    any_tags_filter = f.get("any_tags")
    if any_tags_filter is not None:
        task_tags = [tg.lower() for tg in (task.get("tags") or [])]
        if not any(tag.lower() in task_tags for tag in any_tags_filter):
            return False

    # Priority — config uses 0=none, 1=low, 2=medium, 3=high, "any"=all
    # mapped to TickTick API values: 0→0, 1→1, 2→3, 3→5
    priority_filter = f.get("priority")
    if priority_filter is not None and priority_filter != "any":
        PMAP = {0: 0, 1: 1, 2: 3, 3: 5}
        api_priorities = {PMAP.get(p, p) for p in priority_filter}
        if task.get("priority", 0) not in api_priorities:
            return False

    # Projects — "any" skips filter, otherwise match by name
    if f.get("projects") and f["projects"] != "any":
        project_ids = {project_name_to_id.get(n.lower()) for n in f["projects"]}
        if task.get("_projectId") not in project_ids:
            return False

    # Due date filters
    d = task_local_date(task)
    if f.get("due_before"):
        cutoff = DATE_MAP.get(f["due_before"], f["due_before"])
        if not d or d > cutoff:
            return False
    if f.get("due_after"):
        cutoff = DATE_MAP.get(f["due_after"], f["due_after"])
        if not d or d < cutoff:
            return False
    if f.get("no_date"):
        if d:
            return False

    # Shorthand due field
    due = f.get("due")
    if due and due != "all":
        if due == "overdue":
            if not d or d >= today:
                return False
        elif due == "today":
            if d != today:
                return False
        elif due == "tomorrow":
            if d != tomorrow:
                return False
        elif due == "next7days":
            if not d or not (today <= d <= next7):
                return False
        elif due == "this_week":
            if not d or not (week_start <= d <= week_end):
                return False
        elif due == "next_week":
            if not d or not (next_week_start <= d <= next_week_end):
                return False
        elif due == "this_month":
            if not d or not (month_start <= d <= month_end):
                return False
        elif due == "next_month":
            if not d or not (next_month_start <= d <= next_month_end):
                return False
        elif due == "no_date":
            if d:
                return False

    return True

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    env_index    = os.environ.get("filter_index", "")
    raw_arg      = sys.argv[1] if len(sys.argv) > 1 else ""
    filter_index = int(env_index) if env_index.isdigit() else (int(raw_arg) if raw_arg.isdigit() else -1)
    query        = "" if raw_arg.isdigit() or raw_arg == "__tag__" else raw_arg
    filter_tag   = os.environ.get("filter_tag", "")

    try:
        if filter_index < 0 or filter_index >= len(FILTERS):
            emit_error(f"Invalid filter index: {filter_index}")
            return

        f         = FILTERS[filter_index]
        f_name    = f.get("name", f"Filter {filter_index + 1}")
        all_tasks = cache_store.get("all_tasks") or []

        # Build project name → id lookup
        projects_cache = cache_store.get("projects") or []
        project_name_to_id = {p["name"].lower(): p["id"] for p in projects_cache}

        # Only incomplete top-level tasks
        candidates = [t for t in all_tasks
                      if t.get("status", 0) == 0 and not t.get("parentId")]

        tasks = [t for t in candidates if matches(t, f, project_name_to_id)]

        def _task_item(t, f_name, all_tasks):
            tid  = t["id"]
            pid  = t.get("_projectId", t.get("projectId", ""))
            name = t.get("title", "Untitled")

            lname      = t.get("_projectName", "")
            col_name   = t.get("_columnName", "")
            breadcrumb = join_breadcrumb(f_name, lname, col_name)

            sub_count = sum(1 for s in all_tasks
                            if s.get("parentId") == tid and s.get("status", 0) == 0)

            link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

            return alfred.item(
                uid=f"task-{tid}",
                title=build_title(t),
                subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb),
                arg=f"open:{link}",
                mods={
                    "cmd":     {"arg": "",                              "subtitle": "Add subtask"},
                    "shift":   {"arg": f"complete:{pid}:{tid}:{name}", "subtitle": "Complete task"},
                    "alt":     {"arg": "",                              "subtitle": "Browse subtasks"},
                    "alt+cmd": {"arg": f"copy:{link}",                 "subtitle": "Copy link to task"},
                    "ctrl":    {"arg": "",                              "subtitle": "Change attributes"},
                },
                variables={"task_id": tid, "task_title": name, "task_list_id": pid},
            )

        if not query and not filter_tag:
            # ── Level 1: tag selection (sections view) ────────────────────────
            try:
                from tags_config import TAGS as _config_tags
                tag_order = {t.lower(): i for i, t in enumerate(_config_tags)}
            except Exception:
                tag_order = {}

            from collections import defaultdict
            tag_groups = defaultdict(list)
            untagged   = []
            for t in tasks:
                first_tag = (t.get("tags") or [None])[0]
                if first_tag:
                    tag_groups[first_tag].append(t)
                else:
                    untagged.append(t)

            sorted_tags = sorted(tag_groups, key=lambda x: (tag_order.get(x.lower(), 9999), x.lower()))

            items = []
            for tag in sorted_tags:
                count = len(tag_groups[tag])
                items.append(alfred.item(
                    uid=f"tag-{tag}",
                    title=f"#{tag}",
                    subtitle=f"{count} task{'s' if count != 1 else ''}  |  ⏎ ⤵️  ⌘⇧ 🔙",
                    arg="",
                    valid=True,
                    variables={"filter_tag": tag, "filter_index": str(filter_index)},
                ))

            if untagged:
                count = len(untagged)
                items.append(alfred.item(
                    uid="tag-untagged",
                    title="No Tag",
                    subtitle=f"{count} task{'s' if count != 1 else ''}  |  ⏎ ⤵️  ⌘⇧ 🔙",
                    arg="",
                    valid=True,
                    variables={"filter_tag": "__untagged__", "filter_index": str(filter_index)},
                ))

        else:
            # ── Level 2: tasks (scoped to tag if filter_tag set) ──────────────
            if filter_tag:
                if filter_tag == "__untagged__":
                    visible = [t for t in tasks if not (t.get("tags") or [])]
                else:
                    visible = [t for t in tasks if (t.get("tags") or [None])[0] == filter_tag]
            else:
                visible = tasks

            items = [_task_item(t, f_name, all_tasks) for t in visible]

            if query:
                items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))

        if not items:
            items.append(alfred.item(
                title=f'No tasks matching "{query}"' if query else f"No tasks in {f_name}",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
