#!/usr/bin/env python3
"""okr_stats.py - what the real work gave the plan (HANDOFF_OKR phase 5):
the aligned-work ratio and focus per objective. Pure: the caller hands in
the plan's items and the task rows it knows; nothing here reads a cache or
the network.

ALIGNED (Vex 2026-09-18, "Not sure I understand alligned work ration thing,
but it sounds interesting. You can go for it. I will see it in practice"):
a completed task SERVED an objective when it is the real thing a plan item
links (the planning copy's title link - "the copy is the plan, the original
is reality"), sits under one (a subtask at any depth), or lives in a list an
item links. A 📌CTA task links its project's list in its own title, so an O
linked to its CTA covers the whole list, and an O linked to the list covers
its CTA - focus mostly lands on the CTA, whose id changes when it is
re-minted, but whose title keeps the list link. Links are the ONLY join:
the 💼 tags on the copies live in the plan list alone (checked live
2026-09-19), so an unlinked plan aligns nothing, and says so.

Every match is credited to an OWNER: the O a KR sits under (the numbers are
per objective), the O itself, a Y itself; a KR hung straight under a Y is
the Y's, and a KR with no parent at all owns its own. When two items link
the same thing, an OPEN one wins over a closed one (a done O from last
quarter must not take this week's work from the O running now), then plan
order. The plan list's own rows are never real work.

A CTA is known by its list (the 📌CTA list id, when the caller has it) or by
its title shape ("💼 P • [name](list link)", areas.build_action) - the
hourly and 04:30 runs have no Alfred env, so the list id is often "" there
and the shape has to do. `cta_lists` ({CTA task id: [list ids]}) is the
caller's memory of CTA titles already seen: an O keeps linking the CTA it
was imported with, and once that task is completed and gone from every
cache, its row cannot say which list it opened.
"""
import re
from datetime import datetime, timezone

import okr
import periodic_model as pm

_CTA_RE = re.compile(r"^[^\w\s]{1,8}\s*P\s+[•·]\s+\[")    # "💼 P • [name](...)"

MAX_DEPTH = 12            # parentId hops; TickTick nests 5 deep, a loop stops


def _pid(t):
    return (t or {}).get("projectId") or (t or {}).get("_projectId") or ""


def _title_lists(title):
    """The lists a title links ("💼 P • [TickAL](list link) 🔗")."""
    import okr_write
    return [tg[1] for tg in okr_write._title_targets(title or "") if tg[0] == "list"]


def is_cta(row, cta=""):
    """A 📌CTA task: in the CTA list, or titled like one."""
    if not isinstance(row, dict):
        return False
    if cta and _pid(row) == cta:
        return True
    return bool(_CTA_RE.match(pm.unescape_md(row.get("title") or "").strip()))


def cta_list_map(rows, cta=""):
    """{CTA task id: [the lists its title links]} over the rows handed in -
    what a caller keeps (and merges into what it kept before) so a CTA that
    has left the caches still resolves."""
    out = {}
    for t in rows or ():
        if isinstance(t, dict) and t.get("id") and is_cta(t, cta):
            lists = _title_lists(t.get("title"))
            if lists:
                out[t["id"]] = lists
    return out


def owner_of(it, by):
    """The item a match on `it`'s link is credited to (module docstring)."""
    if it.kind in okr.PARENT_KINDS:
        return it
    for a in okr._ancestors(it, by):
        if a.kind == "O":
            return a
    for a in okr._ancestors(it, by):
        if a.kind == "Y":
            return a
    return it


class Aligned:
    """The join from real tasks to the plan's objectives.

    items  the plan (okr.Item), done ones included - a KR ticked last week
           still owns the subtasks finished under its original this week;
           won't-do ones are out
    rows   every real task row known (open + completed), for parent chains
           and the CTA titles
    plan   the plan list's id: its rows are copies, never real work"""

    def __init__(self, items, rows=(), plan="", cta="", cta_lists=None):
        self.plan = plan or ""
        self.cta = cta or ""
        self.by_item = okr.index(items)
        self.rows = {}
        for t in rows or ():
            if isinstance(t, dict) and t.get("id") and t["id"] not in self.rows:
                self.rows[t["id"]] = t
        known = dict(cta_lists or {})
        known.update(cta_list_map(self.rows.values(), self.cta))
        self.tasks, self.lists = {}, {}
        # open items claim first (the module docstring), then plan order
        for it in sorted(items, key=lambda x: (x.history, okr._order(x))):
            if it.abandoned or it.kind not in okr.KINDS:
                continue
            tg = it.target
            if not tg or tg[0] not in ("task", "list"):
                continue
            own = owner_of(it, self.by_item).id
            if tg[0] == "task":
                self.tasks.setdefault(tg[2], own)
                for lp in known.get(tg[2], ()):
                    self.lists.setdefault(lp, own)          # a CTA's project list
            else:
                self.lists.setdefault(tg[1], own)
        # the other face: a list's CTA task(s) - where the focus lands
        for tid, lps in known.items():
            for lp in lps:
                row = self.rows.get(tid)
                if lp in self.lists and _pid(row) != lp:
                    self.tasks.setdefault(tid, self.lists[lp])

    def any(self):
        """False when no plan item links anything: the ratio has nothing to
        read, and a 0% would lie."""
        return bool(self.tasks or self.lists)

    def owner(self, task, title=None):
        """The owner id `task` (a row, or {"id": ...} for a focus segment)
        served, else None. Tried in order: the task (or its repeat series),
        its list, its ancestors, a list its title links when it is titled
        like a CTA (a re-minted CTA, or a focus segment whose row is not
        cached - `title` is the segment's)."""
        if not isinstance(task, dict):
            return None
        if _pid(task) and _pid(task) == self.plan:
            return None
        seen, t = set(), task
        for _hop in range(MAX_DEPTH):
            if not t or t.get("id") in seen:
                break
            seen.add(t.get("id"))
            for key in (t.get("id"), t.get("repeatTaskId")):
                if key and key in self.tasks:
                    return self.tasks[key]
            if _pid(t) in self.lists:
                return self.lists[_pid(t)]
            parent = t.get("parentId")
            t = self.rows.get(parent) if parent else None
        text = title if title is not None else task.get("title")
        if is_cta({"title": text, "projectId": _pid(task)}, self.cta):
            for lp in _title_lists(text):
                if lp in self.lists:
                    return self.lists[lp]
        return None


def aligned_counts(done_rows, al):
    """(served, total, {owner id: n}) over the completed rows handed in (the
    caller already dropped the routines and the plan list)."""
    per = {}
    served = 0
    for t in done_rows or ():
        o = al.owner(t)
        if o is not None:
            served += 1
            per[o] = per.get(o, 0) + 1
    return served, len(done_rows or ()), per


def _ts(raw):
    try:
        return datetime.strptime((raw or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def segments(rec):
    """[(taskId, title, minutes)] of one focus record (v2 pomodoros/timeline):
    each task entry's OWN start-end segment, scaled so they add up to the
    record's net minutes (its span minus pauseDuration, in seconds). One
    entry = the whole net. Entries without a taskId are unattributed and
    dropped (their minutes still count in the week's Focus total)."""
    s, e = _ts(rec.get("startTime")), _ts(rec.get("endTime"))
    if s is None or e is None:
        return []
    net = max(0.0, (e - s).total_seconds() - float(rec.get("pauseDuration") or 0)) / 60.0
    tasks = [t for t in rec.get("tasks") or [] if isinstance(t, dict)]
    if not tasks:
        return []
    if len(tasks) == 1:
        raw = [1.0]
    else:
        raw = []
        for t in tasks:
            a, b = _ts(t.get("startTime")), _ts(t.get("endTime"))
            raw.append(max(0.0, (b - a).total_seconds()) if a and b else 0.0)
        if not sum(raw):
            raw = [1.0] * len(tasks)
    k = net / sum(raw)
    return [(t.get("taskId"), t.get("title") or "", w * k)
            for t, w in zip(tasks, raw) if t.get("taskId")]


def focus_per_owner(records, al):
    """{owner id: minutes} over focus records (already cut to the period by
    the caller): each segment credited through Aligned.owner - its task's
    row when cached (the chain, the list), else the segment's own title."""
    out = {}
    for rec in records or ():
        for tid, title, mins in segments(rec):
            row = al.rows.get(tid) or {"id": tid}
            o = al.owner(row, title=title)
            if o is not None:
                out[o] = out.get(o, 0.0) + mins
    return {k: int(round(v)) for k, v in out.items()}


def pts_chip(cur, prev):
    """The week-over-week chip of a PERCENTAGE, in points: "🟢 ▲ 7 pts" /
    "🔴 ▼ 7 pts" / "⚪ ▬" (pm.chip's glyphs; its (+P%) would be a relative
    change of a percentage, which reads as nonsense). None without a prev."""
    if cur is None or prev is None:
        return None
    d = cur - prev
    unit = "pt" if abs(d) == 1 else "pts"
    if d > 0:
        return f"🟢 ▲ {d} {unit}"
    if d < 0:
        return f"🔴 ▼ {-d} {unit}"
    return "⚪ ▬"


def pct(served, total):
    return round(100 * served / total) if total else None
