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

import re

SORT_STEP = 65536
RESPREAD = "respread"          # move_order sentinel: midpoint collapsed
MAX_DEPTH = 4                  # descendants() default reach (TickTick nests ~4)


def descendants(tasks, root_tid, max_depth=MAX_DEPTH):
    """Every task under root_tid, DFS in DISPLAY order (siblings by
    sortOrder ascending, a child right after its parent), each a shallow
    copy stamped _depth (1 = direct child) and _dfs (its display ordinal -
    display_key sorts on it). tasks: any task-dict pool (project data, the
    cache); the caller filters status. Cycle-safe (a corrupt parent loop
    visits each id once) and depth-capped (2026-09-09: fx_tick / the bar /
    the picker used to see direct children only - grandchildren staged
    app-side were invisible)."""
    if not root_tid:
        return []
    kids = {}
    for t in tasks or []:
        p = t.get("parentId")
        if p:
            kids.setdefault(p, []).append(t)
    out, seen = [], {root_tid}

    def walk(pid, depth):
        if depth > max_depth:
            return
        for t in sorted(kids.get(pid, []), key=lambda t: t.get("sortOrder") or 0):
            tid = t.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append(dict(t, _depth=depth, _dfs=len(out)))
            walk(tid, depth + 1)

    walk(root_tid, 1)
    return out


def display_key(t):
    """Sort key for a child list: the DFS ordinal when descendants() stamped
    one, sortOrder otherwise (a flat direct-children list)."""
    return (t.get("_dfs", 0), t.get("sortOrder") or 0)


def children_summary(open_children, child_ids, done_titles=None):
    """The focus bar / fx_tick model - the EXACT dict shape block_summary
    produced: {done, total, items: [{idx, title, url, tid, pid, checked,
    depth}], date}. open_children: open child task dicts (sorted here by
    display_key - descendants() DFS order when stamped, else sortOrder
    ascending = app display order; depth = _depth, 1 when unstamped).
    child_ids: the focus task's childIds (completed included). Done rows
    carry a title only when done_titles ({tid: title}) knows one - the bar
    renders unchecked rows and counts, so blank done titles cost nothing."""
    open_sorted = sorted(open_children or [], key=display_key)
    open_ids = {t.get("id") for t in open_sorted}
    done_ids = [c for c in (child_ids or []) if c not in open_ids]
    items = []
    idx = 0
    for t in open_sorted:
        idx += 1
        pid = t.get("projectId") or t.get("_projectId", "")
        items.append({"idx": idx, "title": t.get("title", ""),
                      "url": f"https://ticktick.com/webapp/#p/{pid}/tasks/{t.get('id')}",
                      "tid": t.get("id"), "pid": pid, "checked": False,
                      "depth": t.get("_depth", 1)})
    for c in done_ids:
        idx += 1
        items.append({"idx": idx, "title": (done_titles or {}).get(c, ""),
                      "url": None, "tid": c, "pid": "", "checked": True,
                      "depth": 1})
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


# ── drag-drop reorder (focus bar grip, Vex 2026-09-10) ───────────────────────
def order_at(orders, pos, tgt):
    """New sortOrder moving the item at index pos of an ASCENDING orders
    list to index tgt of the list WITHOUT it (0..n-1) - the drag-drop form
    of move_order (up/down/top/bottom are tgt pos-1/pos+1/0/n-1). None when
    nothing moves, RESPREAD when the midpoint gap collapsed."""
    n = len(orders)
    if not (0 <= pos < n and 0 <= tgt < n) or tgt == pos:
        return None
    rest = orders[:pos] + orders[pos + 1:]
    prev = rest[tgt - 1] if tgt > 0 else None
    nxt = rest[tgt] if tgt < len(rest) else None
    if prev is None:
        return nxt - SORT_STEP
    if nxt is None:
        return prev + SORT_STEP
    return RESPREAD if nxt - prev < 2 else (prev + nxt) // 2


def _subtree_end(items, k):
    """Index just past items[k]'s contiguous subtree in a DFS display list
    (the rows after it that sit deeper)."""
    d = items[k].get("depth", 1)
    j = k + 1
    while j < len(items) and items[j].get("depth", 1) > d:
        j += 1
    return j


def _parents(items):
    """Each row's parent tid, inferred from DFS order + depth (children_summary
    carries depth, not parentId): the nearest earlier row one level up;
    None = a direct child of the focus task."""
    out, stack = [], []
    for t in items:
        d = t.get("depth", 1)
        while stack and stack[-1][0] >= d:
            stack.pop()
        out.append(stack[-1][1] if stack else None)
        stack.append((d, t.get("tid")))
    return out


def sibling_gaps(items, i):
    """Drop gaps for dragging items[i] in a DFS display list: [(g, tgt)] -
    g = the flat row index the drop line sits ABOVE (len(items) = below the
    last row), tgt = the sibling slot without the dragged item (order_at /
    xact fx_move at:<tgt>). ONLY its own siblings take it: sortOrder ranks
    siblings, so a drop never reparents. The two gaps hugging the item map
    to its own slot (a no-op drop)."""
    if not (0 <= i < len(items)):
        return []
    par = _parents(items)
    sibs = [k for k in range(len(items)) if par[k] == par[i]]
    p = sibs.index(i)
    gaps = [(k, n if n <= p else n - 1) for n, k in enumerate(sibs)]
    gaps.append((_subtree_end(items, sibs[-1]), len(sibs) - 1))
    return gaps


def open_rows(items):
    """The bar's live rows: unchecked items MINUS every row inside a checked
    row's subtree (depth contiguity). A ticked parent's open children drop
    out of reach on the next poll (descendants() walks open parents only),
    so the bar hides them now - left in, _parents re-homed them under the
    wrong parent and a drag wrote the wrong slot (drag review 2026-09-10)."""
    out, skip_d = [], None
    for it in items or []:
        d = it.get("depth", 1)
        if skip_d is not None:
            if d > skip_d:
                continue
            skip_d = None
        if it.get("checked"):
            skip_d = d
            continue
        out.append(it)
    return out


# ── row links + folding (the bar's right-hand icons, 2026-09-12) ────────────
# A routine's steps carry their automation in the TITLE as markdown
# ("[Startup • Start](kmtrigger://macro=...)"), so the bar needs the target,
# not the rendered text (display.md_links_display turns it into "[name]🔗").
_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)\s*\)")
_BARE_URL = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s)\]]+", re.I)
_SCHEME = re.compile(r"[a-z][a-z0-9+.\-]*:", re.I)
_BLOCKED = ("javascript:", "data:", "vbscript:")


def title_link(title):
    """The URL a task title carries: its FIRST markdown link's target, else a
    bare scheme://... in the text, else None. A target without a scheme is
    not openable, so it comes back None; javascript:/data:/vbscript: never
    come back at all (a title can arrive from a shared list)."""
    s = title or ""
    m = _MD_LINK.search(s)
    url = m.group(1) if m else None
    if not url:
        b = _BARE_URL.search(s)
        url = b.group(0).rstrip(".,;") if b else None
    if not url or not _SCHEME.match(url):
        return None
    return None if url.lower().startswith(_BLOCKED) else url


def kid_tids(rows):
    """The tids in a DFS row list that HAVE a subtree (the next row is
    deeper). Read it off the unfolded list: a folded row's children are gone
    from the folded one, and its chevron would vanish with them."""
    out = set()
    for i, it in enumerate(rows or []):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt and nxt.get("depth", 1) > it.get("depth", 1) and it.get("tid"):
            out.add(it["tid"])
    return out


def fold_rows(rows, folded):
    """rows minus every row inside a FOLDED row's subtree - open_rows' depth
    contiguity, one level up: the folded row itself stays (it carries the
    chevron), its descendants go. folded: a tid container."""
    folded = folded or ()
    out, skip_d = [], None
    for it in rows or []:
        d = it.get("depth", 1)
        if skip_d is not None:
            if d > skip_d:
                continue
            skip_d = None
        out.append(it)
        if it.get("tid") in folded:
            skip_d = d
    return out


def drop_anchor(rest, tgt):
    """A drop as an ANCHOR, not a slot: ('after', tid) of the sibling it
    lands after, or ('before', tid) for the top slot. rest = sibling tids
    WITHOUT the mover, in display order. A bar list gone stale between
    polls can then never land the row somewhere the line didn't show."""
    if tgt <= 0:
        return ("before", rest[0]) if rest else ("at", "0")
    return ("after", rest[min(tgt, len(rest)) - 1])


def anchor_slot(rest, kind, anchor):
    """Server side of drop_anchor: slot k in rest (the server's siblings
    WITHOUT the mover, sortOrder ascending - order_at's tgt), or None when
    the anchor is no longer a sibling (the list changed)."""
    if anchor not in rest:
        return None
    k = rest.index(anchor)
    return k + 1 if kind == "after" else k


def move_block(items, i, g):
    """items with items[i] AND its subtree moved to flat gap g (sibling_gaps'
    g, original indexing) - the bar's optimistic local reorder. A gap inside
    or hugging the block moves nothing."""
    j = _subtree_end(items, i)
    if i <= g <= j:
        return list(items)
    block = items[i:j]
    rest = items[:i] + items[j:]
    at = g if g < i else g - (j - i)
    return rest[:at] + block + rest[at:]


# ── drag-to-reparent (focus bar grip, Vex 2026-09-13) ───────────────────────
# "make a task a subtask of another task in focus bar by dragging ... to the
# right and holding over a task we want to be a parent task". The reorder
# drag above stays sibling-only; dragging RIGHT switches the same gesture to
# nesting. Rows are addressed by TID here, not index: the bar hit-tests the
# FOLDED visible list but must reason about the UNFOLDED one (a folded row
# still carries its hidden subtree along).
ROOT = ""        # the focus task itself as a drop target: the bar's header row


def reparent_targets(items, tid, max_depth=MAX_DEPTH):
    """The tids that may ADOPT the row `tid` together with its subtree, plus
    ROOT for the focus task. items: the bar's UNFOLDED open rows (DFS,
    depth-stamped).

    Refused: the row itself and its own subtree (a cycle), its CURRENT parent
    (a no-op the bar should not flare for), and any parent under which the
    moved subtree would sink past max_depth - descendants() stops reading
    there, so the row would silently vanish from the bar after the move.
    """
    i = next((k for k, x in enumerate(items or []) if x.get("tid") == tid), None)
    if i is None:
        return set()
    par = _parents(items)
    j = _subtree_end(items, i)
    d0 = items[i].get("depth", 1)
    height = max(items[k].get("depth", 1) for k in range(i, j)) - d0
    out = set()
    if par[i] is not None and 1 + height <= max_depth:
        out.add(ROOT)
    for k, t in enumerate(items):
        if i <= k < j or not t.get("tid") or t.get("tid") == par[i]:
            continue
        if t.get("depth", 1) + 1 + height > max_depth:
            continue
        out.add(t["tid"])
    return out


def reparent_block(items, tid, target):
    """items with row `tid` and its subtree moved to be the LAST child of
    `target` (ROOT = of the focus task, i.e. the end of the list), depths
    re-based - the bar's optimistic local move, the move_block of nesting.
    An unknown tid/target, or a target inside the moved block, changes
    nothing."""
    items = list(items or [])
    i = next((k for k, x in enumerate(items) if x.get("tid") == tid), None)
    if i is None:
        return items
    j = _subtree_end(items, i)
    if target != ROOT and any(x.get("tid") == target for x in items[i:j]):
        return items
    block = [dict(x) for x in items[i:j]]
    rest = items[:i] + items[j:]
    if target == ROOT:
        new_d, at = 1, len(rest)
    else:
        k = next((n for n, x in enumerate(rest) if x.get("tid") == target), None)
        if k is None:
            return items
        new_d, at = rest[k].get("depth", 1) + 1, _subtree_end(rest, k)
    shift = new_d - block[0].get("depth", 1)
    for x in block:
        x["depth"] = x.get("depth", 1) + shift
    return rest[:at] + block + rest[at:]


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
