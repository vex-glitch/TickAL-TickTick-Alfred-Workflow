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

# ── Modifier vocabulary ───────────────────────────────────────────────────────
# Single source of truth for the emoji hints shown in item subtitles.
# key+emoji pairs; each item type advertises only the actions it actually wires.
MOD_OPEN   = "⏎↗️"      # open in TickTick
MOD_ADD    = "⌘➕"      # add task / subtask
MOD_DONE   = "⇧✔️"      # complete
MOD_UNDONE = "⇧↩️"      # uncomplete
MOD_BROWSE = "⌥⤵️"      # drill into children (Alfred)
MOD_URL    = "⌥⌘🔗"     # copy link
MOD_MODIFY = "⌃ℹ️"      # task details (schedule, move, tags, priority, rename, delete)
MOD_BACK   = "⌘⇧🔙"     # go back

# Per-type ordered modifier templates. MOD_BROWSE is conditional — it's
# dropped when the item has no children (nothing to drill into).
_MOD_TEMPLATES = {
    "task":      [MOD_OPEN, MOD_ADD, MOD_DONE, MOD_BROWSE, MOD_URL, MOD_MODIFY, MOD_BACK],
    "list":      [MOD_OPEN, MOD_ADD, MOD_BROWSE, MOD_URL, MOD_BACK],
    "section":   [MOD_OPEN, MOD_ADD, MOD_BROWSE, MOD_URL, MOD_BACK],
    "note":      [MOD_OPEN, MOD_MODIFY, MOD_URL, MOD_BACK],
    "completed": [MOD_OPEN, MOD_UNDONE, MOD_BACK],
}


def mods_for(kind="task", has_children=True):
    """Build the modifier hint line for an item kind, omitting the Browse
    (⤵️) hint when has_children is False — a drill with no destination."""
    parts = _MOD_TEMPLATES.get(kind, _MOD_TEMPLATES["task"])
    if not has_children:
        parts = [p for p in parts if p != MOD_BROWSE]
    return "  ".join(parts)


# Static "has children" lines (used where children always exist or count is unknown)
MODS_TASK      = mods_for("task")
MODS_LIST      = mods_for("list")
MODS_SECTION   = mods_for("section")
MODS_NOTE      = mods_for("note")
MODS_COMPLETED = mods_for("completed")

# Map everything-search type prefixes → their kind
_KIND_BY_TYPE = {"Task": "task", "List": "list", "Sect": "section", "Note": "note"}

# Back-compat alias (task line is the default)
MODIFIERS = MODS_TASK


def _utc_to_local(iso_str):
    """Parse a UTC ISO string → local datetime, or None."""
    try:
        c = iso_str[:19]
        return datetime(
            int(c[0:4]), int(c[5:7]), int(c[8:10]),
            int(c[11:13]), int(c[14:16]), int(c[17:19]),
            tzinfo=timezone.utc,
        ).astimezone()
    except Exception:
        return None


def fmt_date(task):
    """
    Return '📆 DD/MM/YYYY HH:MM' or '' if no date is set.

    When the task spans a duration (startDate < dueDate, both timed) the range
    is shown:  '📆 18/06/2026 08:00-17:00'  (same day)  or
               '📆 18/06/2026 08:00 → 19/06 02:00'  (crosses midnight).
    Uses startDate preferentially (TickTick displays startDate in the UI).
    Time is shown only when the UTC time has non-zero hours/minutes
    (all-day tasks are stored as T00:00:00Z by the TickTick API).
    """
    start = task.get("startDate") or ""
    due   = task.get("dueDate") or ""
    anchor = start or due
    if not anchor:
        return ""
    ls = _utc_to_local(anchor)
    if ls is None:
        return ""

    all_day = bool(task.get("isAllDay", False))

    def timed(iso):
        # All-day tasks are stored as UTC midnight (T00:00:00Z); a non-zero
        # UTC time means a real clock time was set.
        c = iso[:19]
        return (not all_day) and (int(c[11:13]) != 0 or int(c[14:16]) != 0)

    result = ls.strftime("%d/%m/%Y")
    start_timed = timed(anchor)

    # Span = distinct start and end timestamps
    has_span = bool(start and due and due[:19] != start[:19])
    le = _utc_to_local(due) if has_span else None
    end_timed = bool(le) and timed(due)

    if has_span and (start_timed or end_timed):
        if ls.date() == le.date():
            result += ls.strftime(" %H:%M") + le.strftime("-%H:%M")
        else:
            result += ls.strftime(" %H:%M") + " → " + le.strftime("%d/%m %H:%M")
    elif start_timed:
        result += ls.strftime(" %H:%M")
    return f"📆 {result}"


_TAG_LABELS = None

def _tag_label(tag):
    """Map a task's stored tag (lowercase, e.g. '🔥active') to its properly
    cased label from the tags cache ('🔥Active'). Falls back to the raw tag."""
    global _TAG_LABELS
    if _TAG_LABELS is None:
        _TAG_LABELS = {}
        try:
            import cache as cache_store
            for lbl in (cache_store.get("tags") or []):
                _TAG_LABELS[lbl.lower()] = lbl
        except Exception:
            pass
    return _TAG_LABELS.get(tag.lower(), tag)


def fmt_tags(tags):
    """Render tags as '#🔥Active #🔥Lead' — no space after #, proper case."""
    return " ".join(f"#{_tag_label(t)}" for t in (tags or []))


def build_title(task):
    """
    Build the Alfred item title field (the breadcrumb now lives in the subtitle).
    Format: 'Task Name ⚫️ 📆 13/05/2026 08:00-17:00 #🔥Active #🔥Lead'
             'Task Name ⚫️ #🔥Active'                  (no date)
             'Task Name ⚫️'                            (no date, no tags)
    """
    name     = task.get("title", "Untitled")
    priority = PRIORITY.get(task.get("priority", 0), "⚫️")
    date_str = fmt_date(task)                        # "" when no date
    tag_str  = fmt_tags(task.get("tags"))

    core = f"{name} {priority} {date_str}".rstrip() if date_str else f"{name} {priority}"
    return f"{core} {tag_str}" if tag_str else core


def build_subtitle(sub_count=0, item_type="", child_label="Subtask", breadcrumb=""):
    """
    Build the Alfred item subtitle field:
      '[Type  ][N Children  ]<modifiers>  |  <breadcrumb>'

    Each item type shows only the modifier actions it actually wires; the
    Browse hint is dropped when there are no children to drill into. The
    breadcrumb (List>Section>…) lives here so the title row stays uncluttered.

      '9 Subtasks  ⏎↗️  ⌘➕  …  ⌘⇧🔙  |  💼P • Onboard 4️⃣>Not Sectioned'
      'List  ⏎↗️  ⌘➕  ⌥⤵️  ⌥⌘🔗  ⌘⇧🔙'
    """
    kind = _KIND_BY_TYPE.get(item_type, "task")
    mods = mods_for(kind, has_children=bool(sub_count))

    prefix = ""
    if item_type:
        if sub_count:
            plural = "s" if sub_count != 1 else ""
            prefix = f"{item_type}  {sub_count} {child_label}{plural}  "
        else:
            prefix = f"{item_type}  "
    elif sub_count:
        plural = "s" if sub_count != 1 else ""
        prefix = f"{sub_count} {child_label}{plural}  "

    line = f"{prefix}{mods}"
    if breadcrumb:
        line += f"  |  {breadcrumb}"
    return line


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
