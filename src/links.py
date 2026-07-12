"""Extract openable links (any scheme) from text.

Shared by the ⌘ Actions menu (to gate the "Open link" row so it only shows when
the item actually has a link) and by open_links.py (the picker). Markdown links
of any target and bare URIs of any scheme (obsidian://, file://, ticktick://,
things://, https://…) are recognised — anything macOS `open` can handle.
"""
import re

# Markdown links — angle form (target may contain spaces/parens) and plain form.
MD_ANGLE = re.compile(r'\[([^\]]*)\]\(\s*<\s*([^>]+?)\s*>\s*\)')
MD_PLAIN = re.compile(r'\[([^\]]*)\]\(\s*([^)\s]+?)\s*\)')
# Bare URIs of any scheme. Lookbehind drops "](" / "(<" lead-ins and mid-word
# matches; the dedup below is the real guard against double-capture.
BARE_URI = re.compile(r'(?<![\w(<])[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s)>\]]+')
_SCHEME  = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*:')


def _openable(target):
    """A real URI (foo://…, mailto:, things:…) or a local file path — i.e.
    something `open` can handle. Filters out non-link markdown targets like (bar)."""
    return bool(_SCHEME.match(target)) or target.startswith(('/', '~'))


def extract_links(text):
    """Return [(label, target)] for markdown + bare links of any scheme,
    deduped, in document order."""
    if not text:
        return []
    found = {}  # target -> (position, label) — first occurrence wins
    for pat, labelled in ((MD_ANGLE, True), (MD_PLAIN, True), (BARE_URI, False)):
        for m in pat.finditer(text):
            if labelled:
                label, target = m.group(1).strip(), m.group(2).strip()
            else:
                target = m.group(0).rstrip('.,;')
                label = target
            if _openable(target) and target not in found:
                found[target] = (m.start(), label or target)
    return [(lbl, tgt) for tgt, (_pos, lbl) in
            sorted(found.items(), key=lambda kv: kv[1][0])]


def has_link(text):
    """Fast boolean — does the text contain at least one openable link?"""
    return bool(extract_links(text))
