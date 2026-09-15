"""day_move.py - put a task on another day, keeping its time of day.

Vex 2026-09-15, picking a task as the daily goal: "Move to tomorrow, keep
time". The old goal road wrote T00:00:00+0000 into both dates, which is not
midnight here and reads as all-day, so a 16:00 task lost its time.

  * a TIMED task lands on the new day at the same local clock time, with its
    duration kept (an end that crossed midnight still does);
  * an UNTIMED or undated task becomes all-day on the new day;
  * a REPEATING task is left alone - moving its start moves the whole series,
    and the goal line links it either way;
  * a task already COMPLETED (the picker's pool is the hourly cache) is left
    alone too.

Dates go out as UTC "+0000" strings with isAllDay stated, never left to
api.update_task's guess. Pure: no I/O. `tz` defaults to the machine's
local zone, the one TickTick's Mac app shows.
"""
from datetime import datetime, time, timedelta, timezone

_FMT = "%Y-%m-%dT%H:%M:%S+0000"


def _parse(iso):
    """A TickTick date string -> aware UTC datetime | None."""
    if not iso or len(iso) < 19:
        return None
    try:
        base = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    off = iso[19:].lstrip(".0123456789")          # drop ".000" millis
    if off and off not in ("Z", "+0000", "+00:00"):
        try:
            sign = 1 if off[0] == "+" else -1
            hh, mm = int(off[1:3]), int(off[-2:])
            return (base - sign * timedelta(hours=hh, minutes=mm)).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return None
    return base.replace(tzinfo=timezone.utc)


def _local_tz():
    """The machine's zone as a DST-aware ZoneInfo (via /etc/localtime), so a
    move across a clock change keeps the wall-clock time; a fixed offset only
    when that cannot be read."""
    try:
        import os
        from zoneinfo import ZoneInfo
        link = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in link:
            return ZoneInfo(link.split("zoneinfo/", 1)[1])
    except Exception:
        pass
    return datetime.now().astimezone().tzinfo


def _out(dt):
    return dt.astimezone(timezone.utc).strftime(_FMT)


def is_timed(task, tz=None):
    """True when the task carries a real clock time (not all-day, not
    local midnight)."""
    if task.get("isAllDay"):
        return False
    start = _parse(task.get("startDate") or task.get("dueDate"))
    if start is None:
        return False
    local = start.astimezone(tz or _local_tz())
    return (local.hour, local.minute, local.second) != (0, 0, 0)


def move_fields(task, day, tz=None):
    """(fields, note). fields = {startDate, dueDate, isAllDay} for
    api.update_task - isAllDay EXPLICIT, because the api's guess reads any
    00:00 UTC as all-day and a 02:00 CEST task would lose its time - or None
    when the task must not be moved (note says why: 'repeats', 'done')."""
    if task.get("status") not in (None, 0) or task.get("deleted"):
        return None, "done"
    if task.get("repeatFlag"):
        return None, "repeats"
    tz = tz or _local_tz()
    if is_timed(task, tz):
        start = _parse(task.get("startDate") or task.get("dueDate"))
        due = _parse(task.get("dueDate"))
        span = (due - start) if due and due > start else timedelta(0)
        clock = start.astimezone(tz).time()
        new_start = datetime.combine(day, clock).replace(tzinfo=tz)
        return {"startDate": _out(new_start), "dueDate": _out(new_start + span),
                "isAllDay": False}, "timed"
    midnight = datetime.combine(day, time(0, 0)).replace(tzinfo=tz)
    return {"startDate": _out(midnight), "dueDate": _out(midnight), "isAllDay": True}, "all-day"


def occurs_on(task, day, tz=None):
    """True when the task's own (next) date falls on `day` locally."""
    start = _parse(task.get("startDate") or task.get("dueDate"))
    return bool(start) and start.astimezone(tz or _local_tz()).date() == day
