"""tagtree.py — parent→children tag relations from the v2 tags cache.

`tags_tree` (cached by sync.py via api_v2.get_tags) is the raw /api/v2/tags
list: [{name, label, parent, …}] — the open API has no tag endpoint. Parent
tags (🎩Area, 🔥CRM, 🏁Status…) are organisational — not meant to be assigned to
tasks directly — so the pickers turn them into drill rows: ⏎ on a parent shows
its children.
"""
import cache as cache_store


def _tree():
    return cache_store.get("tags_tree") or []


def parent_names():
    """Lowercase names of tags that actually have children."""
    return {(t.get("parent") or "").lower() for t in _tree()} - {""}


def is_parent(name):
    return (name or "").lower().lstrip("#") in parent_names()


def children_of(name):
    """Child tag names (stored lowercase form) for a parent name/label, ci."""
    n = (name or "").lower().lstrip("#")
    return [t.get("name") or t.get("label") for t in _tree()
            if (t.get("parent") or "").lower() == n]


def parent_labels():
    """Display labels of the parent tags (those with children)."""
    ps = parent_names()
    return [t.get("label") or t.get("name") for t in _tree()
            if (t.get("name") or "").lower() in ps]


def top_level_labels(fallback=None):
    """Labels of tags WITHOUT a parent — the only legal nest targets
    (TickTick nests one level). Falls back to the given list (or [])
    when no tree is cached."""
    tree = _tree()
    if not tree:
        return list(fallback or [])
    return [t.get("label") or t.get("name") for t in tree
            if not t.get("parent")]
