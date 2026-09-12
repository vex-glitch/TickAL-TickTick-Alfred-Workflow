"""periodic_sections.py - pure generic `###`-section splitter.

Periodic notes (daily/weekly/monthly/quarterly/yearly) are NOTE-kind tasks
whose content is a sequence of `### <name>` sections. Every feature is a
"filler" that owns one section; this module is the only thing that touches
the document structure.

    <lead - breadcrumb line + anything above the first header>
    ### 🧭 Nav
    <body lines>
    ### 💰 Money
    <body lines>

Contracts:
  * serialize_sections(parse_sections(c)) == c for every c (byte-preserving;
    CRLF-stripped \\r is the ONE normalization - the focus_blocks rule).
  * find() is an EXACT header-name match; a missing/renamed header means the
    filler skips silently and the rest of the note is untouched. That is both
    the disclosed limitation and the universal per-section kill switch.
  * set_body/append_body never reflow other sections: mutations are local to
    one section's line list.

Sibling of focus_blocks.py, deliberately separate: the focus grammar keys on
date headers only and its parser must stay untouched. Checkbox/link
line classification is shared by importing focus_blocks' regex CONSTANTS
(never its block model).

Pure module: no I/O, no workflow imports.
"""
import re

SECTION_HEADER_RE = re.compile(r'^(?P<hashes>#{3,6})\s+(?P<name>.+?)\s*$')

# A `- name` bullet inside a section body is addressable exactly like a
# section: its BODY is the indented run beneath it. Vex's 2026-09-12 layout
# turned most sub-sections into bullets (TickTick folds headers, so the few
# that stay headers are the folding points) and 66 fillers address their
# targets BY NAME - so the name resolves to either shape and every filler
# keeps working untouched.
BULLET_RE = re.compile(r'^(?P<indent>\t*)- (?P<name>.+?)\s*$')


# Decor lines: `---` dividers and `#`/`##`
# GROUP headers between sections. They belong to the section that FOLLOWS
# them (its `pre`), so fillers rewriting a body can never wipe the divider
# or group header sitting above the next section.
DECOR_RE = re.compile(r'^(?:---+|#{1,2}\s.*)\s*$')


class Section:
    __slots__ = ("header", "name", "body", "pre")

    def __init__(self, header, name, body=None, pre=None):
        self.header = header      # exact original header line (no \n)
        self.name = name          # stripped text after "### "
        self.body = body or []    # raw lines until the next header
        self.pre = pre or []      # decor lines owned by THIS section


class SecDoc:
    __slots__ = ("lead", "sections")

    def __init__(self, lead=None, sections=None):
        self.lead = lead or []          # raw lines before the first header
        self.sections = sections or []  # document order


def parse_sections(content):
    """content str → SecDoc. Splits on `### ` headers; everything else is
    body/lead verbatim. A trailing run of decor lines (`---`, `# Group`) in a
    body migrates to the NEXT section's pre - leading blanks of the run stay
    behind as the body's gap. '' parses to an empty-lead doc."""
    lines = (content or "").replace("\r", "").split("\n")
    doc = SecDoc()
    current = None
    for raw in lines:
        m = SECTION_HEADER_RE.match(raw)
        if m:
            current = Section(raw, m.group("name"))
            doc.sections.append(current)
        elif current is not None:
            current.body.append(raw)
        else:
            doc.lead.append(raw)
    # decor migration: a trailing run of decor lines in a body belongs to the
    # NEXT section's pre
    for i in range(1, len(doc.sections)):
        body = doc.sections[i - 1].body
        j = len(body)
        while j > 0 and (not body[j - 1].strip() or DECOR_RE.match(body[j - 1])):
            j -= 1
        run = body[j:]
        while run and not run[0].strip():      # leading blanks stay in body
            run.pop(0)
            j += 1
        if any(ln.strip() for ln in run):
            doc.sections[i].pre = run
            del body[j:]
    # lead migration: only the trailing `#`/`##` GROUP header (plus one blank
    # above it) moves to the first section - the lead itself is engine-
    # composed and would wipe a group header parked there; its own ---
    # divider stays put
    if doc.sections:
        lead = doc.lead
        j = len(lead)
        while j > 0 and (not lead[j - 1].strip() or DECOR_RE.match(lead[j - 1])):
            j -= 1
        k = next((i for i in range(j, len(lead))
                  if re.match(r'^#{1,2}\s', lead[i])), None)
        if k is not None and not doc.sections[0].pre:
            doc.sections[0].pre = lead[k:]
            del lead[k:]
    return doc


def serialize_sections(doc):
    """Inverse of parse_sections - byte round-trip."""
    out = list(doc.lead)
    for sec in doc.sections:
        out.extend(sec.pre)
        out.append(sec.header)
        out.extend(sec.body)
    return "\n".join(out)


def _tabs(line):
    return len(line) - len(line.lstrip("\t"))


def _rebase(lines, tabs):
    """Re-indent `lines` so their shallowest line sits at `tabs`, keeping
    every relative depth (a journal's Q/A nesting must survive)."""
    real = [l for l in lines if l.strip()]
    if not real:
        return list(lines)
    base = min(_tabs(l) for l in real)
    out = []
    for l in lines:
        if not l.strip():
            out.append("")
            continue
        out.append("\t" * (tabs + _tabs(l) - base) + l.lstrip("\t"))
    return out


class Block:
    """A `- name` bullet addressed like a section. Its span is recomputed on
    every access, so a write that changes the body's length cannot leave a
    stale index behind."""
    __slots__ = ("sec", "header", "name", "indent")

    def __init__(self, sec, header, name, indent):
        self.sec, self.header, self.name, self.indent = sec, header, name, indent

    def _span(self):
        body = self.sec.body
        try:
            i = body.index(self.header)
        except ValueError:
            return None, None
        j = i + 1
        while j < len(body):
            ln = body[j]
            if ln.strip() and _tabs(ln) <= self.indent:
                break
            j += 1
        while j > i + 1 and not body[j - 1].strip():   # trailing blanks are
            j -= 1                                     # the GAP, not the body
        return i + 1, j

    @property
    def body(self):
        a, b = self._span()
        return [] if a is None else self.sec.body[a:b]

    @body.setter
    def body(self, lines):
        a, b = self._span()
        if a is not None:
            self.sec.body[a:b] = _rebase(lines, self.indent + 1)


def _blocks(sec):
    """Every bullet of a section body, at ANY depth, outermost first.

    Depth matters because a block can hold another: the 💰 Money block lives
    INSIDE the day summary (Vex 2026-09-12 - "Money needs to be a part of
    today summary, not a standalone section"), so its entries are two levels
    below the header. Ambiguity is handled by find()'s guard, not by only
    looking at the top level."""
    out = []
    for l in sec.body:
        m = BULLET_RE.match(l)
        if m:
            out.append(Block(sec, l, m.group("name"), _tabs(l)))
    return sorted(out, key=lambda b: b.indent)


# Vex's layout renamed anchors as he de-emojied ("💰 Money" -> "- Money",
# "☀️ Daily" -> "- 📌 Daily", "🌅 Morning journal" -> "- 🌅 Morning Journal"),
# so a name also matches with its symbols and case stripped.
_NORM_RE = re.compile(r"[^\w\s']+", re.UNICODE)


def _norm(name):
    return " ".join(_NORM_RE.sub(" ", name or "").split()).casefold()


def _only(cands):
    """The single candidate, or None - an AMBIGUOUS normalized name must never
    be guessed. "📊 Today" and "☀️ Today" both normalize to "today", and
    writing the day summary into the group that holds Habits, Countdowns and
    Money would eat three blocks."""
    return cands[0] if len(cands) == 1 else None


def find(doc, name):
    """The section or bullet BLOCK this name addresses.

    Four passes, most literal first: exact header, exact bullet, then the
    normalized forms - bullets BEFORE headers, because a renamed sub-block
    is the intended target far more often than a group header that happens
    to normalize the same way. A normalized pass that finds two candidates
    returns None rather than pick one.
    """
    for sec in doc.sections:
        if sec.name == name:
            return sec
    for sec in doc.sections:
        for blk in _blocks(sec):
            if blk.name == name:
                return blk
    want = _norm(name)
    if not want:
        return None
    blocks = [b for sec in doc.sections for b in _blocks(sec) if _norm(b.name) == want]
    hit = _only(blocks)
    if hit is not None:
        return hit
    return _only([sec for sec in doc.sections if _norm(sec.name) == want])


def find_prefix(doc, prefix):
    """First section whose name STARTS WITH prefix, else the first bullet
    block that does - the anchor form for data-in-header sections
    ('### ✅ Completed: 121 · 🟢 …', or '- Completed: 121')."""
    for sec in doc.sections:
        if sec.name.startswith(prefix):
            return sec
    for sec in doc.sections:
        for blk in _blocks(sec):
            if blk.name.startswith(prefix):
                return blk
    return None


def set_header(sec, name):
    """Rewrite a section's header text (data-in-header sections). Returns
    True when it changed. A Block's header is its bullet line, and its own
    hash level / indent is preserved - a filler must never flatten the
    layout it writes into."""
    if sec.name == name:
        return False
    if isinstance(sec, Block):
        body = sec.sec.body
        try:
            i = body.index(sec.header)
        except ValueError:
            return False
        new_line = "\t" * sec.indent + f"- {name}"
        body[i] = new_line
        sec.header, sec.name = new_line, name
        return True
    hashes = (SECTION_HEADER_RE.match(sec.header or "").group("hashes")
              if SECTION_HEADER_RE.match(sec.header or "") else "###")
    sec.name = name
    sec.header = f"{hashes} {name}"
    return True


def _canon(lines):
    """Body content with no trailing blanks - the gap to the next header is
    decided by _gap (--- dividers sit TIGHT against the body; plain
    sections get one blank line)."""
    body = list(lines)
    while body and not body[-1].strip():
        body.pop()
    return body


def _gap(doc, sec):
    """The canonical trailing gap after sec's body: nothing when the next
    section opens with decor (--- hugs the content), one blank otherwise.
    A Block owns no gap - the blank between bullets belongs to the section
    body around it, so writing one would grow the note on every refresh."""
    if isinstance(sec, Block):
        return []
    i = doc.sections.index(sec)
    nxt = doc.sections[i + 1] if i + 1 < len(doc.sections) else None
    return [] if (nxt is not None and nxt.pre) else [""]


def set_body(doc, name, lines):
    """Rewrite a section's body (FILLER semantics). False when the section is
    absent or the canonical body is already identical."""
    sec = find(doc, name)
    if sec is None:
        return False
    return set_sec_body(doc, sec, lines)


def set_sec_body(doc, sec, lines):
    """set_body on an already-located section (the data-in-header sections
    are found by prefix, then written directly)."""
    new = _canon(lines) + _gap(doc, sec)
    if sec.body == new:
        return False
    sec.body = new
    return True


def append_body(doc, name, lines):
    """Append lines at the section's end, before the trailing gap (APPEND
    semantics - existing lines are never rewritten). False when the section
    is absent or lines is empty.

    The write goes back through `sec.body = ...`, never by mutating the list
    in place: a Block's `body` is a PROPERTY that hands out a copy of its
    slice, so `sec.body.extend(...)` filled a throwaway list and returned
    True while the note never changed. That is what silently ate every
    "➕ Entry" once 📓 Notes became a bullet (Vex 2026-09-12: "I tried adding
    a win, it did nothing")."""
    sec = find(doc, name)
    if sec is None or not lines:
        return False
    body = list(sec.body)
    while body and not body[-1].strip():
        body.pop()
    real = [l for l in body if l.strip()]
    if real:
        # Land beside what is already there, not under it. Callers pass their
        # own indent guess (pm.T2 and friends) and a Block re-bases the WHOLE
        # body as one run, so an appended line one tab deeper than the last
        # one became its CHILD - the second entry of the day nested inside
        # the first.
        lines = _rebase(lines, min(_tabs(l) for l in real))
    body.extend(lines)
    body.extend(_gap(doc, sec))
    sec.body = body
    return True
