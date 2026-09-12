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


# ── the 🔗 entry grammar (Vex 2026-09-12) ────────────────────────────────────
# "it should take a clipboard and whatever I write should be the description
# part between [] of a markdown link". So: the URL comes from the clipboard,
# the words you type name it. A URL typed in the bar still wins over the
# clipboard - typing one is a louder signal than whatever got copied last.
URL_RE = re.compile(r"(?<![\w@])[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s<>\"')\]]+")
_MD_ONLY_RE = re.compile(r"^\s*\[([^\[\]]*)\]\(([^()\s]+)\)\s*$")


def find_url(text):
    """The first URL in `text`, else None. Any scheme - ticktick://,
    obsidian:// and kmtrigger:// are links Vex pastes as often as https."""
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?") if m else None


def url_name(url):
    """A readable stand-in label when you typed none: the host without www,
    or the scheme's own word for schemes that have no host."""
    if not url:
        return ""
    rest = url.split("://", 1)[1] if "://" in url else url
    host = rest.split("/", 1)[0].split("?", 1)[0]
    host = host.split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    return host or (url.split("://", 1)[0] if "://" in url else url)


def link_entry(typed, clip):
    """(typed words, clipboard) → the text of a 🔗 entry, or None when there
    is nothing to log.

    A clipboard that already holds a markdown link keeps its URL and takes
    your words as the new label. With no URL anywhere this is just text -
    a link entry with nothing to link is still a note worth keeping.
    """
    typed, clip = (typed or "").strip(), (clip or "").strip()
    md = _MD_ONLY_RE.match(clip)
    if md:
        return md_link(typed or md.group(1) or url_name(md.group(2)),
                       md.group(2))
    url = find_url(typed)
    if url:
        label = " ".join(typed.replace(url, " ", 1).split())
    else:
        url, label = find_url(clip), typed
    if not url:
        return typed or clip or None
    return md_link(link_text(label) or url_name(url), url)
