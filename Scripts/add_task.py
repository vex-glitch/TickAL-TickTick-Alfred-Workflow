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

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
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
    from reminders import (PRESETS as REMINDER_OPTIONS,
                           trigger as _reminder_trigger,
                           human   as _reminder_human)
    import clipboard as clip_util
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Constants ────────────────────────────────────────────────────────────────
PRIORITY_OPTIONS = [
    ("!1", "🟡 Low priority",    1),
    ("!2", "🟠 Medium priority", 3),
    ("!3", "🔴 High priority",   5),
]
PRIORITY_VAL = {"1": 1, "2": 3, "3": 5}
PRIORITY_LABEL = {1: "🟡", 3: "🟠", 5: "🔴"}

# 🔥CRM — the bookings list. Adds targeting it auto-attach a clipboard image
# (except 🔥prepare follow-ups) and scope the [[ task-link picker to CRM bookings.
import areas as _areas
CRM_ID = _areas.CRM_ID   # Configure panel; empty = CRM scoping never triggers
PREPARE_TAG = "🔥prepare"

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
    # [[ task-link picker — active while an unclosed [[ is being typed (no ]] after
    # the last [[). Takes priority since the user is mid-link; closes once ]] lands.
    idx = scan.rfind('[[')
    if idx != -1 and ']]' not in scan[idx + 2:]:
        return ('[[', scan[:idx], scan[idx + 2:])
    for i in range(len(scan) - 1, -1, -1):
        ch = scan[i]
        if ch not in ('~', '#', '!', '*', '/', '>', '@', '&', '%'):
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
        if ch in ('#', '!', '/', '>', '&', '%') and ' ' in fragment:
            return None
        # Date / time triggers: if fragment ends with a space the token is done
        if ch in ('*', '@') and fragment.endswith(' '):
            return None
        return (ch, prefix, fragment)
    return None

def parse_task(query):
    """Extract structured fields from the raw query string."""
    q = query

    # =note — everything after the marker to end of string (always last).
    # re.S: a pasted note may contain newlines (⌘V of multi-line text) — without
    # it the match dies on the first \n and the whole bar becomes the title.
    note = None
    m = re.search(r'(?<!\S)=\s*(.*)$', q, re.S)
    if m:
        note = m.group(1).strip() or None
        q = q[:m.start()]

    # ^attach-image flag — a standalone marker (no value) set by the / menu's
    # "Add image" row; on create, dispatch uploads the clipboard image to the
    # new task. Stripped from the pre-note text only (a literal ^ inside a =note
    # stays put). All occurrences are removed so re-selecting can't leave a stray.
    new_q, n_attach = re.subn(r'(?<!\S)\^ ?', '', q)
    attach_image = n_attach > 0
    q = new_q

    # +stage / +focus — standalone post-create markers set by the / menu
    # (R4.2): dispatch stages the new task / adds it to the running focus
    # session right after the create lands. Stripped like ^ above.
    # (?=\s|$) not \b — \b matches before punctuation and would strip a
    # legitimate "+stage:" / "+stage-two" out of a title
    new_q, n_stage = re.subn(r'(?<!\S)\+stage(?=\s|$) ?', '', q)
    q = new_q
    new_q, n_fx = re.subn(r'(?<!\S)\+focus(?=\s|$) ?', '', q)
    post_stage, post_focus = n_stage > 0, n_fx > 0
    q = new_q

    # ~p parent_task (multi-word, ends at next trigger or end of string)
    parent_name = None
    m = re.search(r'(?<!\S)~p\s+(.+?)(?=\s+[~#!*@/>=&%]|\s*$)', q)
    if m:
        parent_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # ~s section (multi-word)
    section_name = None
    m = re.search(r'(?<!\S)~s\s+(.+?)(?=\s+[~#!*@/>=&%]|\s*$)', q)
    if m:
        section_name = m.group(1)
        q = q[:m.start()] + q[m.end():]

    # ~l list (multi-word). The capture runs to the next trigger char or end of
    # string — so when the TITLE follows the list name ("#tag ~l 🔥CRM buy milk",
    # tokens-first order) it swallows the title too (the historic "~l trap").
    # Trim the span word-by-word until it resolves to a real list; whatever is
    # left goes back to the title.
    list_name = None
    m = re.search(r'(?<!\S)~l\s+(.+?)(?=\s+[~#!*@/>=&%]|\s*$)', q)
    if m:
        span, leftover = m.group(1), ""
        try:
            lists = get_lists()
        except Exception:
            lists = []
        if lists and resolve_list_id(span, lists)[0] is None:
            words = span.split(" ")
            for cut in range(len(words) - 1, 0, -1):
                cand = " ".join(words[:cut])
                if resolve_list_id(cand, lists)[0] is not None:
                    span, leftover = cand, " ".join(words[cut:])
                    break
        list_name = span
        q = q[:m.start()] + (leftover + " " if leftover else "") + q[m.end():]

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
    m = re.search(r'(?<!\S)\*(.+?)(?=\s*[~#!/>@=&%]|$)', q)
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

    # %reminder — preset/offset tokens (multiple allowed); resolved to TRIGGER later
    reminders = []
    while True:
        m = re.search(r'(?<!\S)%(\S+)', q)
        if not m:
            break
        reminders.append(m.group(1).lower())
        q = q[:m.start()] + q[m.end():]

    title = ' '.join(q.split())
    return (title, date_str, time_str, end_str, priority, tags,
            list_name, parent_name, section_name, note, repeat, reminders,
            attach_image, post_stage, post_focus)

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


def resolve_wikilinks(text, prefer_pid=None):
    """Replace [[Task Name]] with a TickTick task-link, matching how the app stores
    native links: [Title](https://ticktick.com/webapp/#p/<pid>/tasks/<tid>). The
    name is resolved against cached tasks/notes by exact (case-insensitive) title;
    ties prefer the current list, then the most-recent (ids are time-ordered).
    Unresolved names are left as literal [[Name]] rather than breaking the title."""
    if "[[" not in text:
        return text
    pool = (cache_store.get("all_tasks") or []) + (cache_store.get("all_notes") or [])

    def _sub(m):
        name = m.group(1).strip()
        hits = [t for t in pool if (t.get("title") or "").strip().lower() == name.lower()]
        if not hits:
            return m.group(0)
        hits.sort(key=lambda t: (
            (t.get("_projectId") or t.get("projectId")) == prefer_pid,
            t.get("status", 0) == 0,
            t.get("id", ""),
        ), reverse=True)
        t   = hits[0]
        pid = t.get("_projectId") or t.get("projectId") or ""
        tid = t.get("id", "")
        return f"[{t.get('title') or name}](https://ticktick.com/webapp/#p/{pid}/tasks/{tid})"

    return re.sub(r'\[\[(.+?)\]\]', _sub, text)

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
            subtitle="",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No lists matching "{fragment}"', valid=False)]
    return items


# 🔥CRM tag group — a CRM add's # picker offers only the booking tags
CRM_TAGS = {"🔥lead", "🔥consultation", "🔥ongoing", "🔥tattoo", "🔥prepare"}

def tag_picker(prefix, fragment):
    import tagtree
    from display import tag_match_key
    tags = get_tags()
    crm_scoped = (bool(CRM_ID) and os.environ.get("list_id", "") == CRM_ID) \
        or "🔥CRM" in prefix

    # '#name>pfrag' — parent step of ➕ new tag (R4.3): pick which existing
    # tag the new one nests under; the token '#name>parent' rides the query
    # and task_preview splits it into payload tags + _tag_parents. Never on
    # a locked CRM picker — its tag family is fixed.
    if ">" in fragment and not crm_scoped:
        base, _, pfrag = fragment.partition(">")
        base = (base.strip().lstrip("#")
                .replace(",", "").replace(":", "").replace(">", ""))
        if not base:
            return [alfred.item(title="Type the new tag's name before >",
                                valid=False)]
        rows = [alfred.item(
            title=f"#{base} under {t}",
            subtitle="Nest under parent",
            arg="", valid=False,
            autocomplete=f"{prefix}#{base}>{t} ",
        ) for t in tagtree.top_level_labels(tags)
            if tag_match_key(t) != tag_match_key(base)]
        if pfrag.strip():
            rows = fuzz.filter_and_score(pfrag.strip(), rows,
                                         key_fn=lambda x: x["title"])
        return rows or [alfred.item(
            title=f'No parent matching "{pfrag.strip()}"', valid=False)]
    # CRM adds (env list from the CRM window, or a typed ~l 🔥CRM) scope the
    # picker to the CRM tag group — nothing else belongs on a booking.
    if crm_scoped:
        crm_lc = {c.lower() for c in CRM_TAGS}
        scoped = [t for t in tags if t.lower() in crm_lc]
        tags = scoped or tags
    else:
        # Parent drill (Run 3.5): an exact parent fragment lists its children;
        # parents also appear as drill rows (they're never committed to tasks).
        kids = tagtree.children_of(fragment) if fragment else []
        if kids:
            tags, fragment = kids, ""
        else:
            known = {t.lower() for t in tags}
            tags = tags + [p for p in tagtree.parent_labels()
                           if p.lower() not in known]
    items = []
    for tag in tags:
        if not crm_scoped and tagtree.is_parent(tag):
            # no trailing space → stays the fragment → next render shows children
            filled, sub = f"{prefix}#{tag.lower()}", "Show child tags"
        else:
            filled, sub = f"{prefix}#{tag} ", ""
        items.append(alfred.item(
            title=tag,
            subtitle=sub,
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
        # ➕ new tag (R4.2/R4.3): no match → two rows, like scheduling — plain,
        # or pick a parent first. Matching is emoji-stripped (typing CRM must
        # count as existing when 🔥CRM does). Created at save time (v2).
        frag_tag = (fragment.strip().lstrip("#")
                    .replace(",", "").replace(":", "").replace(">", ""))
        if (frag_tag and not crm_scoped
                and tag_match_key(frag_tag) not in {tag_match_key(t) for t in tags}):
            items.append(alfred.item(
                title=f"➕ #{frag_tag}",
                subtitle="Add new tag",
                arg="", valid=False,
                autocomplete=f"{prefix}#{frag_tag} ",
            ))
            items.append(alfred.item(
                title=f"➕ #{frag_tag} → parent…",
                subtitle="Add tag + nest under parent",
                arg="", valid=False,
                autocomplete=f"{prefix}#{frag_tag}>",
            ))
    if not tags and not fragment:
        items = [alfred.item(title="No tags cached — run Sync first", valid=False)]
    elif not items:
        items = [alfred.item(title=f'No tags matching "{fragment}"', valid=False)]
    return items

def priority_picker(prefix, fragment):
    task_title = parse_task(prefix)[0] or "task"
    items = []
    for token, label, val in PRIORITY_OPTIONS:
        if fragment and fragment not in label.lower() and fragment != token[1:]:
            continue
        filled = f"{prefix}{token} "
        items.append(alfred.item(
            title=label,
            subtitle=f"{PRIORITY_LABEL[val]} {task_title}",
            arg="",
            valid=False,
            autocomplete=filled,
        ))
    return items or [alfred.item(title=f'No priority matching "{fragment}"', valid=False)]

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
                subtitle=subtitle,
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
            subtitle     = f"↳ {parent_title}>{list_name}" if parent_title else list_name
        else:
            subtitle = list_name or ""

        filled = f"{fill}{title} "
        items.append(alfred.item(
            title=title,
            subtitle=subtitle,
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


def link_picker(prefix, fragment, scope_list_id=None):
    """[[ task-link picker. Selecting a task inserts the readable wiki form
    [[Title]] (resolved to a real TickTick link on create). In a CRM add it scopes
    to CRM bookings (excludes 🔥prepare follow-ups); else spans all tasks + notes."""
    all_tasks = cache_store.get("all_tasks") or []
    task_map  = {t["id"]: t for t in all_tasks}
    # Truthiness guard: CRM unconfigured (CRM_ID "") + scope-less picker must
    # span everything, not collapse to (empty) CRM bookings.
    crm = bool(CRM_ID) and scope_list_id == CRM_ID
    if crm:
        candidates = [t for t in all_tasks
                      if t.get("_projectId") == CRM_ID and t.get("status", 0) == 0
                      and PREPARE_TAG not in (t.get("tags") or [])]
    else:
        candidates = [t for t in all_tasks if t.get("status", 0) == 0]
        candidates += list(cache_store.get("all_notes") or [])

    items, seen = [], set()
    for t in candidates:
        tid = t.get("id")
        if tid in seen:
            continue
        seen.add(tid)
        title     = t.get("title", "Untitled")
        list_name = t.get("_projectName", "")
        parent_id = t.get("parentId", "")
        if parent_id:
            parent   = task_map.get(parent_id)
            ptitle   = parent.get("title", "") if parent else ""
            crumb    = f"↳ {ptitle}>{list_name}" if ptitle else list_name
        else:
            crumb = list_name or ""
        items.append(alfred.item(
            title=title,
            subtitle=f"🔗 {crumb}" if crumb else "🔗 Link task",
            arg="", valid=False,
            autocomplete=f"{prefix}[[{title}]] ",
        ))

    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        what = "CRM bookings" if crm else "tasks"
        msg = (f'No {what} matching "{fragment}"' if fragment
               else f"No {what} cached — run Sync first")
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
            subtitle=display,
            arg="", valid=False, autocomplete=filled,
        ))

    if not items:
        items = [alfred.item(
            title=f'Can\'t parse "{fragment}" as a date' if fragment else "Type a date or phrase",
            subtitle="tomorrow  21/07  next monday  in 3 days",
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
                subtitle=f"{ampm}  Pick minutes",
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
                subtitle="Set time",
                arg="",
                valid=False,
                autocomplete=filled,
            ))
    if not items:
        items = [alfred.item(
            title=f'No hours matching "{fragment}"',
            subtitle="Type 0–23",
            valid=False,
        )]
    return items

# ── Symbol legend (contextual) ───────────────────────────────────────────────
def symbol_legend(has_date=False, note_mode=False):
    if note_mode:
        syms = ["*📅"]
        if has_date:
            syms += ["&🔁", "%🔔"]
        syms += ["#🏷️", "~🏠", "=📝"]
        return "/ More…  " + " ".join(syms)
    syms = ["*📅"]
    # @ time and > duration are offered as selectable rows once a date/time is
    # set (see task_preview), so they're intentionally left out of the legend.
    if has_date:
        syms.append("&🔁")
        syms.append("%🔔")
    syms += ["!🚩", "#🏷️", "~🏠", "=📝"]
    return "/ More…  " + " ".join(syms)


# ── Container context (Add invoked on a specific list/section/task) ───────────
def _adding_to_container():
    """True when Add was invoked on a specific item via ⌘ Actions — the item's
    type rides in as item_type (the master add keyword never sets it). Then we're
    adding INTO that list/section/task, not choosing what to create at top level."""
    return bool(os.environ.get("item_type", "").strip())


def _list_display_name(lid):
    if not lid:
        return ""
    for p in (cache_store.get("projects") or []):
        if p.get("id") == lid:
            return p.get("name", "") or ""
    return ""


def _add_target_label():
    """Short 'where it lands' subtitle when adding into a container, else None."""
    itype = os.environ.get("item_type", "").strip()
    if not itype:
        return None
    tid   = os.environ.get("task_id", "")
    sid   = os.environ.get("section_id", "")
    lid   = os.environ.get("list_id") or os.environ.get("task_list_id", "")
    title = os.environ.get("task_title", "").strip()
    if itype in ("task", "subtask") and tid:
        return f"↳ Subtask of “{title}”" if title else "↳ Subtask"
    if itype == "section" and sid:
        sname = ""
        pdata = cache_store.get(f"project_data_{lid}") if lid else None
        for col in (pdata or {}).get("columns", []) or []:
            if col.get("id") == sid:
                sname = (col.get("name") or "").strip()
                break
        lname = _list_display_name(lid)
        tail  = f">{lname}" if lname else ""
        return (f"Adding to §{sname}{tail}" if sname else f"Adding to section{tail}")
    lname = _list_display_name(lid)
    return f"Adding to {lname}" if lname else "Adding to this list"


# ── / master menu ─────────────────────────────────────────────────────────────
def mode_menu(fragment):
    """Typing / on an empty field: choose what to create. Each row
    autocompletes its prefix; the letter shortcut is shown too."""
    rows = [
        ("",   "✅", "Task",    "Type name"),
        ("L ", "📋", "List",    "New list"),
        ("N ", "📝", "Note",    "New note"),
        ("P ", "💼", "Project", "list + meta task"),
        ("T ", "🏷️", "Tag",     "a new tag"),
    ]
    items = []
    for ac, emoji, name, hint in rows:
        items.append(alfred.item(
            title=f"{emoji} {name}", subtitle=hint,
            arg="", valid=False, autocomplete=ac,
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    return items or [alfred.item(title=f'No options matching "{fragment}"', valid=False)]


def _fx_running():
    """True when a task-bound focus session runs (timer file, or pomo sidecar
    validated against the app's LIVE pomo state — a stale sidecar file must
    not fake a session). Gates the / menu's post-create 'Add to focus' row."""
    try:
        import xact
        if xact._current_focus_task():
            return True
        # _pomo_sidecar self-validates against the app's live pomo state and
        # drops the file when idle — no extra probe needed
        ps = xact._pomo_sidecar()
        return bool(ps and ps.get("tid"))
    except Exception:
        return False


def _fx_probe():
    """Cheap per-keystroke session probe for the preview chords (R4.4 fleet):
    _fx_running()'s pomo self-validation shells out to `defaults` (~150 ms) —
    too hot for a path that re-renders on every character. Timer file first,
    then the RAW sidecar file. A stale sidecar only mislabels the ⌘ chord;
    dispatch's fx_add no-session guard stays honest at ⏎ time."""
    try:
        import xact
        st = xact._focus_state()
        if st and st.get("tid"):
            return True
        with open(xact.POMO_FILE) as f:
            return bool(json.load(f).get("tid"))
    except Exception:
        return False


def master_menu(prefix, fragment, note_mode=False):
    """Typing / shows every add-on as a menu row. Selecting one autocompletes
    its symbol into the query — the menu doubles as a syntax reference. With no
    task name yet (and not in note mode) it instead offers the creation modes."""
    if not note_mode and not prefix.strip() and not _adding_to_container():
        return mode_menu(fragment)

    _, date_str, time_str, end_str, _, _, _, _, _, _, repeat, *_ = parse_task(prefix)

    rows = []
    if note_mode:
        rows.append(("*", "📅", "Date", "natural language"))
        if not date_str:
            # R5a-R2 (Vex): one-pick today/tomorrow — plain *date shortcuts,
            # the 💫 daily note pulls them in on its next refresh
            rows.append(("*today ", "☀️", "Today", "due today"))
            rows.append(("*tomorrow ", "🌙", "Tomorrow", "due tomorrow"))
        if date_str:
            rows.append(("@", "⏰", "Time", "hour, then minutes"))
        if time_str and not end_str:
            rows.append((">", "⏳", "Duration", "end time or length"))
        if date_str and not repeat:
            rows.append(("&", "🔁", "Repeat", "daily  weekly  monthly"))
        if date_str:
            rows.append(("%", "🔔", "Reminder", "at time  before due"))
        rows += [
            ("#", "🏷️", "Tag",       "from your tags"),
            ("~", "🏠", "Location",  "list  section  parent"),
            ("=", "📝", "Note",      "add note text"),
        ]
    else:
        rows.append(("*", "📅", "Date", "natural language"))
        if not date_str:
            rows.append(("*today ", "☀️", "Today", "due today"))
            rows.append(("*tomorrow ", "🌙", "Tomorrow", "due tomorrow"))
        if date_str:
            rows.append(("@", "⏰", "Time", "hour, then minutes"))
        if time_str and not end_str:
            rows.append((">", "⏳", "Duration", "end time or length"))
        if date_str and not repeat:
            rows.append(("&", "🔁", "Repeat", "daily  weekly  monthly"))
        if date_str:
            rows.append(("%", "🔔", "Reminder", "at time  before due"))
        rows += [
            ("!", "🚩", "Priority",  "low  medium  high"),
            ("#", "🏷️", "Tag",       "from your tags"),
            ("~", "🏠", "Location",  "list  section  parent"),
            ("=", "📝", "Note",      "add note text"),
            ("^", "🖼️", "Add image", "Add screenshot from clipboard"),
            ("+stage ", "🎯", "Stage for Focus", "Stage after create"),
        ]
        if _fx_running():
            rows.append(("+focus ", "➕", "Add to focus",
                         "Add to running focus"))

    items = []
    for sym, emoji, name, hint in rows:
        items.append(alfred.item(
            title=f"{emoji} {name}",
            subtitle=hint,
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
    """Bare ~ shows the location menu (List / Section / Parent task). Picking one
    autocompletes ~l / ~s / ~p and drills into its sub-picker. Typing with no
    scope letter defaults to list-filtering (same UX as the Move picker)."""
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

    stripped = fragment.strip()

    # Typing with no scope letter → default to list, filter lists by fragment
    # (same UX as the Move picker)
    if stripped:
        return list_picker(f"{prefix}~l ", stripped, lists=lists)

    # Idle (bare ~) → the location menu (all options visible)
    rows = [
        ("l", "📋", "List",        "Add to list"),
        ("s", "📑", "Section",     "Add to section"),
        ("p", "🧬", "Parent task", "Make subtask"),
    ]
    items = []
    for letter, emoji, name, hint in rows:
        items.append(alfred.item(
            title=f"{emoji} {name}",
            subtitle=hint,
            arg="",
            valid=False,
            autocomplete=f"{prefix}~{letter} ",
        ))
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
            subtitle="Add time with @",
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
            subtitle=f"⏳ {_duration_label(time_str, end)}",
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
                subtitle=f"⏳ {_duration_label(time_str, end_preview)} at :{sm:02d}  Pick minutes",
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
                subtitle=f"⏳ {_duration_label(time_str, end)}",
                arg="", valid=False,
                autocomplete=f"{prefix}>{end} ",
            ))
    if not items:
        items = [alfred.item(
            title=f'No end times matching "{frag}"',
            subtitle="Hour, 14:30, or 2h / 90m / 1h30",
            valid=False,
        )]
    return items


# ── & repeat picker ───────────────────────────────────────────────────────────
def repeat_picker(prefix, fragment):
    date_str = parse_task(prefix)[1]
    if not date_str:
        return [alfred.item(
            title="Set a date first",
            subtitle="Add date with *",
            valid=False,
        )]
    items = []
    for tok, label, hint, _ in REPEAT_OPTIONS:
        items.append(alfred.item(
            title=f"🔁 {label}",
            subtitle=hint,
            arg="",
            valid=False,
            autocomplete=f"{prefix}&{tok} ",
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(title=f'No repeat matching "{fragment}"', valid=False)]
    return items


def reminder_picker(prefix, fragment):
    date_str = parse_task(prefix)[1]
    if not date_str:
        return [alfred.item(
            title="Set a date first",
            subtitle="Add date with *",
            valid=False,
        )]
    frag = fragment.strip().lower()

    # Any typed token that resolves to a trigger → one direct row (covers free-typed
    # offsets like 45m/2h AND preset tokens like 2d/7d/7am whose labels — "Two days
    # before", "Week before", "Day of · 7am" — don't contain the token to fuzzy on).
    if frag and _reminder_trigger(frag):
        return [alfred.item(
            title=f"🔔 {_reminder_human(frag)}",
            subtitle="reminder offset",
            arg="", valid=False,
            autocomplete=f"{prefix}%{frag} ",
        )]

    items = []
    for tok, label, hint in REMINDER_OPTIONS:
        items.append(alfred.item(
            title=f"🔔 {label}",
            subtitle=hint,
            arg="", valid=False,
            autocomplete=f"{prefix}%{tok} ",
            match=f"{tok} {label}",
        ))
    if fragment:
        items = fuzz.filter_and_score(fragment, items, key_fn=lambda x: x.get("match", x["title"]))
    if not items:
        items = [alfred.item(title=f'No reminder matching "{fragment}"', valid=False)]
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


def _split_tag_parents(tags):
    """'name>parent' picker tokens → (clean names, {name_lower: parent}) —
    the ➕ new-tag parent step rides the query as one token (R4.3)."""
    names, parents = [], {}
    for t in (tags or []):
        name, _, par = str(t).partition(">")
        name = name.strip()
        if not name:
            continue
        names.append(name)
        if par.strip():
            parents[name.lower()] = par.strip()
    return names, parents


# ── Task preview ──────────────────────────────────────────────────────────────
def task_preview(query):
    (title, date_str, time_str, end_str, priority, tags,
     list_name, parent_name, section_name, note, repeat, reminders,
     attach_image, post_stage, post_focus) = parse_task(query)

    # A link grabbed by the URL hotkey rides along as a session variable so the
    # add window opens "as usual" (empty title to type) with the URL already in
    # the description. A typed =note stays on top; the link is appended below it.
    pre = os.environ.get("prefill_note", "").strip()
    eff_note = (f"{note}\n\n{pre}" if note and pre else (note or pre or None))

    # A tag pre-applied by the CRM tag-drill (⌘ add-with-tag) rides in like the
    # note prefill; merge it into the parsed tags so the chip + payload include it.
    # Split BEFORE the prefill merge — dedup must compare clean names, not
    # raw 'name>parent' tokens (fleet catch R4.3).
    tags, tag_parents = _split_tag_parents(tags)
    pre_tag = os.environ.get("prefill_tag", "").strip()
    if pre_tag and pre_tag.lower() not in {t.lower() for t in tags}:
        tags = tags + [pre_tag]

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

    # CRM bookings auto-attach the clipboard image (the reference-image step) — but
    # never the 🔥prepare follow-up. Manual ^ / 🖼️ Add image still works elsewhere.
    if (list_id == CRM_ID and PREPARE_TAG not in {t.lower() for t in tags}
            and not attach_image and clip_util.has_image()):
        attach_image = True

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
    for rem in reminders:
        ok = _reminder_trigger(rem) and (due_date or end_date)
        parts.append(f"🔔{rem}" if ok else f"🔔{rem}?")
    if priority:
        parts.append(f"{PRIORITY_LABEL[priority]} priority")
    for t in tags:
        parts.append(f"#{t}" + (f"↳{tag_parents[t.lower()]}"
                                if t.lower() in tag_parents else ""))
    if note:
        short = note if len(note) <= 24 else note[:24] + "…"
        parts.append(f"📝{short}")
    if pre:
        parts.append("🔗 link")
    if attach_image:
        parts.append("🖼️ image")
    if post_stage:
        parts.append("🎯 stage after")
    if post_focus:
        parts.append("➕ to focus after")
    if "[[" in title:
        parts.append("🔗 linked")
    # A CRM booking's post-create slot belongs to the Prepare window
    # (dispatch's _crm_chained wins) — advertising the focus chords there
    # would promise a step that gets silently dropped (R4.4 fleet).
    _crm_book = bool(CRM_ID and list_id == CRM_ID
                     and {t.lower() for t in tags} & _areas.BOOKING_TAGS)
    _hint = "" if _crm_book else "⌘🎯 ⇧⌘📍  |  "
    subtitle = (("  ".join(parts) + "  |  " if parts else "")
                + _hint + symbol_legend(has_date=bool(due_date)))

    # [[Name]] in the title resolves to a real TickTick task link for the payload
    # (prefer the current list when names collide); the "Create:" row below keeps
    # the readable [[Name]] form.
    payload = {"title": resolve_wikilinks(title, prefer_pid=list_id), "listName": list_display}
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
        if tag_parents:
            payload["_tag_parents"] = tag_parents
    if eff_note:
        payload["content"] = eff_note
    if attach_image:
        payload["_attach_image"] = True
    if post_stage:
        payload["_post_stage"] = True
    if post_focus:
        payload["_post_fx"] = True
    if repeat in REPEAT_RRULE and (due_date or end_date):
        payload["repeatFlag"] = REPEAT_RRULE[repeat]
    if reminders and (due_date or end_date):
        seen = set()
        triggers = []
        for rem in reminders:
            trig = _reminder_trigger(rem)
            if trig and trig not in seen:
                seen.add(trig)
                triggers.append(trig)
        if triggers:
            payload["reminders"] = triggers
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

    # R4.4 focus chords on the preview row: ⌘ chains the new task into the
    # focus world — running session → fx_add, idle → the ⏱/🍅 start flow —
    # and ⇧⌘ stages it. Each chord rides its own payload copy; the typed
    # +stage/+focus markers stay untouched on plain ⏎. Bookings get honest
    # disabled chords instead (the Prepare chain owns the post-create slot).
    if _crm_book:
        _book_sub = "🔥 Booking  |  Prepare next"
        chord_mods = {"cmd": {"valid": False, "subtitle": _book_sub},
                      "cmd+shift": {"valid": False, "subtitle": _book_sub}}
    else:
        p_cmd = dict(payload)
        p_cmd.pop("_post_stage", None)
        if _fx_probe():
            p_cmd["_post_fx"] = True
            cmd_sub = "🎯 Add to running focus"
        else:
            p_cmd.pop("_post_fx", None)
            p_cmd["_post_fstart"] = True
            cmd_sub = "🎯 Start Focus"
        p_stage = dict(payload)
        p_stage.pop("_post_fx", None)
        p_stage.pop("_post_fstart", None)
        p_stage["_post_stage"] = True
        enc_cmd = base64.b64encode(json.dumps(p_cmd).encode()).decode()
        enc_stage = base64.b64encode(json.dumps(p_stage).encode()).decode()
        chord_mods = {"cmd": {"valid": True, "arg": f"create:{enc_cmd}",
                              "subtitle": cmd_sub},
                      "cmd+shift": {"valid": True, "arg": f"create:{enc_stage}",
                                    "subtitle": "📍 Stage for focus"}}

    items = [alfred.item(
        title=f"Create: {title}",
        subtitle=subtitle,
        arg=f"create:{encoded}",
        valid=True,
        mods=chord_mods,
    )]

    # Offer the next scheduling step as a selectable row (mirrors reschedule.py
    # Screen 2): once a date is set, surface "Add time"; once a time is set,
    # "Add duration" — each drops into the existing @ / > picker. Skipped when a
    # =note is present (the trigger would land after the opaque note text). Date
    # entry stays on the * picker.
    if not note:
        base_q = query.rstrip()
        if due_date and not time_str:
            items.append(alfred.item(
                title="⏰ Add time",
                subtitle=f"Pick time for {_utc_iso_to_picker_display(due_date)}",
                arg="", valid=False,
                autocomplete=f"{base_q} @",
            ))
        elif time_str and not end_str:
            items.append(alfred.item(
                title="⏳ Add duration",
                subtitle=f"End time for @{time_str}",
                arg="", valid=False,
                autocomplete=f"{base_q} >",
            ))
        # Always offer a reminder once a date is set (mirrors reschedule.py)
        if due_date or end_date:
            items.append(alfred.item(
                title="🔔 Add another reminder" if reminders else "🔔 Add reminder",
                subtitle=(f"Current: {', '.join(reminders)}  ⏎ add another"
                          if reminders else "Remind before due"),
                arg="", valid=False,
                autocomplete=f"{base_q} %",
            ))

    return items

# ── Note preview ─────────────────────────────────────────────────────────────
def note_preview(query):
    (title, date_str, time_str, end_str, _, tags,
     list_name, parent_name, section_name, note, repeat, reminders, *_) = parse_task(query)

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

    # Scheduling — notes support dates/duration/repeat/reminders too (verified via
    # API). Same computation as task_preview.
    if date_str and time_str:
        combined_date_str = f"{date_str} {time_str}"
    elif time_str:
        combined_date_str = f"today {time_str}"
    else:
        combined_date_str = date_str
    due_date = parse_date(combined_date_str)
    end_date = None
    end_norm = _normalize_end(end_str) if end_str else None
    if end_norm and time_str and due_date:
        end_date = parse_date(f"{date_str} {end_norm}" if date_str else f"today {end_norm}")
        if end_date and end_date <= due_date:
            from datetime import datetime, timedelta
            dt = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S%z") + timedelta(days=1)
            end_date = dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

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
    if date_str or time_str:
        date_display = _utc_iso_to_local_display(due_date) if due_date else f"{combined_date_str or ''}?"
        parts.append(f"*{date_display}")
    if end_date and time_str:
        parts.append(f"⏳{_duration_label(time_str, end_norm)}")
    elif end_str and not time_str:
        parts.append(f">{end_str}?")
    if repeat:
        parts.append(f"🔁{REPEAT_LABEL[repeat]}" if repeat in REPEAT_RRULE and date_str else f"🔁{repeat}?")
    for rem in reminders:
        ok = _reminder_trigger(rem) and (due_date or end_date)
        parts.append(f"🔔{rem}" if ok else f"🔔{rem}?")
    tags, tag_parents = _split_tag_parents(tags)
    for t in tags:
        parts.append(f"#{t}" + (f"↳{tag_parents[t.lower()]}"
                                if t.lower() in tag_parents else ""))
    if note:
        short = note if len(note) <= 24 else note[:24] + "…"
        parts.append(f"📝{short}")
    subtitle = (("  ".join(parts) + "  |  " if parts else "")
                + "⌘🎯 ⇧⌘📍  |  "
                + symbol_legend(has_date=bool(due_date), note_mode=True))

    # Build payload
    payload = {"title": resolve_wikilinks(title, prefer_pid=list_id), "kind": "NOTE"}
    if list_id:
        payload["projectId"] = list_id
    if note:
        payload["content"] = note
    if tags:
        payload["tags"] = tags
        if tag_parents:
            payload["_tag_parents"] = tag_parents
    if end_date and due_date:
        payload["startDate"] = due_date
        payload["dueDate"]   = end_date
    elif due_date:
        payload["dueDate"] = due_date
    if repeat in REPEAT_RRULE and (due_date or end_date):
        payload["repeatFlag"] = REPEAT_RRULE[repeat]
    if reminders and (due_date or end_date):
        seen = set()
        triggers = []
        for rem in reminders:
            trig = _reminder_trigger(rem)
            if trig and trig not in seen:
                seen.add(trig)
                triggers.append(trig)
        if triggers:
            payload["reminders"] = triggers
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

    # R4.4 focus chords, note parity: the ⌘ Actions menu already offers
    # 🎯 Focus / Add-to-focus / Stage on notes, so the preview chords mirror
    # the task path — same payload-copy trick (fleet: the new canvas edges
    # would otherwise fire the plain create silently on a chorded ⏎).
    p_cmd = dict(payload)
    if _fx_probe():
        p_cmd["_post_fx"] = True
        cmd_sub = "🎯 Add to running focus"
    else:
        p_cmd["_post_fstart"] = True
        cmd_sub = "🎯 Start Focus"
    p_stage = dict(payload)
    p_stage["_post_stage"] = True
    enc_cmd = base64.b64encode(json.dumps(p_cmd).encode()).decode()
    enc_stage = base64.b64encode(json.dumps(p_stage).encode()).decode()

    items = [alfred.item(
        title=f"Create note: {title}",
        subtitle=subtitle,
        arg=f"create:{encoded}",
        valid=True,
        mods={"cmd": {"valid": True, "arg": f"create:{enc_cmd}",
                      "subtitle": cmd_sub},
              "cmd+shift": {"valid": True, "arg": f"create:{enc_stage}",
                            "subtitle": "📍 Stage for focus"}},
    )]
    # Offer the next scheduling step (mirrors task_preview). The "n " prefix keeps
    # the autocomplete in note mode; skipped when a =note body is present.
    if not note:
        base_q = "n " + query.rstrip()
        if due_date and not time_str:
            items.append(alfred.item(
                title="⏰ Add time",
                subtitle=f"Pick time for {_utc_iso_to_picker_display(due_date)}",
                arg="", valid=False, autocomplete=f"{base_q} @"))
        elif time_str and not end_str:
            items.append(alfred.item(
                title="⏳ Add duration",
                subtitle=f"End time for @{time_str}",
                arg="", valid=False, autocomplete=f"{base_q} >"))
        if due_date or end_date:
            items.append(alfred.item(
                title="🔔 Add another reminder" if reminders else "🔔 Add reminder",
                subtitle=(f"Current: {', '.join(reminders)}  ⏎ add another"
                          if reminders else "Remind before due"),
                arg="", valid=False, autocomplete=f"{base_q} %"))
    return items


# ── List creation mode ────────────────────────────────────────────────────────
def list_create_items(name):
    if not name:
        return [alfred.item(
            title="Type a list name…",
            subtitle="Create list  ⌃ 🔙",
            valid=False,
        )]
    payload = {"name": name}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    # Chorded ⏎ must NOT silently fall through the R4.4 ⌘/⇧⌘ canvas edges
    # and create the list anyway — the focus chords are a preview-row thing.
    _no_chord = {"cmd": {"valid": False, "subtitle": ""},
                 "cmd+shift": {"valid": False, "subtitle": ""}}
    return [alfred.item(
        title="Create list",
        subtitle="⌃ 🔙",
        arg=f"create_list:{encoded}",
        valid=True,
        mods=_no_chord,
    )]


# ── Tag creation mode (R4.5 — the T scope; two-step like the schedule flow) ──
def tag_create_items(fragment):
    """'T <name>' → exactly TWO rows: ➕ create top-level, or 🪆 nest — ⏎ on
    nest autocompletes 'T <name>>' and only THEN the parent list appears,
    text after the '>' filtering it (Vex 2026-07-11: the flat all-at-once
    parent list couldn't be filtered). The arg is xact:tag_create:<b64> —
    dispatch grew an xact: passthrough for it (its raw-URL fallback would
    open() the arg)."""
    import tagtree
    from display import tag_match_key
    if not fragment:
        return [alfred.item(
            title="Type a tag name…",
            subtitle="Create tag  ⌃ 🔙",
            valid=False,
        )]
    # '>' splits the name from the parent step BEFORE the sanitizer eats it
    # (the # picker's '#name>parent' grammar)
    base, nest_step, pfrag = fragment.partition(">")
    # , : never reach TickTick (see xact.tag_create); # is the token char
    name = (base.strip().split(" ", 1)[0]
            .lstrip("#").replace(",", "").replace(":", ""))
    if not name:
        return [alfred.item(title="Type a tag name…",
                            subtitle="Create tag  ⌃ 🔙", valid=False)]
    tags = cache_store.get("tags") or []
    if tag_match_key(name) in {tag_match_key(t) for t in tags}:
        return [alfred.item(
            title=f"#{name} already exists",
            subtitle="Pick a new name  ⌃ 🔙",
            valid=False,
        )]

    def _arg(parent=None):
        spec = {"label": name}
        if parent:
            spec["parent"] = parent
        return "xact:tag_create:" + base64.b64encode(
            json.dumps(spec).encode()).decode()

    # chorded ⏎ must not fall through the R4.4 ⌘/⇧⌘ canvas edges
    _no_chord = {"cmd": {"valid": False, "subtitle": ""},
                 "cmd+shift": {"valid": False, "subtitle": ""}}

    if not nest_step:
        return [
            alfred.item(
                uid="tadd-create-plain",
                title=f"➕ #{name}",
                subtitle="Create tag  ⌃ 🔙",
                arg=_arg(),
                mods=_no_chord,
            ),
            alfred.item(
                uid="tadd-create-nest",
                title=f"🪆 #{name} under parent…",
                subtitle="Pick parent  ⌃ 🔙",
                arg="", valid=False,
                autocomplete=f"t {name}>",
            ),
        ]

    # parent step: 't name>[filter]'
    pfrag_l = pfrag.strip().lower()
    items = []
    for p in tagtree.top_level_labels(tags):
        if tag_match_key(p) == tag_match_key(name):
            continue
        if pfrag_l and pfrag_l not in p.lower():
            continue
        items.append(alfred.item(
            uid=f"tadd-create-{p}",
            title=f"➕ #{name} under {p}",
            subtitle="Create nested tag  ⌃ 🔙",
            arg=_arg(p),
            mods=_no_chord,
        ))
    return items or [alfred.item(
        title=f'No parent matching "{pfrag.strip()}"',
        subtitle="⌫ 🔙",
        valid=False,
    )]


# ── Project creation mode ─────────────────────────────────────────────────────
# Keycap number emoji: digit + U+FE0F (variation selector) + U+20E3 (keycap)
AREA_RE = re.compile(r"^([0-9]️?⃣)")

def get_area_tags():
    """Area tags — entries starting with a keycap number. Delegates to
    areas.area_tags(): synced tags cache first (v2 tree / config /
    discovered)."""
    return _areas.area_tags()   # [("1️⃣Work", "1️⃣"), …]


def project_create_items(name):
    if not name:
        return [alfred.item(
            title="Type a project name…",
            subtitle="Create 💼P • list, schedule 📌CTA  ⌃ 🔙",
            valid=False,
        )]
    areas = get_area_tags()
    if not areas:
        return [alfred.item(
            title="No area tags found",
            subtitle="Tag one 1️⃣… in TickTick, then Sync",
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
            subtitle=f"Create  💼P • {name} {emoji}  →  schedule  💼 P • {name} 🔗",
            arg=f"create_project_meta:{payload}",
            # chorded ⏎ must not fall through the R4.4 mod edges and
            # commit the whole project flow
            mods={"cmd": {"valid": False, "subtitle": ""},
                  "cmd+shift": {"valid": False, "subtitle": ""}},
        ))
    return items


# ── Main ──────────────────────────────────────────────────────────────────────
# P4c: back is ⌃ everywhere — stamp the ⌃ back-mod on every emitted row
# (mod-level valid=True lets it fire even from invalid prompt/hint rows).
# R3.75: opened on a TASK (add-subtask from ⌘ Actions) → ⌃ returns to that
# task's Actions menu instead of the main menu. The ⌃ wire is hardcoded to
# the MainMenu Call-ET (passinputasargument=False, passvariables=True), so
# the return request rides a session variable that main_menu.py honors.
_orig_output = alfred.output
def _output_backstamped(items, **kw):
    back = {"valid": True, "arg": "", "subtitle": "🔙 Main menu"}
    _pid = os.environ.get("task_list_id", "")
    _tid = os.environ.get("task_id", "")
    if _pid and _tid and os.environ.get("item_type", "") in ("task", "note"):
        back = {"valid": True, "arg": "", "subtitle": "🔙 Task actions",
                "variables": {"menu_return": f"{_pid}:{_tid}"}}
    for _it in items:
        _it.setdefault("mods", {}).setdefault("ctrl", dict(back))
    return _orig_output(items, **kw)
alfred.output = _output_backstamped


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
            pre = os.environ.get("prefill_note", "").strip()
            err = os.environ.get("prefill_error", "").strip()
            if pre:
                sub = f"🔗 {pre}"
            elif err:
                sub = f"⚠️ {err}"
            else:
                sub = _add_target_label() or "/ for list, note, project or tag"
            items = [alfred.item(
                title="Type a task name…",
                subtitle=sub,
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

        # ── T prefix → create tag (R4.5) ──────────────────────────────────────
        if query.lower().startswith("t "):
            items = tag_create_items(query[2:].strip())
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
                elif ch == '#':
                    items = tag_picker(prefix, fragment)
                elif ch == '*':
                    items = date_picker(prefix, fragment)
                elif ch == '@':
                    items = time_picker(prefix, fragment)
                elif ch == '>':
                    items = duration_picker(prefix, fragment)
                elif ch == '&':
                    items = repeat_picker(prefix, fragment)
                elif ch == '%':
                    items = reminder_picker(prefix, fragment)
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
            elif ch == '%':
                items = reminder_picker(prefix, fragment)
            elif ch == '[[':
                sl = parse_task(prefix)[6]   # list typed so far (~l …)
                scope = (resolve_list_id(sl, get_lists())[0] if sl
                         else os.environ.get("list_id") or os.environ.get("task_list_id") or None)
                items = link_picker(prefix, fragment, scope)
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
