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

# &repeat presets — token, label, hint, RRULE
REPEAT_OPTIONS = [
    ("daily",    "Daily",    "every day",                  "RRULE:FREQ=DAILY"),
    ("weekdays", "Weekdays", "Mon–Fri",                    "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
    ("weekly",   "Weekly",   "same weekday every week",    "RRULE:FREQ=WEEKLY"),
    ("monthly",  "Monthly",  "same day every month",       "RRULE:FREQ=MONTHLY"),
    ("yearly",   "Yearly",   "same date every year",       "RRULE:FREQ=YEARLY"),
]
REPEAT_RRULE = {tok: rrule for tok, _, _, rrule in REPEAT_OPTIONS}
REPEAT_LABEL = {tok: label for tok, label, _, _ in REPEAT_OPTIONS}

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
    Find the last trigger char (~, #, !, *, /, >, @) that starts a word and
    hasn't been 'closed' yet (for single-word triggers: no space after it;
    for *date: always open so user can type multi-word dates).
    ~ is special: bare ~frag is the location menu; ~p / ~l / ~s followed by
    a space stay open for the corresponding sub-picker fragment.
    Everything after the = note marker is opaque — no triggers inside a note.
    Returns (trigger, prefix_before_trigger, fragment_after_trigger) or None.
    """
    m = re.search(r'(?<!\S)=', query)
    scan = query[:m.start()] if m else query
    for i in range(len(scan) - 1, -1, -1):
        ch = scan[i]
        if ch not in ('~', '#', '!', '*', '/', '>', '@', '&'):
            continue
        # Must be at start or preceded by a space
        if i > 0 and scan[i - 1] != ' ':
            continue
        prefix   = scan[:i]
        fragment = scan[i + 1:]
        if ch == '~':
            sub = re.match(r'[pls] (.*)$', fragment)
            if sub:
                # Sub-picker mode (~p / ~l / ~s) — closed once the name is picked
                if ' ' in sub.group(1):
                    return None
                return (ch, prefix, fragment)
            # Location menu — single word filter
            if ' ' in fragment:
                return None
            return (ch, prefix, fragment)
        # Single-word triggers: if fragment contains a space the token is done
        if ch in ('#', '!', '/', '>', '&') and ' ' in fragment:
            return None
        # Date / time triggers: if fragment ends with a space the token is done
        if ch in ('*', '@') and fragment.endswith(' '):
            return None
        return (ch, prefix, fragment)
    return None

def parse_task(query):
    """Extract structured fields from the raw query string."""
    q = query

    # =note — everything after the marker to end of string (always last)
    note = None
    m = re.search(r'(?<!\S)=\s*(.*)$', q)
    if m:
        note = m.group(1).strip() or None
        q = q[:m.start()]

    # ~p parent_task (multi-word, ends at next trigger or end of string)
    parent_name = None
    m = re.search(r'(?<!\S)~p\s+(.+?)(?=\s+[~#!*@/>=&]|\s*$)', q)
    if m:
        parent_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # ~s section (multi-word)
    section_name = None
    m = re.search(r'(?<!\S)~s\s+(.+?)(?=\s+[~#!*@/>=&]|\s*$)', q)
    if m:
        section_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # ~l list (multi-word)
    list_name = None
    m = re.search(r'(?<!\S)~l\s+(.+?)(?=\s+[~#!*@/>=&]|\s*$)', q)
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
    m = re.search(r'(?<!\S)\*(.+?)(?=\s*[~#!/>@=&]|$)', q)
    if m:
        date_str = m.group(1).strip()
        q = q[:m.start()] + q[m.end():]

    # @time — HH:MM explicit time picker result
    time_str = None
    m = re.search(r'(?<!\S)@(\d{1,2}:\d{2})\b', q)
    if m:
        time_str = m.group(1).strip()
        q = q[:m.start()] + q[m.end():]

    # >end — duration end time (14 or 14:30), set via duration picker
    end_str = None
    m = re.search(r'(?<!\S)>(\d{1,2}(?::\d{2})?)(?=\s|$)', q)
    if m:
        end_str = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # &repeat — preset token (daily/weekdays/weekly/monthly/yearly)
    repeat = None
    m = re.search(r'(?<!\S)&(\S+)', q)
    if m:
        repeat = m.group(1).lower()
        q = q[:m.start()] + q[m.end():]

    title = ' '.join(q.split())
    return (title, date_str, time_str, end_str, priority, tags,
            list_name, parent_name, section_name, note, repeat)

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
# `fill` is the full query text to put before the picked name (e.g. "Task ~l ")
def list_picker(fill, fragment, lists=None):
    if lists is None:
        lists = get_lists()
    items = []
    for p in lists:
        name = p["name"]
        filled = f"{fill}{name} "
        items.append(alfred.item(
            title=name,
            subtitle="⏎ ✅",
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
            subtitle="⏎ ✅",
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
        if fragment and fragment not in label.lower() and fragment != token[1:]:
            continue
        filled = f"{prefix}{token} "
        items.append(alfred.item(
            title=label,
            subtitle="⏎ ✅",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    return items or [alfred.item(title="Type 1, 2, or 3", valid=False)]

def section_picker(fill, fragment, current_list_id=None):
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
            filled   = f"{fill}{col_name} "
            items.append(alfred.item(
                title=col_name,
                subtitle=subtitle + ("  ⏎ ✅" if subtitle else "⏎ ✅"),
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


def task_picker(fill, fragment):
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

        filled = f"{fill}{title} "
        items.append(alfred.item(
            title=title,
            subtitle=subtitle + "  ⏎ ✅" if subtitle else "⏎ ✅",
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
                subtitle=f"⏎ Set time to {label}",
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

# ── Symbol legend (contextual) ───────────────────────────────────────────────
def symbol_legend(has_date=False, has_time=False, note_mode=False):
    if note_mode:
        return "/ More…  |  ~🏠 =📝"
    syms = ["*📅"]
    if has_date:
        syms.append("@⏰")
    if has_time:
        syms.append(">⏳")
    if has_date:
        syms.append("&🔁")
    syms += ["!🚩", "#🏷️", "~🏠", "=📝"]
    return "/ More…  |  " + " ".join(syms)


# ── / master menu ─────────────────────────────────────────────────────────────
def master_menu(prefix, fragment, note_mode=False):
    """Typing / shows every add-on as a menu row. Selecting one autocompletes
    its symbol into the query — the menu doubles as a syntax reference."""
    _, date_str, time_str, end_str, _, _, _, _, _, _, repeat = parse_task(prefix)

    rows = []
    if note_mode:
        rows = [
            ("~", "🏠", "Location",  "list · section · parent"),
            ("=", "📝", "Note",      "add note text"),
        ]
    else:
        rows.append(("*", "📅", "Date", "natural language"))
        if date_str:
            rows.append(("@", "⏰", "Time", "hour, then minutes"))
        if time_str and not end_str:
            rows.append((">", "⏳", "Duration", "end time or length"))
        if date_str and not repeat:
            rows.append(("&", "🔁", "Repeat", "daily · weekly · monthly"))
        rows += [
            ("!", "🚩", "Priority",  "low · medium · high"),
            ("#", "🏷️", "Tag",       "from your tags"),
            ("~", "🏠", "Location",  "list · section · parent"),
            ("=", "📝", "Note",      "add note text"),
        ]

    items = []
    for sym, emoji, name, hint in rows:
        items.append(alfred.item(
            title=f"{emoji} {name}",
            subtitle=f"{sym}  ·  {hint}  ·  ⏎ ✅",
            arg="",
            valid=False,
            autocomplete=f"{prefix}{sym}",
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No options matching "{fragment}"', valid=False)]
    return items


# ── ~ location menu / sub-pickers ────────────────────────────────────────────
def location_router(prefix, fragment, lists=None, note_mode=False):
    """Bare ~ shows the location menu (Parent / List / Section). Picking one
    autocompletes ~p / ~l / ~s, which routes to the matching sub-picker."""
    sub = re.match(r'([pls]) (.*)$', fragment)
    if sub:
        mode, frag = sub.group(1), sub.group(2)
        fill = f"{prefix}~{mode} "
        if mode == 'p':
            return task_picker(fill, frag)
        if mode == 'l':
            return list_picker(fill, frag, lists=lists)
        # mode == 's' — use the already-chosen list to narrow sections
        ln = parse_task(prefix)[6]
        cur_lid = None
        if ln:
            source = lists if lists is not None else get_lists()
            cur_lid = resolve_list_id(ln, source)[0]
        return section_picker(fill, frag, current_list_id=cur_lid)

    rows = [
        ("l", "📋", "List",        "which list the task lives in"),
        ("s", "📑", "Section",     "kanban column inside a list"),
        ("p", "🧬", "Parent task", "make it a subtask"),
    ]
    items = []
    for letter, emoji, name, hint in rows:
        items.append(alfred.item(
            title=f"{emoji} {name}",
            subtitle=f"~{letter}  ·  {hint}  ·  ⏎ ✅",
            arg="",
            valid=False,
            autocomplete=f"{prefix}~{letter} ",
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No location matching "{fragment}"', valid=False)]
    return items


# ── > duration picker ─────────────────────────────────────────────────────────
def _normalize_end(end_str):
    """'14' → '14:00', '14:30' stays. Returns None if unparseable."""
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?$', end_str or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _duration_label(start_hm, end_hm):
    """Human duration between two HH:MM strings (end may wrap to next day)."""
    sh, sm = (int(x) for x in start_hm.split(":"))
    eh, em = (int(x) for x in end_hm.split(":"))
    mins = (eh * 60 + em) - (sh * 60 + sm)
    if mins <= 0:
        mins += 24 * 60
    h, m = divmod(mins, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def duration_picker(prefix, fragment):
    _, date_str, time_str, _, *_ = parse_task(prefix)
    if not time_str:
        return [alfred.item(
            title="Set a start time first",
            subtitle="Duration needs a time — add one with @",
            valid=False,
        )]
    sh, sm = (int(x) for x in time_str.split(":"))
    frag = fragment.strip()

    # Length syntax: 2h, 90m, 1h30 — resolves to an end time
    m = re.match(r'^(\d+)h(\d+)?m?$|^(\d+)m$', frag)
    if m:
        if m.group(3):                      # pure minutes: 90m
            mins = int(m.group(3))
        else:                               # hours (+ optional minutes)
            mins = int(m.group(1)) * 60 + int(m.group(2) or 0)
        total = sh * 60 + sm + mins
        eh, em = divmod(total % (24 * 60), 60)
        end = f"{eh:02d}:{em:02d}"
        return [alfred.item(
            title=f"{time_str} → {end}",
            subtitle=f"⏳ {_duration_label(time_str, end)}  ·  ⏎ ✅",
            arg="", valid=False,
            autocomplete=f"{prefix}>{end} ",
        )]

    items = []
    if ':' not in frag:
        # End-hour list — same day, from the start hour onward
        for h in range(sh, 24):
            hh = f"{h:02d}"
            if frag and not (hh.startswith(frag) or str(h).startswith(frag)):
                continue
            end_preview = f"{hh}:{sm:02d}"
            items.append(alfred.item(
                title=hh,
                subtitle=f"⏳ {_duration_label(time_str, end_preview)} (at :{sm:02d})  ·  ⏎ pick minutes",
                arg="", valid=False,
                autocomplete=f"{prefix}>{hh}:",
            ))
    else:
        hour_part = frag.split(':')[0]
        try:
            hh = f"{int(hour_part):02d}"
        except ValueError:
            hh = hour_part
        for mi in (0, 15, 30, 45):
            end = f"{hh}:{mi:02d}"
            items.append(alfred.item(
                title=end,
                subtitle=f"⏳ {_duration_label(time_str, end)}  ·  ⏎ End at {end}",
                arg="", valid=False,
                autocomplete=f"{prefix}>{end} ",
            ))
    if not items:
        items = [alfred.item(
            title=f'No end times matching "{frag}"',
            subtitle="Type an hour, 14:30, or a length like 2h / 90m / 1h30",
            valid=False,
        )]
    return items


# ── & repeat picker ───────────────────────────────────────────────────────────
def repeat_picker(prefix, fragment):
    date_str = parse_task(prefix)[1]
    if not date_str:
        return [alfred.item(
            title="Set a date first",
            subtitle="Repeats need an anchor date — add one with *",
            valid=False,
        )]
    items = []
    for tok, label, hint, _ in REPEAT_OPTIONS:
        items.append(alfred.item(
            title=f"🔁 {label}",
            subtitle=f"{hint}  ·  ⏎ ✅",
            arg="",
            valid=False,
            autocomplete=f"{prefix}&{tok} ",
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No repeat matching "{fragment}"', valid=False)]
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
    (title, date_str, time_str, end_str, priority, tags,
     list_name, parent_name, section_name, note, repeat) = parse_task(query)

    if not title:
        return [alfred.item(
            title="Type a task name…",
            subtitle=symbol_legend(),
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

    # >end — duration: startDate = due_date, dueDate = end of the span
    end_date = None
    end_norm = _normalize_end(end_str) if end_str else None
    if end_norm and time_str and due_date:
        end_date = parse_date(f"{date_str} {end_norm}" if date_str else f"today {end_norm}")
        if end_date and end_date <= due_date:
            # End before start → wraps past midnight to the next day
            from datetime import datetime, timedelta
            dt = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S%z") + timedelta(days=1)
            end_date = dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

    # Build subtitle summary
    parts = []
    parts.append(f"~{list_display}" if list_display else "~Inbox")
    if section_display:
        parts.append(f"§{section_display}")
    elif section_name:
        parts.append(f"§{section_name}?")
    if parent_display:
        parts.append(f"↳{parent_display}")
    elif parent_name:
        parts.append(f"↳{parent_name}?")
    if date_str or time_str:
        if due_date:
            date_display = _utc_iso_to_local_display(due_date)
        else:
            raw = combined_date_str or ""
            date_display = f"{raw}?"
        parts.append(f"*{date_display}")
    if end_date and time_str:
        parts.append(f"⏳{_duration_label(time_str, end_norm)}")
    elif end_str and not time_str:
        parts.append(f">{end_str}?")
    if repeat:
        if repeat in REPEAT_RRULE and date_str:
            parts.append(f"🔁{REPEAT_LABEL[repeat]}")
        else:
            parts.append(f"🔁{repeat}?")
    if priority:
        parts.append(f"{PRIORITY_LABEL[priority]} priority")
    for t in tags:
        parts.append(f"#{t}")
    if note:
        short = note if len(note) <= 24 else note[:24] + "…"
        parts.append(f"📝{short}")
    subtitle = ("  ".join(parts) + "  |  " if parts else "") + symbol_legend(
        has_date=bool(due_date), has_time=bool(time_str))

    payload = {"title": title, "listName": list_display}
    if list_id:
        payload["projectId"] = list_id
    if end_date and due_date:
        payload["startDate"] = due_date
        payload["dueDate"]   = end_date
    elif due_date:
        payload["dueDate"] = due_date
    if priority:
        payload["priority"] = priority
    if tags:
        payload["tags"] = tags
    if note:
        payload["content"] = note
    if repeat in REPEAT_RRULE and (due_date or end_date):
        payload["repeatFlag"] = REPEAT_RRULE[repeat]
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
    (title, _, _, _, _, _,
     list_name, parent_name, section_name, note, _) = parse_task(query)

    if not title:
        return [alfred.item(
            title="Type a note title…",
            subtitle=symbol_legend(note_mode=True),
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
        parts.append(f"§{section_display}")
    elif section_name:
        parts.append(f"§{section_name}?")
    if parent_display:
        parts.append(f"↳{parent_display}")
    elif parent_name:
        parts.append(f"↳{parent_name}?")
    if note:
        short = note if len(note) <= 24 else note[:24] + "…"
        parts.append(f"📝{short}")
    subtitle = ("  ".join(parts) + "  |  " if parts else "") + symbol_legend(note_mode=True)

    # Build payload
    payload = {"title": title, "kind": "NOTE"}
    if list_id:
        payload["projectId"] = list_id
    if note:
        payload["content"] = note
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
            subtitle="Create list  ⌘⇧ 🔙",
            valid=False,
        )]
    payload = {"name": name}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return [alfred.item(
        title=f"Create list: {name}",
        subtitle="Create  Move to a folder in TickTick afterwards  ⌘⇧ 🔙",
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
            subtitle="Creates 💼P • list + PM meta task  ⌘⇧ 🔙",
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
                    items = location_router(prefix, fragment, lists=all_lists, note_mode=True)
                elif ch == '/':
                    items = master_menu(prefix, fragment, note_mode=True)
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
                items = location_router(prefix, fragment)
            elif ch == '#':
                items = tag_picker(prefix, fragment)
            elif ch == '!':
                items = priority_picker(prefix, fragment)
            elif ch == '*':
                items = date_picker(prefix, fragment)
            elif ch == '@':
                items = time_picker(prefix, fragment)
            elif ch == '>':
                items = duration_picker(prefix, fragment)
            elif ch == '&':
                items = repeat_picker(prefix, fragment)
            elif ch == '/':
                items = master_menu(prefix, fragment)
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
