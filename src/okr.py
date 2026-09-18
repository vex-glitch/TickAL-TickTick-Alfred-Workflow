#!/usr/bin/env python3
"""okr.py - the goals (OKR) model: pure functions first, one loader last.

Spec: HANDOFF_OKR.md (Vex's decisions, 2026-09-18). The short of it:

  "I see OKRs more like forecasting ... They should serve more like
  'guiding star' rather than daily work plan. Cause as we all know reality
  drifts from plans."  (Vex 2026-09-18)

ONE list holds the plan (config.get_okr_list_id, 🏆Goals Planning), and Vex
schedules it BY HAND in TickTick's timeline view. Every item is an all-day
PLANNING COPY whose title may link to the real thing it plans. Three levels,
told apart by the title prefix alone:

    🏔️ Y • Productivity System                      year objective, one per area
    🥅 O • TickAL                                    objective (under a Y, or loose)
    🔑 KR • [Goals wf](<task link>) - TA             key result = a deliverable

This module reads that list and answers: the tree, the dates, the parent
spans a timeline drag has left stale (heal), progress (ticked KRs over all
KRs), pace, the plan for a period, the ripple a schedule action would cause,
the KRs whose linked original is already done (auto-tick) and the objective
codes. Nothing here writes: the planners RETURN what a writer should do, and
phase 1 only prints it.

Pure part: no I/O. The one impure piece is load() at the bottom (v1 open
tasks + v2 completed ones, cache fallback that SAYS it fell back) and the
__main__ report:

    python3 src/okr.py          # the live tree, read-only

THE WRITER RULE (phase 2 and on). Every writer this model feeds - the span
heal, the auto-tick, the ripple of a schedule action - must REFUSE unless
the Snapshot it planned from says source == "live" AND done_complete
(Snapshot.writable). A cache read is minutes to hours old, and a plan
without every completed KR reads a ticked deliverable as deleted: it counts
nowhere, shapes no span, and a heal or ripple built on that would write a
wrong plan over the right one. Reading (the report, the notes' forecast
lines) may use any Snapshot; writing may not.
"""
import os
import re
import sys
from collections import Counter, namedtuple
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import areas
import day_move
import mdtext
import periodic_model as pm

# ── Titles ───────────────────────────────────────────────────────────────────
KINDS = ("Y", "O", "KR")
PREFIX = {"Y": "🏔️ Y • ", "O": "🥅 O • ", "KR": "🔑 KR • "}
CODE_SEP = " - "

# The dashes a title may carry where Vex typed a hyphen: the hyphen itself,
# and the en dash, em dash and minus sign that text substitution and pasted
# text turn it into (escapes, never the characters, in this file).
_DASHES = "\\-\u2013\u2014\u2212"

# Tolerant on purpose (HANDOFF section 2): VS16 on the emoji optional, any of
# • · or a dash after the letter, any spacing, either case. The emoji itself
# is NOT optional - "O - ..." or "KR - ..." are ordinary words at the start
# of an ordinary title, and a bare letter would drag strangers into the plan.
_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?P<Y>\U0001F3D4\ufe0f?\s*Y)"
    r"|(?P<O>\U0001F945\ufe0f?\s*O)"
    r"|(?P<KR>\U0001F511\ufe0f?\s*KR)"
    r")\s*[•·" + _DASHES + r"]\s*", re.I)

# The code suffix: a SPACED dash or middle dot, then ONE word that starts
# with a capital or a digit, at the very end. Two things this refuses on
# purpose:
#   * a spaced • - Vex uses it INSIDE names ("🥅 O • Audits • Execute &
#     Establish (Naming Conventions)", live 2026-09-18), and reading
#     "Execute" as a code would rewrite his title the first time a writer
#     rebuilds it;
#   * a lower-case last word - "Fix the export - again" is a name, not a code.
# What this reads is only a CANDIDATE. Whether it is a code is settled in
# context once the whole list is read (settle_codes): Vex's live codes are
# not all caps (16 KRs end " - Shortcuts", 6 end " - Audit").
_CODE_RE = re.compile(r"\s+[·" + _DASHES + r"]\s+(?P<code>\w{1,16})\s*$")
# The one UNSPACED form: the separator right after a link's closing paren
# ("[Goals wf](url)- TA"), where there is no word it could be glued to.
_TAIL_CODE_RE = re.compile(r"[·" + _DASHES + r"]\s+(?P<code>\w{1,16})\s*$")

# A markdown link whose LABEL may hold one level of brackets, as typed in
# the app ("[Sleeve [250]](url)"). mdtext.MD_LINK_RE refuses a nested
# bracket, and a title is exactly where Vex types one. The target part is
# mdtext's (a URL with one level of parens, like Wikipedia's).
_LINK_RE = re.compile(
    r"\[((?:[^\[\]\n]|\[[^\[\]\n]*\])*)\]\((?:[^()\n]|\([^()\n]*\))*\)")

# TickTick's own URLs for a list and for a task. areas.TASK_LINK_RE only knows
# the https TASK form inside a [label](url); a list link (areas._list_link
# writes ticktick:///webapp/#p/<pid>/tasks) and the app-scheme task form need
# this wider one. The BUILDERS stay areas._task_link / areas._list_link.
_TT_URL_RE = re.compile(
    r"^(?:ticktick://|https://(?:www\.)?ticktick\.com)"
    r"/webapp/#p/(?P<pid>\w+)/tasks(?:/(?P<tid>\w+))?/?$")


def _is_code(word):
    return bool(word) and (word[0].isupper() or word[0].isdigit())


def _flatten(text):
    """Links reduced to their label, nested-bracket labels included."""
    return _LINK_RE.sub(r"\1", text or "")


def _split_link(body):
    """(name, url) of a title body. A body that IS one markdown link gives
    its label and target. A link inside other words gives the flattened text
    and the FIRST link's target (build_title cannot write that shape back -
    it only ever writes a whole-body link - but reading must not lose it)."""
    m = _LINK_RE.search(body)
    if not m:
        return " ".join(body.split()), None
    label = m.group(1)
    url = m.group(0)[len(label) + 3:-1].strip()
    if m.group(0) == body:
        return " ".join(label.split()), url
    return " ".join(_flatten(body).split()), url


def _split_code(body):
    """(body without the suffix, candidate code or None)."""
    cm = _CODE_RE.search(body)
    if cm and _is_code(cm.group("code")) and body[:cm.start()].strip():
        return body[:cm.start()], cm.group("code")
    last = None
    for last in _LINK_RE.finditer(body):
        pass
    if last is not None:
        tm = _TAIL_CODE_RE.match(body, last.end())
        if tm and _is_code(tm.group("code")):
            return body[:last.end()], tm.group("code")
    return body, None


def _parse(title, split_code=True):
    t = pm.unescape_md(title or "").strip()
    m = _PREFIX_RE.match(t)
    kind = m.lastgroup if m else None
    body = t[m.end():] if m else t
    code = None
    if kind and split_code:
        body, code = _split_code(body)
    name, link = _split_link(body.strip())
    return kind, name, link, code


def parse_title(title):
    """title -> (kind, name, link, code).

    kind  "Y" | "O" | "KR", or None for a title without an OKR prefix
    name  the words, link label rather than markdown, spacing collapsed
    link  the raw URL of the link in the title, or None (link_target says
          what it points at)
    code  the CANDIDATE " - TA" suffix, or None. Read on all three kinds so
          build_title round-trips, but only KRs carry one by convention - an
          O's own code lives in its description (code_of). An unprefixed
          title never has one: without a kind there is no convention to read
          it by. A candidate is not yet a code: "Call Anna - Monday" reads
          Monday here, and settle_codes, which sees the KR's O, folds it back
          into the name. Everything that reads a whole list goes through
          items_from, which settles; this function is the context-free half.

    Tolerant: a dash may be the en dash, em dash or minus sign; the
    separator may sit right after a link's closing paren with no space
    ("[Goals wf](url)- TA"); a link label may hold one level of brackets.
    The app backslash-escapes markdown in titles it saves (pm.unescape_md),
    so "\\[Goals wf\\]\\(url\\)" reads like the link it was typed as."""
    return _parse(title)


def build_title(kind, name, link=None, code=None):
    """The title parse_title reads back as (kind, name, link, code).

    The prefix and the suffix stay OUTSIDE the link (HANDOFF section 2):
    "🔑 KR • [Goals wf](https://ticktick.com/webapp/#p/P/tasks/T) - TA".
    The label goes through mdtext.md_link, so a name with brackets in it
    comes back with parens - the one place the round trip is not literal.
    A name that itself ends in " - Word" reads back with Word as its
    candidate code. settle_codes folds a candidate that is not all caps
    ("Monday", "2027") back into the name unless it is the O's code, but
    nothing in a title can escape an all-caps one ("- USA"), so callers
    stamping a text-only name should check it with parse_title first."""
    if kind not in PREFIX:
        raise ValueError(f"unknown OKR kind {kind!r}")
    body = mdtext.md_link(name, link) if link else " ".join((name or "").split())
    return PREFIX[kind] + body + (f"{CODE_SEP}{code}" if code else "")


def link_target(url):
    """What a title link points at:
         ("task", pid, tid)   a task, subtask or note (the webapp task URL)
         ("list", pid, None)  a list (ticktick:///webapp/#p/<pid>/tasks, or
                              the https form of it)
         ("url", None, None)  anything else - kept, never interpreted
         None                 no link at all"""
    if not url:
        return None
    m = _TT_URL_RE.match(url.strip())
    if not m:
        return ("url", None, None)
    if m.group("tid"):
        return ("task", m.group("pid"), m.group("tid"))
    return ("list", m.group("pid"), None)


def task_link(pid, tid):
    """The URL a KR title uses for a task / subtask / note."""
    return areas._task_link(pid, tid)


def list_link(pid):
    """The URL an O title uses for a list."""
    return areas._list_link(pid)


# ── Dates (HANDOFF section 3 - read it before touching any of this) ─────────
# TickTick writes the due of a MULTI-day all-day item as the NEXT day's
# midnight: start 21 Dec, due 25 Dec = 21-24 Dec. A single-day item comes in
# BOTH forms in his live list (start == due, and due == start + 1), and both
# are one day. Evidence the exclusive reading is right: his chains hand over
# ON the due date (Backups WF due 21 Dec, Files and folders WF starts 21 Dec).
#
# Stamps arrive as "2026-12-25T00:00:00+0100" (timeZone Europe/Berlin), as
# "2026-09-24T22:00:00+0000" (timeZone "") - midnight Berlin written in UTC -
# and, from the v1 API, as "2026-12-24T23:00:00.000+0000". So: convert to the
# item's own zone (else Berlin) FIRST, then take the date. Taking [:10] of
# the second form puts the item on the day before.
DEFAULT_TZ = "Europe/Berlin"
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RAW_RE = re.compile(
    r"^(?P<wall>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?P<frac>\.\d+)?"
    r"(?P<off>Z|[+-]\d\d:?\d\d)?$")
_UTC_OFFS = ("Z", "+0000", "-0000", "+00:00", "-00:00")


def _tz(name=None):
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def local_dt(raw, tz_name=None):
    """A TickTick stamp as an aware datetime in the item's zone, or None."""
    inst = day_move._parse((raw or "").strip())
    return inst.astimezone(_tz(tz_name)) if inst else None


def to_date(raw, tz_name=None):
    """A TickTick stamp -> its LOCAL date (the zone conversion comes first)."""
    raw = (raw or "").strip()
    if _DATE_ONLY_RE.match(raw):
        return date.fromisoformat(raw)
    dt = local_dt(raw, tz_name)
    return dt.date() if dt else None


def span(task):
    """(start, end_inclusive) dates of a raw task, (None, None) undated.

    end_inclusive = due - 1 day if due > start else start. The one other
    case: a TIMED item (not all-day, due not at local midnight) ends ON its
    due day - OKR items are all-day by rule, but a timed task dragged into
    the list must not lose a day. Only one of the two dates set = one day."""
    tz = task.get("timeZone") or None
    s_raw, d_raw = task.get("startDate"), task.get("dueDate")
    s, d = to_date(s_raw, tz), to_date(d_raw, tz)
    if s is None and d is None:
        return None, None
    if s is None:
        return d, d
    if d is None or d <= s:
        return s, s
    due = local_dt(d_raw, tz)
    if not task.get("isAllDay") and due is not None and due.time() != time(0):
        return s, d
    return s, d - timedelta(days=1)


def _form(raw):
    """(fraction, offset) as a raw stamp WROTE them: '.000' or '', and the
    offset text ('+0000', '+0100', 'Z', '+01:00')."""
    m = _RAW_RE.match((raw or "").strip())
    if not m:
        return "", "+0000"
    return m.group("frac") or "", m.group("off") or "+0000"


def _write(dt_local, like=None):
    """An aware datetime in the FORM of `like`: a UTC-form stamp stays UTC
    ("…T22:00:00+0000"), a local-offset one stays local and takes the new
    day's own offset (+0200 in summer, +0100 in winter), and the millis
    come along when they were there. No `like` = the plain UTC form the
    Open API writes (day_move._FMT)."""
    frac, off = _form(like)
    if off in _UTC_OFFS:
        wall = dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return wall + frac + off
    z = dt_local.strftime("%z")
    if ":" in off:
        z = z[:3] + ":" + z[3:]
    return dt_local.strftime("%Y-%m-%dT%H:%M:%S") + frac + z


def _shift1(raw, days, tz_name):
    if not raw:
        return raw
    raw = raw.strip()
    if _DATE_ONLY_RE.match(raw):
        return (date.fromisoformat(raw) + timedelta(days=days)).isoformat()
    loc = local_dt(raw, tz_name)
    if loc is None:
        raise ValueError(f"unreadable TickTick date {raw!r}")
    wall = loc.replace(tzinfo=None) + timedelta(days=days)
    return _write(wall.replace(tzinfo=_tz(tz_name)), raw)


def shift_raw(start_raw, due_raw, days, tz_name=None):
    """(start, due) raw strings moved by `days` CALENDAR days, each keeping
    the item's own form: the same UTC-or-local style, the same millis, and
    the same single-day shape (start == due stays start == due).

    The day is added to the LOCAL wall clock, never to the UTC instant: an
    all-day item stored as "2026-10-24T22:00:00+0000" (25 Oct, CEST) moved a
    week lands on "2026-10-31T23:00:00+0000" (1 Nov, CET). Adding 7 x 24 h
    would have put it on 31 Oct. An undated field stays undated."""
    return _shift1(start_raw, days, tz_name), _shift1(due_raw, days, tz_name)


def span_raw(start, end, tz_name=None, like=None):
    """(start, due) raw strings for an all-day span start..end INCLUSIVE,
    written in the exclusive form (due = the day after end, midnight local)
    - what a NEW LENGTH writes (HANDOFF section 3). `like` = an existing
    stamp of the item whose form to keep; None = the Open API's UTC form."""
    if start is None or end is None or end < start:
        raise ValueError(f"bad span {start}..{end}")
    tz = _tz(tz_name)
    s = datetime.combine(start, time(0)).replace(tzinfo=tz)
    d = datetime.combine(end + timedelta(days=1), time(0)).replace(tzinfo=tz)
    return _write(s, like), _write(d, like)


# ── Items ────────────────────────────────────────────────────────────────────
@dataclass
class Item:
    """One task of the OKR list, read. `raw` is the task dict it came from
    (a writer posts that back, changed); everything else is derived."""
    id: str
    pid: str = ""
    kind: Optional[str] = None            # "Y" | "O" | "KR" | None
    name: str = ""
    link: Optional[str] = None
    code: Optional[str] = None            # SETTLED code (settle_codes)
    tags: list = field(default_factory=list)
    start: Optional[date] = None
    end: Optional[date] = None            # INCLUSIVE
    done: bool = False                    # status 2
    parent: Optional[str] = None
    # childIds as TickTick has them. Read ONLY by dangling(): the tree,
    # spans and progress all follow parentId (a KR moved to another O stays
    # in the old one's childIds).
    children: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    suffix: Optional[str] = None          # the title's CANDIDATE code (parse_title)

    @property
    def dated(self):
        return self.start is not None

    @property
    def abandoned(self):
        """Won't do (status -1): out of progress, pace and spans alike."""
        return (self.raw or {}).get("status") == -1

    @property
    def history(self):
        """Done or won't do: HISTORY. It never moves - no ripple shifts it,
        no parent's move drags it, no heal rewrites a done Y/O's span."""
        return self.done or self.abandoned

    @property
    def target(self):
        return link_target(self.link)

    @property
    def title(self):
        return (self.raw or {}).get("title") or ""

    @property
    def tz(self):
        return (self.raw or {}).get("timeZone") or None


def from_task(task):
    """A raw TickTick task -> Item, read on its own: `code` is the title's
    candidate as it stands (items_from settles it against the KR's O)."""
    kind, name, link, code = parse_title(task.get("title"))
    s, e = span(task)
    return Item(id=task.get("id") or "", pid=task.get("projectId") or "",
                kind=kind, name=name, link=link, code=code,
                tags=list(task.get("tags") or []), start=s, end=e,
                done=task.get("status") == 2,
                parent=task.get("parentId") or None,
                children=list(task.get("childIds") or []), raw=task,
                suffix=code)


def items_from(tasks):
    """Raw tasks -> Items, codes settled in context (settle_codes)."""
    return settle_codes([from_task(t) for t in tasks or [] if t.get("id")])


def write_fields(item, new_start, new_end):
    """{startDate, dueDate, isAllDay} for putting `item` on new_start..
    new_end (inclusive). An ALL-DAY item (raw isAllDay true) keeping its
    length = a SHIFT, which keeps the item's own form. Anything else - a new
    length, an undated item, and a TIMED item even at the same length -
    gets the exclusive midnight all-day form: shifting a timed stamp and
    then stamping isAllDay on it would make its due (10:00 the next day)
    read as an exclusive end, a day short."""
    raw = item.raw or {}
    if (item.dated and raw.get("isAllDay") is True
            and (new_end - new_start) == (item.end - item.start)
            and raw.get("startDate")):
        s, d = shift_raw(raw.get("startDate"), raw.get("dueDate"),
                         (new_start - item.start).days, item.tz)
    else:
        s, d = span_raw(new_start, new_end, item.tz, like=raw.get("startDate"))
    return {"startDate": s, "dueDate": d or s, "isAllDay": True}


def index(items):
    return {it.id: it for it in items}


def _order(it):
    return (not it.dated, it.start or date.max, it.name)


def _kids(items):
    """{parent id: [children]} by the children's own parentId, dated first
    in start order. The tree, the spans and progress all follow parentId;
    childIds is read by dangling() alone."""
    out = {}
    for it in items:
        if it.parent:
            out.setdefault(it.parent, []).append(it)
    for v in out.values():
        v.sort(key=_order)
    return out


def _ancestors(it, by):
    """Nearest first; a parentId loop (never seen, cheap to refuse) stops."""
    out, seen = [], {it.id}
    p = by.get(it.parent) if it.parent else None
    while p is not None and p.id not in seen:
        out.append(p)
        seen.add(p.id)
        p = by.get(p.parent) if p.parent else None
    return out


def _descendants(iid, kids):
    out, todo = set(), [iid]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c.id not in out and c.id != iid:
                out.add(c.id)
                todo.append(c.id)
    return out


# ── Tree ─────────────────────────────────────────────────────────────────────
_FITS = {"Y": (), "O": ("Y",), "KR": ("O",)}      # the parent kinds each may have


def tree(items):
    """The plan as nodes, node = (item, [child nodes]), dated children first
    in start order. Nothing is dropped:

      years       Y roots, each with its whole subtree
      orphan_os   O roots - an O with no Y above it (every O in the list on
                  2026-09-18: the Y level is new). It IS a lane on its own.
      orphan_krs  KR roots - a KR with no O above it
      loose       unprefixed roots, with whatever hangs under them
      unprefixed  EVERY unprefixed item, wherever it sits (the report: each
                  one wants a prefix, or does not belong in the list)
      misplaced   items whose parent is the wrong level - a KR straight
                  under a Y, an O under an O, a Y with a parent. They also
                  stay where they are in their parent's subtree.

    A parentId that points at nothing in the list (the parent was deleted,
    or is in another list) makes the item a root."""
    by = index(items)
    kids = _kids(items)

    def node(it, seen):
        seen = seen | {it.id}
        return (it, [node(c, seen) for c in kids.get(it.id, []) if c.id not in seen])

    out = {"years": [], "orphan_os": [], "orphan_krs": [], "loose": [],
           "unprefixed": [], "misplaced": []}
    slot = {"Y": "years", "O": "orphan_os", "KR": "orphan_krs", None: "loose"}
    reached = set()

    def mark(n):
        reached.add(n[0].id)
        for k in n[1]:
            mark(k)

    for it in sorted((i for i in items if not (i.parent and i.parent in by)), key=_order):
        out[slot[it.kind]].append(node(it, frozenset()))
        mark(out[slot[it.kind]][-1])
    # A parentId loop has no root to hang from; TickTick cannot make one, but
    # "never dropped" has to hold for any input, so each stray becomes a root.
    for it in sorted((i for i in items if i.id not in reached), key=_order):
        if it.id not in reached:
            out[slot[it.kind]].append(node(it, frozenset()))
            mark(out[slot[it.kind]][-1])
    out["unprefixed"] = sorted((i for i in items if i.kind is None), key=_order)
    out["misplaced"] = sorted(
        (i for i in items if i.kind and i.parent in by
         and by[i.parent].kind not in _FITS[i.kind]), key=_order)
    return out


def dangling(items):
    """[(parent id, child id)] for every childId that resolves to no item.

    Those are DELETED or WON'T-DO children. TickTick keeps a deleted
    child's id in its parent's childIds (five of them in the live list on
    2026-09-18), and a won't-do child is in neither read load() makes (v1
    data = the open tasks, v2 completed = status 2). The MCP answers "not
    found" for all five; the v1 GET is no referee - it answers 404 for some
    and, for others, a status-0 TRASHED task that looks open. Under the
    cache fallback, or a truncated completed read, a completed KR can land
    here too - load() says when that can be the case. Nothing else reads
    childIds: progress and the tree follow parentId."""
    by = index(items)
    return [(it.id, c) for it in items for c in it.children if c not in by]


# ── Spans + heal ─────────────────────────────────────────────────────────────
PARENT_KINDS = ("Y", "O")


def wanted_spans(items):
    """{id: (start, end)} for every Y and O with at least one DATED
    descendant: "an O runs from its first dated KR's start to its last dated
    KR's end; a Y the same over its O's" (HANDOFF section 4).

    Bottom-up: a Y/O child contributes its OWN wanted span when it has one
    (a stale stored span on an O must not stretch its Y), else its stored
    dates; a KR contributes its stored dates (its own subtasks do not move
    it). Undated children are ignored, abandoned ones too, and a parent with
    no dated child is absent - left alone, never undated."""
    kids = _kids(items)
    memo = {}

    def contrib(it, stack):
        if it.kind in PARENT_KINDS:
            w = want(it, stack)
            if w:
                return w
        return (it.start, it.end) if it.dated else None

    def want(it, stack):
        if it.id in memo:
            return memo[it.id]
        if it.id in stack:
            return None
        spans = [contrib(c, stack | {it.id}) for c in kids.get(it.id, [])
                 if not c.abandoned]
        spans = [s for s in spans if s]
        memo[it.id] = ((min(s[0] for s in spans), max(s[1] for s in spans))
                       if spans else None)
        return memo[it.id]

    out = {}
    for it in items:
        if it.kind in PARENT_KINDS:
            w = want(it, frozenset())
            if w:
                out[it.id] = w
    return out


def heal_diff(items):
    """[(id, want_start, want_end)] for every Y/O whose STORED dates differ
    from its wanted span, deepest first (an O before its Y), so a writer can
    apply them in order. A drag in TickTick never ripples - nothing can see
    it happen - but its parent heals on the next pass. A done or won't-do
    Y/O is HISTORY and is never a target: its span stays what it was when
    it closed."""
    by = index(items)
    want = wanted_spans(items)
    out = []
    for it in items:
        w = want.get(it.id)
        if w and not it.history and (it.start, it.end) != w:
            out.append((len(_ancestors(it, by)), it.id, w))
    out.sort(key=lambda r: -r[0])
    return [(iid, w[0], w[1]) for _d, iid, w in out]


def healed(items):
    """The items with heal_diff applied to replace()d copies: every open Y/O
    on its WANTED span, everything else as it is. The input is untouched.
    ripple_plan plans on this, so a stale stored span never becomes a
    delta."""
    fix = {iid: (s, e) for iid, s, e in heal_diff(items)}
    return [replace(it, start=fix[it.id][0], end=fix[it.id][1])
            if it.id in fix else it for it in items]


def _effective(it, want):
    """The span a Y/O is READ on: its wanted span when it has one, else its
    stored dates (pace and overlapping share this)."""
    if it.kind in PARENT_KINDS:
        w = want.get(it.id)
        if w:
            return w
    return it.start, it.end


# ── Progress + pace ──────────────────────────────────────────────────────────
def _deliverables(o, kids):
    """The KRs of one O: the items whose parentId is it - the tree's own
    rule, and the only one. childIds is NOT read: a KR moved to another O
    stays in the old one's childIds, and reading both counted it under
    both. A completed KR still counts, because load() reads it (v2
    project_completed) with its parentId. An abandoned child (won't do) is
    not a deliverable any more; an O or Y child is not a KR (misplaced -
    tree reports it)."""
    return [c for c in kids.get(o.id, [])
            if not c.abandoned and c.kind not in PARENT_KINDS]


def krs_of(item, items):
    """The KRs an item's numbers are made of: an O's own; a Y's = the KRs of
    all its O's plus any KR hung straight under it; a KR is its own. By
    parentId throughout."""
    kids = _kids(items)
    if item.kind == "O":
        return _deliverables(item, kids)
    if item.kind == "Y":
        out = []
        for c in kids.get(item.id, []):
            if c.abandoned or c.kind == "Y":
                continue
            out.extend(_deliverables(c, kids) if c.kind == "O" else [c])
        return list({k.id: k for k in out}.values())
    return [item]


def progress(item, items):
    """(done, total) - the ONLY number in Vex's OKRs: "Only number I see
    useful here is progress of Objective in our calculations by how much KRs
    where ticked off" (2026-09-18). Children by parentId only (krs_of), so
    each KR counts under exactly one O, and a completed KR still counts in
    the total when load() read it. A childId that resolves to nothing (a
    deleted or won't-do task, see dangling) counts in neither."""
    krs = krs_of(item, items)
    return sum(1 for k in krs if k.done), len(krs)


Pace = namedtuple("Pace", "expected actual behind_days elapsed")


def pace(item, items, today=None):
    """Pace from the dates alone (HANDOFF section 4):

      expected     dated KRs whose end is before today
      actual       done KRs (dated or not)
      behind_days  today minus the end of the earliest OPEN KR already past
                   its end; 0 when none is
      elapsed      0.0-1.0 through the item's span, None when it has none:
                   day N of M, TODAY COUNTED AS ELAPSED - (today - start)
                   + 1 day over the span's days, clamped; 0.0 before the
                   start, so the first day reads 1/M and the last 1.0. The
                   WANTED span when there is one - a stale stored span is
                   exactly what the next heal fixes, and pace should not
                   read it meanwhile.

    Undated KRs never count in expected or behind (a done one still counts
    in actual)."""
    today = today or date.today()
    krs = krs_of(item, items)
    dated = [k for k in krs if k.dated]
    expected = sum(1 for k in dated if k.end < today)
    actual = sum(1 for k in krs if k.done)
    late = [k.end for k in dated if not k.done and k.end < today]
    behind = (today - min(late)).days if late else 0
    s, e = _effective(item, wanted_spans(items))
    elapsed = None
    if s is not None:
        total = (e - s).days + 1
        elapsed = 0.0 if today < s else min(1.0, ((today - s).days + 1) / total)
    return Pace(expected, actual, behind, elapsed)


def overlapping(items, start, end, kinds=KINDS):
    """The plan for a period: dated items of `kinds` whose span touches
    start..end (inclusive both ends), in start order. kinds=None = every
    item, unprefixed too. Done items stay in: they were the plan.

    A Y/O is tested (and ordered) on its WANTED span when it has one - the
    fallback pace uses - never on a stale stored one: live 2026-09-18,
    🥅 O • Workflows was stored 1-24 Dec while its Typinator WF ran 26-30
    Nov, and November's plan must show the O. An undated O whose KRs are
    dated is in the plan too. The items come back as they are (stored
    dates); only the test reads the wanted span.
    The periodic notes read this (HANDOFF section 4): 🎉 Year = Y's (+ O's),
    🌓 Quarter = O's, 🗓️ Month = O's + KRs, ♻️ Week and ☀️ Day = KRs."""
    want = wanted_spans(items)
    out = []
    for it in items:
        if kinds is not None and it.kind not in kinds:
            continue
        s, e = _effective(it, want)
        if s is not None and s <= end and e >= start:
            out.append((s, it))
    out.sort(key=lambda r: (r[0], r[1].name))
    return [it for _s, it in out]


# ── Ripple ───────────────────────────────────────────────────────────────────
def lane_of(item, items):
    """The lane a schedule action ripples in (decided 2026-09-18: SAME Y
    OBJECTIVE): the item's topmost Y ancestor (itself when it is a Y); no Y
    = its topmost O; neither = the root of its own tree."""
    chain = [item] + _ancestors(item, index(items))
    ys = [x for x in chain if x.kind == "Y"]
    if ys:
        return ys[-1]
    os_ = [x for x in chain if x.kind == "O"]
    return os_[-1] if os_ else chain[-1]


def _span_leaves(item, kids, want):
    """The items that SHAPE a Y/O's wanted span: its children, recursing
    through child Y/O's down to the KRs (and any unprefixed step) - never
    into a KR's own subtasks, which do not move it. Abandoned ones shape
    nothing and are left out, as wanted_spans leaves them out.

    A child Y/O with NO wanted span of its own (an O dated by hand before it
    has a dated KR) is a leaf itself: wanted_spans counts its stored dates
    (contrib), so it shapes its parent exactly like a KR does, and an extend
    that ends on it has to move IT (review 2026-09-18: without this, a Y
    whose end came from such an O moved some KR and never lengthened)."""
    out, todo, seen = [], [item.id], {item.id}
    while todo:
        for c in kids.get(todo.pop(), []):
            if c.id in seen or c.abandoned:
                continue
            seen.add(c.id)
            if c.kind in PARENT_KINDS and c.id in want:
                todo.append(c.id)
            else:
                out.append(c)
    return out


def _shift(x, days):
    return x.start + timedelta(days=days), x.end + timedelta(days=days)


def ripple_plan(items, moved_id, new_start, new_end):
    """What a schedule action on one item does to the plan -> (moves, heals).

    moves  [(id, new_start, new_end)], the item that actually moves first
    heals  heal_diff of the plan AFTER the moves (an id may be in both - a
           writer applies moves, then heals, and the heal wins)

    HEAL FIRST. The plan is made on healed(items): every open Y/O on its
    WANTED span. A timeline drag leaves a parent's stored span stale until
    the next heal (live 2026-09-18: 🥅 O • TickAL stored 29 Sep - 14 Oct
    while its Goals wf starts 19 Sep), and reading the stale one would turn
    "put TickAL on 19 Sep - 14 Oct" - the span it already has - into a
    ten-day pull-in of every KR under it. So the deltas and the successor
    threshold below all read healed spans.

    The rule (HANDOFF section 4, decided 2026-09-18): the move changes the
    item's END by D days. Every DATED item in the same lane (lane_of) whose
    start is AFTER the item's inclusive end (as it was) shifts by the same
    D. The item's own descendants move WITH it, by the change of its START
    (a move / pick-a-date on a Y or O shifts its whole subtree). Its
    ancestors never shift - they heal. Items that overlap it (start on or
    before its old end) stay put, and so does anything undated, and anything
    in another lane. Negative D (pulling in) is the same rule mirrored - to
    be flagged to Vex when phase 2 ships.

    EXTEND ON A PARENT goes to its last deliverable. A Y/O's span is its
    KRs', so a Y/O with dated deliverables whose START stays and END moves
    (extend +N, or pulling its end in) hands the change down: to its
    last-ending OPEN dated deliverable, recursively (a Y through its O's)
    down to a KR (or to a child O dated by hand that has no dated KR yet -
    _span_leaves). That deliverable is given the PARENT's requested end, so
    the parent lands on it even when a done KR is what ended it (review
    2026-09-18: handing the KR only "+D" left the O short and opened a
    D-day hole in front of the next one). The lane then ripples by the
    parent's D, from the PARENT's old end - an item overlapping the
    parent's tail is inside it, not after it. If the parent still cannot
    land on the requested end (another open KR ends after a pulled-in end,
    or a done one does), the plan is REFUSED: ValueError naming the KR to
    move instead, never a plan whose heal quietly undoes the request.
    Every deliverable done = nothing open to extend: ValueError too.

    HISTORY NEVER MOVES. A done or won't-do item is skipped by the
    successor shift and by the descendant shift alike - it stays where it
    was when it closed - and a schedule action on one is refused: its
    stored span is never healed, so a delta read off it is stale by design.

    An UNDATED item getting dates has no old end, so it ripples nothing.
    Absolute dates must be read off healed(items), never off a Snapshot's
    stored items (schedule_plan does that for the three actions).
    Pure: returns the plan, writes nothing."""
    if new_start is None or new_end is None or new_end < new_start:
        raise ValueError(f"bad span {new_start}..{new_end}")
    plan = healed(items)
    by = index(plan)
    m = by[moved_id]
    if m.history:
        raise ValueError(f"{m.name!r} is closed - reopen it before moving it")
    kids = _kids(plan)
    anchor = None               # the parent an extend was handed down from
    if m.kind in PARENT_KINDS and m.dated and new_start == m.start and new_end != m.end:
        want = wanted_spans(plan)
        leaves = [x for x in _span_leaves(m, kids, want) if x.dated]
        if leaves:
            live = [x for x in leaves if not x.history]
            if not live:
                raise ValueError(f"nothing open to extend under {m.name!r}: "
                                 f"every dated deliverable is done")
            t = max(live, key=lambda x: (x.end, x.start, x.id))
            if new_end < t.start:
                raise ValueError(f"bad span {t.start}..{new_end} for {t.name!r}")
            anchor = m
            m, new_start = t, t.start
    moves = {m.id: (new_start, new_end)}
    if m.dated:
        mine = _descendants(m.id, kids)
        s_delta = (new_start - m.start).days
        # the lane follows the PARENT when the change was handed down to a KR
        edge = anchor or m
        d = (new_end - edge.end).days
        if s_delta:
            for did in mine:
                x = by[did]
                if x.dated and not x.history:
                    moves[did] = _shift(x, s_delta)
        if d:
            lane = lane_of(m, plan)
            members = {lane.id} | _descendants(lane.id, kids)
            skip = {m.id} | mine | {a.id for a in _ancestors(m, by)}
            for xid in members - skip:
                x = by[xid]
                if x.dated and not x.history and x.start > edge.end:
                    moves[xid] = _shift(x, d)
    # The heal is judged against what is STORED: every item not moved keeps
    # its stored dates here, so a stale span anywhere still shows up.
    after = [replace(it, start=moves[it.id][0], end=moves[it.id][1])
             if it.id in moves else it for it in items]
    if anchor is not None:
        got = wanted_spans(after).get(anchor.id)
        if got != (anchor.start, new_end):
            longer = [x for x in _span_leaves(anchor, _kids(after), wanted_spans(after))
                      if x.dated and x.end > new_end]
            x = longer[0] if longer else None
            who = ("" if x is None else
                   f" - {x.name!r} is done and ends {x.end}" if x.history else
                   f" - {x.name!r} ends {x.end}, move that one")
            raise ValueError(f"{anchor.name!r} cannot end on {new_end}{who}")
    first = [(m.id,) + moves[m.id]]
    rest = sorted(((i,) + se for i, se in moves.items() if i != m.id),
                  key=lambda r: (r[1], r[0]))
    return first + rest, heal_diff(after)


SCHEDULE_ACTIONS = ("extend", "tomorrow", "date")


def schedule_plan(items, item_id, action, arg=None, today=None):
    """The three schedule actions (HANDOFF section 4: "extend duration. Move
    to tomorrow or pick a date" - no time entry) -> ripple_plan's (moves,
    heals). The absolute dates are read off healed(items), so a caller
    holding a Snapshot's STORED items cannot hand ripple_plan a stale span
    (review 2026-09-18: "extend TickAL +2" computed off the stored span
    became a subtree move that put Goals wf on the wrong week).

      extend    arg = N days (negative pulls the end in); start stays
      tomorrow  start = today + 1, the length kept (an undated item = 1 day)
      date      arg = the new start date, the length kept"""
    today = today or date.today()
    it = index(healed(items))[item_id]
    length = (it.end - it.start).days if it.dated else 0
    if action == "extend":
        if not it.dated:
            raise ValueError(f"{it.name!r} has no dates to extend - pick a date first")
        return ripple_plan(items, item_id, it.start,
                           it.end + timedelta(days=int(arg or 0)))
    if action in ("tomorrow", "date"):
        start = today + timedelta(days=1) if action == "tomorrow" else arg
        if not isinstance(start, date):
            raise ValueError(f"no date to move {it.name!r} to")
        return ripple_plan(items, item_id, start, start + timedelta(days=length))
    raise ValueError(f"unknown schedule action {action!r}")


# ── Auto-tick ────────────────────────────────────────────────────────────────
def autotick_candidates(items, is_done):
    """Open KRs whose link points at a SINGLE task that is completed (decided
    2026-09-18: yes, on refresh and hourly sync). is_done(pid, tid) -> True
    | False | None is injected so this stays pure; only True ticks - unknown
    never does. A KR linked to a list, a note, a URL or nothing is ticked by
    hand; a note never reads as done (the lookup's job - see done_lookup)."""
    out = []
    for it in sorted(items, key=_order):
        if it.kind != "KR" or it.done or it.abandoned:
            continue
        tg = it.target
        if tg and tg[0] == "task" and is_done(tg[1], tg[2]) is True:
            out.append(it)
    return out


# ── Codes ────────────────────────────────────────────────────────────────────
# An O's code lives in its DESCRIPTION (HANDOFF section 2), on a line of its
# own led by the label emoji: "🏷️ TA" (VS16 optional, a "- " bullet allowed).
# 🏷 because it is the one emoji that reads "this is its label", and nothing
# else the workflow writes into a task description starts a line with it.
CODE_MARK = "🏷️"
_CODE_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?\U0001F3F7\ufe0f?\s*(?P<code>\w{1,16})\s*$", re.M)
_WORD_RE = re.compile(r"[^\W_]+")


def code_line(code):
    """The description line code_of reads back."""
    return f"{CODE_MARK} {code}"


def _humps(word):
    """First letters of the camel-case humps. A run of capitals is ONE hump
    (an acronym): TickAL -> Tick + AL -> T, A. HTMLParser -> H, P."""
    out = []
    for i, ch in enumerate(word):
        prev = word[i - 1] if i else ""
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if (i == 0
                or (ch.isupper() and (prev.islower() or prev.isdigit()))
                or (ch.isupper() and prev.isupper() and nxt.islower())
                or (ch.isdigit() and not prev.isdigit())):
            out.append(ch)
    return out


def _acronym(word):
    """The capitals (and digits) of a word written in capitals - "YNAB",
    "CRM", or with only a plural s after them, "OKRs" - else None: a word
    with any other lower-case letter is mixed case and goes by its humps."""
    core = word[:-1] if len(word) > 1 and word.endswith("s") else word
    if any(ch.islower() for ch in core) or not any(ch.isupper() for ch in core):
        return None
    return [ch for ch in core if ch.isupper() or ch.isdigit()]


def propose_code(name):
    """The code offered when an O is created (Vex confirms or types his own):
    several words = the first letter of each; one word written in capitals
    = its capitals (YNAB -> YNA, CRM -> CRM, OKRs -> OKR - a trailing plural
    s does not make it mixed case); one mixed-case word = its humps' first
    letters (TickAL -> TA, VexOS -> VO). At most three, upper case;
    "Onboard TickTick" -> OT (HANDOFF section 2). "" when the name has no
    letters at all."""
    words = _WORD_RE.findall(_flatten(name or ""))
    if not words:
        return ""
    if len(words) > 1:
        letters = [w[0] for w in words]
    else:
        letters = _acronym(words[0]) or _humps(words[0])
    return "".join(letters)[:3].upper()


def _majority(codes):
    """The candidate held by MORE than half of the ones given, else None -
    a tie or a scatter ("Monday", "Tuesday", "TA") names nothing."""
    c = Counter(x for x in codes if x)
    if not c:
        return None
    top, n = c.most_common(1)[0]
    return top if n * 2 > sum(c.values()) else None


def code_of(o_item, kr_items):
    """An O's code: the 🏷️ line in its description; else a code on its own
    title; else the MAJORITY candidate suffix among its KRs (more than half
    of the KRs that carry one; a tie names nothing); else None. It reads
    the KRs' CANDIDATES (Item.suffix), so a settled list and a raw one give
    the same answer. Existing suffixes are never corrected - the live
    Onboard TickTicks KRs say TT where his note said OT, and TT is what they
    keep."""
    raw = o_item.raw or {}
    text = pm.unescape_md((raw.get("content") or "") + "\n" + (raw.get("desc") or ""))
    m = _CODE_LINE_RE.search(text)
    if m:
        return m.group("code")
    if o_item.code:
        return o_item.code
    cands = [k.suffix if k.suffix is not None else k.code for k in kr_items]
    top = _majority(cands)
    # A word that is not all caps must be CARRIED to be a code: at least two
    # KRs (review 2026-09-18). One "Call Anna - Monday" under a fresh O would
    # otherwise vote itself in, and every KR added later would inherit
    # " - Monday". The live Shortcuts (16) and Audit (6) are untouched.
    if top and not _caps(top) and sum(1 for c in cands if c == top) < 2:
        return None
    return top


def _caps(code):
    """All caps: 2-6 letters/digits, every letter a capital, at least one
    letter (TA, TT, OT, Q4, USA - but not 2027, which is a year)."""
    return bool(code) and 2 <= len(code) <= 6 and code.isalnum() and code.isupper()


def settle_codes(items):
    """Candidates -> codes, in context (review 2026-09-18). Vex's live codes
    are not always caps - 16 KRs end " - Shortcuts" and 6 " - Audit", and
    those ARE codes - so a title alone cannot tell "Eagle - Audit" (a code)
    from "Call Anna - Monday" (a name). Its O can: an O's code is its 🏷️
    line, else its title code, else the MAJORITY candidate among its KRs
    (code_of). A KR whose candidate differs from its O's code AND is not all
    caps (_caps) gets the suffix folded back into its name, code None:
    "Call Anna - Monday" under TickAL keeps its whole name, and "Q4 money -
    2027" keeps 2027 in the name unless the O's code IS 2027. An all-caps
    candidate always stays a code. A KR with no O above it (orphan, or under
    a Y) is judged against no code. Y and O titles are left as parsed.
    Returns new Items (replace()d); the input is untouched."""
    by = index(items)
    kids = _kids(items)
    o_code = {it.id: code_of(it, _deliverables(it, kids))
              for it in items if it.kind == "O"}
    out = []
    for it in items:
        cand = it.suffix
        if it.kind == "KR" and cand:
            o = next((a for a in _ancestors(it, by) if a.kind == "O"), None)
            if cand != (o_code.get(o.id) if o else None) and not _caps(cand):
                if it.title:
                    _k, name, _l, _c = _parse(it.title, split_code=False)
                else:
                    name = f"{it.name}{CODE_SEP}{cand}"
                it = replace(it, name=name, code=None)
        out.append(it)
    return out


# ── Loader (the impure part) ─────────────────────────────────────────────────
COMPLETED_DAYS = 400      # a year of KRs, with room for a late tick
COMPLETED_LIMIT = 1000


class OkrLoadError(RuntimeError):
    """Neither the network nor the cache could say what is in the list.
    Raised rather than returning [] - "no items" and "could not read" must
    never look the same."""


@dataclass
class Snapshot:
    items: list
    source: str               # "live" | "cache"
    detail: str               # which reads answered, and why a fallback
    list_id: str
    name: str = ""
    # True only when v2 project_completed ANSWERED and came back under
    # COMPLETED_LIMIT rows: every completed KR of the window is in `items`.
    done_complete: bool = False

    @property
    def writable(self):
        """THE WRITER RULE (module docstring): a heal, an auto-tick or a
        ripple may write only from a live read with every completed KR."""
        return self.source == "live" and self.done_complete


def _age(cache_store, key):
    a = cache_store.age_seconds(key)
    if a is None:
        return "age unknown"
    return f"{int(a // 60)} min old" if a < 5400 else f"{a / 3600:.1f} h old"


def _why(e, at_import=False):
    """One failure as text. The interpreter hint only where it can be the
    cause: an ImportError or TypeError raised while IMPORTING the client
    (the vendored requests needs 3.10+, and Apple's 3.9 fails there with
    "unsupported operand type(s) for |"). A timeout on 3.9 is a timeout."""
    msg = f"{type(e).__name__}: {e}"
    if (at_import and isinstance(e, (ImportError, TypeError))
            and sys.version_info < (3, 10)):
        msg += (" - this python is %d.%d and the vendored requests needs 3.10+"
                " (bash Scripts/py.sh src/okr.py)" % sys.version_info[:2])
    return msg


def _shape(data):
    if isinstance(data, dict):
        return "a dict without a task list (keys: %s)" % (", ".join(sorted(map(str, data))[:6]) or "none")
    return f"a {type(data).__name__}"


def load(api=None, v2=None, list_id=None):
    """The OKR list -> Snapshot. READ-ONLY: GETs only, and not even the local
    cache is written.

    Live = v1 get_project_data (the OPEN tasks; the client is built the way
    periodic_engine._api builds it) + v2 project_completed over
    COMPLETED_DAYS (the completed ones - without them a ticked KR would drop
    out of its O's total). done_complete is True only when v2 answered with
    fewer than COMPLETED_LIMIT rows; the detail says "v2 completed
    unavailable" when it did not answer and warns when it hit the limit.

    v1 answering something that is not a dict with a list under "tasks" is
    OkrLoadError on the spot - a changed answer is not an empty plan, and
    not a reason to show the cache either. v1 FAILING (network, HTTP,
    import) = the cache: project_data_<pid> (what the hourly sync keeps),
    else all_tasks filtered to the list - where no row at all is an error
    unless the cached lists show the list exists (an empty list is real, a
    list the cache never saw is not) - plus the account-wide completed_tasks
    feed, which only holds the newest completions: the detail says so,
    because an older completed KR then reads as deleted. v2 failing alone
    keeps v1's live open tasks and takes completed ones from that same
    feed. Nothing readable = OkrLoadError, never an empty plan.

    Only a live read with done_complete may feed a writer (Snapshot.
    writable, the module docstring's writer rule)."""
    import cache as cache_store
    import config as cfg
    pid = list_id or cfg.get_okr_list_id()
    if not pid:
        raise OkrLoadError("no OKR list - okr_list_id is set blank")
    done_rows, name, notes, done_complete = None, "", [], False
    stage = "import"
    try:
        if api is None:
            from api import TickTickAPI
            stage = "client"
            api = TickTickAPI(cfg.get_token())
        stage = "read"
        data = api.get_project_data(pid)
    except Exception as e:
        data, why = None, _why(e, at_import=stage == "import")
    else:
        if not (isinstance(data, dict) and isinstance(data.get("tasks"), list)):
            if data == {}:
                # live v1 answers HTTP 200 with {} for a list id that does
                # not exist (probed 2026-09-18) - say THAT, not "keys: none"
                raise OkrLoadError(f"list {pid} not found (v1 answered {{}}) "
                                   f"- check okr_list_id")
            raise OkrLoadError(f"v1 answered {_shape(data)} for list {pid}")
    if data is not None:
        source = "live"
        open_rows = data["tasks"]
        name = (data.get("project") or {}).get("name") or ""
        notes.append(f"v1 open {len(open_rows)}")
    else:
        source = "cache"
        pd = cache_store.get(f"project_data_{pid}")
        if isinstance(pd, dict) and isinstance(pd.get("tasks"), list):
            open_rows = pd["tasks"]
            name = (pd.get("project") or {}).get("name") or ""
            notes.append(f"live read failed ({why}); open {len(open_rows)} from "
                         f"the project_data cache ({_age(cache_store, f'project_data_{pid}')})")
        else:
            allt = cache_store.get("all_tasks")
            if not isinstance(allt, list):
                raise OkrLoadError(f"live read failed ({why}) and there is no "
                                   f"cache of list {pid} to fall back on")
            open_rows = [t for t in allt if isinstance(t, dict) and t.get("projectId") == pid]
            projects = cache_store.get("projects")
            known = next((p for p in projects or [] if isinstance(p, dict)
                          and p.get("id") == pid), None) if isinstance(projects, list) else None
            if not open_rows and known is None:
                raise OkrLoadError(f"live read failed ({why}), and the all_tasks cache "
                                   f"has no row of list {pid} while the cached lists do "
                                   f"not show it exists")
            name = (known or {}).get("name") or ""
            notes.append(f"live read failed ({why}); open {len(open_rows)} from "
                         f"the all_tasks cache ({_age(cache_store, 'all_tasks')})")
    if source == "live":
        stage = "import"
        try:
            if v2 is None:
                from api_v2 import TickTickV2
                stage = "client"
                v2 = TickTickV2()
            stage = "read"
            done_rows = v2.project_completed(pid, days=COMPLETED_DAYS,
                                             limit=COMPLETED_LIMIT)
        except Exception as e:
            notes.append(f"v2 completed unavailable ({_why(e, at_import=stage == 'import')})")
            done_rows = None
        else:
            if not isinstance(done_rows, list):
                notes.append("v2 completed unavailable")
                done_rows = None
            elif len(done_rows) >= COMPLETED_LIMIT:
                notes.append(f"v2 completed {len(done_rows)} ({COMPLETED_DAYS} d) - "
                             f"TRUNCATED at the {COMPLETED_LIMIT}-row limit: an older "
                             f"completed KR reads as deleted")
            else:
                done_complete = True
                notes.append(f"v2 completed {len(done_rows)} ({COMPLETED_DAYS} d)")
    if done_rows is None:
        feed = cache_store.get("completed_tasks")
        if isinstance(feed, list) and feed:
            done_rows = [t for t in feed if isinstance(t, dict) and t.get("projectId") == pid]
            notes.append(f"completed {len(done_rows)} from the account-wide cache "
                         f"feed (newest {len(feed)} only, {_age(cache_store, 'completed_tasks')}): "
                         f"an older completed KR reads as deleted")
        elif isinstance(feed, list):
            done_rows = []
            notes.append(f"the completed cache feed is empty "
                         f"({_age(cache_store, 'completed_tasks')}): a ticked KR reads as deleted")
        else:
            done_rows = []
            notes.append("no completed tasks readable: a ticked KR reads as deleted")
    seen = {t.get("id") for t in open_rows}
    rows = list(open_rows) + [t for t in done_rows
                              if t.get("id") not in seen and not t.get("deleted")]
    return Snapshot(items_from(rows), source, "; ".join(notes), pid, name, done_complete)


def done_lookup(api=None):
    """is_done(pid, tid) for autotick_candidates: True only for a COMPLETED
    task (status 2), False for anything else it can see, None when it
    cannot tell - and None never ticks.

    The live GET decides: the original is reality, and a stale cache must
    not tick a KR. v1 get_task answers a TRASHED task as status 0 (not a
    404), so a trashed original reads open and never ticks - only status 2
    ever does. A note is never done. A GET that FAILS (network, 404, an
    answer that is not a task) is None: unknown.

    The caches answer only when no client can be built at all (no token, an
    interpreter that cannot import the API): the OPEN cache first - a task
    reopened after its completion sits in both, and open is the newer truth
    - then the completed feed; neither = None. Memoized per call site."""
    memo = {}
    box = {"api": api, "broken": False}

    def client():
        if box["api"] is None and not box["broken"]:
            try:
                import config as cfg
                from api import TickTickAPI
                box["api"] = TickTickAPI(cfg.get_token())
            except Exception:
                box["broken"] = True
        return box["api"]

    def cached(pid, tid):
        import cache as cache_store
        open_rows = list(cache_store.get("all_tasks") or [])
        pd = cache_store.get(f"project_data_{pid}")
        if isinstance(pd, dict):
            open_rows += list(pd.get("tasks") or [])
        for t in open_rows:
            if isinstance(t, dict) and t.get("id") == tid:
                return False
        for t in cache_store.get("completed_tasks") or []:
            if isinstance(t, dict) and t.get("id") == tid:
                return t.get("kind") != "NOTE"
        return None

    def is_done(pid, tid):
        if (pid, tid) in memo:
            return memo[(pid, tid)]
        c = client()
        if c is None:
            verdict = cached(pid, tid)
        else:
            try:
                t = c.get_task(pid, tid)
                verdict = (t.get("kind") != "NOTE" and t.get("status") == 2
                           if isinstance(t, dict) and t.get("id") else None)
            except Exception:
                verdict = None
        memo[(pid, tid)] = verdict
        return verdict

    return is_done


# ── __main__: the live tree, read-only ───────────────────────────────────────
def _d(d, today):
    s = f"{pm.MONTH_ABBR[d.month]} {d.day}"
    return s if d.year == today.year else f"{s} {d.year}"


def _span_txt(s, e, today):
    if s is None:
        return "undated"
    return _d(s, today) if s == e else f"{_d(s, today)} - {_d(e, today)}"


def _link_txt(it):
    tg = it.target
    return "no link" if not tg else f"link {tg[0]}"


def _row(it, items, today, depth):
    pad = "    " * depth
    head = (PREFIX.get(it.kind, "") + it.name) if it.kind else f"(unprefixed) {it.name}"
    bits = [_span_txt(it.start, it.end, today)]
    if it.kind in PARENT_KINDS:
        krs = krs_of(it, items)
        code = code_of(it, krs) if it.kind == "O" else None
        if code:
            bits.append(f"code {code}")
        done, total = progress(it, items)
        bits.append(f"{done}/{total} KRs")
        p = pace(it, items, today)
        el = "-" if p.elapsed is None else f"{round(p.elapsed * 100)}%"
        bits.append(f"pace {p.actual} done of {p.expected} due, "
                    f"behind {p.behind_days}d, {el} elapsed")
    else:
        if it.code:
            bits.append(f"code {it.code}")
        state = "done" if it.done else "open"
        if not it.done and it.dated and it.end < today:
            state = f"late {(today - it.end).days}d"
        bits.append(state)
    bits.append(_link_txt(it))
    return f"{pad}{head}  ·  " + "  ·  ".join(bits)


def _walk(node, items, today, depth, out):
    it, kids = node
    out.append(_row(it, items, today, depth))
    for k in kids:
        _walk(k, items, today, depth + 1, out)


def report(snap, today=None, is_done=None):
    """The printable read-only report of a Snapshot (lines)."""
    today = today or date.today()
    items = snap.items
    by = index(items)
    t = tree(items)
    out = [f"OKR list {snap.name or '?'} ({snap.list_id})",
           f"source: {snap.source} - {snap.detail}",
           "writers: " + ("allowed (live, every completed KR read)" if snap.writable
                          else "would REFUSE (not a live read with every completed KR)"),
           f"today {today.isoformat()} · {len(items)} items", ""]
    for key, label in (("years", "🏔️ Year objectives"),
                       ("orphan_os", "🥅 Objectives without a Y (each its own lane)"),
                       ("orphan_krs", "🔑 KRs without an O"),
                       ("loose", "Unprefixed roots")):
        if not t[key]:
            continue
        out.append(f"{label}:")
        for n in t[key]:
            _walk(n, items, today, 1, out)
        out.append("")
    heals = heal_diff(items)
    out.append(f"Heal (would write, read-only here): {len(heals) or 'none'}")
    for iid, s, e in heals:
        it = by[iid]
        out.append(f"    {PREFIX.get(it.kind, '')}{it.name}: "
                   f"{_span_txt(it.start, it.end, today)} -> {_span_txt(s, e, today)}")
    ticks = autotick_candidates(items, is_done or (lambda p, t_: None))
    linked = sum(1 for it in items if it.kind == "KR" and not it.done
                 and (it.target or ("",))[0] == "task")
    out.append(f"Auto-tick (would tick, read-only here): {len(ticks) or 'none'}"
               f" ({linked} open KRs link a single task)")
    for it in ticks:
        out.append(f"    {PREFIX['KR']}{it.name}")
    dang = dangling(items)
    out.append(f"Dangling childIds (deleted or won't-do, counted nowhere): {len(dang) or 'none'}")
    if t["unprefixed"]:
        out.append("Unprefixed: " + ", ".join(i.name for i in t["unprefixed"]))
    if t["misplaced"]:
        out.append("Misplaced: " + ", ".join(
            f"{PREFIX[i.kind]}{i.name} under {by[i.parent].kind or 'unprefixed'}"
            for i in t["misplaced"]))
    return out


def _modern_python():
    """`python3` on this Mac is Apple's 3.9, and the vendored requests needs
    3.10+ (reference: the interpreter ladder, 2026-09-15) - so a plain
    `python3 src/okr.py` could only ever show the cache. Hop once onto the
    workflow's own ladder (Scripts/py.sh) instead; the env guard stops a
    second hop, and a machine without 3.10+ gets py.sh's own message."""
    if sys.version_info >= (3, 10) or os.environ.get("TICKAL_PY_HOP"):
        return
    here = os.path.abspath(__file__)
    ladder = os.path.join(os.path.dirname(os.path.dirname(here)), "Scripts", "py.sh")
    if not os.path.exists(ladder):
        return
    os.environ["TICKAL_PY_HOP"] = "1"
    try:
        os.execv("/bin/bash", ["bash", ladder, here] + sys.argv[1:])
    except OSError:
        return


def main():
    snap = load()
    print("\n".join(report(snap, is_done=done_lookup())))


if __name__ == "__main__":
    _modern_python()
    try:
        main()
    except OkrLoadError as e:
        print(f"OKR list unreadable: {e}")
        sys.exit(1)
