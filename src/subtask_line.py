"""subtask_line.py - the '|' subtask grammar of the add bar (PURE: stdlib only).

Vex 2026-09-12: `add "Buy groceries | Milk | Bread ~Money #buy"` should create
the task AND its subtasks in one go, the way the focus picker's "from A | B"
flow already reads. The attribute tokens (~list, #tag, !priority, dates …)
belong to the WHOLE add, so they are parsed first and this module only ever
sees the title that survives them.

Two shapes, decided by where the add is aimed:
  * no parent in play -> the first segment is the task, the rest its subtasks
  * adding INTO a parent (the ⌘ Actions "➕ Add task" road, or ~p) -> every
    segment is a sibling under that parent, because the parent already exists
So the rule reads the same both ways: a pipe starts the next child of
whatever the line is hanging from.
"""
import re as _re

SEP = "|"

# A pipe inside a [[wikilink]], a [markdown](link) or a BARE url is TEXT.
# All three carry real-world strings (a picked task, a pasted link, a query
# string like ?family=A|B) and must survive the split: add_task's own [[ ]]
# syntax round-trips through here, and the `u ` link prefix builds its
# markdown link from the title only AFTER this has run.
_OPAQUE = _re.compile(r'\[\[[^\[\]]*\]\]'
                      r'|\[[^\[\]]*\]\((?:[^()\n]|\([^()\n]*\))*\)'
                      r'|[a-zA-Z][a-zA-Z0-9+.\-]*://\S+')

# The add bar's attribute triggers, at a word boundary (add_task.parse_task).
_TOKEN = _re.compile(r'(?<!\S)[~#!*@/>=&%]')


# Only what the bar ACTUALLY consumes, so ordinary punctuation survives:
# "Fish & Chips" keeps its &, "Sale 50% off" its %, "2020 > 2021" its >.
# Two rules beyond parse_task's own tokens, both from find_active_trigger:
# a trigger in the LAST word opens a sub-picker on a one-word fragment, and
# a word-initial @ opens the time picker whatever follows it (it strips its
# fragment before testing). The standalone markers are here too: a page
# title carrying "^" or "+focus" would silently arm them and lose the word.
_UNSAFE = _re.compile(
    r'(?<!\S)(?:'
    r'[~*/=@]'                                            # picker or span
    r'|#(?=\S)'                                           # #tag
    r'|!(?=[123](?:\s|$))'                                # !priority
    r'|>(?=\d)'                                           # >duration
    r'|&(?=(?:daily|weekdays|weekly|monthly|yearly)(?:\s|$))'
    r'|%(?=\S)'                                           # %reminder
    r'|\^(?=\s|$)'                                        # ^ attach image
    r'|\+(?=(?:stage|focus|web)(?:\s|$))'                 # +stage +focus +web
    r'|[~#!*/>@&%=](?=\S*\s*$)'                           # one in the last word
    r')', _re.IGNORECASE)


def splice_title(text, name):
    """`text` with `name` joined onto its TITLE, before the first attribute
    token - the rule next_query already follows for the pipe.

    Appending at the END would feed the words to whatever token sits last:
    "u *sat " plus "Monday Night Football" reads as a date span, not a name,
    and both the title and the date come out wrong.
    """
    if not name:
        return text
    masked, show = _masked(text or "")
    m = _TOKEN.search(masked)
    cut = m.start() if m else len(masked)
    head = show(masked[:cut]).rstrip()
    tail = show(masked[cut:]).strip()
    out = f"{head} {name}".strip()
    return f"{out} {tail}" if tail else out


def bar_safe(text):
    """Arbitrary text made safe to put INTO the add bar.

    The bar owns a dozen characters, so text that came from somewhere else -
    a web page title, fed in by the `u ` prefix's browser row - cannot be
    typed in raw: "Easy chicken curry | BBC Good Food" would have carved
    "BBC Good Food" off as a subtask, and "Recipe #5" would have minted a
    tag. The pipe becomes the separator this workflow uses everywhere else;
    a word-initial trigger is dropped, because this grammar has no escape
    and the words matter more than the punctuation.
    """
    t = (text or "").replace(SEP, "·").replace("[[", "((").replace("]]", "))")
    for _ in range(12):         # dropping one can expose the next: "~/path"
        out = _UNSAFE.sub("", t)
        if out == t:
            break
        t = out
    return " ".join(t.split())


def _masked(text):
    """(text with every opaque run hidden, a function that puts them back)."""
    holes = []

    def _hide(m):
        holes.append(m.group(0))
        return f"\x00P{len(holes) - 1}\x00"

    masked = _OPAQUE.sub(_hide, text or "")

    def _show(s):
        if not holes or s is None:
            return s
        return _re.sub(r'\x00P(\d+)\x00',
                       lambda m: holes[int(m.group(1))], s)

    return masked, _show


def split_line(text):
    """(head, [child, ...]) for a pipe-separated title.

    "Buy groceries | Milk | Bread" -> ("Buy groceries", ["Milk", "Bread"])
    Empty segments drop, so a trailing "| " (what the ➕ row leaves behind)
    is not a nameless subtask. Whitespace is squeezed, as in the bar itself.
    """
    masked, show = _masked(text)
    parts = [" ".join(show(p).split()) for p in masked.split(SEP)]
    head = parts[0] if parts else ""
    kids = [p for p in parts[1:] if p]
    if not head and kids:          # a line that opens with a pipe still
        head, kids = kids[0], kids[1:]      # names the first thing typed
    return head, kids


def in_subtask_mode(text):
    """True once the line carries a separator at all - including a trailing one
    with nothing after it yet, which is exactly what the ➕ row leaves."""
    return SEP in _masked(text)[0]


def next_query(text):
    """The query with room for one more subtask.

    The separator lands after the TITLE, before the first attribute token:
    appending it at the very end would feed the pipe to whatever token sits
    last, and "~Money | " reads as a list named "Money |". Alfred drops the
    cursor at the end, so the next word typed still joins the title once the
    tokens are parsed out of the middle.
    """
    masked, show = _masked(text or "")
    m = _TOKEN.search(masked)
    cut = m.start() if m else len(masked)
    head, tail = show(masked[:cut]).rstrip(), show(masked[cut:]).strip()
    while head.endswith(SEP):
        head = head[:-1].rstrip()
    out = f"{head} {SEP} ".lstrip()
    return f"{out}{tail}" if tail else out


def chip(kids, sibling=False):
    """The '+ 2 subtasks' chip for a preview row, '' when there are none.

    `sibling` is the into-a-parent road: those segments are NOT children of
    the task on the row, they are the next children of the same parent, so
    calling them subtasks of it would be a lie.
    """
    n = len(kids or [])
    if not n:
        return ""
    if sibling:
        return f"+ {n} more"
    return f"+ {n} subtask" + ("" if n == 1 else "s")
