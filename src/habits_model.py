"""habits_model.py - the 🔄 Habits model (pure, unit-tested).

Entity truth (webapp bundle + live probes 2026-07-24):
- habit: type "Boolean"|"Real", goal/step/unit, recordEnable (per-day
  diary notes), repeatRule RRULE (WEEKLY;BYDAY=…, DAILY;INTERVAL=N,
  WEEKLY;TT_TIMES=N = flexible x-per-week), targetStartDate YYYYMMDD,
  exDates, sectionId; server maintains currentStreak/maxStreak/
  totalCheckIns ON the entity.
- checkin: checkinStamp YYYYMMDD, value/goal, status 0=unmarked-or-
  partial · 1=explicitly skipped · 2=done. Un-tick = UPDATE to status 0
  (delete 500s). Record (note): stamp/content/emoji, delete needs the
  FULL object.

This module: due-today math, state chips, checkin/record builders,
history dots. No I/O - the verbs feed it cache + live payloads.
"""
import re
from datetime import date, timedelta

_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

DONE, SKIPPED, UNMARKED = 2, 1, 0


def stamp(d):
    return d.year * 10000 + d.month * 100 + d.day


def unstamp(n):
    try:
        return date(n // 10000, n // 100 % 100, n % 100)
    except Exception:
        return None


def is_real(habit):
    return (habit.get("type") or "Boolean") == "Real"


def times_per_week(habit):
    """TT_TIMES=N of a flexible weekly habit, else None."""
    m = re.search(r"TT_TIMES=(\d+)", habit.get("repeatRule") or "")
    return int(m.group(1)) if m else None


def due_today(habit, today=None):
    """Is the habit scheduled today? WEEKLY;BYDAY → listed weekdays;
    DAILY;INTERVAL=N → every Nth day anchored at targetStartDate;
    TT_TIMES (flexible) → every day (the week chip carries the quota).
    exDates always win. Unparseable rules default True - better a
    tickable extra row than a hidden habit."""
    today = today or date.today()
    if stamp(today) in set(habit.get("exDates") or []):
        return False
    rule = habit.get("repeatRule") or ""
    start = unstamp(habit.get("targetStartDate") or 0)
    if start and today < start:
        return False
    if "TT_TIMES" in rule:
        return True
    m = re.search(r"BYDAY=([A-Z,]+)", rule)
    if "FREQ=WEEKLY" in rule and m:
        days = {_BYDAY[d] for d in m.group(1).split(",") if d in _BYDAY}
        return today.weekday() in days
    m = re.search(r"FREQ=DAILY;INTERVAL=(\d+)", rule)
    if m:
        n = int(m.group(1))
        if n <= 1 or not start:
            return True
        return (today - start).days % n == 0
    return True


def checkin_for(checkins, day_stamp):
    """The day's checkin dict from a query result list, or None."""
    for c in checkins or []:
        if c.get("checkinStamp") == day_stamp:
            return c
    return None


def state_chip(habit, checkin):
    """Row chip for a day: '✅' done · '⛔' skipped · '3/8' partial value ·
    '⬜' untouched."""
    if not checkin or checkin.get("status") == UNMARKED:
        v = (checkin or {}).get("value") or 0
        if is_real(habit) and v:
            return f"{_fmt_num(v)}/{_fmt_num(habit.get('goal') or 1)}"
        return "⬜"
    if checkin.get("status") == SKIPPED:
        return "⛔"
    if is_real(habit):
        return f"✅ {_fmt_num(checkin.get('value') or 0)}"
    return "✅"


def _fmt_num(x):
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:g}"


def tick_payload(habit, day_stamp, existing, op_iso):
    """(entry, done_now, new_value) - the habitCheckins/batch element for
    one ⏎: Boolean → straight to done; Real → +step, done when the goal
    is reached. Pass the day's existing checkin (or None); the entry goes
    in `update` when existing, else `add` (caller decides by `existing`).
    An already-done Boolean returns None (idempotent ⏎)."""
    goal = habit.get("goal") or 1
    step = habit.get("step") or 1
    if existing and existing.get("status") == DONE and not is_real(habit):
        return None
    value = ((existing or {}).get("value") or 0) + step \
        if is_real(habit) else goal
    done = value >= goal
    entry = dict(existing or {})
    entry.update({"habitId": habit["id"], "checkinStamp": day_stamp,
                  "value": value, "goal": goal,
                  "status": DONE if done else UNMARKED,
                  "opTime": op_iso, "checkinTime": op_iso})
    return entry, done, value


def untick_payload(existing, op_iso):
    """UPDATE element that clears a day (status 0, value 0). None when
    there is nothing to clear."""
    if not existing:
        return None
    e = dict(existing)
    e.update({"value": 0, "status": UNMARKED, "opTime": op_iso})
    return e


def skip_payload(habit, day_stamp, existing, op_iso):
    """Explicit '⛔ not today' element (TickTick's own skipped state -
    keeps streak math honest vs just leaving it blank)."""
    e = dict(existing or {})
    e.update({"habitId": habit["id"], "checkinStamp": day_stamp,
              "value": 0, "goal": habit.get("goal") or 1,
              "status": SKIPPED, "opTime": op_iso, "checkinTime": op_iso})
    return e


def record_payload(rid, habit_id, day_stamp, content, op_iso, emoji=0):
    return {"id": rid, "habitId": habit_id, "stamp": day_stamp,
            "content": content, "emoji": emoji, "opTime": op_iso}


def week_done(checkins, today=None):
    """Distinct done-stamps in the Monday-start week of `today` - the
    TT_TIMES quota chip ('1/2 this week')."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    a, b = stamp(monday), stamp(today)
    return len({c.get("checkinStamp") for c in checkins or []
                if a <= (c.get("checkinStamp") or 0) <= b
                and c.get("status") == DONE})


def dots(habit, checkins, today=None, days=14):
    """Last-N-days history strip, oldest→today, square scheme (Vex
    re-rule 2026-07-24): 🟩 done · 🟥 skipped · ⬜ due but blank ·
    ▫️ nothing scheduled that day."""
    today = today or date.today()
    by_stamp = {c.get("checkinStamp"): c for c in checkins or []}
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        c = by_stamp.get(stamp(d))
        if c and c.get("status") == DONE:
            out.append("🟩")
        elif c and c.get("status") == SKIPPED:
            out.append("🟥")
        elif due_today(habit, d):
            out.append("⬜")
        else:
            out.append("▫️")
    return "".join(out)


def new_entity(hid, name, section_id="-1", rule=None, goal=1, unit="Count",
               step=1, real=False, record=False, start_stamp=None,
               icon="habit_daily_check_in", color="#7BC4FA"):
    """Full habit entity with app defaults (rule None = every day)."""
    return {
        "id": hid, "name": name, "iconRes": icon, "color": color,
        "sortOrder": 0, "status": 0, "encouragement": "",
        "type": "Real" if real else "Boolean",
        "goal": goal, "step": step, "unit": unit,
        "repeatRule": rule or "RRULE:FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH,FR,SA",
        "reminders": [], "recordEnable": bool(record),
        "sectionId": section_id or "-1", "targetDays": 0,
        "targetStartDate": start_stamp, "completedCycles": 0,
        "exDates": [], "style": 1,
    }


# Frequency presets for the ➕ create flow (label → RRULE)
RULE_PRESETS = [
    ("Every day", "RRULE:FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH,FR,SA"),
    ("Weekdays", "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
    ("Once a week", "RRULE:FREQ=WEEKLY;TT_TIMES=1"),
    ("Twice a week", "RRULE:FREQ=WEEKLY;TT_TIMES=2"),
    ("3x a week", "RRULE:FREQ=WEEKLY;TT_TIMES=3"),
    ("Every 30 days", "RRULE:FREQ=DAILY;INTERVAL=30"),
    ("Every 90 days", "RRULE:FREQ=DAILY;INTERVAL=90"),
]


def review_slot(name):
    """His Reviews section habits map onto periodic notes - 'Weekly
    Review' → weekly. The ⌘ hop rides this."""
    n = (name or "").lower()
    if "weekly" in n or "week" in n:
        return "weekly"
    if "monthly" in n or "month" in n:
        return "monthly"
    if "quarter" in n:
        return "quarterly"
    if "year" in n or "annual" in n:
        return "yearly"
    return None
