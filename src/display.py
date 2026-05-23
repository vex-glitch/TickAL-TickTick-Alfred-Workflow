#!/usr/bin/env python3
"""
display.py — Shared display helpers for Alfred task items.

All task-displaying scripts import from here to ensure consistent
formatting of titles, subtitles, dates, priority, and breadcrumbs.
"""
import re
from datetime import datetime, timezone

# Pre-compiled patterns for search key cleaning
_MD_LINK_RE     = re.compile(r'\[([^\]]*)\]\([^)]*\)')  # [text](url) → text
_URL_RE         = re.compile(r'https?://\S+')
_TAG_SUFFIX_RE  = re.compile(r'\s+#\s+\S.*$')           # ' # tag1 tag2…' suffix            # bare URLs

# Priority suffix emojis — appended after the task name in the title field
PRIORITY = {0: "⚫️", 1: "🟡", 3: "🟠", 5: "🔴"}

# Modifier key line — shown in every task subtitle
MODIFIERS = "Open  ⌘ Add  ⇧ Done  ⌥ Browse  ⌥⌘ URL  ⌃ Modify  ⇧⌘ Back"


def fmt_date(task):
    """
    Return '📆 DD/MM/YYYY HH:MM' or '' if no date is set.
    Uses startDate preferentially (TickTick displays startDate in the UI).
    Time is shown only when the UTC time has non-zero hours/minutes
    (all-day tasks are stored as T00:00:00Z by the TickTick API).
    """
    date_str = task.get("startDate") or task.get("dueDate") or ""
    if not date_str:
        return ""
    try:
        clean  = date_str[:19]
        dt_utc = datetime(
            int(clean[0:4]),  int(clean[5:7]),  int(clean[8:10]),
            int(clean[11:13]), int(clean[14:16]), int(clean[17:19]),
            tzinfo=timezone.utc,
        )
        local  = dt_utc.astimezone()
        result = local.strftime("%d/%m/%Y")
        # Show time only for timed tasks (all-day = 00:00:00 UTC)
        if int(clean[11:13]) != 0 or int(clean[14:16]) != 0:
            result += local.strftime(" %H:%M")
        return f"📆 {result}"
    except Exception:
        return ""


def build_title(task, breadcrumb=""):
    """
    Build the Alfred item title field.
    Format: 'Task Name ⚫️ 📆 13/05/2026 | List>Section # tag1 tag2'
             'Task Name ⚫️ | List>Section # tag1 tag2'   (no date → nothing shown)
             'Task Name ⚫️ # tag1 tag2'                  (no breadcrumb)
    """
    name     = task.get("title", "Untitled")
    priority = PRIORITY.get(task.get("priority", 0), "⚫️")
    date_str = fmt_date(task)                        # "" when no date
    tags     = task.get("tags") or []

    # Core: name + priority dot + date (only when present)
    core = f"{name} {priority} {date_str}".rstrip() if date_str else f"{name} {priority}"

    # Suffix: '| breadcrumb' and/or '# tag1 tag2'
    tag_str  = "# " + " ".join(tags) if tags else ""
    if breadcrumb and tag_str:
        return f"{core} | {breadcrumb} {tag_str}"
    elif breadcrumb:
        return f"{core} | {breadcrumb}"
    elif tag_str:
        return f"{core} {tag_str}"
    return core


def build_subtitle(sub_count=0, item_type="", child_label="Subtask"):
    """
    Build the Alfred item subtitle field.

    Without item_type (regular task scripts):
      '2 Subtasks ◼️ ⏎ Open · …'   or   '⏎ Open · …'  (no ◼️ when nothing precedes it)

    With item_type (everything search):
      'Task · 2 Subtasks ◼️ ⏎ Open · …'   or   'Task ◼️ ⏎ Open · …'
    """
    if item_type:
        if sub_count:
            plural = "s" if sub_count != 1 else ""
            return f"{item_type}  {sub_count} {child_label}{plural} ◼️ {MODIFIERS}"
        return f"{item_type} ◼️ {MODIFIERS}"
    # No type prefix — standard task scripts
    if sub_count:
        plural = "s" if sub_count != 1 else ""
        return f"{sub_count} {child_label}{plural} ◼️ {MODIFIERS}"
    return MODIFIERS


def col_lookup(project_data):
    """Return a {column_id: column_name} dict from project_data."""
    columns = (project_data or {}).get("columns", []) or []
    return {c["id"]: c.get("name", "") for c in columns}


def list_name_for(list_id, projects_cache):
    """Look up a list name by ID from the projects cache list."""
    for p in (projects_cache or []):
        if p["id"] == list_id:
            return p.get("name", "")
    return ""


def join_breadcrumb(*parts):
    """Join non-empty parts with '>' — no spaces."""
    return ">".join(p for p in parts if p)


def search_key(title):
    """
    Strip non-searchable suffixes from a task title before fuzzy matching:
    - Markdown links: '[text](url)' → 'text'
    - Bare URLs
    - Tag suffix: ' # tag1 tag2…'  (added by build_title)
    """
    title = _MD_LINK_RE.sub(r'\1', title)
    title = _URL_RE.sub('', title)
    title = _TAG_SUFFIX_RE.sub('', title)
    return title.strip()
