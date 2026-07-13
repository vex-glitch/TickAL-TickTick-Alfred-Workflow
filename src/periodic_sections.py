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

SECTION_HEADER_RE = re.compile(r'^###\s+(?P<name>.+?)\s*$')


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


def find(doc, name):
    """First section whose name matches EXACTLY, else None."""
    for sec in doc.sections:
        if sec.name == name:
            return sec
    return None


def find_prefix(doc, prefix):
    """First section whose name STARTS WITH prefix, else None - the anchor
    form for data-in-header sections ('### ✅ Completed: 121 · 🟢 …')."""
    for sec in doc.sections:
        if sec.name.startswith(prefix):
            return sec
    return None


def set_header(sec, name):
    """Rewrite a section's header text (data-in-header sections). Returns
    True when it changed."""
    if sec.name == name:
        return False
    sec.name = name
    sec.header = f"### {name}"
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
    section opens with decor (--- hugs the content), one blank otherwise."""
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
    is absent or lines is empty."""
    sec = find(doc, name)
    if sec is None or not lines:
        return False
    body = sec.body
    while body and not body[-1].strip():
        body.pop()
    body.extend(lines)
    body.extend(_gap(doc, sec))
    return True
