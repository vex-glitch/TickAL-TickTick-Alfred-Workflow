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
    ctx:albpick:<mode>:<lib>:<tid>[:<ret>]   album picker, mode = move (the
                                        stashed Eagle selection → an album,
                                        ➕ New album rows → albcust) | merge
                                        (album B → the row's album A)
    ctx:albcust:<lib>:<stage>:<mode>[:<tid>] customer picker for an album,
                                        mode = new (stashed shots' new album)
                                        | adopt (a John Doe row gains one)
    ctx:okr[:y|o:<id>]                  🥅 OKRs hub: the plan, or one Y / O
                                        with its children (HANDOFF_OKR.md)
    ctx:okrpace[:<tier>]                📈 Pace: quarter · month · week · day,
                                        or that period's plan
    ctx:okrsched:<id>                   📅 schedule an OKR item (extend,
                                        tomorrow, a date - ripple previewed)
    ctx:okraddkr:<oid>                  🔑 KRs under an O, "a | b | c =XY"
    ctx:okrlink:<id>                    🔗 link an OKR item to a task / list
    ctx:okrtag:<id>                     🏷 an OKR item's area / project tag
    ctx:okrimport:<task|note|list>:<pid>:<tid|->
                                        🥅 Add to OKRs: as a KR under an O,
                                        a new O, a new Y (⌘ Actions)
    ctx:okrcarry[:<quarter start>[:<id>]]
                                        ↪️ quarter carry-over: what a quarter
                                        leaves open, or one item's three
                                        choices (carry · won't do · someday)

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
import time
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
                         note_snippet, md_links_display)
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
               "routines": "ctx:routines",
               "tph": "ctx:tph",
               "content": "ctx:contentpl",
               "inbox": "ctx:inbox", "completed": "ctx:completed",
               # main-menu view args (▷50F14423 branches)
               "view_today": "ctx:smart:today",
               "view_tomorrow": "ctx:smart:tomorrow",
               "view_7": "ctx:smart:next7", "view_inbox": "ctx:inbox"}
    # On an OKR screen the bar is TEXT: a date ("tomorrow"), KR names ("today
    # | review") or a search. An alias there would jump away mid-typing
    # (verified: "tomorrow" typed over ctx:countdowns rendered smart:tomorrow).
    riding = os.environ.get("browse_ctx", "") or os.environ.get("browse_back", "")
    # ...and on a 🥘 meal screen the bar is a recipe search (same guard)
    if token in ALIASES and not riding.startswith(("ctx:okr", "ctx:meal")):
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
def task_item(t, pid, sub_count, breadcrumb="", uid="", child_level="subtasks",
              task_map=None):
    """Canonical task row (tasks.py rendering): build_title + actions subtitle,
    ⏎ open, ⇧ complete, ⌥ drill ctx (valid only with children), ⌥⌘ copy.
    `task_map` (id → task): a dateless subtask borrows its parent's date."""
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
        title=build_title(t, buffered=tid in buffered_ids(), task_map=task_map),
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
    # display-only '[name]🔗': a CTA parent's title IS a link (Vex 2026-09-20)
    titles   = [md_links_display(c.get("title", "")) for c in reversed(chain)]
    breadcrumb = join_breadcrumb(lname, top_col, *titles)

    children = [t for t in all_tasks
                if t.get("parentId") == task_id and t.get("status", 0) == 0]

    items = []
    for t in children:
        items.append(task_item(
            t, list_id, _child_count(all_tasks, t["id"]),
            breadcrumb=breadcrumb,
            child_level="subsubtasks",
            task_map=task_by_id,      # dateless child → the parent's ↑📆
        ))

    if query:
        items = filter_task_items(query, items)

    if not items:
        link = f"ticktick:///webapp/#p/{list_id}/tasks/{task_id}"
        items.append(alfred.item(
            # display-only: a childless task's title can BE a link (every
            # routine step, the Todoist imports) - Vex 2026-09-20
            title=f'No subtasks matching "{query}"' if query else f'No subtasks in "{md_links_display(parent_title)}"',
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


def _note_pid(x):
    """The list a records note lives in - Records OR the archive list
    (2026-09-09). Takes the note dict (cheap) or an id (cache scan)."""
    import crm_records as cr
    return cr.pid_of(x)


def _record_vars(note):
    pid = _note_pid(note)
    return {"task_id": note["id"], "task_list_id": pid,
            "list_id": pid, "task_title": note.get("title") or "",
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
                mods["shift"] = {"arg": _open_note_arg(lb),
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
        disp = md_links_display(cr.LINK_RE.sub(r"\1", t.get("title") or ""))   # see _crm_task_row
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
                # what the next price will absorb, not every payment
                # ever (deposit ruling 2026-09-08)
                dep_s = cr.unapplied_deposit_text(_lb2.get("content") or "")
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

def _open_note_arg(note_or_tid):
    """⏎ open-in-TickTick arg for a records note, wherever it lives."""
    tid = note_or_tid["id"] if isinstance(note_or_tid, dict) else note_or_tid
    return f"open:ticktick:///webapp/#p/{_note_pid(note_or_tid)}/tasks/{tid}"


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
                 + "  |  ⏎⤵️  ⇧➕🎨  ⌥⇧➕💬  ⌘⚡  ⌃🔙",
        arg=f"xact:crmbrowse:ctx:crmcust:{c['id']}",
        # chord map 2026-09-08: ⌥ drills, ⇧/⌥⇧ book (the frequent verbs),
        # ↗️ open lives on the hub's head row and in ⌘
        mods={**_picker_mods(),
              "alt": {"arg": "", "valid": True, "subtitle": "Customer hub",
                      "variables": {"browse_ctx": f"ctx:crmcust:{c['id']}"}},
              "shift": {"arg": f"xact:crmnew_go:tattoo:{c['id']}", "valid": True,
                        "subtitle": "➕ New tattoo"},
              "alt+shift": {"arg": f"xact:crmnew_go:consult:{c['id']}", "valid": True,
                            "subtitle": "➕ New consultation"}},
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
    # LINK_RE first (the logbook link → its bare name), THEN any other
    # link a title carries renders '[name]🔗' - a pasted ticktick:/// or
    # web link showed raw markdown here (Vex 2026-09-20). Display-only:
    # task_title and every arg keep the raw title.
    disp = md_links_display(cr.LINK_RE.sub(r"\1", t.get("title") or ""))
    linked = cr.is_session_task(t.get("title") or "")
    chip = "" if linked else " · 🔗 unlinked"
    mods = _picker_mods()
    hit = cr.parse_first_link(t.get("title") or "")
    if hit:
        mods["alt"] = {"arg": "", "valid": True, "subtitle": "Logbook hub",
                       "variables": {"browse_ctx": f"ctx:crmbook:{hit[2]}"}}
    # chord map 2026-09-08 (bug 6a9b1321 'Shift Enter needs to be session
    # done'): ⇧ = the lifecycle advance, ⌥⇧ = the schedule picker. Only
    # on a real session task - a hand-made CRM task keeps ⇧ dead.
    if linked:
        mods["shift"] = {"arg": f"xact:sessiondone:{CRM_ID}:{t['id']}",
                         "valid": True, "subtitle": "✅ Session done"}
        mods["alt+shift"] = {"arg": f"xact:crmsched:{CRM_ID}:{t['id']}",
                             "valid": True, "subtitle": "📅 Reschedule"}
    emo = ("💬" if cr.title_marker(t.get("title") or "") == "Consult"
           else "📅")
    return alfred.item(
        uid=f"{uid_prefix}-t-{t['id']}",
        title=f"{emo} {disp}",
        subtitle=f"{day or 'Dormant · not scheduled'}{chip}"
                 + ("  |  ⏎↗️  ⇧✅  ⌥⇧📅  ⌥⤵️  ⌘⚡  ⌃🔙" if linked
                    else "  |  ⏎↗️  ⌘⚡  ⌥⤵️  ⌃🔙" if hit
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

    # 💰 the money glance on a booking row (Vex 2026-09-08: "every row on
    # CRM should show my percentage"): the linked logbook's open quote
    # remainder, else its last charged entry, each with the 🫵 cut chip.
    # Nothing derivable = nothing shown (no lying "0€").
    _lb_by_id = {}
    def _glance(log_tid):
        if not log_tid:
            return ""
        if not _lb_by_id:
            _lb_by_id.update((l.get("id"), l) for l in cr.records_notes())
        content = (_lb_by_id.get(log_tid) or {}).get("content") or ""
        rem = cr.quote_remainder(content)
        if rem:
            return f"{rem} open{cr.cut_chip(cr._num(rem), rem)}"
        for segs in reversed(cr._entries(content)):
            if len(segs) > 3 and cr.is_gratis(segs[3]):
                continue
            amt, sym, pre = cr._amount_of(segs)
            if amt:
                shown = cr._fmt_money(amt, sym or "€", pre)
                return f"last {shown}{cr.cut_chip(amt, shown)}"
        return ""

    for d, t in pool:
        disp = md_links_display(cr.LINK_RE.sub(r"\1", t.get("title") or ""))   # see _crm_task_row
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
        linked = cr.is_session_task(t.get("title") or "")
        if _l:
            mods["alt"] = {"arg": "", "valid": True,
                           "subtitle": "Logbook hub",
                           "variables": {"browse_ctx": f"ctx:crmbook:{_l[2]}"}}
            arg = f"xact:crmbrowse:ctx:crmbook:{_l[2]}"
            # chord map 2026-09-08: ⇧ Session done · ⌥⇧ Reschedule on a
            # real session task (same as every other session row)
            if linked:
                mods["shift"] = {"arg": f"xact:sessiondone:{CRM_ID}:{t['id']}",
                                 "valid": True, "subtitle": "✅ Session done"}
                mods["alt+shift"] = {"arg": f"xact:crmsched:{CRM_ID}:{t['id']}",
                                     "valid": True, "subtitle": "📅 Reschedule"}
                chips = "⏎⤵️  ⇧✅  ⌥⇧📅  ⌘⚡"
            else:
                mods["alt+shift"] = {"arg": f"xact:notego:{t['id']}",
                                     "valid": True,
                                     "subtitle": "Open in TickTick"}
                chips = "⏎⤵️  ⌘⚡  ⌥⇧↗️"
            g = _glance(_l[2])
            if g:
                chips = f"{g}  |  {chips}"
        else:
            arg = f"open:ticktick:///webapp/#p/{CRM_ID}/tasks/{t['id']}"
            chips = "⏎↗️  ⌘⚡"
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
    # money display vanished (Vex smoke 2026-07-27). The ledger sits UNDER
    # the session rows, totals last (Vex 2026-09-08), radar below it.
    rows.append(alfred.item(
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
    # Vex 2026-09-08: a hub is where you GO, ⌘ is what you DO - every verb
    # this screen used to list (schedule, pay, past session, summary,
    # rename, log a line, edit, archive, delete, content potential, edit
    # this) lives in ⌘ Actions on any logbook row now; here: status, the
    # next booked session (⇧ Session done · ⌥⇧ reschedule), photos, folders.
    rows = [alfred.item(
        uid="bk-open", title=lb.get("title") or "Logbook",
        subtitle=cr.paid_summary(lb.get("content") or "")
                 + (f" · 🖤 {g} gratis" if g else "")
                 + (" · 📁 archived" if archived else "")
                 + f"  |  ⏎↗️  ⌘⚡  ⌥⇧▶️S{n}",
        arg=_open_note_arg(log_tid),
        mods={**_picker_mods(),
              "alt+shift": {"arg": f"xact:crmnew_go:session::{log_tid}",
                            "valid": True,
                            "subtitle": f"▶️ Schedule S{n}"}},
        variables=_record_vars(lb))]
    nt = cr.next_session_task(log_tid)
    if nt:
        rows.append(_crm_task_row(cr, nt[2], uid_prefix="bk"))
    elif not archived:
        rows.append(alfred.item(
            uid="bk-next", title=f"▶️ Schedule S{n}",
            subtitle="Nothing booked · Add window prefilled",
            arg=f"xact:crmnew_go:session::{log_tid}", mods=_picker_mods()))
    setup = cr.last_setup(lb.get("content") or "")
    if setup:
        rows.append(alfred.item(
            uid="bk-setup", title=f"🧰 Last setup · {setup}",
            subtitle="From the previous session · prefilled at the next one",
            valid=False))
    rows += [
        alfred.item(uid="bk-sessphotos", title="📸 Photos",
                    subtitle="Import · file a selection · browse",
                    arg=f"xact:crmbrowse:ctx:lbphotos:{log_tid}",
                    mods=_picker_mods()),
        alfred.item(uid="bk-folders", title="🦅 Folders",
                    subtitle="Stage folders · counts · grid",
                    arg=f"xact:crmbrowse:ctx:lbeagle:{log_tid}:hub",
                    mods=_picker_mods()),
    ]
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

    def _entry_money_cut(x):
        """'600€ · 🫵 300€' - the entry's money with the artist's share
        (Vex 2026-09-08: every row shows the percentage); gratis and
        unpriced entries carry no chip."""
        shown = _entry_money(x)
        if x["gratis"] or not x["amount"]:
            return shown
        return shown + cr.cut_chip(x["amount"], shown)

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
        det = sorted((x for x in cr.entries_detailed()
                      if w0.isoformat() <= x["date"] <= wend.isoformat()
                      and (x["amount"] is not None or x["is_s"])),
                     key=lambda x: x["date"])
        rows = []
        for x in det:
            tid = x["lb"].get("id")
            hrs = f" · {x['minutes'] / 60:g}h" if x["minutes"] else ""
            d = _date.fromisoformat(x["date"])
            rows.append(alfred.item(
                uid=f"wke-{tid}-{x['date']}-{x['marker']}",
                title=f"{_entry_money_cut(x)} · {x['lb'].get('title') or ''}"
                      f" · {x['marker']}",
                subtitle=f"{d.strftime('%a %d %b')}{hrs}  |  ⏎⤵️  ⌥⤵️",
                arg=f"xact:crmbrowse:ctx:crmmoney:lb:{tid}",
                mods={**_picker_mods(), "alt": _hub_alt(tid)}))
        # totals LAST, under the entries (Vex 2026-09-08: "in the last row
        # should be totals")
        rows.append(alfred.item(
            uid="wk-sum",
            title=f"💰 {m2}{cr.cut_chip(r2, m2)}"
                  f" · {n2} session{'s' if n2 != 1 else ''}"
                  + (f" · {h2:g}h" if h2 else ""),
            subtitle=f"Mon {w0.strftime('%d %b')} → Sun "
                     f"{wend.strftime('%d %b')}",
            valid=False))
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
        rows = []
        for x in det:
            hrs = f" · {x['minutes'] / 60:g}h" if x["minutes"] else ""
            rows.append(alfred.item(
                uid=f"lbe-{x['date']}-{x['marker']}",
                title=f"{x['marker']} · {_entry_money_cut(x)}",
                subtitle=f"{x['date']}{hrs}", valid=False))
        # totals LAST (the wk: shape); ⏎ still drills the logbook hub
        rows.append(alfred.item(
            uid="lb-head", title=f"💰 {head}",
            subtitle=(lb.get("title") or "Logbook") + "  |  ⏎⤵️",
            arg=f"xact:crmbrowse:ctx:crmbook:{tid}",
            mods=_picker_mods()))
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
        # Count EVERY session bucket that actually exists, not just s1..sn:
        # a bucket numbered beyond the current session is exactly the mess
        # you go there to fix, and it read "0 shots" while holding 7 (Vex
        # smoke 2026-07-28, Luca's S3). Unnumbered shots bucket as s0.
        for nm in pool:
            m = re.search(r"• S(\d+) •", nm)
            key = f"s{int(m.group(1))}" if m else "s0"
            if key not in out:
                out[key] = sum(1 for x in pool
                               if (re.search(r"• S(\d+) •", x) is None
                                   if key == "s0"
                                   else f"• S{key[1:]} •" in x))
        out["unfiled"] = subtree.get(node.get("id"), 0) - sum(
            subtree.get(cid, 0) for cid in kids.values() if cid)
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
        # Typing the CURRENT session number must not double the screen:
        # the "s" row above already IS S<n> (Vex smoke 2026-07-28 -
        # repairing Luca's mis-numbered shots showed "04 Sessions · S2"
        # twice, once as current and once as older).
        if k != n:
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


# Raw rows used to read "Raw · undecided" ("promotion undecided" in the
# state model). After the migration filled the queue with 270 tattoos
# Vex read the word as "unclassified" (2026-09-07) - the stage word
# alone says it.
_CPL_STATES = [("📸edit", "✂️", "Editing"), ("📸post", "📤", "Ready to post"),
               ("📸raw", "🎞", "Raw")]


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
        alfred.item(uid="cm-albmove", title="📦 Move Eagle selection…",
                    subtitle="Shots → another album · new album",
                    arg="xact:albmove:", mods=_picker_mods()),
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


_FID_LIB = None


def _fid_lib_index():
    """{folder id: library key} across the four libraries, one disk read
    each, memoised per render - a pipeline row must name the library
    that REALLY holds its folder (Raw rows link CRM skeletons for live
    bookings and TV/FM homes for the migrated ones)."""
    global _FID_LIB
    if _FID_LIB is None:
        import eagle as _eg
        idx = {}
        for key, (_nm, path) in _eg.LIBS.items():
            try:
                tree = _eg.disk_folder_tree(path)
            except Exception:
                continue

            def walk(nodes):
                for f in nodes:
                    idx.setdefault(f.get("id"), key)
                    walk(f.get("children") or [])
            walk(tree)
        _FID_LIB = idx
    return _FID_LIB


def _cpl_task_row(t, tag, icon, word, lib, chip, queue="all"):
    """One content-task row. Chord map 2026-09-08 (Vex: ⌘ = do, ⌥ =
    drill, the frequent verbs on ⇧/⌥⇧): ⏎ opens the Eagle folder,
    ⇧ advances the stage (Edit this · File edited · Posted), ⌥ drills
    into the photos (folders, then the grid), ⌥⇧ retires, ⌥⌘ copies
    the Eagle link, ⌘ Actions carries every content verb."""
    title = (t.get("title") or "").strip()
    # markdown of ANY scheme - legacy tasks link http://localhost:41595
    mk = re.match(r"^\[(.*?)\]\(\S+?\)$", title)
    base = (mk.group(1).strip() if mk
            else re.sub(r"\s*eagle://\S+", "", title).strip())
    m = (re.search(r"eagle://folder/([^)\s]+)", title)
         or re.search(r"localhost:41595/folder\?id=([A-Za-z0-9]+)", title))
    fid = m.group(1) if m else ""
    flib = (_fid_lib_index().get(fid) if fid else "") or \
        ("crm" if tag == "📸raw" else lib)
    arg = f"xact:eaglego:{flib}:{fid}" if fid else ""
    mods = dict(_picker_mods())
    legend = ["⏎ folder" if fid else ""]
    if fid:
        mods["alt"] = {"arg": "", "valid": True, "subtitle": "🖼 Photos",
                       "variables": {"browse_ctx":
                                     f"ctx:plfolder:{flib}:{fid}:{t['id']}:{queue}::{lib}"}}
        legend.append("⌥ photos")
        mods["alt+cmd"] = {"arg": f"copy:eagle://folder/{fid}", "valid": True,
                           "subtitle": "🔗 Copy Eagle link"}
    adv = {"📸raw": (f"xact:pledit:{t['id']}", "🎬 Edit this", "⇧ edit"),
           "📸edit": ("xact:filedited", "📥 File edited shots", "⇧ file edits"),
           "📸post": (f"xact:posted:{t['id']}", "📤 Posted", "⇧ posted")}.get(tag)
    if adv:
        mods["shift"] = {"arg": adv[0], "valid": True, "subtitle": adv[1]}
        legend.append(adv[2])
    mods["alt+shift"] = {"arg": f"xact:cretire:{t['id']}", "valid": True,
                         "subtitle": "➖ Retire · row done"}
    legend += ["⌥⇧ retire", "⌘⚡"]
    sub = f"{word} · {chip} · " + " · ".join(x for x in legend if x)
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
        rows += [_cpl_task_row(t, tag, icon, wrd, lib, chip, queue=queue)
                 for t in tasks if tag in tags_of(t)]
    if not rows:
        rows = [alfred.item(title="Queue empty",
                            subtitle="🎬 Edit this on a logbook feeds it",
                            valid=False)]
    if query:
        rows = fuzz.filter_and_score(query, rows,
                                     key_fn=lambda x: x["title"]) or rows
    return add_back(rows, f"ctx:contentpl:{lib}")


def _peek_payload(fid, lib, lb, ret, direct=False, sess=""):
    """b64 payload for the Grid View trampoline (xact:peek) - same shape
    render_lbeagle's peek_arg builds; lb may be '' for a John Doe row
    (grid chords that need a logbook toast instead). Deleted by mistake
    with the ⌥ PL hub (4270dc2, 2026-09-09) while render_plfolder kept
    calling it - every ⌥ on a pipeline row died on a NameError."""
    import base64
    payload = json.dumps({"fid": fid, "sess": sess, "lib": lib, "lb": lb,
                          "ret": ret, "direct": direct})
    return "xact:peek:" + base64.b64encode(payload.encode()).decode()


def render_plfolder(ids, query):
    """🖼 Folder browser for ONE pipeline row (Vex 2026-09-07: "I should
    be able to drill down folders if it is an 02 Edit folder and it has
    subfolders until I get to photos"). Straight from DISK, any library.
    Rows: 🖼 all shots (⏎ grid of the whole subtree), one 📁 per child
    (⏎ drills, ⌥⇧ grids just that child), · unfiled when shots sit in
    this folder beside subfolders. Works for John Doe rows: the logbook
    is optional. ⌃ backs up one level, then to the PL hub."""
    lib = ids[0] if ids else ""
    fid = ids[1] if len(ids) > 1 else ""
    tid = ids[2] if len(ids) > 2 else ""
    queue = ids[3] if len(ids) > 3 else "all"
    up = ids[4] if len(ids) > 4 else ""          # parent folder id, if any
    plib = ids[5] if len(ids) > 5 else lib
    hub = f"ctx:contentpl:{plib}:{queue}" if plib else "ctx:contentpl"
    back = f"ctx:plfolder:{lib}:{up}:{tid}:{queue}::{plib}" if up else hub
    import eagle
    import crm_records as cr
    try:
        lib_path = eagle.LIBS[lib][1]
        root, sub_ids = eagle.disk_subtree_ids(lib_path, fid)
        items = eagle.disk_items_in(lib_path, sub_ids)
    except Exception as e:
        return add_back([alfred.item(title="🦅 Folder unreadable",
                                     subtitle=str(e), valid=False)], back)
    t = cache_store.find_task(tid) if tid else None
    hit = cr.parse_first_link((t or {}).get("content") or "")
    lb = hit[2] if hit else ""
    here = f"ctx:plfolder:{':'.join(ids)}"
    tvars = ({"task_id": t["id"], "task_list_id": t.get("_projectId") or t.get("projectId") or "",
              "list_id": t.get("_projectId") or t.get("projectId") or "",
              "task_title": t.get("title") or "", "item_type": "task"} if t else {})

    def _sub(node):
        out = {node["id"]}
        for ch in node.get("children") or []:
            out |= _sub(ch)
        return out
    kids = sorted(root.get("children") or [], key=lambda c: c.get("name") or "")
    n_all = len(items)
    rows = [alfred.item(
        uid=f"plf-all-{fid}", title=f"🖼 {root.get('name') or fid}",
        subtitle=f"{n_all} shot{'' if n_all == 1 else 's'} in all"
                 + ("  |  ⏎🖼 grid  ⌥⌘🔗  ⌃🔙" if n_all else "  |  ⌥⌘🔗  ⌃🔙"),
        arg=_peek_payload(fid, lib, lb, here), valid=bool(n_all),
        mods={**_picker_mods(), "alt+cmd": {"arg": f"copy:eagle://folder/{fid}",
                                            "valid": True, "subtitle": "🔗 Copy Eagle link"}},
        variables=tvars)]
    for c in kids:
        cset = _sub(c)
        n = len({it["id"] for it in items if set(it.get("folders") or []) & cset})
        deeper = bool(c.get("children"))
        m = _picker_mods()
        if n:
            m["alt+shift"] = {"arg": _peek_payload(c["id"], lib, lb, here),
                              "valid": True, "subtitle": "🖼 Grid of this folder"}
        rows.append(alfred.item(
            uid=f"plf-{c['id']}", title=f"📁 {c.get('name') or '?'}",
            subtitle=f"🖼 {n}" + (" · has subfolders" if deeper else "")
                     + "  |  ⏎⤵️" + ("  ⌥⇧🖼" if n else "") + "  ⌃🔙",
            arg=f"xact:crmbrowse:ctx:plfolder:{lib}:{c['id']}:{tid}:{queue}:{fid}:{plib}",
            mods=m, variables=tvars))
    if kids:
        strays = [it for it in items if fid in (it.get("folders") or [])]
        if strays:
            rows.append(alfred.item(
                uid=f"plf-strays-{fid}", title="· unfiled",
                subtitle=f"🖼 {len(strays)} · in this folder, not in a subfolder  |  ⏎🖼  ⌃🔙",
                arg=_peek_payload(fid, lib, lb, here, direct=True),
                mods=_picker_mods(), variables=tvars))
    if query:
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, back)


# ── Albums: move · rename · merge · customer-later (2026-09-11) ──────────
# Two picker screens for the album verbs (xact.py `alb*`, ⌘ Actions
# '🖼 Album…' on a pipeline row, 🎛 Manage > Content). Both read
# src/albums.py LAZILY (the substrate: the stash a picker screen inherits
# from the verb's process, the disk-read album list); a missing module
# renders one honest row instead of a crash. Disk reads only - looking
# never switches the Eagle library.
_ALB_STAGE_DIRS = (("Raw", "01 Raw"), ("Edit", "02 Edit"),
                   ("Portfolio", "04 Portfolio"))


def _alb_missing(back, err=""):
    return add_back([alfred.item(
        title="albums module missing",
        subtitle=(str(err) or "src/albums.py absent") + "  |  ⌃🔙",
        valid=False)], back)


def _alb_row(tid):
    """(base, fid, lib) of a pipeline row from the cache: base + fid from
    the title (both link shapes), lib = its list's CONTENT_DESTS key."""
    t = cache_store.find_task(tid) if tid else None
    if not t:
        return "", "", ""
    title = (t.get("title") or "").strip()
    mk = re.match(r"^\[(.*?)\]\(\S+?\)$", title)
    base = (mk.group(1).strip() if mk
            else re.sub(r"\s*eagle://\S+", "", title).strip())
    m = (re.search(r"eagle://folder/([^)\s]+)", title)
         or re.search(r"localhost:41595/folder\?id=([A-Za-z0-9]+)", title))
    pid = t.get("_projectId") or t.get("projectId") or ""
    lib = next((k for k, v in _areas.CONTENT_DESTS.items() if v[0] == pid), "")
    return base, (m.group(1) if m else ""), lib


def render_albpick(ids, query):
    """📦/🔗 Album picker. ctx:albpick:<mode>:<lib>:<tid>[:<ret>]
    mode=move: head = the stash (n shots · the first SOURCE ALBUM ·
    'k albums' when several · 'n loose' for shots whose folders are no
    album - the 03 Post shelf, an inbox, the root - never counted as a
    source); no stash = one 'Select shots in Eagle first' row. Then ➕
    New album in 01 Raw / 02 Edit / 04 Portfolio → ctx:albcust:<lib>:
    <stage>:new, then every album of the library (albums.library_albums:
    01 Raw, 02 Edit any depth, 04 Portfolio; never 03 Post) →
    xact:albmoveto:<lib>:<fid>. Portfolio targets say 'finals only'.
    mode=merge: head = 'Merge into {A}', the row's own album and its
    children left out, and the FINALS RULE in the picker: a Raw/Edit
    survivor never lists a 04 Portfolio album (its finals would be
    relabelled Raw), a Portfolio survivor lists only Portfolio albums
    (chip 'finals only') → xact:albmergeinto:<tid>:<fid>.
    Fuzzy on the album name; ⌃ = ret, default ctx:contentpl:<lib>."""
    mode = ids[0] if ids else "move"
    lib = ids[1] if len(ids) > 1 else ""
    tid = ids[2] if len(ids) > 2 else ""
    ret = ":".join(ids[3:]) if len(ids) > 3 else ""
    back = ret or f"ctx:contentpl:{lib}"
    try:
        import albums
    except Exception as e:
        return _alb_missing(back, e)
    head = []
    fixed = []
    sur_fid = sur_stage = ""
    st, shots = {}, []
    if mode == "merge":
        base, sur_fid, _lib = _alb_row(tid)
        head.append(alfred.item(
            title=f"🔗 Merge into {base or 'this album'} · pick the album to absorb",
            subtitle="Its shots · row · logbook fold into this one  |  ⌃🔙",
            valid=False))
        chip = "⏎🔗"
    else:
        try:
            st = albums.unstash() or {}
        except Exception:
            st = {}
        shots = st.get("items") or []
        if not shots:
            return add_back([alfred.item(
                title="Select shots in Eagle first",
                subtitle="Then 📦 Move Eagle selection  |  ⌃🔙",
                valid=False)], back)
        for stage, folder in _ALB_STAGE_DIRS:
            fixed.append(alfred.item(
                uid=f"albp-new-{stage}",
                title=f"➕ New album in {folder}",
                subtitle="Customer → name → dates"
                         + (" · finals only" if stage == "Portfolio" else "")
                         + "  |  ⏎⚡",
                arg=f"xact:crmbrowse:ctx:albcust:{lib}:{stage}:new",
                match=f"new album {folder}", mods=_picker_mods()))
        chip = "⏎📦"
    lib_err = None
    try:
        albs = albums.library_albums(lib)
    except Exception as e:
        lib_err = alfred.item(title="🦅 Library unreadable",
                              subtitle=str(e), valid=False)
        albs = []
    by_fid = {a.get("fid"): a for a in albs}
    if mode == "merge":
        sur_stage = (by_fid.get(sur_fid) or {}).get("stage") or ""
        if not sur_stage and sur_fid:
            try:
                sur_stage = albums.album_stage(lib, sur_fid) or ""
            except Exception:
                sur_stage = ""
        if sur_fid and not sur_stage and not lib_err:
            # the row's folder is no album of THIS library (a live-era
            # row still linking its CRM skeleton, or a folder the disk
            # list cannot see): merging library albums into it would be
            # a cross-library move, which Eagle cannot do - say so
            return add_back([alfred.item(
                uid="albpick-nolib",
                title="🔗 This row's album is not in this library",
                subtitle=f"{lib.upper()} holds no album for it · 🎬 Edit this"
                         " first  |  ⌃🔙",
                valid=False)], back)
    else:
        # the head counts ALBUM sources only: a shot on the 03 Post shelf
        # sits in its album AND on the shelf, and the shelf is no album.
        # An album = a library_albums entry, or (the disk list lags a
        # fresh folder / is unreadable) a source whose name is not a
        # known non-album: shelf, stage root, inbox, bin.
        src_names = st.get("source_names") or {}

        def is_album_src(f):
            if f in by_fid:
                return True
            nm = albums._norm(src_names.get(f) or "")
            return bool(nm) and not (
                re.fullmatch(r"(?:\d+\s*)?(raw|edit|post|portfolio)", nm)
                or nm in ("deleted", "duplicates")
                or nm.startswith("eagle inbox"))
        srcs = [f for f in (st.get("sources") or {}) if is_album_src(f)]
        names = [src_names.get(f) or (by_fid.get(f) or {}).get("name") or ""
                 for f in srcs]
        n_loose = sum(1 for it in shots
                      if not any(is_album_src(f) for f in it.get("folders") or []))
        title = f"📦 {len(shots)} shots from {names[0] if names else 'Eagle'}"
        if len(srcs) > 1:
            title += f" · {len(srcs)} albums"
        if n_loose:
            title += f" · {n_loose} loose"
        head.append(alfred.item(title=title,
                                subtitle="Pick the album they go to  |  ⌃🔙",
                                valid=False))
    if lib_err:
        head.append(lib_err)
    # a copied CRM skeleton's empty stage children (01 Consultation …
    # 06 Healed under an 02 Edit album, FM: Shteffi - Ker) are not
    # albums: hidden when deeper than level 1 AND empty; every other
    # row stays (albums 📦 move, 2026-09-11)
    try:
        import eagle as _eg
        skel = {s.casefold() for s in _eg.SKELETON}
    except Exception:
        skel = set()

    def under_survivor(a):
        seen, p = set(), a.get("parent")
        while p and p not in seen:
            if p == sur_fid:
                return True
            seen.add(p)
            p = (by_fid.get(p) or {}).get("parent")
        return False

    rows = []
    for a in albs:
        fid = a.get("fid", "")
        stage = a.get("stage", "")
        if mode == "merge":
            if fid == sur_fid or under_survivor(a):
                continue
            # the finals rule, picker half: finals live in 04 Portfolio,
            # so a Raw/Edit survivor never absorbs a Portfolio album and
            # a Portfolio survivor absorbs nothing but finals
            if sur_stage and (stage == "Portfolio") != (sur_stage == "Portfolio"):
                continue
        if (a.get("depth", 1) > 1 and not a.get("n")
                and (a.get("name") or "").casefold() in skel):
            continue
        sub = f"{a.get('path') or stage} · 🖼 {a.get('n', 0)}"
        if stage == "Portfolio":
            sub += " · finals only"
        arg = (f"xact:albmergeinto:{tid}:{fid}" if mode == "merge"
               else f"xact:albmoveto:{lib}:{fid}")
        rows.append(alfred.item(
            uid=f"albp-{fid}", title=a.get("name", ""),
            subtitle=f"{sub}  |  {chip}", arg=arg,
            match=a.get("name", ""), mods=_picker_mods()))
    if not rows:
        rows = [alfred.item(title="No albums here",
                            subtitle="01 Raw · 02 Edit · 04 Portfolio hold none",
                            valid=False)]
    body = fixed + rows
    if query:
        body = fuzz.filter_and_score(
            query, body, key_fn=lambda x: x.get("match", x["title"])) or body
    return add_back(head + body, back)


def render_albcust(ids, query):
    """👤 Customer picker for an album. ctx:albcust:<lib>:<stage>:<mode>
    [:<tid>]. mode=new (the stashed shots' new album): ❓ Don't know ·
    John Doe album → xact:albnew:<lib>:<stage>:none, ➕ New customer… →
    …:new, then every customer + lead → …:<custTid>. mode=adopt (a John
    Doe row gains a customer): ➕ New customer… → xact:albadopt:<tid>:new,
    customers → xact:albadopt:<tid>:<custTid>. Subtitle = the person's
    tattoo count. Fuzzy on the name; no hit keeps the ➕/❓ rows (they
    are new). ⌃ = the album picker (new) / ctx:contentpl:<lib> (adopt)."""
    lib = ids[0] if ids else ""
    stage = ids[1] if len(ids) > 1 else ""
    mode = ids[2] if len(ids) > 2 else "new"
    tid = ids[3] if len(ids) > 3 else ""
    back = (f"ctx:contentpl:{lib}" if mode == "adopt"
            else f"ctx:albpick:move:{lib}:")
    gate = _records_gate()
    if gate:
        return add_back(gate, back)
    import crm_records as cr
    folder = dict(_ALB_STAGE_DIRS).get(stage, stage or "album")

    def arg_for(who):
        return (f"xact:albadopt:{tid}:{who}" if mode == "adopt"
                else f"xact:albnew:{lib}:{stage}:{who}")

    if mode == "adopt":
        base = _alb_row(tid)[0]
        head = alfred.item(title=f"👤 {base or 'This album'} · whose tattoo?",
                           subtitle="Logbook minted · album + row renamed  |  ⌃🔙",
                           valid=False)
    else:
        head = alfred.item(title=f"📦 New album in {folder} · whose tattoo?",
                           subtitle="Name + dates asked next  |  ⌃🔙",
                           valid=False)
    fixed = []
    if mode != "adopt":
        fixed.append(alfred.item(
            uid="albc-none", title="❓ Don't know · John Doe album",
            subtitle="Album named after the tattoo · no logbook  |  ⏎⚡",
            arg=arg_for("none"), match="dont know john doe unknown",
            mods=_picker_mods()))
    fixed.append(alfred.item(
        uid="albc-new", title="➕ New customer…",
        subtitle="Name asked · customer note minted  |  ⏎⚡",
        arg=arg_for("new"), match="new customer", mods=_picker_mods()))
    # tattoo counts: one pass over the logbooks (open + archived)
    counts, seen_lb = {}, set()
    for tag in (_areas.LOGBOOK_TAG, _areas.ARCHIVE_TAG):
        for lb in cr.records_notes(tag):
            if lb["id"] in seen_lb:
                continue
            seen_lb.add(lb["id"])
            hit = cr.parse_first_link(lb.get("content") or "")
            if hit:
                counts[hit[2]] = counts.get(hit[2], 0) + 1
    rows, seen = [], set()
    for c in (cr.records_notes(_areas.CUSTOMER_TAG)
              + cr.records_notes(_areas.LEAD_TAG)):
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        n = counts.get(c["id"], 0)
        who = cr.customer_display(c)
        rows.append(alfred.item(
            uid=f"albc-{c['id']}",
            title=f"{'🎣' if cr.is_lead(c) else '👤'} {who}",
            subtitle=f"{n} tattoo{'' if n == 1 else 's'}  |  ⏎⚡",
            arg=arg_for(c["id"]), match=who, mods=_picker_mods(),
            variables=_record_vars(c)))
    if query:
        rows = fuzz.filter_and_score(
            query, rows, key_fn=lambda x: x.get("match", x["title"]))
    return add_back([head] + fixed + rows, back)


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
        return "🔴", (f"📦 {cr.note_year(lb)}" if cr.note_year(lb)
                      else "📦 year?")
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
                     "valid": True, "subtitle": "⇧ Photos · folders"}
    # chord map 2026-09-08: ⌥⇧ books the next session (the Add window
    # prefilled, forecast asked); archived logbooks get the reopen ask
    # inside crmnew_go, so the chord stays live everywhere
    mods["alt+shift"] = {"arg": f"xact:crmnew_go:session::{lb['id']}",
                         "valid": True, "subtitle": "▶️ Schedule next session"}
    # ⌥⌘ copies the TICKTICK link here (Vex 2026-07-28) - the Eagle link
    # is one step deeper, on ⇧ Content, where Eagle is what you are
    # looking at. Same chord, right link for the world you are in.
    mods["alt+cmd"] = {"arg": f"copy:{_open_note_arg(lb)[5:]}",
                       "valid": True, "subtitle": "🔗 Copy TickTick link"}
    return alfred.item(
        uid=f"{uid_prefix}-{lb['id']}",
        title=f"🎨 {name}  {circle} " + " • ".join(head),
        subtitle=" · ".join(sub) + "  |  ⌥ hub  ⇧ photos  ⌥⇧ book  |  ⌘⚡ ⏎↗️"
                 + ("  ⌥⌘🔗" if fid else "") + "  ⌃🔙",
        arg=_open_note_arg(lb),
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

    def _lbe_mods(stage=None, link="", bucket=""):
        # ⌥⇧ is a free executing chord (canvas fact): on STAGE rows it
        # imports the Photos selection INTO that stage (Vex ask
        # 2026-07-26); the head row keeps 🎬 Edit this. ⌥⌘ rides the
        # modURL copy chain (copies whatever arg it gets) - the
        # folder's eagle:// link, zero canvas. ⇧ is the OTHER one
        # (modComplete passes the arg to dispatch): on a bucket row it
        # moves the WHOLE bucket to a stage you pick (Vex 2026-07-28).
        # _picker_mods pins ⇧ dead, so claiming it is an override.
        m = _picker_mods()
        if stage:
            m["alt+shift"] = {"arg": f"xact:sessphotos:{log_tid}:{stage}",
                              "valid": True,
                              "subtitle": "📸 Photos selection → here"}
        else:
            m["alt+shift"] = {"arg": f"xact:editthis:{log_tid}",
                              "valid": True, "subtitle": "🎬 Edit this"}
        if bucket:
            m["shift"] = {
                "arg": f"xact:crmbrowse:ctx:bulkstage:{log_tid}:{bucket}",
                "valid": True, "subtitle": "⇧ Move ALL of these → a stage"}
        if link:
            m["alt+cmd"] = {"arg": f"copy:eagle://folder/{link}",
                            "valid": True,
                            "subtitle": "🔗 Copy Eagle link"}
        return m

    # Which rows own a bucket the bulk move can empty. 04 Sessions is
    # deliberately absent: it is a CONTAINER of sessions, and "move all
    # sessions at once" is never what you mean.
    _LBE_BUCKETS = {"01 Consultation": "consult", "02 Preparation": "prep",
                    "03 Design": "design", "05 Finished": "finished",
                    "06 Healed": "healed"}

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
        bucket = _LBE_BUCKETS.get(name) if n else ""
        rows.append(alfred.item(
            uid=f"lbe-{cid}", title=name,
            subtitle=f"🖼️ {n}"
                     + (f"  |  ⏎🖼  ⌘⚡  {chord}"
                        + ("  ⇧➡️" if bucket else "")
                        + "  ⌥⌘🔗  ⌃🔙" if n
                        else f"  |  {chord}  ⌥⌘🔗  ⌃🔙"),
            arg=peek_arg(cid), valid=bool(n),
            mods=_lbe_mods(skey, cid, bucket), variables=_record_vars(lb)))
        if name == "04 Sessions" and n:
            sess = {}
            for it in shots:
                m = re.search(r"• S(\d+) •", it.get("name") or "")
                sess.setdefault(int(m.group(1)) if m else 0, []).append(it)
            for k in sorted(sess):
                label = f"S{k}" if k else "unnumbered"
                rows.append(alfred.item(
                    uid=f"lbe-{cid}-s{k}", title=f"   · {label}",
                    subtitle=f"🖼️ {len(sess[k])}"
                             "  |  ⏎🖼  ⌥⇧📸  ⇧➡️  ⌥⌘🔗  ⌃🔙",
                    arg=peek_arg(cid, f"s{k}"),
                    mods=_lbe_mods(f"s{k}" if k else "s", cid,
                                   f"s{k}" if k else "s0"),
                    variables=_record_vars(lb)))
    # honest strays: shots dragged straight into the tattoo root folder
    # (outside the 01-06 skeleton) get their own row (review find)
    strays = list({it["id"]: it for it in items
                   if root["id"] in (it.get("folders") or [])}.values())
    if strays:
        ns = len(strays)
        rows.append(alfred.item(
            uid=f"lbe-{root['id']}-strays", title="· unfiled",
            subtitle=f"🖼️ {ns} · folder root  |  ⏎🖼  ⌥⇧🎬  ⇧➡️  ⌃🔙",
            arg=peek_arg(root["id"], direct=True),
            mods=_lbe_mods(bucket="unfiled"), variables=_record_vars(lb)))
    if query:
        rows = rows[:1] + (fuzz.filter_and_score(
            query, rows[1:], key_fn=lambda x: x["title"]) or rows[1:])
    return add_back(rows, back)


def render_bulkstage(ids, query):
    """⇧ on a folder-screen bucket row: where does the WHOLE bucket go?
    (Vex green 2026-07-28 - repairing a mis-numbered session one shot at
    a time was the only road before this.) Same _stage_rows skeleton as
    every other stage screen, minus the bucket you are standing in."""
    import crm_records as cr
    log_tid = ids[0] if ids else ""
    src = ids[1] if len(ids) > 1 else ""
    back = f"ctx:lbeagle:{log_tid}"
    lb = next((l for l in cr.records_notes() if l.get("id") == log_tid), None)
    if not (lb and src):
        return add_back([alfred.item(title="Lost the bucket context",
                                     subtitle="Re-enter from the folder screen",
                                     valid=False)], back)
    n = cr.current_snum(lb.get("content") or "", log_tid)
    counts = _stage_counts(cr, lb, n)
    src_label = ({"unfiled": "unfiled", "s0": "unnumbered"}.get(src)
                 or (f"S{src[1:]}" if re.fullmatch(r"s\d+", src) else
                     next((f for k, f, _s in _TRIAGE_STAGES if k == src), src)))
    have = counts.get(src, 0) if counts else 0
    rows = [alfred.item(
        title=f"🖼 Move {src_label} · {have} shot{'' if have == 1 else 's'}",
        subtitle=f"Everything in {src_label} → the stage you pick "
                 f"({cr.logbook_base(lb)})", valid=False)]
    srows, _digit = _stage_rows(
        "bulk", n, query, lambda k: f"xact:bulkmove:{log_tid}:{src}:{k}",
        f"Current session · names get S{n}",
        "Older session · names get S{k}",
        mods_fn=lambda _k: _picker_mods(), counts=counts)
    # never offer the bucket you are already in ("s" and "s<n>" are the
    # same target when the current session is n)
    same = {src} | ({"s", f"s{n}"} if src in ("s", f"s{n}") else set())
    rows += [r for r in srows
             if (r.get("arg") or "").rsplit(":", 1)[-1] not in same]
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
        # album move: lib resolved from the OPEN library (xact album_move)
        ("mg-albmove", "📦 Move Eagle selection…",
         "Shots → another album · new album", "xact:albmove:"),
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
                    title="🖼 Browse photos",
                    subtitle="Folders → grid · ⏎ opens in Eagle · "
                             "⌥⇧ attaches a shot to its session",
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
    year = ""
    if scopes:
        names = "|".join(re.escape(l) for l, _p in scopes)
        m = re.match(rf"(?i)^({names})(?:\s+(.*))?$", term)
        if m:
            label = m.group(1)
            filt = next(p for l, p in scopes if l.lower() == label.lower())
            term = (m.group(2) or "").strip()
            # "Archived 2023" = one kanban column of 📦CRM Archive;
            # "Archived ?" = the notes still without a year (2026-09-09)
            if label.lower() == "archived":
                ym = re.match(r"^(\d{4}|\?)(?:\s+(.*))?$", term)
                if ym:
                    year = ym.group(1)
                    term = (ym.group(2) or "").strip()
                    base_f = filt
                    want = "" if year == "?" else year
                    filt = (lambda cr, o, _b=base_f, _w=want:
                            _b(cr, o) and cr.note_year(o) == _w)
        elif term.startswith("/"):
            frag = term[1:].strip().lower()
            menu = [alfred.item(
                uid=f"{uid}-sc-{l}", title=f"{emoji} {l}",
                subtitle=f"Scope {name.lower()} to {l.lower()}",
                valid=False, autocomplete=f"{l} ")
                for l, _p in scopes if frag in l.lower()]
            if scope == "lo":
                years = {}
                for lb in cr.logbook_notes():
                    if cr.logbook_archived(lb):
                        y = cr.note_year(lb) or "?"
                        years[y] = years.get(y, 0) + 1
                for y in sorted(years, reverse=True):
                    if frag and frag not in y and frag not in "archived":
                        continue
                    menu.append(alfred.item(
                        uid=f"{uid}-sc-y{y}",
                        title=f"📦 {y if y != '?' else 'year unknown'}"
                              f" · {years[y]}",
                        subtitle="One archive column",
                        valid=False, autocomplete=f"Archived {y} "))
            return add_back(menu or [alfred.item(
                title=f'No scope matching "{frag}"', valid=False)],
                "ctx:crmhub")
    if label.lower() == "archived" and _areas.archive_id():
        list_id = _areas.archive_id()
    rows = [alfred.item(
        uid=f"{uid}-open", title=f"{emoji} {name}"
                                 + (f" · {label}" if label else "")
                                 + (f" · 📦 {year}" if year else ""),
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
    new = alfred.item(
        uid="crmcal-new", title="➕ New entry",
        subtitle="Tattoo · consultation · customer · lead",
        arg="xact:crmbrowse:ctx:manage:crm", mods=_picker_mods())
    return _crmlist_drill("crmcal", "📅", "Calendar", _areas.CRM_ID,
                          "ca", query, extra=(week, new))


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
        arg=_open_note_arg(cust), mods=_picker_mods(),
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
    # Vex 2026-09-08: verbs (new tattoo, log a line, edit, rename,
    # aftercare, make customer, cold lead, delete) live in ⌘ Actions on
    # any customer row; the hub is the person: contact, tattoos, sessions.
    if not lbs:
        rows.append(alfred.item(
            uid="hub-newtattoo", title=f"➕ New tattoo for {name}",
            subtitle="Logbook + S1 → scheduling",
            arg=f"xact:crmnew_go:tattoo:{cust_tid}", mods=_picker_mods()))
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
                title=md_links_display(title) or "Untitled",   # display-only (Vex 2026-09-20)
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
        disp = md_links_display(cr.LINK_RE.sub(r"\1", t.get("title") or ""))   # see _crm_task_row
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
        disp = md_links_display(cr.LINK_RE.sub(r"\1", t.get("title") or ""))   # see _crm_task_row
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
    # notes too - buffer_pairs counts a buffered NOTE alive, so a tasks-only
    # lookup showed "Buffer is empty" while search still said "Buffer · 1"
    by_id = {t["id"]: t for t in all_tasks + (cache_store.get("all_notes") or [])}
    items = []
    for pid, tid in pairs:
        t = by_id.get(tid)
        if not t:
            continue   # stray (completed/deleted since buffering) - skip
        it = task_item(t, pid, _child_count(all_tasks, tid),
                       breadcrumb=t.get("_projectName", ""), uid=f"buf-{tid}",
                       task_map=by_id)
        it["variables"]["item_type"] = "buffer_item"   # ⌘ → batch menu
        items.append(it)
    if query:
        items = filter_task_items(query, items)
    if not items:
        items = [alfred.item(title="🅿️ Buffer is empty",
                             subtitle="⌥⇧🅿️ or ⌘⚡ on any task",
                             valid=False)]
    return add_back(items, "ctx:folders")

# ── Level: pnlist (💫 every note of ONE tier, newest first) ─────────────────
def render_pnlist(ids, query):
    """ctx:pnlist:<daily|weekly|monthly|quarterly|yearly> - the archive behind
    a periodic row's ⌥ (Vex 2026-09-12: "I should be able to enter a list of
    those notes, current at top, the oldest at the bottom ... so I can
    actually open any note, not just this week's").

    Tier membership comes from the note's TIER TAG, the same truth the engine
    indexes on, never from parsing a title. Sorting is the title descending,
    which is chronological for every tier because each one leads with a
    zero-padded number (2026-09-12 · Sat · 2026-W37 · 2026-09 September ·
    2026-Q3 · 2026). The CACHE is the pool: this renders on every keystroke.
    """
    import periodic_model as pm
    import areas
    spec = (ids[0] if ids else "").lower()
    if spec not in pm.TIER_TAGS:
        return add_back([alfred.item(title="💫 Unknown period", valid=False)],
                        "ctx:folders")
    if not areas.periodic_configured():
        return add_back([areas.setup_row("Periodic notes", "48-periodic.md")],
                        "ctx:folders")
    want = pm.TIER_TAGS[spec].lower()
    pid = areas.PERIODIC_LIST_ID
    seen, pool = set(), []
    for n in (cache_store.get("all_notes") or []) + (cache_store.get("all_tasks") or []):
        nid = n.get("id")
        if not nid or nid in seen:
            continue
        if (n.get("_projectId") or n.get("projectId")) != pid:
            continue
        if want not in {str(x).lower() for x in (n.get("tags") or [])}:
            continue
        seen.add(nid)
        pool.append(n)
    pool.sort(key=lambda n: (n.get("title") or ""), reverse=True)

    now = pm.title(pm.period_for(spec, datetime.now().date()))
    items = []
    for n in pool:
        title = n.get("title") or "Untitled"
        here = title.startswith(now) or now.startswith(title)
        items.append(alfred.item(
            uid=f"pnl-{n['id']}",
            title=("⭐️ " if here else "") + title,
            subtitle=("Current  |  ⏎↗️  ⌃🔙" if here else "⏎↗️  ⌃🔙"),
            arg=f"open:ticktick:///webapp/#p/{pid}/tasks/{n['id']}",
            valid=True,
            variables={"task_id": n["id"], "task_list_id": pid,
                       "task_title": title, "item_type": "note"},
            mods=_picker_mods()))
    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])
    if not items:
        items = [alfred.item(
            uid="pnl-none",
            title=(f'No {spec} note matching "{query}"' if query
                   else f"No {spec} notes yet"),
            subtitle="They are minted as you use them", valid=False)]
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
                uid=f"pc-{t['id']}", title=f"📌 {md_links_display(t.get('title', ''))}",
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
                uid=f"plt-{t['id']}", title=build_title(t),
                subtitle=(f"📂 {t.get('_projectName') or 'Inbox'}"
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
def render_routines(query):
    """🌓 Routines: one row per routine, from src/routines.py (config, never
    name matching). The title is the LIVE task title, so the emoji Vex keeps
    on the task in TickTick is the emoji on the row.

    Chords (Vex 2026-09-12): ⏎ opens the task in TickTick · ⌃ STARTS it (its
    "… • Start" KM macro, through the ⌃ router → XAct) · ⇧ ticks it done (a
    repeating routine rolls to its next date) · ⌥ browses its steps · ⌘ is
    Actions, as everywhere. NO add_back here: ⌃ is the start chord on this
    screen, and this screen hangs off the main menu."""
    import routines as rt
    tasks = cache_store.get("all_tasks") or []
    by_id = {t.get("id"): t for t in tasks}
    kids = {}
    for t in tasks:
        if t.get("parentId") and t.get("status", 0) == 0:
            kids[t["parentId"]] = kids.get(t["parentId"], 0) + 1

    rows = []
    for r in rt.ROUTINES:
        t = by_id.get(r["tid"]) or {}
        title = t.get("title") or r["label"]
        pid = t.get("projectId") or r["pid"]
        n = kids.get(r["tid"], 0)
        steps = f"{n} steps" if n != 1 else "1 step"
        if not t:
            steps = "not synced yet"
        # which occurrence is live, so the row says it before ⌃ does
        st = rt.due_state(t)
        chip = {"today": "due today", "overdue": "overdue",
                "ahead": f"next {st['date']:%a %d %b}" if st["date"] else ""}.get(st["state"], "")
        if st["state"] == "overdue" and st["date"]:
            chip = f"overdue since {st['date']:%a %d %b}"
        # NATIVE since 2026-09-12: the step list in routines.json, no
        # Keyboard Maestro. The macro uid stays in the registry as the
        # fallback road while Vex smokes this.
        ctrl = {"arg": f"xact:routine_start:{r['key']}",
                "subtitle": "▶️ Start", "valid": True}
        rows.append(alfred.item(
            uid=f"rt-{r['key']}",
            title=title,
            subtitle=f"{steps}{' · ' + chip if chip else ''}  |  ⏎↗️  ⌃▶️  ⇧✅  ⌥📋  ⌘⇧📊  ⌘⚡",
            arg=f"open:ticktick:///webapp/#p/{pid}/tasks/{r['tid']}",
            valid=True,
            variables={"task_id": r["tid"], "task_list_id": pid,
                       "task_title": title, "item_type": "task"},
            mods={
                "cmd":   {"arg": "", "subtitle": "⌘ Actions"},
                "shift": {"arg": f"complete:{pid}:{r['tid']}:{title}",
                          "subtitle": "✅ Done"},
                "alt":   {"arg": "", "subtitle": "📋 Steps",
                          "valid": bool(n),
                          "variables": {"browse_ctx": f"ctx:subtasks:{pid}:{r['tid']}"}},
                "ctrl":  ctrl,
                # ⌘⇧ → the tracker, this routine on top (the ⌘⇧ router sends
                # a "ctx:" arg into Browse instead of the Add window)
                "cmd+shift": {"arg": f"ctx:rtrack:{r['key']}",
                              "subtitle": "📊 Tracker"},
            }))
    # 🥘 the meal-prep hub, this screen's neighbour and its zero-canvas door
    # until the main-menu row lands (HANDOFF_MEAL.md). ⏎ rides the BrowseCtx
    # trampoline (a plain row cannot switch ctx on ⏎); ⌃ stays dead here.
    rows.append(alfred.item(
        uid="rt-meal-hub", title="🥘 Meal Prep hub",
        subtitle="This week · the next 13 weeks · groceries · library  |  ⏎⤵️  ⌥⤵️",
        arg="xact:crmbrowse:ctx:meal", valid=True,
        variables={"task_id": "", "task_list_id": "", "task_title": "",
                   "item_type": ""},
        mods={"cmd": {"arg": "", "valid": False, "subtitle": ""},
              "shift": {"arg": "", "valid": False, "subtitle": ""},
              "alt": {"arg": "", "valid": True, "subtitle": "⤵️",
                      "variables": {"browse_ctx": "ctx:meal"}},
              "ctrl": {"arg": "", "valid": False, "subtitle": ""},
              "cmd+shift": {"arg": "ctx:meal", "subtitle": "⤵️"}}))
    if query:
        rows = [r for r in rows if fuzz.score(query, r["title"]) > 0]
    return rows or [alfred.item(title="No routine matches", valid=False)]


def render_rconfirm(ids, query):
    """The ⌃ Start safety net (Vex 2026-09-12): this routine is NOT due
    today - today's run is done, or today is not its day - so the start was
    held and this screen says which occurrence it would open.

    Head line names today and the schedule; row 1 starts the next occurrence
    anyway, with its day spelled out; row 2 names the previous one (derived
    from the rule - the series has already rolled past it, so it needs no
    completion record) with the real completion time when the cache has it."""
    import routines as rt
    from datetime import date as _date
    key = ids[0] if ids else ""
    r = rt.by_key(key)
    if not r:
        return add_back([alfred.item(title="Unknown routine", valid=False)],
                        "ctx:routines")
    t = cache_store.find_task(r["tid"]) or {}
    name = t.get("title") or r["label"]
    import dayroll
    today = dayroll.today()           # the routine's day rolls at 04:00
    st = rt.due_state(t, today)
    nxt, prev = st["date"], st["prev"]

    def when(d):
        if not d:
            return "date unknown"
        delta = (d - today).days
        chip = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(delta)
        return f"{d:%A %Y-%m-%d}" + (f" · {chip}" if chip else "")

    # the completion time of the previous occurrence, when the sync window
    # still holds that instance (it keeps ~200 rows, a few days)
    done_at = ""
    for c in cache_store.get("completed_tasks") or []:
        if c.get("repeatTaskId") == r["tid"] and c.get("completedTime"):
            day = rt.local_date(c["completedTime"])
            if day and (not prev or day >= prev):
                done_at = f" · ticked {day:%a %Y-%m-%d}"
                break

    rows = [alfred.item(
        uid="rc-head",
        title=f"Today is {today:%A} · {name} runs {st['rule'] or 'on no schedule'}",
        subtitle="Not due today · nothing has started",
        valid=False)]
    rows.append(alfred.item(
        uid="rc-go",
        title=f"▶️ Start the next one · {when(nxt)}",
        subtitle=f"Runs {name} now  |  ⏎▶️  ⌃🔙",
        arg=f"xact:routine_run:{key}",
        valid=True))
    rows.append(alfred.item(
        uid="rc-prev",
        title=(f"✅ Last one · {when(prev)}{done_at}" if prev
               else "✅ No earlier occurrence"),
        subtitle=f"Open {name} in TickTick  |  ⏎↗️  ⌃🔙",
        arg=f"open:ticktick:///webapp/#p/{t.get('projectId') or r['pid']}/tasks/{r['tid']}",
        valid=True,
        variables={"task_id": r["tid"], "task_list_id": t.get("projectId") or r["pid"],
                   "task_title": name, "item_type": "task"}))
    return add_back(rows, "ctx:routines")


def render_rtrack(ids, query):
    """📊 Routines tracker (⌘⇧ on any routine row): every routine's habit in
    ONE screen, not just the row you pressed - the point of a tracker is the
    comparison, and the row you came from rides on top so it is preselected.
    Same chords as the Habits hub, so the muscle memory carries: ⏎ ticks
    today, ⌥ opens that habit's screen (past days, un-tick, skip, diary),
    ⌃ goes back to Routines."""
    import routines as rt
    import habits_model as hm
    import dayroll
    today = dayroll.today()           # the routine's day rolls at 04:00
    ts = hm.stamp(today)
    want = [r for r in rt.ROUTINES if r.get("habit")]
    habits = {h["id"]: h for h in (cache_store.get("habits") or [])}
    checks = cache_store.get("habit_checkins") or {}
    if not query and any(r["habit"] not in habits for r in want):
        # A habit minted since the last hourly sync: ONE live read, so the
        # screen never says "not synced yet" about a habit we just made.
        # Guarded by `not query`: this filter re-runs per KEYSTROKE, and an
        # id that no longer resolves (deleted habit, registry typo) would
        # otherwise re-read on every character, forever. What it reads is
        # written back to the cache, so the next render needs no network.
        try:
            import api_v2
            v2 = api_v2.TickTickV2()          # ONE client, not two
            live = v2.get_habits()
            if live:
                habits = {h["id"]: h for h in live}
                cache_store.set("habits", live)
                # stamp() packs YYYYMMDD: subtract DAYS from the date, never
                # from the packed int (20260912 - 31 = 20260881, a stamp no
                # August day can be below - it silently dropped the month)
                fresh = v2.habit_checkins([r["habit"] for r in want],
                                          hm.stamp(today - timedelta(days=32)))
                if fresh:
                    checks = dict(checks, **fresh)
                    cache_store.set("habit_checkins", checks)
        except Exception:
            pass

    first = ids[0] if ids else ""
    want.sort(key=lambda r: (r["key"] != first, ))
    tasks = {t.get("id"): t for t in cache_store.get("all_tasks") or []}
    rows = []
    for r in want:
        h = habits.get(r["habit"])
        name = (tasks.get(r["tid"]) or {}).get("title") or r["label"]
        if h is None:
            rows.append(alfred.item(
                uid=f"rk-{r['key']}", title=f"⬜ {name}",
                subtitle="habit not readable · run a sync", valid=False))
            continue
        ck = checks.get(r["habit"])
        chip = hm.state_chip(h, hm.checkin_for(ck, ts))
        bits = [hm.dots(h, ck, today)]
        if h.get("currentStreak"):
            bits.append(f"🔥{h['currentStreak']}")
        bits.append(f"{h.get('totalCheckIns') or 0} total")
        rows.append(alfred.item(
            uid=f"rk-{r['key']}",
            title=f"{chip} {name}",
            subtitle=f"{' · '.join(bits)}  |  ⏎✅  ⌥📅  ⌃🔙",
            match=f"{name} {r['key']}",
            arg=f"xact:habit_tick:{r['habit']}",
            valid=True,
            # a habit row is not a task: clear the task vars the Routines row
            # exported on its way here, or ⌘ Actions would act on the routine
            # you pressed ⌘⇧ on, whatever row the cursor is now standing on
            variables={"task_id": "", "task_list_id": "", "task_title": "",
                       "item_type": ""},
            mods={
                "alt": {"arg": "", "subtitle": "📅 Days, un-tick, diary",
                        "variables": {"browse_ctx": f"ctx:habit:{r['habit']}",
                                      "task_id": "", "task_list_id": "",
                                      "task_title": "", "item_type": ""}},
            }))
    if query:
        rows = [x for x in rows if fuzz.score(query, x["title"]) > 0]
    return add_back(rows or [alfred.item(title="No routine matches", valid=False)],
                    "ctx:routines")


# ── Level: okr (🥅 OKRs hub, HANDOFF_OKR.md) ─────────────────────────────────
# "I see OKRs more like forecasting ... 'guiding star' rather than daily work
# plan" (Vex 2026-09-18). The plan is ONE list of all-day planning copies
# (src/okr.py reads it); these screens show it and hand every change to an
# xact:okr_* verb, which re-reads LIVE before it writes (the writer rule in
# okr.py's docstring). Nothing here writes TickTick, and a schedule preview
# computed here is display only - the verb re-plans from a writable read.
#
# Chords, ALL SIX spelled out on EVERY row (a missing mod fires the row's
# default arg down that chord's edge: ⌥ dumps it in the bar, ⇧ runs an
# xact:crmbrowse through dispatch, ⌘⇧ with a ctx: arg navigates):
#   Y / O row   ⏎⤵️ inside (xact:crmbrowse) · ⌥⤵️ the same hop, faster
#               (a variable hop skips End's Sync click) · ⌥⇧📅 schedule ·
#               ⌘⚡ Actions · ⌥⌘ copy link · ⇧ and ⌘⇧ dead
#   KR row      ⏎↗️ opens the COPY · ⇧✅ ticks it (⇧↩️ reopens a done or
#               won't-do one) · ⌥⤵️ the
#               REAL thing it links, in Alfred · ⌥⇧📅 · ⌘⚡ · ⌥⌘ copy link
#   any other   ⌘ pinned dead: a row that is not a task would otherwise
#               open ⌘ Actions on the LAST task acted on (actions.py
#               recovers /tmp/ticktick_reattribute.txt when vars are blank)
# ⌘⇧ stays dead on items until the Add layer stamps "🔑 KR • … - CODE":
# today it would open the Add bar under an O and mint an unprefixed child.
_OKR_CHORDS = ("cmd", "shift", "alt", "alt+shift", "alt+cmd", "cmd+shift")
_OKR_NO_TASK = {"task_id": "", "task_list_id": "", "list_id": "",
                "section_id": "", "task_title": "", "item_type": ""}
# A live okr.load() is ~1.6 s (v1 open + v2 completed, measured 2026-09-18),
# too slow for every hop between hub screens. The last live read is reused
# for this long, and only while nothing newer has touched the caches a write
# patches (project_data of the list, all_tasks, completed_tasks) - so a ⇧ tick
# or a verb's write is never shown stale, and a drag in the app is at most
# this old when the hub reopens.
_OKR_FRESH_S = 45
_OKR_GLYPH = {"Y": "🏔️", "O": "🥅", "KR": "🔑"}


def _okr_dead():
    return {"arg": "", "valid": False}


def _okr_dead_mods():
    """Every chord dead, FRESH dicts: add_back rewrites mods in place, so
    two rows sharing one dict would share their ⌃ too."""
    return {k: _okr_dead() for k in _OKR_CHORDS}


def _okr_nav_mods(ctx):
    """A non-task navigation row: ⌥ makes the same hop as its ⏎."""
    m = _okr_dead_mods()
    m["alt"] = {"arg": "", "valid": True, "subtitle": "⤵️",
                "variables": {"browse_ctx": ctx}}
    return m


def _okr_seal(rows):
    """The two row invariants, enforced once at the end of every OKR render
    rather than trusted to each builder: all six chords present (a missing
    one is dead), and a row that is not a task says so in its variables, so
    no task id from an earlier row rides along into whatever it opens."""
    for r in rows:
        mods = r.setdefault("mods", {})
        for k in _OKR_CHORDS:
            if k not in mods:
                mods[k] = _okr_dead()
        v = r.setdefault("variables", {})
        if not v.get("task_id"):
            for k, blank in _OKR_NO_TASK.items():
                v.setdefault(k, blank)
            mods["cmd"] = _okr_dead()
    return rows


def _okr_mtime(key):
    try:
        return os.path.getmtime(os.path.join(cache_store.CACHE_DIR, f"{key}.json"))
    except OSError:
        return None


def _okr_cached(pid):
    """The plan rebuilt from the local cache - source "cache", never
    writable. The last live read (okr_rows) when nothing newer has touched
    the list's project_data; else the synced OPEN rows plus every completed
    one still known (okr_rows' own, then the account-wide completed feed),
    because without the ticked KRs an O's total shrinks. None when the
    cache has no row of the list at all."""
    import okr
    c = cache_store.get("okr_rows")
    c = c if isinstance(c, dict) and c.get("list_id") == pid else None
    pd = cache_store.get(f"project_data_{pid}")
    pd = pd if isinstance(pd, dict) and isinstance(pd.get("tasks"), list) else None
    name = (c or {}).get("name") or ((pd or {}).get("project") or {}).get("name") or ""
    if c and (pd is None or (_okr_mtime("okr_rows") or 0)
              >= (_okr_mtime(f"project_data_{pid}") or 0)):
        rows = list(c.get("rows") or [])
    else:
        if pd is not None:
            open_rows = list(pd["tasks"])
        else:
            open_rows = [t for t in cache_store.get("all_tasks") or []
                         if isinstance(t, dict) and t.get("projectId") == pid]
            if not open_rows and not c:
                return None
        seen = {t.get("id") for t in open_rows}
        done = []
        # okr_rows is this list's by construction; the feed is account-wide
        feed = [t for t in cache_store.get("completed_tasks") or []
                if isinstance(t, dict) and t.get("projectId") == pid]
        for t in list((c or {}).get("rows") or []) + feed:
            if isinstance(t, dict) and t.get("status") in (2, -1) and t.get("id") not in seen:
                seen.add(t.get("id"))
                done.append(t)
        rows = open_rows + done
    return okr.Snapshot(okr.items_from(rows), "cache", "local cache", pid, name)


def _okr_fresh(pid):
    t = _okr_mtime("okr_rows")
    if t is None or time.time() - t > _OKR_FRESH_S:
        return False
    return all((_okr_mtime(k) or 0) <= t
               for k in (f"project_data_{pid}", "all_tasks", "completed_tasks"))


def _okr_snapshot(query, live=True):
    """(Snapshot | None, why, live?) for an OKR screen.

    The filter re-runs on EVERY keystroke, so the network is read only on an
    EMPTY bar (the render_rtrack rule) and only on the screens that show
    numbers (live=True): hub, Y/O, pace. A typed bar and the picker screens
    read the cache. What a live read returns is kept as okr_rows, the cache
    everything else reads - v1's project_data cache holds OPEN tasks only.
    `live?` is what the head row's "cache" chip reads: False = these numbers
    may be old."""
    import okr
    pid = cfg.get_okr_list_id()
    if not pid:
        return None, "off", False
    if query or not live:
        snap = _okr_cached(pid)
        return snap, ("" if snap else "not synced yet"), False
    if _okr_fresh(pid):
        c = cache_store.get("okr_rows") or {}
        if c.get("list_id") == pid:
            return (okr.Snapshot(okr.items_from(c.get("rows") or []), "cache",
                                 "live read, reused", pid, c.get("name") or ""),
                    "", True)
    try:
        snap = okr.load(list_id=pid)
    except okr.OkrLoadError as e:
        return None, str(e), False
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", False
    if snap.source == "live":
        try:
            cache_store.set("okr_rows", {"list_id": pid, "name": snap.name,
                                         "done_complete": snap.done_complete,
                                         "detail": snap.detail or "",
                                         "rows": [i.raw for i in snap.items]})
        except Exception:
            pass
        if snap.done_complete:
            _okr_remember_complete(snap)
    return snap, "", snap.source == "live"


def _okr_remember_complete(snap):
    """A live read with every completed KR is kept as okr_complete too
    (okr_write.remember_complete): the dedupe's memory of which closed
    items exist, for the reads that come back without them. Lazy and
    forgiving: no writer layer, nothing kept (the verb then refuses a
    linked add it cannot check, and the import screen says so first)."""
    try:
        import okr_write
        fn = getattr(okr_write, "remember_complete", None)
        if fn is not None:
            fn(snap)
    except Exception:
        pass


def _okr_problem(why, back="ctx:okr"):
    """The one row a screen shows when the plan cannot be read."""
    if why == "off":
        row = alfred.item(uid="okr-off", title="🥅 OKRs need a list",
                          subtitle="⚙️ Settings → OKR List  |  ⌃🔙", valid=False)
    else:
        row = alfred.item(uid="okr-err", title="🥅 OKR list unreadable",
                          subtitle=f"{why}  |  ⌃🔙", valid=False)
    return add_back(_okr_seal([row]), back)


def _okr_gone(back="ctx:okr"):
    return add_back(_okr_seal([alfred.item(
        uid="okr-gone", title="Not in the plan · sync or reopen",
        subtitle="Deleted, moved, or not synced yet  |  ⌃🔙", valid=False)]), back)


def _okr_home(it, by):
    """The screen that LISTS an item (its ⌃ target, and where a verb lands
    after writing): its Y/O's screen, else the hub root."""
    p = by.get(it.parent) if it.parent else None
    return (f"ctx:okr:{p.kind.lower()}:{p.id}"
            if p is not None and p.kind in ("Y", "O") else "ctx:okr")


def _okr_span(it, want):
    """The span a row SHOWS: an open Y/O on its wanted span (what its KRs
    say, and what the next heal writes - a stale stored one is exactly what
    the hub-open heal fixes), everything else as stored."""
    if it.kind in ("Y", "O") and not it.history and want.get(it.id):
        return want[it.id]
    return it.start, it.end


def _okr_real():
    """{id: task} + {parent id: open children} over the open caches, built
    once per render for the KR ⌥ hop (cache.find_task re-reads the whole
    all_tasks file per call)."""
    by, kids = {}, {}
    for key in ("all_tasks", "all_notes"):
        for t in cache_store.get(key) or []:
            if isinstance(t, dict) and t.get("id") and t["id"] not in by:
                by[t["id"]] = t
                if t.get("parentId") and t.get("status", 0) == 0:
                    kids[t["parentId"]] = kids.get(t["parentId"], 0) + 1
    return by, kids


def _okr_real_ctx(it, real):
    """Where ⌥ on a linked KR goes in Alfred: the linked task's subtasks
    when it has open ones, the linked list's tasks; else None (dead)."""
    tg = it.target
    if not tg or tg[0] not in ("task", "list"):
        return None
    if tg[0] == "list":
        return f"ctx:tasks:{tg[1]}"
    by, kids = real
    t = by.get(tg[2]) or {}
    if not kids.get(tg[2]):
        return None
    p = t.get("projectId") or t.get("_projectId") or tg[1]
    return f"ctx:subtasks:{p}:{tg[2]}"


def _okr_row(it, items, today, pid, want, real, head=False, where=None):
    """One Y / O / KR as a FULL task row (task_id, task_list_id, list_id,
    section_id, the RAW title, item_type), so ⌘ opens ⌘ Actions on it.
    head=True is the item a Y/O screen is about: ⏎ opens it, no drill.
    where = {id: item} on screens that mix parents (a flat search, a
    period's plan): the row then names its O / Y, or two "🔑 Eagle" KRs
    under two objectives read the same."""
    import okr
    link = f"ticktick:///webapp/#p/{pid}/tasks/{it.id}"
    s, e = _okr_span(it, want)
    bits = [okr.span_txt(s, e, today)]
    up = where.get(it.parent) if where is not None and it.parent else None
    if up is not None and up.kind in okr.PARENT_KINDS:
        nm = up.name if len(up.name) <= 24 else up.name[:23] + "…"
        bits.insert(0, f"{_OKR_GLYPH[up.kind]} {nm}")
    parent = it.kind in okr.PARENT_KINDS
    if parent:
        d, n = okr.progress(it, items)
        bits.append(f"{d}/{n} KRs")
        if not it.history:
            p = okr.pace(it, items, today)
            if p.behind_days:
                bits.append(f"behind {p.behind_days}d")
            if p.elapsed:                      # 0 = not started: no chip
                bits.append(f"⏳{round(p.elapsed * 100)}%")
    elif it.dated and not it.history and it.end < today:
        bits.append(f"late {(today - it.end).days}d")
    mods = _okr_dead_mods()
    mods["cmd"] = {"arg": "", "valid": True, "subtitle": "⌘ Actions"}
    mods["alt+cmd"] = {"arg": f"copy:{link}", "valid": True, "subtitle": "Copy link"}
    chips = []
    drill = None if head or not parent else f"ctx:okr:{it.kind.lower()}:{it.id}"
    if drill:
        arg = f"xact:crmbrowse:{drill}"
        chips.append("⏎⤵️")
        mods["alt"] = {"arg": "", "valid": True, "subtitle": "⤵️ Inside",
                       "variables": {"browse_ctx": drill}}
    else:
        arg = f"open:{link}"
        chips.append("⏎↗️")
    if not parent:
        # a done KR reopens through dispatch's uncomplete:; a WON'T DO one
        # through xact:wontdo_undo, which also drops it from the wontdo log
        # and restores it into all_tasks (dispatch only knows completed_tasks
        # and would invalidate the whole all_tasks cache - review 2026-09-18)
        if it.abandoned:
            sarg = f"xact:wontdo_undo:{pid}:{it.id}"
        else:
            verb = "uncomplete" if it.history else "complete"
            sarg = f"{verb}:{pid}:{it.id}:{it.name}"
        mods["shift"] = {"arg": sarg, "valid": True,
                         "subtitle": "↩️ Reopen" if it.history else "✅ Done"}
        chips.append("⇧↩️" if it.history else "⇧✅")
    if not parent:
        ctx = _okr_real_ctx(it, real)
        if ctx:
            mods["alt"] = {"arg": "", "valid": True, "subtitle": "⤵️ The real one",
                           "variables": {"browse_ctx": ctx}}
            chips.append("⌥⤵️")
    if not it.history:
        # actions_loop blanked: this road is the hub's, not ⌘ Actions' act-again
        mods["alt+shift"] = {"arg": f"xact:crmbrowse:ctx:okrsched:{it.id}",
                             "valid": True, "subtitle": "📅 Schedule",
                             "variables": {"actions_loop": ""}}
        chips.append("⌥⇧📅")
    chips += ["⌘⚡", "⌃🔙"]
    glyph = _OKR_GLYPH.get(it.kind, "▫️")
    state = "✅ " if it.done else ("🚫 " if it.abandoned else "")
    return alfred.item(
        uid=f"okr-{it.id}{'-h' if head else ''}",
        title=f"{state}{glyph} {it.name}{' 🔗' if it.link else ''}",
        subtitle=" · ".join(bits) + "  |  " + "  ".join(chips),
        arg=arg, valid=True, match=f"{it.name} {it.code or ''} {it.kind or ''}",
        variables={"task_id": it.id, "task_list_id": pid, "list_id": pid,
                   "section_id": "", "task_title": it.title,
                   "item_type": "note" if (it.raw or {}).get("kind") == "NOTE" else "task"},
        mods=mods)


def _okr_open_first(xs):
    """Open first, closed after - each half in plan order (dated by start,
    then undated)."""
    from datetime import date as _date
    return sorted(xs, key=lambda x: (x.history, not x.dated,
                                     x.start or _date.max, x.name))


def _okr_heal_nudge():
    """Hub open = a heal pass (HANDOFF_OKR section 4), fired DETACHED: the
    verb loads live, refuses unless the read is writable, and spawn_heal
    debounces it. Lazy and silent: the screens must work before the writer
    layer exists."""
    try:
        import okr_write
        okr_write.spawn_heal()
    except Exception:
        pass


def render_okr(ids, query):
    """ctx:okr - the hub: head row (list, counts, "cache" chip when the
    numbers are not from a live read), 📈 Pace, then the plan's roots - Y's,
    O's without a Y, KRs without an O, unprefixed items - open first. A typed
    bar searches EVERY item, flat.
    ctx:okr:y:<id> / ctx:okr:o:<id> - that item (head row) + its children.

    A typed bar also ADDS (phase 3, "I should be able to import text only
    as well"): ➕ rows APPENDED after the search results (_okr_plus_rows),
    so a search still hits its match first and a name nothing matches is
    the first ⏎."""
    import okr
    from datetime import date as _date
    snap, why, live = _okr_snapshot(query)
    if snap is None:
        return _okr_problem(why, "ctx:folders" if not ids else "ctx:okr")
    items, pid, today = snap.items, snap.list_id, _date.today()
    by = okr.index(items)
    want = okr.wanted_spans(items)
    real = _okr_real()
    # the search reads the bar WITHOUT a "=XY" code word (that one is for
    # the ➕ rows); a bar that is only a code searches nothing
    stext = _okr_typed(query)[2] if query else ""

    def row(it, head=False):
        return _okr_row(it, items, today, pid, want, real, head=head)

    def search(rows):
        if not stext:
            return []
        return fuzz.filter_and_score(stext, rows,
                                     key_fn=lambda x: x.get("match") or x["title"])

    if len(ids) >= 2 and ids[0] in ("y", "o"):
        it = by.get(ids[1])
        if it is None:
            return _okr_gone()
        rows = [row(c) for c in _okr_open_first(c for c in items if c.parent == it.id)]
        if query:
            rows = (search(rows) + _okr_plus_rows(it, query, items)) or [alfred.item(
                uid="okr-none", title=f'Nothing matching "{query}"',
                subtitle="⌃🔙", valid=False)]
        else:
            if not rows:
                rows = [alfred.item(
                    uid="okr-empty", valid=False,
                    title="No KRs yet" if it.kind == "O" else "No objectives yet",
                    subtitle=("Closed  |  ⌃🔙" if it.history else
                              "Type a name to add · | for more  |  ⌃🔙"))]
            rows = [row(it, head=True)] + rows
        return add_back(_okr_seal(rows), _okr_home(it, by))

    pace_row = alfred.item(
        uid="okr-pace", title="📈 Pace",
        subtitle="Quarter · month · week · day · capacity  |  ⏎⤵️  ⌃🔙",
        arg="xact:crmbrowse:ctx:okrpace", valid=True, match="pace capacity",
        variables=dict(_OKR_NO_TASK), mods=_okr_nav_mods("ctx:okrpace"))
    # ↪️ only while the closing quarter leaves something open
    cq = okr.closing_quarter(today)
    left = okr.carry_candidates(items, cq.end)
    extra = [pace_row]
    if left:
        extra.append(alfred.item(
            uid="okr-carry", title=f"↪️ Carry-over · {_okr_q(cq)} · {len(left)} open",
            subtitle="Carry · won't do · someday  |  ⏎⤵️  ⌃🔙",
            arg="xact:crmbrowse:ctx:okrcarry", valid=True,
            match="carry over quarter leftovers",
            variables=dict(_OKR_NO_TASK), mods=_okr_nav_mods("ctx:okrcarry")))
    if query:
        rows = search([_okr_row(x, items, today, pid, want, real, where=by)
                       for x in _okr_open_first(items)] + extra)
        rows = (rows + _okr_plus_rows(None, query, items)) or [alfred.item(
            uid="okr-none", title=f'No OKR matching "{query}"',
            subtitle="⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), "ctx:folders")

    t = okr.tree(items)
    roots = [n[0] for key in ("years", "orphan_os", "orphan_krs", "loose")
             for n in t[key]]
    roots = [x for x in roots if not x.history] + [x for x in roots if x.history]
    count = {k: sum(1 for x in items if x.kind == k and not x.history) for k in okr.KINDS}
    n_done = sum(1 for x in items if x.history)
    head = alfred.item(
        uid="okr-head",
        title=f"{snap.name or '🥅 OKRs'} · {sum(count.values())} open",
        subtitle=(f"{count['Y']} Y · {count['O']} O · {count['KR']} KR"
                  + (f" · {n_done} done" if n_done else "")
                  + ("" if live else " · cache") + "  |  ⏎↗️  ⌃🔙"),
        arg=f"open:ticktick:///webapp/#p/{pid}/tasks", valid=True,
        variables=dict(_OKR_NO_TASK))
    rows = [head] + extra + [row(x) for x in roots]
    if not roots:
        rows.append(alfred.item(uid="okr-empty", title="The plan is empty",
                                subtitle="⌃🔙", valid=False))
    _okr_heal_nudge()
    return add_back(_okr_seal(rows), "ctx:folders")


# tier, emoji, word, the kinds its plan lists (HANDOFF_OKR section 4:
# 🌓 Quarter = O's · 🗓️ Month = O's + KRs · ♻️ Week and ☀️ Day = KRs)
_OKR_TIERS = (("quarterly", "🌓", "Quarter", ("O",)),
              ("monthly", "🗓️", "Month", ("O", "KR")),
              ("weekly", "♻️", "Week", ("KR",)),
              ("daily", "☀️", "Day", ("KR",)))


def _okr_pace_bits(pp):
    bits = [f"{pp.done}/{pp.total} KRs"]
    if pp.expected:
        bits.append(f"{pp.expected} due")
    if pp.behind_days:
        bits.append(f"behind {pp.behind_days}d")
    return bits


def render_okrpace(ids, query):
    """ctx:okrpace - the four periods now running, each with its KR pace
    (okr.period_pace: ticked / planned, how many should be done by now, how
    far behind); ⏎ and ⌥ open one. ctx:okrpace:<tier> - that period's plan
    (okr.overlapping, the tier's kinds), item rows with their pace."""
    import okr
    import periodic_model as pm
    from datetime import date as _date
    snap, why, _live = _okr_snapshot(query)
    if snap is None:
        return _okr_problem(why)
    items, pid, today = snap.items, snap.list_id, _date.today()
    tier = next((x for x in _OKR_TIERS if ids and x[0] == ids[0]), None)
    if ids and tier is None:
        return add_back(_okr_seal([alfred.item(
            uid="okrp-bad", title=f"Unknown period “{ids[0]}”",
            subtitle="quarterly · monthly · weekly · daily  |  ⌃🔙",
            valid=False)]), "ctx:okrpace")
    if tier is None:
        rows = []
        for kind, emo, word, _kinds in _OKR_TIERS:
            p = pm.period_for(kind, today)
            pp = okr.period_pace(items, p.start, p.end, today)
            rows.append(alfred.item(
                uid=f"okrp-{kind}", title=f"{emo} {word} · {pm.title(p)}",
                subtitle=" · ".join([okr.span_txt(p.start, p.end, today)]
                                    + _okr_pace_bits(pp)) + "  |  ⏎⤵️  ⌃🔙",
                arg=f"xact:crmbrowse:ctx:okrpace:{kind}", valid=True,
                match=f"{word} {kind} {pm.title(p)}",
                variables=dict(_OKR_NO_TASK),
                mods=_okr_nav_mods(f"ctx:okrpace:{kind}")))
        rows.append(_okr_capacity_row(items, today))
        if query:
            rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["match"]) \
                or [alfred.item(uid="okrp-none", title=f'No period matching "{query}"',
                                subtitle="⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), "ctx:okr")
    kind, emo, word, kinds = tier
    p = pm.period_for(kind, today)
    pp = okr.period_pace(items, p.start, p.end, today)
    want = okr.wanted_spans(items)
    real = _okr_real()
    by = okr.index(items)
    rows = [_okr_row(x, items, today, pid, want, real, where=by)
            for x in okr.overlapping(items, p.start, p.end, kinds)]
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["match"]) \
            or [alfred.item(uid="okrp-none", title=f'Nothing matching "{query}"',
                            subtitle="⌃🔙", valid=False)]
    else:
        if not rows:
            rows = [alfred.item(uid="okrp-empty", title=f"Nothing planned this {word.lower()}",
                                subtitle="⌃🔙", valid=False)]
        rows.insert(0, alfred.item(
            uid=f"okrp-head-{kind}", title=f"{emo} {word} · {pm.title(p)}",
            subtitle=" · ".join([okr.span_txt(p.start, p.end, today)]
                                + _okr_pace_bits(pp)) + "  |  ⌃🔙",
            valid=False))
        if kind == "weekly":
            # the weekly review opens this screen: the check sits where the
            # next week gets planned
            rows.append(_okr_capacity_row(items, today))
    return add_back(_okr_seal(rows), "ctx:okrpace")


def _okr_capacity_row(items, today):
    """⚖️ the capacity check (okr.capacity, HANDOFF_OKR phase 5: "KRs per
    week, not focus"): the KRs the plan puts due in the next four weeks
    against the KRs ticked in the last four, per week. ⚠️ when at least two
    are due and the plan asks for more than half again what gets finished
    (one KR due against none ticked is no overload). Display only."""
    import okr
    c = okr.capacity(items, today)
    over = c.planned >= 2 and c.planned > 1.5 * c.done
    return alfred.item(
        uid="okrp-capacity",
        title=(f"⚖️ Capacity · plan {okr.rate_txt(c.planned, c.weeks)} · "
               f"done {okr.rate_txt(c.done, c.weeks)}" + (" · ⚠️ over" if over else "")),
        subtitle=(f"Next {c.weeks} wks: {c.planned} KRs due · last {c.weeks} wks: "
                  f"{c.done} ticked  |  ⌃🔙"),
        valid=False, match="capacity load rate")


def _okr_q(q):
    """ "Q3" - the quarter's short name (okr_notes.tier_label without its
    emoji)."""
    return f"Q{(q.start.month - 1) // 3 + 1}"


def render_okrcarry(ids, query):
    """ctx:okrcarry[:<quarter start>] - the quarter carry-over (HANDOFF_OKR
    phase 5: "Every open KR gets one decision: carry into next quarter /
    won't do / someday. Nothing leaks silently from one quarter into the
    next"): okr.carry_candidates for okr.closing_quarter - the quarter now
    ending in its last two weeks, else the one just gone - each a full hub
    row (⇧✅ ⌥⇧📅 ⌘⚡ as everywhere) whose ⏎ opens its three choices.
    ctx:okrcarry:<quarter start>:<id> - those three, each an xact:okr_carry
    that lands back on the list, pinned to the same quarter, so the next
    leftover is on top. A carry ripples like any schedule action: the rest
    of the lane moves along, often out of the quarter with it."""
    import okr
    import periodic_model as pm
    from datetime import date as _date
    from periodic_rows import _b64
    pinned = None
    if ids:
        try:
            pinned = _date.fromisoformat(ids[0])
        except ValueError:
            pinned = None
    today = _date.today()
    q = okr.closing_quarter(today, pinned)
    nq = pm.next_period(q)
    qkey = q.start.isoformat()
    home = f"ctx:okrcarry:{qkey}"
    if len(ids) >= 2:
        snap, it, by, problem = _okr_item_for(ids[1:])
        if problem:
            return add_back(problem, home)
        items = snap.items
        want = okr.wanted_spans(items)
        s, e = _okr_span(it, want)
        up = by.get(it.parent) if it.parent else None
        head = alfred.item(
            uid="okrc-head",
            title=f"{_OKR_GLYPH.get(it.kind, '▫️')} {it.name} · {okr.span_txt(s, e, today)}",
            subtitle=((f"{_OKR_GLYPH[up.kind]} {up.name} · " if up is not None
                       and up.kind in okr.PARENT_KINDS else "")
                      + f"left open in {_okr_q(q)}  |  ⌃🔙"),
            valid=False)
        if it.history:
            return add_back(_okr_seal([head, alfred.item(
                uid="okrc-closed", title="Closed already · nothing to decide",
                subtitle="⌃🔙", valid=False)]), home)
        start = okr.carry_start(q.end, today)

        def pay(action, arg=None):
            return _b64({"id": it.id, "action": action, "arg": arg, "back": home})

        try:
            moves, heals = okr.schedule_plan(items, it.id, "date", start, today)
            new = {i: (a, b) for i, a, b in list(moves) + list(heals)}
            ns, ne = new.get(it.id, (s, e))
            n = len({m[0] for m in moves} - {it.id})
            carry = alfred.item(
                uid="okrc-carry", title=f"↪️ Carry into {_okr_q(nq)}",
                subtitle=(f"{okr.span_txt(ns, ne, today)}"
                          + (f" · moves {n} along" if n else "") + "  |  ⏎↪️  ⌃🔙"),
                arg=f"xact:okr_carry:{pay('carry', start.isoformat())}",
                valid=True, match="carry next quarter")
        except ValueError as ex:
            carry = alfred.item(uid="okrc-carry", title=f"↪️ Carry into {_okr_q(nq)}",
                                subtitle=f"{ex}  |  ⌃🔙", valid=False,
                                match="carry next quarter")
        # the verb refuses a won't do with open work under it (it would
        # strand it): never offer that ⏎
        kids = okr._kids(items)
        below = [x for x in okr._descendants(it.id, kids) if x in by and not by[x].history]
        wontdo = (alfred.item(uid="okrc-wontdo", title="🚫 Won't do",
                              subtitle=(f"{len(below)} open under it · decide those first"
                                        "  |  ⌃🔙"),
                              valid=False, match="wont do drop abandon")
                  if below else
                  alfred.item(uid="okrc-wontdo", title="🚫 Won't do",
                              subtitle="Out of progress and pace  |  ⏎🚫  ⌃🔙",
                              arg=f"xact:okr_carry:{pay('wontdo')}", valid=True,
                              match="wont do drop abandon"))
        rows = [head, carry, wontdo,
                alfred.item(uid="okrc-someday", title="💤 Someday",
                            subtitle="Off the timeline · stays in the plan  |  ⏎💤  ⌃🔙",
                            arg=f"xact:okr_carry:{pay('someday')}", valid=True,
                            match="someday later undate park")]
        if query:
            rows = fuzz.filter_and_score(query, rows[1:], key_fn=lambda x: x["match"]) \
                or [alfred.item(uid="okrc-none", title=f'Nothing matching "{query}"',
                                subtitle="⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), home)
    snap, why, _live = _okr_snapshot(query)
    if snap is None:
        return _okr_problem(why)
    items, pid = snap.items, snap.list_id
    by = okr.index(items)
    want = okr.wanted_spans(items)
    real = _okr_real()
    left = okr.carry_candidates(items, q.end)
    rows = []
    for it in left:
        r = _okr_row(it, items, today, pid, want, real, where=by)
        r["arg"] = f"xact:crmbrowse:{home}:{it.id}"
        r["subtitle"] = (r["subtitle"].replace("⏎↗️", "⏎↪️", 1)
                         .replace("⏎⤵️", "⏎↪️", 1))
        rows.append(r)
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x.get("match") or x["title"]) \
            or [alfred.item(uid="okrc-none", title=f'Nothing matching "{query}"',
                            subtitle="⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), "ctx:okr")
    head = alfred.item(
        uid="okrc-list-head",
        title=f"↪️ Carry-over · {_okr_q(q)} · {len(left)} open",
        subtitle=(f"{_okr_q(q)} ends {okr.span_txt(q.end, q.end, today)} · "
                  f"carry into {_okr_q(nq)} · won't do · someday  |  ⌃🔙"),
        valid=False)
    if not left:
        rows = [alfred.item(uid="okrc-clean", title=f"Nothing left open · {_okr_q(q)} is clean",
                            subtitle="⌃🔙", valid=False)]
    return add_back(_okr_seal([head] + rows), "ctx:okr")


def _okr_item_for(ids):
    """(snap, item, by, problem rows) for the screens about ONE item. They
    read the CACHE: each is a picker reached from a hub row or ⌘ Actions a
    moment after a live read, and it re-renders per keystroke."""
    import okr
    snap, why, _live = _okr_snapshot("", live=False)
    if snap is None:
        return None, None, {}, _okr_problem(why)
    by = okr.index(snap.items)
    it = by.get(ids[0]) if ids else None
    if it is None:
        return snap, None, by, _okr_gone()
    return snap, it, by, None


# "+3" · "+3d" · "- 2 days" · "+1w" · "+2 Weeks": a length, never a date
# okr_write.MAX_EXTEND: a length the verb refuses is never offered as a ⏎
_OKR_MAX_EXTEND = 3660
_OKR_EXTEND_RE = re.compile(r"([+-])\s*(\d{1,3})\s*(d|days?|w|weeks?)?", re.I)


def render_okrsched(ids, query):
    """ctx:okrsched:<id> - the ONE schedule screen (⌥⇧ on a hub row, 📅
    Schedule… in ⌘ Actions): ⏩ +1 / +3 / +7 days, 🌙 Tomorrow, or typed:
    a bar led by + or - is ALWAYS a length ("+N", "+Nd", "+N days", "+Nw",
    "+N weeks"; a bare number is a DAY of the month to dateutil, so
    extending needs its sign) and never reaches dateutil; anything else is
    a date, today or later. No time entry ("we can remove add time",
    HANDOFF_OKR section 4): parsedatetime's own status refuses one, since
    "2am" at UTC+2 is UTC midnight and reads as a date by its ISO alone.
    Each row previews "<new span> · moves N" from okr.schedule_plan over
    the cache; a refusal (closed item, undated extend, a parent that
    cannot land) is the row's subtitle and the row is dead. Rows fire
    xact:okr_sched:<b64>."""
    import okr
    import dateutil
    import periodic_model as pm
    from datetime import date as _date
    from periodic_rows import _b64
    snap, it, by, problem = _okr_item_for(ids)
    if problem:
        return problem
    items, today = snap.items, _date.today()
    home = _okr_home(it, by)
    want = okr.wanted_spans(items)
    cur = _okr_span(it, want)
    head = alfred.item(uid="okrs-head",
                       title=f"📅 {it.name} · {okr.span_txt(cur[0], cur[1], today)}",
                       subtitle="Type +N · -N · a date  |  ⌃🔙", valid=False)
    if it.history:
        return add_back(_okr_seal([head, alfred.item(
            uid="okrs-closed", title="Closed · never moves",
            subtitle="Reopen it first  |  ⌃🔙", valid=False)]), home)

    def plan(uid, title, action, arg, match):
        pay = {"id": it.id, "action": action,
               "arg": arg.isoformat() if isinstance(arg, _date) else arg,
               "back": home}
        if action == "extend" and abs(arg) > _OKR_MAX_EXTEND:
            return alfred.item(uid=uid, title=title,
                               subtitle="Too long · pick a date  |  ⌃🔙",
                               valid=False, match=match)
        try:
            moves, heals = okr.schedule_plan(items, it.id, action, arg, today)
        except ValueError as e:
            # "bad span 2026-09-18..2026-09-16" = pulled in past its start:
            # said in words, never as raw ISO dates
            why = ("Longer than the item · pick a date"
                   if str(e).startswith("bad span") else str(e))
            return alfred.item(uid=uid, title=title, subtitle=f"{why}  |  ⌃🔙",
                               valid=False, match=match)
        new = {i: (s, e) for i, s, e in moves}
        new.update({i: (s, e) for i, s, e in heals})
        s, e = new.get(it.id, cur)
        if action == "extend" and e is not None and e < today:
            # the verb refuses it too (okr_write.schedule): never offer a ⏎
            # that can only answer "no"
            return alfred.item(uid=uid, title=title,
                               subtitle="That end is gone · today or later  |  ⌃🔙",
                               valid=False, match=match)
        n = len({m[0] for m in moves} - {it.id})
        return alfred.item(uid=uid, title=title,
                           subtitle=f"{okr.span_txt(s, e, today)} · moves {n}  |  ⏎📅  ⌃🔙",
                           arg=f"xact:okr_sched:{_b64(pay)}", valid=True, match=match)

    fixed = [plan(f"okrs-x{n}", f"⏩ +{n} day{'s' if n > 1 else ''}", "extend", n,
                  f"+{n} extend longer")
             for n in (1, 3, 7)]
    fixed.append(plan("okrs-tmrw", "🌙 Tomorrow", "tomorrow", None,
                      "tomorrow move next day"))
    q = query.strip()
    if q[:1] in ("\u2212", "\u2013", "\u2014"):
        # text substitution turns a typed "-" into these; read as a date,
        # "-3 days" would become a FORWARD move (review 2026-09-18)
        q = "-" + q[1:]
    if not q:
        return add_back(_okr_seal([head] + fixed + [alfred.item(
            uid="okrs-date", title="📆 Pick a date · type it",
            subtitle="12.10 · next mon · 12 oct  |  ⌃🔙", valid=False)]), home)
    # ONE answer per bar: what was typed wins; a word that is no date
    # ("tom") falls back to the fixed rows it names before saying so
    if q[0] in "+-":
        # a sign = a length, ALWAYS: "-2" must never reach dateutil
        m = _OKR_EXTEND_RE.fullmatch(q)
        if not m:
            return add_back(_okr_seal([alfred.item(
                uid="okrs-typed", title="+N longer · -N shorter",
                subtitle="+3 · +3d · +2w · -1d  |  ⌃🔙", valid=False)]), home)
        k = int(m.group(2))
        weeks = (m.group(3) or "d")[:1].lower() == "w"
        n = k * (7 if weeks else 1) * (-1 if m.group(1) == "-" else 1)
        word = f"{k} {'week' if weeks else 'day'}{'s' if k > 1 else ''}"
        rows = [plan("okrs-typed",
                     f"⏩ Extend +{word}" if n > 0 else f"⏪ Pull in {word}",
                     "extend", n, q) if n else
                alfred.item(uid="okrs-typed", title="Nothing to move",
                            subtitle="+N longer · -N shorter  |  ⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), home)
    iso, status = dateutil.parse_date_status(q)
    d = _date.fromisoformat(iso[:10]) if iso else None
    if iso and status != 1:
        rows = [alfred.item(uid="okrs-typed", title="Dates only · no time",
                            subtitle="OKR items are all-day  |  ⌃🔙", valid=False)]
    elif d is not None and d < today:
        rows = [alfred.item(uid="okrs-typed", title="That day is gone · today or later",
                            subtitle=f"{pm.DAY_ABBR[d.weekday()]} · "
                                     f"{okr.span_txt(d, d, today)}  |  ⌃🔙",
                            valid=False)]
    elif d is not None:
        rows = [plan("okrs-typed",
                     f"📆 {pm.DAY_ABBR[d.weekday()]} · {okr.span_txt(d, d, today)}",
                     "date", d, q)]
    else:
        rows = (fuzz.filter_and_score(q, fixed, key_fn=lambda x: x.get("match") or x["title"])
                or [alfred.item(uid="okrs-typed", title=f'No date in "{q}"',
                                subtitle="12.10 · next mon · 12 oct · +N  |  ⌃🔙",
                                valid=False)])
    return add_back(_okr_seal(rows), home)


_OKR_CODE_TOKEN = re.compile(r"(?:^|(?<=\s))=(\w{1,16})(?=\s|$)")


def _okr_typed(query):
    """(names, override, text) of an add bar, the ONE grammar every OKR add
    reads (🔑 Add KRs, the hub's ➕ rows, the import screen's code): "=XY"
    is a word of its own ANYWHERE and the last one wins; the rest splits on
    pipes like the add bar's subtasks (subtask_line), empty segments
    dropped. `text` is the bar without the code, for search and ➕ Another."""
    import subtask_line
    found = _OKR_CODE_TOKEN.findall(query or "")
    text = " ".join(_OKR_CODE_TOKEN.sub(" ", query or "").split())
    head, kids = subtask_line.split_line(text)
    return [x for x in [head] + kids if x], (found[-1] if found else None), text


def _okr_code_bad(code):
    """True when a typed "=XY" would not read back off a title
    (okr_write.code_ok): the row carrying it goes dead with the rule as its
    subtitle, so no ⏎ is offered that can only answer "no". Lazy and
    forgiving: no writer layer, no check (the verb decides)."""
    if not code:
        return False
    try:
        import okr_write
        return not okr_write.code_ok(code)
    except Exception:
        return False


def _okr_propose(name):
    """The code a new objective gets when none is typed, as the verb picks
    it: okr.propose_code, kept only when okr_write.code_ok says a title
    reads it back. add_items drops any other ("学习 计划" proposes 学计,
    which no title reads as a code), so a preview showing it would promise
    a code the verb never writes. None = no code. The ONE proposal every
    code preview uses (➕ rows, 🔑 Add KRs, the import screen). Lazy and
    forgiving: no writer layer, the plain proposal (the verb decides)."""
    import okr
    code = okr.propose_code(name) or None
    if code is None:
        return None
    try:
        import okr_write
        return code if okr_write.code_ok(code) else None
    except Exception:
        return code


def _okr_unreadable(kind, names, code=None):
    """Why the new titles would not read back, else None - the dead row's
    subtitle. okr_write._title_for answers None for a name the verb then
    SKIPS ("Trip - USA" as a Y, an O or a code-less KR reads USA as its
    code and cuts the name short), so the row goes dead naming it - never
    a ⏎ that quietly drops a name. `code` = the code the verb stamps on a
    KR (a Y / O title carries none); tested on its own first, because when
    IT fails, the code is what to fix, not the names. Lazy and forgiving:
    no writer layer, no check (the verb decides)."""
    try:
        import okr_write
        fn = okr_write._title_for
    except Exception:
        return None
    code = code if kind == "KR" else None
    try:
        if code and fn("KR", "x", None, code) is None:
            return "Code: one word, capital first"
        for n in names:
            if fn(kind, n, None, code) is None:
                return f"'{_okr_shown([n], 40)}' reads as a code · reword"
    except Exception:
        return None
    return None


def _okr_more(text, override):
    """The bar after "one more": " | " at the END of the names, "=XY" moved
    to the FRONT - Alfred leaves the cursor at the end, and a name typed
    right after "=XY" would glue onto the code. Never subtask_line's
    next_query: it cuts at the add bar's first attribute token, and an OKR
    bar has none - "Fish & Chips" came back "Fish | & Chips" and "Read 20
    books / year" handed "/ year" to the next name."""
    head = " ".join((text or "").split())
    while head.endswith("|"):
        head = head[:-1].rstrip()
    return (f"={override} " if override else "") + (f"{head} | " if head else "")


def render_okraddkr(ids, query):
    """ctx:okraddkr:<oid> - KRs under an O from ONE line, the add bar's pipe
    grammar (subtask_line): "Draft | Review | Ship" = three KRs, "=XY" as a
    word of its own sets the code. Row 1 commits (⏎ = xact:okr_addkr with the NAMES
    - the verb stamps "🔑 KR • <name> - <code>" from a live read), row 2
    "➕ Another KR" puts one more pipe in the bar. The code shown is the one
    the verb will use: the O's 🏷️ line / title code / KR majority
    (okr.code_of), else a proposal (_okr_propose) the verb writes into
    the O's description. A closed O takes no new KRs."""
    import okr
    from periodic_rows import _b64
    snap, o, by, problem = _okr_item_for(ids)
    if problem:
        return problem
    if o.kind != "O":
        return add_back(_okr_seal([alfred.item(
            uid="okra-no", title="KRs go under an objective",
            subtitle=f"{_OKR_GLYPH.get(o.kind, '▫️')} {o.name} is not an O  |  ⌃🔙",
            valid=False)]), _okr_home(o, by))
    back = f"ctx:okr:o:{o.id}"
    if o.history:
        return add_back(_okr_seal([alfred.item(
            uid="okra-closed", title=f"🥅 {o.name} is closed",
            subtitle="Reopen it first  |  ⌃🔙", valid=False)]), back)
    # "=XY" is read as a standalone word ANYWHERE (the last one wins), not
    # only at the end: ➕ Another KR moves it to the FRONT of the bar
    # (_okr_more)
    names, override, text = _okr_typed(query)
    have = okr.code_of(o, okr.krs_of(o, snap.items))
    code = override or have or _okr_propose(o.name)
    code_txt = f"code {code}" if code else "no code"
    if code and not have:
        code_txt += " · new 🏷️"
    if not names:
        return add_back(_okr_seal([alfred.item(
            uid="okra-prompt", title=f"🔑 KRs under 🥅 {o.name} · {code_txt}",
            subtitle="Type a name · | for more · =XY sets code  |  ⌃🔙",
            valid=False)]), back)
    n = len(names)
    pay = {"oid": o.id, "names": names, "code": override, "back": back}
    preview = " · ".join(names)
    # an =XY the title would not read back ("=xy") is refused by the verb,
    # and a name that would read as a code is skipped: the row says so first
    bad = "Code: one word, capital first" if _okr_code_bad(override) else None
    bad = bad or _okr_unreadable("KR", names, code)
    rows = [alfred.item(
        uid="okra-go", title=f"✅ Add {n} KR{'s' if n > 1 else ''} under 🥅 {o.name} · {code_txt}",
        subtitle=(f"{bad}  |  ⌃🔙" if bad else
                  (preview[:90] + ("…" if len(preview) > 90 else "")) + "  |  ⏎✅  ⌃🔙"),
        arg="" if bad else f"xact:okr_addkr:{_b64(pay)}", valid=not bad),
        alfred.item(uid="okra-more", title="➕ Another KR",
                    subtitle="One more | in the bar  |  ⌃🔙", arg="", valid=False,
                    autocomplete=_okr_more(text, override))]
    return add_back(_okr_seal(rows), back)


def render_okrlink(ids, query):
    """ctx:okrlink:<id> - what an OKR item plans: an open task, subtask or
    note anywhere but the OKR list and the periodic list, or a list. ⏎ fires
    xact:okr_link, which rewrites only the COPY's title ("moving a copy
    NEVER moves the real task"). An O or Y usually plans a list, so lists
    lead there; a KR plans a task, so tasks lead."""
    import okr
    from display import pick_title, pick_where, search_key
    from periodic_rows import _b64
    snap, it, by, problem = _okr_item_for(ids)
    if problem:
        return problem
    home = _okr_home(it, by)
    skip = {x for x in (snap.list_id, _areas.PERIODIC_LIST_ID) if x}
    tasks, seen = [], set()
    for key in ("all_tasks", "all_notes"):
        for t in cache_store.get(key) or []:
            if (not isinstance(t, dict) or not t.get("id") or t["id"] in seen
                    or t["id"] == it.id or t.get("status", 0) != 0
                    or (t.get("projectId") or t.get("_projectId")) in skip):
                continue
            seen.add(t["id"])
            tasks.append(t)
    tasks.sort(key=lambda t: t.get("modifiedTime") or t.get("createdTime") or "",
               reverse=True)
    lists = [p for p in (cache_store.get("projects") or [])
             if isinstance(p, dict) and p.get("id") and p.get("kind") != "SMART_LIST"
             and not p.get("closed") and p["id"] not in skip]
    lists.sort(key=lambda p: p.get("sortOrder") or 0)
    tmap = {t["id"]: t for t in tasks}
    q = query.strip()

    def pay(to, lpid, tid):
        return f"xact:okr_link:{_b64({'id': it.id, 'to': to, 'pid': lpid, 'tid': tid, 'back': home})}"

    def task_row(t):
        tpid = t.get("projectId") or t.get("_projectId") or ""
        mods = _picker_mods()
        return alfred.item(
            uid=f"okrl-{t['id']}", title=pick_title(t, task_map=tmap),
            subtitle=f"{pick_where(t, tmap)}  |  ⏎🔗  ⌘⚡  ⌃🔙",
            arg=pay("task", tpid, t["id"]), valid=True,
            variables={"task_id": t["id"], "task_list_id": tpid, "list_id": tpid,
                       "section_id": "", "task_title": t.get("title", ""),
                       "item_type": "note" if t.get("kind") == "NOTE" else "task"},
            mods=mods)

    def list_row(p):
        return alfred.item(uid=f"okrl-list-{p['id']}", title=f"📂 {p.get('name', '')}",
                           subtitle="List  |  ⏎🔗  ⌃🔙",
                           arg=pay("list", p["id"], None), valid=True)

    if q:
        # the kind this item usually plans wins a near tie ("tickal" on an O
        # should put the list above the list's own bridge notes)
        lead = 0 if it.kind in ("Y", "O") else 1
        scored = [(fuzz.score(q, search_key(t.get("title", "")) + " "
                              + (t.get("_projectName") or "")), 1, t) for t in tasks]
        scored += [(fuzz.score(q, p.get("name", "")), 0, p) for p in lists]
        scored = sorted((x for x in scored if x[0] > 0),
                        key=lambda x: -(x[0] + (25 if x[1] == lead else 0)))[:60]
        rows = [task_row(x) if kind else list_row(x) for _s, kind, x in scored]
        rows = rows or [alfred.item(uid="okrl-none", title=f'Nothing matching "{q}"',
                                    subtitle="⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), home)
    tg = it.target
    now = {"task": "a task", "list": "a list", "url": "a web link"}.get(tg[0] if tg else "", "text only")
    head = alfred.item(uid="okrl-head", title=f"🔗 {_OKR_GLYPH.get(it.kind, '▫️')} {it.name}",
                       subtitle=f"Links {now} · type to find  |  ⌃🔙", valid=False)
    trows = [task_row(t) for t in tasks[:40]]
    lrows = [list_row(p) for p in lists]
    body = lrows + trows if it.kind in ("Y", "O") else trows + lrows
    return add_back(_okr_seal([head] + body), home)


def render_okrtag(ids, query):
    """ctx:okrtag:<id> - the tag an OKR item carries, from a CLOSED pool:
    the 0️⃣Area children and the tags the OKR list already uses (HANDOFF_OKR
    section 4). No ➕ create row: area tags are never minted from a picker
    (HANDOFF trap 11). ⏎ fires xact:okr_tag, which REPLACES the item's pool
    tag and keeps its others; on an O its open KRs follow."""
    import okr
    import tagtree
    from collections import Counter
    from periodic_rows import _b64
    snap, it, by, problem = _okr_item_for(ids)
    if problem:
        return problem
    home = _okr_home(it, by)
    labels = {(t.get("name") or "").lower(): t.get("label") or t.get("name")
              for t in cache_store.get("tags_tree") or [] if isinstance(t, dict)}
    rank = _tag_rank()
    area = sorted({(n or "").lower() for n in tagtree.children_of("0️⃣area") if n},
                  key=lambda n: (rank.get(n, len(rank)), n))
    used = Counter(str(tg).lower() for x in snap.items for tg in x.tags if tg)
    # the SAME pool retag accepts (0️⃣Area + every Y / O tag): a KR-only or
    # loose tag offered here would be refused by the verb (review 2026-09-18)
    try:
        import okr_write
        accepted = {str(n).lower() for n in okr_write.tag_pool(snap.items)}
    except Exception:
        accepted = None
    pool = area + [n for n, _c in used.most_common()
                   if n not in area and (accepted is None or n in accepted)]
    mine = {str(tg).lower() for tg in it.tags}
    rows = []
    for name in pool:
        bits = ["Area" if name in area else "In use"]
        if used.get(name):
            bits.append(f"{used[name]} item{'s' if used[name] > 1 else ''}")
        if it.kind == "O":
            bits.append("KRs follow")
        rows.append(alfred.item(
            uid=f"okrt-{name}",
            title=f"🏷️ {labels.get(name, name)}{'  ✓' if name in mine else ''}",
            subtitle=" · ".join(bits) + "  |  ⏎🏷️  ⌃🔙",
            arg=f"xact:okr_tag:{_b64({'id': it.id, 'tag': name, 'back': home})}",
            valid=True, match=f"{labels.get(name, name)} {name}"))
    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda x: x["match"]) \
            or [alfred.item(uid="okrt-none", title=f'No tag matching "{query}"',
                            subtitle="Area tags are made in TickTick  |  ⌃🔙", valid=False)]
        return add_back(_okr_seal(rows), home)
    from display import fmt_tags
    head = alfred.item(uid="okrt-head",
                       title=f"🏷 {_OKR_GLYPH.get(it.kind, '▫️')} {it.name}",
                       subtitle=f"{fmt_tags(it.tags) or 'No tag'}  |  ⌃🔙", valid=False)
    return add_back(_okr_seal([head] + (rows or [alfred.item(
        uid="okrt-empty", title="No area tags cached", subtitle="Run a sync  |  ⌃🔙",
        valid=False)])), home)


# ── 🥅 phase 3: import + text-only adds (HANDOFF_OKR section 4, Import) ─────
# "goal will mostly be a project. So a project CTA should be linked in
# title. KR will be some tasks or subtasks ... I should be able to import
# text only as well ... rapid fire key results like we rapid fire subtasks"
# (Vex 2026-09-19). Every row here fires ONE verb, xact:okr_add:<b64>
#     {"kind": Y|O|KR, "parent", "names", "code", "link", "then", "back"}
# which re-reads LIVE, refuses a wrong or closed parent and a second copy,
# stamps prefix and code (okr_write.add_items), then reopens `back` - or the
# new Y/O's tag picker when "then" is "tag" and exactly one was made. These
# screens only preview: the names, the code the verb will use, where it
# lands. They read the cache, never the network (one render per keystroke).
_OKR_CTA_HEAD = re.compile(r"^[^\w\s]{1,8}\s*P\s+[•·]\s+")      # "💼 P • "


def _okr_add_row(uid, title, subtitle, pay, match=None, dead=None, more=None):
    """One xact:okr_add row. Not a task, so the seal pins ⌘ dead and every
    other chord is dead from the start: a stray ⇧ or ⌥⇧ must never carry
    the payload down another canvas edge. `dead` = why the verb would say
    no: the row shows it and offers no ⏎. `more` = the bar Tab leaves (one
    more pipe: rapid fire, the subtask way)."""
    from periodic_rows import _b64
    return alfred.item(
        uid=uid, title=title,
        subtitle=f"{dead}  |  ⌃🔙" if dead else subtitle,
        arg="" if dead else f"xact:okr_add:{_b64(pay)}", valid=not dead,
        match=match, autocomplete=None if dead else more,
        variables=dict(_OKR_NO_TASK), mods=_okr_dead_mods())


def _okr_shown(names, cap=60):
    s = " · ".join(names)
    return s if len(s) <= cap else s[:cap - 1] + "…"


def _okr_plus_rows(it, query, items):
    """The typed ➕ rows of a hub screen (it = None for the root, else the
    Y / O the screen is about). A pipe makes several SIBLINGS; one Y or O
    goes on to its tag picker ("after adding objective or key result, next
    thing should be a tag picker"), several land back on this screen. A
    closed Y/O takes nothing new: a typed name there gets ONE dead row
    saying so (never 'Nothing matching'), and a KR screen does not exist.

    Every row is dead when the verb would refuse it or drop a name
    (add_items), with the reason as its subtitle: a "=xy" no title reads
    back, "=XY" on SEVERAL objectives (a code names ONE; a Y ignores the
    code and stays live), a name whose title would read as a code
    (_okr_unreadable, on a code-less KR too)."""
    import okr
    names, override, text = _okr_typed(query)
    if not names or (it is not None and it.kind not in ("Y", "O")):
        return []
    if it is not None and it.history:
        return [alfred.item(
            uid="okr-plus-closed", title="Closed · reopen it first",
            subtitle=f"{_OKR_GLYPH[it.kind]} {it.name} takes nothing new  |  ⌃🔙",
            valid=False, variables=dict(_OKR_NO_TASK), mods=_okr_dead_mods())]
    n, shown, more = len(names), _okr_shown(names), _okr_more(text, override)
    many = "s" if n > 1 else ""
    then = "tag" if n == 1 else None
    bad = "Code: one word, capital first" if _okr_code_bad(override) else None
    back = "ctx:okr" if it is None else f"ctx:okr:{it.kind.lower()}:{it.id}"

    def dead_for(kind, code=None):
        # the verb's own refusals and skips, in its order (add_items)
        if kind != "Y" and bad:
            return bad
        if kind == "O" and override and n > 1:
            return "=XY codes ONE objective"
        return _okr_unreadable(kind, names, code)

    def o_codes():
        codes = [override or _okr_propose(x) for x in names]
        codes = list(dict.fromkeys(c for c in codes if c))
        return (f"code{'s' if len(codes) > 1 else ''} {' · '.join(codes)}"
                if codes else "no code")

    def pay(kind, parent, code):
        return {"kind": kind, "parent": parent, "names": names, "code": code,
                "link": None, "then": then if kind != "KR" else None, "back": back}

    tag_txt = "then 🏷" if then else f"{n} siblings"
    if it is None:
        return [
            _okr_add_row("okr-plus-o", f"➕ New 🥅 objective{many} · {shown}",
                         f"{o_codes()} · {tag_txt}  |  ⏎➕  ⌃🔙",
                         pay("O", None, override), match=text, dead=dead_for("O"),
                         more=more),
            _okr_add_row("okr-plus-y", f"➕ New 🏔️ year objective{many} · {shown}",
                         f"No code · {tag_txt}  |  ⏎➕  ⌃🔙",
                         pay("Y", None, None), match=text, dead=dead_for("Y"), more=more)]
    if it.kind == "Y":
        return [_okr_add_row(
            "okr-plus-o", f"➕ New 🥅 objective{many} under {it.name} · {shown}",
            f"{o_codes()} · {tag_txt}  |  ⏎➕  ⌃🔙",
            pay("O", it.id, override), match=text, dead=dead_for("O"), more=more)]
    have = okr.code_of(it, okr.krs_of(it, items))
    code = override or have or _okr_propose(it.name)
    bits = ["| for more"] + (["new 🏷️"] if code and not have else [])
    return [_okr_add_row(
        "okr-plus-kr",
        f"➕ New 🔑 KR{many} · {shown} · {f'code {code}' if code else 'no code'}",
        " · ".join(bits) + "  |  ⏎➕  ⌃🔙",
        pay("KR", it.id, override), match=text, dead=dead_for("KR", code), more=more)]


def _okr_find_task(tid):
    """The cached open task or note (one pass, stops at the hit)."""
    for key in ("all_tasks", "all_notes"):
        for t in cache_store.get(key) or []:
            if isinstance(t, dict) and t.get("id") == tid:
                return t
    return None


def _okr_source_fallback(kind, pid, tid):
    """What the import would be when the writer layer has no import_source
    (a writer older than this screen): the plain name and the thing itself,
    the 📌CTA swap left out - the screen stays usable, and the verb still
    re-reads live before it writes anything. The plan list and a task in
    it are refused in the writer's words (okr_write.PLAN_LIST /
    IN_PLAN_COPY): no ⏎ is offered that the verb can only refuse."""
    import periodic_model as pm
    from mdtext import flatten_links
    okr_pid = cfg.get_okr_list_id()
    if kind == "list":
        if okr_pid and pid == okr_pid:
            return None, "🥅 That is the plan list · add the real one"
        p = next((p for p in cache_store.get("projects") or []
                  if isinstance(p, dict) and p.get("id") == pid), None)
        if not p:
            return None, "List not synced yet · sync or reopen"
        nm = p.get("name") or ""
        nm = _areas.clean_project_name(nm) if _areas.is_project(nm) else nm
        return {"name": " ".join(nm.split()),
                "link": {"to": "list", "pid": pid, "tid": None}, "kind_hint": "O"}, ""
    t = _okr_find_task(tid)
    if not t:
        return None, "Not synced yet · sync or reopen"
    name = _OKR_CTA_HEAD.sub("", flatten_links(pm.unescape_md(t.get("title") or "")).strip())
    name = " ".join(re.sub(r"\s*🔗\s*$", "", name).split())
    tpid = t.get("projectId") or t.get("_projectId") or pid
    if okr_pid and okr_pid in (tpid, pid):
        return None, "🥅 That is a planning copy · add the original"
    cta = bool(_areas.CTA_LIST_ID) and tpid == _areas.CTA_LIST_ID
    return {"name": name, "link": {"to": "task", "pid": tpid, "tid": tid},
            "kind_hint": "O" if cta else "KR"}, ""


def _okr_source(kind, pid, tid):
    """(source, why): what "🥅 Add to OKRs" imports - {"name", "link": {"to",
    "pid", "tid"}, "kind_hint": "O" | "KR"}. okr_write.import_source is the
    ONE resolver (the name cleaned of its CTA prefix and 🔗, a list swapped
    for its project's 📌CTA task), so the screen previews exactly what the
    payload will carry; a Refusal it raises or returns is the screen's dead
    row. Missing, or failing on something that is no refusal, the fallback
    keeps the screen alive (lazy: the writer layer is optional here)."""
    try:
        import okr_write
        fn = getattr(okr_write, "import_source", None)
        refusal = getattr(okr_write, "Refusal", None)
    except Exception:
        fn, refusal = None, None
    if fn is not None:
        try:
            r = fn(kind, pid, tid)
        except Exception as e:
            if isinstance(refusal, type) and isinstance(e, refusal):
                return None, str(e)
            r = None
        if isinstance(r, BaseException):
            return None, str(r)
        if (isinstance(r, dict) and r.get("name") and isinstance(r.get("link"), dict)
                and r["link"].get("to") in ("task", "list")):
            return r, ""
    return _okr_source_fallback(kind, pid, tid)


def _okr_planned(items, to, pid, tid):
    """The plan item that already links this, else None: okr_write.planned
    when there is one (the SAME test the verb runs inside its lock, both
    faces of a project - its list and its 📌CTA task), else the exact
    task / list (_okr_linking)."""
    try:
        import okr_write
        fn = getattr(okr_write, "planned", None)
    except Exception:
        fn = None
    if fn is not None:
        try:
            return fn(items, to, pid, tid)
        except Exception:
            pass
    return _okr_linking(items, to, pid, tid)


def _okr_linking(items, to, pid, tid):
    """The plan item that already links this (open ones first, then closed:
    history counts too - a second copy of a finished KR is still a second
    copy). A task is its id alone (its list may have changed since, it is
    the same task); a list is its list id."""
    for it in _okr_open_first(items):
        tg = it.target
        if not tg:
            continue
        if (to == "task" and tg[0] == "task" and tid and tg[2] == tid) or \
                (to == "list" and tg[0] == "list" and tg[1] == pid):
            return it
    return None


def _okr_screen_of(it, by):
    """Where an item is SHOWN: a Y / O on its own screen, a KR (or a loose
    item) on the screen that lists it."""
    if it.kind in ("Y", "O"):
        return f"ctx:okr:{it.kind.lower()}:{it.id}"
    return _okr_home(it, by)


_OKR_PLAN_KEYS = ("name", "link", "kind_hint", "hit", "screen", "blocked")


def _okr_plan_ok(r):
    """An import_plan answer this screen can render: a refusal, a hit, or
    a name with a task / list link."""
    if not isinstance(r, dict):
        return False
    if r.get("blocked") or r.get("hit") is not None:
        return True
    lk = r.get("link")
    return bool(r.get("name")) and isinstance(lk, dict) and lk.get("to") in ("task", "list")


def _okr_import_plan(kind, pid, tid, items):
    """{"name", "link", "kind_hint", "hit", "screen", "blocked"}: the ONE
    answer to "can this be added, and if not why" - okr_write.import_plan,
    the call the ⌘ Actions row makes too (actions.okr_import_row), over the
    same cached plan, and add_items asks planned() the same question inside
    its lock. This screen decides nothing on its own. A writer layer
    without it (older than this screen) gets the fallback: the resolver,
    and the dedupe over `items` asked ONCE with the payload's link - the
    screen stays usable, and the verb still decides."""
    try:
        import okr_write
        fn = getattr(okr_write, "import_plan", None)
    except Exception:
        fn = None
    if fn is not None:
        try:
            r = fn(kind, pid, tid)
        except Exception:
            r = None
        if _okr_plan_ok(r):
            return r
    import okr
    out = dict.fromkeys(_OKR_PLAN_KEYS)
    src, why = _okr_source(kind, pid, tid)
    if src is None:
        out["blocked"] = why or "🥅 Nothing to add"
        return out
    out.update(src)
    if not src.get("name"):
        out["blocked"] = "🥅 No name to copy · give it a title first"
        return out
    lk = src["link"]
    hit = _okr_planned(items, lk["to"], lk.get("pid"), lk.get("tid"))
    if hit is not None:
        out["hit"], out["screen"] = hit, _okr_screen_of(hit, okr.index(items))
    return out


def _okr_kr_dead(o, name, url, code):
    """Why a KR row of the import screen would be SKIPPED by the verb, else
    None: okr_write._title_for with the name, the link and the code
    add_items stamps (the O's, else its proposal). A linked name always
    reads back (it is the link's label), so what fails is the code - an
    O's 🏷️ line the title cannot carry ("🏷️ xy"). Lazy and forgiving: no
    writer layer, no check (the verb decides)."""
    try:
        import okr_write
        if okr_write._title_for("KR", name, url, code) is not None:
            return None
    except Exception:
        return None
    if code:
        return f"{o.name}'s code '{code}' does not read back · fix its 🏷️ line"
    return f"'{_okr_shown([name], 40)}' reads as a code · reword"


def render_okrimport(ids, query):
    """ctx:okrimport:<task|note|list>:<pid>:<tid or -> - "🥅 Add to OKRs"
    from ⌘ Actions (HANDOFF_OKR section 4, Import). The head row is the
    thing itself (⏎ opens it); then where its planning copy can go, each ⏎
    = xact:okr_add carrying the LINK:
        🔑 KR under 🥅 <O> · code XY     every open O, running ones first
        🥅 New objective · code XY       loose, then one under each open Y
        🏔️ New year objective
    kind_hint puts the likely level first: a list or a 📌CTA task plans an
    objective ("goal will mostly be a project"), anything else a KR. Typed
    words filter by the target's name; "=XY" overrides a NEW objective's
    code (dead when it would not read back). Y / O rows go on to the tag
    picker. ⌃ = the hub, the way the people picker backs to its hub.

    Whether it can be added at all is okr_write.import_plan's answer and
    nothing else (_okr_import_plan) - the call the ⌘ Actions row makes, so
    the row, this screen and the verb never disagree: a hit = a dead row
    saying so and a row that opens its screen, never a second copy; a
    refusal = its words on a dead row, never a ⏎ the verb can only
    refuse. A KR row whose O's code the title cannot carry is dead too
    (_okr_kr_dead: the verb would skip the name)."""
    import okr
    from datetime import date as _date
    back = "ctx:okr"
    kind = ids[0] if ids else ""
    spid = ids[1] if len(ids) > 1 else ""
    stid = ids[2] if len(ids) > 2 and ids[2] not in ("", "-") else None

    def dead(uid, title, sub=""):
        return add_back(_okr_seal([alfred.item(uid=uid, title=title,
                                               subtitle=f"{sub}  |  ⌃🔙" if sub else "⌃🔙",
                                               valid=False)]), back)

    if kind not in ("task", "note", "list") or not spid or (kind != "list" and not stid):
        return dead("okri-bad", "Nothing to import", "A task, note or list")
    snap, why, _live = _okr_snapshot("", live=False)
    if snap is None:
        return _okr_problem(why)
    items, today = snap.items, _date.today()
    by = okr.index(items)
    plan = _okr_import_plan(kind, spid, stid, items)
    name, link = plan.get("name"), plan.get("link")
    if plan.get("blocked") and not (name and isinstance(link, dict)):
        return dead("okri-no", plan["blocked"])
    here = (f"ticktick:///webapp/#p/{spid}/tasks/{stid}" if stid
            else f"ticktick:///webapp/#p/{spid}/tasks")
    if kind == "list":
        where = "📂 List" + (" · links its 📌 CTA" if (link or {}).get("to") == "task" else "")
    else:
        from display import pick_where
        t = _okr_find_task(stid) or {}
        par = _okr_find_task(t["parentId"]) if t.get("parentId") else None
        where = pick_where(t, {par["id"]: par} if par else None) if t else "Task"
    head = alfred.item(uid="okri-head", title=f"↗️ {_okr_shown([name or '?'], 70)}",
                       subtitle=f"{where}  |  ⏎↗️  ⌃🔙", arg=f"open:{here}", valid=True,
                       variables=dict(_OKR_NO_TASK), mods=_okr_dead_mods())

    hit = plan.get("hit")
    if hit is not None:
        # planned: where it is, never a second copy (the verb refuses one)
        screen = plan.get("screen") or "ctx:okr"
        m = re.match(r"ctx:okr:[yo]:(.+)$", screen)
        tgt = (hit if hit.id == m.group(1) else by.get(m.group(1))) if m else None
        at = f"{_OKR_GLYPH.get(tgt.kind, '▫️')} {tgt.name}" if tgt is not None else "🥅 OKRs"
        state = " · done" if hit.history else ""
        return add_back(_okr_seal([
            head,
            alfred.item(uid="okri-planned",
                        title=f"In the plan · {_OKR_GLYPH.get(hit.kind, '▫️')} {hit.name}",
                        subtitle=f"No second copy{state}  |  ⌃🔙", valid=False),
            alfred.item(uid="okri-open", title=f"⤵️ Open it · {at}",
                        subtitle="Its place in the plan  |  ⏎⤵️  ⌥⤵️  ⌃🔙",
                        arg=f"xact:crmbrowse:{screen}", valid=True,
                        variables=dict(_OKR_NO_TASK), mods=_okr_nav_mods(screen))]), back)
    if plan.get("blocked"):
        # the verb could not tell planned from not (no complete read):
        # the thing, and why nothing is offered
        return add_back(_okr_seal([
            head, alfred.item(uid="okri-blocked", title=plan["blocked"],
                              subtitle="Open 🥅 OKRs to re-read  |  ⏎⤵️  ⌃🔙",
                              arg="xact:crmbrowse:ctx:okr", valid=True,
                              variables=dict(_OKR_NO_TASK),
                              mods=_okr_nav_mods("ctx:okr"))]), back)
    url = (okr.task_link(link.get("pid"), link.get("tid")) if link["to"] == "task"
           else okr.list_link(link.get("pid")))

    found = _OKR_CODE_TOKEN.findall(query or "")
    override = found[-1] if found else None
    ftext = " ".join(_OKR_CODE_TOKEN.sub(" ", query or "").split())
    bad = "Code: one word, capital first" if _okr_code_bad(override) else None
    want = okr.wanted_spans(items)

    def now_first(o):
        s, e = _okr_span(o, want)
        running = s is not None and s <= today <= (e or s)
        return (not running, s is None, s or _date.max, o.name.lower())

    kr_rows = []
    for o in sorted((x for x in items if x.kind == "O" and not x.history), key=now_first):
        have = okr.code_of(o, okr.krs_of(o, items))
        code = have or _okr_propose(o.name)
        up = by.get(o.parent) if o.parent else None
        bits = ([f"🏔️ {up.name}"] if up is not None and up.kind == "Y" else []) \
            + [okr.span_txt(*_okr_span(o, want), today)] + (["new 🏷️"] if code and not have else [])
        kr_rows.append(_okr_add_row(
            f"okri-kr-{o.id}",
            f"🔑 KR under 🥅 {o.name} · {f'code {code}' if code else 'no code'}",
            " · ".join(bits) + "  |  ⏎✅  ⌃🔙",
            {"kind": "KR", "parent": o.id, "names": [name], "code": None, "link": link,
             "then": None, "back": f"ctx:okr:o:{o.id}"},
            match=f"{o.name} {code or ''} {up.name if up is not None else ''} kr key result",
            dead=_okr_kr_dead(o, name, url, code)))

    ocode = override or _okr_propose(name)
    ocode_txt = f"code {ocode}" if ocode else "no code"

    def o_pay(parent, where_back):
        return {"kind": "O", "parent": parent, "names": [name], "code": override,
                "link": link, "then": "tag", "back": where_back}

    obj_rows = [_okr_add_row("okri-o", f"🥅 New objective · {ocode_txt}",
                             "No year objective · then 🏷  |  ⏎✅  ⌃🔙",
                             o_pay(None, back), match="new objective o loose", dead=bad)]
    for y in _okr_open_first(x for x in items if x.kind == "Y" and not x.history):
        obj_rows.append(_okr_add_row(
            f"okri-oy-{y.id}", f"🥅 New objective under 🏔️ {y.name}",
            f"{ocode_txt} · then 🏷  |  ⏎✅  ⌃🔙", o_pay(y.id, f"ctx:okr:y:{y.id}"),
            match=f"{y.name} new objective o", dead=bad))
    obj_rows.append(_okr_add_row(
        "okri-y", "🏔️ New year objective", "One per area · then 🏷  |  ⏎✅  ⌃🔙",
        {"kind": "Y", "parent": None, "names": [name], "code": None, "link": link,
         "then": "tag", "back": back}, match="new year objective y area"))

    rows = obj_rows + kr_rows if plan.get("kind_hint") == "O" else kr_rows + obj_rows
    if ftext:
        rows = fuzz.filter_and_score(ftext, rows, key_fn=lambda x: x.get("match") or x["title"]) \
            or [alfred.item(uid="okri-none", title=f'No objective matching "{ftext}"',
                            subtitle="⌃🔙", valid=False)]
    elif not query:
        rows = [head] + rows
    return add_back(_okr_seal(rows), back)


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
            title=f"{md_links_display(name)} {priority_dot}{tag_str}",   # display-only; name stays raw below
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
            title=f"{md_links_display(name)} {priority_dot}{tag_str}",   # display-only; name stays raw below
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

# ── Level: meal (🥘 Meal Prep hub - HANDOFF_MEAL.md) ─────────────────────────
# The OKR screens' row invariants, reused as they are: six chords stamped as
# fresh dicts (_okr_seal), ⌘ dead on anything that is not a task, never an
# xact arg on ⌘ or ⌥, ⏎ navigation through the BrowseCtx trampoline (iron
# rule 8), ⌥ the same hop by variable. Since 2026-09-21 the PLAN is read off
# Apple Calendar (Mela's "Add to Calendar", src/mela_cal.py) through
# meal_write.plan_view - the screens never write (Vex: "I will be scheduling
# in Mela, it is nicer"; "get rid of Plan the week / Schedule a meal"). The
# ONE network read is the routine list on an EMPTY bar, reused for
# _MEAL_FRESH_S, so the cook Sunday survives a routine reset dropping
# all_tasks (the _okr_snapshot rule).
#
# THE MEAL ROW (hub this-week, ctx:mealw, ctx:meallib): ⏎ open:mela://recipe
# (Vex: "open the link to Mela"), ⇧ open:<web> ("and a link to the web" -
# the Browse SF's ⇧ edge is junction 581BB8A1 → Call-ET modComplete →
# dispatch.py, whose first branch executes open: args; traced 2026-09-21),
# ⌥⌘ copy:mela://recipe, ⌘ live only when the meal maps to a library task,
# and ⌥⇧ = xact:meal_cooked on that library task (Vex 2026-09-21: "mark
# meal cooked via modifier" - ⌥⇧ is the ONE chord besides ⏎ that executes
# a row's xact arg, the 892DFDB7 router; the verb tags 👨‍🍳cooked and asks
# for one note). The rating and the comments have no chord of their own:
# ⌘ Actions on the row carries ⭐️ Rate… (ctx:mealrate, the picker below)
# and 💬 Comment…, "cause I cannot rate a meal until I ate it".
#
# THE 🛒 ROW (the hub's 🛒 Groceries row, the ctx:mealgroc list rows): ⏎
# opens (the hub row the screen, a list row its task), ⇧ ticks a list done,
# ⌥⌘ copies its link, and ⌥⇧ = xact:meal_portions (Vex 2026-09-22: "can we
# have a row that would ask me how many portions of each meal I would like
# to cook this week and then adjust groceries accordingly? Like separate
# action. Maybe on groceries row for that list under some modifier?"). The
# payload is meal.portions_payload: ONE list {pid, tid} on a ctx:mealgroc
# row, {all: true} on the hub's row (the verb then asks per open list of
# the upcoming 🛒 Groceries task); `back` the screen it reopens. The sync's
# own cut stays PORTIONS = 7 ("We can keep those calculations as are in
# general"); a list row's chip says the count it was cut for now
# (meal.portions_of, off the yield note), so a re-cut is visible.
#
# THE 🏷 ROW (the hub's 🏷 Prices row, the ctx:mealprice key rows): a price
# SPECULATION, never a receipt (Vex 2026-09-22: "how feasible is the idea
# of price speculations? Like how much will each ingredient cost and total
# per meal?", "Could we not scrape prices of that site, write them in the
# pricebook and use that?", "Speculation is all I need"). The hub row sums
# the week's lists off the cost lines the sync wrote into their content
# (meal_write.week_cost: no network, no live read), ⏎ / ⌥ open the book,
# and ⌥⇧ = xact:meal_prices, the ONE road to knuspr.de (never a background
# job, Vex 2026-09-21); a ctx:mealgroc chip says a list's total the same
# way. On the book screen every key row is ⏎ xact:meal_price_set (type a
# price by hand) and ⌥⇧ xact:meal_price_search (change the term, re-read
# that one key), both with back = the screen itself; ⌥⌘ copies the product's
# knuspr page. Since D27 (Vex 2026-09-23: "Let's do what you pay at the
# till please.") the hub row says the week's TILL beside what it uses (the
# packs, pooled once across the week, meal_write.week_till) with the pantry
# staples' share apart, a ctx:mealgroc chip carries its list's till, and a
# pantry entry's book row says so.
_MEAL_FRESH_S = 45
_MEAL_SLUG = {"b": "breakfast", "l": "lunch", "s": "snack"}
_MEAL_KEY = {v: k for k, v in _MEAL_SLUG.items()}
_MEAL_PLURAL = {"Breakfast": "Breakfasts", "Lunch": "Lunches", "Snack": "Snacks"}
_MEAL_LEGEND = "⏎🍴 Mela  ⇧🌐 web  ⌥⇧👨‍🍳 cooked  ⌥⌘🔗  ⌘⚡"


def _meal_b64(d):
    import base64
    return base64.b64encode(json.dumps(d).encode("utf-8")).decode("ascii")


def _meal_link(pid, tid):
    return f"ticktick:///webapp/#p/{pid}/tasks/{tid}"


def _meal_task_vars(t, pid):
    return {"task_id": t.get("id", ""), "task_list_id": pid, "list_id": pid,
            "section_id": t.get("columnId") or "", "task_title": t.get("title", ""),
            "item_type": "task"}


def _meal_age(secs):
    if secs is None:
        return "?"
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min"
    if secs < 2 * 86400:
        return f"{int(secs // 3600)} h"
    return f"{int(secs // 86400)} d"


def _meal_off(back="ctx:folders"):
    return add_back(_okr_seal([alfred.item(
        uid="meal-off", title="🥘 Meal prep needs a list",
        subtitle="⚙️ Settings → Meal Prep List  |  ⌃🔙", valid=False)]), back)


def _meal_pool(list_id):
    import meal_write as mw
    return mw._pool_tasks(list_id)


def _meal_list(rid, live=False):
    """(the routines list's rows, its list id, the routine task) - the pool
    the batch is found in (meal.upcoming). The cache first; on an empty bar
    one live read, kept as meal_kids for _MEAL_FRESH_S."""
    import routines as rt
    t = cache_store.find_task(rid) or {}
    pid = (t.get("projectId") or t.get("_projectId")
           or (rt.by_tid(rid) or {}).get("pid") or rt.ROUTINES_LIST)
    tasks = None
    kept = cache_store.get("meal_kids")
    if (isinstance(kept, dict) and kept.get("rid") == rid
            and time.time() - (kept.get("ts") or 0) < _MEAL_FRESH_S):
        tasks = kept.get("tasks") or []
        t = kept.get("routine") or t
    elif live:
        try:
            pd = TickTickAPI(cfg.get_token()).get_project_data(pid) or {}
            tasks = list(pd.get("tasks") or [])
            t = next((x for x in tasks if x.get("id") == rid), None) or t
            try:
                cache_store.set("meal_kids", {"rid": rid, "ts": time.time(),
                                              "routine": t, "tasks": tasks})
            except Exception:
                pass
        except Exception:
            tasks = None
    if tasks is None:
        tasks = [x for x in (cache_store.get("all_tasks") or [])
                 if (x.get("projectId") or x.get("_projectId")) == pid]
        if not tasks:
            tasks = list((cache_store.get(f"project_data_{pid}") or {}).get("tasks") or [])
    return tasks, pid, t


def _meal_routine(rid, live=False):
    """(routine task, {slot: pointer task}, its list id). The cache first;
    on an empty bar one live read of the routine's list, kept as meal_kids
    for _MEAL_FRESH_S so hopping between hub screens costs nothing."""
    import meal
    import routines as rt
    t = cache_store.find_task(rid) or {}
    pid = (t.get("projectId") or t.get("_projectId")
           or (rt.by_tid(rid) or {}).get("pid") or rt.ROUTINES_LIST)
    tasks = None
    kept = cache_store.get("meal_kids")
    if (isinstance(kept, dict) and kept.get("rid") == rid
            and time.time() - (kept.get("ts") or 0) < _MEAL_FRESH_S):
        tasks = kept.get("tasks") or []
        t = kept.get("routine") or t
    elif live:
        try:
            pd = TickTickAPI(cfg.get_token()).get_project_data(pid) or {}
            tasks = list(pd.get("tasks") or [])
            live_t = next((x for x in tasks if x.get("id") == rid), None)
            t = live_t or t
            try:
                cache_store.set("meal_kids", {"rid": rid, "ts": time.time(),
                                              "routine": t, "tasks": tasks})
            except Exception:
                pass
        except Exception:
            tasks = None
    if tasks is None:
        tasks = cache_store.get("all_tasks") or []
        if not tasks:
            tasks = list((cache_store.get(f"project_data_{pid}") or {}).get("tasks") or [])
    return t, meal.pointers_of(tasks, rid), pid


def _meal_plan(sunday, n_weeks, today=None):
    """meal_write.plan_view anchored on a cook SUNDAY (the routine's, via
    first_sunday), so its first week IS that week; never raises - a broken
    read side is an error line for the status row."""
    import meal_write as mw
    try:
        pv = mw.plan_view(today=today, n_weeks=n_weeks, first_sunday=sunday) or {}
    except Exception as e:
        pv = {"weeks": [], "first_sunday": sunday, "planned_count": 0, "error": str(e)}
    pv.setdefault("weeks", [])
    pv.setdefault("planned_count", 0)
    pv.setdefault("error", "")
    return pv


def _meal_week(pv, sunday):
    """The Week for this Sunday out of plan_view's rows, empty when absent."""
    import meal
    return next((w for w in pv.get("weeks") or [] if w.sunday == sunday),
                meal.Week(sunday=sunday, meals=[]))


def _meal_history(today):
    """The calendar rows a library chip reads: a year back (cooked N weeks
    ago) and the horizon ahead (next Sun …). [] when the store is
    unreadable - the chip then says "never cooked", the hub's status row
    says why."""
    import meal_write as mw
    import mela_cal
    try:
        return mela_cal.plan(since=today - timedelta(days=364),
                             until=today + timedelta(days=7 * mw.HORIZON_WEEKS))
    except Exception:
        return []


def _meal_recipes():
    """{UUID: mela.Recipe} from the Mela snapshot (the web link lives on
    the recipe, ZLINK); {} when Mela's DB is missing or unreadable."""
    import mela
    try:
        return {(r.id or "").upper(): r for r in mela.library()}
    except Exception:
        return {}


def _meal_row(uid, m, chip, when=None, lib_kids=None, lib_title="", back="ctx:meal",
              cooked=False, rating=None):
    """THE MEAL ROW. `m` = meal.Meal (slot, name, uuid, web, tid, pid).
    `when` (a date) stamps ' · Sun 27 Sep' on a plan row; `lib_kids`
    (a count, or None on plan rows) makes ⌥ the subtask drill of a library
    row. ⌘ Actions is live ONLY with a library task behind the meal - the
    row then carries the task variables; else _okr_seal blanks them.
    ⌥⇧ = xact:meal_cooked on that same library task (the tag + one note),
    `back` the screen the verb reopens after its toast; dead without a
    task, the tag has nowhere to go. `cooked` (the 👨‍🍳cooked tag is on
    the task) and `rating` (its ⭐️ count) finish the chip: a plan row
    gets the word and the stars here, a library chip already carries
    them (meal.lib_chip), so neither is stamped twice."""
    import meal
    title = f"{m.glyph} {m.name}" + (f" · {when:%a %-d %b}" if when else "")
    if cooked and "cooked" not in (chip or ""):
        chip = f"{chip} · 👨‍🍳 cooked" if chip else "👨‍🍳 cooked"
    if meal.stars(rating) and meal.stars(rating) not in (chip or ""):
        chip = f"{chip} · {meal.stars(rating)}" if chip else meal.stars(rating)
    mods = _okr_dead_mods()
    mods["alt+cmd"] = {"arg": f"copy:{m.url}", "valid": True, "subtitle": "Copy Mela link"}
    if m.web:
        mods["shift"] = {"arg": f"open:{m.web}", "valid": True, "subtitle": "🌐 Open the web page"}
    else:
        mods["shift"] = {"arg": "", "valid": False, "subtitle": "No web page"}
    variables = None
    if m.tid:
        mods["cmd"] = {"arg": "", "valid": True, "subtitle": "⌘ Actions"}
        mods["alt+shift"] = {
            "arg": f"xact:meal_cooked:{_meal_b64(meal.cooked_payload(m.pid, m.tid, back))}",
            "valid": True, "subtitle": "👨‍🍳 Cooked · a note asked"}
        variables = _meal_task_vars({"id": m.tid, "title": lib_title or meal.md_link(m.name, m.uuid)},
                                    m.pid)
    else:
        mods["alt+shift"] = {"arg": "", "valid": False, "subtitle": "No library task"}
    if lib_kids is not None:
        mods["alt"] = {"arg": "", "valid": bool(lib_kids), "subtitle": "⤵️ Subtasks",
                       "variables": {"browse_ctx": f"ctx:subtasks:{m.pid}:{m.tid}"}}
    legend = _MEAL_LEGEND.replace("⌥⌘", "⌥⤵️  ⌥⌘") if lib_kids is not None else _MEAL_LEGEND
    return alfred.item(uid=uid, title=title,
                       subtitle=f"{chip}  |  {legend}" if chip else legend,
                       arg=f"open:{m.url}", valid=True, variables=variables, mods=mods)


def _meal_cook(sunday, today):
    """'cooked Sun 20 Sep' once the cook day is past, 'cook Sun 27 Sep' ahead
    (the hub shows THIS week, the one being eaten; next Sunday is a week row)."""
    return ("cooked" if sunday < today else "cook") + f" {sunday:%a %-d %b}"


def _meal_head(uid, week, sunday, today, routine=None, cache=False):
    import meal
    n = len(week.meals)
    what = (f"{n} meal" + ("" if n == 1 else "s")) if n else "nothing planned in Mela"
    title = f"🥘 {week.label} · {_meal_cook(sunday, today)} · {what}" + (" · cache" if cache else "")
    # a past cook day has no shopping left to do
    sub = (f"groceries {meal.grocery_day(sunday, today):%a %-d %b}" if sunday >= today
           else "eating this week")
    if routine is not None:
        sub += f" · {md_links_display(routine.get('title') or '🥘 Meal Prep')}"
    elif not n:
        sub += " · Plan it in Mela: ⌘⌥A Add to Calendar"
    return alfred.item(uid=uid, title=title, subtitle=sub + "  |  ⌃🔙", valid=False)


def render_meal(ids, query):
    """The hub root: the cook week's meals (the routine's cook Sunday, read
    off the calendar plan), 📆 the next 13 weeks, 🔄 the one sync verb,
    🛒 groceries, 🏷 the price book, the three 📚 libraries, a status line."""
    import meal
    import meal_write as mw
    from datetime import date as _date
    list_id, rid = cfg.get_meal_list_id(), cfg.get_meal_routine_id()
    if not list_id or not rid:
        return _meal_off()
    today = _date.today()
    r_tasks, _rpid, routine = _meal_list(rid, live=not query)
    # THE BATCH (Vex 2026-09-21): the next 🥘 Meal Prep task - the series or
    # the copy he moved to a weekday - and the meals Mela has on ITS day.
    prep = meal.upcoming(r_tasks, meal.PREP_TITLE, today, ids=(rid,))
    groc_task = meal.upcoming(r_tasks, meal.GROCERIES_TITLE, today,
                              ids=(cfg.get_meal_groceries_id(),))
    cook = meal.task_date(prep) if prep else meal.next_sunday(today)
    sunday = meal.cook_week_of(today)     # 📆 starts on THIS week, starred
    pool = _meal_pool(list_id)
    entries = meal.library_entries(pool, list_id)
    by_slot = meal.entries_by_slot(entries)
    pv = _meal_plan(sunday, mw.HORIZON_WEEKS, today)
    meals = meal.meals_on(pv.get("planned") or [], pv.get("by_id") or {},
                          pv.get("tag_map"), pv.get("entries") or entries, cook)
    try:
        counts = mw.hub_counts()
    except Exception as e:
        counts = {"new": 0, "missing": 0, "uncategorised": 0, "mela_error": str(e)}
    n = len(meals)
    what = (f"{n} meal" + ("" if n == 1 else "s")) if n else f"nothing planned in Mela on {cook:%a %-d %b}"
    head = f"🥘 {_meal_cook(cook, today)} · {what}" + (" · cache" if pv["error"] else "")
    gday = meal.task_date(groc_task) if groc_task else max(cook - timedelta(days=1), today)
    sub = f"{meal.week_label(sunday)} · groceries {gday:%a %-d %b}"
    if prep is None:
        sub += " · no upcoming 🥘 Meal Prep task"
    elif not n:
        sub += " · Plan it in Mela: ⌘⌥A Add to Calendar"
    rows = [alfred.item(uid="meal-head", title=head, subtitle=sub + "  |  ⌃🔙", valid=False)]
    by_tid = {e["tid"]: e for e in entries}
    for m in meals:
        e = by_tid.get(m.tid) or {}
        rows.append(_meal_row(f"meal-{m.slot}-{m.uuid[:8]}", m,
                              (meal.slot(m.slot) or meal.SLOT_X)[3], when=m.date,
                              back="ctx:meal", cooked=e.get("cooked", False),
                              rating=e.get("rating")))
    n_plan = pv["planned_count"]
    rows.append(alfred.item(
        uid="meal-next", title=f"📆 Next {mw.HORIZON_WEEKS} weeks",
        subtitle=f"{n_plan} planned meal" + ("" if n_plan == 1 else "s")
                 + " in the Mela calendar · by week  |  ⏎⤵️  ⌥⤵️",
        arg="xact:crmbrowse:ctx:mealq", valid=True, mods=_okr_nav_mods("ctx:mealq")))
    n_new, n_missing = counts.get("new", 0), counts.get("missing", 0)
    sync_arg = f"xact:meal_sync:{_meal_b64(meal.sync_payload('ctx:meal'))}"
    sm = _okr_dead_mods()
    sm["alt+shift"] = {"arg": sync_arg, "valid": True, "subtitle": "🔄 Sync with Mela"}
    rows.append(alfred.item(
        uid="meal-sync",
        title=f"🔄 Sync with Mela · {n_new} new · {n_missing} to fill",
        subtitle=f"Recipes in, descriptions filled, {cook:%a %-d %b}'s meals onto the prep task + groceries + note + recipe dates",
        arg=sync_arg, valid=True, mods=sm))
    groc = mw._grocery_lists(pool + r_tasks)
    # ⌥⇧ asks a count for every open list and re-cuts them (Vex 2026-09-22:
    # "how many portions of each meal I would like to cook this week");
    # dead with nothing to re-cut
    gm = _okr_nav_mods("ctx:mealgroc")
    gm["alt+shift"] = {
        "arg": "xact:meal_portions:" + _meal_b64(meal.portions_payload(back="ctx:meal")),
        "valid": len(groc) > 0, "subtitle": "🔢 Portions… (asks per list)"}
    rows.append(alfred.item(
        uid="meal-groc",
        title=f"🛒 Groceries · {len(groc)} open list" + ("" if len(groc) == 1 else "s") + f" · {gday:%a %-d %b}",
        subtitle=("under " + md_links_display(groc_task.get("title") or "🛒 Groceries") if groc_task
                  else "loose in the library list") + "  |  ⏎⤵️  ⌥⤵️  ⌥⇧🔢",
        arg="xact:crmbrowse:ctx:mealgroc", valid=True, mods=gm))
    # 🏷 the week's speculation (Vex 2026-09-22: "how much will each
    # ingredient cost and total per meal?", "Speculation is all I need"):
    # what the week USES read off the lists' cost lines, and what the
    # TILL charges for the packs (Vex 2026-09-23: "Let's do what you pay
    # at the till please.") pooled once across the week off the book, the
    # pantry staples' share said apart; no network here, ⌥⇧ is the ONE
    # road to knuspr.de (never a background job, Vex 2026-09-21)
    import meal_price as mp
    book = mp.load_book()
    try:
        wtotal, wholes, _wn = mw.week_cost()
    except Exception:
        wtotal, wholes = None, 0
    try:
        wtill, wpantry, _wl = mw.week_till(book=book)
    except Exception:
        wtill, wpantry = None, 0.0
    n_book = len(book.get("entries") or {})
    pm = _okr_nav_mods("ctx:mealprice")
    pm["alt+shift"] = {"arg": "xact:meal_prices:" + _meal_b64({"back": "ctx:meal"}),
                       "valid": True, "subtitle": "🏷 Refresh prices from knuspr.de"}
    chips = ([f"≈ {wtotal:.2f} € used"] if wtotal is not None else []) \
        + ([f"till ≈ {wtill:.2f} €"] if wtill is not None else [])
    ptitle = "🏷 Prices · " + (" · ".join(chips) if chips else "nothing priced yet")
    if wholes:
        ptitle += f" · {wholes} unpriced"
    rows.append(alfred.item(
        uid="meal-price", title=ptitle,
        subtitle=(f"pantry {wpantry:.2f} € of the till · " if wpantry else "")
                 + f"knuspr.de speculation · book {n_book} entr{'y' if n_book == 1 else 'ies'}"
                 " · ⌥⇧ refresh (≈ 0.5 s a key)  |  ⏎⤵️  ⌥⤵️  ⌥⇧🏷",
        arg="xact:crmbrowse:ctx:mealprice", valid=True, mods=pm))
    for key, tag, glyph, label in meal.SLOTS:
        ctx = f"ctx:meallib:{_MEAL_SLUG[key]}"
        rows.append(alfred.item(
            uid=f"meal-lib-{key}", title=f"📚 {glyph} {_MEAL_PLURAL.get(label, label + 's')} · {len(by_slot[key])}",
            subtitle=f"the {tag} library  |  ⏎⤵️  ⌥⤵️",
            arg=f"xact:crmbrowse:{ctx}", valid=True, mods=_okr_nav_mods(ctx)))
    if pv["error"]:
        st = pv["error"]
    elif counts.get("mela_error"):
        st = f"Mela: {counts['mela_error']}"
    else:
        cal = ", ".join(pv.get("calendars") or []) or "calendar"
        st = (f"Mela data {_meal_age(counts.get('mela_age_s'))} old · {cal}: {n_plan} planned meal"
              + ("" if n_plan == 1 else "s"))
    rows.append(alfred.item(uid="meal-status", title=f"ℹ️ {st}",
                            subtitle=f"{len(entries)} recipes in the library  |  ⌃🔙",
                            valid=False))
    if query:
        rows = [r for r in rows if fuzz.score(query, r["title"]) > 0] or \
               [alfred.item(uid="meal-none", title="No row matches", valid=False)]
    return add_back(_okr_seal(rows), "ctx:folders")


def render_mealq(ids, query):
    """The quarter: one row per cook week for HORIZON_WEEKS from the
    routine's cook Sunday (Vex: "all the next meals for a quarter, by
    week"). This week starred; an empty week is a dead row that says
    where to plan it. ⏎ / ⌥ open that week (ctx:mealw:<sunday>)."""
    import meal
    import meal_write as mw
    from datetime import date as _date
    list_id, rid = cfg.get_meal_list_id(), cfg.get_meal_routine_id()
    if not list_id or not rid:
        return _meal_off("ctx:meal")
    today = _date.today()
    sunday = meal.cook_week_of(today)     # this week first, starred
    pv = _meal_plan(sunday, mw.HORIZON_WEEKS, today)
    weeks = list(pv["weeks"])
    if not weeks:
        weeks = [meal.Week(sunday=sunday + timedelta(days=7 * i), meals=[])
                 for i in range(mw.HORIZON_WEEKS)]
    rows = []
    for w in weeks:
        star = "⭐️ " if w.sunday == sunday else ""
        ctx = f"ctx:mealw:{w.sunday.isoformat()}"
        names = " · ".join(f"{m.glyph} {m.name}" for m in w.meals)
        if w.meals:
            rows.append(alfred.item(
                uid=f"mq-{w.sunday.isoformat()}", title=f"{star}{w.label} · {names}",
                subtitle=f"{_meal_cook(w.sunday, today)} · {len(w.meals)} meal"
                         + ("" if len(w.meals) == 1 else "s") + "  |  ⏎⤵️  ⌥⤵️",
                arg=f"xact:crmbrowse:{ctx}", valid=True, mods=_okr_nav_mods(ctx)))
        else:
            rows.append(alfred.item(
                uid=f"mq-{w.sunday.isoformat()}", title=f"{star}{w.label} · nothing planned",
                subtitle=f"{_meal_cook(w.sunday, today)} · Plan it in Mela: ⌘⌥A Add to Calendar",
                valid=False, mods=_okr_nav_mods(ctx)))
    if pv["error"]:
        rows.insert(0, alfred.item(uid="mq-err", title=f"ℹ️ {pv['error']}",
                                   subtitle="the weeks below come from the cache  |  ⌃🔙",
                                   valid=False))
    if query:
        rows = [r for r in rows if fuzz.score(query, r["title"]) > 0] or \
               [alfred.item(uid="mq-none", title=f'No week matching "{query}"', valid=False)]
    return add_back(_okr_seal(rows), "ctx:meal")


def render_mealw(ids, query):
    """One cook week (ctx:mealw:<YYYY-MM-DD of its Sunday>): the head line
    and that week's MEAL ROWS."""
    import meal
    from datetime import date as _date
    list_id = cfg.get_meal_list_id()
    if not list_id:
        return _meal_off("ctx:mealq")
    try:
        sunday = meal.cook_week_of(_date.fromisoformat((ids[0] or "").strip()))
    except (ValueError, IndexError, TypeError):
        return _missing("mealw", "<YYYY-MM-DD sunday>")
    today = _date.today()
    pv = _meal_plan(sunday, 1, today)
    week = _meal_week(pv, sunday)
    rows = [_meal_head("mw-head", week, sunday, today, cache=bool(pv["error"]))]
    meals = week.meals
    if query:
        meals = fuzz.filter_and_score(query, meals, key_fn=lambda m: m.name)
    # the library as plan_view read it (a broken read side hands back none:
    # the cache pool then, so the cooked / ⭐️ chips never depend on the calendar)
    entries = pv.get("entries") or meal.library_entries(_meal_pool(list_id), list_id)
    by_tid = {e["tid"]: e for e in entries}
    back = f"ctx:mealw:{sunday.isoformat()}"
    for m in meals:
        e = by_tid.get(m.tid) or {}
        rows.append(_meal_row(f"mw-{m.slot}-{m.uuid[:8]}", m,
                              (meal.slot(m.slot) or meal.SLOT_X)[3], when=m.date,
                              back=back, cooked=e.get("cooked", False), rating=e.get("rating")))
    if query and not meals:
        rows.append(alfred.item(uid="mw-none", title="No meal matches", valid=False))
    return add_back(_okr_seal(rows), "ctx:mealq")


def render_meallib(ids, query):
    """One tag's library, never-cooked first: MEAL ROWS with the cooked chip
    read off the calendar plan ('never cooked' / 'cooked 2 weeks ago' /
    'next Sun 4 Oct'), 'cooked before' when only the 👨‍🍳cooked tag says
    so, then the ⭐️ rating (meal.lib_chip; the tag-only rows sort after
    the never-cooked ones); ⌥ drills open subtasks."""
    import meal
    from datetime import date as _date
    list_id = cfg.get_meal_list_id()
    if not list_id:
        return _meal_off("ctx:meal")
    key = _MEAL_KEY.get((ids[0] or "").lower(), ids[0] if ids[0] in meal.SLOT_KEYS else None)
    if key is None:
        return _missing("meallib", "<breakfast|lunch|snack>")
    _k, tag, glyph, label = meal.slot(key)
    today = _date.today()
    pool = _meal_pool(list_id)
    planned = _meal_history(today)
    recipes = _meal_recipes()
    entries = meal.sort_for_lib([e for e in meal.library_entries(pool, list_id) if e["slot"] == key],
                                planned, today)
    kids = {}
    for t in cache_store.get("all_tasks") or []:
        if t.get("parentId") and t.get("status", 0) == 0:
            kids[t["parentId"]] = kids.get(t["parentId"], 0) + 1
    if query:
        entries = fuzz.filter_and_score(query, entries, key_fn=lambda e: e["name"])
    rows = [alfred.item(uid="ml-head", title=f"📚 {glyph} {_MEAL_PLURAL.get(label, label + 's')} · {len(entries)}",
                        subtitle=f"{tag} · never cooked first · ⏎ opens the recipe in Mela  |  ⌃🔙", valid=False)]
    back = f"ctx:meallib:{_MEAL_SLUG[key]}"
    for e in entries:
        r = recipes.get(e["uuid"])
        m = meal.Meal(slot=key, name=e["name"], uuid=e["uuid"], date=today,
                      web=(getattr(r, "link", "") or "").strip(), tid=e["tid"], pid=e["pid"])
        chip = meal.lib_chip(planned, e["uuid"], today, tagged=e["cooked"], rating=e["rating"])
        chip += " · " + ("recipe in the description" if e.get("content") else "no description yet")
        rows.append(_meal_row(f"ml-{e['tid']}", m, chip, lib_kids=kids.get(e["tid"], 0),
                              lib_title=e["title"], back=back, cooked=e["cooked"],
                              rating=e["rating"]))
    if not entries:
        rows.append(alfred.item(uid="ml-none", title="No recipe matches" if query
                                else f"No {tag} recipes yet", valid=False))
    return add_back(_okr_seal(rows), "ctx:meal")


def render_mealgroc(query):
    """This week's 🛒 checklists, wherever the sync put them (under the
    upcoming 🛒 Groceries task, loose in the library list without one): ⏎
    opens the task, ⇧ ticks it done, ⌥⌘ copies its link, ⌘ Actions, and
    ⌥⇧ = xact:meal_portions on THAT list (Vex 2026-09-22: "a row that would
    ask me how many portions of each meal I would like to cook this week
    and then adjust groceries accordingly ... Maybe on groceries row for
    that list under some modifier?"): the verb asks one count and re-cuts
    the checklist. The chip says the count a list was cut for now
    (meal.portions_of, read off the yield note the sync wrote into the
    task's content); the very first lists were saved with an empty content,
    so the chip and the chord's "now N" go missing on those, never wrong.
    The sync's own cut stays PORTIONS = 7 ("We can keep those calculations
    as are in general"). A list the book has costed carries " · ≈ 18.40 €"
    after the portions chip, off the cost line the sync writes FIRST in the
    content (_meal_cost_total); the lists cut before the book existed have
    none, so that chip goes missing too, never wrong."""
    import meal
    import meal_write as mw
    list_id, rid = cfg.get_meal_list_id(), cfg.get_meal_routine_id()
    if not list_id:
        return _meal_off("ctx:meal")
    pool = _meal_pool(list_id)
    r_tasks = _meal_list(rid, live=False)[0] if rid else []
    # the lists sit under the upcoming 🛒 Groceries task now (loose in the
    # library list only when there is none)
    groc = list(mw._grocery_lists(pool + r_tasks).values())
    groc.sort(key=lambda t: (t.get("dueDate") or "", t.get("title") or ""))
    if query:
        groc = fuzz.filter_and_score(query, groc, key_fn=lambda t: t.get("title") or "")
    rows = [alfred.item(uid="mg-head", title=f"🛒 Groceries · {len(groc)} open list"
                        + ("" if len(groc) == 1 else "s"),
                        subtitle=f"one checklist per planned meal, cut to {meal.PORTIONS} portions"
                                 " · ⌥⇧ re-cuts one  |  ⌃🔙",
                        valid=False)]
    for t in groc:
        pid = t.get("projectId") or t.get("_projectId") or list_id
        link = _meal_link(pid, t["id"])
        items = t.get("items") or []
        done = sum(1 for it in items if it.get("status") == 2)
        dd = meal.task_date(t)
        due = f"{dd:%a %-d %b}" if dd else ""
        parsed = meal.parse_title(t.get("title") or "")
        name = parsed[0] if parsed else (t.get("title") or "")
        mods = _okr_dead_mods()
        mods["cmd"] = {"arg": "", "valid": True, "subtitle": "⌘ Actions"}
        mods["shift"] = {"arg": f"complete:{pid}:{t['id']}:{t.get('title', '')}",
                         "valid": True, "subtitle": "✅ Done"}
        mods["alt+cmd"] = {"arg": f"copy:{link}", "valid": True, "subtitle": "Copy link"}
        # the count this list was cut for, off its yield note (None on the
        # first lists, saved without one): the chord's default, the chip
        portions = meal.portions_of(t.get("content") or t.get("desc") or "")
        mods["alt+shift"] = {
            "arg": "xact:meal_portions:" + _meal_b64(meal.portions_payload(pid, t["id"], "ctx:mealgroc")),
            "valid": True,
            "subtitle": "🔢 Portions…" + (f" (now {portions})" if portions is not None else "")}
        chip = f"{done}/{len(items)} ticked" if items else "no items (recipe not in Mela?)"
        if portions is not None:
            chip += f" · {portions} portions"
        cost = _meal_cost_total(t.get("content") or t.get("desc") or "")
        if cost is not None:
            used, till = cost
            chip += f" · ≈ {used:.2f} €"
            if till is not None:            # a line written before D27 has no till
                chip += f" · till {till:.2f} €"
        rows.append(alfred.item(
            uid=f"mg-{t['id']}", title=f"🛒 {name}",
            subtitle=f"{('due ' + due + ' · ') if due else ''}{chip}  |  ⏎↗️  ⇧✅  ⌥⇧🔢  ⌥⌘🔗  ⌘⚡",
            arg=f"open:{link}", valid=True, variables=_meal_task_vars(t, pid), mods=mods))
    if not groc:
        rows.append(alfred.item(uid="mg-none", title="No grocery lists open",
                                subtitle="🔄 Sync with Mela to make them  |  ⌃🔙", valid=False))
    return add_back(_okr_seal(rows), "ctx:meal")


def render_mealrate(ids, query):
    """ctx:mealrate:<pid>:<tid>[:<back level>[:<more>]] - the ⭐️ picker a
    recipe's ⌘ Actions opens (Vex 2026-09-21: "rate a meal and give a
    comment", "it should use stars"). The head says the recipe and its
    rating now, the comments already under it follow (dead, oldest first,
    the retrospective "add less salt next time" lines), then ⭐️ .. ⭐️⭐️⭐️⭐️⭐️
    and 🚫 No rating: each fires xact:meal_rate on ⏎ and ⌥⇧ alike (the 🔄
    row's pair - both chords execute an xact arg, nothing else does), and
    the verb reopens `back` after its toast: the trailing ids re-joined
    ("meallib:lunch" -> ctx:meallib:lunch), the hub when none. The pid in
    the ctx wins for the payload (a row can come off a view alias); the
    task itself is read from the cache, a recipe not in it is a dead row.
    Not task rows: the seal keeps ⌘ dead and blanks the variables."""
    import meal
    pid, tid = (ids[0] or "").strip(), (ids[1] or "").strip()
    back = "ctx:" + ":".join(ids[2:]) if len(ids) > 2 else "ctx:meal"
    list_id = cfg.get_meal_list_id()
    t = cache_store.find_task(tid) if tid else None
    if not t and list_id:
        t = next((x for x in _meal_pool(list_id) if x.get("id") == tid), None)
    if not t:
        return add_back(_okr_seal([alfred.item(
            uid="mr-none", title="Recipe not in the cache · open the library first",
            subtitle="🥘 Meal Prep › 📚 library  |  ⌃🔙", valid=False)]), back)
    parsed = meal.parse_title(t.get("title") or "")
    name = parsed[0] if parsed else meal.unescape(t.get("title") or "")
    content = t.get("content") or ""
    now = meal.read_rating(content)
    rows = [alfred.item(
        uid="mr-head",
        title=f"⭐️ Rate · {name} · " + (f"now {meal.stars(now)}" if now else "not rated"),
        subtitle="⏎ on a row below · the stars land under the recipe's links  |  ⌃🔙",
        valid=False)]
    for i, c in enumerate(meal.read_comments(content)[:5]):
        rows.append(alfred.item(uid=f"mr-c{i}", title=f"💬 {c}",
                                subtitle="a comment already under the rating", valid=False))
    for n in range(1, meal.MAX_STARS + 1):
        arg = f"xact:meal_rate:{_meal_b64(meal.rate_payload(pid, tid, n, back))}"
        mods = _okr_dead_mods()
        mods["alt+shift"] = {"arg": arg, "valid": True, "subtitle": "⭐️ Rate"}
        rows.append(alfred.item(
            uid=f"mr-{n}", title=meal.stars(n),
            subtitle="⏎ rate" + (" · current" if n == now else ""),
            arg=arg, valid=True, mods=mods, match=f"{n} {meal.stars(n)} {n} stars"))
    clear = f"xact:meal_rate:{_meal_b64(meal.rate_payload(pid, tid, 0, back))}"
    mods = _okr_dead_mods()
    if now:
        mods["alt+shift"] = {"arg": clear, "valid": True, "subtitle": "🚫 Clear the rating"}
    rows.append(alfred.item(
        uid="mr-0", title="🚫 No rating",
        subtitle="⏎ clears the stars line" if now else "not rated yet",
        arg=clear if now else "", valid=bool(now), mods=mods, match="0 none clear no rating"))
    if query:
        rows = [r for r in rows if fuzz.score(query, r.get("match") or r["title"]) > 0] or \
               [alfred.item(uid="mr-nomatch", title="No row matches", valid=False)]
    return add_back(_okr_seal(rows), back)


def _meal_cost_total(content):
    """(used, till) off a 🛒 list's cost line (the first line the sync
    writes above the yield note; meal_price.read_cost_line reads it as
    (total, per_portion, unpriced, till)), None on a list without one -
    the lists cut before the book existed. `till` is None on a line
    written before D27 (Vex 2026-09-23: "Let's do what you pay at the
    till please."), so the chip says only what it knows. A reader that
    trips is a missing chip, never a broken screen."""
    import meal_price as mp
    try:
        got = mp.read_cost_line(content or "")
        if got is None:
            return None
        total, _per, holes, till = got
        if holes is None and not total:      # "nothing priced yet": no chip, like the hub
            return None
        return float(total), (float(till) if till is not None else None)
    except Exception:
        return None


def _meal_price_usable(e):
    """The book entry when it can price a line (a per-unit price in g / ml
    / pc), else None: a bare entry that only carries a search term is a
    hole in the book, not a price."""
    import meal_price as mp
    return e if isinstance(e, dict) and mp._entry_per(e)[0] is not None else None


def _meal_day_text(iso):
    """A book date the way a row reads it: '22 Sep' from the ISO stamp the
    book keeps, '?' when there is none or it is not a date."""
    from datetime import date as _date
    try:
        return f"{_date.fromisoformat(str(iso)[:10]):%-d %b}"
    except (TypeError, ValueError):
        return "?"


def render_mealprice(ids, query):
    """ctx:mealprice[:<back level>[:<more>]] - the 🏷 price book (Vex
    2026-09-22: "Could we not scrape prices of that site, write them in
    the pricebook and use that?", "Speculation is all I need"). The head
    says the book's size, the week's holes and when knuspr.de was last
    read; then the WEEK's ingredient keys (meal_price.keys_of over the
    open 🛒 lists' item titles, the price suffix stripped first or "rice ·
    ≈ 1.75 €" would key as three words), the unpriced ones FIRST so the
    holes are what the eye lands on (❓), then the priced ones with the
    shelf price and the product knuspr picked (🧾, ✍️ when typed by hand),
    then the rest of the book (📖, not on this week's lists). A key is
    priced the way a line is: meal_price.lookup, so "boneless chicken
    thigh" wears the "chicken thigh" entry. ⏎ on any key row types a price
    by hand (xact:meal_price_set, a manual entry the refresh never
    overwrites), ⌥⇧ changes the search term and re-reads that ONE key
    (xact:meal_price_search) - both reopen THIS ctx after the toast, the
    ⭐️ picker's shape; ⌥⌘ copies the product's knuspr page. The book is
    read once a render and no network is ever touched here (the refresh
    is the hub row's ⌥⇧). A row whose key or entry is a pantry staple
    (meal_price.is_pantry: the entry's own flag, else the default list)
    wears " · pantry" at the end of its title, because the till counts
    those packs but the hub says their share apart (D27, Vex 2026-09-23:
    "Let's do what you pay at the till please."), and the price box takes
    "pantry" / "not pantry" to flip the flag. Not task rows: the seal
    keeps ⌘ dead and blanks the variables. back = the trailing ids
    re-joined, the hub when none. The bar filters on the key and the
    product name."""
    import meal_price as mp
    import meal_write as mw
    ctx = "ctx:mealprice" + (":" + ":".join(ids) if ids else "")
    back = "ctx:" + ":".join(ids) if ids else "ctx:meal"
    book = mp.load_book()
    entries = book.get("entries") or {}
    lines = []
    for t in mw.week_lists():
        lines += [mp.strip_price(it.get("title") or "") for it in (t.get("items") or [])
                  if isinstance(it, dict)]
    # the verdict comes from the engine that wrote the suffixes, never from
    # a bare lookup: a key is priced when one of its lines cost something
    import meal_scale as _ms
    week = mp.keys_of(lines)
    costs = {}
    for c in mp.list_cost(lines, book).costs:
        if c.key:
            costs.setdefault(c.key, []).append(c)
    found, why = {}, {}
    for k in week:
        ok = [c for c in costs.get(k, []) if c.reason == "priced"]
        if ok:
            base = mp.to_base(_ms.parse_quantity(mp.strip_price(ok[0].line)))[1]
            found[k] = _meal_price_usable(mp.lookup(k, book, base))
        else:
            found[k] = None
            reasons = [c.reason for c in costs.get(k, [])]
            why[k] = ("unit mismatch" if "unit mismatch" in reasons
                      else "no amount" if reasons and all(r == "no amount" for r in reasons)
                      else "no entry")
    holes = [k for k in week if found[k] is None]
    priced = [k for k in week if found[k] is not None]
    used = {(e or {}).get("key") for e in found.values() if e}
    rest = sorted(k for k in entries if k not in found and k not in used)
    rows = [alfred.item(
        uid="mp-head",
        title=f"🏷 Price book · {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
              f" · {len(holes)} unpriced this week · updated {book.get('updated') or 'never'}",
        subtitle="knuspr.de prices as speculation · ⏎ type a price (or pantry / not pantry in the price box)"
                 " · ⌥⇧ change the search term  |  ⌃🔙",
        valid=False)]

    def key_row(glyph, key, e):
        # a priced week key edits the ENTRY that prices it ("boneless
        # chicken thigh" wears "chicken thigh"), a hole mints its own
        pay = _meal_b64({"key": (e or {}).get("key") or key, "back": ctx})
        term = mp.search_term(key, book)
        url = (e or {}).get("url") or ""
        # the pantry verdict: the entry that prices the row, else the bare
        # entry a "pantry" answer minted under the exact key (it prices
        # nothing, so `e` is None for it), else the default list by key
        pantry = mp.is_pantry(key, e if e is not None else entries.get(key))
        mods = _okr_dead_mods()
        mods["alt+shift"] = {"arg": f"xact:meal_price_search:{pay}", "valid": True,
                             "subtitle": "🔍 Search term…"}
        if url:
            mods["alt+cmd"] = {"arg": f"copy:{url}", "valid": True, "subtitle": "Copy the knuspr link"}
        if e is None:
            title = f"{glyph} {key} · no price yet"
            reason = why.get(key, "no entry")
            if reason == "unit mismatch":
                sub = "pieces against a per-kilo price · ⏎ type a price per piece"
            elif reason == "no amount":
                sub = "the line has no amount · ⏎ a price still serves other lines"
            else:
                sub = f"searched as {term} · ⏎ type a price · ⌥⇧ search term"
        else:
            per, unit = mp._entry_per(e)
            when = _meal_day_text(e.get("date"))
            if e.get("key") and e.get("key") != key:
                key = f"{key} ({e['key']})"
            if e.get("source") == "manual":
                title = f"{glyph} {key} · {mp._per_text(per, unit)} · manual {when}"
                sub = "typed by hand, the refresh leaves it · ⏎ type a price · ⌥⇧ search term"
            else:
                try:
                    price = f"{float(e.get('price')):.2f} €"
                except (TypeError, ValueError):
                    price = "? €"
                what = " ".join(s for s in (e.get("product") or "?", e.get("pack") or "", price) if s)
                title = f"{glyph} {key} · {mp._per_text(per, unit)} · {what} · knuspr {when}"
                sub = f"searched as {term} · ⏎ type a price · ⌥⇧ search term"
        if pantry:
            title += " · pantry"
        if url:
            sub += "  |  ⌥⌘🔗"
        return alfred.item(uid=f"mp-{key}", title=title, subtitle=sub,
                           arg=f"xact:meal_price_set:{pay}", valid=True, mods=mods,
                           match=f"{key} {(e or {}).get('product') or ''}".strip())

    body = ([key_row("❓", k, None) for k in holes]
            + [key_row("✍️" if found[k].get("source") == "manual" else "🧾", k, found[k])
               for k in priced]
            + [key_row("📖", k, _meal_price_usable(entries[k])) for k in rest])
    if query:
        body = [r for r in body if fuzz.score(query, r.get("match") or r["title"]) > 0]
    rows += body
    if not body:
        rows.append(alfred.item(
            uid="mp-none", title="No entry matches" if query else "Nothing to price yet",
            subtitle="🔄 Sync with Mela makes the lists · ⌥⇧ on 🏷 Prices reads knuspr.de  |  ⌃🔙",
            valid=False))
    return add_back(_okr_seal(rows), back)


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

        elif level == "pnlist":
            items = render_pnlist(ids, query)

        elif level == "bridges":
            items = render_bridges(ids, query)

        elif level in ("people", "person"):
            items = render_people(level, ids, query)

        elif level in ("countdowns", "countdown"):
            items = render_countdowns(level, ids, query)

        elif level in ("habits", "habit"):
            items = render_habits(level, ids, query)

        elif level == "routines":
            items = render_routines(query)

        elif level == "rtrack":
            items = render_rtrack(ids, query)

        elif level == "rconfirm":
            items = render_rconfirm(ids, query)

        elif level == "okr":
            items = render_okr(ids, query)

        elif level == "meal":
            items = render_meal(ids, query)

        elif level == "mealq":
            items = render_mealq(ids, query)

        elif level == "mealw":
            items = render_mealw(ids, query) if ids else _missing(level, "<YYYY-MM-DD sunday>")

        elif level == "meallib":
            items = render_meallib(ids, query) if ids else _missing(level, "<breakfast|lunch|snack>")

        elif level == "mealgroc":
            items = render_mealgroc(query)

        elif level == "mealrate":
            items = render_mealrate(ids, query) if len(ids) >= 2 else _missing(level, "<listId>:<taskId>")

        elif level == "mealprice":
            items = render_mealprice(ids, query)

        elif level == "okrpace":
            items = render_okrpace(ids, query)

        elif level in ("okrsched", "okraddkr", "okrlink", "okrtag"):
            items = ({"okrsched": render_okrsched, "okraddkr": render_okraddkr,
                      "okrlink": render_okrlink, "okrtag": render_okrtag}[level](ids, query)
                     if ids else _missing(level, "<itemId>"))

        elif level == "okrimport":
            items = render_okrimport(ids, query)

        elif level == "okrcarry":
            items = render_okrcarry(ids, query)

        elif level == "tph":
            items = render_tph(ids[0] if ids else "", query)

        elif level == "triage":
            items = render_triage(ids[0] if ids else "", query)

        elif level == "contentpl":
            items = render_contentpl(ids, query)

        elif level == "plfolder":
            items = render_plfolder(ids, query)

        elif level == "albpick":
            items = render_albpick(ids, query)

        elif level == "albcust":
            items = render_albcust(ids, query)

        elif level == "cmanage":
            items = render_cmanage(query)

        elif level == "lbphotos":
            items = render_lbphotos(ids, query)

        elif level == "bulkstage":
            items = render_bulkstage(ids, query)

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
