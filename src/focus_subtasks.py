"""focus_subtasks.py - pure model helpers for the subtask-based focus flow.

Focus revamp (2026-07-21, Vex ruling): staged tasks are literal SUBTASKS of
the focus task - moved under it, not checkbox-linked into its description.
This module is the pure side: summaries, cycle guards, ordering math, record
notes. All I/O (API calls, ledger file, cache mirrors) lives in xact.py.
The checkbox grammar (focus_blocks.py) survives for NOTE targets and legacy
content only.

API facts the design leans on (live-verified 2026-07-21 on scratch tasks):
  * v1 get_task returns childIds; completed children STAY in it (they stay
    GET-able with status 2 but leave project/data tasks) - so
    done = childIds minus the open children found in project data.
  * v1 full-object update SETS parentId (same project) but silently ignores
    parentId=None - detaching is v2 batch/taskParent
    {taskId, projectId, oldParentId}.
  * v1 move_task keeps a stale cross-project parent link on a moved child -
    ALWAYS detach before moving a child out, move before parenting in.
  * sortOrder is the display order (ascending, periodic-engine convention);
    childIds is creation order - never trust it for display.
"""

SORT_STEP = 65536
RESPREAD = "respread"          # move_order sentinel: midpoint collapsed


def children_summary(open_children, child_ids, done_titles=None):
    """The focus bar / fx_tick model - the EXACT dict shape block_summary
    produced: {done, total, items: [{idx, title, url, tid, pid, checked}],
    date}. open_children: open child task dicts (sorted here by sortOrder
    ascending = app display order). child_ids: the focus task's childIds
    (completed included). Done rows carry a title only when done_titles
    ({tid: title}) knows one - the bar renders unchecked rows and counts,
    so blank done titles cost nothing."""
    open_sorted = sorted(open_children or [],
                         key=lambda t: t.get("sortOrder") or 0)
    open_ids = {t.get("id") for t in open_sorted}
    done_ids = [c for c in (child_ids or []) if c not in open_ids]
    items = []
    idx = 0
    for t in open_sorted:
        idx += 1
        pid = t.get("projectId") or t.get("_projectId", "")
        items.append({"idx": idx, "title": t.get("title", ""),
                      "url": f"https://ticktick.com/webapp/#p/{pid}/tasks/{t.get('id')}",
                      "tid": t.get("id"), "pid": pid, "checked": False})
    for c in done_ids:
        idx += 1
        items.append({"idx": idx, "title": (done_titles or {}).get(c, ""),
                      "url": None, "tid": c, "pid": "", "checked": True})
    return {"done": len(done_ids), "total": len(items), "items": items,
            "date": None}


def would_cycle(focus_tid, candidate_tid, lookup):
    """True when parenting candidate under focus would loop: the candidate
    IS the focus task or one of its ANCESTORS. lookup: tid -> task dict or
    None. Bounded walk - corrupt parent chains must not hang the picker."""
    if not candidate_tid:
        return False
    cur = focus_tid
    for _ in range(20):
        if not cur:
            return False
        if cur == candidate_tid:
            return True
        cur = (lookup(cur) or {}).get("parentId")
    return False


def stage_orders(existing_orders, n):
    """sortOrders appending n staged items at the BOTTOM of the child list
    (ascending display), in staging order - first staged sits above the
    later ones, matching the old first-buffered-first-checkbox promise."""
    base = (max(existing_orders) if existing_orders else 0) + SORT_STEP
    return [base + i * SORT_STEP for i in range(n)]


def move_order(orders, pos, direction):
    """New sortOrder for the item at index pos of an ASCENDING orders list.
    up/down = one slot (midpoint insertion), top/bottom = past the edge.
    Returns the int, None (already at the edge / unknown direction), or
    RESPREAD when the midpoint gap collapsed (caller re-spreads all)."""
    n = len(orders)
    if pos < 0 or pos >= n:
        return None

    def mid(a, b):
        return RESPREAD if b - a < 2 else (a + b) // 2

    if direction == "up":
        if pos == 0:
            return None
        return orders[0] - SORT_STEP if pos == 1 else mid(orders[pos - 2],
                                                          orders[pos - 1])
    if direction == "down":
        if pos == n - 1:
            return None
        return (orders[-1] + SORT_STEP if pos == n - 2
                else mid(orders[pos + 1], orders[pos + 2]))
    if direction == "top":
        return None if pos == 0 else orders[0] - SORT_STEP
    if direction == "bottom":
        return None if pos == n - 1 else orders[-1] + SORT_STEP
    return None


def respread(n, anchor=0):
    """Fresh ascending orders after a midpoint collapse."""
    return [anchor + (i + 1) * SORT_STEP for i in range(n)]


def record_note(date, entries):
    """The focus record's note - the children snapshot at stop time,
    today_note's successor. entries: [(title, checked)] in display order.
    '' when there is nothing to tell."""
    if not entries:
        return ""
    lines = ["### " + date]
    for title, checked in entries:
        clean = " ".join((title or "(untitled)").split())
        lines.append(("- [x] " if checked else "- [ ] ") + clean)
    return "\n".join(lines)
