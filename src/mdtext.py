"""mdtext.py - the markdown-link text rules (PURE: stdlib only).

ONE rule, learned the hard way twice in a day (2026-09-12): a title that is
ITSELF a markdown link cannot be wrapped in another one. Every routine step
carries its automation in the title, so

    [Money](kmtrigger://macro=X)

put inside a task link becomes

    [[Money](kmtrigger://macro=X)](https://ticktick.com/webapp/#p/…/tasks/…)

a link inside a link. It renders as neither, and it breaks every parser that
reads the form back, because they all match the label with [^]]* and stop at
the first inner bracket.

Three builders already solved this privately (routine_link.markdown,
grab_url.md_link, and the flatten in display.search_key) while three others
did not (the weekly note's ♻️ mirror, the [[ ]] picker, the 📌CTA query).
This module is where the rule lives now.
"""
import re

MD_LINK_RE = re.compile(r"\[([^\[\]]*)\]\([^()]*\)")
_BRACKETS = {ord("["): "(", ord("]"): ")"}


def flatten_links(text):
    """Markdown links reduced to their label: '[a](u) b' -> 'a b'."""
    return MD_LINK_RE.sub(r"\1", text or "")


def link_text(text, limit=None):
    """Text safe to use as a markdown link LABEL: links flattened, then any
    surviving bracket turned into a PAREN and backslashes dropped - a bracket
    would end the label early, a trailing backslash would escape the closing
    one. Parens rather than deletion because a literal bracket is usually
    content, not syntax ("Rebecca • Sleeve [250]" is a price); grab_url.md_link
    has converted them this way all along. `limit` caps the result (trimmed
    again, so a cut never leaves a dangling space)."""
    t = flatten_links(text).translate(_BRACKETS).replace("\\", "").strip()
    return t[:limit].strip() if limit else t


def md_link(text, url, limit=None):
    """A markdown link whose label can neither nest nor break the syntax."""
    return f"[{link_text(text, limit)}]({url})"
