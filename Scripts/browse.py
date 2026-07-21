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
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr

    if kind == "session":
        rows = []
        seen = set()
        for tag in (_areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG):
            for lb in cr.records_notes(tag):
                if lb["id"] in seen:
                    continue
                seen.add(lb["id"])
                archived = tag == _areas.ARCHIVE_TAG
                n = cr.next_snum(lb.get("content") or "", lb["id"])
                if archived:
                    state = "📁 archived · ⏎ reopens for a touch-up"
                else:
                    nxt = cr.next_session_task(lb["id"])
                    state = (f"{nxt[1] or 'session'} scheduled 📅 {nxt[0] or '?'}"
                             if nxt else "nothing scheduled")
                mods = _picker_mods()
                mods["shift"] = {"arg": f"open:ticktick:///webapp/#p/"
                                        f"{_areas.RECORDS_ID}/tasks/{lb['id']}",
                                 "valid": True, "subtitle": "Open the logbook"}
                rows.append(alfred.item(
                    uid=f"crmnew-s-{lb['id']}",
                    title=lb.get("title") or "Untitled",
                    subtitle=f"⏎ Schedule S{n} · {state}",
                    arg=f"xact:crmnew_go:session::{lb['id']}",
                    mods=mods,
                    variables=_record_vars(lb),
                ))
        if query:
            rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No open logbooks",
                                subtitle="➕ New tattoo starts one", valid=False)]
        return add_back(rows, "ctx:crmhub")

    label = "consultation" if kind == "consult" else "tattoo"
    new_row = alfred.item(
        uid="crmnew-newcust",
        title="➕ New customer",
        subtitle=f"Dialogs ask name + contact, then the {label}",
        arg=f"xact:crmnew_newcust:{kind}",
    )
    rows = [new_row]
    # Leads picker-in too: booking one IS its promotion to customer.
    pool = (cr.records_notes(_areas.CUSTOMER_TAG)
            + cr.records_notes(_areas.LEAD_TAG))
    seen = set()
    for c in pool:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        chip = " · 🎣 lead converts" if cr.is_lead(c) else ""
        rows.append(alfred.item(
            uid=f"crmnew-c-{c['id']}",
            title=c.get("title") or "Untitled",
            subtitle=f"⏎ New {label} for this customer{chip}",
            arg=f"xact:crmnew_go:{kind}:{c['id']}",
            mods=_picker_mods(),
            variables=_record_vars(c),
        ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"]) \
            or [new_row]   # no matching customer → they're new
    return add_back(rows, "ctx:crmhub")


def render_crmdone(query):
    """Open calendar tasks that link a logbook - ⏎ completes + logs (dialogs)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
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
        mods = _picker_mods("⏎ completes + logs it properly")
        _l = cr.parse_first_link(t.get("title") or "")
        if _l:
            _lb = next((x for x in cr.records_notes()
                        if x.get("id") == _l[2]), None)
            _c = cr.parse_first_link((_lb or {}).get("content") or "")
            if _c:
                mods["alt"] = {"arg": "", "valid": True,
                               "subtitle": "Customer hub",
                               "variables": {"browse_ctx": f"ctx:crmcust:{_c[2]}"}}
        dep = ""
        if _l:
            _lb2 = next((x for x in cr.records_notes()
                         if x.get("id") == _l[2]), None)
            if _lb2:
                dep_s, _dv = cr.payments_sum(_lb2.get("content") or "")
                if dep_s:
                    dep = f" · 💶 {dep_s} on file"
        rows.append(alfred.item(
            uid=f"crmdone-{t['id']}",
            title=f"✅ {disp}",
            subtitle=f"📅 {_day(t) or 'Not scheduled'}{dep} · ⏎ Complete + log",
            arg=f"xact:sessiondone:{CRM_ID}:{t['id']}",
            mods=mods,
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
    return add_back(rows, "ctx:crmhub")


def render_crmlog(query):
    """Every records note (customers, logbooks, archive) - ⏎ logs a line."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
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
    return add_back(rows, "ctx:crmhub")


# ── Levels: crmsearch / crmcust / crmback / crmsched (round-2 surfaces) ──────

def _open_note_arg(tid):
    return f"open:ticktick:///webapp/#p/{_areas.RECORDS_ID}/tasks/{tid}"


def _cust_row(cr, c, uid_prefix="crms"):
    """Customer search row: contact + lifetime in the subtitle, ⌥ drills into
    the customer hub, ⏎ opens the note."""
    phone, mail, _b, insta = cr.contact_of(c)
    money, k, n = cr.lifetime(c["id"])
    lead_chip = ""
    if cr.is_lead(c):
        age = cr.note_age_days(c)
        lead_chip = f"🎣 lead · {age}d" if age is not None else "🎣 lead"
    bd = cr.bday_next(_b)
    g = cr.lifetime_gratis(c["id"])
    bits = [b for b in (
        f"📞 {phone}" if phone else (f"📸 {insta}" if insta else ""),
        f"{k} tattoo{'s' if k != 1 else ''}" if k else "",
        money if money != "-" else "",
        f"🖤 {g}" if g else "",
        lead_chip,
        (f"🎂 {'today!' if bd == 0 else f'in {bd}d'}"
         if bd is not None and bd <= 14 else ""),
    ) if b]
    return alfred.item(
        uid=f"{uid_prefix}-c-{c['id']}",
        title=c.get("title") or "Untitled",
        subtitle=(" · ".join(bits) or "No contact yet") + " · ⌥ hub",
        arg=_open_note_arg(c["id"]),
        mods={**_picker_mods(),
              "alt": {"arg": "", "valid": True, "subtitle": "Customer hub",
                      "variables": {"browse_ctx": f"ctx:crmcust:{c['id']}"}}},
        variables=_record_vars(c),
    )


def _logbook_row(cr, lb, uid_prefix="crms"):
    """Logbook search row: customer + paid + next session in the subtitle,
    ⌥ opens the LOGBOOK hub (photo/payment/rename/archive), ⏎ opens the
    note. Customer hub: ⌥ on the customer row, or ⌃ from the hub."""
    paid = cr.paid_summary(lb.get("content") or "")
    hit = cr.parse_first_link(lb.get("content") or "")
    cust_name = cr.PERSON_RE.sub("", hit[0]) if hit else ""
    archived = _areas.ARCHIVE_TAG in {str(t).lower()
                                      for t in (lb.get("tags") or [])}
    if archived:
        state = "📁 archived"
    else:
        nxt = cr.next_session_task(lb["id"])
        state = (f"next {nxt[1] or 'session'} 📅 {nxt[0] or 'unscheduled'}"
                 if nxt else "▶️ nothing scheduled")
    bits = [b for b in (cust_name,
                        "" if paid.startswith("-") else paid,
                        state) if b] + ["⌥ hub"]
    mods = _picker_mods()
    mods["alt"] = {"arg": "", "valid": True, "subtitle": "Logbook hub",
                   "variables": {"browse_ctx": f"ctx:crmbook:{lb['id']}"}}
    return alfred.item(
        uid=f"{uid_prefix}-l-{lb['id']}",
        title=lb.get("title") or "Untitled",
        subtitle=" · ".join(bits),
        arg=_open_note_arg(lb["id"]),
        mods=mods,
        variables=_record_vars(lb),
    )


def _crm_task_row(cr, t, uid_prefix="crms"):
    """Calendar task row for the CRM search: ⏎ opens, ⌘ Actions carries the
    Session done row, ⌥ jumps to the linked tattoo's logbook hub, dateless
    tasks read as dormant."""
    due = t.get("dueDate") or t.get("startDate") or ""
    try:
        day = utc_str_to_local_date(due) if due else ""
    except Exception:
        day = ""
    disp = cr.LINK_RE.sub(r"\1", t.get("title") or "")
    linked = cr.is_session_task(t.get("title") or "")
    chip = " · ⌥ hub" if linked else " · 🔗 unlinked (⌘ → Link)"
    mods = _picker_mods()
    hit = cr.parse_first_link(t.get("title") or "")
    if hit:
        mods["alt"] = {"arg": "", "valid": True, "subtitle": "Logbook hub",
                       "variables": {"browse_ctx": f"ctx:crmbook:{hit[2]}"}}
    emo = ("💬" if (t.get("title") or "").rstrip().endswith("Consult")
           else "📅")
    return alfred.item(
        uid=f"{uid_prefix}-t-{t['id']}",
        title=f"{emo} {disp}",
        subtitle=(f"{day or 'Dormant · not scheduled'}{chip}"),
        arg=f"open:ticktick:///webapp/#p/{CRM_ID}/tasks/{t['id']}",
        mods=mods,
        variables={"task_id": t["id"], "task_list_id": CRM_ID,
                   "list_id": CRM_ID, "task_title": t.get("title") or "",
                   "item_type": "task"},
    )


def _crm_open_tasks():
    return [t for t in cache_store.get("all_tasks") or []
            if (t.get("_projectId") or t.get("projectId")) == CRM_ID
            and t.get("status", 0) == 0]


def render_crmweek(query):
    """📆 The morning glance: today's + this week's sessions in date order,
    then the 🔔 needs-booking radar (active logbooks with nothing scheduled
    and no entry in 14 days - the pipeline leak)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    from datetime import date as _date, datetime as _dt, timedelta as _td

    def _local_dt(t):
        due = t.get("dueDate") or t.get("startDate") or ""
        if not due:
            return None
        try:
            clean = due[:19]
            d = _dt(int(clean[0:4]), int(clean[5:7]), int(clean[8:10]),
                    int(clean[11:13]), int(clean[14:16]),
                    tzinfo=__import__("datetime").timezone.utc)
            return d.astimezone()
        except Exception:
            return None

    today = _date.today()
    horizon = today + _td(days=7)
    rows = []
    pool = []
    for t in _crm_open_tasks():
        d = _local_dt(t)
        if d and today <= d.date() <= horizon:
            pool.append((d, t))
    pool.sort(key=lambda x: x[0])
    for d, t in pool:
        disp = cr.LINK_RE.sub(r"\1", t.get("title") or "")
        when = ("Today" if d.date() == today else
                ("Tomorrow" if d.date() == today + _td(days=1)
                 else d.strftime("%a %d")))
        clock = d.strftime(" %H:%M") if d.strftime("%H:%M") != "00:00" else ""
        mods = _picker_mods()
        _l = cr.parse_first_link(t.get("title") or "")
        if _l:
            mods["alt"] = {"arg": "", "valid": True,
                           "subtitle": "Logbook hub",
                           "variables": {"browse_ctx": f"ctx:crmbook:{_l[2]}"}}
        emo = ("💬" if (t.get("title") or "").rstrip().endswith("Consult")
               else "📆")
        rows.append(alfred.item(
            uid=f"wk-{t['id']}",
            title=f"{emo} {when}{clock} · {disp}",
            subtitle="⏎ Open · ⌘ Actions (Session done) · ⌥ hub",
            arg=f"open:ticktick:///webapp/#p/{CRM_ID}/tasks/{t['id']}",
            mods=mods,
            variables={"task_id": t["id"], "task_list_id": CRM_ID,
                       "list_id": CRM_ID, "task_title": t.get("title") or "",
                       "item_type": "task"}))
    if not rows:
        rows = [alfred.item(title="📆 Nothing this week",
                            subtitle="The radar below is your move",
                            valid=False)]

    # 🔔 radar: active logbook + nothing scheduled + last entry > 14d ago
    cutoff = (today - _td(days=14)).isoformat()
    for lb in cr.records_notes(_areas.LOGBOOK_TAG):
        if cr.next_session_task(lb["id"]):
            continue
        dates = [m.group(1)[:10] for m in
                 cr.ENTRY_RE.finditer(lb.get("content") or "")]
        last = max(dates) if dates else None
        age_ref = last or (today - _td(days=(cr.note_age_days(lb) or 0))).isoformat()
        if age_ref <= cutoff:
            chip = f"last entry {last}" if last else "no entries yet"
            rows.append(alfred.item(
                uid=f"wk-radar-{lb['id']}",
                title=f"🔔 {lb.get('title') or ''}",
                subtitle=f"Nothing scheduled · {chip} · "
                         "⏎ Schedule next session · ⌥ hub",
                arg=f"xact:crmnew_go:session::{lb['id']}",
                mods={**_picker_mods(),
                      "alt": {"arg": "", "valid": True,
                              "subtitle": "Logbook hub",
                              "variables": {
                                  "browse_ctx": f"ctx:crmbook:{lb['id']}"}}},
                variables=_record_vars(lb)))

    # 🎣 radar: leads sitting quiet past the same cutoff - nothing booked
    # anywhere on their logbooks. Leads rot silently; bookings don't.
    for ld in cr.records_notes(_areas.LEAD_TAG):
        age = cr.note_age_days(ld)
        if age is None or age < 14:
            continue
        if any(cr.next_session_task(lb["id"])
               for lb in cr.customer_logbooks(ld["id"])):
            continue
        rows.append(alfred.item(
            uid=f"wk-lead-{ld['id']}",
            title=ld.get("title") or "",
            subtitle=f"Lead going cold · {age}d quiet · ⏎ Open · ⌥ hub",
            arg=_open_note_arg(ld["id"]),
            mods={**_picker_mods(),
                  "alt": {"arg": "", "valid": True,
                          "subtitle": "Customer hub",
                          "variables": {
                              "browse_ctx": f"ctx:crmcust:{ld['id']}"}}},
            variables=_record_vars(ld)))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    return add_back(rows, "ctx:crmhub")


def render_crmbook(log_tid, query):
    """🎨 The logbook hub - everything about ONE tattoo on one screen."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    lb = next((l for l in cr.records_notes() if l.get("id") == log_tid), None)
    if lb is None:
        return add_back([alfred.item(title="Logbook not found",
                                     subtitle="Run tsy", valid=False)],
                        "ctx:crmhub")
    archived = _areas.ARCHIVE_TAG in {str(t).lower()
                                      for t in (lb.get("tags") or [])}
    hit = cr.parse_first_link(lb.get("content") or "")
    back = f"ctx:crmcust:{hit[2]}" if hit else "ctx:crmhub"
    n = cr.next_snum(lb.get("content") or "", log_tid)
    g = cr.gratis_count(lb.get("content") or "")
    rows = [alfred.item(
        uid="bk-open", title=lb.get("title") or "Logbook",
        subtitle=cr.paid_summary(lb.get("content") or "")
                 + (f" · 🖤 {g} gratis" if g else "")
                 + (" · 📁 archived" if archived else "") + " · ⏎ Open note",
        arg=_open_note_arg(log_tid), mods=_picker_mods(),
        variables=_record_vars(lb))]
    if not archived:
        rows.append(alfred.item(
            uid="bk-next", title=f"▶️ Schedule S{n}",
            subtitle="Add window · prefilled",
            arg=f"xact:crmnew_go:session::{log_tid}", mods=_picker_mods()))
    setup = cr.last_setup(lb.get("content") or "")
    if setup:
        rows.append(alfred.item(
            uid="bk-setup", title=f"🧰 Last setup · {setup}",
            subtitle="From the previous session · prefilled at the next one",
            valid=False))
    rows += [
        alfred.item(uid="bk-photo", title="🖼 Attach photo",
                    subtitle="Clipboard → logbook (reference · session · healed)",
                    arg=f"xact:crmphoto:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-pay", title="💶 Log payment",
                    subtitle="Deposit · remainder · minus = refund",
                    arg=f"xact:crmpay:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-past", title="🕰 Log past session",
                    subtitle="Dated entry, no task",
                    arg=f"xact:crmpast:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-summary", title="🧾 Copy money summary",
                    subtitle="Sessions + amounts + total → clipboard",
                    arg=f"xact:crmsummary:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-rename", title="✏️ Rename tattoo",
                    subtitle="Ripples through titles, links, bullets",
                    arg=f"xact:crmrename:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-log", title="📝 Log a line",
                    subtitle="Timestamped · lands under ## Notes",
                    arg=f"xact:crmlog:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-edit", title="✏️ Edit note",
                    subtitle="Alfred text view",
                    arg=f"xact:crmedit:{log_tid}", mods=_picker_mods()),
    ]
    if not archived:
        rows.append(alfred.item(
            uid="bk-close", title="📁 Archive",
            subtitle="Close without a session",
            arg=f"xact:crmclose:{log_tid}", mods=_picker_mods()))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, back)


def render_crmmoney(sub, query):
    """💰 Vex's money screen: all-time totals first, customers second,
    open logbooks below; archived behind one row (typing searches them too).
    Sub-screens: periods (week/month/quarter/year sums) · cust (totals per
    customer, richest first) · arch (archived logbooks)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    from datetime import date as _date, timedelta as _td

    if sub == "periods":
        e = cr.all_entries()
        today = _date.today()
        monday = today - _td(days=today.weekday())
        m0 = today.replace(day=1)
        lm_end = m0 - _td(days=1)
        q0 = _date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        y0 = _date(today.year, 1, 1)
        def row(uid, label, a, b):
            money, n, hours, raw = cr.sum_entries(e, a and a.isoformat(),
                                                  b and b.isoformat())
            extra = f" · {hours:g}h" if hours else ""
            return alfred.item(
                uid=uid, title=f"{label} · {money}{cr.cut_chip(raw, money)}"
                               f" · {n} session{'s' if n != 1 else ''}{extra}",
                subtitle=f"{a.isoformat() if a else '…'} → {b.isoformat() if b else 'today'}",
                valid=False)
        rows = [
            row("mo-w",  "📆 This week",    monday, None),
            row("mo-lw", "📆 Last week",    monday - _td(days=7), monday - _td(days=1)),
            row("mo-m",  "📆 This month",   m0, None),
            row("mo-lm", "📆 Last month",   lm_end.replace(day=1), lm_end),
            row("mo-q",  "📆 This quarter", q0, None),
            row("mo-y",  "📆 This year",    y0, None),
            row("mo-ly", "📆 Last year",    _date(today.year - 1, 1, 1),
                _date(today.year - 1, 12, 31)),
        ]
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:crmmoney")

    if sub == "cust":
        pool = (cr.records_notes(_areas.CUSTOMER_TAG)
                + cr.records_notes(_areas.LEAD_TAG))
        seen, custs = set(), []
        for c in pool:
            if c["id"] not in seen:
                seen.add(c["id"])
                custs.append(c)
        custs.sort(key=lambda c: -cr.lifetime_raw(c["id"]))
        rows = [_cust_row(cr, c, uid_prefix="mo") for c in custs]
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No customers yet", valid=False)]
        return add_back(rows, "ctx:crmmoney")

    if sub == "arch":
        rows = [_logbook_row(cr, lb, uid_prefix="mo")
                for lb in cr.records_notes(_areas.ARCHIVE_TAG)]
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="Nothing archived yet", valid=False)]
        return add_back(rows, "ctx:crmmoney")

    # root: totals + customers pinned, open logbooks below; typing also
    # searches the archived ones (chipped) so history stays reachable.
    e = cr.all_entries()
    money, n, hours, raw = cr.sum_entries(e)
    arch = cr.records_notes(_areas.ARCHIVE_TAG)
    rate = ""
    if hours:
        import re as _re2
        mnum = _re2.search(r"-?[\d.]+", money.replace(",", ""))
        if mnum:
            r = float(mnum.group(0)) / hours
            symm = _re2.sub(r"[-\d.,\s]", "", money) or "€"
            rate = f" · {hours:g}h · ~{int(r)}{symm}/h"
    pinned = [
        alfred.item(uid="mo-total",
                    title=f"💰 All time · {money}{cr.cut_chip(raw, money)}"
                          f" · {n} session{'s' if n != 1 else ''}{rate}",
                    subtitle="⏎ Weekly · monthly · quarterly · yearly",
                    arg="xact:crmbrowse:ctx:crmmoney:periods",
                    mods=_picker_mods()),
        alfred.item(uid="mo-cust", title="👥 Customers",
                    subtitle="⏎ Totals per customer · richest first",
                    arg="xact:crmbrowse:ctx:crmmoney:cust",
                    mods=_picker_mods()),
    ]
    lbs = [_logbook_row(cr, lb, uid_prefix="mo")
           for lb in cr.records_notes(_areas.LOGBOOK_TAG)]
    if query:
        lbs += [_logbook_row(cr, lb, uid_prefix="mo-a") for lb in arch]
        lbs = fuzz.filter_and_score(query, lbs, key_fn=lambda x: x["title"])
        return add_back(pinned + lbs, "ctx:crmhub")
    rows = pinned + lbs
    rows.append(alfred.item(
        uid="mo-csv", title="🧾 CSV export",
        subtitle="Every dated charge / deposit / refund → ~/Downloads",
        arg="xact:crmcsv", mods=_picker_mods()))
    if arch:
        rows.append(alfred.item(
            uid="mo-arch",
            title=f"📁 Archived · {len(arch)} logbook{'s' if len(arch) != 1 else ''}",
            subtitle="⏎ Show them (typing up here searches them too)",
            arg="xact:crmbrowse:ctx:crmmoney:arch",
            mods=_picker_mods()))
    return add_back(rows, "ctx:crmhub")


def _stat_periods():
    from datetime import date as _date, timedelta as _td
    t = _date.today()
    m0 = t.replace(day=1)
    lm_end = m0 - _td(days=1)
    lm0 = lm_end.replace(day=1)
    q0 = _date(t.year, ((t.month - 1) // 3) * 3 + 1, 1)
    lq_end = q0 - _td(days=1)
    lq0 = _date(lq_end.year, ((lq_end.month - 1) // 3) * 3 + 1, 1)
    y0 = _date(t.year, 1, 1)
    iso = lambda d: d.isoformat() if d else None
    return {
        "thism":  ("This month",  iso(m0), None, iso(lm0), iso(lm_end)),
        "lastm":  ("Last month",  iso(lm0), iso(lm_end),
                   iso((lm0 - _td(days=1)).replace(day=1)), iso(lm0 - _td(days=1))),
        "quarter": ("This quarter", iso(q0), None, iso(lq0), iso(lq_end)),
        "year":   ("This year",   iso(y0), None,
                   f"{t.year - 1}-01-01", f"{t.year - 1}-12-31"),
        "all":    ("All time",    None, None, None, None),
    }


def _delta_chip(cur, prev):
    if prev in (0, None) or cur is None:
        return ""
    if prev == 0:
        return ""
    pct = round((cur - prev) / abs(prev) * 100)
    if pct > 0:
        return f" · ▲ {pct}%"
    if pct < 0:
        return f" · ▼ {abs(pct)}%"
    return " · ="


def render_crmstats(sub, query):
    """📊 The KPI dashboard Vex asked for: pick a period, get the numbers a
    real CRM would show - money/hours/rate, sessions, new vs returning
    customers, tattoos started/finished, top customer - every one computed
    live from the logbook entries (there are NO stat notes; the logbooks are
    the database) with vs-previous-period deltas."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    periods = _stat_periods()

    if sub in periods:
        label, a, b, pa, pb = periods[sub]
        k = cr.period_kpis(a, b)
        p = cr.period_kpis(pa, pb) if (pa or pb) else None
        fm = lambda v: cr._fmt_money(v, k["sym"], k["pre"])
        cut = cr.cut_percent()
        cut_part = (f" · 🫵 {fm(k['money'] * cut / 100.0)}"
                    if cut and k["money"] else "")
        rows = [alfred.item(uid="kp-money",
                            title=f"💰 {fm(k['money'])}"
                                  + _delta_chip(k["money"], p and p["money"])
                                  + cut_part,
                            subtitle=f"{label} · money made · 🫵 = your cut",
                            valid=False)]
        if k["hours"]:
            rate = f" · ~{int(k['rate'])}{k['sym']}/h" if k["rate"] else ""
            rows.append(alfred.item(
                uid="kp-hours", title=f"🧮 {k['hours']:g}h{rate}"
                + _delta_chip(k["hours"], p and p["hours"]),
                subtitle="Hours in the chair · effective rate", valid=False))
        rows.append(alfred.item(
            uid="kp-sess", title=f"🪡 {k['sessions']} session"
            + ("s" if k["sessions"] != 1 else "")
            + _delta_chip(k["sessions"], p and p["sessions"]),
            subtitle="Needle sessions logged", valid=False))
        rows.append(alfred.item(
            uid="kp-new", title=f"✨ {k['new_customers']} new customer"
            + ("s" if k["new_customers"] != 1 else "")
            + _delta_chip(k["new_customers"], p and p["new_customers"]),
            subtitle="Customer notes created in the period", valid=False))
        rows.append(alfred.item(
            uid="kp-ret",
            title=f"🔁 {k['returning']} returning · "
                  f"{k['active_customers']} active",
            subtitle="Returning = tattooed before this period too",
            valid=False))
        rows.append(alfred.item(
            uid="kp-fin", title=f"🎨 {k['finished']} finished · "
            f"{k['started']} started"
            + _delta_chip(k["finished"], p and p["finished"]),
            subtitle="Tattoos (logbooks) in the period", valid=False))
        if k["top"]:
            rows.append(alfred.item(
                uid="kp-top",
                title=f"👑 {k['top']['name'] or 'Top customer'} · "
                      f"{fm(k['top']['money'])}",
                subtitle="Top customer of the period · ⏎ their hub",
                arg=f"xact:crmbrowse:ctx:crmcust:{k['top']['tid']}",
                mods=_picker_mods()))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:crmstats")

    # root: period picker with headline subtitles
    rows = []
    cut = cr.cut_percent()
    for key in ("thism", "lastm", "quarter", "year", "all"):
        label, a, b, _pa, _pb = periods[key]
        k = cr.period_kpis(a, b)
        fmz = lambda v: cr._fmt_money(v, k["sym"], k["pre"])
        head = fmz(k["money"])
        if cut and k["money"]:
            head += f" · 🫵 {fmz(k['money'] * cut / 100.0)}"
        head += f" · {k['sessions']} session{'s' if k['sessions'] != 1 else ''}"
        if k["hours"]:
            head += f" · {k['hours']:g}h"
        rows.append(alfred.item(
            uid=f"st-{key}", title=f"📊 {label}",
            subtitle=f"{head} · ⏎ Full dashboard",
            arg=f"xact:crmbrowse:ctx:crmstats:{key}",
            mods=_picker_mods()))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmhub")


def render_crmhub(query):
    """🏠 The CRM home inside browse - every verb one row away. ⌃ from any
    CRM screen lands here (the two-key Session-done → Next-session loop).
    Rows trampoline via xact:crmbrowse (plain rows can't switch ctx on ⏎)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    def hop(uid, title, subtitle, ctx):
        return alfred.item(uid=uid, title=title, subtitle=subtitle,
                           arg=f"xact:crmbrowse:{ctx}", mods=_picker_mods())
    rows = [
        hop("hub-done", "✅ Session done", "Tick off · log · schedule next",
            "ctx:crmdone"),
        hop("hub-next", "▶️ Next session", "Pick logbook → S<n>",
            "ctx:crmnew:session"),
        hop("hub-tattoo", "➕ New tattoo", "Customer → logbook → S1",
            "ctx:crmnew:tattoo"),
        hop("hub-consult", "➕ New consultation", "Customer → logbook → schedule",
            "ctx:crmnew:consult"),
        alfred.item(uid="hub-person", title="➕ New lead / customer",
                    subtitle="Dialogs · lead lands in Records",
                    arg="xact:crmperson", mods=_picker_mods()),
        hop("hub-backlog", "📕 Backlog", "Import finished tattoo · past session",
            "ctx:crmback"),
        hop("hub-sched", "📅 Schedule", "Dormant tasks → schedule + link",
            "ctx:crmsched"),
        hop("hub-search", "🔍 Search", "Everything CRM · / scopes",
            "ctx:crmsearch"),
        hop("hub-log", "📝 Log", "Line into a customer / logbook note",
            "ctx:crmlog"),
        hop("hub-stats", "📊 Stats", "Earnings + sessions per month",
            "ctx:crmstats"),
        hop("hub-money", "💰 Money", "Totals · periods · per customer",
            "ctx:crmmoney"),
        hop("hub-week", "📆 Week", "Who's coming + the needs-booking radar",
            "ctx:crmweek"),
    ]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmhub")


_CRM_SCOPES = [("ca", "Calendar",  "📅", "Session + dormant tasks"),
               ("lo", "Logbooks",  "🎨", "Active + archived"),
               ("cu", "Customers", "👥", "Customers + leads"),
               ("ar", "Archived",  "📁", "Finished logbooks only")]
# Locked-scope bar reads as a word ('Calendar smith'), everything-search style;
# the short codes stay valid for muscle memory.
_CRM_SCOPE_RE = re.compile(r"(?i)(calendar|logbooks|customers|archived"
                           r"|ca|lo|cu|ar)(?:\s+(.*))?$")


def _crmsearch_rows(cr, scope, term):
    """Pooled, filtered, rendered rows for one scope code: '' = everything,
    'cu' customers, 'lo' logbooks+archived, 'ar' archived only, 'ca' calendar
    tasks, 're' = records (customers + logbooks) - 're' has no search-bar
    spelling, it exists for the crmcal/crmlogs menu drills."""
    rows = []
    if scope in ("", "cu", "re"):
        leads = sorted(cr.records_notes(_areas.LEAD_TAG),
                       key=lambda c: -(cr.note_age_days(c) or 0))
        pool = cr.records_notes(_areas.CUSTOMER_TAG) + leads
        seen = set()
        for c in pool:
            if c["id"] not in seen:
                seen.add(c["id"])
                rows.append(("cust", c))
    if scope in ("", "lo", "ar", "re"):
        seen = set()
        tags = ((_areas.ARCHIVE_TAG,) if scope == "ar"
                else (_areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG))
        for tag in tags:
            for lb in cr.records_notes(tag):
                if lb["id"] not in seen:
                    seen.add(lb["id"])
                    rows.append(("log", lb))
    if scope in ("", "ca"):
        tasks = _crm_open_tasks()
        tasks.sort(key=lambda t: (t.get("dueDate") or t.get("startDate")
                                  or "9999"))
        rows += [("task", t) for t in tasks]

    if term:
        tl = term.lower()
        def _hits(kind, o):
            if tl in (o.get("title") or "").lower():
                return True
            # content matching (phone digits, mail, session text) for notes
            if kind in ("cust", "log") and len(tl) >= 3:
                return tl in (o.get("content") or "").lower()
            return False
        rows = [(k, o) for k, o in rows if _hits(k, o)]

    out = []
    for kind, o in rows[:60]:
        if kind == "cust":
            out.append(_cust_row(cr, o))
        elif kind == "log":
            out.append(_logbook_row(cr, o))
        else:
            out.append(_crm_task_row(cr, o))
    return out


def render_crmsearch(query):
    """ONE search over the whole CRM (Vex ruling): customers + logbooks +
    calendar. '/' opens the scope menu; picking one locks the bar to
    '<Scope> <term>' (short codes 'ca ' etc. also work). Content matching
    included - typing a phone number finds its customer."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr

    q = (query or "").strip()
    if q.startswith("/"):
        frag = q[1:].strip()
        rows = [alfred.item(uid=f"crms-scope-{k}", title=f"{e} {name}",
                            subtitle=s, arg="", valid=False,
                            autocomplete=f"{name} ")
                for k, name, e, s in _CRM_SCOPES]
        if frag:
            rows = fuzz.filter_and_score(frag, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:crmhub")

    scope, term = "", q
    m = _CRM_SCOPE_RE.fullmatch(q)
    if m:
        scope = m.group(1).lower()[:2]
        term = (m.group(2) or "").strip()

    out = _crmsearch_rows(cr, scope, term)
    if not out:
        out = [alfred.item(title=f'Nothing matching "{term}"' if term
                           else "CRM is empty",
                           subtitle="/ scopes · ca lo cu", valid=False)]
    elif not q:
        # Scope indicator on the empty bar - everything-search parity.
        out.insert(0, alfred.item(title="Type to search the CRM…",
                                  subtitle="Type / for scope", valid=False))
    return add_back(out, "ctx:crmhub")


def _crmlist_drill(uid, emoji, name, list_id, scope, query):
    """Menu-row drill for one of the two CRM lists (Vex ruling 2026-07-21):
    row 1 is ALWAYS "open in TickTick" (the old ⏎), everything under it is
    the list itself, searchable in its scope."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    term = (query or "").strip()
    rows = [alfred.item(uid=f"{uid}-open", title=f"{emoji} {name}",
                        subtitle="⏎ Open list in TickTick",
                        arg=f"open:ticktick:///webapp/#p/{list_id}/tasks")]
    hits = _crmsearch_rows(cr, scope, term)
    if term and not hits:
        hits = [alfred.item(title=f'Nothing matching "{term}"', valid=False)]
    return add_back(rows + hits, "ctx:crmhub")


def render_crmcal(query):
    """📅 The calendar list: open row on top, open tasks under it."""
    return _crmlist_drill("crmcal", "📅", "Calendar", _areas.CRM_ID,
                          "ca", query)


def render_crmlogs(query):
    """🗂️ The Records list: open row on top, customers + logbooks under."""
    return _crmlist_drill("crmlogs", "🗂️", "Logs", _areas.RECORDS_ID,
                          "re", query)


def render_crmcust(cust_tid, query):
    """👤 Customer hub: contact copy rows, lifetime, logbooks, upcoming
    sessions, and the next-action rows - the one screen per human."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr

    cust = next((c for c in cr.records_notes()
                 if c.get("id") == cust_tid), None)
    if cust is None:
        return add_back([alfred.item(title="Customer not found",
                                     subtitle="Run tsy", valid=False)], "")
    name = cr.customer_display(cust)
    phone, mail, bday, insta = cr.contact_of(cust)
    money, k, n = cr.lifetime(cust_tid)
    rows = []
    info = " · ".join(b for b in (
        f"💰 {money}" if money != "-" else "",
        f"{k} tattoo{'s' if k != 1 else ''}",
        f"{n} session{'s' if n != 1 else ''}",
        f"🎂 {bday}" if bday else "",
        "🎣 lead" if cr.is_lead(cust) else "",
    ) if b)
    rows.append(alfred.item(
        uid="hub-open", title=cust.get("title") or name,
        subtitle=(info or "New customer") + " · ⏎ Open note",
        arg=_open_note_arg(cust_tid), mods=_picker_mods(),
        variables=_record_vars(cust)))
    if phone:
        rows.append(alfred.item(uid="hub-phone", title=f"📞 {phone}",
                                subtitle="⏎ Copy number",
                                arg=f"xact:crmcopy:{phone}",
                                mods=_picker_mods()))
    if mail:
        rows.append(alfred.item(uid="hub-mail", title=f"✉️ {mail}",
                                subtitle="⏎ Copy mail",
                                arg=f"xact:crmcopy:{mail}",
                                mods=_picker_mods()))
    if insta:
        handle = insta.lstrip("@")
        rows.append(alfred.item(uid="hub-insta", title=f"📸 @{handle}",
                                subtitle="⏎ Open profile (DMs live here)",
                                arg=f"open:https://instagram.com/{handle}",
                                mods=_picker_mods()))
    if phone:
        digits = re.sub(r"[^\d]", "", phone)
        if digits:
            rows.append(alfred.item(
                uid="hub-wa", title="💬 WhatsApp",
                subtitle=f"⏎ Chat with {phone}",
                arg=f"open:https://wa.me/{digits.lstrip('0')}",
                mods=_picker_mods()))
    lbs = cr.customer_logbooks(cust_tid)
    lb_ids = {lb["id"] for lb in lbs}
    for lb in lbs:
        r = _logbook_row(cr, lb, uid_prefix="hub")
        # ⏎ opens the LOGBOOK HUB (photo/payment/summary/rename/archive all
        # live there) - the note itself is one more ⏎ inside.
        r["arg"] = f"xact:crmbrowse:ctx:crmbook:{lb['id']}"
        r["subtitle"] = (r.get("subtitle") or "") + " · ⏎ Logbook hub"
        rows.append(r)
    for t in _crm_open_tasks():
        if any(f"/tasks/{lid})" in (t.get("title") or "") for lid in lb_ids):
            rows.append(_crm_task_row(cr, t, uid_prefix="hub"))
    rows.append(alfred.item(
        uid="hub-newtattoo", title=f"➕ New tattoo for {name}",
        subtitle="Logbook + S1 → scheduling",
        arg=f"xact:crmnew_go:tattoo:{cust_tid}", mods=_picker_mods()))
    rows.append(alfred.item(
        uid="hub-log", title="📝 Log a line",
        subtitle="Timestamped · lands under ## Notes",
        arg=f"xact:crmlog:{cust_tid}", mods=_picker_mods()))
    rows.append(alfred.item(
        uid="hub-edit", title="✏️ Edit note",
        subtitle="Alfred text view · contact line is line 1",
        arg=f"xact:crmedit:{cust_tid}", mods=_picker_mods()))
    rows.append(alfred.item(
        uid="hub-rename", title=f"✏️ Rename {name}",
        subtitle="Ripples through logbooks, links, bullets",
        arg=f"xact:crmrename:{cust_tid}", mods=_picker_mods()))
    rows.append(alfred.item(
        uid="hub-aftercare", title="🩹 Copy aftercare",
        subtitle="Template + name → clipboard",
        arg=f"xact:crmaftercare:{cust_tid}", mods=_picker_mods()))
    if cr.is_lead(cust):
        rows.append(alfred.item(
            uid="hub-convert", title="👤 Make customer",
            subtitle="Lead → customer (bookings do this automatically)",
            arg=f"xact:crmconvert:{cust_tid}", mods=_picker_mods()))
        rows.append(alfred.item(
            uid="hub-cold", title="🥶 Cold lead · archive",
            subtitle="One-line reason → ## Notes · out of the pickers",
            arg=f"xact:crmcold:{cust_tid}", mods=_picker_mods()))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmsearch")


def render_crmback(query):
    """📕 Backlog chooser: import a finished tattoo, date-log a past session
    into an existing logbook, or adopt a pre-automation calendar task."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    rows = [
        alfred.item(uid="back-import", title="📕 Import finished tattoo",
                    subtitle="Customer → name → total → sessions → archived",
                    arg="xact:crmimport", mods=_picker_mods()),
        alfred.item(uid="back-past", title="🕰 Log past session",
                    subtitle="Pick logbook → date + the usual questions",
                    arg="", valid=False, autocomplete="past "),
        alfred.item(uid="back-adopt", title="🔗 Adopt task",
                    subtitle="Old task → customer + logbook → log done",
                    arg="", valid=False, autocomplete="adopt "),
        alfred.item(uid="back-img", title="🖼️ Image to session",
                    subtitle="Copy image first · pick logbook → session",
                    arg="", valid=False, autocomplete="img "),
        alfred.item(uid="back-batch", title="🖼️ Batch images",
                    subtitle="Select photos in Finder first · "
                             "capture dates pick the sessions",
                    arg="", valid=False, autocomplete="batch "),
    ]
    q = (query or "").strip()
    if q.startswith("adopt"):
        import crm_records as cr
        frag = q[5:].strip()
        rows = []
        prep = (_areas.PREPARE_TAG or "").lower()
        for t in _crm_open_tasks():
            title = t.get("title") or ""
            if cr.is_session_task(title):
                continue          # already linked - Session done handles it
            if prep and prep in {str(x).lower() for x in (t.get("tags") or [])}:
                continue
            due = t.get("dueDate") or t.get("startDate")
            rows.append(alfred.item(
                uid=f"back-a-{t['id']}",
                title=title or "Untitled",
                subtitle="⏎ Customer → logbook → link"
                         + ("" if due else " · dormant"),
                arg=f"xact:crmlink:{CRM_ID}:{t['id']}",
                mods=_picker_mods(),
                variables={"task_id": t["id"], "task_list_id": CRM_ID,
                           "list_id": CRM_ID, "task_title": title,
                           "item_type": "task"}))
        if frag:
            rows = fuzz.filter_and_score(frag, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="Nothing to adopt",
                                subtitle="Every calendar task is linked 💪",
                                valid=False)]
        return add_back(rows, "ctx:crmback")
    if q.startswith(("past", "img", "batch")):
        mode = next(m for m in ("past", "img", "batch") if q.startswith(m))
        import crm_records as cr
        frag = q[len(mode):].strip()
        sub = {"img": "⏎ Pick session → image lands there",
               "batch": "⏎ Finder photos → sessions by date",
               "past": "⏎ Log a dated session"}[mode]
        verb = {"img": "crmimg", "batch": "crmbatchimg",
                "past": "crmpast"}[mode]
        rows = []
        seen = set()
        for tag in (_areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG):
            for lb in cr.records_notes(tag):
                if lb["id"] in seen:
                    continue
                seen.add(lb["id"])
                chip = (" · archived"
                        if _areas.ARCHIVE_TAG in {str(t).lower()
                                                  for t in (lb.get("tags") or [])}
                        else "")
                rows.append(alfred.item(
                    uid=f"back-{mode[0]}-{lb['id']}",
                    title=lb.get("title") or "Untitled",
                    subtitle=f"{sub}{chip}",
                    arg=f"xact:{verb}:{lb['id']}",
                    mods=_picker_mods(),
                    variables=_record_vars(lb)))
        if frag:
            rows = fuzz.filter_and_score(frag, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No logbooks yet",
                                subtitle="📕 Import creates one", valid=False)]
    elif q:
        rows = fuzz.filter_and_score(q, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmhub")


def render_crmsched(query):
    """📅 Dormant calendar tasks (no date) - ⏎ jumps straight into the
    schedule picker; Link to logbook lives on ⌘ Actions."""
    import crm_records as cr
    rows = []
    for t in _crm_open_tasks():
        if t.get("dueDate") or t.get("startDate"):
            continue
        disp = cr.LINK_RE.sub(r"\1", t.get("title") or "")
        linked = cr.is_session_task(t.get("title") or "")
        rows.append(alfred.item(
            uid=f"sched-{t['id']}",
            title=disp,
            subtitle="⏎ Schedule"
                     + ("" if linked else " · 🔗 unlinked · ⌘ link"),
            arg=f"xact:crmsched:{CRM_ID}:{t['id']}",
            mods=_picker_mods(),
            variables={"task_id": t["id"], "task_list_id": CRM_ID,
                       "list_id": CRM_ID, "task_title": t.get("title") or "",
                       "item_type": "task"},
        ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title="Nothing dormant",
                            subtitle="Every CRM task is scheduled 💪",
                            valid=False)]
    return add_back(rows, "ctx:crmhub")


def render_crmprep(query):
    """🔥 Prepare picker: every open CRM booking (🔥prepare tasks excluded),
    scheduled first in date order, dormant after - ⏎ opens the Add window
    prefilled "Prepare for [[…]]" (xact:crmprep)."""
    import crm_records as cr
    from datetime import date as _date, datetime as _dt, timedelta as _td, \
        timezone as _tz

    def _local_dt(t):
        due = t.get("dueDate") or t.get("startDate") or ""
        if not due:
            return None
        try:
            c = due[:19]
            return _dt(int(c[0:4]), int(c[5:7]), int(c[8:10]),
                       int(c[11:13]), int(c[14:16]),
                       tzinfo=_tz.utc).astimezone()
        except Exception:
            return None

    today = _date.today()
    sched, dormant = [], []
    for t in _crm_open_tasks():
        tags_lc = {str(x).lower() for x in (t.get("tags") or [])}
        # Tag is the real gate; the title check catches untagged strays.
        if _areas.PREPARE_TAG in tags_lc \
                or (t.get("title") or "").lstrip().startswith("Prepare for "):
            continue
        d = _local_dt(t)
        (sched if d else dormant).append((d, t))
    sched.sort(key=lambda x: x[0])
    rows = []
    for d, t in sched + dormant:
        disp = cr.LINK_RE.sub(r"\1", t.get("title") or "")
        if d:
            dd = d.date()
            if dd == today:
                when = "Today"
            elif dd == today + _td(days=1):
                when = "Tomorrow"
            elif today < dd <= today + _td(days=6):
                when = d.strftime("%a %d")
            else:   # beyond this week (or overdue) - weekday alone misleads
                when = d.strftime("%d %b")
            clock = d.strftime(" %H:%M") if d.strftime("%H:%M") != "00:00" else ""
            sub = f"{when}{clock} · ⏎ Prepare"
        else:
            sub = "Dormant · ⏎ Prepare"
        rows.append(alfred.item(
            uid=f"prep-{t['id']}",
            title=disp,
            subtitle=sub,
            arg=f"xact:crmprep:{CRM_ID}:{t['id']}",
            mods=_picker_mods(),
            variables={"task_id": t["id"], "task_list_id": CRM_ID,
                       "list_id": CRM_ID, "task_title": t.get("title") or "",
                       "item_type": "task"},
        ))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title="Nothing to prepare for",
                            subtitle="No open bookings", valid=False)]
    return add_back(rows, "ctx:crmhub")


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

    return add_back(items, "ctx:crmhub")

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

    return add_back(items, "ctx:crmhub")

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

    return add_back(items, "ctx:crmhub")


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

    return add_back(items, "ctx:crmhub")


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

    return add_back(items, "ctx:crmhub")

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

        elif level == "crmhub":
            items = render_crmhub(query)

        elif level == "crmstats":
            items = render_crmstats(ids[0] if ids else "", query)

        elif level == "crmmoney":
            items = render_crmmoney(ids[0] if ids else "", query)

        elif level == "crmweek":
            items = render_crmweek(query)

        elif level == "crmbook":
            items = render_crmbook(ids[0], query) if ids \
                else _missing(level, "<logbookTid>")

        elif level == "crmsearch":
            items = render_crmsearch(query)

        elif level == "crmcal":
            items = render_crmcal(query)

        elif level == "crmlogs":
            items = render_crmlogs(query)

        elif level == "crmcust":
            items = render_crmcust(ids[0], query) if ids \
                else _missing(level, "<customerTid>")

        elif level == "crmback":
            items = render_crmback(query)

        elif level == "crmsched":
            items = render_crmsched(query)

        elif level == "crmprep":
            items = render_crmprep(query)

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
