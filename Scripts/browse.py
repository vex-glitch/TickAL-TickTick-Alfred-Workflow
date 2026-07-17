#!/usr/bin/env python3
"""
browse.py - Alfred Script Filter (unified browse box)

ONE node renders every level of the browse tree. The whole state rides in $1:

    ctx:<level>[:<id1>[:<id2>]] [query…]

Levels:
    ctx:folders                         folder picker (+ 📥 Inbox row)
    ctx:lists[:<folderId>]              lists - all, or those in a folder
    ctx:sections:<listId>               sections - auto-skips straight to tasks
                                        when the list only has unsectioned content
    ctx:tasks:<listId>[:<sectionId>]    tasks (sectionId may be UNSECTIONED)
    ctx:subtasks:<listId>:<taskId>      children of a task
    ctx:subsubtasks:<listId>:<taskId>   children of a subtask
    ctx:tags:<listId>                   tag picker for a list (drill_tags screen 1)
    ctx:tagitems:<listId>:<tag>         the list's tasks carrying that tag
    ctx:smart:today|tomorrow|next7      smart views ("next7days" accepted too)
    ctx:inbox                           inbox tasks
    ctx:completed                       locally-tracked completed tasks
    ctx:wontdo                          Won't Do (abandoned) tasks
    ctx:crmnew:consult|tattoo|session   CRM records: customer / logbook picker
                                        (⏎ args are xact:crmnew_* dialog verbs)
    ctx:crmdone                         open session tasks - ⏎ complete + log
    ctx:crmlog                          records notes - ⏎ log a line

Anything after the ctx token is the fuzzy filter query. `ctx:subtasks:<taskId>`
(single id) is also accepted - the list is then
resolved from the all_tasks cache.

Every row emits:
    arg         ⏎ meaning per row type (open:<deeplink> → existing OPEN path;
                completed rows keep their ⇧ uncomplete:<…> ride)
    variables   full task context (task_id / task_title / task_list_id /
                list_id / section_id / item_type - same keys the old per-level
                scripts emitted, so the ⌘ Actions rail keeps working)
                + browse_back = ctx of the parent screen (⌃⇧ back loop)
    mods.alt    arg = child ctx (⌥ drill loop); on task rows valid only when
                the task actually has incomplete children

Replaced the old per-level script filters (folders / lists / sections / tasks /
subtasks / subsubtasks / drill_tags / inbox_tasks / smart_list /
completed_list); their rendering logic was copied here.
"""
import sys
import os
import re
import json
import traceback
from datetime import datetime, timedelta, timezone

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
    import config as cfg
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from api import TickTickAPI
    from display import (build_title, build_subtitle, fmt_tags, tag_link,
                         col_lookup, list_name_for, join_breadcrumb, search_key,
                         PRIORITY, MOD_BACK, MODS_COMPLETED, buffered_ids,
                         note_snippet)
    # Smart-list helpers live in src/filtering.py (shared with
    # everything_search's inline views).
    from filtering import (SMART_LABELS, smart_filter, task_local_date,
                           utc_str_to_local_date)
except Exception as e:
    emit_error(f"Import failed: {e} | SRC_DIR={SRC_DIR}")
    sys.exit(0)

# ── Constants ────────────────────────────────────────────────────────────────
INBOX_API_ID = "inbox"   # literal string accepted by the TickTick API

# 🔥CRM (ported from drill_tags.py): on this list's tag screen, ⇧⌘⏎ on a tag
# opens the CRM add pre-tagged, and the tag list is restricted to the 🔥CRM tag
# group.
import areas as _areas
CRM_ID   = _areas.CRM_ID   # Configure panel; empty = CRM branches never match
CRM_TAGS = _areas.CRM_TAGS  # canonical home (Configure-driven, lower form)


# ── ctx parsing ──────────────────────────────────────────────────────────────
def parse_ctx(raw):
    """'ctx:tasks:LID:SID some query' → ('tasks', ['LID','SID'], 'some query').
    A bar without a ctx token falls back to the folders root, whole bar = query."""
    raw = raw or ""
    parts = raw.split(None, 1)
    token = parts[0] if parts else ""
    query = parts[1].strip() if len(parts) > 1 else ""
    # bare aliases let plain menu args ("today") reach the right level
    # without argument-injector nodes
    ALIASES = {"today": "ctx:smart:today", "tomorrow": "ctx:smart:tomorrow",
               "next7days": "ctx:smart:next7", "7days": "ctx:smart:next7",
               "inbox": "ctx:inbox", "completed": "ctx:completed",
               # main-menu view args (▷50F14423 branches)
               "view_today": "ctx:smart:today",
               "view_tomorrow": "ctx:smart:tomorrow",
               "view_7": "ctx:smart:next7", "view_inbox": "ctx:inbox"}
    if token in ALIASES:
        token = ALIASES[token]
    if not token.startswith("ctx:"):
        # No ctx in the bar → context rides invisibly as session variables
        # (browse_ctx set by the ⌥/entry hop, browse_back by the ⌃⇧ hop) and
        # the whole bar is the filter query. Keeps the search bar human-clean.
        env_ctx = os.environ.get("browse_ctx", "") or os.environ.get("browse_back", "")
        env_ctx = ALIASES.get(env_ctx, env_ctx)
        if env_ctx.startswith("ctx:"):
            token, query = env_ctx, raw.strip()
        else:
            return "folders", [], raw.strip()
    bits  = token.split(":")
    level = bits[1] if len(bits) > 1 and bits[1] else "folders"
    ids   = bits[2:]
    return level, ids, query

# ── Data helpers ─────────────────────────────────────────────────────────────
def get_projects():
    data = cache_store.get("projects")
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_projects()
        cache_store.set("projects", data)
    return sorted(
        [p for p in data if p.get("kind") != "SMART_LIST"],
        key=lambda p: p.get("sortOrder", 0)
    )

def get_project_data(list_id):
    cache_key = f"project_data_{list_id}"
    data = cache_store.get(cache_key)
    # Inbox tasks carry their real projectId ("inbox…") but the cache is keyed
    # by the literal "inbox" - fall back before hitting the API.
    if data is None and list_id.startswith("inbox"):
        data = cache_store.get("project_data_inbox")
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(list_id)
        cache_store.set(cache_key, data)
    return data

def get_sections(list_id):
    return sorted(
        (get_project_data(list_id) or {}).get("columns", []),
        key=lambda s: s.get("sortOrder", 0)
    )

def find_inbox_id():
    """Inbox project id from the projects cache, else from a cached inbox task."""
    for p in (cache_store.get("projects") or []):
        if p.get("kind") == "INBOX" or (
            p.get("name", "").lower() == "inbox" and not p.get("groupId")
        ):
            return p["id"]
    inbox_data = cache_store.get("project_data_inbox") or {}
    for t in inbox_data.get("tasks", []):
        if t.get("projectId"):
            return t["projectId"]
    return ""

def _unsectioned_col(sections):
    return next(
        (s for s in sections
         if "not" in s.get("name", "").lower() and "section" in s.get("name", "").lower()),
        None
    )

def _child_count(all_tasks, tid):
    return sum(1 for s in all_tasks
               if s.get("parentId") == tid and s.get("status", 0) == 0)

def tag_counts(all_tasks):
    """Distinct tags among incomplete top-level tasks → {tag: count}."""
    counts = {}
    for t in all_tasks:
        if t.get("status", 0) != 0 or t.get("parentId"):
            continue
        for tag in (t.get("tags") or []):
            counts[tag] = counts.get(tag, 0) + 1
    return counts

def _tag_rank():
    """Tag name (lower) → position in TickTick's OWN tag order (v2 tags_tree
    sortOrder - the deliberate order that drives the app's group-by-tag
    sections). Falls back to the tags cache order when the tree is absent
    (no v2 token)."""
    tree = cache_store.get("tags_tree") or []
    if tree:
        names = [t.get("name", "") for t in
                 sorted(tree, key=lambda t: t.get("sortOrder") or 0)]
    else:
        names = [str(t) for t in (cache_store.get("tags") or [])]
    return {n.lower(): i for i, n in enumerate(names) if n}

def _tag_group_key(task, rank):
    """Clusters tasks by their best-ranked tag: known tags in TickTick order,
    unknown tags alphabetically after them, untagged last."""
    tags = [x.lower() for x in (task.get("tags") or [])]
    if not tags:
        return (2, 0, "")
    best = min(tags, key=lambda x: (rank.get(x, len(rank)), x))
    return (0, rank[best], "") if best in rank else (1, 0, best)

def _sort_tasks(tasks, group_by_tag=False):
    """Priority floats to the top of every drill view; the
    whole-list 'Show all' view additionally groups by tag. Stable sorts -
    cache order survives inside each band, and a typed query's fuzzy scoring
    still wins (this order is its tiebreak)."""
    tasks.sort(key=lambda t: -(t.get("priority") or 0))
    if group_by_tag:
        rank = _tag_rank()
        tasks.sort(key=lambda t: _tag_group_key(t, rank))
    return tasks

def _show_all_row(list_id, all_tasks, uid="tag-all"):
    """Top row of the tag/section drill screens: ⏎ rewrites
    the bar to the 'all ' sentinel - the whole list flat, grouped by tag,
    priority first. ⌥⏎ does the same through a proper ctx hop."""
    n_open = sum(1 for t in all_tasks
                 if t.get("status", 0) == 0 and not t.get("parentId"))
    return alfred.item(
        uid=uid,
        title="📋 Show all tasks",
        subtitle=f"{n_open} Tasks by tag, priority first",
        arg="", valid=False, autocomplete="all ",
        mods={"alt": {"arg": "", "valid": True, "subtitle": "Show all tasks",
                      "variables": {"browse_ctx": f"ctx:tasks:{list_id}"}}},
        variables={"list_id": list_id, "task_list_id": list_id},
    )

def fmt_completed_time(task):
    """'DD/MM/YYYY HH:MM' from completedTime (ported from completed_list.py)."""
    ct = task.get("completedTime", "")
    if not ct:
        return "unknown date"
    try:
        clean  = ct[:19]
        dt_utc = datetime(
            int(clean[0:4]), int(clean[5:7]),  int(clean[8:10]),
            int(clean[11:13]), int(clean[14:16]), int(clean[17:19]),
            tzinfo=timezone.utc,
        )
        return dt_utc.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ct[:10]

# ── Parent-ctx computation (browse_back) ─────────────────────────────────────
def group_of(list_id):
    for p in (cache_store.get("projects") or []):
        if p.get("id") == list_id:
            return p.get("groupId") or ""
    return ""

def lists_parent(list_id):
    """The list-picker screen this list belongs to."""
    gid = group_of(list_id)
    return f"ctx:lists:{gid}" if gid else "ctx:lists"

def tasks_parent(list_id, section_id):
    """Where ⌃⇧ goes from a tasks screen: the section picker if the list has
    one, otherwise straight up to the list picker (mirrors the auto-skip)."""
    if section_id:
        return f"ctx:sections:{list_id}"
    sections = get_sections(list_id)
    if len(sections) == 0 or (len(sections) == 1 and _unsectioned_col(sections)):
        return lists_parent(list_id)
    return f"ctx:sections:{list_id}"

def add_back(items, back):
    """Stamp the ⌃ back mod + browse_back onto every row (empty-state rows
    included) so the ⌃ → R:emit-back → back-router loop always knows where up
    is. The ⌃ mod carries its OWN variables (mod vars REPLACE item vars): it
    must RESET browse_ctx - the ⌥ drill hop plants it as a session variable,
    and a stale value otherwise outranks browse_back in parse_ctx, re-rendering
    the same screen (the childless-drill "back does nothing" bug)."""
    for it in items:
        mods = it.setdefault("mods", {})
        ctrl = mods.get("ctrl") or {"subtitle": "🔙 Back"}
        ctrl["valid"] = True
        ctrl["arg"] = ""
        ctrl["variables"] = {"browse_ctx": "", "browse_back": back}
        mods["ctrl"] = ctrl
        it.setdefault("variables", {})["browse_back"] = back
    return items

# ── Shared task-row builder ──────────────────────────────────────────────────
def task_item(t, pid, sub_count, breadcrumb="", uid="", child_level="subtasks"):
    """Canonical task row (tasks.py rendering): build_title + actions subtitle,
    ⏎ open, ⇧ complete, ⌥ drill ctx (valid only with children), ⌥⌘ copy."""
    tid  = t["id"]
    name = t.get("title", "Untitled")
    link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"
    is_note = t.get("kind") == "NOTE"
    mods = {
        "cmd":     {"arg": "", "subtitle": "⌘ Actions"},
        "shift":   {"arg": f"complete:{pid}:{tid}:{name}", "subtitle": "Complete"},
        "alt":     {"arg": "", "subtitle": "Browse subtasks",
                    "valid": bool(sub_count),
                    "variables": {"browse_ctx": f"ctx:{child_level}:{pid}:{tid}"}},
        "alt+cmd": {"arg": f"copy:{link}", "subtitle": "Copy link"},
        "ctrl":    {"valid": True, "subtitle": "🔙 Back"},
    }
    if not is_note:
        # ⌥⇧ → buffer (tasks/subtasks only; X1 routes xact: args)
        mods["alt+shift"] = {"valid": True,
                             "arg": f"xact:buffer_add:{pid}:{tid}",
                             "subtitle": "🅿️ Add to buffer",
                             "variables": {"task_title": name, "task_id": tid,
                                           "task_list_id": pid,
                                           "item_type": "task"}}
    return alfred.item(
        uid=uid,
        title=build_title(t, buffered=tid in buffered_ids()),
        subtitle=build_subtitle(sub_count, breadcrumb=breadcrumb, actions=True,
                                buffer_mod=not is_note,
                                note="" if is_note else note_snippet(t.get("content"))),
        arg=f"open:{link}",
        mods=mods,
        # item_type is load-bearing: without it actions.py falls back to its
        # pid-present→"list" guess and serves the container menu (the CRM bug).
        variables={"task_id": tid, "task_title": name, "task_list_id": pid,
                   "item_type": "note" if is_note else "task"},
    )

def filter_task_items(query, items):
    return fuzz.filter_and_score(
        query, items,
        key_fn=lambda x: search_key(x.get("variables", {}).get("task_title", x["title"]))
    )

# ── Level: folders ───────────────────────────────────────────────────────────
def render_folders(query):
    items    = []
    folders  = cfg.get_folders()  # {groupId: name}
    projects = cache_store.get("projects") or []

    # ── Inbox (special: ⌥ drills directly to tasks - the old Inbox-skip
    #    conditional 42264365, now in-script) ───────────────────────────────
    inbox_id   = find_inbox_id()
    inbox_data = cache_store.get("project_data_inbox") or {}
    inbox_count = sum(1 for t in inbox_data.get("tasks", [])
                      if t.get("status", 0) == 0 and not t.get("parentId"))
    inbox_link = f"ticktick:///webapp/#p/{inbox_id}/tasks" if inbox_id else ""

    items.append(alfred.item(
        title="📥 Inbox",
        subtitle=build_subtitle(inbox_count, child_label="Task", actions=True),
        arg=f"open:{inbox_link}" if inbox_link else "",
        mods={
            "alt": {"arg": "", "valid": True, "subtitle": "Browse Inbox tasks",
                    "variables": {"browse_ctx": "ctx:inbox"}},
            "cmd": {"valid": False, "subtitle": ""},
        },
        variables={"list_id": inbox_id or "", "list_name": "Inbox", "folder_id": "",
                   "item_type": "list"},
    ))

    # ── Folders from config ───────────────────────────────────────────────
    if not folders:
        items.append(alfred.item(
            title="No folders configured",
            subtitle="Attachment Login in Settings auto-names folders",
            valid=False,
        ))
    else:
        def _folder_order(name):
            """Extract (sort_int, clean_name) from strict '1) Name' prefix."""
            m = re.match(r'^(\d+)\)\s(.+)$', name.strip())
            if m:
                return int(m.group(1)), m.group(2).strip()
            return 9999, name.strip()

        # Manual "1) Name" prefixes rank first; unprefixed (v2 auto-named)
        # folders follow in TickTick's own sidebar order (group sortOrder);
        # folders with no live group (tokenless installs, ghosts of deleted
        # groups) sink below the autos in insertion order - the original
        # rendering for tokenless users.
        v2_order = {g.get("id"): (g.get("sortOrder") or 0)
                    for g in (cache_store.get("folder_groups") or [])}
        pos = {gid: i for i, gid in enumerate(folders)}
        sorted_folders = sorted(
            folders.items(),
            key=lambda kv: (_folder_order(kv[1])[0],
                            v2_order.get(kv[0], float("inf")),
                            pos[kv[0]]))

        for group_id, raw_name in sorted_folders:
            _, clean = _folder_order(raw_name)
            list_count = sum(1 for p in projects
                             if p.get("groupId") == group_id and p.get("kind") != "SMART_LIST")
            items.append(alfred.item(
                uid=f"folder-{group_id}",
                title=clean,
                subtitle=build_subtitle(list_count, child_label="List", actions=True),
                arg="",
                mods={
                    "alt": {"arg": "", "valid": True, "subtitle": "Browse lists",
                            "variables": {"browse_ctx": f"ctx:lists:{group_id}"}},
                    # Actions can't handle folder context yet - dead ⌘ here
                    # would otherwise fire the junction and crash actions.py.
                    "cmd": {"valid": False, "subtitle": ""},
                    "alt+cmd": {"arg": f"copy:{group_id}",
                                "subtitle": "Copy folder id"},
                },
                variables={"folder_id": group_id, "folder_name": clean,
                           "item_type": "folder"},
            ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items = [alfred.item(
            uid="no-results",
            title=f'No folders matching "{query}"',
            valid=False,
        )]

    return add_back(items, "")   # root - no parent inside browse

# ── Level: lists ─────────────────────────────────────────────────────────────
def render_lists(folder_id, query):
    all_projects = get_projects()
    projects = ([p for p in all_projects if p.get("groupId") == folder_id]
                if folder_id else all_projects)

    all_tasks = cache_store.get("all_tasks") or []
    items = []
    for p in projects:
        pid  = p["id"]
        name = p["name"]
        link = f"ticktick:///webapp/#p/{pid}/tasks"

        # Sub-count: distinct TAGS on the list's open tasks - the count must
        # match what ⌥ drills into. Browse and search agree: ⌥ tags ·
        # ⌥⇧ sections on both.
        list_tags = {tag for t in all_tasks
                     if t.get("_projectId") == pid and t.get("status", 0) == 0
                     for tag in (t.get("tags") or [])}

        items.append(alfred.item(
            uid=f"list-{pid}",
            title=name,
            subtitle=build_subtitle(len(list_tags), child_label="Tag", actions=True),
            arg=f"open:{link}",
            mods={
                "cmd":       {"arg": "", "subtitle": "⌘ Actions"},
                "alt":       {"arg": "", "valid": True, "subtitle": "Browse tags",
                              "variables": {"browse_ctx": f"ctx:tags:{pid}"}},
                "alt+shift": {"arg": "", "valid": True, "subtitle": "Browse sections",
                              "variables": {"browse_ctx": f"ctx:sections:{pid}"}},
                "alt+cmd":   {"arg": f"copy:{link}", "subtitle": "Copy link"},
            },
            variables={"item_type": "list", "list_id": pid, "list_name": name,
                       "folder_id": folder_id},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items.append(alfred.item(
            uid="no-results",
            title=f'No lists matching "{query}"' if query else
                  ("No lists in this folder" if folder_id else "No lists · run Sync first"),
            valid=False,
        ))

    return add_back(items, "ctx:folders")

# ── Level: sections ──────────────────────────────────────────────────────────
def render_sections(list_id, query):
    data       = get_project_data(list_id) or {}
    sections   = get_sections(list_id)
    all_tasks  = data.get("tasks", [])
    column_ids = {s["id"] for s in sections}
    list_name  = list_name_for(list_id, cache_store.get("projects") or []) or "List"

    orphaned = [t for t in all_tasks
                if not t.get("parentId")
                and t.get("status", 0) == 0
                and (not t.get("columnId") or t.get("columnId") not in column_ids)]

    unsectioned_col = _unsectioned_col(sections)

    # ── Auto-skip: only unsectioned content → render tasks directly ─────────
    only_unsectioned = (
        len(sections) == 0 or
        (len(sections) == 1 and unsectioned_col is not None)
    )
    if only_unsectioned:
        sid = unsectioned_col["id"] if unsectioned_col else "UNSECTIONED"
        return render_tasks(list_id, sid, query, back_override=lists_parent(list_id))

    # "all " sentinel: ⏎ on the 📋 Show-all row rewrites the bar -
    # the whole list renders flat, grouped by tag; anything after the token
    # filters it. Human-readable advance, same idea as "#Tag ".
    if query == "all" or query.startswith("all "):
        return render_tasks(list_id, "", query[3:].strip(),
                            back_override=f"ctx:sections:{list_id}")

    # ── Normal section picker ────────────────────────────────────────────────
    items = [_show_all_row(list_id, all_tasks, uid="section-all")]

    if orphaned and unsectioned_col is None:
        items.append(alfred.item(
            uid="unsectioned",
            title="Not sectioned",
            subtitle=build_subtitle(len(orphaned), child_label="Task", actions=True),
            arg="",
            mods={
                "alt": {"arg": "", "valid": True, "subtitle": "Browse tasks",
                        "variables": {"browse_ctx": f"ctx:tasks:{list_id}:UNSECTIONED"}},
            },
            variables={"item_type": "section", "list_id": list_id, "task_list_id": list_id,
                       "section_id": "UNSECTIONED", "section_name": "Not sectioned",
                       "folder_id": group_of(list_id)},
        ))

    for s in sections:
        sid   = s["id"]
        sname = s.get("name", "Unnamed Section")
        section_link = f"ticktick:///webapp/#p/{list_id}/tasks/{sid}"
        list_link    = f"ticktick:///webapp/#p/{list_id}/tasks"

        is_unsectioned_col = "not" in sname.lower() and "section" in sname.lower()

        task_count = sum(1 for t in all_tasks
                         if t.get("columnId") == sid
                         and not t.get("parentId")
                         and t.get("status", 0) == 0)
        if is_unsectioned_col:
            task_count += len(orphaned)

        items.append(alfred.item(
            uid=f"section-{sid}",
            title=sname,
            subtitle=build_subtitle(task_count, child_label="Task", actions=True),
            arg=f"open:{list_link}",
            mods={
                "cmd":     {"arg": "", "subtitle": "⌘ Actions"},
                "alt":     {"arg": "", "valid": True, "subtitle": "Browse tasks",
                            "variables": {"browse_ctx": f"ctx:tasks:{list_id}:{sid}"}},
                "alt+cmd": {"arg": f"copy:{section_link}", "subtitle": "Copy link"},
            },
            variables={"item_type": "section", "list_id": list_id, "task_list_id": list_id,
                       "section_id": sid, "section_name": sname,
                       "folder_id": group_of(list_id)},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items and query:
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items.append(alfred.item(
            uid="no-results",
            title=f'No sections matching "{query}"',
            subtitle=MOD_BACK,
            arg=f"open:{list_link}",
            valid=True,
            variables={"list_id": list_id, "list_name": list_name,
                       "folder_id": group_of(list_id)},
        ))

    return add_back(items, lists_parent(list_id))

# ── Level: tasks ─────────────────────────────────────────────────────────────
def render_tasks(list_id, section_id, query, back_override=None):
    data           = get_project_data(list_id) or {}
    all_tasks      = data.get("tasks", [])
    col_name_by_id = col_lookup(data)
    column_ids     = set(col_name_by_id.keys())
    lname          = list_name_for(list_id, cache_store.get("projects") or [])

    if section_id == "UNSECTIONED":
        section_name = "Not sectioned"
    else:
        section_name = col_name_by_id.get(section_id, "") if section_id else ""

    # Filter to section if one was chosen
    if section_id == "UNSECTIONED":
        tasks = [t for t in all_tasks
                 if not t.get("columnId") or t.get("columnId") not in column_ids]
    elif section_id:
        tasks = [t for t in all_tasks if t.get("columnId") == section_id]
        if "not" in section_name.lower() and "section" in section_name.lower():
            orphaned = [t for t in all_tasks
                        if not t.get("columnId") or t.get("columnId") not in column_ids]
            seen = {t["id"] for t in tasks}
            tasks = tasks + [t for t in orphaned if t["id"] not in seen]
    else:
        tasks = all_tasks

    # Only incomplete top-level tasks
    tasks = [t for t in tasks if t.get("status", 0) == 0 and not t.get("parentId")]
    # Priority first everywhere; the section-less whole-list view also groups
    # by tag in TickTick's own tag order.
    _sort_tasks(tasks, group_by_tag=not section_id)

    items = []
    for t in tasks:
        if section_id and section_id != "UNSECTIONED":
            bc_section = section_name
        else:
            bc_section = col_name_by_id.get(t.get("columnId") or "", "")
        items.append(task_item(
            t, list_id, _child_count(all_tasks, t["id"]),
            breadcrumb=join_breadcrumb(lname, bc_section),
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        label = section_name or "this list"
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items.append(alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {label}",
            subtitle=MOD_BACK,
            arg=f"open:{list_link}",
            valid=True,
            variables={"task_list_id": list_id, "list_id": list_id,
                       "section_id": section_id},
        ))

    back = back_override if back_override is not None else tasks_parent(list_id, section_id)
    return add_back(items, back)

# ── Levels: subtasks / subsubtasks ───────────────────────────────────────────
def render_children(list_id, task_id, query, level):
    data           = get_project_data(list_id) or {}
    all_tasks      = data.get("tasks", [])
    col_name_by_id = col_lookup(data)
    lname          = list_name_for(list_id, cache_store.get("projects") or [])
    task_by_id     = {t["id"]: t for t in all_tasks}
    parent         = task_by_id.get(task_id)
    parent_title   = (parent or {}).get("title", "task")

    # Breadcrumb: List>Section(top ancestor)>…ancestor titles…>parent title
    # (walks the parent chain - matches subtasks.py at depth 1 and
    #  subsubtasks.py at depth 2, and keeps working below that).
    chain, cur, seen = [], parent, set()
    while cur and cur["id"] not in seen and len(chain) < 6:
        seen.add(cur["id"])
        chain.append(cur)
        cur = task_by_id.get(cur.get("parentId") or "")
    top      = chain[-1] if chain else None
    top_col  = col_name_by_id.get((top or {}).get("columnId") or "", "")
    titles   = [c.get("title", "") for c in reversed(chain)]
    breadcrumb = join_breadcrumb(lname, top_col, *titles)

    children = [t for t in all_tasks
                if t.get("parentId") == task_id and t.get("status", 0) == 0]

    items = []
    for t in children:
        items.append(task_item(
            t, list_id, _child_count(all_tasks, t["id"]),
            breadcrumb=breadcrumb,
            child_level="subsubtasks",
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        link = f"ticktick:///webapp/#p/{list_id}/tasks/{task_id}"
        items.append(alfred.item(
            title=f'No subtasks matching "{query}"' if query else f'No subtasks in "{parent_title}"',
            subtitle=MOD_BACK,
            arg=f"open:{link}",
            valid=True,
            variables={"task_id": task_id, "task_title": parent_title,
                       "task_list_id": list_id},
        ))

    if level == "subsubtasks":
        gp_id = (parent or {}).get("parentId") or ""
        back = f"ctx:subtasks:{list_id}:{gp_id}" if gp_id else f"ctx:tasks:{list_id}"
    else:
        back = f"ctx:tasks:{list_id}"
    return add_back(items, back)

# ── Level: tags (drill_tags screen 1) ────────────────────────────────────────
def render_tags(list_id, query):
    all_tasks = (get_project_data(list_id) or {}).get("tasks", [])
    counts    = tag_counts(all_tasks)

    # ⏎ on a tag row autocompletes "#<Tag> " - a human-readable advance (keeps
    # raw ctx: tokens out of the bar). An exact #tag token renders that tag's
    # tasks; anything after it filters them.
    if query.startswith("#"):
        head, _, rest = query[1:].partition(" ")
        match = next((t for t in counts if t.lower() == head.lower()), None)
        if match:
            return render_tagitems(list_id, match, rest.strip())

    # "all " sentinel - the 📋 Show-all top row's advance (see _show_all_row)
    if query == "all" or query.startswith("all "):
        return render_tasks(list_id, "", query[3:].strip(),
                            back_override=f"ctx:tags:{list_id}")

    items = [_show_all_row(list_id, all_tasks)]
    for tag in sorted(counts):
        if CRM_ID and list_id == CRM_ID and tag.lower() not in CRM_TAGS:
            continue   # CRM search surfaces only the 🔥CRM tag group
        item = alfred.item(
            uid=f"tag-{tag}",
            title=fmt_tags([tag]) or f"#{tag}",
            subtitle=build_subtitle(counts[tag], child_label="Task", actions=True),
            arg="", valid=False,
            # ⏎ → advance to this tag's tasks. The bar gets a human-readable
            # "#Tag " (parsed back above) - never a raw ctx: token.
            autocomplete=f"{fmt_tags([tag]) or '#' + tag} ",
            mods={
                "alt": {"arg": "", "valid": True, "subtitle": "Browse this tag's tasks",
                        "variables": {"browse_ctx": f"ctx:tagitems:{list_id}:{tag}"}},
                # Real ⌘ Actions for tags (open tag / copy link / back)
                "cmd": {"arg": "", "valid": True, "subtitle": "⌘ Actions"},
                "alt+cmd": {"arg": f"copy:{tag_link(tag)}", "valid": True,
                            "subtitle": "Copy tag link"},
            },
            variables={"list_id": list_id, "task_list_id": list_id,
                       "item_type": "tag", "tag_name": tag},
        )
        # 🔥CRM: ⇧⌘⏎ on a tag opens the CRM add pre-tagged (booking flow).
        # Ported from the old tag-drill screen.
        if CRM_ID and list_id == CRM_ID:
            item["mods"]["cmd+shift"] = {
                "arg": "add", "valid": True,
                "subtitle": f"Add 🔥CRM booking tagged {fmt_tags([tag]) or '#'+tag}",
                "variables": {"list_id": CRM_ID, "task_list_id": CRM_ID,
                              "list_name": _areas.crm_list_name(),
                              "prefill_tag": tag, "item_type": "list"},
            }
        items.append(item)

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        # Typing on a tag screen also filters the list's tasks
        # directly - matching tasks follow the tag rows, so the CRM search
        # works without picking a tag first. Clearing the query brings back
        # the pure tag list.
        data           = get_project_data(list_id) or {}
        col_name_by_id = col_lookup(data)
        lname          = list_name_for(list_id, cache_store.get("projects") or [])
        pool = _sort_tasks([t for t in all_tasks
                            if t.get("status", 0) == 0 and not t.get("parentId")])
        task_rows = [task_item(
            t, list_id, _child_count(all_tasks, t["id"]),
            breadcrumb=join_breadcrumb(lname, col_name_by_id.get(t.get("columnId") or "", "")),
        ) for t in pool]
        items += filter_task_items(query, task_rows)

    if not items:
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items = [alfred.item(
            title=f'No tags or tasks matching "{query}"' if query else "No tags in this list",
            subtitle=MOD_BACK, arg=f"open:{list_link}", valid=True,
            variables={"list_id": list_id, "task_list_id": list_id},
        )]

    return add_back(items, lists_parent(list_id))

# ── Level: tagitems (drill_tags screen 2) ────────────────────────────────────
def render_tagitems(list_id, tag, query):
    data           = get_project_data(list_id) or {}
    all_tasks      = data.get("tasks", [])
    col_name_by_id = col_lookup(data)
    lname          = list_name_for(list_id, cache_store.get("projects") or [])

    tasks = [t for t in all_tasks
             if t.get("status", 0) == 0 and not t.get("parentId")
             and tag in (t.get("tags") or [])]
    _sort_tasks(tasks)

    items = []
    for t in tasks:
        bc_section = col_name_by_id.get(t.get("columnId") or "", "")
        items.append(task_item(
            t, list_id, _child_count(all_tasks, t["id"]),
            breadcrumb=join_breadcrumb(lname, bc_section),
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        list_link = f"ticktick:///webapp/#p/{list_id}/tasks"
        items = [alfred.item(
            title=f'No tasks tagged {tag}' + (f' matching "{query}"' if query else ""),
            subtitle=MOD_BACK, arg=f"open:{list_link}", valid=True,
            variables={"list_id": list_id, "task_list_id": list_id},
        )]

    return add_back(items, f"ctx:tags:{list_id}")

# ── Levels: crmnew / crmdone / crmlog (CRM records pickers) ──────────────────
# The tcr rows route here with arg "tags" + a browse_ctx variable (riding the
# CRM conditional's BROWSE branch - zero canvas). Row ⏎ args are xact:* verbs:
# the Open ⏎ junction's modOpen runscript passes any xact:* through to xact.py,
# where the dialog chains live (see crm_records.py for the data model).
def _records_gate():
    """Setup row when crm_records_list_id is unset - or None when good to go."""
    if not _areas.records_configured():
        return [alfred.item(**_areas.setup_row("CRM records", "47-crm.md"))]
    return None


def _record_vars(note):
    return {"task_id": note["id"], "task_list_id": _areas.RECORDS_ID,
            "list_id": _areas.RECORDS_ID, "task_title": note.get("title") or "",
            "item_type": "note"}


def _picker_mods(subtitle="⏎ picks here"):
    """Explicit mod stamps for picker rows: ⌘ Actions stays live (item vars
    carry the note/task context), the other chords are pinned dead so a
    stray ⇧/⌥ press can't fire the row's xact arg down the wrong canvas edge."""
    return {
        "cmd":     {"arg": "", "valid": True,  "subtitle": "⌘ Actions"},
        "shift":   {"arg": "", "valid": False, "subtitle": subtitle},
        "alt":     {"arg": "", "valid": False, "subtitle": subtitle},
        "alt+cmd": {"arg": "", "valid": False, "subtitle": subtitle},
    }


def render_crmnew(kind, query):
    """Customer picker for a new consultation/tattoo entry (kind=consult|
    tattoo), or the open-logbook picker for the next session (kind=session)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "")
    import crm_records as cr

    if kind == "session":
        rows = []
        for lb in cr.records_notes(_areas.LOGBOOK_TAG):
            n = cr.next_snum(lb.get("content") or "", lb["id"])
            rows.append(alfred.item(
                uid=f"crmnew-s-{lb['id']}",
                title=lb.get("title") or "Untitled",
                subtitle=f"⏎ Schedule S{n}",
                arg=f"xact:crmnew_go:session::{lb['id']}",
                mods=_picker_mods(),
                variables=_record_vars(lb),
            ))
        if query:
            rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No open logbooks",
                                subtitle="➕ New tattoo starts one", valid=False)]
        return add_back(rows, "")

    label = "consultation" if kind == "consult" else "tattoo"
    new_row = alfred.item(
        uid="crmnew-newcust",
        title="➕ New customer",
        subtitle=f"Dialogs ask name + contact, then the {label}",
        arg=f"xact:crmnew_newcust:{kind}",
    )
    rows = [new_row]
    for c in cr.records_notes(_areas.CUSTOMER_TAG):
        rows.append(alfred.item(
            uid=f"crmnew-c-{c['id']}",
            title=c.get("title") or "Untitled",
            subtitle=f"⏎ New {label} for this customer",
            arg=f"xact:crmnew_go:{kind}:{c['id']}",
            mods=_picker_mods(),
            variables=_record_vars(c),
        ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"]) \
            or [new_row]   # no matching customer → they're new
    return add_back(rows, "")


def render_crmdone(query):
    """Open calendar tasks that link a logbook - ⏎ completes + logs (dialogs)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "")
    import crm_records as cr

    def _day(t):
        due = t.get("dueDate") or t.get("startDate") or ""
        return utc_str_to_local_date(due) if due else ""

    pool = []
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) == CRM_ID
                and t.get("status", 0) == 0
                and cr.is_session_task(t.get("title") or "")):
            pool.append(t)
    pool.sort(key=lambda t: _day(t) or "9999")   # soonest first, dateless last

    rows = []
    for t in pool:
        disp = cr.LINK_RE.sub(r"\1", t.get("title") or "")
        rows.append(alfred.item(
            uid=f"crmdone-{t['id']}",
            title=f"✅ {disp}",
            subtitle=f"📅 {_day(t) or 'Not scheduled'} · ⏎ Complete + log",
            arg=f"xact:sessiondone:{CRM_ID}:{t['id']}",
            mods=_picker_mods("⏎ completes + logs it properly"),
            variables={"task_id": t["id"], "task_list_id": CRM_ID,
                       "list_id": CRM_ID, "task_title": t.get("title") or "",
                       "item_type": "task"},
        ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title="No open session tasks",
                            subtitle="➕ New consultation / tattoo creates them",
                            valid=False)]
    return add_back(rows, "")


def render_crmlog(query):
    """Every records note (customers, logbooks, archive) - ⏎ logs a line."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "")
    import crm_records as cr

    rows, seen = [], set()
    for tag in (_areas.CUSTOMER_TAG, _areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG):
        for n in cr.records_notes(tag):
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            chip = " · archived" if tag == _areas.ARCHIVE_TAG else ""
            rows.append(alfred.item(
                uid=f"crmlog-{n['id']}",
                title=n.get("title") or "Untitled",
                subtitle=f"⏎ Log a line{chip}",
                arg=f"xact:crmlog:{n['id']}",
                mods=_picker_mods(),
                variables=_record_vars(n),
            ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title="No records notes yet",
                            subtitle="➕ New consultation / tattoo creates them",
                            valid=False)]
    return add_back(rows, "")


# ── Level: buffer (🅿️ - tasks collected via ⌘/⌥⇧) ───────────────────────────
def render_buffer(query):
    try:
        with open(run_path("tickal_buffer.txt")) as f:
            pairs = [ln.strip().split(":", 1) for ln in f if ln.strip()]
    except OSError:
        pairs = []
    all_tasks = cache_store.get("all_tasks") or []
    by_id = {t["id"]: t for t in all_tasks}
    items = []
    for pid, tid in pairs:
        t = by_id.get(tid)
        if not t:
            continue   # stray (completed/deleted since buffering) - skip
        it = task_item(t, pid, _child_count(all_tasks, tid),
                       breadcrumb=t.get("_projectName", ""), uid=f"buf-{tid}")
        it["variables"]["item_type"] = "buffer_item"   # ⌘ → batch menu
        items.append(it)
    if query:
        items = filter_task_items(query, items)
    if not items:
        items = [alfred.item(title="🅿️ Buffer is empty",
                             subtitle="⌥⇧🅿️ or ⌘⚡ on any task",
                             valid=False)]
    return add_back(items, "ctx:folders")

# ── Level: smart (today / tomorrow / next7days) ──────────────────────────────
def render_smart(kind, query):
    if kind in ("next7", "7", "next7d"):
        kind = "next7days"
    all_tasks = cache_store.get("all_tasks") or []
    tasks     = smart_filter(all_tasks, kind)
    label     = SMART_LABELS.get(kind, kind)

    items = []
    for t in tasks:
        pid = t.get("_projectId", t.get("projectId", ""))
        items.append(task_item(
            t, pid, _child_count(all_tasks, t["id"]),
            breadcrumb=join_breadcrumb(t.get("_projectName", ""), t.get("_columnName", "")),
            uid=f"task-{t['id']}",
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        items.append(alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {label}",
            valid=False,
        ))

    # ↗️ Open the smart list in TickTick as the FIRST row - parity with search's
    # inline view. The tod/tom/tne keywords + Today/Tomorrow/Next-7 hotkeys land
    # here and previously offered no "open in TickTick" action, only the rows.
    _deeplink = {"today":     "ticktick://v1/show?smartlist=today",
                 "tomorrow":  "ticktick://v1/show?smartlist=tomorrow",
                 "next7days": "ticktick://v1/show?smartlist=next_7_days"}.get(kind)
    if _deeplink:
        items.insert(0, alfred.item(
            uid=f"smart-open-{kind}",
            title=f"↗️ Open {label} in TickTick",
            subtitle="Smart list  |  ⏎↗️",
            arg=f"open:{_deeplink}",
            valid=True,
        ))

    return add_back(items, "")

# ── Level: inbox ─────────────────────────────────────────────────────────────
def render_inbox(query):
    cache_key = "project_data_inbox"
    data = cache_store.get(cache_key)
    if data is None:
        data = TickTickAPI(cfg.get_token()).get_project_data(INBOX_API_ID)
        cache_store.set(cache_key, data)
    all_tasks = data.get("tasks", [])

    tasks = [t for t in all_tasks if t.get("status", 0) == 0 and not t.get("parentId")]

    items = []
    for t in tasks:
        real_pid = t.get("projectId", INBOX_API_ID)
        items.append(task_item(
            t, real_pid, _child_count(all_tasks, t["id"]),
            breadcrumb="Inbox",
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        items.append(alfred.item(
            title=f'No tasks matching "{query}"' if query else "Inbox is empty",
            valid=False,
        ))

    return add_back(items, "")

# ── Level: completed ─────────────────────────────────────────────────────────
def render_completed(query):
    tasks = cache_store.get("completed_tasks") or []

    items = []
    for t in tasks:
        tid  = t.get("id", "")
        pid  = t.get("_projectId", t.get("projectId", ""))
        name = t.get("title", "Untitled")

        priority_dot = PRIORITY.get(t.get("priority", 0), "⚫️")
        tags         = t.get("tags") or []
        tag_str      = " # " + " ".join(tags) if tags else ""

        breadcrumb = join_breadcrumb(t.get("_projectName", ""), t.get("_columnName", ""))

        subtitle_parts = [f"✅ {fmt_completed_time(t)}"]
        if breadcrumb:
            subtitle_parts.append(breadcrumb)
        subtitle_parts.append("|")   # the house '  |  ' before the legend
        subtitle_parts.append(MODS_COMPLETED)
        subtitle = "  ".join(subtitle_parts)

        link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

        items.append(alfred.item(
            uid=f"done-{tid}",
            title=f"{name} {priority_dot}{tag_str}",
            subtitle=subtitle,
            arg=f"open:{link}",
            mods={
                "cmd":   {"arg": "", "subtitle": "⌘ Actions"},
                "shift": {"arg": f"uncomplete:{pid}:{tid}:{name}", "subtitle": "Uncomplete"},
            },
            variables={"task_id": tid, "task_title": name, "task_list_id": pid},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x["title"]))

    if not items:
        if query:
            items = [alfred.item(
                title=f'No completed tasks matching "{query}"',
                valid=False,
            )]
        else:
            items = [alfred.item(
                title="No completed tasks recorded yet",
                subtitle="⇧✅ tasks appear here",
                valid=False,
            )]

    return add_back(items, "")


# ── Level: wontdo (the third status; twin of render_completed) ──────────────
def render_wontdo(query):
    tasks = cache_store.get("wontdo_tasks") or []

    items = []
    for t in tasks:
        tid  = t.get("id", "")
        pid  = t.get("_projectId", t.get("projectId", ""))
        name = t.get("title", "Untitled")

        priority_dot = PRIORITY.get(t.get("priority", 0), "⚫️")
        tags         = t.get("tags") or []
        tag_str      = " # " + " ".join(tags) if tags else ""

        breadcrumb = join_breadcrumb(t.get("_projectName", ""), t.get("_columnName", ""))

        subtitle_parts = [f"🚫 {fmt_completed_time(t)}"]
        if breadcrumb:
            subtitle_parts.append(breadcrumb)
        subtitle_parts.append("|")   # the house '  |  ' before the legend
        subtitle_parts.append(MODS_COMPLETED)
        subtitle = "  ".join(subtitle_parts)

        link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

        items.append(alfred.item(
            uid=f"wontdo-{tid}",
            title=f"{name} {priority_dot}{tag_str}",
            subtitle=subtitle,
            arg=f"open:{link}",
            mods={
                "cmd":   {"arg": "", "subtitle": "⌘ Actions"},
                "shift": {"arg": f"xact:wontdo_undo:{pid}:{tid}", "subtitle": "Reopen"},
            },
            variables={"task_id": tid, "task_title": name, "task_list_id": pid},
        ))

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: search_key(x["title"]))

    if not items:
        if query:
            items = [alfred.item(
                title=f'No won\'t-do tasks matching "{query}"',
                valid=False,
            )]
        else:
            items = [alfred.item(
                title="Nothing marked Won't Do yet",
                subtitle="🚫 lives in the ⌘ Actions menu",
                valid=False,
            )]

    return add_back(items, "")


# ── Level: filter (custom filters from filters_config.py) ───────────────────
def render_filter(index, query):
    """Tasks matching FILTERS[index], as canonical task rows (full ⌘ Actions).
    Flat - the retired filter_view's L1 tag-grouping is not reproduced. Back
    is inert ("" → the back-router's unconnected else): this ctx is entered
    from search via ⌥, and ⌫ / ⌃-main-menu are the ways out."""
    import filtering
    filters = filtering.load_filters()
    try:
        f = filters[int(index)]
    except (ValueError, IndexError):
        return [alfred.item(title=f"Unknown filter index “{index}”",
                            subtitle=f"Reopen the list  |  {len(filters)} filters known",
                            valid=False)]
    f_name    = f.get("name", f"Filter {int(index) + 1}")
    all_tasks = cache_store.get("all_tasks") or []
    projects  = cache_store.get("projects") or []
    tasks     = filtering.matching_tasks(f, all_tasks, projects)

    items = []
    for t in tasks:
        pid = t.get("_projectId", t.get("projectId", ""))
        items.append(task_item(
            t, pid, _child_count(all_tasks, t["id"]),
            breadcrumb=join_breadcrumb(f_name, t.get("_projectName", ""),
                                       t.get("_columnName", "")),
            uid=f"task-{t['id']}",
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        items.append(alfred.item(
            title=f'No tasks matching "{query}"' if query else f"No tasks in {f_name}",
            valid=False,
        ))

    return add_back(items, "")

# ── Main ─────────────────────────────────────────────────────────────────────
def _missing(level, want):
    return [alfred.item(
        title=f"Browse: ctx:{level} needs {want}",
        subtitle="Grammar: ctx:<level>[:<id1>[:<id2>]] [query…]",
        valid=False,
    )]

def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    level, ids, query = parse_ctx(raw)

    try:
        if level == "folders":
            items = render_folders(query)

        elif level == "lists":
            items = render_lists(ids[0] if ids else "", query)

        elif level == "sections":
            items = render_sections(ids[0], query) if ids else _missing(level, "<listId>")

        elif level == "tasks":
            if not ids:
                items = _missing(level, "<listId>[:<sectionId>]")
            else:
                items = render_tasks(ids[0], ids[1] if len(ids) > 1 else "", query)

        elif level in ("subtasks", "subsubtasks"):
            if len(ids) >= 2:
                lid, tid = ids[0], ids[1]
            elif len(ids) == 1:
                # Design-doc short form ctx:subtasks:<taskId> - resolve the list
                tid = ids[0]
                t   = cache_store.find_task(tid) or {}
                lid = t.get("_projectId") or t.get("projectId") or ""
            else:
                lid = tid = ""
            if not (lid and tid):
                items = _missing(level, "<listId>:<taskId> (or a cached <taskId>)")
            else:
                items = render_children(lid, tid, query, level)

        elif level == "buffer":
            items = render_buffer(query)

        elif level == "tags":
            items = render_tags(ids[0], query) if ids else _missing(level, "<listId>")

        elif level == "tagitems":
            if len(ids) >= 2:
                items = render_tagitems(ids[0], ":".join(ids[1:]), query)
            else:
                items = _missing(level, "<listId>:<tag>")

        elif level == "smart":
            items = render_smart(ids[0] if ids else "today", query)

        elif level == "inbox":
            items = render_inbox(query)

        elif level == "completed":
            items = render_completed(query)

        elif level == "wontdo":
            items = render_wontdo(query)

        elif level == "filter":
            items = render_filter(ids[0], query) if ids else _missing(level, "<index>")

        elif level == "crmnew":
            items = render_crmnew(ids[0] if ids else "", query)

        elif level == "crmdone":
            items = render_crmdone(query)

        elif level == "crmlog":
            items = render_crmlog(query)

        else:
            items = [alfred.item(
                title=f"Unknown browse context “{level}”",
                subtitle="Levels: folders lists sections tasks subtasks subsubtasks "
                         "tags tagitems smart inbox completed wontdo filter buffer "
                         "crmnew crmdone crmlog",
                valid=False,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
