#!/usr/bin/env python3
"""
everything_search.py - Alfred Script Filter
Searches across ALL item types: lists, sections, and tasks at every depth.

Each result carries an item_type variable ("list" / "section" / "task") plus a
browse_ctx, so ⌥⏎ (Browse) drills into the matching browse.py context.
"""
import sys
import os
import json
import traceback

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR, run_path
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from display import (build_title, build_subtitle, join_breadcrumb, search_key,
                         fmt_tags, tag_link, MODS_NOTE, buffered_ids,
                         md_links_display, note_snippet, tag_match_key)
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

# ── Depth calculator ─────────────────────────────────────────────────────────
def compute_depths(all_tasks):
    """Return {task_id: depth} where depth 0 = top-level, 1 = subtask, etc."""
    task_by_id = {t["id"]: t for t in all_tasks}
    depths     = {}

    def get_depth(tid, visited=None):
        if tid in depths:
            return depths[tid]
        if visited is None:
            visited = set()
        if tid in visited:          # cycle guard
            return 0
        visited.add(tid)
        t = task_by_id.get(tid)
        if not t or not t.get("parentId"):
            depths[tid] = 0
            return 0
        d = get_depth(t["parentId"], visited) + 1
        depths[tid] = d
        return d

    for t in all_tasks:
        get_depth(t["id"])
    return depths

# ── Breadcrumb helper ─────────────────────────────────────────────────────────
def get_task_breadcrumb(task, task_by_id):
    ancestor_titles = []
    current = task
    seen    = set()
    while current.get("parentId"):
        pid = current["parentId"]
        if pid in seen:
            break
        seen.add(pid)
        parent = task_by_id.get(pid)
        if not parent:
            break
        ancestor_titles.append(parent.get("title", "?"))
        current = parent
    col_name  = current.get("_columnName", "")
    list_name = task.get("_projectName", "")
    ancestor_titles.reverse()
    return join_breadcrumb(list_name, col_name, *ancestor_titles)

# ── Scope picker (/) ──────────────────────────────────────────────────────────
# (prefix, emoji, name, description, letter shortcut)
SCOPES = [
    ("",    "🔍", "Everything",       "every item type",          ""),
    ("l ",  "📋", "Lists",            "lists only",        "L"),
    ("s ",  "📑", "Sections",         "sections only",     "S"),
    ("t ",  "✅", "Tasks",            "top-level tasks",          "T"),
    ("tt ", "↳",  "Subtasks",         "subtasks only",            "TT"),
    ("a ",  "🗂",  "Tasks + Subtasks", "tasks at any depth",       "A"),
    ("g ",  "🏷",  "Tags",             "tasks by tag",        "G"),
    ("v ",  "🗓",  "Smart lists",      "Today, Inbox, Completed…", "V"),
    ("f ",  "🔍", "Filters",          "your TickTick filters",    "F"),
    ("fo ", "📂", "Folders",          "your TickTick folders",    "FO"),
    ("la ", "👉", "Last Added",       "recently created first",   "LA"),
    ("pn ", "💫", "Periodic",         "daily / weekly notes",     "PN"),
    ("n ",  "📝", "Notes",            "note titles",              "N"),
    ("nc ", "📄", "Note bodies",      "note text",  "NC"),
]

def scope_menu(fragment):
    """Dropdown of search scopes, shown when the query starts with '/'.
    Selecting one autocompletes its prefix; the letter shortcut is also shown."""
    frag = fragment.lower().strip()
    items = []
    for prefix, emoji, name, desc, letter in SCOPES:
        if frag and not (letter.lower().startswith(frag) or name.lower().startswith(frag)):
            continue
        items.append(alfred.item(
            title=f"{emoji}  {name}",
            subtitle=desc,
            arg="", valid=False,
            autocomplete=prefix,
        ))
    if not items:
        items = [alfred.item(title=f'No scope matching "{fragment}"', valid=False)]
    return items

def get_hint_items(raw_query):
    """
    Empty query → a hint pointing at '/'. Query starting with '/' → scope menu.
    Returns None to proceed with normal search.
    """
    if not raw_query:
        rows = [alfred.item(
            title="Type to search everything…",
            subtitle="Type / for scope",
            valid=False,
        )]
        # 🅿️ non-empty buffer → surface it (⌥ opens the buffer view)
        try:
            with open(run_path("tickal_buffer.txt")) as f:
                n = len([ln for ln in f if ln.strip()])
        except OSError:
            n = 0
        if n:
            rows.insert(0, alfred.item(
                title=f"🅿️ Buffer · {n} task{'s' if n != 1 else ''}",
                subtitle="⌥ Open buffer",
                valid=False,
                mods={"alt": {"valid": True, "arg": "", "subtitle": "Open buffer",
                              "variables": {"browse_ctx": "ctx:buffer"}}},
            ))
        return rows

    if raw_query.startswith("/"):
        return scope_menu(raw_query[1:])

    return None

# ── Scope prefix detection ───────────────────────────────────────────────────
SCOPE_PREFIXES = {
    "l ":  "list",
    "s ":  "section",
    "t ":  "task",
    "tt ": "subtask",
    "a ":  "all_tasks",
    "g ":  "tag",
    "v ":  "view",
    "f ":  "filter",
    "fo ": "folders",
    "la ": "last_added",
    "pn ": "periodic",
    "n ":  "note",
    "nc ": "note_content",
}

def detect_scope(query):
    """Return (scope, stripped_query) or (None, query)."""
    q_lower = query.lower()
    # Check longer prefixes first (ts/nc before t/n/s)
    for prefix in sorted(SCOPE_PREFIXES, key=len, reverse=True):
        if q_lower.startswith(prefix):
            return SCOPE_PREFIXES[prefix], query[len(prefix):].strip()
    return None, query


# Inline /x tokens: the same letters as the leading-prefix grammar,
# usable anywhere in the bar ("monday /t").
_INLINE_TOKENS = {k.strip(): v for k, v in SCOPE_PREFIXES.items()}


def _tag_create_parent_rows(fragment):
    """'g +<name> ' - step 2 of ➕ Create tag: create top-level, or pick
    a parent to nest under. Rows fire xact:tag_create:<b64> - the xact route
    is the only arg shape search-⏎ (modOpen) forwards to a script."""
    import base64
    import tagtree
    name = (fragment.strip().lstrip("#")
            .replace(",", "").replace(":", "").replace(">", ""))
    frag = ""
    if " " in name:
        name, frag = name.split(" ", 1)
        frag = frag.strip().lower()
    if not name:
        return [alfred.item(title="Type the new tag's name", valid=False)]
    known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
    if tag_match_key(name) in known:
        return [alfred.item(
            uid="gtag-create-exists",
            title=f"#{name} already exists",
            subtitle="⌃🔙",
            arg="", valid=False, autocomplete=f"g {name}")]

    def _arg(parent=None):
        spec = {"label": name}
        if parent:
            spec["parent"] = parent
        return "xact:tag_create:" + base64.b64encode(
            json.dumps(spec).encode()).decode()

    rows = [alfred.item(
        uid="gtag-create-plain",
        title=f"➕ #{name}",
        subtitle="Create top-level tag  ⌃🔙",
        arg=_arg(), valid=True)]
    for p in tagtree.top_level_labels():
        if frag and frag not in p.lower():
            continue
        rows.append(alfred.item(
            uid=f"gtag-create-{p}",
            title=f"➕ #{name} under {fmt_tags([p]) or '#' + p}",
            subtitle="Create under parent  ⌃🔙",
            arg=_arg(p), valid=True))
    return rows


# ── G scope tag rows ─────────────────────────────────────────────────────────
def tag_scope_rows(all_tasks, fragment, only=None):
    """Every tag on an incomplete item, with counts - the first screen of the
    G scope. ⏎ advances the bar to 'g #<tag> ' (exact-tag mode below); ⌘ opens
    the Actions menu for the tag; ⌥⌘ copies the tag's web-app link."""
    if fragment.startswith("+"):
        return _tag_create_parent_rows(fragment[1:])
    counts = {}
    for t in all_tasks:
        if t.get("status", 0) != 0:
            continue
        for tag in (t.get("tags") or []):
            counts[tag] = counts.get(tag, 0) + 1

    # Tags with no open items (incl. parent tags like 🔥CRM) still get a row -
    # ⌘ Actions / the web link work for them, and hiding them reads as data loss.
    seen = {t.lower() for t in counts}
    for lbl in (cache_store.get("tags") or []):
        if lbl.lower() not in seen:
            counts[lbl.lower()] = 0

    if only is not None:   # parent drill: restrict to the parent's children
        counts = {t: n for t, n in counts.items() if t.lower() in only}
        for k in only:     # children with no cached usage still get a row
            if k not in {t.lower() for t in counts}:
                counts[k] = 0

    rows = []
    for tag in sorted(counts, key=lambda t: (counts[t] == 0, t.lower())):
        n = counts[tag]
        plural = "s" if n != 1 else ""
        link = tag_link(tag)
        rows.append(alfred.item(
            uid=f"gtag-{tag}",
            title=fmt_tags([tag]) or f"#{tag}",
            subtitle=f"Tag  {n} Item{plural}  |  ⏎⤵️  ⌘⚡  ⌃🔙",
            arg="", valid=False,
            autocomplete=f"g #{tag} ",
            mods={
                "cmd":     {"arg": "", "valid": True, "subtitle": "⌘ Actions"},
                "alt+cmd": {"arg": f"copy:{link}", "valid": True,
                            "subtitle": "Copy tag link"},
            },
            variables={"item_type": "tag", "tag_name": tag,
                       "search_name": tag, "type_rank": 0},
        ))
    if fragment:
        rows = fuzz.filter_and_score(
            fragment, rows,
            key_fn=lambda x: x.get("variables", {}).get("search_name", x["title"]))
        # ➕ new tag: the typed name matches no existing tag → offer to
        # coin it; ⏎ opens the top-level / nest-under-parent step. Checked
        # against the FULL cache (not the drill-restricted counts) and never
        # offered inside a parent drill - `only` hides existing tags there.
        frag_tag = fragment.strip().lstrip("#")
        full_known = ({tag_match_key(t) for t in counts}
                      | {tag_match_key(t) for t in (cache_store.get("tags") or [])})
        if only is None and frag_tag and tag_match_key(frag_tag) not in full_known:
            rows.append(alfred.item(
                uid="gtag-new",
                title=f"➕ Create tag #{frag_tag}",
                subtitle="Add tag + nest under parent  ⌃🔙",
                arg="", valid=False,
                autocomplete=f"g +{frag_tag} ",
            ))
    return rows

# ── V/F scopes: smart lists + filters live in search ─────────────────────────
# (key, emoji, name, kind, browse ctx, app-open URL). kind "alfred" renders
# inline on ⏎ (locked scope, G-scope pattern); kind "app" opens the view in
# TickTick on ⏎ via its deep-link route (ticktick://habit|matrix|focus -
# verified against the app; the alfred://runtrigger URL scheme does NOT fire
# from modOpen, don't go back to it).
VIEWS = [
    ("today",     "☀️", "Today",       "alfred", "ctx:smart:today",
     "ticktick://v1/show?smartlist=today"),
    ("tomorrow",  "🌅", "Tomorrow",    "alfred", "ctx:smart:tomorrow",
     "ticktick://v1/show?smartlist=tomorrow"),
    ("next7",     "📅", "Next 7 Days", "alfred", "ctx:smart:next7",
     "ticktick://v1/show?smartlist=next_7_days"),
    ("inbox",     "📥", "Inbox",       "alfred", "ctx:inbox",
     "ticktick:///webapp/#p/inbox/tasks"),
    ("summary",   "📈", "Summary",     "app", None, None),
    # Summary has NO working deep link (v1/show?smartlist=summary,
    # ticktick://summary, webapp/#summary are all dead) - url None routes it
    # through xact:view_open (List-menu click). ⏎ needs the modOpen
    # runscript's xact passthrough; ⌘ → Open always works.
    ("completed", "✅", "Completed",   "alfred", "ctx:completed",
     "ticktick://v1/show?smartlist=completed"),
    # Won't Do has NO app route at all (v1/show + webapp hashes + List menu
    # all probed dead) - Alfred-inline only, url None.
    ("wontdo",    "🚫", "Won't Do",    "alfred", "ctx:wontdo", None),
    ("habits",    "🔄", "Habits",      "app", None, "ticktick://habit"),
    ("matrix",    "🧭", "Matrix",      "app", None, "ticktick://matrix"),
    ("pomo",      "🍅", "Pomodoro",    "app", None, "ticktick://focus"),
]


def view_rows(fragment):
    """Smart-list rows: ⏎ drills inline (autocomplete lock) for in-Alfred
    views, opens the app view for app-only ones; ⌥ = Browse-box drill."""
    items = []
    for key, emoji, name, kind, ctx, url in VIEWS:
        if kind == "app":
            items.append(alfred.item(
                uid=f"view-{key}",
                title=f"{emoji} {name}",
                subtitle="Smart list  |  ⏎↗️  ⌘⚡  ⌃🔙",
                arg=f"open:{url}" if url else f"xact:view_open:{key}",
                mods={"cmd":       {"valid": True, "arg": "", "subtitle": "⌘ Actions"},
                      "shift":     {"valid": False, "subtitle": ""},
                      "alt":       {"valid": False, "subtitle": ""},
                      "alt+shift": {"valid": False, "subtitle": ""},
                      "alt+cmd":   ({"valid": True, "arg": f"copy:{url}",
                                     "subtitle": "Copy app link"} if url
                                    else {"valid": False, "subtitle": ""})},
                variables={"item_type": "view", "search_name": name, "type_rank": 0,
                           "view_key": key, "view_name": name, "view_url": url or ""},
            ))
        else:
            items.append(alfred.item(
                uid=f"view-{key}",
                title=f"{emoji} {name}",
                subtitle=("Smart list  |  ⏎⤵️  ⌘⚡  ⌥⤵️  ⌥⌘🔗  ⌃🔙" if url
                          else "Smart list  |  ⏎⤵️  ⌘⚡  ⌥⤵️  ⌃🔙"),
                arg="", valid=False,
                autocomplete=f"v {name} ",
                mods={
                    "cmd":       {"valid": True, "arg": "", "subtitle": "⌘ Actions"},
                    "alt":       {"valid": True, "arg": "", "subtitle": "Browse in Alfred",
                                  "variables": {"browse_ctx": ctx}},
                    "alt+cmd":   ({"valid": True, "arg": f"copy:{url}",
                                   "subtitle": "Copy app link"} if url
                                  else {"valid": False, "subtitle": ""}),
                    "shift":     {"valid": False, "subtitle": ""},
                    "alt+shift": {"valid": False, "subtitle": ""},
                },
                variables={"item_type": "view", "search_name": name, "type_rank": 0,
                           "view_key": key, "view_name": name, "view_url": url or ""},
            ))
    if fragment:
        items = fuzz.filter_and_score(
            fragment, items,
            key_fn=lambda x: x.get("variables", {}).get("search_name", x["title"]))
    return items


def filter_rows(fragment):
    """Custom-filter rows (filters_config.py): ⏎ drills inline, ⌥ = ctx:filter
    Browse-box drill (full ⌘ Actions on the tasks there)."""
    import filtering
    import re as _re
    items = []
    for i, f in enumerate(filtering.load_filters()):
        name = f.get("name", f"Filter {i + 1}")
        # emoji-stripped search key: typing "crm" must exact-match "🔥CRM"
        clean = _re.sub(r"[^\w\s·-]", "", name).strip() or name
        crit = filtering.filter_criteria_summary(f)
        sub  = f"Filter  {crit}  |  ⏎⤵️  ⌥⤵️  ⌃🔙" if crit else "Filter  |  ⏎⤵️  ⌥⤵️  ⌃🔙"
        items.append(alfred.item(
            uid=f"vfilter-{i}",
            title=name,
            subtitle=sub,
            arg="", valid=False,
            autocomplete=f"f {name} ",
            mods={
                "alt":       {"valid": True, "arg": "", "subtitle": "Browse in Alfred",
                              "variables": {"browse_ctx": f"ctx:filter:{i}"}},
                "shift":     {"valid": False, "subtitle": ""},
                "alt+shift": {"valid": False, "subtitle": ""},
                "alt+cmd":   {"valid": False, "subtitle": ""},
            },
            variables={"item_type": "filter", "search_name": clean, "type_rank": 0},
        ))
    if fragment:
        items = fuzz.filter_and_score(
            fragment, items,
            key_fn=lambda x: x.get("variables", {}).get("search_name", x["title"]))
    return items


def _inline_task_row(t, crumb_head, pool, completed=False, wontdo=False):
    """Task row for a locked v/f view - search-convention mods (⏎ open,
    ⇧ complete/uncomplete, ⌘ Actions, ⌥ browse subtasks, ⌥⌘ copy).
    completed/wontdo = the two closed states; same row shape, ⇧ reopens."""
    tid  = t.get("id", "")
    pid  = t.get("projectId") or t.get("_projectId", "")
    name = t.get("title", "Untitled")
    breadcrumb = join_breadcrumb(crumb_head, t.get("_projectName", ""),
                                 t.get("_columnName", ""))
    link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"
    if completed or wontdo:
        done_on = (t.get("completedTime") or "")[:10]
        mark = "🚫" if wontdo else "✅"
        subtitle = f"{mark} {done_on}  {breadcrumb}  |  ⏎↗️  ⇧↩️  ⌘⚡  ⌃🔙"
        shift = {"arg": (f"xact:wontdo_undo:{pid}:{tid}" if wontdo
                         else f"uncomplete:{pid}:{tid}:{name}"), "valid": True,
                 "subtitle": "Reopen" if wontdo else "Uncomplete"}
        alt   = {"valid": False, "subtitle": ""}
        altshift = {"valid": False, "subtitle": ""}   # buffering done tasks = nonsense
        ctrlshift = {"valid": False, "subtitle": ""}  # focusing them, too
    else:
        sub_count = sum(1 for s in pool
                        if s.get("parentId") == tid and s.get("status", 0) == 0)
        subtitle = build_subtitle(sub_count, "Task", breadcrumb=breadcrumb, actions=True,
                                  note=note_snippet(t.get("content"))
                                  if t.get("kind") != "NOTE" else "")
        shift = {"arg": f"complete:{pid}:{tid}:{name}"}
        alt   = {"arg": "", "subtitle": "Browse subtasks",
                 "variables": {"browse_ctx": f"ctx:subtasks:{pid}:{tid}"}}
        # ⌥⇧ → buffer
        altshift = {"valid": True, "arg": f"xact:buffer_add:{pid}:{tid}",
                    "subtitle": "🅿️ Add to buffer",
                    "variables": {"task_title": name, "task_id": tid,
                                  "task_list_id": pid, "item_type": "task"}}
        # ⌃⇧ → the ⏱/🍅 start flow; notes don't focus
        ctrlshift = ({"valid": True, "arg": f"xact:focus_open:{pid}:{tid}",
                      "subtitle": "Start focus",
                      "variables": {"task_title": name, "task_id": tid,
                                    "task_list_id": pid, "item_type": "task"}}
                     if t.get("kind") != "NOTE"
                     else {"valid": False, "subtitle": ""})
    return alfred.item(
        title=build_title(t, buffered=tid in buffered_ids()),
        subtitle=subtitle,
        arg=f"open:{link}",
        mods={
            "cmd":        {"arg": ""},
            "shift":      shift,
            "alt":        alt,
            "alt+shift":  altshift,
            "ctrl+shift": ctrlshift,
            "alt+cmd":    {"arg": f"copy:{link}"},
            "ctrl":       {"arg": "", "subtitle": "🔙 Main menu"},
        },
        variables={"item_type": "task", "task_id": tid, "task_title": name,
                   "task_list_id": pid, "search_name": name, "type_rank": 2,
                   "_priority": t.get("priority") or 0},
    )


def last_added_rows(query, all_tasks):
    """LA scope: incomplete tasks, newest createdTime first. Typing
    filters, but recency keeps ruling the order (fuzzy decides inclusion,
    not position)."""
    pool = [t for t in all_tasks if t.get("status", 0) == 0]
    if query:
        pool = fuzz.filter_and_score(query, pool,
                                     key_fn=lambda t: search_key(t.get("title", "")))
    pool = sorted(pool, key=lambda t: t.get("createdTime") or "", reverse=True)[:100]
    rows = [_inline_task_row(t, "Last Added", all_tasks) for t in pool]
    if not rows:
        rows = [alfred.item(
            title=f'No task matching "{query}"' if query else "No tasks cached · run Sync first",
            valid=False)]
    return rows


def folder_scope_rows(query):
    """FO scope: your TickTick folders (v2 auto-named at sync, manual
    config.json overrides on top) - ⌥⏎ drills into the folder's lists, same
    ordering as browse's folder root."""
    import config as cfg
    import re as _re
    projects = cache_store.get("projects") or []
    folders  = cfg.get_folders()
    v2_order = {g.get("id"): (g.get("sortOrder") or 0)
                for g in (cache_store.get("folder_groups") or [])}
    pos = {gid: i for i, gid in enumerate(folders)}

    def _ord(name):
        m = _re.match(r'^(\d+)\)\s(.+)$', name.strip())
        return (int(m.group(1)), m.group(2).strip()) if m else (9999, name.strip())

    rows = []
    for gid, raw_name in sorted(folders.items(),
                                key=lambda kv: (_ord(kv[1])[0],
                                                v2_order.get(kv[0], float("inf")),
                                                pos[kv[0]])):
        clean = _ord(raw_name)[1]
        n = sum(1 for p in projects
                if p.get("groupId") == gid and p.get("kind") != "SMART_LIST")
        rows.append(alfred.item(
            uid=f"folder-{gid}",
            title=clean,
            subtitle=f"Folder  {n} List{'s' if n != 1 else ''}  |  ⌥⤵️  ⌃🔙",
            arg="", valid=False,
            mods={
                "alt":   {"arg": "", "valid": True, "subtitle": "Browse lists",
                          "variables": {"browse_ctx": f"ctx:lists:{gid}"}},
                # Actions can't handle folder context - dead ⌘ (browse parity)
                "cmd":   {"valid": False, "subtitle": ""},
                "shift": {"valid": False, "subtitle": ""},
            },
            variables={"folder_id": gid, "folder_name": clean,
                       "item_type": "folder", "search_name": clean,
                       "type_rank": 0},
        ))
    if not rows:
        return [alfred.item(
            title="No folders known yet",
            subtitle="Run Sync + Attachment Login",
            valid=False)]
    if query:
        rows = fuzz.filter_and_score(
            query, rows,
            key_fn=lambda x: x.get("variables", {}).get("search_name", x["title"])) \
            or [alfred.item(title=f'No folders matching "{query}"', valid=False)]
    return rows


def render_view_inline(entry, query):
    """Locked 'v <Name> [query]' - the view's tasks inline in search."""
    key, emoji, name, kind, ctx, url = entry
    items = []
    if url or kind == "app":
        items.append(alfred.item(
            uid=f"view-open-{key}",
            title=f"↗️ Open {name} in TickTick",
            subtitle="Smart list  |  ⏎↗️  ⌘⚡",
            arg=f"open:{url}" if url else f"xact:view_open:{key}",
            mods={"cmd":       {"valid": True, "arg": "", "subtitle": "⌘ Actions"},
                  "shift":     {"valid": False, "subtitle": ""},
                  "alt":       {"valid": False, "subtitle": ""},
                  "alt+shift": {"valid": False, "subtitle": ""},
                  "alt+cmd":   {"valid": False, "subtitle": ""}},
            variables={"item_type": "view", "search_name": name,
                       "view_key": key, "view_name": name, "view_url": url},
        ))
    if kind == "app":
        return items

    if key in ("today", "tomorrow", "next7"):
        from filtering import smart_filter
        pool = cache_store.get("all_tasks") or []
        kind_map = {"today": "today", "tomorrow": "tomorrow", "next7": "next7days"}
        rows = [_inline_task_row(t, name, pool)
                for t in smart_filter(pool, kind_map[key])]
    elif key == "inbox":
        data = cache_store.get("project_data_inbox") or {}
        pool = data.get("tasks", [])
        rows = [_inline_task_row(t, "Inbox", pool)
                for t in pool
                if t.get("status", 0) == 0 and not t.get("parentId")]
    elif key == "completed":
        pool = cache_store.get("completed_tasks") or []
        rows = [_inline_task_row(t, "", pool, completed=True) for t in pool]
    elif key == "wontdo":
        pool = cache_store.get("wontdo_tasks") or []
        rows = [_inline_task_row(t, "", pool, wontdo=True) for t in pool]
    else:
        rows = []

    if query:
        rows = fuzz.filter_and_score(
            query, rows,
            key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))
    if not rows:
        rows = [alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {name}",
            valid=False)]
    return items + rows


def render_filter_inline(index, f, query, all_tasks, projects):
    """Locked 'f <Name> [query]' - the filter's matching tasks inline."""
    import filtering
    f_name = f.get("name", f"Filter {index + 1}")
    rows = [_inline_task_row(t, f_name, all_tasks)
            for t in filtering.matching_tasks(f, all_tasks, projects)]
    if query:
        rows = fuzz.filter_and_score(
            query, rows,
            key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"])))
    if not rows:
        rows = [alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {f_name}",
            valid=False)]
    return rows


def render_vf_scope(scope, raw_query, all_tasks, projects):
    """Route a v/f-scoped bar: locked '<Name> <query>' (trailing space, name
    matched longest-first case-insensitive) renders the view/filter's tasks
    inline; anything else is a fragment filtering the picker rows."""
    rest   = raw_query[2:]          # unstripped - the lock needs the trailing space
    rest_l = rest.lower()
    if scope == "view":
        by_name = {e[2].lower(): e for e in VIEWS}
        for nm in sorted(by_name, key=len, reverse=True):
            if rest_l.startswith(nm + " "):
                return render_view_inline(by_name[nm], rest[len(nm) + 1:].strip())
        return view_rows(rest.strip())
    import filtering
    filters = filtering.load_filters()
    by_name = {(f.get("name", f"Filter {i+1}")).lower(): (i, f)
               for i, f in enumerate(filters)}
    for nm in sorted(by_name, key=len, reverse=True):
        if rest_l.startswith(nm + " "):
            i, f = by_name[nm]
            return render_filter_inline(i, f, rest[len(nm) + 1:].strip(),
                                        all_tasks, projects)
    return filter_rows(rest.strip())


# ── Main ─────────────────────────────────────────────────────────────────────
# Back is ⌃ everywhere - stamp the ⌃ back-mod on every emitted row
# (mod-level valid=True lets it fire even from invalid prompt/hint rows).
_orig_output = alfred.output
def _output_backstamped(items, **kw):
    for _it in items:
        _it.setdefault("mods", {}).setdefault("ctrl", {"valid": True, "arg": "", "subtitle": "🔙 Main menu"})
    return _orig_output(items, **kw)
alfred.output = _output_backstamped


_PN_KEYWORDS = [("daily", "daily", "💫", "Daily"),
                ("weekly", "weekly", "📆", "Weekly"),
                ("monthly", "monthly", "🗓", "Monthly"),
                ("quarterly", "quarterly", "🧭", "Quarterly"),
                ("yearly", "yearly", "📅", "Yearly")]


def _periodic_keyword_rows(query):
    """'daily note' / 'weekly'… typed in the everything or note scopes →
    the matching 💫 open row on top."""
    q = (query or "").strip().lower()
    if len(q) < 3:
        return []
    try:
        import areas
        if not areas.periodic_configured():
            return []
        import periodic_rows as pr
        import periodic_model as pmm
        from datetime import date as _date
        rows = []
        for word, spec, emoji, label in _PN_KEYWORDS:
            if f"{word} note".startswith(q):
                p = pr._period_of(spec, _date.today())
                rows.append(alfred.item(
                    uid=f"pn-kw-{spec}",
                    title=f"{emoji} {label} note · {pmm.title(p)}",
                    subtitle="⏎↗️ Open  ⌃⇧📌 Sticky",
                    arg=f"xact:pn_open:{spec}", valid=True,
                    # top-tier type rank + a search_name matching the typed
                    # words, or any list named "Daily…" outranks the row the
                    # feature promises on top
                    variables={"item_type": "view",
                               "search_name": f"{word} note"},
                    mods=pr._mods(spec)))
        return rows
    except Exception:
        return []


def main():
    raw_query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        hint_items = get_hint_items(raw_query)
        if hint_items is not None:
            print(alfred.output(hint_items, skipknowledge=True))
            return

        # ── Instant tag dropdown ──────────────────────────────────────────────
        # A leading '#' IS the tag scope - no 'g' + space dance. '#' alone
        # lists every tag, '#fra' filters, a known tag + space rides the
        # exact-tag / parent-drill machinery unchanged.
        if raw_query.startswith("#"):
            _head = raw_query[1:].split(" ", 1)[0].lower()
            _known = {lbl.lower() for lbl in (cache_store.get("tags") or [])}
            if _head and _head in _known:
                scope, query = "tag", raw_query
            else:
                scope, query = "tag", raw_query[1:]
        else:
            # ── Inline /x scope ──────────────────────────────────────────────
            # A space-preceded /token anywhere in the bar switches the scope
            # instantly - zero extra keypresses, the token is inert for
            # matching ("monday /t" ≡ "t monday"). Unknown tokens
            # (e.g. "/support") stay literal text. A LEADING "/" is the scope
            # menu (handled above). The last valid token wins; it is cut out
            # of the matching query.
            import re as _re
            inline_hit = None
            for _m in _re.finditer(r'(?<!\S)/(\S+)', raw_query):
                if _m.start() > 0 and _m.group(1).lower() in _INLINE_TOKENS:
                    inline_hit = _m
            if inline_hit:
                scope = _INLINE_TOKENS[inline_hit.group(1).lower()]
                query = (raw_query[:inline_hit.start()]
                         + raw_query[inline_hit.end():]).strip()
            else:
                scope, query = detect_scope(raw_query)
        projects  = cache_store.get("projects") or []
        all_tasks = cache_store.get("all_tasks")
        if all_tasks is None:
            # Cache was invalidated - re-fetch so search works immediately
            try:
                import config as cfg
                from api import TickTickAPI
                api_client = TickTickAPI(cfg.get_token())
                all_tasks  = []
                # Inbox is not returned by /project - fetch it separately
                try:
                    inbox_data = api_client.get_project_data("inbox")
                    for t in inbox_data.get("tasks", []):
                        t["_projectId"]   = "inbox"
                        t["_projectName"] = "Inbox"
                        t["_columnName"]  = ""
                        all_tasks.append(t)
                except Exception:
                    pass
                for p in projects:
                    if p.get("kind") == "SMART_LIST":
                        continue
                    try:
                        pdata = api_client.get_project_data(p["id"])
                        for t in pdata.get("tasks", []):
                            t["_projectId"]   = p["id"]
                            t["_projectName"] = p.get("name", "")
                            t["_columnName"]  = ""
                            all_tasks.append(t)
                    except Exception:
                        pass
                cache_store.set("all_tasks", all_tasks)
            except Exception:
                all_tasks = []
        all_tasks = all_tasks or []
        task_by_id = {t["id"]: t for t in all_tasks}
        depths     = compute_depths(all_tasks)

        # G scope, exact-tag mode: 'g #<tag> [query]' (the ⏎ advance from a tag
        # row) locks the view to that tag's items; the rest of the bar fuzzy-
        # filters them by title.
        exact_tag = None
        parent_kids = None
        if scope == "tag" and query.startswith("#"):
            head, _, rest = query[1:].partition(" ")
            # Parent tag: ⏎ on 🎩Area/🔥CRM/… lists its CHILDREN as
            # tag rows instead of an (always empty) exact-tag view.
            import tagtree
            kids = tagtree.children_of(head)
            if kids:
                parent_kids = {k.lower() for k in kids}
                query = rest.strip()
            else:
                known = {tag.lower() for t in all_tasks if t.get("status", 0) == 0
                         for tag in (t.get("tags") or [])}
                known |= {lbl.lower() for lbl in (cache_store.get("tags") or [])}
                if head.lower() in known:
                    exact_tag = head.lower()
                    query = rest.strip()

        # ── V/F scopes render standalone ──────────────────────────────────────
        if scope in ("view", "filter"):
            if inline_hit:
                # Inline "/v" | "/f": picker rows filtered by the cleaned query
                # (the locked-name inline grammar stays leading-prefix only -
                # render_vf_scope slices the raw bar and can't see cut tokens).
                rows = view_rows(query) if scope == "view" else filter_rows(query)
            else:
                rows = render_vf_scope(scope, raw_query, all_tasks, projects)
            print(alfred.output(rows, skipknowledge=True))
            return

        # ── LA / FO scopes render standalone too ──────────────────────────────
        if scope == "last_added":
            print(alfred.output(last_added_rows(query, all_tasks),
                                skipknowledge=True))
            return
        if scope == "folders":
            print(alfred.output(folder_scope_rows(query), skipknowledge=True))
            return
        # ── PN scope: periodic notes - standalone, config-gated ──────────────
        if scope == "periodic":
            import periodic_rows
            print(alfred.output(periodic_rows.rows(query), skipknowledge=True))
            return

        items = []

        # ── 💫 Periodic keyword rows: "daily note", "weekly"…
        # in the everything or note scopes → the matching open row on top.
        if scope in (None, "note"):
            items += _periodic_keyword_rows(query)

        # Smart lists + filters are searchable like everything else -
        # first in on ties (stable sort), so an exact name beats a task hit.
        # Folders too (their rows only surface when the query matches).
        if scope is None:
            items += view_rows("") + filter_rows("")
            items += [r for r in folder_scope_rows("")
                      if (r.get("uid") or "").startswith("folder-")]

        # ── Lists ─────────────────────────────────────────────────────────────
        for p in (projects if scope in (None, "list", "section") else []):
            pid   = p["id"]
            pname = p.get("name", "Untitled")
            pdata = cache_store.get(f"project_data_{pid}") or {}
            sections = pdata.get("columns", []) or []   # section rows below need these

            # Sub-count: distinct TAGS on the list's open tasks - the count must
            # match what ⌥ drills into here (⌥ = Browse tags on search list
            # rows; sections live on ⌥⇧).
            list_tags = {tag for t in all_tasks
                         if t.get("_projectId") == pid and t.get("status", 0) == 0
                         for tag in (t.get("tags") or [])}
            sub_count   = len(list_tags)
            child_label = "Tag"

            link = f"ticktick:///webapp/#p/{pid}/tasks"

            if scope in (None, "list"):
                items.append(alfred.item(
                    uid=f"list-{pid}",
                    title=pname,
                    subtitle=build_subtitle(sub_count, "List", child_label, actions=True),
                    arg=f"open:{link}",
                    mods={
                        # LIST: Complete / Change Attributes are task-only → suppress
                        # (valid False + blank subtitle so the preview text disappears).
                        "shift":     {"valid": False, "subtitle": ""},
                        "ctrl":      {"valid": True, "arg": "", "subtitle": "🔙 Main menu"},
                        # ⌥ / ⌥⇧ → unified Browse box (ctx rides as a variable
                        # so the search bar stays clean)
                        "alt":       {"arg": "", "subtitle": "Browse tags",
                                      "variables": {"browse_ctx": f"ctx:tags:{pid}"}},
                        "alt+shift": {"arg": "", "subtitle": "Browse sections",
                                      "variables": {"browse_ctx": f"ctx:sections:{pid}"}},
                        "alt+cmd":   {"arg": f"copy:{link}"},
                    },
                    variables={"item_type": "list", "list_id": pid, "search_name": pname, "type_rank": 0},
                ))

            # ── Sections ──────────────────────────────────────────────────────
            if scope in (None, "section"):
                for s in sections:
                    sid   = s["id"]
                    sname = s.get("name", "Untitled")
                    # The "Not Sectioned" pseudo-section never surfaces - same rule as breadcrumbs.
                    if sname.strip().lower() == "not sectioned":
                        continue

                    task_count = sum(1 for t in all_tasks
                                     if t.get("columnId") == sid
                                     and t.get("status", 0) == 0
                                     and not t.get("parentId"))

                    link      = f"ticktick:///webapp/#p/{pid}/tasks/{sid}"
                    list_link = f"ticktick:///webapp/#p/{pid}/tasks"
                    title = f"{sname} | {pname}"

                    items.append(alfred.item(
                        uid=f"section-{sid}",
                        title=title,
                        subtitle=build_subtitle(task_count, "Sect", "Task", actions=True),
                        arg=f"open:{list_link}",   # ⏎ opens the list the section lives in
                        mods={
                            # SECTION: Complete / Change Attributes task-only → suppress.
                            "shift":     {"valid": False, "subtitle": ""},
                            "ctrl":      {"valid": True, "arg": "", "subtitle": "🔙 Main menu"},
                            # ⌥ → unified Browse box (this section's tasks)
                            "alt":       {"arg": "", "subtitle": "Browse tasks",
                                          "variables": {"browse_ctx": f"ctx:tasks:{pid}:{sid}"}},
                            # ⌥⇧ Browse sections is list-only → suppress on a section.
                            "alt+shift": {"valid": False, "subtitle": ""},
                            "alt+cmd":   {"arg": f"copy:{link}"},
                        },
                        variables={
                            "item_type":    "section",
                            "list_id":      pid,
                            "section_id":   sid,
                            "section_name": sname,
                            "search_name":  f"{sname} {pname}",
                            "type_rank":    1,
                        },
                    ))

        # ── Tasks / Subtasks ──────────────────────────────────────────────────
        # t   = top-level tasks only
        # s   = subtasks only (has parentId)
        # ts  = all tasks at any depth
        # none = all tasks at any depth (part of everything)
        if scope in (None, "task", "subtask", "all_tasks", "tag"):
            for t in [t for t in all_tasks if t.get("status", 0) == 0]:
                if t.get("kind") == "NOTE": continue   # notes rendered in their own section
                is_subtask = bool(t.get("parentId"))
                if scope == "task"    and is_subtask:     continue
                if scope == "subtask" and not is_subtask: continue
                if scope == "tag"     and not t.get("tags"): continue  # tag scope: tagged tasks only
                if exact_tag and exact_tag not in [x.lower() for x in (t.get("tags") or [])]:
                    continue   # exact-tag mode: only this tag's tasks

                tid  = t["id"]
                pid  = t.get("projectId") or t.get("_projectId", "")
                name = t.get("title", "Untitled")
                # In tag scope the query matches the task's tags, not its title -
                # except in exact-tag mode, where the tag is fixed and the query
                # goes back to filtering titles.
                ssearch = " ".join(t.get("tags") or []) if scope == "tag" and not exact_tag else name

                breadcrumb = get_task_breadcrumb(t, task_by_id)
                sub_count  = sum(1 for s in all_tasks
                                 if s.get("parentId") == tid and s.get("status", 0) == 0)

                link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

                items.append(alfred.item(
                    title=build_title(t, buffered=tid in buffered_ids()),
                    subtitle=build_subtitle(sub_count, "Task", breadcrumb=breadcrumb, actions=True,
                                            note=note_snippet(t.get("content"))
                                            if t.get("kind") != "NOTE" else ""),
                    arg=f"open:{link}",
                    mods={
                        "cmd":       {"arg": ""},
                        "shift":     {"arg": f"complete:{pid}:{tid}:{name}"},
                        # ⌥ → unified Browse box (this task's subtasks)
                        "alt":       {"arg": "", "subtitle": "Browse subtasks",
                                      "variables": {"browse_ctx": f"ctx:subtasks:{pid}:{tid}"}},
                        # ⌥⇧ → buffer (the router node forwards xact: args to the executor)
                        "alt+shift": {"valid": True,
                                      "arg": f"xact:buffer_add:{pid}:{tid}",
                                      "subtitle": "🅿️ Add to buffer",
                                      "variables": {"task_title": name,
                                                    "task_id": tid,
                                                    "task_list_id": pid,
                                                    "item_type": "task"}},
                        # ⌃⇧ → the ⏱/🍅 start flow
                        "ctrl+shift": {"valid": True,
                                       "arg": f"xact:focus_open:{pid}:{tid}",
                                       "subtitle": "Start focus",
                                       "variables": {"task_title": name,
                                                     "task_id": tid,
                                                     "task_list_id": pid,
                                                     "item_type": "task"}},
                        "alt+cmd":   {"arg": f"copy:{link}"},
                        "ctrl":      {"arg": "", "subtitle": "🔙 Main menu"},
                    },
                    variables={
                        "item_type":    "task",
                        "task_id":      tid,
                        "task_title":   name,
                        "task_list_id": pid,
                        "search_name":  ssearch,
                        "type_rank":    2 + depths.get(tid, 0),
                        "_priority":    t.get("priority") or 0,
                    },
                ))

        # ── Notes ─────────────────────────────────────────────────────────────
        # n  = search by title (title field = note name | folder)
        # nc = search by content (title field = content snippet, subtitle = note name · folder)
        if scope in (None, "note", "note_content", "tag"):
            # Prefer the dedicated all_notes cache (has content for nc search).
            # Fall back to all_tasks filtered by kind=="NOTE" - covers inbox notes
            # and works without a full sync immediately after note creation.
            all_notes = cache_store.get("all_notes") or []
            kind_notes = [t for t in all_tasks if t.get("kind") == "NOTE"]
            # Merge: kind_notes first (always fresh), deduplicated by id
            seen_ids  = {n["id"] for n in kind_notes}
            all_notes = kind_notes + [n for n in all_notes if n["id"] not in seen_ids]
            for n in all_notes:
                nid      = n["id"]
                # Prefer real projectId over _projectId alias ("inbox" alias
                # only works for get_project_data, not task-level API calls)
                npid     = n.get("projectId") or n.get("_projectId", "")
                ntitle   = n.get("title", "Untitled")
                # Display-only: '[name](url)' → '[name]🔗' in titles/snippets;
                # search_name / task_title keep the RAW strings.
                ndisp    = md_links_display(ntitle)
                nfolder  = n.get("_projectName", "")
                ncontent = (n.get("content") or "").strip()
                snippet  = (md_links_display(ncontent[:160]).replace("\n", " ")[:120]
                            if ncontent else "")
                link     = f"ticktick:///webapp/#p/{npid}/tasks/{nid}"

                ntags = n.get("tags") or []
                if scope == "tag" and not ntags:
                    continue   # tag search: only tagged notes
                if exact_tag and exact_tag not in [x.lower() for x in ntags]:
                    continue   # exact-tag mode: only this tag's notes

                if scope == "tag" and exact_tag:
                    # Tag locked → query filters note titles again
                    title       = ndisp
                    subtitle    = build_subtitle(0, "Note", breadcrumb=nfolder, actions=True,
                                                 note=note_snippet(ncontent))
                    search_name = ntitle
                elif scope == "tag":
                    # Tag mode: match the query against the note's tags
                    title       = ndisp
                    subtitle    = build_subtitle(0, "Note", breadcrumb=nfolder, actions=True,
                                                 note=note_snippet(ncontent))
                    search_name = " ".join(ntags)
                elif scope == "note_content":
                    # Content mode: content preview in title, name · folder as breadcrumb
                    title       = snippet if snippet else ndisp
                    crumb       = f"{ndisp}>{nfolder}" if nfolder else ndisp
                    subtitle    = build_subtitle(0, "Note", breadcrumb=crumb, actions=True)
                    search_name = ncontent
                else:
                    # Title mode (default): note name in title, folder as breadcrumb
                    title       = ndisp
                    subtitle    = build_subtitle(0, "Note", breadcrumb=nfolder, actions=True,
                                                 note=note_snippet(ncontent))
                    search_name = f"{ntitle} {nfolder}"

                # Tag chips on note rows, same as task rows get via build_title
                ntag_str = fmt_tags(ntags)
                if ntag_str:
                    title = f"{title} {ntag_str}"

                items.append(alfred.item(
                    uid=f"note-{nid}",
                    title=title,
                    subtitle=subtitle,
                    arg=f"open:{link}",
                    mods={
                        # NOTE: everything but Complete (⇧). No children to browse
                        # from the search view → suppress ⌥/⌥⇧/⌃⇧. ⌃ keeps note details.
                        "shift":      {"valid": False, "subtitle": ""},
                        "alt":        {"valid": False, "subtitle": ""},
                        "alt+shift":  {"valid": False, "subtitle": ""},
                        "ctrl+shift": {"valid": False, "subtitle": ""},
                        "ctrl":       {"arg": "", "subtitle": "🔙 Main menu"},
                        "alt+cmd":    {"arg": f"copy:{link}"},
                    },
                    variables={
                        "item_type":    "note",
                        "task_id":      nid,
                        "task_list_id": npid,
                        "task_title":   ntitle,
                        "search_name":  search_name,
                        "type_rank":    5,
                    },
                ))

        # ── G scope assembly: tag rows lead, tagged items follow ──────────────
        # (own fuzzy pass so tags stay on top; the grouped sort below is for
        # the mixed everything view and would interleave them.)
        tag_scope_assembled = False
        if scope == "tag":
            if query:
                items = fuzz.filter_and_score(
                    query, items,
                    key_fn=lambda x: search_key(x.get("variables", {}).get("search_name", x["title"])),
                )
            if parent_kids is not None:
                items = tag_scope_rows(all_tasks, query, only=parent_kids)
            elif exact_tag is None:
                # Empty fragment → tags only (clean first screen); once the
                # user types, matching tagged items follow the tag rows.
                items = tag_scope_rows(all_tasks, query) + (items if query else [])
            tag_scope_assembled = True

        if query and not tag_scope_assembled:
            items = fuzz.filter_and_score(
                query, items,
                key_fn=lambda x: search_key(x.get("variables", {}).get("search_name", x["title"])),
            )

            # ── Relevance-first sort ──────────────────────────────────────────
            # Match STRENGTH always beats type: exact name → word-start match
            # ("test" in "test ⌘V…" / "Testo") → inside-a-word ("rest" in
            # "interests") → letter-scatter (t…e…s…t across a whole row - the
            # junk that outranked real hits). Within a strength class:
            # List → Task (top-level above subtasks) → Note → Tag → Section
            # (sections are legacy - always last in class). Scatter rows are
            # DROPPED entirely whenever a word-or-better match exists; with no
            # word match they stay (typos still find things). sorted() is
            # stable, so fuzzy order survives within each (strength, type).
            import re as _re
            q = " ".join(query.split()).lower()
            word_re = _re.compile(r'(?:^|[^\w])' + _re.escape(q))
            _ORD = {"list": 0, "view": 0, "filter": 0, "folder": 0, "task": 1,
                    "note": 2, "tag": 3, "section": 4}

            def _annot(x):
                v = x.get("variables", {})
                key = " ".join(search_key(
                    v.get("search_name", x["title"])).split()).lower()
                if key == q:
                    s = 0
                elif word_re.search(key):
                    s = 1
                elif q in key:
                    s = 2
                else:
                    s = 3
                itype = v.get("item_type", "task")
                depth = v.get("type_rank", 2) if itype == "task" else 0
                return (s, _ORD.get(itype, 1), depth, -int(v.get("_priority") or 0))

            ann = {id(x): _annot(x) for x in items}
            if any(a[0] <= 1 for a in ann.values()):
                items = [x for x in items if ann[id(x)][0] < 3]
            items.sort(key=lambda x: ann[id(x)])

        if not items:
            if scope == "tag" and exact_tag:
                msg = f"No open items tagged {fmt_tags([exact_tag]) or '#' + exact_tag}" \
                    + (f' matching "{query}"' if query else "")
            else:
                msg = f'No results matching "{query}"' if query else "No data · run sync first"
            items.append(alfred.item(title=msg, valid=False))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
