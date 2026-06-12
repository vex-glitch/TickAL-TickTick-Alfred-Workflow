#!/usr/bin/env python3
"""
add_task.py — Alfred Script Filter
Natural language task creation with live sub-pickers.

Syntax:  Buy milk *tomorrow @08:30 !2 #shopping ~Personal
  *  → date      (parsedatetime — natural language)
  @  → time      (24h dropdown: hour → minute 00/15/30/45)
  !  → priority  1=low  2=medium  3=high
  #  → tag       (sub-picker from cache)
  ~  → list      (sub-picker from cache)

Enter on a sub-picker result fills it back into the query.
Enter on the task preview creates it via dispatch.py.
"""
import sys
import os
import re
import json
import base64
import traceback

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    print(json.dumps({"items": [{"title": "Path error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

try:
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from api import TickTickAPI
    from dateutil import (parse_date,
                          utc_to_local_display   as _utc_iso_to_local_display,
                          utc_to_picker_display  as _utc_iso_to_picker_display,
                          build_date_shortcuts)
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Constants ────────────────────────────────────────────────────────────────
PRIORITY_OPTIONS = [
    ("!1", "↓ Low priority",    1),
    ("!2", "↑ Medium priority", 3),
    ("!3", "⬆ High priority",   5),
]
PRIORITY_VAL = {"1": 1, "2": 3, "3": 5}
PRIORITY_LABEL = {1: "↓", 3: "↑", 5: "⬆"}

# ── Data helpers ─────────────────────────────────────────────────────────────
def get_lists():
    data = cache_store.get("projects")
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_projects()
        cache_store.set("projects", data)
    return [p for p in data if p.get("kind") not in ("SMART_LIST", "NOTE")]

def get_note_lists():
    data = cache_store.get("projects")
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_projects()
        cache_store.set("projects", data)
    return [p for p in data if p.get("kind") == "NOTE"]

def get_tags():
    cached  = cache_store.get("tags") or []
    manual  = cfg.get_tags()
    return sorted(set(cached) | set(manual))

# ── Query parser ─────────────────────────────────────────────────────────────
def find_active_trigger(query):
    """
    Find the last trigger char (~, #, !, *, /, >) that starts a word and hasn't
    been 'closed' yet (for single-word triggers: no space after it;
    for *date: always open so user can type multi-word dates).
    Returns (trigger, prefix_before_trigger, fragment_after_trigger) or None.
    """
    for i in range(len(query) - 1, -1, -1):
        ch = query[i]
        if ch not in ('~', '#', '!', '*', '/', '>', '@'):
            continue
        # Must be at start or preceded by a space
        if i > 0 and query[i - 1] != ' ':
            continue
        prefix   = query[:i]
        fragment = query[i + 1:]
        # Single-word triggers: if fragment contains a space the token is done
        if ch in ('~', '#', '!', '/', '>') and ' ' in fragment:
            return None
        # Date / time triggers: if fragment ends with a space the token is done
        if ch in ('*', '@') and fragment.endswith(' '):
            return None
        return (ch, prefix, fragment)
    return None

def parse_task(query):
    """Extract structured fields from the raw query string."""
    q = query

    # >section (can be multi-word, ends at next trigger or end of string)
    section_name = None
    m = re.search(r'(?<!\S)>(.+?)(?=\s+[~#!*/>]|\s*$)', q)
    if m:
        section_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # /parent_task (can be multi-word, ends at next trigger or end of string)
    parent_name = None
    m = re.search(r'(?<!\S)/(.+?)(?=\s+[~#!*/>]|\s*$)', q)
    if m:
        parent_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # ~list (can be multi-word, ends at next trigger or end of string)
    list_name = None
    m = re.search(r'(?<!\S)~(.+?)(?=\s+[~#!*/>]|\s*$)', q)
    if m:
        list_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # #tags (single word each, multiple allowed)
    tags = []
    while True:
        m = re.search(r'(?<!\S)#(\S+)', q)
        if not m:
            break
        tags.append(m.group(1))
        q = q[:m.start()] + q[m.end():]

    # !priority (1/2/3)
    priority = 0
    m = re.search(r'(?<!\S)!([123])', q)
    if m:
        priority = PRIORITY_VAL[m.group(1)]
        q = q[:m.start()] + q[m.end():]

    # *date — greedily takes everything to next trigger or end (stops at @)
    date_str = None
    m = re.search(r'(?<!\S)\*(.+?)(?=\s*[~#!/>@]|$)', q)
    if m:
        date_str = m.group(1).strip()
        q = q[:m.start()] + q[m.end():]

    # @time — HH:MM explicit time picker result
    time_str = None
    m = re.search(r'(?<!\S)@(\d{1,2}:\d{2})\b', q)
    if m:
        time_str = m.group(1).strip()
        q = q[:m.start()] + q[m.end():]

    title = ' '.join(q.split())
    return title, date_str, time_str, priority, tags, list_name, parent_name, section_name

def resolve_list_id(list_name, lists):
    """Find project ID by name (case-insensitive prefix/contains match)."""
    name_lower = list_name.lower()
    for p in lists:
        if p["name"].lower() == name_lower:
            return p["id"], p["name"]
    for p in lists:
        if p["name"].lower().startswith(name_lower):
            return p["id"], p["name"]
    for p in lists:
        if name_lower in p["name"].lower():
            return p["id"], p["name"]
    return None, list_name

# ── Sub-pickers ───────────────────────────────────────────────────────────────
def list_picker(prefix, fragment, lists=None):
    if lists is None:
        lists = get_lists()
    items = []
    for p in lists:
        name = p["name"]
        filled = f"{prefix}~{name} "
        items.append(alfred.item(
            title=name,
            subtitle="↵ Select",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No lists matching "{fragment}"', valid=False)]
    return items


def tag_picker(prefix, fragment):
    tags = get_tags()
    items = []
    for tag in tags:
        filled = f"{prefix}#{tag} "
        items.append(alfred.item(
            title=tag,
            subtitle="↵ Select",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not tags:
        items = [alfred.item(title="No tags cached — run Sync first", valid=False)]
    elif not items:
        items = [alfred.item(title=f'No tags matching "{fragment}"', valid=False)]
    return items

def priority_picker(prefix, fragment):
    items = []
    for token, label, _ in PRIORITY_OPTIONS:
        filled = f"{prefix}{token} "
        items.append(alfred.item(
            title=label,
            subtitle="↵ Select",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    if fragment:
        items = [i for i in items if fragment in i["title"].lower()]
    return items or [alfred.item(title="Type 1, 2, or 3", valid=False)]

def section_picker(prefix, fragment, current_list_id=None):
    projects = cache_store.get("projects") or []
    search   = [p for p in projects if p["id"] == current_list_id] if current_list_id else projects

    items = []
    for proj in search:
        proj_data = cache_store.get(f"project_data_{proj['id']}")
        if not proj_data:
            continue
        for col in proj_data.get("columns", []):
            col_name = col.get("name", "").strip()
            if not col_name or col_name.lower() == "not sectioned":
                continue
            subtitle = "" if current_list_id else proj["name"]
            filled   = f"{prefix}>{col_name} "
            items.append(alfred.item(
                title=col_name,
                subtitle=subtitle + ("  ↵ Select" if subtitle else "↵ Select"),
                arg="",
                valid=False,
                autocomplete=filled,
            ))

    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        msg = f'No sections matching "{fragment}"' if fragment else "No sections cached — run Sync first"
        items = [alfred.item(title=msg, valid=False)]
    return items


def task_picker(prefix, fragment):
    all_tasks = cache_store.get("all_tasks") or []
    candidates = [t for t in all_tasks if t.get("status", 0) == 0]
    task_map   = {t["id"]: t for t in all_tasks}

    items = []
    for t in candidates:
        title     = t.get("title", "Untitled")
        list_name = t.get("_projectName", "")
        parent_id = t.get("parentId", "")

        if parent_id:
            parent       = task_map.get(parent_id)
            parent_title = parent.get("title", "") if parent else ""
            subtitle     = f"↳ {parent_title}  ·  {list_name}" if parent_title else list_name
        else:
            subtitle = list_name or ""

        filled = f"{prefix}/{title} "
        items.append(alfred.item(
            title=title,
            subtitle=subtitle + "  ↵ Select" if subtitle else "↵ Select",
            arg="",
            valid=False,
            autocomplete=filled,
        ))

    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        msg = f'No tasks matching "{fragment}"' if fragment else "No tasks cached — run Sync first"
        items = [alfred.item(title=msg, valid=False)]
    return items


def date_picker(prefix, fragment):
    shortcuts  = build_date_shortcuts()
    items      = []
    frag_lower = fragment.lower().strip() if fragment else ""
    typing     = bool(frag_lower)   # True when user has typed something

    # Custom free-typed date — shown first when typing
    if fragment and fragment.strip():
        resolved_frag = parse_date(fragment)
        if resolved_frag:
            display = _utc_iso_to_picker_display(resolved_frag)
            filled  = f"{prefix}*{fragment.strip()} "
            items.append(alfred.item(
                title=display,
                subtitle="⏎ Schedule",
                arg="", valid=False, autocomplete=filled,
            ))

    # Shortcut list — filter by fragment against parse string, label, and extra tags
    seen_iso = set()
    for shortcut in shortcuts:
        parse_str, label = shortcut[0], shortcut[1]
        extra = shortcut[2] if len(shortcut) > 2 else ""
        search = f"{parse_str} {label.lower()} {extra}".strip()
        if frag_lower and frag_lower not in search:
            continue
        resolved = parse_date(parse_str)
        if not resolved:
            continue
        # Deduplicate by date — first shortcut for a given date wins
        # (keeps "In 3 Days" and bumps any later entry on the same date)
        if resolved in seen_iso:
            continue
        seen_iso.add(resolved)
        display = _utc_iso_to_picker_display(resolved)
        filled  = f"{prefix}*{parse_str} "
        items.append(alfred.item(
            title=label,
            subtitle=display + ("  ·  ⏎ Schedule" if typing else ""),
            arg="", valid=False, autocomplete=filled,
        ))

    if not items:
        items = [alfred.item(
            title=f'Can\'t parse "{fragment}" as a date' if fragment else "Type a date or phrase",
            subtitle="e.g. tomorrow · 21/07 · next monday · in 3 days",
            valid=False,
        )]
    return items

def _hour_ampm(h):
    """Return a 12h AM/PM label for a 0–23 hour integer."""
    if h == 0:   return "12 AM"
    if h < 12:   return f"{h} AM"
    if h == 12:  return "12 PM"
    return f"{h - 12} PM"

def time_picker(prefix, fragment):
    """Show hour dropdown (no colon in fragment) or minute dropdown (colon present)."""
    items = []
    if ':' not in fragment:
        # Hour selection — show 00–23, filtered by whatever the user typed so far
        frag = fragment.strip()
        frag_int = int(frag) if frag.isdigit() else None

        for h in range(24):
            hh = f"{h:02d}"
            # Standard prefix match
            matches = hh.startswith(frag) or str(h).startswith(frag)
            # AM/PM assist: "6" also surfaces 18, "8" also surfaces 20, etc.
            if not matches and frag_int and 1 <= frag_int <= 12:
                matches = (h == frag_int + 12)
            if frag and not matches:
                continue
            filled = f"{prefix}@{hh}:"
            ampm   = _hour_ampm(h)
            items.append(alfred.item(
                title=hh,
                subtitle=f"{ampm}  ·  ⏎ Confirm and pick minutes",
                arg="",
                valid=False,
                autocomplete=filled,
            ))
    else:
        # Minute selection — always show all four options for the chosen hour
        hour_part = fragment.split(':')[0]
        try:
            h = int(hour_part)
            hh = f"{h:02d}"
        except ValueError:
            hh = hour_part
        for m in (0, 15, 30, 45):
            label  = f"{hh}:{m:02d}"
            filled = f"{prefix}@{label} "
            items.append(alfred.item(
                title=label,
                subtitle=f"↵ Set time to {label}",
                arg="",
                valid=False,
                autocomplete=filled,
            ))
    if not items:
        items = [alfred.item(
            title=f'No hours matching "{fragment}"',
            subtitle="Type 0–23 to filter",
            valid=False,
        )]
    return items

# ── Notification builder ─────────────────────────────────────────────────────
def _build_notif(title, list_display, env_list_id, env_section_id, env_task_id, section_display=None):
    """
    Returns the notification string for a task creation, potentially two lines:
      Line 1 — action label  ("Subtask added" / "Task added to {Section}" / etc.)
      Line 2 — breadcrumb path  ("{List} › {Section} › {Parent task} › …")
    """
    # Section name — explicit override, then env var, then cache lookup
    section_name = section_display or os.environ.get("section_name", "")
    if (not section_name
            and env_section_id
            and env_section_id not in ("UNSECTIONED", "")
            and env_list_id):
        proj_data = cache_store.get(f"project_data_{env_list_id}")
        if proj_data:
            for col in proj_data.get("columns", []):
                if col.get("id") == env_section_id:
                    sname = col.get("name", "").strip()
                    if sname.lower() != "not sectioned":
                        section_name = sname
                    break

    # Walk the parent-task chain (root → … → immediate parent)
    parent_titles = []
    if env_task_id:
        task_map = {t["id"]: t for t in (cache_store.get("all_tasks") or [])}
        pid = env_task_id
        while pid:
            t = task_map.get(pid)
            if not t:
                break
            parent_titles.insert(0, t.get("title", "?"))
            pid = t.get("parentId")

    depth = len(parent_titles)   # 0 = new top-level task, 1 = subtask, 2 = sub-subtask, …

    # ── Line 1: action label ──────────────────────────────────────────────────
    if depth == 0:
        if section_name:
            line1 = f"Task {title} added to {section_name}"
        else:
            line1 = f"Task {title} added to {list_display or 'Inbox'}"
    elif depth == 1:
        line1 = f"Subtask {title} added"
    elif depth == 2:
        line1 = f"Sub-subtask {title} added"
    else:
        line1 = ("Sub-" * (depth - 1)) + f"subtask {title} added"

    # ── Line 2: breadcrumb including the new task ─────────────────────────────
    crumb = []
    if list_display:
        crumb.append(list_display)
    if depth == 0:
        if section_name:
            crumb.append(section_name)
    else:
        if section_name:
            crumb.append(section_name)
        crumb.extend(parent_titles)
    crumb.append(title)   # new task always goes at the end

    line2 = " › ".join(crumb) if len(crumb) > 1 else ""
    return f"{line1}\n{line2}" if line2 else line1


# ── Task preview ──────────────────────────────────────────────────────────────
def task_preview(query):
    title, date_str, time_str, priority, tags, list_name, parent_name, section_name = parse_task(query)

    if not title:
        return [alfred.item(
            title="Type a task name…",
            subtitle="Add *date  !priority  #tag  ~list  >section  /parent",
            valid=False,
        )]

    lists    = get_lists()
    list_id  = None
    list_display = None

    # Pre-filled from env (coming from a list/section/task modifier)
    env_list_id    = os.environ.get("list_id") or os.environ.get("task_list_id", "")
    env_list_name  = os.environ.get("list_name", "")
    env_section_id = os.environ.get("section_id", "")
    env_task_id    = os.environ.get("task_id", "")    # set when adding a subtask via ⌘

    if list_name:
        list_id, list_display = resolve_list_id(list_name, lists)
    elif env_list_id:
        list_id      = env_list_id
        # If list_name wasn't in env, look it up from the projects cache
        if env_list_name:
            list_display = env_list_name
        else:
            list_display = next((p["name"] for p in lists if p["id"] == env_list_id), "")

    # Resolve >section — search the already-known list first, then all lists
    section_id      = None
    section_display = None
    if section_name:
        search_list_ids = [list_id] if list_id else [p["id"] for p in get_lists()]
        for sid in search_list_ids:
            if not sid:
                continue
            proj_data = cache_store.get(f"project_data_{sid}")
            if not proj_data:
                continue
            for col in proj_data.get("columns", []):
                if col.get("name", "").strip().lower() == section_name.lower():
                    section_id      = col["id"]
                    section_display = col.get("name", section_name)
                    # Inherit list from section's project if not yet set
                    if not list_id:
                        list_id      = sid
                        list_display = next((p["name"] for p in get_lists() if p["id"] == sid), "")
                    break
            if section_id:
                break

    # Resolve /parent_task — explicit choice overrides env task_id
    parent_id      = None
    parent_display = None
    if parent_name:
        all_tasks_cache = cache_store.get("all_tasks") or []
        resolved = next(
            (t for t in all_tasks_cache
             if t.get("title", "").lower() == parent_name.lower()
             and t.get("status", 0) == 0),
            None,
        ) or next(
            (t for t in all_tasks_cache
             if parent_name.lower() in t.get("title", "").lower()
             and t.get("status", 0) == 0),
            None,
        )
        if resolved:
            parent_id      = resolved["id"]
            parent_display = resolved.get("title", parent_name)
            # Inherit list from parent if no list explicitly set
            if not list_id:
                list_id      = resolved.get("_projectId") or resolved.get("projectId", "")
                list_display = resolved.get("_projectName", "")

    # Effective parent: explicit /task choice wins over env
    effective_parent_id = parent_id or env_task_id

    # Combine *date and @time into a single string for parsing
    if date_str and time_str:
        combined_date_str = f"{date_str} {time_str}"
    elif time_str:
        combined_date_str = f"today {time_str}"
    else:
        combined_date_str = date_str
    due_date = parse_date(combined_date_str)

    # Build subtitle summary
    parts = []
    parts.append(f"~{list_display}" if list_display else "~Inbox")
    if section_display:
        parts.append(f">{section_display}")
    elif section_name:
        parts.append(f">{section_name}?")
    if parent_display:
        parts.append(f"/{parent_display}")
    elif parent_name:
        parts.append(f"/{parent_name}?")
    if date_str or time_str:
        if due_date:
            date_display = _utc_iso_to_local_display(due_date)
        else:
            raw = combined_date_str or ""
            date_display = f"{raw}?"
        parts.append(f"*{date_display}")
    if priority:
        parts.append(f"{PRIORITY_LABEL[priority]} priority")
    for t in tags:
        parts.append(f"#{t}")
    subtitle = ("  ".join(parts) + "  |  " if parts else "") + "* Date  @ Time  ! Priority  # Tag  ~ List  > Section  / Parent"

    payload = {"title": title, "listName": list_display}
    if list_id:
        payload["projectId"] = list_id
    if due_date:
        payload["dueDate"] = due_date
    if priority:
        payload["priority"] = priority
    if tags:
        payload["tags"] = tags
    if section_id and not effective_parent_id:
        payload["columnId"] = section_id
    elif env_section_id and not effective_parent_id:
        payload["columnId"] = env_section_id
    elif env_list_id and not effective_parent_id:
        # Find the "Not Sectioned" column and use its ID
        cached = cache_store.get(f"project_data_{env_list_id}")
        if cached:
            for col in cached.get("columns", []):
                if col.get("name", "").strip().lower() == "not sectioned":
                    payload["columnId"] = col["id"]
                    break
    if effective_parent_id:
        payload["parentId"] = effective_parent_id

    payload["_notif_text"] = _build_notif(
        title, list_display or "", env_list_id, env_section_id, effective_parent_id,
        section_display=section_display,
    )

    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    return [alfred.item(
        title=f"Create: {title}",
        subtitle=subtitle,
        arg=f"create:{encoded}",
        valid=True,
    )]

# ── Note preview ─────────────────────────────────────────────────────────────
def note_preview(query):
    title, _, _, _, _, list_name, parent_name, section_name = parse_task(query)

    if not title:
        return [alfred.item(
            title="Type a note title…",
            subtitle="~ List  > Section  / Parent note",
            valid=False,
        )]

    all_lists    = get_lists() + get_note_lists()
    list_id      = None
    list_display = None

    env_list_id   = os.environ.get("list_id") or os.environ.get("task_list_id", "")
    env_list_name = os.environ.get("list_name", "")
    env_task_id   = os.environ.get("task_id", "")

    if list_name:
        list_id, list_display = resolve_list_id(list_name, all_lists)
    elif env_list_id:
        list_id      = env_list_id
        list_display = env_list_name or next(
            (p["name"] for p in all_lists if p["id"] == env_list_id), ""
        )

    # Resolve >section
    section_id      = None
    section_display = None
    if section_name and list_id:
        proj_data = cache_store.get(f"project_data_{list_id}")
        if proj_data:
            for col in proj_data.get("columns", []):
                if col.get("name", "").strip().lower() == section_name.lower():
                    section_id      = col["id"]
                    section_display = col.get("name", section_name)
                    break

    # Resolve /parent — search notes only (tasks in NOTE-type projects)
    parent_id      = None
    parent_display = None
    if parent_name:
        all_tasks_cache = cache_store.get("all_tasks") or []
        resolved = next(
            (t for t in all_tasks_cache
             if t.get("title", "").lower() == parent_name.lower()),
            None,
        ) or next(
            (t for t in all_tasks_cache
             if parent_name.lower() in t.get("title", "").lower()),
            None,
        )
        if resolved:
            parent_id      = resolved["id"]
            parent_display = resolved.get("title", parent_name)
            if not list_id:
                list_id      = resolved.get("_projectId") or resolved.get("projectId", "")
                list_display = resolved.get("_projectName", "")

    effective_parent_id = parent_id or env_task_id

    # Build subtitle
    parts = []
    parts.append(f"~{list_display}" if list_display else "~Notes")
    if section_display:
        parts.append(f">{section_display}")
    elif section_name:
        parts.append(f">{section_name}?")
    if parent_display:
        parts.append(f"/{parent_display}")
    elif parent_name:
        parts.append(f"/{parent_name}?")
    subtitle = ("  ".join(parts) + "  |  " if parts else "") + "~ List  > Section  / Parent note"

    # Build payload
    payload = {"title": title, "kind": "NOTE"}
    if list_id:
        payload["projectId"] = list_id
    if section_id and not effective_parent_id:
        payload["columnId"] = section_id
    if effective_parent_id:
        payload["parentId"] = effective_parent_id

    # Notification text
    list_label = list_display or "Notes"
    if section_display and not effective_parent_id:
        notif = f"Note {title} added to {section_display}\n{list_label} › {section_display} › {title}"
    elif effective_parent_id:
        parent_label = parent_display or "note"
        notif = f"Sub-note {title} added\n{list_label} › {parent_label} › {title}"
    else:
        notif = f"Note {title} added to {list_label}"
    payload["_notif_text"] = notif

    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return [alfred.item(
        title=f"Create note: {title}",
        subtitle=subtitle,
        arg=f"create:{encoded}",
        valid=True,
    )]


# ── List creation mode ────────────────────────────────────────────────────────
def list_create_items(name):
    if not name:
        return [alfred.item(
            title="Type a list name…",
            subtitle="Create list  ⇧⌘ Back",
            valid=False,
        )]
    payload = {"name": name}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return [alfred.item(
        title=f"Create list: {name}",
        subtitle="Create  Move to a folder in TickTick afterwards  ⇧⌘ Back",
        arg=f"create_list:{encoded}",
        valid=True,
    )]


# ── Project creation mode ─────────────────────────────────────────────────────
# Keycap number emoji: digit + U+FE0F (variation selector) + U+20E3 (keycap)
AREA_RE = re.compile(r"^([0-9]️?⃣)")

def get_area_tags():
    """Area tags from tags_config.py — entries starting with a keycap number."""
    try:
        cfg_path = os.path.join(WORKFLOW_DIR, "tags_config.py")
        ns = {}
        with open(cfg_path, encoding="utf-8") as f:
            exec(f.read(), ns)
        tags = ns.get("TAGS", [])
    except Exception:
        tags = []
    areas = []
    for t in tags:
        m = AREA_RE.match(t)
        if m:
            areas.append((t, m.group(1)))  # ("1️⃣Work", "1️⃣")
    return areas


def project_create_items(name):
    if not name:
        return [alfred.item(
            title="Type a project name…",
            subtitle="Creates 💼P • list + PM meta task  ⇧⌘ Back",
            valid=False,
        )]
    areas = get_area_tags()
    if not areas:
        return [alfred.item(
            title="No area tags found",
            subtitle="tags_config.py has no tags starting with a number emoji (1️⃣…)",
            valid=False,
        )]
    items = []
    for tag, emoji in areas:
        payload = base64.b64encode(json.dumps(
            {"name": name, "tag": tag, "emoji": emoji}
        ).encode()).decode()
        items.append(alfred.item(
            uid=f"area-{tag}",
            title=tag,
            subtitle=f"Create  💼P • {name} {emoji}  +  PM • {name} 🗺️",
            arg=f"create_project_meta:{payload}",
        ))
    return items


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    # Strip routing prefixes passed as initial arg from upstream script filters
    for prefix in ("addtask:", "addsection:", "addsubtask:", "stickynote:",
                   "pomodoro:", "attributes:", "complete:", "add"):
        if query.startswith(prefix):
            query = ""
            break

    try:
        # ── Empty → hint ──────────────────────────────────────────────────────
        if not query:
            items = [alfred.item(
                title="Type to add a task…",
                subtitle="Prefix: L List · N Notes · P Project",
                valid=False,
            )]
            print(alfred.output(items, skipknowledge=True))
            return

        # ── L prefix → create list ────────────────────────────────────────────
        if query.lower().startswith("l "):
            items = list_create_items(query[2:].strip())
            print(alfred.output(items, skipknowledge=True))
            return

        # ── P prefix → create project + meta task ─────────────────────────────
        if query.lower().startswith("p "):
            items = project_create_items(query[2:].strip())
            print(alfred.output(items, skipknowledge=True))
            return

        # ── N prefix → create note ────────────────────────────────────────────
        if query.lower().startswith("n "):
            all_lists = get_lists() + get_note_lists()
            trigger = find_active_trigger(query)
            if trigger:
                ch, prefix, fragment = trigger
                if ch == '~':
                    items = list_picker(prefix, fragment, lists=all_lists)
                elif ch == '>':
                    _, _, _, _, _, ln, _, _ = parse_task(query[2:])
                    cur_lid = resolve_list_id(ln, all_lists)[0] if ln else None
                    items = section_picker(prefix, fragment, current_list_id=cur_lid)
                elif ch == '/':
                    items = task_picker(prefix, fragment)
                else:
                    items = note_preview(query[2:])
            else:
                items = note_preview(query[2:])
            print(alfred.output(items, skipknowledge=True))
            return

        # ── Task creation ─────────────────────────────────────────────────────
        trigger = find_active_trigger(query)

        if trigger:
            ch, prefix, fragment = trigger
            if ch == '~':
                items = list_picker(prefix, fragment)
            elif ch == '#':
                items = tag_picker(prefix, fragment)
            elif ch == '!':
                items = priority_picker(prefix, fragment)
            elif ch == '*':
                items = date_picker(prefix, fragment)
            elif ch == '@':
                items = time_picker(prefix, fragment)
            elif ch == '>':
                # Pass current resolved list_id if ~ was already typed
                _, _, _, _, _, ln, _, _ = parse_task(prefix)
                cur_lid = resolve_list_id(ln, get_lists())[0] if ln else None
                items = section_picker(prefix, fragment, current_list_id=cur_lid)
            elif ch == '/':
                items = task_picker(prefix, fragment)
        else:
            items = task_preview(query)

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        print(json.dumps({"items": [{
            "title": "Error in add_task.py",
            "subtitle": f"{type(e).__name__}: {e}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
