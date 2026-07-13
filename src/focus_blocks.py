"""focus_blocks.py - pure parse/model/serialize for focus session blocks.

A "focus task"'s description carries dated session blocks above the original
description text:

    ### 2026-07-07
    - [ ] [Task A](https://ticktick.com/webapp/#p/<pid>/tasks/<tid>)
    - [x] [Task B](…)
    ---
    ### 2026-07-05
    - [x] [Task C](…)
    ---
    <original description - NEVER touched>

Contracts:
  * serialize(parse(c)) == c for every well-formed c (byte-preserving:
    trailing spaces, CRLF-stripped \\r is the ONE normalization, blank lines
    between blocks, tail verbatim).
  * Checked lines are NEVER removed or rewritten - mutations only append new
    lines, flip "[ ]"→"[x]" once, or move whole unchecked Line objects.
  * Zero-line blocks are never emitted (drops empty headers silently).

Format facts verified against the live app: the app writes "- [x]"
lowercase, preserves our trailing space after the link, and merges concurrent
sticky-side + API-side edits (op-based sync - no whole-buffer clobber).

Pure module: no I/O, no workflow imports - importable by xact.py,
focus_picker.py and focus_bar.py alike.
"""
import re

DATE_HEADER_RE = re.compile(r'^###\s+(\d{4}-\d{2}-\d{2})\s*$')
SEPARATOR_RE = re.compile(r'^---\s*$')
CHECKBOX_RE = re.compile(r'^\s*[-*]\s\[(?P<mark>[ xX])\]\s?(?P<body>.*)$')
# Match by the TRAILING url group, anchored at end of line - titles contain
# markdown links in real data, so never anchor on the FIRST "[".
LINK_TAIL_RE = re.compile(
    r'\]\(https://ticktick\.com/webapp/#p/(?P<pid>[A-Za-z0-9]+)'
    r'/tasks/(?P<tid>[a-f0-9]{24})\)\s*$')


class Line:
    __slots__ = ("raw", "kind", "checked", "tid", "pid")

    def __init__(self, raw, kind, checked=None, tid=None, pid=None):
        self.raw = raw          # exact original line text (no \n, \r stripped)
        self.kind = kind        # "checkbox" | "free"
        self.checked = checked  # bool for checkboxes, None for free lines
        self.tid = tid          # linked task id (None for freehand boxes)
        self.pid = pid


class Block:
    __slots__ = ("date", "lines", "has_separator", "post_blanks")

    def __init__(self, date, lines=None, has_separator=True, post_blanks=0):
        self.date = date                  # "YYYY-MM-DD"
        self.lines = lines or []
        self.has_separator = has_separator
        self.post_blanks = post_blanks    # blank lines between "---" and next header


class FocusDoc:
    __slots__ = ("lead", "blocks", "tail")

    def __init__(self, lead=None, blocks=None, tail=None):
        self.lead = lead or []    # blank lines before the first header
        self.blocks = blocks or []  # newest first (document order)
        self.tail = tail          # original description (str) or None


def _classify(raw):
    m = CHECKBOX_RE.match(raw)
    if not m:
        return Line(raw, "free")
    checked = m.group("mark") in ("x", "X")
    lm = LINK_TAIL_RE.search(raw)
    if lm:
        return Line(raw, "checkbox", checked, lm.group("tid"), lm.group("pid"))
    return Line(raw, "checkbox", checked)


def parse(content):
    """Content string → FocusDoc. Tolerates CRLF, missing separators, blank
    runs between blocks. Anything from the first non-block line down is tail,
    byte-preserved."""
    if not content:
        return FocusDoc()
    lines = [l.rstrip("\r") for l in content.split("\n")]

    # Leading blanks count as lead ONLY when a date header follows them;
    # any other first non-blank line means the whole content is tail.
    j = 0
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines) or not DATE_HEADER_RE.match(lines[j]):
        return FocusDoc(tail=content)
    lead = lines[:j]
    i = j

    blocks = []
    tail = None
    while i < len(lines):
        m = DATE_HEADER_RE.match(lines[i])
        if not m:
            tail = "\n".join(lines[i:])
            break
        date = m.group(1)
        i += 1
        blk_lines = []
        has_sep = False
        while i < len(lines):
            if SEPARATOR_RE.match(lines[i]):
                has_sep = True
                i += 1
                break
            if DATE_HEADER_RE.match(lines[i]):
                break  # next block begins; this one had no separator
            blk_lines.append(_classify(lines[i]))
            i += 1
        blk = Block(date, blk_lines, has_sep)
        # blanks after the separator belong to the block iff a header follows
        if has_sep:
            k = i
            while k < len(lines) and lines[k].strip() == "":
                k += 1
            if k < len(lines) and DATE_HEADER_RE.match(lines[k]):
                blk.post_blanks = k - i
                i = k
        blocks.append(blk)
    return FocusDoc(lead, blocks, tail)


def serialize(doc):
    out = []
    out.extend(doc.lead)
    for b in doc.blocks:
        if not b.lines:
            continue  # never emit a zero-line block
        out.append("### " + b.date)
        out.extend(l.raw for l in b.lines)
        if b.has_separator:
            out.append("---")
            out.extend([""] * b.post_blanks)
    if doc.tail is not None:
        out.append(doc.tail)
    return "\n".join(out)


def make_line(pid, tid, title):
    """New unchecked checkbox line, format cloned from the app's own storage
    (trailing space after the link matches wild data)."""
    clean = " ".join((title or "(untitled)").replace("\r", " ").split("\n"))
    return Line(
        f"- [ ] [{clean}](https://ticktick.com/webapp/#p/{pid}/tasks/{tid}) ",
        "checkbox", False, tid, pid)


def ensure_today(doc, today):
    """Return today's block, creating it at the front if needed. Creation
    CARRIES OVER every unchecked checkbox line from older blocks (in document
    order); checked and free lines stay put - permanent record."""
    if doc.blocks and doc.blocks[0].date == today:
        return doc.blocks[0]
    fresh = Block(today)
    for b in doc.blocks:
        movers = [l for l in b.lines if l.kind == "checkbox" and not l.checked]
        if movers:
            b.lines = [l for l in b.lines if not (l.kind == "checkbox" and not l.checked)]
            fresh.lines.extend(movers)
    doc.blocks.insert(0, fresh)
    return fresh


def insert_checkboxes(doc, today, items):
    """items = [(pid, tid, title)] appended at the BOTTOM of today's block.
    Dedupe: skip a tid already sitting UNCHECKED in today's block (checked
    occurrences - today or older - don't prevent re-adding).
    Returns (added, skipped)."""
    blk = ensure_today(doc, today)
    present = {l.tid for l in blk.lines
               if l.kind == "checkbox" and not l.checked and l.tid}
    added = 0
    skipped = 0
    for pid, tid, title in items:
        if tid and tid in present:
            skipped += 1
            continue
        blk.lines.append(make_line(pid, tid, title))
        if tid:
            present.add(tid)
        added += 1
    return added, skipped


def _current_block(doc, today):
    if not doc.blocks:
        return None
    for b in doc.blocks:
        if b.date == today:
            return b
    return doc.blocks[0]  # midnight-crossing session


def tick(doc, today, target_tid=None):
    """Flip the first unchecked checkbox (optionally: first with target_tid)
    in the current block. Returns the Line or None."""
    blk = _current_block(doc, today)
    if not blk:
        return None
    for l in blk.lines:
        if l.kind != "checkbox" or l.checked:
            continue
        if target_tid and l.tid != target_tid:
            continue
        l.raw = l.raw.replace("[ ]", "[x]", 1)
        l.checked = True
        return l
    return None


def move_item(doc, today, tid, direction):
    """Reorder a checkbox line among the UNCHECKED checkbox lines of the
    current block (the bar's ⤒↑↓⤓ buttons; the bar only shows
    unchecked rows, so moving across checked lines would look dead).
    direction: up/down = one slot, top/bottom = edge. Checked and freehand
    lines keep their positions - only the unchecked lines permute among
    their own slots. Returns True when the order changed."""
    blk = _current_block(doc, today)
    if not blk or not tid:
        return False
    idxs = [i for i, l in enumerate(blk.lines)
            if l.kind == "checkbox" and not l.checked]
    pos = next((k for k, i in enumerate(idxs) if blk.lines[i].tid == tid), None)
    if pos is None:
        return False
    tgt = {"up": pos - 1, "down": pos + 1,
           "top": 0, "bottom": len(idxs) - 1}.get(direction)
    if tgt is None or tgt == pos or tgt < 0 or tgt >= len(idxs):
        return False
    seq = [blk.lines[i] for i in idxs]
    seq.insert(tgt, seq.pop(pos))
    for i, l in zip(idxs, seq):
        blk.lines[i] = l
    return True


def sweep_targets(doc):
    """Every checked LINKED line across ALL blocks → [(pid, tid)], deduped,
    document order. Openness/kind filtering is the caller's job."""
    seen = set()
    out = []
    for b in doc.blocks:
        for l in b.lines:
            if l.kind == "checkbox" and l.checked and l.tid and l.tid not in seen:
                seen.add(l.tid)
                out.append((l.pid, l.tid))
    return out


def today_note(doc, today):
    """The current block verbatim (header + every raw line, checked/unchecked/
    freehand) - becomes the focus record's note. "" when no blocks."""
    blk = _current_block(doc, today)
    if not blk or not blk.lines:
        return ""
    return "### " + blk.date + "\n" + "\n".join(l.raw for l in blk.lines)


def _display_title(line):
    m = LINK_TAIL_RE.search(line.raw)
    cm = CHECKBOX_RE.match(line.raw)
    body = cm.group("body") if cm else line.raw
    if m:
        # body is "[Title](url) " - cut at the link tail, strip the leading "["
        bm = LINK_TAIL_RE.search(body)
        t = body[:bm.start()] if bm else body
        return t[1:] if t.startswith("[") else t
    return body.strip()


def block_summary(doc, today):
    """{done, total, items:[{idx,title,url,tid,pid,checked}]} over the current
    block's checkbox lines - consumed by the focus bar and fx_tick's JSON."""
    blk = _current_block(doc, today)
    items = []
    if blk:
        idx = 0
        for l in blk.lines:
            if l.kind != "checkbox":
                continue
            idx += 1
            url = (f"https://ticktick.com/webapp/#p/{l.pid}/tasks/{l.tid}"
                   if l.tid else None)
            items.append({"idx": idx, "title": _display_title(l), "url": url,
                          "tid": l.tid, "pid": l.pid, "checked": l.checked})
    done = sum(1 for it in items if it["checked"])
    return {"done": done, "total": len(items), "items": items,
            "date": blk.date if blk else None}
