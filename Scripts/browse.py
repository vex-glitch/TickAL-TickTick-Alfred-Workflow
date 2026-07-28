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
               "overdue": "ctx:smart:overdue",
               "view_overdue": "ctx:smart:overdue",
               "bridges": "ctx:bridges",
               "people": "ctx:people",
               "countdowns": "ctx:countdowns",
               "habits": "ctx:habits",
               "tph": "ctx:tph",
               "content": "ctx:contentpl",
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


# CRM chip legend (search-parity, mirrors display.py MOD_*): ⏎↗️ open in app
# · ⏎⤵️ drill in Alfred · ⏎⚡ fire the flow · ⏎📅 schedule · ⏎✅ complete+log
# · ⏎📝 log line · ⏎📋 copy · ⏎🔥 prep task · ⌘⚡ Actions · ⌥⤵️ hub · ⌃🔙
# back. Chips ride the subtitle tail after "  |  "; chips-only rows skip the
# pipe (Vex convention ruling 2026-07-21).
def _picker_mods(subtitle=None):
    """Explicit mod stamps for picker rows: ⌘ Actions stays live (item vars
    carry the note/task context), the other chords are pinned dead so a
    stray ⇧/⌥ press can't fire the row's xact arg down the wrong canvas
    edge. Dead chords keep the row's OWN subtitle (the old '⏎ picks here'
    filler confused more than it explained); pass subtitle= to say
    something while held."""
    dead = {"arg": "", "valid": False}
    if subtitle:
        dead["subtitle"] = subtitle
    return {
        "cmd":     {"arg": "", "valid": True,  "subtitle": "⌘ Actions"},
        "shift":   dict(dead),
        "alt":     dict(dead),
        "alt+cmd": dict(dead),
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
                    state = "📁 archived · touch-up reopens it"
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
                    subtitle=f"S{n} · {state}  |  ⏎📅",
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
            subtitle=f"New {label}{chip}  |  ⏎⚡",
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
        mods = _picker_mods()
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
            subtitle=f"📅 {_day(t) or 'Not scheduled'}{dep}  |  ⏎✅",
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
                subtitle=f"→ ## Notes{chip}  |  ⏎📝",
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
    """Customer search row: contact + lifetime in the subtitle. ⏎ (and
    ⌥) drill into the customer hub, ⌥⇧ opens the note in TickTick -
    inverted 2026-07-26, Vex: drilling is the frequent move."""
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
        subtitle=(" · ".join(bits) or "No contact yet")
                 + "  |  ⏎⤵️  ⌘⚡  ⌥⇧↗️  ⌃🔙",
        arg=f"xact:crmbrowse:ctx:crmcust:{c['id']}",
        mods={**_picker_mods(),
              "alt": {"arg": "", "valid": True, "subtitle": "Customer hub",
                      "variables": {"browse_ctx": f"ctx:crmcust:{c['id']}"}},
              "alt+shift": {"arg": f"xact:notego:{c['id']}", "valid": True,
                            "subtitle": "Open in TickTick"}},
        variables=_record_vars(c),
    )


def _logbook_row(cr, lb, uid_prefix="crms"):
    """CRM-list tattoo row - delegates to THE unified row builder (Vex
    2026-07-28): one tattoo row, identical in every list."""
    return _unified_logbook_row(cr, lb, uid_prefix)


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
    chip = "" if linked else " · 🔗 unlinked"
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
        subtitle=f"{day or 'Dormant · not scheduled'}{chip}"
                 + ("  |  ⏎↗️  ⌘⚡  ⌥⤵️  ⌃🔙" if hit
                    else "  |  ⏎↗️  ⌘⚡  ⌃🔙"),
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

    def _local_dt(t, key=None):
        due = (t.get(key) if key
               else t.get("dueDate") or t.get("startDate")) or ""
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
        # inversion (Vex 2026-07-27: "⏎ drills everywhere"): linked
        # rows ⏎ → logbook hub, ⌥ drills too (muscle memory), ⌥⇧
        # opens the task in TickTick; unlinked rows keep ⏎↗️ (nothing
        # to drill into)
        if _l:
            mods["alt"] = {"arg": "", "valid": True,
                           "subtitle": "Logbook hub",
                           "variables": {"browse_ctx": f"ctx:crmbook:{_l[2]}"}}
            mods["alt+shift"] = {"arg": f"xact:notego:{t['id']}",
                                 "valid": True,
                                 "subtitle": "Open in TickTick"}
            arg = f"xact:crmbrowse:ctx:crmbook:{_l[2]}"
            chips = "Session done in ⌘  |  ⏎⤵️  ⌘⚡  ⌥⇧↗️"
        else:
            arg = f"open:ticktick:///webapp/#p/{CRM_ID}/tasks/{t['id']}"
            chips = "Session done in ⌘  |  ⏎↗️  ⌘⚡"
        emo = ("💬" if (t.get("title") or "").rstrip().endswith("Consult")
               else "📆")
        rows.append(alfred.item(
            uid=f"wk-{t['id']}",
            title=f"{emo} {when}{clock} · {disp}",
            subtitle=chips, arg=arg, mods=mods,
            variables={"task_id": t["id"], "task_list_id": CRM_ID,
                       "list_id": CRM_ID, "task_title": t.get("title") or "",
                       "item_type": "task"}))
    if not rows:
        rows = [alfred.item(title="📆 Nothing this week",
                            subtitle="The radar below is your move",
                            valid=False)]

    # 💰 the ledger line: what this calendar week logged so far + what is
    # still booked before Sunday (Vex tracks weekly cuts by hand).
    monday = today - _td(days=today.weekday())
    sunday = monday + _td(days=6)
    wk_money, wk_n, _wh, wk_raw = cr.sum_entries(
        cr.all_entries(), monday.isoformat(), sunday.isoformat())
    bk_n, bk_h = 0, 0.0
    for d, t in pool:
        if d.date() > sunday:
            continue
        bk_n += 1
        s, e2 = _local_dt(t, "startDate"), _local_dt(t, "dueDate")
        if s and e2 and e2 > s:
            bk_h += (e2 - s).total_seconds() / 3600.0
    booked_bit = (f"{bk_n} booked" + (f" · {bk_h:g}h" if bk_h else "")
                  if bk_n else "nothing booked")
    # zero state says 0€ - a bare "-" on Monday morning reads like the
    # money display vanished (Vex smoke 2026-07-27)
    rows.insert(0, alfred.item(
        uid="wk-money",
        title=f"💰 {wk_money if wk_money != '-' else '0€'}"
              f"{cr.cut_chip(wk_raw, wk_money)} this week",
        subtitle=f"Mon-Sun logged · ahead: {booked_bit}  |  ⏎⤵️",
        arg=f"xact:crmbrowse:ctx:crmmoney:wk:{monday.isoformat()}",
        mods=_picker_mods()))

    # 🔔 radar: active logbook + nothing scheduled + last entry beyond the
    # crm_radar_days window (env knob, default 14 - crm_cut precedent).
    def _days_env(name):
        try:
            v = int(float(os.environ.get(name, "") or 14))
            return v if v > 0 else 14
        except ValueError:
            return 14
    cutoff = (today - _td(days=_days_env("crm_radar_days"))).isoformat()
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
                subtitle=f"Nothing scheduled · {chip}  |  ⏎📅  ⌥⤵️",
                arg=f"xact:crmnew_go:session::{lb['id']}",
                mods={**_picker_mods(),
                      "alt": {"arg": "", "valid": True,
                              "subtitle": "Logbook hub",
                              "variables": {
                                  "browse_ctx": f"ctx:crmbook:{lb['id']}"}}},
                variables=_record_vars(lb)))

    # 🎣 radar: leads sitting quiet past their own window (crm_lead_days,
    # default 14) - nothing booked anywhere on their logbooks. Leads rot
    # silently; bookings don't.
    lead_days = _days_env("crm_lead_days")
    for ld in cr.records_notes(_areas.LEAD_TAG):
        age = cr.note_age_days(ld)
        if age is None or age < lead_days:
            continue
        if any(cr.next_session_task(lb["id"])
               for lb in cr.customer_logbooks(ld["id"])):
            continue
        rows.append(alfred.item(
            uid=f"wk-lead-{ld['id']}",
            title=ld.get("title") or "",
            subtitle=f"Going cold · {age}d quiet  |  ⏎⤵️  ⌥⇧↗️",
            arg=f"xact:crmbrowse:ctx:crmcust:{ld['id']}",
            mods={**_picker_mods(),
                  "alt": {"arg": "", "valid": True,
                          "subtitle": "Customer hub",
                          "variables": {
                              "browse_ctx": f"ctx:crmcust:{ld['id']}"}},
                  "alt+shift": {"arg": f"xact:notego:{ld['id']}",
                                "valid": True,
                                "subtitle": "Open in TickTick"}},
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
                 + (" · 📁 archived" if archived else "") + "  |  ⏎↗️",
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
        alfred.item(uid="bk-sessphotos", title="📸 Photos",
                    subtitle="Import · file an Eagle selection · browse",
                    arg=f"xact:crmbrowse:ctx:lbphotos:{log_tid}",
                    mods=_picker_mods()),
        alfred.item(uid="bk-eagle", title="🦅 Eagle folder",
                    subtitle="Create if new · open in Eagle",
                    arg=f"xact:eaglefolder:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-cdest",
                    title="🎬 Content potential · "
                          + {"tv": "TV", "fm": "FM", "studio": "Studio",
                             "-": "➖"}.get(
                              cr.content_dest_of(lb.get("content") or ""),
                              "unset"),
                    subtitle="TV · FM · Studio · none",
                    arg=f"xact:cdest:{log_tid}", mods=_picker_mods()),
        alfred.item(uid="bk-editthis", title="🎬 Edit this",
                    subtitle="Whole tree → To edit · task → Edit",
                    arg=f"xact:editthis:{log_tid}", mods=_picker_mods()),
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
    rows.append(alfred.item(
        uid="bk-trash", title="🗑 Delete entry",
        subtitle="Mistakes only · sessions + Eagle go too",
        arg=f"xact:crmtrash:{log_tid}", mods=_picker_mods()))
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
        def row(uid, label, a, b, ctx=None):
            money, n, hours, raw = cr.sum_entries(e, a and a.isoformat(),
                                                  b and b.isoformat())
            extra = ""
            if hours:
                extra = f" · {hours:g}h"
                if raw:
                    sym2 = re.sub(r"[-\d.,\s]", "", money) or "€"
                    rr = raw / hours
                    extra += (f" · ~{int(rr)}{sym2}/h"
                              + cr.cut_rate_chip(rr, sym2))
            span = (f"{a.isoformat() if a else '…'} → "
                    f"{b.isoformat() if b else 'today'}")
            kw = (dict(arg=f"xact:crmbrowse:{ctx}", mods=_picker_mods())
                  if ctx else dict(valid=False))
            return alfred.item(
                uid=uid, title=f"{label} · {money}{cr.cut_chip(raw, money)}"
                               f" · {n} session{'s' if n != 1 else ''}{extra}",
                subtitle=span + ("  |  ⏎⤵️" if ctx else ""), **kw)
        lm0 = lm_end.replace(day=1)
        rows = [
            row("mo-w",  "📆 This week",    monday, None,
                f"ctx:crmmoney:wk:{monday.isoformat()}"),
            row("mo-lw", "📆 Last week",    monday - _td(days=7),
                monday - _td(days=1),
                f"ctx:crmmoney:wk:{(monday - _td(days=7)).isoformat()}"),
            row("mo-m",  "📆 This month",   m0, None,
                f"ctx:crmmoney:mw:{m0.strftime('%Y-%m')}"),
            row("mo-lm", "📆 Last month",   lm0, lm_end,
                f"ctx:crmmoney:mw:{lm0.strftime('%Y-%m')}"),
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

    def _entry_money(x):
        if x["gratis"]:
            return "🖤 free"
        if x["amount"] is None:
            return "-"
        return f"{x['amount']:g}{x['sym'] or '€'}"

    def _hub_alt(tid):
        return {"arg": "", "valid": True, "subtitle": "Logbook hub",
                "variables": {"browse_ctx": f"ctx:crmbook:{tid}"}}

    if sub.startswith("mw:"):   # one month, week by week (ledger shape)
        try:
            y, mo_ = int(sub[3:7]), int(sub[8:10])
            first = _date(y, mo_, 1)
        except ValueError:
            return add_back([alfred.item(title="Bad month", valid=False)],
                            "ctx:crmmoney")
        last = (_date(y + (1 if mo_ == 12 else 0), mo_ % 12 + 1, 1)
                - _td(days=1))
        e = cr.all_entries()
        today = _date.today()
        rows = []
        w = first - _td(days=first.weekday())
        while w <= last and w <= today:
            wend = w + _td(days=6)
            m2, n2, h2, r2 = cr.sum_entries(e, w.isoformat(),
                                            wend.isoformat())
            rows.append(alfred.item(
                uid=f"mw-{w.isoformat()}",
                title=f"📆 wk {w.isocalendar()[1]} · "
                      + (f"{w.strftime('%d %b')}-{wend.strftime('%d %b')}"
                         if w.month != wend.month
                         else f"{w.strftime('%d')}-{wend.strftime('%d %b')}")
                      + f" · {m2}{cr.cut_chip(r2, m2)}"
                      f" · {n2} session{'s' if n2 != 1 else ''}"
                      + (f" · {h2:g}h" if h2 else ""),
                subtitle="The week's sessions  |  ⏎⤵️",
                arg=f"xact:crmbrowse:ctx:crmmoney:wk:{w.isoformat()}",
                mods=_picker_mods()))
            w += _td(days=7)
        rows.reverse()   # newest week on top, ledger habit
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        if not rows:
            rows = [alfred.item(title="Nothing that month", valid=False)]
        return add_back(rows, "ctx:crmmoney")

    if sub.startswith("wk:"):   # one Mon-Sun week, session by session
        try:
            w0 = _date.fromisoformat(sub[3:])
        except ValueError:
            return add_back([alfred.item(title="Bad week", valid=False)],
                            "ctx:crmmoney")
        w0 -= _td(days=w0.weekday())
        wend = w0 + _td(days=6)
        m2, n2, h2, r2 = cr.sum_entries(cr.all_entries(), w0.isoformat(),
                                        wend.isoformat())
        rows = [alfred.item(
            uid="wk-sum",
            title=f"💰 {m2}{cr.cut_chip(r2, m2)}"
                  f" · {n2} session{'s' if n2 != 1 else ''}"
                  + (f" · {h2:g}h" if h2 else ""),
            subtitle=f"Mon {w0.strftime('%d %b')} → Sun "
                     f"{wend.strftime('%d %b')}",
            valid=False)]
        det = sorted((x for x in cr.entries_detailed()
                      if w0.isoformat() <= x["date"] <= wend.isoformat()
                      and (x["amount"] is not None or x["is_s"])),
                     key=lambda x: x["date"])
        for x in det:
            tid = x["lb"].get("id")
            hrs = f" · {x['minutes'] / 60:g}h" if x["minutes"] else ""
            d = _date.fromisoformat(x["date"])
            rows.append(alfred.item(
                uid=f"wke-{tid}-{x['date']}-{x['marker']}",
                title=f"{_entry_money(x)} · {x['lb'].get('title') or ''}"
                      f" · {x['marker']}",
                subtitle=f"{d.strftime('%a %d %b')}{hrs}  |  ⏎⤵️  ⌥⤵️",
                arg=f"xact:crmbrowse:ctx:crmmoney:lb:{tid}",
                mods={**_picker_mods(), "alt": _hub_alt(tid)}))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:crmmoney")

    if sub == "lbs":   # every tattoo with money on it, richest first
        seen, pool = set(), []
        for tag in (_areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG):
            for lb in cr.records_notes(tag):
                if lb["id"] not in seen:
                    seen.add(lb["id"])
                    pool.append(lb)
        raws = {lb["id"]: cr._totals_raw(lb.get("content") or "")[0]
                for lb in pool}
        rows = []
        for lb in sorted((x for x in pool if raws[x["id"]] > 0),
                         key=lambda x: -raws[x["id"]]):
            g = cr.gratis_count(lb.get("content") or "")
            rows.append(alfred.item(
                uid=f"mo-l-{lb['id']}",
                title=lb.get("title") or "Untitled",
                subtitle=cr.paid_summary(lb.get("content") or "")
                         + (f" · 🖤 {g}" if g else "")
                         + "  |  ⏎⤵️  ⌥⤵️",
                arg=f"xact:crmbrowse:ctx:crmmoney:lb:{lb['id']}",
                mods={**_picker_mods(), "alt": _hub_alt(lb["id"])}))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No money logged yet", valid=False)]
        return add_back(rows, "ctx:crmmoney")

    if sub.startswith("lb:"):   # one tattoo: S1 = x, S2 = y … total + rate
        tid = sub[3:]
        lb = next((x for x in cr.records_notes()
                   if x.get("id") == tid), None)
        if not lb:
            return add_back([alfred.item(title="Logbook not found",
                                         subtitle="Run tsy", valid=False)],
                            "ctx:crmmoney")
        content = lb.get("content") or ""
        det = sorted((x for x in cr.entries_detailed()
                      if x["lb"].get("id") == tid),
                     key=lambda x: x["date"])
        mins = sum(x["minutes"] or 0 for x in det)
        total, _n2, sym2, _pre2 = cr._totals_raw(content)
        g = cr.gratis_count(content)
        head = cr.paid_summary(content) + (f" · 🖤 {g}" if g else "")
        if mins:
            head += f" · {mins / 60:g}h"
            if total:
                r = total / (mins / 60.0)
                head += (f" · ~{int(r)}{sym2 or '€'}/h"
                         + cr.cut_rate_chip(r, sym2 or "€"))
        rows = [alfred.item(
            uid="lb-head", title=lb.get("title") or "Logbook",
            subtitle=head + "  |  ⏎⤵️",
            arg=f"xact:crmbrowse:ctx:crmbook:{tid}",
            mods=_picker_mods())]
        for x in det:
            hrs = f" · {x['minutes'] / 60:g}h" if x["minutes"] else ""
            rows.append(alfred.item(
                uid=f"lbe-{x['date']}-{x['marker']}",
                title=f"{x['marker']} · {_entry_money(x)}",
                subtitle=f"{x['date']}{hrs}", valid=False))
        return add_back(rows, "ctx:crmmoney")

    # root: all-time + this-month + this-week + customers + tattoos - five
    # rows, no lists (Vex ruling 2026-07-21: inline tattoos read confusing).
    # Typing = tattoo search (the old habit routes into the lbs sub). Unpaid
    # bookings have no business anywhere on a money screen.
    if query:
        return render_crmmoney("lbs", query)
    e = cr.all_entries()
    money, n, hours, raw = cr.sum_entries(e)
    today = _date.today()
    monday = today - _td(days=today.weekday())
    m0 = today.replace(day=1)
    rate = ""
    if hours:
        import re as _re2
        mnum = _re2.search(r"-?[\d.]+", money.replace(",", ""))
        if mnum:
            r = float(mnum.group(0)) / hours
            symm = _re2.sub(r"[-\d.,\s]", "", money) or "€"
            rate = (f" · {hours:g}h · ~{int(r)}{symm}/h"
                    + cr.cut_rate_chip(r, symm))

    def _sumrow(uid, emoji, label, a, ctx, hint):
        m2, n2, h2, r2 = cr.sum_entries(e, a.isoformat(), None)
        extra = ""
        if h2:
            extra = f" · {h2:g}h"
            if r2:
                sym2 = re.sub(r"[-\d.,\s]", "", m2) or "€"
                rr = r2 / h2
                extra += f" · ~{int(rr)}{sym2}/h" + cr.cut_rate_chip(rr, sym2)
        return alfred.item(
            uid=uid, title=f"{emoji} {label} · {m2}{cr.cut_chip(r2, m2)}"
                           f" · {n2} session{'s' if n2 != 1 else ''}{extra}",
            subtitle=hint, arg=f"xact:crmbrowse:{ctx}",
            mods=_picker_mods())

    pinned = [
        alfred.item(uid="mo-total",
                    title=f"💰 All time · {money}{cr.cut_chip(raw, money)}"
                          f" · {n} session{'s' if n != 1 else ''}{rate}",
                    subtitle="Weekly · monthly · quarterly · yearly  |  ⏎⤵️",
                    arg="xact:crmbrowse:ctx:crmmoney:periods",
                    mods=_picker_mods()),
        _sumrow("mo-month", "📅", "This month", m0,
                f"ctx:crmmoney:mw:{m0.strftime('%Y-%m')}",
                "Week by week  |  ⏎⤵️"),
        _sumrow("mo-week", "📆", "This week", monday,
                f"ctx:crmmoney:wk:{monday.isoformat()}",
                "The week's sessions  |  ⏎⤵️"),
        alfred.item(uid="mo-cust", title="👥 Customers",
                    subtitle="Totals per customer · richest first  |  ⏎⤵️",
                    arg="xact:crmbrowse:ctx:crmmoney:cust",
                    mods=_picker_mods()),
        alfred.item(uid="mo-lbs", title="🎨 Tattoos",
                    subtitle="Money per tattoo · richest first · "
                             "typing up here searches too  |  ⏎⤵️",
                    arg="xact:crmbrowse:ctx:crmmoney:lbs",
                    mods=_picker_mods()),
        alfred.item(uid="mo-csv", title="🧾 CSV export",
                    subtitle="Every dated charge / deposit / refund"
                             " → ~/Downloads",
                    arg="xact:crmcsv", mods=_picker_mods()),
    ]
    return add_back(pinned, "ctx:crmhub")


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
            rate = ((f" · ~{int(k['rate'])}{k['sym']}/h"
                     + cr.cut_rate_chip(k["rate"], k["sym"]))
                    if k["rate"] else "")
            rows.append(alfred.item(
                uid="kp-hours", title=f"🧮 {k['hours']:g}h{rate}"
                + _delta_chip(k["hours"], p and p["hours"]),
                subtitle="Hours in the chair · effective rate · 🫵 = your cut",
                valid=False))
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
                subtitle="Top customer of the period  |  ⏎⤵️",
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
        mods_ = _picker_mods()
        if key in ("thism", "lastm") and a:
            mods_["alt"] = {"arg": "", "valid": True,
                            "subtitle": "Money · week by week",
                            "variables": {
                                "browse_ctx": f"ctx:crmmoney:mw:{a[:7]}"}}
        rows.append(alfred.item(
            uid=f"st-{key}", title=f"📊 {label}",
            subtitle=f"{head}  |  ⏎⤵️"
                     + ("  ⌥💰" if "alt" in mods_ else ""),
            arg=f"xact:crmbrowse:ctx:crmstats:{key}",
            mods=mods_))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmhub")


def render_tph(sub, query):
    """📸 Send-session-photos target picker: today's session first, then
    every active logbook (archived below - late finished/healed shots).
    ⏎ = current session · ⌥⇧ = finished · ⌥ = stage screen (older
    session backlog, consult refs, prep refs, design, healed)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    import photos_bridge as pb
    rows = []
    if pb.photos_running():
        n = pb.selection_count()
        rows.append(alfred.item(
            title=(f"📸 {n} selected in Photos" if n
                   else "📸 Nothing selected in Photos"),
            subtitle="Select shots · ♥ the hero · pick target below",
            valid=False))
    else:
        rows.append(alfred.item(
            title="📸 Photos is not running",
            subtitle="Open Photos · select shots · ♥ the hero",
            valid=False))
    if sub:
        # stage screen for ONE tattoo - the Photos-side backlog road
        lb = next((l for l in cr.records_notes() if l.get("id") == sub),
                  None)
        if lb is None:
            return add_back([alfred.item(title="Logbook not found",
                                         subtitle="Run tsy", valid=False)],
                            "ctx:tph")
        base = cr.logbook_base(lb)
        n = cr.current_snum(lb.get("content") or "", sub)
        rows[0]["subtitle"] = f"Sending the Photos selection to {base}"
        srows, digit = _stage_rows(
            "tphs", n, query, lambda k: f"xact:sessphotos:{sub}:{k}",
            f"Session pics · names get S{n}",
            "Older session · names get S{k}",
            counts=_stage_counts(cr, lb, n))
        rows += srows
        if not digit and query:
            rows = rows[:1] + (fuzz.filter_and_score(
                query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
        return add_back(rows, "ctx:tph")
    # today's session bubbles up: open CRM session task starting today
    # (LOCAL date - raw UTC prefix misses after-midnight/all-day tasks)
    today = datetime.now().date().isoformat()
    todays = set()
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) != _areas.CRM_ID
                or t.get("status", 0) != 0
                or not cr.is_session_task(t.get("title") or "")):
            continue
        due = t.get("startDate") or t.get("dueDate") or ""
        try:
            from filtering import utc_str_to_local_date
            day = utc_str_to_local_date(due) if due else ""
        except Exception:
            day = due[:10]
        if day != today:
            continue
        hit = cr.parse_first_link(t.get("title") or "")
        if hit:
            todays.add(hit[2])

    def lb_row(lb, archived=False):
        # ⌥⇧ is the ONE chord whose canvas edge routes ^xact: args to
        # XAct (892DFDB7); ⌘/⌥ edges drop or misroute custom args -
        # review find 2026-07-25, verified against the plist.
        base = cr.logbook_base(lb)
        is_today = lb.get("id") in todays
        if archived:
            subt, arg = "Archived · ⏎ finished shots · ⌥ pick stage", \
                f"xact:sessphotos:{lb['id']}:finished"
        else:
            subt = "⏎ session pics · ⌥⇧ finished · ⌥ pick stage"
            if is_today:
                subt = "Today's session · " + subt
            arg = f"xact:sessphotos:{lb['id']}"
        return alfred.item(
            uid=f"tph-{lb['id']}", title=f"📸 → {base}", subtitle=subt,
            arg=arg, match=f"{base} photos session",
            mods={"alt+shift": {
                "arg": f"xact:sessphotos:{lb['id']}:finished",
                "subtitle": "Finished-tattoo shots → 05 Finished",
                "valid": True},
                "alt": {
                "arg": "", "valid": True,
                "subtitle": "Stage screen: older S · consult · refs "
                            "· design · healed",
                "variables": {"browse_ctx": f"ctx:tph:{lb['id']}"}}})

    pool = cr.logbook_notes()
    active = [l for l in pool if not cr.logbook_archived(l)]
    active.sort(key=lambda l: l.get("id") not in todays)
    rows += [lb_row(lb) for lb in active]
    rows += [lb_row(lb, archived=True)
             for lb in pool if cr.logbook_archived(lb)]
    if len(rows) == 1:
        rows.append(alfred.item(title="No logbooks yet",
                                subtitle="➕ New tattoo mints one",
                                valid=False))
    if query:
        # state row stays pinned - a query must not hide the warning
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, "ctx:crmhub")


_TRIAGE_STAGES = [
    ("consult", "01 Consultation", "Customer refs"),
    ("prep", "02 Preparation", "Refs found while drawing"),
    ("design", "03 Design", "Final design files"),
    ("s", "04 Sessions", None),          # subtitle built with S<n>
    ("finished", "05 Finished", "Finished-tattoo shots"),
    ("healed", "06 Healed", "Healed shots"),
]


def _stage_counts(cr, lb, n):
    """{stage key: image count} for one tattoo's lifecycle folders, so
    every destination row can say what is already there (Vex 2026-07-28:
    "can descriptions show number of photos in that destination? If none
    it should also say 🖼️0"). None = T9 unplugged, in which case the rows
    say nothing rather than lying with a zero.

    01/02/03/05/06 are folders, so they count by subtree. The session
    buckets are NOT folders - they are the '• S<k> •' token in the item
    name inside 04 Sessions - so they count by name."""
    try:
        import eagle as _eg
        path = _eg.LIBS["crm"][1]
        if not os.path.isdir(path):
            return None
        fid, _lib = cr.eagle_folder_of(lb.get("content") or "")
        if not fid:
            return {}
        node = None

        def find(nodes):
            for f in nodes:
                if f.get("id") == fid:
                    return f
                hit = find(f.get("children") or [])
                if hit:
                    return hit
            return None
        node = find(_eg.disk_folder_tree(path))
        if node is None:
            return {}
        kids = {c.get("name"): c.get("id") for c in node.get("children") or []}
        subtree = _eg.disk_subtree_counts(path)
        names = _eg.disk_names_by_folder(path)
        out = {}
        for key, folder, _sub in _TRIAGE_STAGES:
            cid = kids.get(folder)
            if key == "s":
                continue
            out[key] = subtree.get(cid, 0) if cid else 0
        sess_id = kids.get("04 Sessions")
        pool = names.get(sess_id, []) if sess_id else []
        for k in range(1, max(n, 1) + 1):
            out[f"s{k}"] = sum(1 for nm in pool if f"• S{k} •" in nm)
        out["s"] = out.get(f"s{n}", 0)
        return out
    except Exception:
        return None


def _stage_rows(prefix, n, query, arg_fn, s_default, sk_default,
                suffix="", dsuffix="", mods_fn=None, variables=None,
                counts=None):
    """THE stage-picker skeleton (Vex simplification green 2026-07-26:
    one engine behind the three stage screens - tph / triage /
    imgstage - so a chip change lands everywhere at once). Callers
    pin their own head row, pass their arg shape + trimmings, then
    fuzz. Returns the stage rows (+ the typed-digit S<k> row when the
    query is one)."""
    def extras(key):
        out = {}
        if mods_fn:
            out["mods"] = mods_fn(key)
        if variables is not None:
            out["variables"] = variables
        return out
    def chip(key):
        if counts is None:
            return ""
        return f"  ·  🖼 {counts.get(key, 0)}"
    rows = []
    for key, folder, subtxt in _TRIAGE_STAGES:
        rows.append(alfred.item(
            uid=f"{prefix}-{key}",
            title=f"→ {folder}" + (f" · S{n}" if key == "s" else ""),
            subtitle=(subtxt or s_default) + chip(key) + suffix,
            arg=arg_fn(key), **extras(key)))
    m = re.match(r"^s?(\d+)$", (query or "").strip(), re.I)
    if m:
        k = int(m.group(1))
        rows.append(alfred.item(
            uid=f"{prefix}-sn", title=f"→ 04 Sessions · S{k}",
            subtitle=sk_default.format(k=k) + chip(f"s{k}") + dsuffix,
            arg=arg_fn(f"s{k}"), **extras(f"s{k}")))
        return rows, True
    # Every EARLIER session as a real row (Vex 2026-07-28: standing on
    # S5 there was "no way to import a photo as a photo of session 3").
    # The typed-digit row above still works and still reaches sessions
    # beyond n - this just stops the feature being invisible. Newest
    # first: the session you most likely mean is the one just gone.
    for k in range(n - 1, 0, -1):
        rows.append(alfred.item(
            uid=f"{prefix}-s{k}", title=f"→ 04 Sessions · S{k}",
            subtitle=sk_default.format(k=k) + chip(f"s{k}") + dsuffix,
            arg=arg_fn(f"s{k}"), **extras(f"s{k}")))
    return rows, False


def render_triage(sub, query):
    """🦅 Eagle triage: file the CURRENT Eagle selection into a tattoo's
    lifecycle folder (Review backlog, Inbox strays, any misfile).
    Selection must be made in the CRM library - applying never switches
    (a switch would drop the selection). Two screens: pick tattoo →
    pick stage; ⌘ on a stage also attaches the FIRST selected item to
    the session task."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    import eagle
    try:
        eagle.ensure_running(launch=False)
        lib = eagle.current_library()
        sel = eagle.selected_items()
        state = f"🦅 {len(sel)} selected · {lib}"
        if lib != eagle.LIBS["crm"][0]:
            state += " · OPEN THE CRM LIBRARY"
    except eagle.EagleError as e:
        state = f"🦅 {e}"
    rows = [alfred.item(title=state,
                        subtitle="Select items in Eagle · pick below",
                        valid=False)]
    if not sub:
        rows.append(alfred.item(
            uid="tri-promote", title="🎬 Promote selection",
            subtitle="Picked shots → To edit (tattoo inferred)",
            arg="xact:promotesel", mods=_picker_mods()))
        def lb_row(lb, archived=False):
            base = cr.logbook_base(lb)
            return alfred.item(
                uid=f"tri-{lb['id']}", title=f"🦅 → {base}",
                subtitle=("Archived · " if archived else "") + "⏎ pick stage",
                arg=f"xact:crmbrowse:ctx:triage:{lb['id']}",
                match=f"{base} triage file", mods=_picker_mods())
        pool = cr.logbook_notes()
        rows += [lb_row(lb) for lb in pool if not cr.logbook_archived(lb)]
        rows += [lb_row(lb, archived=True)
                 for lb in pool if cr.logbook_archived(lb)]
        if query:
            # state row stays pinned - the OPEN-CRM warning must survive
            rows = rows[:1] + (fuzz.filter_and_score(
                query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
        return add_back(rows, "ctx:crmhub")
    # stage screen for one logbook
    lb = next((l for l in cr.records_notes() if l.get("id") == sub), None)
    if lb is None:
        return add_back([alfred.item(title="Logbook not found",
                                     subtitle="Run tsy", valid=False)],
                        "ctx:triage")
    base = cr.logbook_base(lb)
    n = cr.current_snum(lb.get("content") or "", sub)
    rows[0]["subtitle"] = f"Filing into {base}"
    srows, digit = _stage_rows(
        "tris", n, query, lambda k: f"xact:triage:{sub}:{k}",
        f"Session pics · names get S{n}",
        "Older session · names get S{k}",
        counts=_stage_counts(cr, lb, n),
        suffix="  ·  ⌥⇧ +attach to task", dsuffix="  ·  ⌥⇧ +attach",
        mods_fn=lambda k: {"alt+shift": {
            "arg": f"xact:triage:{sub}:{k}:attach",
            "subtitle": "File + first pick → task attachment",
            "valid": True}})
    rows += srows
    if not digit and query:
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, "ctx:triage")


_CPL_STATES = [("📸edit", "✂️", "Editing"), ("📸post", "📤", "Ready to post"),
               ("📸raw", "🎞", "Raw · undecided")]


_LBPICK_VERBS = {
    "eaglefolder": ("🦅", "Create if new · open in Eagle"),
    "cdest": ("🎬", "Set TV · FM · Studio · none"),
    "editthis": ("🎬", "Whole tree → To edit"),
    "sessphotos": ("📸", "Photos selection → current session"),
}


def render_lbpick(verb, query, scope=""):
    """Generic logbook picker: one screen, any pipeline verb - the
    'Manage content' road so everything Eagle is reachable from the
    Content pipeline too, not just from CRM.

    scope='unset' = the 🎬 Unclassified drain (Vex smoke 2026-07-28:
    the radar row promised unclassified and delivered ALL logbooks, so
    a just-classified tattoo still sat in the list and the drain looked
    broken). Filtered screens back out to the Content root they came
    from, not to Manage."""
    home = "ctx:contentpl" if scope == "unset" else "ctx:cmanage"
    gate = _records_gate()
    if gate:
        return add_back(gate, home)
    icon, subt = _LBPICK_VERBS.get(verb, ("", ""))
    if not icon:
        return add_back([alfred.item(title=f"Unknown action {verb!r}",
                                     valid=False)], home)
    import crm_records as cr
    rows = []
    for lb in cr.logbook_notes():
        if scope == "unset" and cr.content_dest_of(lb.get("content") or ""):
            continue
        rows.append(alfred.item(
            uid=f"lbp-{lb['id']}",
            title=f"{icon} {cr.logbook_base(lb)}",
            subtitle=("Archived · " if cr.logbook_archived(lb) else "")
                     + subt,
            # :drain = classify, then reopen this list one shorter
            arg=f"xact:{verb}:{lb['id']}"
                + (":drain" if scope == "unset" else ""),
            match=f"{cr.logbook_base(lb)}"))
    if not rows:
        rows = [alfred.item(
            title="🎬 All classified" if scope == "unset" else "No logbooks yet",
            subtitle="Nothing left to drain" if scope == "unset"
                     else "➕ New tattoo mints one", valid=False)]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, home)


def render_cmanage(query):
    """🎛 Manage content - EVERY pipeline action on one screen (Vex:
    'anything related to Eagle from the Content Pipeline list as well
    as from CRM'). Picker roads hop, selection/global roads fire."""
    def hop(uid, title, subtitle, ctx):
        return alfred.item(uid=uid, title=title, subtitle=subtitle,
                           arg=f"xact:crmbrowse:{ctx}", mods=_picker_mods())
    rows = [
        hop("cm-photos", "📸 Send session photos",
            "Photos selection → any stage (⌥ on the tattoo)", "ctx:tph"),
        hop("cm-triage", "🦅 Eagle triage",
            "Eagle selection → any tattoo stage", "ctx:triage"),
        hop("cm-folder", "🦅 Create Eagle folder",
            "Pick tattoo → skeleton + open", "ctx:lbpick:eaglefolder"),
        hop("cm-cdest", "🎬 Content potential",
            "Pick tattoo → TV · FM · Studio · none", "ctx:lbpick:cdest"),
        hop("cm-edit", "🎬 Edit this",
            "Pick tattoo → whole tree → To edit", "ctx:lbpick:editthis"),
        alfred.item(uid="cm-promote", title="🎬 Promote Eagle selection",
                    subtitle="CRM picks → To edit",
                    arg="xact:promotesel", mods=_picker_mods()),
        alfred.item(uid="cm-file", title="📥 File edited shots",
                    subtitle="Intake → To post · task slides",
                    arg="xact:filedited", mods=_picker_mods()),
        alfred.item(uid="cm-star", title="⭐ Portfolio Eagle selection",
                    subtitle="Edits → Tattoo Portfolio shelf",
                    arg="xact:portfolio", mods=_picker_mods()),
        alfred.item(uid="cm-sweep", title="🦅 Eagle sweep",
                    subtitle="Missing skeletons + re-file archived folders",
                    arg="xact:eaglesweep", mods=_picker_mods()),
    ]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:contentpl")


def _cpl_counts():
    """Open pipeline-task counts per 📸 tag across ALL content lists."""
    import areas as _ar
    pids = _ar.CONTENT_PIDS
    out = {tag: 0 for tag, _i, _w in _CPL_STATES}
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) not in pids
                or t.get("status", 0) != 0):
            continue
        tags = {str(x).lower() for x in (t.get("tags") or [])}
        for tag in out:
            if tag in tags:
                out[tag] += 1
    return out


def render_cstats(query):
    """📊 Content pipeline stats: queue totals + TV/FM split, posted /
    retired by month (completed content tasks via v2 - 365d window),
    minted-per-month, oldest item stuck in To edit. Queue counts render
    from cache; history needs the v2 login and says so when missing."""
    import areas as _ar
    LIBS = {_ar.CONTENT_TV_ID: "TV", _ar.CONTENT_FM_ID: "FM",
            _ar.CONTENT_STUDIO_ID: "Studio"}
    tasks = [t for t in cache_store.get("all_tasks") or []
             if (t.get("_projectId") or t.get("projectId")) in LIBS
             and t.get("status", 0) == 0]

    def tags_of(t):
        return {str(x).lower() for x in (t.get("tags") or [])}

    rows = []
    chips = _cpl_counts()
    per_lib = {"TV": 0, "FM": 0, "Studio": 0}
    for t in tasks:
        if tags_of(t) & {s[0] for s in _CPL_STATES}:
            per_lib[LIBS[t.get("_projectId") or t.get("projectId")]] += 1
    rows.append(alfred.item(
        uid="cs-now", title=f"🎞 {chips['📸raw']} raw · ✂️ {chips['📸edit']} "
        f"editing · 📤 {chips['📸post']} to post",
        subtitle=f"Open now · 📺 TV {per_lib['TV']} · 🖋️ FM {per_lib['FM']}"
                 f" · 🏷 Studio {per_lib['Studio']}",
        valid=False))
    # oldest thing stuck in editing - the actionable number
    oldest = None
    for t in tasks:
        if "📸edit" in tags_of(t) and t.get("createdTime"):
            if oldest is None or t["createdTime"] < oldest["createdTime"]:
                oldest = t
    if oldest:
        try:
            born = datetime.fromisoformat(
                oldest["createdTime"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - born).days
            mk = re.match(r"^\[(.*?)\]", (oldest.get("title") or "").strip())
            nm = mk.group(1) if mk else (oldest.get("title") or "")[:30]
            rows.append(alfred.item(
                uid="cs-old", title=f"⏳ Longest in editing · {nm}",
                subtitle=f"{days} days in To edit", valid=False))
        except Exception:
            pass
    # history: completed content tasks = posted (📸post) / retired (📸raw)
    try:
        import api_v2
        done = api_v2.TickTickV2().get_completed(days=365, limit=500)
        mine = [t for t in done or []
                if t.get("projectId") in LIBS]
        months = {}
        posted_all = retired_all = sent_all = 0
        for t in mine:
            mo = (t.get("completedTime") or "")[:7]
            if not mo:
                continue
            tags = {str(x).lower() for x in (t.get("tags") or [])}
            bucket = months.setdefault(mo, [0, 0, 0, 0])
            if "📸post" in tags:
                bucket[0] += 1
                posted_all += 1
            elif "📸studio" in tags:
                bucket[3] += 1
                sent_all += 1
            elif "📸raw" in tags:
                bucket[1] += 1
                retired_all += 1
            else:
                bucket[2] += 1
        rows.append(alfred.item(
            uid="cs-alltime",
            title=f"✅ {posted_all} posted"
                  + (f" · 🏷 {sent_all} sent" if sent_all else "")
                  + f" · ➖ {retired_all} retired",
            subtitle="Completed content tasks · last 365 days",
            valid=False))
        for mo in sorted(months, reverse=True)[:12]:
            p, r, o, s = months[mo]
            bits = [f"✅ {p} posted"] + ([f"🏷 {s} sent"] if s else []) \
                + ([f"➖ {r} retired"] if r else []) \
                + ([f"☑️ {o} other"] if o else [])
            rows.append(alfred.item(
                uid=f"cs-{mo}", title=f"📅 {mo} · " + " · ".join(bits),
                subtitle="", valid=False))
    except Exception as e:
        rows.append(alfred.item(
            title="✅ Posted history unavailable",
            subtitle=f"Needs Attachment Login · {type(e).__name__}",
            valid=False))
    # minted per month from open tasks' createdTime (best-effort)
    minted = {}
    for t in tasks:
        mo = (t.get("createdTime") or "")[:7]
        if mo and tags_of(t) & {s[0] for s in _CPL_STATES}:
            minted[mo] = minted.get(mo, 0) + 1
    if minted:
        top = sorted(minted, reverse=True)[:3]
        rows.append(alfred.item(
            uid="cs-minted",
            title="➕ New in pipeline · "
                  + " · ".join(f"{mo} {minted[mo]}" for mo in top),
            subtitle="Open tasks by creation month", valid=False))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:contentpl")


def _cpl_task_row(t, tag, icon, word, lib, chip):
    """One content-task row: ⏎ opens the Eagle folder cross-library,
    ⌥⇧ = posted (Post rows) / retire (Raw rows)."""
    title = (t.get("title") or "").strip()
    # markdown of ANY scheme - legacy tasks link http://localhost:41595
    mk = re.match(r"^\[(.*?)\]\(\S+?\)$", title)
    base = (mk.group(1).strip() if mk
            else re.sub(r"\s*eagle://\S+", "", title).strip())
    m = (re.search(r"eagle://folder/([^)\s]+)", title)
         or re.search(r"localhost:41595/folder\?id=([A-Za-z0-9]+)", title))
    open_lib = "crm" if tag == "📸raw" else lib
    arg = f"xact:eaglego:{open_lib}:{m.group(1)}" if m else ""
    mods = dict(_picker_mods())
    sub = f"{word} · {chip}" + (" · ⏎ folder" if m else "") + " · ⌘⚡"
    if tag == "📸post":
        mods["alt+shift"] = {"arg": f"xact:posted:{t['id']}",
                             "subtitle": "Mark POSTED · shelf clears",
                             "valid": True}
        sub += " · ⌥⇧ posted"
    elif tag == "📸raw":
        mods["alt+shift"] = {"arg": f"xact:cretire:{t['id']}",
                             "subtitle": "Retire · logbook 🎬 → ➖",
                             "valid": True}
        sub += " · ⌥⇧ retire"
    pid = t.get("_projectId") or t.get("projectId") or ""
    return alfred.item(uid=f"cpl-{t['id']}", title=f"{icon} {base}",
                       subtitle=sub, arg=arg, valid=bool(arg),
                       match=f"{base} {word}", mods=mods,
                       # task vars → ⌘ Actions opens ON this task
                       # (↗️ Open row 1, focus, tags - Vex smoke ask)
                       variables={"task_id": t["id"], "task_list_id": pid,
                                  "list_id": pid,
                                  "task_title": t.get("title") or "",
                                  "item_type": "task"})


def render_contentpl(ids, query):
    """🎬 Pipelines - three levels (Vex smoke 2026-07-26: never a flat
    both-lists dump). Root: the three boards 📺 TV / 🖋️ FM / 🏷 Studio,
    plus the 🎬 Unclassified drain and 📥 intake row when either has
    something to say. Per-library: Open in TickTick + the tag queues
    (To post / To edit / Raw / All). Queue: task rows. Renders from the
    TickTick cache, Eagle not needed to look.
    Customers / Logbooks / stats / Manage left this screen when the home
    unified (Vex 2026-07-28) - they are top-level rows now."""
    import areas as _ar
    import eagle as _eagle
    LIBS = {"tv": (_ar.CONTENT_TV_ID, "📺", "TV"),
            "fm": (_ar.CONTENT_FM_ID, "🖋️", "FM"),
            "studio": (_ar.CONTENT_STUDIO_ID, "🏷", "Studio")}
    lib = ids[0] if ids else ""
    queue = ids[1] if len(ids) > 1 else ""

    def hop(uid, title, subtitle, ctx):
        return alfred.item(uid=uid, title=title, subtitle=subtitle,
                           arg=f"xact:crmbrowse:{ctx}", mods=_picker_mods())

    if lib not in LIBS:
        # root: chip state row (⏎ stats) + global actions + library rows
        pending = 0
        for k in ("tv", "fm", "studio"):
            try:
                pending += len([f for f in os.listdir(_eagle.INTAKE[k])
                                if not f.startswith(".") and os.path.isfile(
                                    os.path.join(_eagle.INTAKE[k], f))])
            except OSError:
                pass
        rows = []
        # 🎬 radar: Vex rule 2026-07-28 - no logbook stays unclassified.
        # Renders ONLY while offenders exist; the mandatory at-birth
        # picker keeps new ones out, this row drains the legacy 32.
        try:
            import crm_records as _cr
            unset = [lb for lb in _cr.logbook_notes()
                     if not _cr.content_dest_of(lb.get("content") or "")]
        except Exception:
            unset = []
        if unset:
            na = sum(1 for lb in unset if not _cr.logbook_archived(lb))
            rows.append(hop(
                "cpl-unset", f"🎬 Unclassified · {len(unset)}",
                f"{na} active · {len(unset) - na} archived · "
                "pick tattoo → classify", "ctx:lbpick:cdest:unset"))
        # Intake is time-sensitive, so it stays visible HERE as well as
        # in 🎛 Manage (Vex's rows-in-both-places rule) - but only when
        # the folders actually hold something.
        if pending:
            rows.append(alfred.item(
                uid="cpl-file", title=f"📥 File edited shots ({pending})",
                subtitle="Intake → To post · names · task → Post",
                arg="xact:filedited", mods=_picker_mods()))
        for k, (pid, chip, word) in LIBS.items():
            n = sum(1 for t in cache_store.get("all_tasks") or []
                    if (t.get("_projectId") or t.get("projectId")) == pid
                    and t.get("status", 0) == 0
                    and {str(x).lower() for x in (t.get("tags") or [])}
                    & {s[0] for s in _CPL_STATES})
            rows.append(hop(f"cpl-{k}", f"{chip} {word} Pipeline",
                            f"{n} in the pipeline · ⏎ queues",
                            f"ctx:contentpl:{k}"))
        if query:
            rows = rows[:1] + (fuzz.filter_and_score(
                query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
        return add_back(rows, "ctx:crmhub")

    pid, chip, word = LIBS[lib]
    tasks = [t for t in cache_store.get("all_tasks") or []
             if (t.get("_projectId") or t.get("projectId")) == pid
             and t.get("status", 0) == 0]

    def tags_of(t):
        return {str(x).lower() for x in (t.get("tags") or [])}

    if not queue:
        # per-library screen: Open in TickTick + the tag queues
        def count(tag):
            return sum(1 for t in tasks if tag in tags_of(t))
        rows = [alfred.item(
            uid="cpq-open", title="↗️ Open in TickTick",
            subtitle=f"The Content PL · {word} list",
            arg=f"open:https://ticktick.com/webapp/#p/{pid}/tasks",
            mods=_picker_mods())]
        for key, tag, icon, label in (
                ("post", "📸post", "📤", "To post"),
                ("edit", "📸edit", "✂️", "To edit"),
                ("raw", "📸raw", "🎞", "Raw")):
            rows.append(hop(f"cpq-{key}", f"{icon} {label}",
                            f"{count(tag)} here",
                            f"ctx:contentpl:{lib}:{key}"))
        rows.append(hop("cpq-all", "🗂 All",
                        f"{len([t for t in tasks if tags_of(t) & {s[0] for s in _CPL_STATES}])} entries flat",
                        f"ctx:contentpl:{lib}:all"))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:contentpl")

    # queue screen: task rows for one tag (or all, grouped by state)
    KEY2TAG = {"post": "📸post", "edit": "📸edit", "raw": "📸raw"}
    rows = []
    for tag, icon, wrd in _CPL_STATES:
        if queue != "all" and KEY2TAG.get(queue) != tag:
            continue
        rows += [_cpl_task_row(t, tag, icon, wrd, lib, chip)
                 for t in tasks if tag in tags_of(t)]
    if not rows:
        rows = [alfred.item(title="Queue empty",
                            subtitle="🎬 Edit this on a logbook feeds it",
                            valid=False)]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, f"ctx:contentpl:{lib}")


def _img_counts():
    """{eagle folder id: images in its subtree} for the CRM library, or
    None when the T9 is unplugged (no chip beats a lying '🖼 0')."""
    try:
        import eagle as _eg
        path = _eg.LIBS["crm"][1]
        if not os.path.isdir(path):
            return None
        return _eg.disk_subtree_counts(path)
    except Exception:
        return None


def _logbook_state(cr, lb):
    """(circle, trailing date) - Vex's legend 2026-07-28:
    🔴 archived · 🟡 active, nothing booked · 🟢 scheduled (+ the date)."""
    if cr.logbook_archived(lb):
        return "🔴", ""
    nxt = cr.next_session_task(lb["id"])
    if nxt and nxt[0]:
        return "🟢", nxt[0]
    return "🟡", ""


def _unified_logbook_row(cr, lb, uid_prefix="ulb", ret="", counts=None):
    """THE tattoo row - one builder for every list that shows tattoos
    (Vex unified home 2026-07-28: "one customers and logbook", the two
    worlds reachable by chord instead of by being in a different tree).

        🎨 Bruno • Dog Portrait 🟡 600€ • 2 Sess
        🎬 TV · 🖼 13  |  ⌥ CRM  ⇧ Content  |  ⌘⚡ ⏎↗️ ⌥⌘🔗 ⌃🔙

    Chords, all shipping on existing canvas: ⏎ opens the note in
    TickTick, ⌥ drills the CRM hub (mod variables), ⇧ drills the Eagle
    hub (⇧ rides modComplete, which passes the argument to dispatch and
    its xact: passthrough - verified 2026-07-28), ⌘ is the full Actions
    menu, ⌥⌘ copies the Eagle link, ⌃ backs out."""
    base = cr.logbook_base(lb)
    name = re.sub(r"^[🎨🏛️\s]+", "", lb.get("title") or "").strip() or base
    circle, when = _logbook_state(cr, lb)
    money, sess = cr.totals(lb.get("content") or "")
    head = [b for b in (money if money and money != "-" else "",
                        f"{sess} Sess" if sess else "",
                        when) if b]
    dest = cr.content_dest_of(lb.get("content") or "")
    dchip = {"tv": "🎬 TV", "fm": "🎬 FM", "studio": "🎬 Studio",
             "-": "🎬 ➖"}.get(dest, "🎬 unset")
    fid, _l = cr.eagle_folder_of(lb.get("content") or "")
    if counts is None:
        counts = _img_counts()
    n_img = (counts or {}).get(fid) if fid else None
    sub = [dchip]
    if n_img is not None:
        sub.append(f"🖼 {n_img}")
    elif not fid:
        sub.append("🦅 no folder yet")
    mods = _picker_mods()
    mods["alt"] = {"arg": "", "valid": True, "subtitle": "⌥ CRM hub",
                   "variables": {"browse_ctx": f"ctx:crmbook:{lb['id']}"}}
    mods["shift"] = {"arg": f"xact:crmbrowse:ctx:lbeagle:{lb['id']}{ret}",
                     "valid": True, "subtitle": "⇧ Content · Eagle folders"}
    # ⌥⌘ copies the TICKTICK link here (Vex 2026-07-28) - the Eagle link
    # is one step deeper, on ⇧ Content, where Eagle is what you are
    # looking at. Same chord, right link for the world you are in.
    mods["alt+cmd"] = {"arg": f"copy:{_open_note_arg(lb['id'])[5:]}",
                       "valid": True, "subtitle": "🔗 Copy TickTick link"}
    return alfred.item(
        uid=f"{uid_prefix}-{lb['id']}",
        title=f"🎨 {name}  {circle} " + " • ".join(head),
        subtitle=" · ".join(sub) + "  |  ⌥ CRM  ⇧ Content  |  ⌘⚡ ⏎↗️"
                 + ("  ⌥⌘🔗" if fid else "") + "  ⌃🔙",
        arg=_open_note_arg(lb["id"]),
        match=base, mods=mods, variables=_record_vars(lb))


def _content_logbook_row(cr, lb, ret=""):
    """Content-list tattoo row - delegates to THE unified row builder.
    ret still threads the ⌃-back tail into the ⇧ Eagle drill."""
    return _unified_logbook_row(cr, lb, "clb", ret)


def render_clbs(query):
    """🎨 Content > Logbooks - every tattoo, ⏎ = its Eagle folders."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:contentpl")
    import crm_records as cr
    rows = [_content_logbook_row(cr, lb) for lb in cr.logbook_notes()]
    if not rows:
        rows = [alfred.item(title="No logbooks yet",
                            subtitle="➕ New tattoo mints one", valid=False)]
    elif query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:contentpl")


def render_ccust(ids, query):
    """👥 Content > Customers - birdseye only: customer → the tattoos
    they did (light rows, never the heavy CRM customer hub)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:contentpl")
    import crm_records as cr
    if ids:
        rows = [_content_logbook_row(cr, lb, f":cu:{ids[0]}")
                for lb in cr.customer_logbooks(ids[0])]
        if not rows:
            rows = [alfred.item(title="No tattoos yet",
                                subtitle="Nothing to browse", valid=False)]
        elif query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"]) or rows
        return add_back(rows, "ctx:ccust")
    rows, seen = [], set()
    for c in (cr.records_notes(_areas.CUSTOMER_TAG)
              + cr.records_notes(_areas.LEAD_TAG)):
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        _m, k, _n = cr.lifetime(c["id"])
        rows.append(alfred.item(
            uid=f"ccu-{c['id']}", title=c.get("title") or "Untitled",
            subtitle=(f"{k} tattoo{'s' if k != 1 else ''}" if k
                      else "no tattoos yet") + "  |  ⏎⤵️  ⌃🔙",
            arg=f"xact:crmbrowse:ctx:ccust:{c['id']}",
            mods=_picker_mods(), variables=_record_vars(c)))
    if not rows:
        rows = [alfred.item(title="No customers yet", valid=False)]
    elif query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:contentpl")


def render_lbeagle(ids, query):
    """🦅 Folder screen - ONE tattoo's Eagle reality, straight from
    DISK (closed libraries read fine - no switching just to look).
    Counts per stage folder, honest zeroes, per-session sub-rows under
    04 Sessions, create row when no folder exists. ⏎ on a folder =
    peek:<fid> → the Grid View (canvas phase_grid)."""
    log_tid = ids[0]
    tail = ids[1:]
    if tail[:1] == ["hub"]:
        back = f"ctx:crmbook:{log_tid}"
    elif tail[:1] == ["cu"] and len(tail) > 1:
        back = f"ctx:ccust:{tail[1]}"
    else:
        back = "ctx:clbs"
    gate = _records_gate()
    if gate:
        return add_back(gate, back)
    import crm_records as cr
    import eagle
    lb = next((l for l in cr.records_notes() if l.get("id") == log_tid), None)
    if lb is None:
        return add_back([alfred.item(title="Logbook not found",
                                     subtitle="Run tsy", valid=False)], back)
    base = cr.logbook_base(lb)
    fid, lib = cr.eagle_folder_of(lb.get("content") or "")
    if not fid:
        return add_back([alfred.item(
            uid="lbe-none", title=f"🦅 {base} - no Eagle folder yet",
            subtitle="⏎ create the skeleton + open in Eagle",
            arg=f"xact:eaglefolder:{log_tid}", mods=_picker_mods(),
            variables=_record_vars(lb))], back)
    lib = lib or "crm"
    lib_path = eagle.LIBS.get(lib, eagle.LIBS["crm"])[1]
    _LBE_STAGE_KEYS = {"01 Consultation": "consult",
                       "02 Preparation": "prep", "03 Design": "design",
                       "04 Sessions": "s", "05 Finished": "finished",
                       "06 Healed": "healed"}

    def _lbe_mods(stage=None, link=""):
        # ⌥⇧ is the one free executing chord (canvas fact): on STAGE
        # rows it imports the Photos selection INTO that stage (Vex
        # ask 2026-07-26); the head row keeps 🎬 Edit this. ⌥⌘ rides
        # the modURL copy chain (copies whatever arg it gets) - the
        # folder's eagle:// link, zero canvas.
        m = _picker_mods()
        if stage:
            m["alt+shift"] = {"arg": f"xact:sessphotos:{log_tid}:{stage}",
                              "valid": True,
                              "subtitle": "📸 Photos selection → here"}
        else:
            m["alt+shift"] = {"arg": f"xact:editthis:{log_tid}",
                              "valid": True, "subtitle": "🎬 Edit this"}
        if link:
            m["alt+cmd"] = {"arg": f"copy:eagle://folder/{link}",
                            "valid": True,
                            "subtitle": "🔗 Copy Eagle link"}
        return m

    head = alfred.item(uid="lbe-open", title=f"🦅 {base}",
                       subtitle="Whole folder, in Eagle"
                               "  |  ⏎↗️  ⌘⚡  ⌥⇧🎬  ⌥⌘🔗  ⌃🔙",
                       arg=f"xact:eaglego:{lib}:{fid}",
                       mods=_lbe_mods(link=fid),
                       variables=_record_vars(lb))
    # The 📸 door lives on the CONTENT side too (Vex 2026-07-28: photo
    # work is both worlds, so it belongs under ⌥ AND ⇧).
    photos = alfred.item(
        uid="lbe-photos", title="📸 Photos",
        subtitle="Import · file an Eagle selection · browse",
        arg=f"xact:crmbrowse:ctx:lbphotos:{lb['id']}",
        mods=_picker_mods(), variables=_record_vars(lb))
    try:
        root, all_ids = eagle.disk_subtree_ids(lib_path, fid)
        items = eagle.disk_items_in(lib_path, all_ids)
    except eagle.EagleError as e:
        return add_back([head, photos, alfred.item(title=f"🦅 {e}",
                                                   subtitle="T9 plugged in?",
                                                   valid=False)], back)
    ret_ctx = "ctx:lbeagle:" + ":".join(ids)

    def peek_arg(cid, sess="", direct=False):
        # The whole grid context rides b64 - the ⏎ road trampolines
        # through ET GridPeek (fresh session, row variables drop).
        import base64
        payload = json.dumps({"fid": cid, "sess": sess, "lib": lib,
                              "lb": log_tid, "ret": ret_ctx,
                              "direct": direct})
        return "xact:peek:" + base64.b64encode(
            payload.encode()).decode()

    def _sub(node):
        out = {node["id"]}
        for ch in node.get("children") or []:
            out |= _sub(ch)
        return out

    order = {n: i for i, n in enumerate(eagle.SKELETON)}
    kids = sorted(root.get("children") or [],
                  key=lambda c: (order.get(c.get("name"), 99),
                                 c.get("name") or ""))
    rows = [head, photos]
    for c in kids:
        cid, name = c["id"], c.get("name") or "?"
        # count over the child's SUBTREE - matches exactly what its
        # grid peek shows (manual nesting counts; review find)
        cset = _sub(c)
        shots = list({it["id"]: it for it in items
                      if set(it.get("folders") or []) & cset}.values())
        n = len(shots)
        skey = _LBE_STAGE_KEYS.get(name)
        chord = "⌥⇧📸" if skey else "⌥⇧🎬"
        rows.append(alfred.item(
            uid=f"lbe-{cid}", title=name,
            subtitle=f"🖼️ {n}"
                     + (f"  |  ⏎🖼  ⌘⚡  {chord}  ⌥⌘🔗  ⌃🔙" if n
                        else f"  |  {chord}  ⌥⌘🔗  ⌃🔙"),
            arg=peek_arg(cid), valid=bool(n),
            mods=_lbe_mods(skey, cid), variables=_record_vars(lb)))
        if name == "04 Sessions" and n:
            sess = {}
            for it in shots:
                m = re.search(r"• S(\d+) •", it.get("name") or "")
                sess.setdefault(int(m.group(1)) if m else 0, []).append(it)
            for k in sorted(sess):
                label = f"S{k}" if k else "unnumbered"
                rows.append(alfred.item(
                    uid=f"lbe-{cid}-s{k}", title=f"   · {label}",
                    subtitle=f"🖼️ {len(sess[k])}  |  ⏎🖼  ⌥⇧📸  ⌥⌘🔗  ⌃🔙",
                    arg=peek_arg(cid, f"s{k}"),
                    mods=_lbe_mods(f"s{k}" if k else "s", cid),
                    variables=_record_vars(lb)))
    # honest strays: shots dragged straight into the tattoo root folder
    # (outside the 01-06 skeleton) get their own row (review find)
    strays = list({it["id"]: it for it in items
                   if root["id"] in (it.get("folders") or [])}.values())
    if strays:
        ns = len(strays)
        rows.append(alfred.item(
            uid=f"lbe-{root['id']}-strays", title="· unfiled",
            subtitle=f"🖼️ {ns} · folder root  |  ⏎🖼  ⌥⇧🎬  ⌃🔙",
            arg=peek_arg(root["id"], direct=True),
            mods=_lbe_mods(), variables=_record_vars(lb)))
    if query:
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, back)


def render_imgstage(query):
    """Stage picker for ONE grid shot (the grid's ⌘⇧ road): full
    lifecycle stages, current session default, typed digit = older
    session - rows fire xact:imgmove:<stage>, the shot rides img_path
    (re-carried on every row so the verb never loses it)."""
    import crm_records as cr
    path = os.environ.get("img_path") or ""
    log_tid = os.environ.get("lb_tid") or ""
    back = os.environ.get("peek_ret") or "ctx:clbs"
    lb = next((l for l in cr.records_notes() if l.get("id") == log_tid), None)
    if not (path and lb):
        return add_back([alfred.item(title="Lost the image context",
                                     subtitle="Re-enter from the grid",
                                     valid=False)], back)
    n = cr.current_snum(lb.get("content") or "", log_tid)
    carry = {"img_path": path, "lb_tid": log_tid, "peek_ret": back}
    rows = [alfred.item(title=f"🖼 {os.path.basename(path)}",
                        subtitle=f"File into a stage of {cr.logbook_base(lb)}",
                        valid=False)]
    srows, digit = _stage_rows(
        "imgs", n, query, lambda k: f"xact:imgmove:{k}",
        f"Current session · name gets S{n}",
        "Older session · name gets S{k}",
        counts=_stage_counts(cr, lb, n),
        mods_fn=lambda k: _picker_mods(),
        variables={**carry, **_record_vars(lb)})
    rows += srows
    if not digit and query:
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, back)


def render_crmhub(query):
    """🏠 The CRM home inside browse - every verb one row away. ⌃ from any
    CRM screen lands here (the two-key Session-done → Next-session loop).
    Rows trampoline via xact:crmbrowse (plain rows can't switch ctx on ⏎)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    # ONE source of truth with crm_menu.py: src/crm_home.py (Vex
    # simplification green 2026-07-26). ctx rows trampoline via
    # xact:crmbrowse (plain rows can't switch ctx on ⏎).
    import crm_home
    rows = []
    for uid, title, subtitle, kind, val in crm_home.rows_for(
            crm_home.HUB_ORDER, crm_home.HUB_UIDS, "hub-"):
        rows.append(alfred.item(
            uid=uid, title=title, subtitle=subtitle,
            arg=(f"xact:crmbrowse:{val}" if kind == "ctx" else val),
            mods=_picker_mods()))
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, "ctx:crmhub")


_MANAGE = {
    "crm": ("🗂 CRM", "New customer · tattoo · consultation · lead", (
        ("mg-newcust", "➕ New customer", "Name → contact → Records",
         "xact:crmperson:customer"),
        ("mg-tattoo", "➕ New tattoo", "Customer → logbook → S1",
         "ctx:crmnew:tattoo"),
        ("mg-consult", "➕ New consultation", "Customer → logbook → schedule",
         "ctx:crmnew:consult"),
        ("mg-lead", "➕ New lead", "Name → contact → Records",
         "xact:crmperson:lead"),
        ("mg-backlog", "📕 Backlog", "Import · past session · adopt task",
         "ctx:crmback"),
    )),
    "content": ("🎬 Content", "Photos · Eagle housekeeping", (
        ("mg-photos", "📸 Images → tattoo",
         "Photos, Finder or clipboard · pick tattoo → stage", "ctx:tph"),
        ("mg-triage", "🦅 Eagle triage", "Eagle selection → tattoo stage",
         "ctx:triage"),
        ("mg-promote", "🎬 Promote Eagle selection", "Picked shots → To edit",
         "xact:promotesel"),
        ("mg-filed", "📥 File edited shots", "Intake → To post · task → Post",
         "xact:filedited"),
        ("mg-sweep", "🦅 Eagle sweep", "Missing skeletons + re-file archived folders",
         "xact:eaglesweep"),
    )),
}


def render_lbphotos(ids, query):
    """📸 Photos - ONE door for every image job on one tattoo (Vex
    2026-07-28: "those three need to be under one action photos... that
    way I will not have to think what do I need to type").

    The four jobs, by where the pixels are: coming in from Photos /
    Finder / clipboard (straight to the current session, or to a stage
    you pick), already sitting in Eagle (file them into a stage), or
    already filed (browse them, where ⌥⇧ attaches one to TickTick)."""
    tid = ids[0] if ids else ""
    if not tid:
        return add_back([alfred.item(title="No tattoo", valid=False)],
                        "ctx:crmhub")
    rows = [
        alfred.item(uid="ph-import", title="📸 Import to this session",
                    subtitle="Photos, Finder or clipboard → Eagle + TickTick",
                    arg=f"xact:sessphotos:{tid}", mods=_picker_mods()),
        alfred.item(uid="ph-stage", title="📸 Import → pick stage",
                    subtitle="Same, but you choose which folder",
                    arg=f"xact:crmbrowse:ctx:tph:{tid}", mods=_picker_mods()),
        alfred.item(uid="ph-triage", title="🦅 File an Eagle selection",
                    subtitle="Already in Eagle · pick the stage · ⌘ also attaches",
                    arg=f"xact:crmbrowse:ctx:triage:{tid}",
                    mods=_picker_mods()),
        alfred.item(uid="ph-browse",
                    title="📎 Eagle photo → TickTick session",
                    subtitle="Grid of this tattoo · ⏎ opens in Eagle · "
                             "⌥⇧ attaches it to its session",
                    arg=f"xact:crmbrowse:ctx:lbeagle:{tid}:hub",
                    mods=_picker_mods()),
    ]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, f"ctx:crmbook:{tid}")


def render_manage(ids, query):
    """🎛 Manage - the honest home for verbs with no entity to hang off
    (Vex unified home 2026-07-28: "a row that will serve as drop for all
    those that aren't meant to be accessed from their log end point").
    Two rows, CRM and Content, each opening its own flat list."""
    group = ids[0] if ids else ""
    if group not in _MANAGE:
        rows = [alfred.item(uid=f"mg-{k}", title=t, subtitle=s,
                            arg=f"xact:crmbrowse:ctx:manage:{k}",
                            mods=_picker_mods())
                for k, (t, s, _i) in _MANAGE.items()]
        home = "ctx:crmhub"
    else:
        _t, _s, items = _MANAGE[group]
        rows = [alfred.item(
            uid=u, title=t, subtitle=s,
            arg=(f"xact:crmbrowse:{v}" if v.startswith("ctx:") else v),
            mods=_picker_mods()) for u, t, s, v in items]
        home = "ctx:manage"
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, home)


def render_stats(query):
    """📊 Stats - two worlds, one door (Vex 2026-07-28). Each row carries
    a live description and opens its own detail screen."""
    import crm_home
    subs = crm_home.subtitles()
    chips = _cpl_counts()
    rows = [
        alfred.item(uid="st-crm", title="📊 CRM stats",
                    subtitle=(subs.get("money")
                              or "Earnings · sessions · customers"),
                    arg="xact:crmbrowse:ctx:crmstats", mods=_picker_mods()),
        alfred.item(uid="st-content", title="🎬 Content pipeline stats",
                    subtitle=f"🎞 {chips['📸raw']} raw · ✂️ {chips['📸edit']} "
                             f"editing · 📤 {chips['📸post']} to post",
                    arg="xact:crmbrowse:ctx:cstats", mods=_picker_mods()),
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


def _crmsearch_rows(cr, scope, term, filt=None):
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
        for lb in cr.logbook_notes():
            if scope == "ar" and not cr.logbook_archived(lb):
                continue
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

    if filt:
        rows = [(k, o) for k, o in rows if filt(k, o)]
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


def _dest_is(key):
    return lambda cr, o: cr.content_dest_of(o.get("content") or "") == key


# Per-list "/" scopes (Vex 2026-07-28: "must have scopes under /").
# Logbook scopes ARE the row's own status legend and dest chip, so the
# filter and what you see on the row always tell the same story.
_LIST_SCOPES = {
    "lo": (("All", None),
           ("Active", lambda cr, o: not cr.logbook_archived(o)),
           ("Scheduled", lambda cr, o: bool(cr.next_session_task(o["id"]))),
           ("Archived", lambda cr, o: cr.logbook_archived(o)),
           ("TV", _dest_is("tv")),
           ("FM", _dest_is("fm")),
           ("Studio", _dest_is("studio")),
           ("Unclassified",
            lambda cr, o: not cr.content_dest_of(o.get("content") or ""))),
    "cu": (("All", None),
           ("Customers", lambda cr, o: not cr.is_lead(o)),
           ("Leads", lambda cr, o: cr.is_lead(o))),
}


def _crmlist_drill(uid, emoji, name, list_id, scope, query, extra=()):
    """Menu-row drill for one of the two CRM lists (Vex ruling 2026-07-21):
    row 1 is ALWAYS "open in TickTick" (the old ⏎), everything under it is
    the list itself, searchable in its scope. `extra` rows sit directly
    under row 1 (Calendar's 📆 Week, Vex unified home 2026-07-28)."""
    gate = _records_gate()
    if gate:
        return add_back(gate, "ctx:crmhub")
    import crm_records as cr
    term = (query or "").strip()
    scopes = _LIST_SCOPES.get(scope) or ()
    filt, label = None, ""
    if scopes:
        names = "|".join(re.escape(l) for l, _p in scopes)
        m = re.match(rf"(?i)^({names})(?:\s+(.*))?$", term)
        if m:
            label = m.group(1)
            filt = next(p for l, p in scopes if l.lower() == label.lower())
            term = (m.group(2) or "").strip()
        elif term.startswith("/"):
            frag = term[1:].strip().lower()
            menu = [alfred.item(
                uid=f"{uid}-sc-{l}", title=f"{emoji} {l}",
                subtitle=f"Scope {name.lower()} to {l.lower()}",
                valid=False, autocomplete=f"{l} ")
                for l, _p in scopes if frag in l.lower()]
            return add_back(menu or [alfred.item(
                title=f'No scope matching "{frag}"', valid=False)],
                "ctx:crmhub")
    rows = [alfred.item(
        uid=f"{uid}-open", title=f"{emoji} {name}"
                                 + (f" · {label}" if label else ""),
        subtitle="The whole list, in the app  |  ⏎↗️"
                 + ("  ·  / scopes" if scopes else ""),
        arg=f"open:ticktick:///webapp/#p/{list_id}/tasks")]
    rows += list(extra)
    hits = _crmsearch_rows(cr, scope, term,
                           filt=(lambda k, o: filt(cr, o)) if filt else None)
    if term and not hits:
        hits = [alfred.item(title=f'Nothing matching "{term}"', valid=False)]
    return add_back(rows + hits, "ctx:crmhub")


def render_crmcal(query):
    """📅 The calendar list: open row on top, 📆 Week under it (Vex moved
    Week inside Calendar when the home unified), then the open tasks."""
    import crm_home
    week = alfred.item(
        uid="crmcal-week", title="📆 Week",
        subtitle=(crm_home.subtitles().get("cal")
                  or "Who's coming + needs-booking radar"),
        arg="xact:crmbrowse:ctx:crmweek", mods=_picker_mods())
    return _crmlist_drill("crmcal", "📅", "Calendar", _areas.CRM_ID,
                          "ca", query, extra=(week,))


def render_crmcusts(query):
    """👥 Customers (leads too): open row on top, customer rows under -
    the 🗂️ Logs pooled search died 2026-07-26 (Vex: customers must
    never pollute a logbook search, and vice versa)."""
    return _crmlist_drill("crmcusts", "👥", "Customers", _areas.RECORDS_ID,
                          "cu", query)


def render_crmlbs(query):
    """🎨 Logbooks (archived too): open row on top, logbook rows under."""
    return _crmlist_drill("crmlbs", "🎨", "Logbooks", _areas.RECORDS_ID,
                          "lo", query)


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
        subtitle=(info or "New customer") + "  |  ⏎↗️",
        arg=_open_note_arg(cust_tid), mods=_picker_mods(),
        variables=_record_vars(cust)))
    if phone:
        rows.append(alfred.item(uid="hub-phone", title=f"📞 {phone}",
                                subtitle="⏎📋 Copy",
                                arg=f"xact:crmcopy:{phone}",
                                mods=_picker_mods()))
    if mail:
        rows.append(alfred.item(uid="hub-mail", title=f"✉️ {mail}",
                                subtitle="⏎📋 Copy",
                                arg=f"xact:crmcopy:{mail}",
                                mods=_picker_mods()))
    if insta:
        handle = insta.lstrip("@")
        rows.append(alfred.item(uid="hub-insta", title=f"📸 @{handle}",
                                subtitle="DMs live here  |  ⏎↗️",
                                arg=f"open:https://instagram.com/{handle}",
                                mods=_picker_mods()))
    if phone:
        digits = re.sub(r"[^\d]", "", phone)
        if digits:
            rows.append(alfred.item(
                uid="hub-wa", title="💬 WhatsApp",
                subtitle=f"{phone}  |  ⏎↗️",
                arg=f"open:https://wa.me/{digits.lstrip('0')}",
                mods=_picker_mods()))
    lbs = cr.customer_logbooks(cust_tid)
    lb_ids = {lb["id"] for lb in lbs}
    for lb in lbs:
        rows.append(_logbook_row(cr, lb, uid_prefix="hub"))
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
    rows.append(alfred.item(
        uid="hub-trash", title="🗑 Delete entry",
        subtitle="Mistakes only · sessions + Eagle go too",
        arg=f"xact:crmtrash:{cust_tid}", mods=_picker_mods()))
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
        alfred.item(uid="back-img", title="📸 Images → tattoo",
                    subtitle="Photos, Finder or clipboard · pick "
                             "logbook → stage",
                    arg="", valid=False, autocomplete="img "),
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
    if q.startswith(("past", "img")):
        mode = next(m for m in ("past", "img") if q.startswith(m))
        import crm_records as cr
        frag = q[len(mode):].strip()
        sub = {"img": "⏎ 🦅 folders · ⌥⇧📸 into a stage",
               "past": "Log a dated session"}[mode]
        # img drills into the folder screen - the ONE 📸 action
        # (Finder source) does the import from there (Vex unification)
        verb = {"img": "crmbrowse:ctx:lbeagle",
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
                    subtitle=f"{sub}{chip}  |  ⏎⚡",
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
            subtitle=("⏎📅  ⌘⚡" if linked
                      else "🔗 unlinked  |  ⏎📅  ⌘⚡"),
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
            sub = f"{when}{clock}  |  ⏎🔥"
        else:
            sub = "Dormant  |  ⏎🔥"
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
    from display import buffer_pairs
    pairs = buffer_pairs()   # self-healed: dead lines drop, file rewrites
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

# ── Level: bridges (🌉 - the five-row hub + the project picker) ──────────────
def render_bridges(ids, query):
    """ctx:bridges - the ruled five rows: Add Daily / Add Project /
    Search Daily / Search Project / Board (searching itself lives in the
    search scopes b · bd · bp - the hub only routes).
    ctx:bridges:new - list picker → xact:bridge_proj."""
    import bridges as br
    import areas
    sub = ids[0] if ids else ""
    all_notes = [n for n in (cache_store.get("all_notes") or [])
                 if n.get("status", 0) == 0]
    today = datetime.now().date()

    if sub == "new":
        rows = []
        for p in get_projects():
            if p["id"] == areas.BRIDGES_ID:
                continue
            rows.append(alfred.item(
                uid=f"brnew-{p['id']}", title=p.get("name", ""),
                subtitle="⏎🌉 Bridge this list",
                arg=f"xact:bridge_proj:{p['id']}", valid=True,
                # real list vars - _picker_mods keeps ⌘ Actions live, and
                # without these it would rail on the LAST acted-on task
                variables={"task_id": "", "task_list_id": p["id"],
                           "list_id": p["id"], "section_id": "",
                           "task_title": p.get("name", ""),
                           "item_type": "list"},
                mods=_picker_mods()))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title=f'No list matching "{query}"',
                                valid=False)]
        return add_back(rows, "ctx:bridges")

    rows = []
    if areas.bridges_configured():
        twant = br.daily_title(today)
        thit = any((n.get("title") or "").strip() == twant
                   for n in all_notes)
        rows.append(alfred.item(
            uid="br-daily",
            title=("🌉 Add Daily Bridge · written ✅" if thit
                   else "✍️ Add Daily Bridge"),
            subtitle=("Open today's  |  ⏎↗️  ⌃🔙" if thit
                      else "Write today's  |  ⏎🌉  ⌃🔙"),
            arg="xact:bridge_daily", valid=True))
    else:
        rows.append(alfred.item(
            uid="br-setup", valid=False,
            title="🌉 Daily bridges need a home list",
            subtitle="Settings → 🌉 Bridges list · project bridges work anyway"))
    rows.append(alfred.item(
        uid="br-new", title="➕ Add Project Bridge",
        subtitle="Pick the list  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:bridges:new", valid=True))
    rows.append(alfred.item(
        uid="br-sd", title="🔎 Search Daily Bridges",
        subtitle="Newest on top  |  ⏎🔎  ⌃🔙",
        arg="xact:search_pre:bd", valid=True))
    rows.append(alfred.item(
        uid="br-sp", title="🔎 Search Project Bridges",
        subtitle="Newest on top  |  ⏎🔎  ⌃🔙",
        arg="xact:search_pre:bp", valid=True))
    if areas.bridges_configured():
        rows.append(alfred.item(
            uid="br-board", title="🗂️ Bridges Board",
            subtitle="Month columns  |  ⏎↗️  ⌃🔙",
            arg=f"open:ticktick:///webapp/#p/{areas.BRIDGES_ID}/tasks",
            valid=True))
        keep = {br.month_tag(today),
                br.month_tag(today.replace(day=1) - timedelta(days=1))}
        n_old = sum(
            1 for n in all_notes
            if (n.get("_projectId") or n.get("projectId")) == areas.BRIDGES_ID
            and br.is_daily(n.get("title", ""))
            and (br.title_date(n.get("title")) is not None)
            and br.month_tag(br.title_date(n.get("title"))) not in keep)
        if n_old:
            rows.append(alfred.item(
                uid="br-tidy", title=f"🗄️ Tidy old months · {n_old}",
                subtitle="Complete bridges before last month · asks first  |  ⏎🗄️  ⌃🔙",
                arg="xact:bridge_tidy", valid=True))

    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title=f'No bridge row matching "{query}"',
                            valid=False)]
    return add_back(rows, "ctx:folders")


def render_people(level, ids, query):
    """ctx:people - the People hub (Add Person / Add CTA / Add Log /
    Search / Board, + conditional 🕸️ stale and ⚙️ seed rows).
    ctx:people:log - person picker → xact:person_log.
    ctx:people:attach:SRCPID:SRCTID - person picker → xact:person_attach.
    ctx:person:TID - one card as a screen: 📇 fields, open CTAs, log tail."""
    import people as pe
    import areas
    all_tasks = [t for t in (cache_store.get("all_tasks") or [])
                 if t.get("status", 0) == 0]
    persons = [t for t in all_tasks
               if (t.get("_projectId") or t.get("projectId")) == areas.PEOPLE_ID
               and pe.is_person(t.get("title", ""))]
    persons.sort(key=lambda t: t.get("title", ""))

    def _person_vars(t):
        return {"task_id": t["id"], "task_list_id": areas.PEOPLE_ID,
                "list_id": "", "section_id": "",
                "task_title": t.get("title", ""), "item_type": "task"}

    if level == "person":
        tid = ids[0] if ids else ""
        card = next((t for t in persons if t.get("id") == tid), None)
        if card is None:
            return add_back([alfred.item(
                title="Card not cached yet · sync or reopen",
                valid=False)], "ctx:people")

        if len(ids) > 1 and ids[1] == "edit":
            # 📇 field editor - one dialog per row, current value shown
            icons = {"Birthday": "🎂", "Phone": "📞", "Mail": "✉️",
                     "Instagram": "📸"}
            content = card.get("content") or ""
            rows = []
            for f in pe.CARD_FIELDS:
                val = pe.card_field(content, f)
                rows.append(alfred.item(
                    uid=f"pedit-{tid}-{f}",
                    title=f"{icons.get(f, '📇')} {f} · {val or '…'}",
                    subtitle="⏎✏️ edit  ⌃🔙",
                    arg=f"xact:person_edit:{f}:{areas.PEOPLE_ID}:{tid}",
                    valid=True))
            if query:
                rows = fuzz.filter_and_score(query, rows,
                                             key_fn=lambda x: x["title"])
            return add_back(rows, f"ctx:person:{tid}")
        name = pe.person_name(card.get("title", ""))
        chip = pe.circle_chip(card.get("tags"))
        content = card.get("content") or ""
        link = f"ticktick:///webapp/#p/{areas.PEOPLE_ID}/tasks/{tid}"
        rows = [alfred.item(
            uid=f"pcard-{tid}", title=f"{chip + ' ' if chip else ''}👽 {name}",
            subtitle=f"{pe.age_chip(content)}  |  ⏎↗️ card  ⌘⚡  ⌃🔙",
            arg=f"open:{link}", valid=True,
            variables=_person_vars(card), mods=_picker_mods())]
        rows.append(alfred.item(
            uid=f"pedit-{tid}", title="📇 Edit card",
            subtitle="Birthday · phone · mail · instagram  |  ⏎✏️  ⌃🔙",
            arg=f"xact:crmbrowse:ctx:person:{tid}:edit", valid=True))
        rows.append(alfred.item(
            uid=f"plog-{tid}", title="🧾 Add log entry",
            subtitle="Timestamped · newest on top  |  ⏎🧾  ⌃🔙",
            arg=f"xact:person_log:{areas.PEOPLE_ID}:{tid}", valid=True))
        rows.append(alfred.item(
            uid=f"pcta-{tid}", title="📌 Add CTA",
            subtitle="Type it · *date @time schedules  |  ⏎➕  ⌃🔙",
            arg=f"xact:add_pre:~p {card.get('title', '')}", valid=True))
        rows.append(alfred.item(
            uid=f"pfact-{tid}", title="💬 Add fact",
            subtitle="Conversation starter  |  ⏎💬  ⌃🔙",
            arg=f"xact:person_fact:{areas.PEOPLE_ID}:{tid}", valid=True))
        rows.append(alfred.item(
            uid=f"pidea-{tid}", title="🎁 Add idea",
            subtitle="Gift stash · typed or clipboard  |  ⏎🎁  ⌃🔙",
            arg=f"xact:person_idea:{areas.PEOPLE_ID}:{tid}", valid=True))
        bday = pe.card_field(content, "Birthday")
        if pe.parse_birthday(bday):
            rows.append(alfred.item(
                uid=f"pbday-{tid}", title=f"🎂 Birthday · {bday}",
                subtitle="Mint the countdown  |  ⏎🎂  ⌃🔙",
                arg=f"xact:person_bday:{areas.PEOPLE_ID}:{tid}", valid=True))
        phone = pe.card_field(content, "Phone")
        if phone:
            digits = re.sub(r"[^\d+]", "", phone)
            if digits:
                rows.append(alfred.item(
                    uid=f"pcall-{tid}", title=f"📞 Call · {phone}",
                    subtitle="⏎📞  ⌃🔙", arg=f"open:tel:{digits}",
                    valid=True))
        mail = pe.card_field(content, "Mail")
        if mail and "@" in mail:
            rows.append(alfred.item(
                uid=f"pmail-{tid}", title=f"✉️ Mail · {mail}",
                subtitle="⏎✉️  ⌃🔙", arg=f"open:mailto:{mail}",
                valid=True))
        insta = pe.card_field(content, "Instagram")
        if insta:
            handle = insta.strip().lstrip("@")
            url = insta if insta.startswith("http") \
                else f"https://www.instagram.com/{handle}/"
            rows.append(alfred.item(
                uid=f"pinsta-{tid}", title=f"📸 Instagram · {insta}",
                subtitle="⏎↗️  ⌃🔙", arg=f"open:{url}", valid=True))
        log = pe.log_body(content)
        if log.strip():
            n = sum(1 for ln in log.splitlines() if ln.strip())
            rows.append(alfred.item(
                uid=f"parch-{tid}", title=f"🗄️ Archive log · {n} lines",
                subtitle="Old entries → dated note · asks first  |  ⏎🗄️  ⌃🔙",
                arg=f"xact:person_archive:{areas.PEOPLE_ID}:{tid}",
                valid=True))
        ctas = sorted((t for t in all_tasks if t.get("parentId") == tid),
                      key=lambda t: t.get("dueDate") or "9999")
        for t in ctas:
            tlink = f"ticktick:///webapp/#p/{areas.PEOPLE_ID}/tasks/{t['id']}"
            due = (t.get("dueDate") or "")[:10]
            rows.append(alfred.item(
                uid=f"pc-{t['id']}", title=f"📌 {t.get('title', '')}",
                subtitle=(f"{due}  |  " if due else "") + "⏎↗️  ⌘⚡  ⌃🔙",
                arg=f"open:{tlink}", valid=True,
                variables={"task_id": t["id"],
                           "task_list_id": areas.PEOPLE_ID,
                           "list_id": "", "section_id": "",
                           "task_title": t.get("title", ""),
                           "item_type": "subtask"},
                mods=_picker_mods()))
        for ln in [l for l in pe.facts_body(content).splitlines()
                   if l.strip()][:5]:
            rows.append(alfred.item(
                title=ln.strip().lstrip("- "), subtitle="💬", valid=False))
        for txt, stamp in pe.log_entries(content)[:5]:
            rows.append(alfred.item(
                title=txt, subtitle=f"🧾 {stamp}".strip(), valid=False))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        return add_back(rows, "ctx:people")

    sub = ids[0] if ids else ""

    if sub == "linktask":
        # any open task → hop into the person picker with it in tow
        pool = [t for t in all_tasks
                if (t.get("_projectId") or t.get("projectId"))
                != areas.PEOPLE_ID
                and t.get("kind") != "NOTE" and not t.get("parentId")]
        pool.sort(key=lambda t: t.get("createdTime") or "", reverse=True)
        rows = []
        for t in pool[:200]:
            tpid = t.get("_projectId") or t.get("projectId") or ""
            rows.append(alfred.item(
                uid=f"plt-{t['id']}", title=t.get("title", ""),
                subtitle=(t.get("_projectName", "")
                          + "  |  ⏎👽 pick the person  ⌃🔙"),
                arg=f"xact:crmbrowse:ctx:people:attach:{tpid}:{t['id']}",
                valid=True,
                variables={"task_id": t["id"], "task_list_id": tpid,
                           "list_id": "", "section_id": "",
                           "task_title": t.get("title", ""),
                           "item_type": "task"},
                mods=_picker_mods()))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        rows = rows[:60]
        if not rows:
            rows = [alfred.item(title=(f'No task matching "{query}"'
                                       if query else "No tasks"),
                                valid=False)]
        return add_back(rows, "ctx:people")

    if sub == "stats":
        today = datetime.now().date()
        scored = []
        for t in persons:
            content = t.get("content") or ""
            nd = pe.nudge_silent_days(t, today)
            n_open = sum(1 for x in all_tasks
                         if x.get("parentId") == t["id"])
            bd = pe.parse_birthday(pe.card_field(content, "Birthday"))
            bchip = ""
            if bd:
                _y, mo, d = bd
                try:
                    cand = today.replace(month=mo, day=d)
                except ValueError:
                    cand = today.replace(month=mo, day=28)
                if cand < today:
                    cand = cand.replace(year=today.year + 1)
                bchip = f"🎂 {(cand - today).days}d"
            scored.append((nd if nd is not None else -1, t, n_open, bchip))
        scored.sort(key=lambda kv: -kv[0])
        rows = [alfred.item(
            title=f"📊 {len(persons)} people · "
                  f"{sum(1 for nd, *_ in scored if nd >= pe.STALE_DAYS)} stale",
            subtitle=f"Quietest first · 🫂 nudges at {pe.NUDGE_DAYS}d silence",
            valid=False)]
        for nd, t, n_open, bchip in scored:
            chip = pe.circle_chip(t.get("tags"))
            bits = [pe.age_chip(t.get("content") or "")]
            if n_open:
                bits.append(f"📌 {n_open} open")
            if bchip:
                bits.append(bchip)
            rows.append(alfred.item(
                uid=f"pst-{t['id']}",
                title=f"{chip + ' ' if chip else ''}{pe.person_name(t.get('title', ''))}",
                subtitle="  ·  ".join(bits) + "  |  ⏎⤵️ card  ⌃🔙",
                arg=f"xact:crmbrowse:ctx:person:{t['id']}", valid=True,
                variables=_person_vars(t), mods=_picker_mods()))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title="No people yet", valid=False)]
        return add_back(rows, "ctx:people")

    if sub in ("log", "attach", "idea"):
        rows = []
        for t in persons:
            if sub == "log":
                arg = f"xact:person_log:{areas.PEOPLE_ID}:{t['id']}"
                subt = "⏎🧾 Log to this card"
            elif sub == "idea":
                src = ":".join(ids[1:3])
                arg = f"xact:person_idea_from:{t['id']}:{src}"
                subt = "⏎🎁 Stash on this card"
            else:
                src = ":".join(ids[1:3])
                arg = f"xact:person_attach:{t['id']}:{src}"
                subt = "⏎👽 CTA under this person"
            rows.append(alfred.item(
                uid=f"ppick-{t['id']}", title=t.get("title", ""),
                subtitle=f"{pe.age_chip(t.get('content') or '')}  |  {subt}",
                arg=arg, valid=True,
                variables=_person_vars(t), mods=_picker_mods()))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        if not rows:
            rows = [alfred.item(title=(f'No person matching "{query}"'
                                       if query else "No people yet"),
                                valid=False)]
        return add_back(rows, "ctx:people")

    # ── the hub ──────────────────────────────────────────────────────────
    rows = []
    if not areas.people_configured():
        rows.append(alfred.item(
            uid="pe-setup", valid=False,
            title="👽 People need a home list",
            subtitle="Settings → 👽 People list · then re-enter"))
        return add_back(rows, "ctx:folders")
    rows.append(alfred.item(
        uid="pe-new", title="➕ Add Person",
        subtitle="Name → circle → card opens  |  ⏎👽  ⌃🔙",
        arg="xact:person_new", valid=True))
    rows.append(alfred.item(
        uid="pe-cta", title="📌 Add CTA",
        subtitle="Pick person · type · *date @time  |  ⏎➕  ⌃🔙",
        arg="xact:add_pre:H", valid=True))
    rows.append(alfred.item(
        uid="pe-log", title="🧾 Add Log Entry",
        subtitle="Pick person · timestamped line  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:people:log", valid=True))
    rows.append(alfred.item(
        uid="pe-search", title="🔎 Search People",
        subtitle="Freshest contact on top  |  ⏎🔎  ⌃🔙",
        arg="xact:search_pre:h", valid=True))
    rows.append(alfred.item(
        uid="pe-link", title="🔗 Attach a task",
        subtitle="Pick task · pick person · becomes a CTA  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:people:linktask", valid=True))
    rows.append(alfred.item(
        uid="pe-stats", title="📊 Stats",
        subtitle="Silence · open CTAs · birthdays  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:people:stats", valid=True))
    rows.append(alfred.item(
        uid="pe-board", title="🗂️ People Board",
        subtitle="Circle columns  |  ⏎↗️  ⌃🔙",
        arg=f"open:ticktick:///webapp/#p/{areas.PEOPLE_ID}/tasks",
        valid=True))
    n_stale = sum(1 for t in persons if pe.is_stale_task(t))
    if n_stale:
        rows.append(alfred.item(
            uid="pe-stale", title=f"🕸️ Stale people · {n_stale}",
            subtitle=f"No log line in {pe.STALE_DAYS}d  |  ⏎🔎  ⌃🔙",
            arg="xact:search_pre:hs", valid=True))
    from display import tag_match_key
    known = {tag_match_key(t) for t in (cache_store.get("tags") or [])}
    if any(tag_match_key(tag) not in known for tag in pe.CIRCLE_TAGS):
        rows.append(alfred.item(
            uid="pe-seed", title="⚙️ Seed circles + board",
            subtitle="Mint the 5 circle tags · flip kanban  |  ⏎⚙️  ⌃🔙",
            arg="xact:person_setup", valid=True))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title=f'No people row matching "{query}"',
                            valid=False)]
    return add_back(rows, "ctx:folders")


# ── Level: countdowns / countdown ────────────────────────────────────────────
def _cd_display_date(cd):
    """'27.6' (+ '.1993' when the year is real); weekly/monthly repeats
    show the rhythm, not the anchor date."""
    rule = cd.get("repeatFlag") or ""
    if "FREQ=WEEKLY" in rule:
        return "weekly"
    if "FREQ=MONTHLY" in rule:
        return "monthly"
    n = cd.get("date") or 0
    d, mo, y = n % 100, n // 100 % 100, n // 10000
    return f"{d}.{mo}" + ("" if cd.get("ignoreYear") else f".{y}")


def render_countdowns(level, ids, query):
    """ctx:countdowns - the ⏳ hub (soonest first, count-ups below).
    ctx:countdowns:stats - counts · next 30 days · running count-ups.
    ctx:countdown:<id> - one countdown as a screen (edit rows).
    ctx:countdown:<id>:appear - the calendar/smart-list visibility picker.
    Renders from the hourly 'countdowns' cache (verbs patch it)."""
    import countdowns as cdm
    from datetime import date as _date
    today = _date.today()
    cached = cache_store.get("countdowns")
    if cached is None:
        return add_back([alfred.item(
            title="⏳ Not synced yet",
            subtitle="Run tsy · the hourly sync fills this", valid=False)],
            "ctx:folders")
    cds = [c for c in cached if c.get("status") == 0]

    if level == "countdown":
        cid = ids[0] if ids else ""
        cd = next((c for c in cds if c.get("id") == cid), None)
        if cd is None:
            return add_back([alfred.item(
                title="Countdown not cached yet · sync or reopen",
                valid=False)], "ctx:countdowns")
        chip = cdm.kind_chip(cd)
        name = cd.get("name", "?")

        if len(ids) > 1 and ids[1] == "appear":
            cur = cd.get("typeOfSmartList") or 0
            rows = []
            for val, label in cdm.APPEAR:
                mark = " ✓" if val == cur else ""
                rows.append(alfred.item(
                    uid=f"cda-{cid}-{val}", title=f"👁️ {label}{mark}",
                    subtitle="Calendar + smart lists  |  ⏎👁️  ⌃🔙",
                    arg=f"xact:countdown_appear:{cid}:{val}", valid=True))
            return add_back(rows, f"ctx:countdown:{cid}")

        rows = [alfred.item(
            uid=f"cd-{cid}",
            title=f"{chip} {name} · {cdm.distance_label(cd, today)}",
            subtitle=f"{_cd_display_date(cd)}  ⌃🔙", valid=False)]
        rows.append(alfred.item(
            uid=f"cdn-{cid}", title="✏️ Name",
            subtitle=f"{name}  |  ⏎✏️  ⌃🔙",
            arg=f"xact:countdown_edit:name:{cid}", valid=True))
        rows.append(alfred.item(
            uid=f"cdd-{cid}", title=f"📅 Date · {_cd_display_date(cd)}",
            subtitle="27.06.1993 · 28.7 · 1993/06/27  |  ⏎✏️  ⌃🔙",
            arg=f"xact:countdown_edit:date:{cid}", valid=True))
        rows.append(alfred.item(
            uid=f"cda-{cid}",
            title="👁️ Appears · "
                  + cdm.APPEAR_LABEL.get(cd.get("typeOfSmartList") or 0,
                                         "On the day"),
            subtitle="When calendar + smart lists show it  |  ⏎⤵️  ⌃🔙",
            arg=f"xact:crmbrowse:ctx:countdown:{cid}:appear", valid=True))
        rows.append(alfred.item(
            uid=f"cdr-{cid}",
            title=f"💬 Remark · {cd.get('remark') or '…'}",
            subtitle="⏎✏️  ⌃🔙",
            arg=f"xact:countdown_edit:remark:{cid}", valid=True))
        rows.append(alfred.item(
            uid=f"cdf-{cid}",
            title="⏱️ Counting " + ("up" if cdm.is_countup(cd) else "down"),
            subtitle="Flip the direction  |  ⏎🔃  ⌃🔙",
            arg=f"xact:countdown_flip:{cid}", valid=True))
        if cd.get("type") == 2:
            import people as pe
            import areas
            match = next(
                (t for t in (cache_store.get("all_tasks") or [])
                 if t.get("status", 0) == 0
                 and (t.get("_projectId") or t.get("projectId"))
                 == areas.PEOPLE_ID and pe.is_person(t.get("title", ""))
                 and pe.person_name(t.get("title", "")).lower()
                 == name.strip().lower()), None)
            if match:
                rows.append(alfred.item(
                    uid=f"cdp-{cid}", title=f"👽 Open {name}'s card",
                    subtitle="⏎⤵️  ⌃🔙",
                    arg=f"xact:crmbrowse:ctx:person:{match['id']}",
                    valid=True))
        rows.append(alfred.item(
            uid=f"cdar-{cid}", title="🗄️ Archive",
            subtitle="Out of the hub, kept in the app  |  ⏎🗄️  ⌃🔙",
            arg=f"xact:countdown_archive:{cid}", valid=True))
        rows.append(alfred.item(
            uid=f"cddel-{cid}", title="🗑️ Delete",
            subtitle="Asks first  |  ⏎🗑️  ⌃🔙",
            arg=f"xact:countdown_delete:{cid}", valid=True))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        return add_back(rows, "ctx:countdowns")

    if ids and ids[0] == "stats":
        rows = []
        kinds = {}
        for c in cds:
            kinds[c.get("type") or 4] = kinds.get(c.get("type") or 4, 0) + 1
        counts = " · ".join(f"{cdm.KINDS[k][0]} {n}"
                            for k, n in sorted(kinds.items()))
        rows.append(alfred.item(uid="cds-counts", title=f"⏳ {len(cds)} · "
                                + counts, subtitle="⌃🔙", valid=False))
        ahead = []
        for c in cds:
            occ = cdm.days_until(c, today)
            if occ and occ[1] == "ahead" and occ[0] <= 30:
                ahead.append((occ[0], c))
        for n, c in sorted(ahead, key=lambda x: x[0]):
            age = cdm.age_on_next(c, today)
            rows.append(alfred.item(
                uid=f"cds-{c['id']}",
                title=f"{cdm.kind_chip(c)} {c.get('name', '?')} · "
                      + cdm.distance_label(c, today)
                      + (f" · turns {age}" if age else ""),
                subtitle=f"{_cd_display_date(c)}  |  ⏎⤵️  ⌃🔙",
                arg=f"xact:crmbrowse:ctx:countdown:{c['id']}", valid=True))
        ups = [(occ[0], c) for c in cds
               for occ in [cdm.days_until(c, today)]
               if occ and occ[1] == "since"]
        for n, c in sorted(ups, reverse=True, key=lambda x: x[0]):
            ms = cdm.milestone(c, today)
            rows.append(alfred.item(
                uid=f"cdsu-{c['id']}",
                title=f"⏱️ {c.get('name', '?')} · {n}d"
                      + (f" · {ms}" if ms else ""),
                subtitle=f"Counting up since {_cd_display_date(c)}  |  "
                         "⏎⤵️  ⌃🔙",
                arg=f"xact:crmbrowse:ctx:countdown:{c['id']}", valid=True))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        return add_back(rows, "ctx:countdowns")

    # ── the hub ──────────────────────────────────────────────────────────
    rows = [alfred.item(
        uid="cd-new", title="➕ New countdown",
        subtitle="Name · date · kind · when it appears  |  ⏎➕  ⌃🔙",
        arg="xact:countdown_new", valid=True)]
    rows.append(alfred.item(
        uid="cd-stats", title="📊 Stats",
        subtitle="Next 30 days · counts · running count-ups  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:countdowns:stats", valid=True))
    for c in sorted(cds, key=lambda c: cdm.sort_key(c, today)):
        age = cdm.age_on_next(c, today)
        ms = cdm.milestone(c, today)
        bits = [cdm.distance_label(c, today), _cd_display_date(c)]
        if age:
            bits.append(f"turns {age}")
        if ms:
            bits.append(ms)
        rows.append(alfred.item(
            uid=f"cdh-{c['id']}",
            title=f"{cdm.kind_chip(c)} {c.get('name', '?')}",
            subtitle=" · ".join(bits) + "  |  ⏎⤵️  ⌃🔙",
            arg=f"xact:crmbrowse:ctx:countdown:{c['id']}", valid=True))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title=f'No countdown matching "{query}"',
                            valid=False)]
    return add_back(rows, "ctx:folders")


# ── Level: habits / habit ────────────────────────────────────────────────────
def render_habits(level, ids, query):
    """ctx:habits - the 🔄 hub, sections as headers, due-first: ⏎ TICKS
    today (value habits step; note dialog rides recordEnable habits).
    ctx:habit:<id> - one habit as a screen (retro tick, skip, un-tick,
    note, review-note hop, archive, delete).
    ctx:habits:stats - streaks · dots · totals.
    Renders from the hourly caches (verbs patch them)."""
    import habits_model as hm
    from datetime import date as _date
    today = _date.today()
    ts = hm.stamp(today)
    cached = cache_store.get("habits")
    if cached is None:
        return add_back([alfred.item(
            title="🔄 Not synced yet",
            subtitle="Run tsy · the hourly sync fills this", valid=False)],
            "ctx:folders")
    habits = [h for h in cached if h.get("status") == 0]
    checks = cache_store.get("habit_checkins") or {}
    sec_rows = sorted(cache_store.get("habit_sections") or [],
                      key=lambda s: s.get("sortOrder") or 0)
    sec_name = {s["id"]: s.get("name", "") for s in sec_rows}

    def _today_chip(h):
        return hm.state_chip(h, hm.checkin_for(checks.get(h["id"]), ts))

    def _sub(h):
        bits = [hm.dots(h, checks.get(h["id"]), today)]
        if h.get("currentStreak"):
            bits.append(f"🔥{h['currentStreak']}")
        tpw = hm.times_per_week(h)
        if tpw:
            bits.append(f"{hm.week_done(checks.get(h['id']), today)}/{tpw} wk")
        return " · ".join(bits)

    if level == "habit":
        hid = ids[0] if ids else ""
        h = next((x for x in habits if x.get("id") == hid), None)
        if h is None:
            return add_back([alfred.item(
                title="Habit not cached yet · sync or reopen",
                valid=False)], "ctx:habits")
        name = h.get("name", "?")
        cur = hm.checkin_for(checks.get(hid), ts)
        rows = [alfred.item(
            uid=f"hb-{hid}", title=f"{_today_chip(h)} {name}",
            subtitle=f"{_sub(h)} · {h.get('maxStreak') or 0} best · "
                     f"{h.get('totalCheckIns') or 0} total  ⌃🔙",
            valid=False)]
        rows.append(alfred.item(
            uid=f"hbt-{hid}", title="✅ Tick today",
            subtitle="⏎✅  ⌃🔙", arg=f"xact:habit_tick:{hid}", valid=True))
        rows.append(alfred.item(
            uid=f"hbp-{hid}", title="⏪ Tick a past day",
            subtitle="Asks the date · y = yesterday  |  ⏎⏪  ⌃🔙",
            arg=f"xact:habit_tick_past:{hid}", valid=True))
        if cur and (cur.get("value") or cur.get("status")):
            rows.append(alfred.item(
                uid=f"hbu-{hid}", title="↩️ Un-tick today",
                subtitle="Back to blank  |  ⏎↩️  ⌃🔙",
                arg=f"xact:habit_untick:{hid}", valid=True))
        rows.append(alfred.item(
            uid=f"hbs-{hid}", title="⛔ Skip today",
            subtitle="Not happening · streak-honest  |  ⏎⛔  ⌃🔙",
            arg=f"xact:habit_skip:{hid}", valid=True))
        rows.append(alfred.item(
            uid=f"hbn-{hid}", title="📝 Note for today",
            subtitle="Rides the habit's diary  |  ⏎📝  ⌃🔙",
            arg=f"xact:habit_note:{hid}", valid=True))
        slot = hm.review_slot(name)
        if slot:
            rows.append(alfred.item(
                uid=f"hbw-{hid}", title=f"💫 Open the {slot} note",
                subtitle="The review lives there  |  ⏎↗️  ⌃🔙",
                arg=f"xact:pn_open:{slot}", valid=True))
        rows.append(alfred.item(
            uid=f"hba-{hid}", title="🗄️ Archive",
            subtitle="Off the hub, history kept  |  ⏎🗄️  ⌃🔙",
            arg=f"xact:habit_archive:{hid}", valid=True))
        rows.append(alfred.item(
            uid=f"hbd-{hid}", title="🗑️ Delete",
            subtitle="Checkins + notes go with it · asks first  |  ⏎🗑️  ⌃🔙",
            arg=f"xact:habit_delete:{hid}", valid=True))
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        return add_back(rows, "ctx:habits")

    if ids and ids[0] == "stats":
        rows = []
        for h in sorted(habits, key=lambda x: -(x.get("currentStreak") or 0)):
            rows.append(alfred.item(
                uid=f"hbs-{h['id']}", title=f"{_today_chip(h)} "
                + h.get("name", "?"),
                subtitle=f"{_sub(h)} · {h.get('maxStreak') or 0} best · "
                         f"{h.get('totalCheckIns') or 0} total  |  ⏎⤵️  ⌃🔙",
                arg=f"xact:crmbrowse:ctx:habit:{h['id']}", valid=True))
        if not rows:
            rows = [alfred.item(title="No habits yet", valid=False)]
        if query:
            rows = fuzz.filter_and_score(query, rows,
                                         key_fn=lambda x: x["title"])
        return add_back(rows, "ctx:habits")

    # ── the hub ──────────────────────────────────────────────────────────
    rows = [alfred.item(
        uid="hb-new", title="➕ New habit",
        subtitle="Name · rhythm · section  |  ⏎➕  ⌃🔙",
        arg="xact:habit_new", valid=True)]
    rows.append(alfred.item(
        uid="hb-stats", title="📊 Stats",
        subtitle="Streaks · history · totals  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:habits:stats", valid=True))
    rows.append(alfred.item(
        uid="hb-app", title="↗️ Open in TickTick",
        subtitle="The app's habit board  |  ⏎↗️  ⌃🔙",
        arg="open:ticktick://habit", valid=True))
    due = [h for h in habits if hm.due_today(h, today)]
    if due and all(
            (hm.checkin_for(checks.get(h["id"]), ts) or {}).get("status")
            in (hm.DONE, hm.SKIPPED) for h in due):
        rows.append(alfred.item(uid="hb-alldone",
                                title="🎉 All done today",
                                subtitle="⌃🔙", valid=False))

    def _hub_key(h):
        c = hm.checkin_for(checks.get(h["id"]), ts)
        is_due = hm.due_today(h, today)
        done = c and c.get("status") in (hm.DONE, hm.SKIPPED)
        return (0 if is_due and not done else 1 if is_due else 2,
                h.get("sortOrder") or 0)

    by_sec = {}
    for h in habits:
        by_sec.setdefault(h.get("sectionId") or "-1", []).append(h)
    sec_order = [s["id"] for s in sec_rows if s["id"] in by_sec]
    sec_order += [k for k in by_sec if k not in sec_order]
    many = len([k for k in sec_order if by_sec[k]]) > 1
    for sid in sec_order:
        group = sorted(by_sec[sid], key=_hub_key)
        if not group:
            continue
        if many:
            nm = sec_name.get(sid, "").lstrip("_").capitalize() or "Habits"
            rows.append(alfred.item(uid=f"hbsec-{sid}", title=f"§ {nm}",
                                    subtitle="⌃🔙", valid=False))
        for h in group:
            due_chip = "" if hm.due_today(h, today) else "  💤"
            rows.append(alfred.item(
                uid=f"hbh-{h['id']}",
                title=f"{_today_chip(h)} {h.get('name', '?')}{due_chip}",
                subtitle=f"{_sub(h)}  |  ⏎✅ tick  ⌥⤵️  ⌃🔙",
                arg=f"xact:habit_tick:{h['id']}", valid=True,
                mods={"alt": {"arg": "", "valid": True,
                              "subtitle": "Habit screen",
                              "variables": {"browse_ctx":
                                            f"ctx:habit:{h['id']}"}}}))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["title"])
    if not rows:
        rows = [alfred.item(title=f'No habit matching "{query}"',
                            valid=False)]
    return add_back(rows, "ctx:folders")


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

        elif level == "bridges":
            items = render_bridges(ids, query)

        elif level in ("people", "person"):
            items = render_people(level, ids, query)

        elif level in ("countdowns", "countdown"):
            items = render_countdowns(level, ids, query)

        elif level in ("habits", "habit"):
            items = render_habits(level, ids, query)

        elif level == "tph":
            items = render_tph(ids[0] if ids else "", query)

        elif level == "triage":
            items = render_triage(ids[0] if ids else "", query)

        elif level == "contentpl":
            items = render_contentpl(ids, query)

        elif level == "cmanage":
            items = render_cmanage(query)

        elif level == "lbphotos":
            items = render_lbphotos(ids, query)

        elif level == "manage":
            items = render_manage(ids, query)

        elif level == "stats":
            items = render_stats(query)

        elif level == "cstats":
            items = render_cstats(query)

        elif level == "lbpick":
            items = render_lbpick(ids[0] if ids else "", query,
                                  ids[1] if len(ids) > 1 else "")

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
            items = render_crmmoney(":".join(ids) if ids else "", query)

        elif level == "crmweek":
            items = render_crmweek(query)

        elif level == "crmbook":
            items = render_crmbook(ids[0], query) if ids \
                else _missing(level, "<logbookTid>")

        elif level == "crmsearch":
            items = render_crmsearch(query)

        elif level == "crmcal":
            items = render_crmcal(query)

        elif level == "crmcusts":
            items = render_crmcusts(query)

        elif level == "crmlbs":
            items = render_crmlbs(query)

        elif level == "ccust":
            items = render_ccust(ids, query)

        elif level == "clbs":
            items = render_clbs(query)

        elif level == "lbeagle":
            items = render_lbeagle(ids, query) if ids \
                else _missing(level, "<logbookTid>[:hub|:cu:<custId>]")

        elif level == "imgstage":
            items = render_imgstage(query)

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
