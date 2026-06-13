#!/usr/bin/env python3
"""
everything_search.py — Alfred Script Filter
Searches across ALL item types: lists, sections, and tasks at every depth.

Each result carries an item_type variable ("list" / "section" / "task") so
Alfred's Conditional node can route ⌥⏎ (Browse) to the correct Script Filter:
  item_type == "list"    → sections.py   (needs: list_id)
  item_type == "section" → tasks.py      (needs: list_id, section_id, section_name)
  item_type == "task"    → subtasks.py   (needs: task_id, task_title, task_list_id)
"""
import sys
import os
import json
import traceback

# ── Fallback error output ────────────────────────────────────────────────────
def emit(items):
    print(json.dumps({"items": items}))

def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])

# ── Path setup ───────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    import cache as cache_store
    import alfred
    import fuzzy as fuzz
    from display import build_title, build_subtitle, join_breadcrumb, search_key, MODS_NOTE
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

# ── Breadcrumb helper (mirrors filter_all.py logic) ──────────────────────────
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
    ("l ",  "📋", "Lists",            "search only lists",        "L"),
    ("s ",  "📑", "Sections",         "search only sections",     "S"),
    ("t ",  "✅", "Tasks",            "top-level tasks",          "T"),
    ("tt ", "↳",  "Subtasks",         "subtasks only",            "TT"),
    ("a ",  "🗂",  "Tasks + Subtasks", "tasks at any depth",       "A"),
    ("n ",  "📝", "Notes",            "note titles",              "N"),
    ("nc ", "📄", "Note bodies",      "search inside note text",  "NC"),
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
        return [alfred.item(
            title="Type to search everything…",
            subtitle="Type / to choose search scope",
            valid=False,
        )]

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

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    raw_query = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        hint_items = get_hint_items(raw_query)
        if hint_items is not None:
            print(alfred.output(hint_items, skipknowledge=True))
            return

        scope, query = detect_scope(raw_query)
        projects  = cache_store.get("projects") or []
        all_tasks = cache_store.get("all_tasks")
        if all_tasks is None:
            # Cache was invalidated — re-fetch so search works immediately
            try:
                import config as cfg
                from api import TickTickAPI
                api_client = TickTickAPI(cfg.get_token())
                all_tasks  = []
                # Inbox is not returned by /project — fetch it separately
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

        items = []

        # ── Lists ─────────────────────────────────────────────────────────────
        for p in (projects if scope in (None, "list", "section") else []):
            pid   = p["id"]
            pname = p.get("name", "Untitled")
            pdata = cache_store.get(f"project_data_{pid}") or {}
            sections = pdata.get("columns", []) or []

            # Sub-count: sections if the list uses them, else top-level tasks
            if sections:
                sub_count   = len(sections)
                child_label = "Section"
            else:
                sub_count   = sum(1 for t in all_tasks
                                  if t.get("_projectId") == pid
                                  and t.get("status", 0) == 0
                                  and not t.get("parentId"))
                child_label = "Task"

            link = f"ticktick:///webapp/#p/{pid}/tasks"

            if scope in (None, "list"):
                items.append(alfred.item(
                    uid=f"list-{pid}",
                    title=pname,
                    subtitle=build_subtitle(sub_count, "List", child_label, actions=True),
                    arg=f"open:{link}",
                    mods={
                        "alt":     {"arg": "",              "subtitle": "Browse sections"},
                        "alt+cmd": {"arg": f"copy:{link}",  "subtitle": "Copy link to list"},
                    },
                    variables={"item_type": "list", "list_id": pid, "search_name": pname, "type_rank": 0},
                ))

            # ── Sections ──────────────────────────────────────────────────────
            if scope in (None, "section"):
                for s in sections:
                    sid   = s["id"]
                    sname = s.get("name", "Untitled")

                    task_count = sum(1 for t in all_tasks
                                     if t.get("columnId") == sid
                                     and t.get("status", 0) == 0
                                     and not t.get("parentId"))

                    link  = f"ticktick:///webapp/#p/{pid}/tasks/{sid}"
                    title = f"{sname} | {pname}"

                    items.append(alfred.item(
                        uid=f"section-{sid}",
                        title=title,
                        subtitle=build_subtitle(task_count, "Sect", "Task", actions=True),
                        arg=f"open:{link}",
                        mods={
                            "alt":     {"arg": "",             "subtitle": "Browse tasks"},
                            "alt+cmd": {"arg": f"copy:{link}", "subtitle": "Copy link to section"},
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
        if scope in (None, "task", "subtask", "all_tasks"):
            for t in [t for t in all_tasks if t.get("status", 0) == 0]:
                if t.get("kind") == "NOTE": continue   # notes rendered in their own section
                is_subtask = bool(t.get("parentId"))
                if scope == "task"    and is_subtask:     continue
                if scope == "subtask" and not is_subtask: continue

                tid  = t["id"]
                pid  = t.get("projectId") or t.get("_projectId", "")
                name = t.get("title", "Untitled")

                breadcrumb = get_task_breadcrumb(t, task_by_id)
                sub_count  = sum(1 for s in all_tasks
                                 if s.get("parentId") == tid and s.get("status", 0) == 0)

                link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

                items.append(alfred.item(
                    title=build_title(t),
                    subtitle=build_subtitle(sub_count, "Task", breadcrumb=breadcrumb, actions=True),
                    arg=f"open:{link}",
                    mods={
                        "cmd":     {"arg": "",                              "subtitle": "Actions"},
                        "shift":   {"arg": f"complete:{pid}:{tid}:{name}",  "subtitle": "Complete task"},
                        "alt":     {"arg": "",                              "subtitle": "Browse subtasks"},
                        "alt+cmd": {"arg": f"copy:{link}",                 "subtitle": "Copy link to task"},
                        "ctrl":    {"arg": "",                              "subtitle": "Change attributes"},
                    },
                    variables={
                        "item_type":    "task",
                        "task_id":      tid,
                        "task_title":   name,
                        "task_list_id": pid,
                        "search_name":  name,
                        "type_rank":    2 + depths.get(tid, 0),
                    },
                ))

        # ── Notes ─────────────────────────────────────────────────────────────
        # n  = search by title (title field = note name | folder)
        # nc = search by content (title field = content snippet, subtitle = note name · folder)
        if scope in (None, "note", "note_content"):
            # Prefer the dedicated all_notes cache (has content for nc search).
            # Fall back to all_tasks filtered by kind=="NOTE" — covers inbox notes
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
                nfolder  = n.get("_projectName", "")
                ncontent = (n.get("content") or "").strip()
                snippet  = ncontent[:120].replace("\n", " ") if ncontent else ""
                link     = f"ticktick:///webapp/#p/{npid}/tasks/{nid}"

                if scope == "note_content":
                    # Content mode: content preview in title, name · folder as breadcrumb
                    title       = snippet if snippet else ntitle
                    crumb       = f"{ntitle} · {nfolder}" if nfolder else ntitle
                    subtitle    = build_subtitle(0, "Note", breadcrumb=crumb, actions=True)
                    search_name = ncontent
                else:
                    # Title mode (default): note name in title, folder as breadcrumb
                    title       = ntitle
                    subtitle    = build_subtitle(0, "Note", breadcrumb=nfolder, actions=True)
                    search_name = f"{ntitle} {nfolder}"

                items.append(alfred.item(
                    uid=f"note-{nid}",
                    title=title,
                    subtitle=subtitle,
                    arg=f"open:{link}",
                    mods={
                        "ctrl":    {"arg": "", "subtitle": "Change attributes"},
                        "alt+cmd": {"arg": f"copy:{link}", "subtitle": "Copy link to note"},
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

        if query:
            items = fuzz.filter_and_score(
                query, items,
                key_fn=lambda x: search_key(x.get("variables", {}).get("search_name", x["title"])),
            )

            # ── Grouped sort ─────────────────────────────────────────────────
            # Tag each item with its position after fuzzy scoring (lower = better)
            for i, item in enumerate(items):
                item["_pos"] = i

            # Resolve the list every item belongs to
            def item_list_id(item):
                v = item.get("variables", {})
                return v.get("list_id") or v.get("task_list_id") or "__unknown__"

            # Build groups preserving fuzzy order within each group
            from collections import defaultdict
            groups = defaultdict(list)
            for item in items:
                groups[item_list_id(item)].append(item)

            # Within each group: hierarchy first, then fuzzy score
            for gid in groups:
                groups[gid].sort(key=lambda x: (
                    x.get("variables", {}).get("type_rank", 99),
                    x["_pos"],
                ))

            # Order groups by: best type_rank in group → best fuzzy position
            def group_sort_key(gid):
                g = groups[gid]
                return (
                    min(x.get("variables", {}).get("type_rank", 99) for x in g),
                    min(x["_pos"] for x in g),
                )

            sorted_gids = sorted(groups, key=group_sort_key)
            items = [item for gid in sorted_gids for item in groups[gid]]

            # Clean up temp field
            for item in items:
                item.pop("_pos", None)

        if not items:
            items.append(alfred.item(
                title=f'No results matching "{query}"' if query else "No data — run sync first",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
