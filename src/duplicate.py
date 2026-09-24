"""duplicate.py - copy a task and its OPEN subtasks to another day, names untouched.

Vex 2026-09-13: "I often have one task scheduled for the day that is my main
work task which has some subtasks. At the end of the day I tick it off. What
I do before that to schedule it again for tomorrow is use TickTick duplicate,
and schedule that task, but that task has a word copy appended on every
subtasks and tasks name."

So this is "carry this task forward", not a clone:
  * every title stays EXACTLY as it is - no " Copy" on anything;
  * only OPEN subtasks come across (the finished ones are today's record and
    stay with today's task), as the same tree, in the same order;
  * the copy lands on the picked day; a picked start keeps the original's
    duration unless an end was picked too; dated subtasks move by the same
    amount the parent moved;
  * the copy never repeats - duplicating a repeating task must not start a
    second series;
  * description, priority, tags, list, section, reminders and a checklist's
    items come across (checklist items reopened).

plan() is pure. run() does the API work: parents are created before their
children, then ONE v2 batch restores the originals' sibling order (a v1 create
takes a DESCENDING sortOrder, and its response reports parentId null even
though the task IS attached - both restated in that batch, the
dispatch._order_children lesson).
"""
from datetime import datetime, timedelta

import focus_subtasks as fsub

_FMT = "%Y-%m-%dT%H:%M:%S"


def _dt(iso):
    try:
        return datetime.strptime((iso or "")[:19], _FMT)
    except ValueError:
        return None


def _iso(dt):
    return dt.strftime(_FMT) + "+0000"


def _all_day(iso):
    """A date-only pick: no time part, or midnight (see api._is_all_day)."""
    return not iso or len(iso) < 12 or iso[11:19] == "00:00:00"


def new_dates(root, start_iso, end_iso=None):
    """(startDate, dueDate, isAllDay, shift) for the copy.

    shift is how far the task moved (a timedelta), applied to dated subtasks;
    None when the original had no date to measure from."""
    o_start = _dt(root.get("startDate") or root.get("dueDate"))
    o_due = _dt(root.get("dueDate") or root.get("startDate"))
    n_start = _dt(start_iso)
    shift = (n_start - o_start) if (o_start and n_start) else None
    if end_iso:
        return start_iso, end_iso, False, shift
    if _all_day(start_iso):
        return None, start_iso, True, shift
    if o_start and o_due and o_due > o_start and not root.get("isAllDay"):
        return start_iso, _iso(n_start + (o_due - o_start)), False, shift
    return start_iso, start_iso, False, shift


def plan(root, open_desc, start_iso, end_iso=None, extra_reminders=()):
    """[{old, parent_old, fields}] in creation order: the root first, then its
    open subtree in display order (a parent always before its children).
    fields are create_task keyword arguments; parent_old is resolved to the
    NEW parent id by run()."""
    s, d, all_day, shift = new_dates(root, start_iso, end_iso)
    reminders = list(dict.fromkeys(list(root.get("reminders") or [])
                                   + [r for r in extra_reminders if r]))
    out = [{
        "old": root.get("id"), "parent_old": None,
        "sortOrder": root.get("sortOrder"),
        "items": root.get("items") or [],
        "fields": {k: v for k, v in {
            "title": root.get("title") or "Task",
            "project_id": root.get("projectId"),
            "content": root.get("content") or None,
            "priority": root.get("priority") or 0,
            "tags": root.get("tags") or None,
            "column_id": root.get("columnId") or None,
            "kind": root.get("kind") or None,
            "start_date": None if all_day else s,
            "due_date": d,
            "reminders": reminders or None,
        }.items() if v not in (None, [], "")},
    }]
    for t in open_desc or []:
        f = {
            "title": t.get("title") or "Task",
            "project_id": t.get("projectId") or root.get("projectId"),
            "content": t.get("content") or None,
            "priority": t.get("priority") or 0,
            "tags": t.get("tags") or None,
            "kind": t.get("kind") or None,
        }
        ts, td = _dt(t.get("startDate")), _dt(t.get("dueDate"))
        if shift is not None and (ts or td):
            if td:
                f["due_date"] = _iso(td + shift)
            if ts and not t.get("isAllDay"):
                f["start_date"] = _iso(ts + shift)
        elif ts or td:
            f["due_date"] = t.get("dueDate") or t.get("startDate")
            if ts and not t.get("isAllDay"):
                f["start_date"] = t.get("startDate")
        out.append({"old": t.get("id"), "parent_old": t.get("parentId"),
                    "sortOrder": t.get("sortOrder"), "items": t.get("items") or [],
                    "fields": {k: v for k, v in f.items() if v not in (None, [], "")}})
    return out


def run(api, v2, pid, tid, start_iso, end_iso=None, extra_reminders=()):
    """Create the copy. Returns (new_root_task, [new_child_tasks], problems)."""
    root = api.get_task(pid, tid)
    data = api.get_project_data(root.get("projectId") or pid) or {}
    open_desc = fsub.descendants(data.get("tasks") or [], tid)
    steps = plan(root, open_desc, start_iso, end_iso, extra_reminders)
    new_id, made, problems = {}, [], []
    for i, st in enumerate(steps):
        f = dict(st["fields"])
        if st["parent_old"] is not None:
            parent_new = new_id.get(st["parent_old"])
            if not parent_new:
                problems.append(f"skipped {f['title'][:30]!r}: its parent was not copied")
                continue
            f["parent_id"] = parent_new
        try:
            t = api.create_task(**f)
        except Exception as e:
            if i == 0:
                raise
            problems.append(f"{f['title'][:30]!r}: {type(e).__name__}")
            continue
        new_id[st["old"]] = t.get("id")
        if st["parent_old"] is not None:
            t["parentId"] = f["parent_id"]      # the response says null; it lies
        made.append((st, t))
        if st["items"]:
            try:
                api.update_task(t["id"], t.get("projectId") or pid, current=t,
                                items=[{"title": it.get("title", ""), "status": 0,
                                        "sortOrder": it.get("sortOrder", 0)}
                                       for it in st["items"]])
            except Exception as e:
                problems.append(f"checklist of {f['title'][:30]!r}: {type(e).__name__}")
    # the originals' sibling order, parents restated (see module docstring)
    bodies = []
    for st, t in made[1:]:
        b = {k: v for k, v in t.items() if not k.startswith("_")}
        b["parentId"] = new_id.get(st["parent_old"])
        b["projectId"] = t.get("projectId") or pid
        if st["sortOrder"] is not None:
            b["sortOrder"] = st["sortOrder"]
        bodies.append(b)
    if bodies:
        try:
            if not v2.update_tasks(bodies, fresh=True):    # this run's creates
                problems.append("subtask order not restored")
        except Exception:
            problems.append("subtask order not restored")
    kids = [t for _st, t in made[1:]]
    return (made[0][1] if made else None), kids, problems
