#!/usr/bin/env python3
"""
Unified Alfred Script Filter for TickTick.

Query modes (determined by leading character):
  plain text     → list browser (default)
  >PID text      → section browser for project PID
  /text          → task search
  +text          → add task (NLP: *date, !1-3, #tag, ~list)
"""
import sys
import os
import re
import json
import base64
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

import config as cfg
import cache as cache_store
import alfred
import fuzzy as fuzz
from api import TickTickAPI

PRIORITY_ICON = {0: "", 1: "↓", 3: "→", 5: "↑"}
PRIORITY_LABEL = {0: "", 1: "Low", 3: "Medium", 5: "High"}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def get_api():
    return TickTickAPI(cfg.get_token())


def projects():
    data = cache_store.get("projects")
    if data is None:
        data = get_api().get_projects()
        cache_store.set("projects", data)
    # Filter out smart lists
    return [p for p in data if p.get("kind") != "SMART_LIST"]


def _folder_order(name):
    """
    Extract (sort_int, clean_name) from strict '1) Name' prefix.
    '1) 1️⃣ Admin', '2) Work' → (1, '1️⃣ Admin'), (2, 'Work').
    No matching prefix → (9999, name) unchanged.
    """
    import re
    m = re.match(r'^(\d+)\)\s(.+)$', name.strip())
    if m:
        return int(m.group(1)), m.group(2).strip()
    return 9999, name.strip()


def all_tasks():
    data = cache_store.get("all_tasks")
    if data is None:
        data = _fetch_all_tasks()
    return data


def _fetch_all_tasks():
    api = get_api()
    result = []
    for p in projects():
        try:
            pdata = api.get_project_data(p["id"])
            for t in pdata.get("tasks", []):
                t["_projectName"] = p["name"]
                t["_projectId"] = p["id"]
                result.append(t)
        except Exception:
            pass
    cache_store.set("all_tasks", result)
    return result


def project_sections(project_id):
    key = f"sections_{project_id}"
    data = cache_store.get(key)
    if data is None:
        pdata = get_api().get_project_data(project_id)
        data = {
            "sections": pdata.get("columns") or pdata.get("groups") or [],
            "tasks": pdata.get("tasks", []),
        }
        cache_store.set(key, data)
    return data


def project_by_id(project_id):
    return next((p for p in projects() if p["id"] == project_id), None)


def known_tags():
    tags = set()
    for t in all_tasks():
        for tag in t.get("tags", []):
            tags.add(tag)
    return sorted(tags)


# ---------------------------------------------------------------------------
# List browser (default mode)
# ---------------------------------------------------------------------------

def show_lists(query):
    # Folder names from the workflow's own naming config (cfg.get_folders())
    # Keys are groupIds, values are whatever the user typed (e.g. "1 Manager").
    # _folder_order() strips the leading/trailing number and returns a sort key.
    saved_folders = cfg.get_folders()   # {groupId: raw_name}

    def _project_sort_key(p):
        gid = p.get("groupId") or ""
        raw = saved_folders.get(gid, "")
        if raw:
            sort_int, _ = _folder_order(raw)
            return (sort_int, p.get("sortOrder", 0))
        return (9999, p.get("sortOrder", 0))

    ps = sorted(projects(), key=_project_sort_key)
    items = []
    for p in ps:
        pid  = p["id"]
        name = p["name"]
        link = f"ticktick:///webapp/#p/{pid}/tasks"
        gid  = p.get("groupId") or ""
        raw_folder = saved_folders.get(gid, "")
        if raw_folder:
            _, clean_folder = _folder_order(raw_folder)
            folder_label = clean_folder
        else:
            folder_label = ""
        subtitle = f"{folder_label}  ·  Open in TickTick   |  ⌘ Copy link" if folder_label else "Open in TickTick   |  ⌘ Copy link"
        items.append(alfred.item(
            uid=f"project-{pid}",
            title=name,
            subtitle=subtitle,
            arg=f"open:{link}",
            autocomplete=f">{pid} ",
            mods={
                "cmd": {
                    "arg": f"copy:{link}",
                    "subtitle": "Copy deep link to clipboard",
                },
                "alt": {
                    "arg": f"open:{link}",
                    "subtitle": "Browse sections",
                },
            },
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items = [alfred.item(
            uid="no-match",
            title=f'No lists matching "{query}"',
            subtitle="Try a different search, or + to add a task",
            valid=False,
        )]

    # When nothing typed, add mode-switch hints at the top
    if not query:
        hints = [
            alfred.item(
                uid="hint-add",
                title="Add Task",
                subtitle="Type + then your task (e.g. +Buy milk *tomorrow !2 #shopping ~Inbox)",
                arg="",
                autocomplete="+",
                valid=False,
            ),
            alfred.item(
                uid="hint-search",
                title="Search Tasks",
                subtitle="Type / then keywords to search tasks across all lists",
                arg="",
                autocomplete="/",
                valid=False,
            ),
        ]
        items = hints + items

    alfred.print_output(items)


# ---------------------------------------------------------------------------
# Section browser (query prefix ">")
# ---------------------------------------------------------------------------

def show_sections(subquery):
    # subquery: "projectId" or "projectId searchterm"
    parts = subquery.strip().split(" ", 1)
    pid = parts[0].strip()
    search = parts[1].strip() if len(parts) > 1 else ""

    back = alfred.item(
        uid="back",
        title="← All Lists",
        subtitle="Clear to return to list browser",
        arg="",
        autocomplete="",
        valid=False,
    )

    if not pid:
        alfred.print_output([back])
        return

    proj = project_by_id(pid)
    proj_name = proj["name"] if proj else "Unknown list"

    try:
        data = project_sections(pid)
    except Exception as e:
        alfred.print_error(f"Could not load sections for {proj_name}: {e}")
        return

    sections = data.get("sections", [])
    sec_items = []
    for s in sections:
        sid = s.get("id", "")
        sname = s.get("name", "Untitled Section")
        link = f"ticktick:///webapp/#p/{pid}/tasks/{sid}"
        sec_items.append(alfred.item(
            uid=f"section-{sid}",
            title=sname,
            subtitle=f"{proj_name}   |  ⌘ Copy link",
            arg=f"open:{link}",
            mods={
                "cmd": {
                    "arg": f"copy:{link}",
                    "subtitle": "Copy section deep link",
                },
            },
        ))

    if search:
        sec_items = fuzz.filter_and_score(search, sec_items, key_fn=lambda x: x["title"])

    if not sec_items:
        sec_items = [alfred.item(
            uid="no-sections",
            title="No sections in this list",
            subtitle=proj_name,
            valid=False,
        )]

    alfred.print_output([back] + sec_items)


# ---------------------------------------------------------------------------
# Task search (query prefix "/")
# ---------------------------------------------------------------------------

def search_tasks(query):
    tasks = all_tasks()

    if query:
        tasks = fuzz.filter_and_score(query, tasks, key_fn=lambda t: t.get("title", ""))
    else:
        # Default: soonest-due incomplete tasks
        tasks = sorted(
            [t for t in tasks if t.get("dueDate") and not t.get("completedTime")],
            key=lambda t: t.get("dueDate", ""),
        )

    tasks = tasks[:25]

    if not tasks:
        alfred.print_output([alfred.item(
            uid="no-tasks",
            title="No tasks found",
            subtitle=f'Nothing matching "{query}"' if query else "No upcoming tasks",
            valid=False,
        )])
        return

    items = []
    for t in tasks:
        tid = t.get("id", "")
        pid = t.get("projectId") or t.get("_projectId", "")
        title = t.get("title") or "Untitled"
        proj_name = t.get("_projectName", "")
        due = t.get("dueDate", "")[:10] if t.get("dueDate") else ""
        priority = t.get("priority", 0)

        meta = "  ·  ".join(filter(None, [
            proj_name,
            f"Due {due}" if due else "",
            PRIORITY_LABEL.get(priority, ""),
        ]))

        task_link = (
            f"ticktick:///webapp/#p/{pid}/tasks"
            if pid else "ticktick:///webapp/#q/all/tasks"
        )

        items.append(alfred.item(
            uid=f"task-{tid}",
            title=title,
            subtitle=f"{meta}   |  ⌘ Complete  |  ⌥ Reschedule" if meta
                    else "Open in TickTick   |  ⌘ Complete  |  ⌥ Reschedule",
            arg=f"open:{task_link}",
            mods={
                "cmd": {
                    "arg": _encode_action("complete", pid, tid, title),
                    "subtitle": f"Mark complete: {title}",
                },
                "alt": {
                    "arg": f"open:{task_link}",
                    "subtitle": "Open to reschedule in TickTick",
                },
            },
        ))

    alfred.print_output(items)


# ---------------------------------------------------------------------------
# Add task (query prefix "+")
# ---------------------------------------------------------------------------

def show_add_task(query):
    # Check for active sub-pickers triggered by ~ or #
    tilde_match = re.search(r"~(\S*)$", query)
    hash_match = re.search(r"#(\S*)$", query)

    if tilde_match:
        _show_list_picker(query, tilde_match)
        return
    if hash_match:
        _show_tag_picker(query, hash_match)
        return

    parsed = _parse_task(query)
    payload = parsed["payload"]
    has_title = bool(payload.get("title", "").strip())

    preview = alfred.item(
        uid="create-task",
        title=parsed["display_title"],
        subtitle=_build_task_subtitle(parsed),
        arg=_encode_create(payload),
        valid=has_title,
        mods={
            "cmd": {
                "arg": _encode_create(payload),
                "subtitle": "Create task (same as Enter)",
            },
        } if has_title else {},
    )

    hints = []
    if not parsed["has_date"]:
        hints.append(alfred.item(
            uid="hint-date",
            title="Add a date",
            subtitle="Append *tomorrow, *next monday, *2pm, *Friday 3pm …",
            valid=False,
            autocomplete=f"+{query} *",
        ))
    if not parsed["has_list"]:
        hints.append(alfred.item(
            uid="hint-list",
            title="Assign to a list",
            subtitle="Append ~ListName  ↵ to pick",
            valid=False,
            autocomplete=f"+{query} ~",
        ))
    if not parsed["has_tags"]:
        hints.append(alfred.item(
            uid="hint-tag",
            title="Add a tag",
            subtitle="Append #TagName  ↵ to pick",
            valid=False,
            autocomplete=f"+{query} #",
        ))

    alfred.print_output([preview] + hints)


def _show_list_picker(query, tilde_match):
    list_query = tilde_match.group(1)
    prefix = query[: tilde_match.start()]
    ps = projects()
    matches = fuzz.filter_and_score(list_query, ps, key_fn=lambda p: p["name"])

    items = []
    for p in matches[:12]:
        completed = f"+{prefix}~{p['name']} "
        items.append(alfred.item(
            uid=f"listpick-{p['id']}",
            title=p["name"],
            subtitle=f"↵ Assign task to this list",
            arg=completed,
            autocomplete=completed,
            valid=False,
        ))

    if not items:
        items = [alfred.item(
            uid="no-list-match",
            title=f'No list matching "~{list_query}"',
            subtitle="Keep typing or press Escape",
            valid=False,
        )]
    alfred.print_output(items)


def _show_tag_picker(query, hash_match):
    tag_query = hash_match.group(1)
    prefix = query[: hash_match.start()]
    tags = known_tags()
    matches = fuzz.filter_and_score(tag_query, tags) if tag_query else tags

    items = []
    for tag in matches[:12]:
        completed = f"+{prefix}#{tag} "
        items.append(alfred.item(
            uid=f"tagpick-{tag}",
            title=f"#{tag}",
            subtitle="↵ Add this tag",
            arg=completed,
            autocomplete=completed,
            valid=False,
        ))

    if not items:
        items = [alfred.item(
            uid="no-tag-match",
            title=f'No tag matching "#{tag_query}"',
            subtitle="Tags are discovered from cached tasks",
            valid=False,
        )]
    alfred.print_output(items)


# ---------------------------------------------------------------------------
# Task NLP parser
# ---------------------------------------------------------------------------

def _parse_task(text):
    import parsedatetime
    from datetime import datetime

    cal = parsedatetime.Calendar()
    remaining = text
    payload = {}
    has_date = has_list = has_tags = False
    date_text = ""

    # List (~word)
    m = re.search(r"~(\S+)", remaining)
    if m:
        name = m.group(1)
        ps = projects()
        matches = fuzz.filter_and_score(name, ps, key_fn=lambda p: p["name"])
        if matches:
            payload["projectId"] = matches[0]["id"]
            payload["_listName"] = matches[0]["name"]
            has_list = True
        remaining = remaining[: m.start()] + remaining[m.end():]

    # Tags (#word)
    tag_matches = re.findall(r"#(\S+)", remaining)
    if tag_matches:
        payload["tags"] = tag_matches
        has_tags = True
        remaining = re.sub(r"#\S+", "", remaining)

    # Priority (!1-3)
    pm = re.search(r"!([1-3])", remaining)
    if pm:
        pmap = {"1": 1, "2": 3, "3": 5}
        payload["priority"] = pmap[pm.group(1)]
        remaining = remaining[: pm.start()] + remaining[pm.end():]

    # Date (*text until next special char or end)
    dm = re.search(r"\*(.+?)(?=\s*[~#!]|\s*$)", remaining)
    if dm:
        date_text = dm.group(1).strip()
        ts, status = cal.parse(date_text)
        if status:
            dt = datetime(*ts[:6])
            payload["dueDate"] = dt.strftime("%Y-%m-%dT%H:%M:%S+0000")
            has_date = True
        remaining = remaining[: dm.start()] + remaining[dm.end():]

    title = re.sub(r"\s+", " ", remaining).strip()
    payload["title"] = title

    # Build display title
    meta_parts = []
    if has_date and date_text:
        meta_parts.append(f"Due: {date_text}")
    if "_listName" in payload:
        meta_parts.append(payload.pop("_listName"))
    if has_tags:
        meta_parts.append(", ".join(f"#{t}" for t in payload.get("tags", [])))
    if payload.get("priority"):
        meta_parts.append(PRIORITY_LABEL.get(payload["priority"], ""))

    display_title = title if title else "(type a task title)"
    if meta_parts:
        display_title = f"{display_title}  ·  {', '.join(meta_parts)}"

    return {
        "payload": payload,
        "display_title": display_title,
        "has_date": has_date,
        "has_list": has_list,
        "has_tags": has_tags,
    }


def _build_task_subtitle(parsed):
    payload = parsed["payload"]
    parts = []
    if payload.get("title"):
        parts.append("Press Enter to create")
    else:
        parts.append("Type a task title")
    if payload.get("dueDate"):
        parts.append(f"📅 {payload['dueDate'][:10]}")
    if payload.get("priority"):
        parts.append(f"⚡ {PRIORITY_LABEL.get(payload['priority'])}")
    return "   ·   ".join(parts)


# ---------------------------------------------------------------------------
# Arg encoding helpers (base64 to survive Alfred escaping)
# ---------------------------------------------------------------------------

def _encode_create(payload):
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"create:{data}"


def _encode_action(action, *parts):
    return f"{action}:{':'.join(str(p) for p in parts)}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if query.startswith(">"):
            show_sections(query[1:])
        elif query.startswith("+"):
            show_add_task(query[1:])
        elif query.startswith("/"):
            search_tasks(query[1:])
        else:
            show_lists(query)
    except Exception as e:
        alfred.print_error(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
