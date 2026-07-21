"""
filtering.py - shared filter-matching engine.

Home of the filters_config.py matcher so BOTH the search inline view
(everything_search.py `f ` scope) and browse.py (ctx:filter:<index>) can use
it. Extracted from filter_view.py, which was unsafe to import: it monkey-
patches alfred.output at import time and can sys.exit on import failure.

Pure logic - no Alfred I/O here.
"""
import calendar
import json
import sys
from datetime import datetime, timedelta, timezone

from script_base import WORKFLOW_DIR


# ── Date helpers ──────────────────────────────────────────────────────────────
def utc_str_to_local_date(date_str):
    if not date_str:
        return ""
    try:
        clean = date_str[:19]
        dt_utc = datetime(
            int(clean[0:4]), int(clean[5:7]), int(clean[8:10]),
            int(clean[11:13]), int(clean[14:16]), int(clean[17:19]),
            tzinfo=timezone.utc,
        )
        return dt_utc.astimezone().strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10]


def task_local_date(task):
    return utc_str_to_local_date(task.get("startDate") or task.get("dueDate") or "")


# ── Smart lists (single source - browse.py and everything_search.py import) ──
SMART_LABELS = {
    "today":     "Today",
    "tomorrow":  "Tomorrow",
    "next7days": "Next 7 Days",
    "overdue":   "Overdue",
}


def smart_filter(all_tasks, smartlist):
    today    = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    in7days  = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    incomplete = [t for t in all_tasks
                  if t.get("status", 0) == 0 and not t.get("parentId")]

    if smartlist == "today":
        return [t for t in incomplete if task_local_date(t) == today]
    elif smartlist == "tomorrow":
        return [t for t in incomplete if task_local_date(t) == tomorrow]
    elif smartlist == "next7days":
        tasks = [t for t in incomplete if today <= task_local_date(t) <= in7days]
        return sorted(tasks, key=lambda t: task_local_date(t))
    elif smartlist == "overdue":
        # day-level: strictly before today (today's timed tasks are today's
        # business); dateless excluded ("" would sort before any date), notes
        # carry dates as metadata, not obligations
        tasks = [t for t in incomplete
                 if t.get("kind") != "NOTE"
                 and (task_local_date(t) or "~") < today]
        return sorted(tasks, key=lambda t: task_local_date(t))
    return []


# ── Config access ─────────────────────────────────────────────────────────────
def load_filters():
    """Native TickTick filters first (synced + translated → cache key
    filters_v2 - zero setup), filters_config.py as the tokenless /
    power-user fallback. [] if neither exists."""
    try:
        import cache as cache_store
        v2 = cache_store.get("filters_v2")
        if v2:
            return v2
    except Exception:
        pass
    if WORKFLOW_DIR not in sys.path:
        sys.path.insert(0, WORKFLOW_DIR)
    try:
        from filters_config import FILTERS
        return FILTERS
    except Exception:
        return []


# ── Native-rule translator ────────────────────────────────────────────────────
# TickTick rule JSON: {"type":0|1,"and":[cond,…]} (or a top-level "or"), each
# cond {"conditionType":1,"or":[values],"conditionName":…}. We express what the
# engine speaks and mark the rest: dropped clauses → _partial, nothing at
# all → _unsupported (the row still lists, honestly labelled).
_DUE_TOKENS = {"overdue": "overdue", "today": "today", "tomorrow": "tomorrow",
               "next7days": "next7days", "thisweek": "this_week",
               "nextweek": "next_week", "thismonth": "this_month",
               "nextmonth": "next_month", "nodate": "no_date"}
_PRIO_API_TO_CFG = {0: 0, 1: 1, 3: 2, 5: 3}


def _translate_clause(cond, out, projects_by_group):
    """One rule clause → keys on out. Returns False when (part of) the clause
    couldn't be expressed."""
    if not isinstance(cond, dict):
        return False
    name = cond.get("conditionName")
    # operator matters: "or" = any-of, "and" = all-of - never conflate them
    is_and = False
    vals = cond.get("or")
    if not vals:
        vals = cond.get("and") or []
        is_and = bool(vals)
    if cond.get("conditionType") != 1 or not vals:
        return False
    ok = True
    if name == "tag":
        strs = [v for v in vals if isinstance(v, str)]
        ok = len(strs) == len(vals)
        if is_and or len(strs) == 1:
            # all-of (or a single value) → the AND-semantics `tags` key
            out.setdefault("tags", []).extend(strs)
        elif strs:
            if "any_tags" in out:
                ok = False          # a second OR-group is inexpressible
            else:
                out["any_tags"] = strs
    elif name in ("list", "listOrGroup"):
        for v in vals:
            if isinstance(v, dict):
                sub = v.get("or") or []
                if v.get("conditionName") == "list":
                    out.setdefault("project_ids", []).extend(
                        x for x in sub if isinstance(x, str))
                elif v.get("conditionName") in ("group", "groupId", "projectGroup"):
                    hit = False
                    for gid in sub:
                        for pid in projects_by_group.get(gid, []):
                            out.setdefault("project_ids", []).append(pid)
                            hit = True
                    ok = ok and hit
                else:
                    ok = False
            elif isinstance(v, str):
                out.setdefault("project_ids", []).append(v)
            else:
                ok = False
    elif name == "keywords":
        strs = [v for v in vals if isinstance(v, str)]
        ok = len(strs) == len(vals) and not (is_and and len(strs) > 1)
        if strs:                    # all-of keywords degrade to any-of (+⚠)
            out["include"] = strs
    elif name == "dueDate":
        mapped = [_DUE_TOKENS[v] for v in vals if v in _DUE_TOKENS]
        ok = len(mapped) == len(vals) and bool(mapped)
        if mapped:
            out["due"] = mapped if len(mapped) > 1 else mapped[0]
    elif name == "priority":
        mapped = [_PRIO_API_TO_CFG.get(v, v) for v in vals if isinstance(v, int)]
        ok = len(mapped) == len(vals) and bool(mapped)
        if mapped:                  # never emit [] - it would match nothing
            out["priority"] = mapped
    else:
        return False
    return ok


def translate_native(raw_filters, projects):
    """[{name, rule, sortOrder}, …] from the v2 sync payload → a FILTERS list
    in sidebar order. Untranslatable pieces degrade honestly (_partial /
    _unsupported) instead of lying."""
    projects_by_group = {}
    for p in (projects or []):
        gid = p.get("groupId")
        if gid:
            projects_by_group.setdefault(gid, []).append(p["id"])
    out = []
    for rf in sorted(raw_filters or [], key=lambda x: x.get("sortOrder") or 0):
        f = {"name": rf.get("name") or "Filter"}
        # per-filter isolation: ONE odd rule shape must never freeze the
        # whole filters_v2 refresh - it degrades to _unsupported instead
        try:
            rule = json.loads(rf.get("rule") or "{}")
            if not isinstance(rule, dict):
                rule = {}
            clauses = rule.get("and") or []
            partial = False
            if not clauses and rule.get("or"):
                # top-level "match any": only a pure tag-OR is expressible
                conds = [c for c in rule["or"] if isinstance(c, dict)]
                if conds and all(c.get("conditionName") == "tag" for c in conds):
                    merged = [v for c in conds for v in (c.get("or") or [])
                              if isinstance(v, str)]
                    if merged:
                        f["any_tags"] = merged
                else:
                    partial = True
            for cond in clauses:
                if not _translate_clause(cond, f, projects_by_group):
                    partial = True
        except Exception:
            f = {"name": rf.get("name") or "Filter"}
            partial = False
        if len(f) == 1:                       # nothing translated
            f["_unsupported"] = True
        elif partial:
            f["_partial"] = True
        out.append(f)
    return out


def filter_criteria_summary(f):
    """One-line human summary of a filter's criteria (from filters_list.py)."""
    parts = []
    if f.get("include"):
        inc = f["include"]
        inc = [inc] if isinstance(inc, str) else inc
        parts.append("title has " + " / ".join(f"“{k}”" for k in inc))
    if f.get("tags"):
        t = f["tags"]
        if isinstance(t, list):
            parts.append("tags (all): " + ", ".join(t))
        else:
            parts.append(f"tags: {t}")
    if f.get("any_tags"):
        parts.append("tags (any): " + ", ".join(f["any_tags"]))
    if f.get("priority"):
        labels = {0: "none", 1: "low", 2: "medium", 3: "high"}   # config scale
        parts.append("priority: " + ", ".join(labels.get(p, str(p)) for p in f["priority"]))
    if f.get("projects"):
        parts.append("lists: " + ", ".join(f["projects"]))
    if f.get("project_ids"):
        n = len(f["project_ids"])
        parts.append(f"{n} list{'s' if n != 1 else ''}")
    if f.get("due"):
        d = f["due"]
        parts.append("due " + (" / ".join(d) if isinstance(d, list) else d))
    if f.get("due_before"):
        parts.append(f"due before {f['due_before']}")
    if f.get("due_after"):
        parts.append(f"due after {f['due_after']}")
    if f.get("no_date"):
        parts.append("no date")
    if f.get("_unsupported"):
        parts.append("⚠ rule not supported yet")
    elif f.get("_partial"):
        parts.append("⚠ part of the rule ignored")
    return "  ".join(parts)


# ── Filter matching ───────────────────────────────────────────────────────────
def _expand_tags(tag_list):
    """{lowercase tags} with parent tags expanded to their children - TickTick
    filter semantics (a filter on a parent tag also matches its children). Uses the
    tags_tree cache via tagtree; falls back to the literal tags."""
    out = set()
    try:
        import tagtree
        for t in tag_list:
            out.add(t.lower())
            for kid in (tagtree.children_of(t) or []):
                out.add(kid.lower())
    except Exception:
        out = {t.lower() for t in tag_list}
    return out


def matches(task, f, project_name_to_id):
    # A filter whose rule didn't translate must show NOTHING, not everything -
    # the picker row carries the ⚠ subtitle, the drill stays honest too.
    if f.get("_unsupported"):
        return False

    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    next7    = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    next14   = (now + timedelta(days=14)).strftime("%Y-%m-%d")

    # Week boundaries (Mon-Sun)
    wd = now.weekday()
    week_start      = (now - timedelta(days=wd)).strftime("%Y-%m-%d")
    week_end        = (now + timedelta(days=6 - wd)).strftime("%Y-%m-%d")
    next_week_start = (now + timedelta(days=7 - wd)).strftime("%Y-%m-%d")
    next_week_end   = (now + timedelta(days=13 - wd)).strftime("%Y-%m-%d")

    # Month boundaries
    month_start     = now.replace(day=1).strftime("%Y-%m-%d")
    month_end       = now.replace(day=calendar.monthrange(now.year, now.month)[1]).strftime("%Y-%m-%d")
    nm_year         = now.year + (1 if now.month == 12 else 0)
    nm_month        = 1 if now.month == 12 else now.month + 1
    next_month_start = datetime(nm_year, nm_month, 1).strftime("%Y-%m-%d")
    next_month_end   = datetime(nm_year, nm_month, calendar.monthrange(nm_year, nm_month)[1]).strftime("%Y-%m-%d")

    DATE_MAP = {"today": today, "tomorrow": tomorrow, "next7days": next7, "next14days": next14}

    # Include - title must contain the string; a LIST means any-of (native
    # "keywords" clauses carry multiple values)
    if f.get("include"):
        inc = f["include"]
        inc = [inc] if isinstance(inc, str) else inc
        title_l = task.get("title", "").lower()
        if not any(str(k).lower() in title_l for k in inc):
            return False

    # Tags - ALL must match
    tags_filter = f.get("tags")
    if tags_filter is not None:
        task_tags = [tg.lower() for tg in (task.get("tags") or [])]
        if tags_filter == "untagged":
            if task_tags:
                return False
        elif tags_filter == "any":
            if not task_tags:
                return False
        elif tags_filter == "any_or_untagged":
            pass  # no filtering - tagged or untagged both pass
        elif isinstance(tags_filter, list):
            # each required tag matches itself OR any of its children
            if not all(set(task_tags) & _expand_tags([tag]) for tag in tags_filter):
                return False

    # Any tags - at least ONE must match (parents expand to children)
    any_tags_filter = f.get("any_tags")
    if any_tags_filter is not None:
        task_tags = [tg.lower() for tg in (task.get("tags") or [])]
        if not (set(task_tags) & _expand_tags(any_tags_filter)):
            return False

    # Priority - config uses 0=none, 1=low, 2=medium, 3=high, "any"=all
    # mapped to TickTick API values: 0→0, 1→1, 2→3, 3→5
    priority_filter = f.get("priority")
    if priority_filter is not None and priority_filter != "any":
        PMAP = {0: 0, 1: 1, 2: 3, 3: 5}
        api_priorities = {PMAP.get(p, p) for p in priority_filter}
        if task.get("priority", 0) not in api_priorities:
            return False

    # Projects - "any" skips filter, otherwise match by name
    if f.get("projects") and f["projects"] != "any":
        project_ids = {project_name_to_id.get(n.lower()) for n in f["projects"]}
        if task.get("_projectId") not in project_ids:
            return False

    # Project ids - direct id match (native "list"/"listOrGroup" clauses;
    # rename-proof where names are not). Checks BOTH ids: inbox tasks carry
    # the normalized _projectId "inbox" while the rule stores the real
    # "inbox<uid>" projectId.
    if f.get("project_ids"):
        if not ({task.get("_projectId"), task.get("projectId")}
                & set(f["project_ids"])):
            return False

    # Due date filters
    d = task_local_date(task)
    if f.get("due_before"):
        cutoff = DATE_MAP.get(f["due_before"], f["due_before"])
        if not d or d > cutoff:
            return False
    if f.get("due_after"):
        cutoff = DATE_MAP.get(f["due_after"], f["due_after"])
        if not d or d < cutoff:
            return False
    if f.get("no_date"):
        if d:
            return False

    # Shorthand due field - a LIST means any-of (native "dueDate"
    # clauses OR their values, e.g. overdue-or-today)
    due = f.get("due")
    if due and due != "all":
        def _due_ok(v):
            if v == "overdue":
                return bool(d) and d < today
            if v == "today":
                return d == today
            if v == "tomorrow":
                return d == tomorrow
            if v == "next7days":
                return bool(d) and today <= d <= next7
            if v == "this_week":
                return bool(d) and week_start <= d <= week_end
            if v == "next_week":
                return bool(d) and next_week_start <= d <= next_week_end
            if v == "this_month":
                return bool(d) and month_start <= d <= month_end
            if v == "next_month":
                return bool(d) and next_month_start <= d <= next_month_end
            if v == "no_date":
                return not d
            return True                      # unknown token → don't reject
        due_vals = due if isinstance(due, list) else [due]
        if not any(_due_ok(v) for v in due_vals):
            return False

    return True


def matching_tasks(f, all_tasks, projects):
    """Incomplete top-level tasks matching filter f (the filter_view pipeline)."""
    project_name_to_id = {p["name"].lower(): p["id"] for p in projects}
    candidates = [t for t in all_tasks
                  if t.get("status", 0) == 0 and not t.get("parentId")]
    return [t for t in candidates if matches(t, f, project_name_to_id)]
