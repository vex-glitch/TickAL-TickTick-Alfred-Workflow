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
