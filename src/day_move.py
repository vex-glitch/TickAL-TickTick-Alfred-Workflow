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


def all_day(day, tz=None):
    """{startDate, dueDate, isAllDay, timeZone} putting something on `day` as
    an all-day item: local midnight written in UTC (a bare date is accepted
    and silently dropped by v1), the zone NAMED so TickTick reads the day in
    it and not in the account's. The periodic notes sit on their period's
    last day this way (Vex 2026-09-19)."""
    tz = tz or _local_tz()
    stamp = _out(datetime.combine(day, time(0, 0)).replace(tzinfo=tz))
    out = {"startDate": stamp, "dueDate": stamp, "isAllDay": True}
    name = getattr(tz, "key", None)
    if name:
        out["timeZone"] = name
    return out


def _midnight(dt):
    return (dt.hour, dt.minute, dt.second) == (0, 0, 0)


def _all_day_of(task, first, tz):
    """Is this task all-day - its flag weighed against its first stamp (an
    aware local datetime). See shift_fields."""
    utc_mid = _midnight(first.astimezone(timezone.utc))
    here_mid = _midnight(first)
    flag = task.get("isAllDay")
    if flag is None:
        return utc_mid or here_mid
    if not flag:
        return utc_mid
    own_mid = False
    try:
        from zoneinfo import ZoneInfo
        if task.get("timeZone"):
            own_mid = _midnight(first.astimezone(ZoneInfo(task["timeZone"])))
    except Exception:
        own_mid = False
    return utc_mid or here_mid or own_mid


def shift_fields(task, days, tz=None):
    """{startDate, dueDate, isAllDay[, timeZone]} moving a task `days` LOCAL
    calendar days, or None when a stamp cannot be read (skip the task whole).

    Adding N x 24 h to the UTC stamp - what the ⏭️ roll did until 2026-09-24 -
    is right only while the clock does not change in between. Across a DST
    change local midnight moves by an hour: an all-day task on 20 Oct
    (19T22:00Z, CEST) rolled on 28 Oct landed on 27T22:00Z = 23:00 CET on the
    27th, the api's all-day guess then said timed, and the task sat at 23:00
    on the wrong day, still overdue (review 2026-09-24; DST ends 25 Oct).

    So each date moves by LOCAL days in `tz` (the Mac's zone, the one the
    roll's own "which day is it" reads):
      all-day -> local midnight of the new day, isAllDay True, and the zone
                 NAMED, so TickTick reads the day in it (a task created
                 without one carries the account's zone);
      timed   -> the same local wall-clock time on the new day, isAllDay
                 False; the task's own zone is left as it is.
    Start and due move by the same count, so a multi-day span keeps its
    length in days; a timed span that would come out backwards (it sat in
    the repeated autumn hour) keeps its real duration instead.

    All-day is read from the flag AND the stamp, because a cached flag can
    be stale (review 2026-09-24): isAllDay True counts only on a stamp that
    is midnight somewhere it could mean one (UTC, this zone, the task's own
    zone) - True on 09:00 is a timed task whose flag lagged; False counts
    as all-day only on UTC midnight, the date-only picker's shape - a real
    00:00 local task stays timed; no flag = the api's guess (UTC or local
    midnight)."""
    tz = tz or _local_tz()
    stamps = {}
    for f in ("startDate", "dueDate"):
        v = task.get(f)
        if not v:
            continue
        dt = _parse(v)
        if dt is None:
            return None
        stamps[f] = dt.astimezone(tz)
    if not stamps:
        return None
    flag = _all_day_of(task, stamps.get("startDate") or stamps.get("dueDate"), tz)
    out, moved = {}, {}
    for f, local in stamps.items():
        day = local.date() + timedelta(days=days)
        clock = time(0, 0) if flag else local.time().replace(tzinfo=None, fold=0)
        moved[f] = datetime.combine(day, clock).replace(tzinfo=tz)
    s0, d0 = stamps.get("startDate"), stamps.get("dueDate")
    if not flag and s0 and d0:
        # compared and measured in UTC: two times in the SAME zone compare
        # and subtract by wall clock, which cannot see the repeated hour
        u = timezone.utc
        if moved["dueDate"].astimezone(u) < moved["startDate"].astimezone(u):
            moved["dueDate"] = moved["startDate"].astimezone(u) + (d0.astimezone(u) - s0.astimezone(u))
    for f, dt in moved.items():
        out[f] = _out(dt)
    out["isAllDay"] = bool(flag)
    name = getattr(tz, "key", None)
    if flag and name:
        out["timeZone"] = name
    return out


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
