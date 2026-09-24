"""Fuzzy matching for Alfred result filtering."""


def score(query, text):
    """Score how well query matches text. Higher = better. 0 = no match."""
    if not query:
        return 100
    q = query.lower()
    t = text.lower()
    if q == t:
        return 1000
    if t.startswith(q):
        return 900
    if q in t:
        return 800 - t.index(q)
    # Subsequence check: every query char appears in order in text
    qi = ti = 0
    while qi < len(q) and ti < len(t):
        if q[qi] == t[ti]:
            qi += 1
        ti += 1
    if qi == len(q):
        return max(1, 500 - (ti - len(q)))
    return 0


def filter_and_score(query, items, key_fn=None):
    """Return items that fuzzy-match query, sorted best-first."""
    if not query:
        return list(items)
    scored = []
    for it in items:
        text = key_fn(it) if key_fn else str(it)
        s = score(query, text)
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored]


# ── Relevance-first ranking (the main search's sort, shared) ─────────────────
# Vex 2026-09-22: "Task picker when choosing goals does not filter correctly.
# If I type in TickAL, it will first list all the bridge notes etc. Unlike our
# search engine which shows correct items at the top". The pickers ranked by
# score() alone, where "inside the text" is 800 minus the POSITION of the hit,
# so a bridge note NAMED "P • TickAL • …" beat the task "💼 P • TickAL • WF"
# by three characters. The search engine had the sort that fixes it, inline
# in everything_search.main; it lives here now so both read ONE rule.

def strength(query, key):
    """How the query hits the key, best first:
        0 the whole name · 1 at a word start ("test" in "test ⌘V", "Testo")
        2 inside a word ("rest" in "interests") · 3 letters scattered.
    Whitespace runs collapse and case folds on both sides."""
    import re
    q = " ".join((query or "").split()).lower()
    k = " ".join((key or "").split()).lower()
    if k == q:
        return 0
    if re.search(r'(?:^|[^\w])' + re.escape(q), k):
        return 1
    if q in k:
        return 2
    return 3


def rank(query, items, key_fn, order_fn=None):
    """filter_and_score(), then match STRENGTH first and order_fn(item) (a
    tuple: type, depth, priority...) within a strength class. Scatter hits
    are DROPPED whenever any word-or-better hit exists; with none they stay,
    so a typo still finds something. Stable: fuzzy order survives inside each
    (strength, order) group. An empty query returns the items as they came."""
    if not (query or "").strip():
        # a blank bar: nothing to match, so the order function alone ranks
        # (tasks before notes, top-level first) instead of the cache order
        # (review 2026-09-24)
        items = list(items)
        if order_fn:
            items.sort(key=lambda x: tuple(order_fn(x)))
        return items
    items = filter_and_score(query, items, key_fn=key_fn)
    ann = {id(x): (strength(query, key_fn(x)),) + tuple(order_fn(x) if order_fn else ())
           for x in items}
    if any(a[0] <= 1 for a in ann.values()):
        items = [x for x in items if ann[id(x)][0] < 3]
    items.sort(key=lambda x: ann[id(x)])
    return items
