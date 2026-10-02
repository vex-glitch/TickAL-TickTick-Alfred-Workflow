"""routines.py - the routine registry (PURE: stdlib only, no I/O).

Vex's routines are TickTick tasks whose steps are subtasks, and each has a
Keyboard Maestro macro that opens the whole workspace for it ("… • Start":
quit and relaunch TickTick, focus + sticky the routine task, place the
stickies and the focus bar, open the apps). The Alfred surface lists them.

The map is CONFIG, never name matching: a renamed macro or a retitled task
must not change which routine a row fires (HANDOFF_ROUTINES §7). Titles are
read LIVE from the cached task, so the emoji Vex puts on the task in
TickTick is the emoji the row shows; LABEL is only the fallback for a task
the cache has not seen yet.

A macro is addressed by UID for the same reason: two macros can share a name
(there are two "YNAB"), and a rename breaks a name link.
"""

ROUTINES_LIST = "6a268ea18f081f1de80eaeb5"      # 🌅 Routines

# key, fallback label, task id, FALLBACK list id, KM macro UID. The list id
# is a hint only: the renderer takes the live task's projectId, so moving a
# routine between lists never breaks its row (Vex moved 🌓 Quarterly Review
# out of 🌓 Quarterly Retreat into 🌅 Routines hours after it was minted).
ROUTINES = (
    {"key": "startup", "label": "🌅 Startup",
     "tid": "6a9faa51635ed1022425af34", "pid": ROUTINES_LIST,
     "macro": "3BE75925-603A-4962-98B1-55686A7DDE6C",
     "habit": "6aa5379e8f081102b4f0d1ec"},          # 🌅 Startup (daily)
    {"key": "shutdown", "label": "🌆 Shutdown",
     "tid": "6a268ea28f081f1de80eb10b", "pid": ROUTINES_LIST,
     "macro": "D896DA99-5DD0-4247-9C4E-17DA9E657009",
     "habit": "6aa537a58f087a63208091fe"},          # 🌆 Shutdown (daily)
    {"key": "weekly", "label": "♻️ Weekly Review",
     "tid": "6aa4eaad7c035e06a3686a2f", "pid": ROUTINES_LIST,
     "macro": "676A175C-92D8-4F5E-9A66-B81E0E4AE6AC",
     "habit": "6a271b2ce2995158ed6ab3a6"},          # Weekly Review (Sun)
    {"key": "monthly", "label": "🗓️ Monthly Review",
     "tid": "6aa517f607a3ba2e0339b7bd", "pid": ROUTINES_LIST,
     "macro": "524BE77F-4BEE-4B8D-AC16-34F128D616DD",
     "habit": "6a271bbda9b89158ed6ab457"},          # Monthly Review (30d)
    {"key": "quarterly", "label": "🌓 Quarterly Review",
     "tid": "6aa520b28f084b1907ea08e2", "pid": ROUTINES_LIST,
     "macro": "28115256-AF19-42FC-A6DA-5CAF2F18D6C6",
     "habit": "6a271c1c30a9d158ed6ab8ad"},          # Quarterly Retreat (90d)
    # 🎉 Yearly Review (the last day of the year, made 2026-09-27): born
    # after the routines went native, so it never had a KM macro; its step
    # list is the routines.json entry, else routine_runner's default
    {"key": "yearly", "label": "🎉 Yearly Review",
     "tid": "6ab90aa78f086a6e16acfa9c", "pid": ROUTINES_LIST,
     "macro": "",
     "habit": "6ab90ab28f087177095cca05"},          # Yearly Review (365d)
    # 🥘 Meal Prep (Sun 19:00): no KM macro - its workspace is the 🥘 hub
    # (ctx:meal). "reset": False on purpose: its children are the week's
    # THREE meal pointers, minted fresh by every plan commit (src/meal_write),
    # so nothing must ever reopen the ones already cooked (HANDOFF_MEAL.md).
    {"key": "meal", "label": "🥘 Meal Prep",
     "tid": "6a9ed0dc0eecd103a69febee", "pid": ROUTINES_LIST,
     "macro": "", "reset": False,
     "habit": "6aa27acd557832cfc9ea5d77"},          # Meal Prep (7d)
)

_HEX = "0123456789abcdefABCDEF"


def by_key(key):
    """The routine with this key, or None."""
    return next((r for r in ROUTINES if r["key"] == key), None)


def by_tid(tid):
    """The routine whose task this is, or None."""
    return next((r for r in ROUTINES if r["tid"] == tid), None)


def valid_macro(uid):
    """A KM macro UID is 8-4-4-4-12 hex. Anything else never reaches `open`:
    the row arg rides the XAct road, and that road takes what a row hands it.
    """
    if not uid or len(uid) != 36:
        return False
    groups = uid.split("-")
    if [len(g) for g in groups] != [8, 4, 4, 4, 12]:
        return False
    return all(c in _HEX for g in groups for c in g)


def macro_url(uid):
    """kmtrigger:// URL for a macro UID, or None when the UID is malformed."""
    return f"kmtrigger://macro={uid}" if valid_macro(uid) else None


# ── which occurrence? (the ⌃ Start safety net, Vex 2026-09-12) ──────────────
# A repeating routine keeps ONE id and rolls its date forward on completion,
# so the task's own due date says which occurrence is live: due today = the
# one you mean; due later = today's is done (or today is not its day) and a
# blind start would open the NEXT one without saying so.
import datetime as _dt
import re as _re

_RRULE = _re.compile(r"(?:RRULE:)?(.*)", _re.I)
_WEEKDAYS = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday",
             "TH": "Thursday", "FR": "Friday", "SA": "Saturday", "SU": "Sunday"}
_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 21: "21st", 22: "22nd", 23: "23rd", 31: "31st"}


def _rule_parts(repeat_flag):
    out = {}
    for bit in (_RRULE.match(repeat_flag or "").group(1) or "").split(";"):
        if "=" in bit:
            k, v = bit.split("=", 1)
            out[k.strip().upper()] = v.strip().upper()
    return out


def local_date(iso):
    """The LOCAL calendar day of a TickTick timestamp ('…+0000'), or None.
    Local, never UTC: a routine due 05:00 UTC is a Berlin morning, and the
    question is always "is this today for Vex"."""
    if not iso:
        return None
    try:
        txt = iso.replace("Z", "+00:00")
        if _re.search(r"[+-]\d{4}$", txt):          # +0000 → +00:00
            txt = txt[:-2] + ":" + txt[-2:]
        return _dt.datetime.fromisoformat(txt).astimezone().date()
    except (ValueError, TypeError):
        return None


def rule_text(repeat_flag):
    """The schedule in words: 'daily', 'Sundays', 'the 30th', 'every 3
    months on the 30th'. '' when the task does not repeat."""
    p = _rule_parts(repeat_flag)
    freq, every = p.get("FREQ"), int(p.get("INTERVAL") or 1)
    if not freq:
        return ""
    if freq == "DAILY":
        return "daily" if every == 1 else f"every {every} days"
    if freq == "WEEKLY":
        days = [_WEEKDAYS.get(d, d) for d in (p.get("BYDAY") or "").split(",") if d]
        when = " and ".join(days) + "s" if days else "weekly"
        return when if every == 1 else f"{when}, every {every} weeks"
    if freq in ("MONTHLY", "YEARLY"):
        day = p.get("BYMONTHDAY")
        if day and day.lstrip("-").isdigit() and int(day) < 0:
            # BYMONTHDAY=-1: the last day (the reviews since 2026-09-25, so
            # February has a review day); -2 and below read "2nd from last"
            n = -int(day)
            on = "the last day" if n == 1 else f"the {_ORDINAL.get(n, str(n) + 'th')} from last day"
        elif day and day.isdigit():
            on = f"the {_ORDINAL.get(int(day), str(int(day)) + 'th')}"
        else:
            on = freq.lower()
        unit = "month" if freq == "MONTHLY" else "year"
        return f"{on} of every {unit}" if every == 1 else f"{on}, every {every} {unit}s"
    return freq.lower()


def prev_occurrence(day, repeat_flag):
    """The occurrence BEFORE `day` for this rule, or None. Used to name the
    one that was just completed: the series rolled past it, so it needs no
    completion record to be known."""
    if not day:
        return None
    p = _rule_parts(repeat_flag)
    freq, every = p.get("FREQ"), int(p.get("INTERVAL") or 1)
    if freq == "DAILY":
        return day - _dt.timedelta(days=every)
    if freq == "WEEKLY":
        return day - _dt.timedelta(weeks=every)
    if freq in ("MONTHLY", "YEARLY"):
        months = every * (12 if freq == "YEARLY" else 1)
        y, m = day.year, day.month - months
        while m <= 0:
            m += 12
            y -= 1
        last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        bmd = p.get("BYMONTHDAY") or ""
        if bmd.lstrip("-").isdigit() and int(bmd) < 0:
            # a last-day rule: the previous occurrence is that month's last
            # day, never the same day number clamped (30 Nov -> 31 Oct, the
            # Finish guard's "prev == today" check; review 2026-09-25)
            return _dt.date(y, m, max(1, last + 1 + int(bmd)))
        return _dt.date(y, m, min(day.day, last))
    return None


def local_moment(iso):
    """A TickTick timestamp as a LOCAL naive datetime, or None (anything that
    is not a timestamp string included: a bad cache record is skipped, never
    a reason for the Finish guard to give up)."""
    if not iso or not isinstance(iso, str):
        return None
    try:
        txt = iso.replace("Z", "+00:00")
        if _re.search(r"[+-]\d{4}$", txt):
            txt = txt[:-2] + ":" + txt[-2:]
        return _dt.datetime.fromisoformat(txt).astimezone().replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def finished_days(tid, completed):
    """The workflow days (dayroll, 04:00) this routine was finished on, read
    from completed-task records: the Finish road's own snapshot carries the
    series id, a synced record is a copy whose repeatTaskId is the series."""
    import dayroll
    out = set()
    for t in completed or ():
        if not isinstance(t, dict) or tid not in (t.get("id"), t.get("repeatTaskId")):
            continue
        when = local_moment(t.get("completedTime"))
        if when is not None:
            out.add(dayroll.today(when))
    return out


def finish_verdict(task, done_days=(), today=None):
    """What a Finish click may do with a routine's live task -> (verdict, date):
        "go"      complete it: the live occurrence is today's, a late one, or
                  undated, or the task does not repeat
        "closed"  refuse: a one-off task that is already completed
        "done"    refuse: the series has rolled past today AND today's
                  occurrence is resolved - the rule's previous occurrence IS
                  today (a daily routine one day ahead, the Sunday review
                  clicked again on Sunday), or the records show it finished
                  today (a review finished a day early, clicked again). A
                  second click would complete the NEXT occurrence, which is
                  the guard's whole reason to exist
        "early"   the next occurrence is a later day and nothing says it was
                  finished today: a Finish a day early (the Sunday review on
                  Saturday), or a completion the record has not caught up with
    `date` is the live occurrence's day (None when undated). Pure: the day
    rolls at 04:00 (dayroll), exactly like the ⌃ Start guard (due_state)."""
    task = task or {}
    if task.get("status") not in (None, 0):
        return "closed", None
    if not task.get("repeatFlag"):
        return "go", local_date(task.get("startDate") or task.get("dueDate"))
    st = due_state(task, today)
    if st["state"] != "ahead":
        return "go", st["date"]
    if today is None:
        import dayroll
        today = dayroll.today()
    # the RULE first: a completion made by a road that writes no record (the
    # focus bar's ●, the note sweep, the app) is still known this way
    # (review 2026-09-24: a Finish after ● asked instead of refusing)
    resolved = st["prev"] == today or today in set(done_days or ())
    return ("done" if resolved else "early"), st["date"]



def before_birth(task, day):
    """Is `day` earlier than the day this task was created? False when the
    task carries no creation stamp (nothing is claimed either way). A rule's
    slot before the first real one is no occurrence: a review made in
    September whose rule says "the last day of the year" never ran the
    December before."""
    born = local_date((task or {}).get("createdTime"))
    return bool(born and day and day < born)


def missed_occurrence(task, done_days=(), today=None):
    """The occurrence this series skipped WITHOUT being finished, or None.

    Vex 2026-10-02: he dragged the monthly and quarterly reviews in the
    calendar two days after their day. TickTick took that as "only this
    occurrence": a dated copy without the tree, and the SERIES rolled on to
    31 Oct and 31 Dec with 30 Sep never completed. The ⌃ Start guard then
    read "ahead" and only offered the NEXT one, whose Finish would have eaten
    October's review and whose journal would have filed into October's note.

    Missed = the series is ahead of today, the rule's previous occurrence
    lies before today, the task already existed by then, and no completion
    record falls on or after that day (a late Finish a day or two after the
    occurrence resolves it too: completing is what rolls the series). The
    records come from the completed feed and the Finish road's own snapshot
    (finished_days); when they are stale the row is still only an OFFER, the
    verb re-reads live and Vex decides. Pure: today is the 04:00 day."""
    task = task or {}
    if task.get("status") not in (None, 0) or not task.get("repeatFlag"):
        return None
    if today is None:
        import dayroll
        today = dayroll.today()
    st = due_state(task, today)
    prev = st["prev"]
    if st["state"] != "ahead" or not prev or prev >= today:
        return None
    if before_birth(task, prev):
        return None
    if any(d >= prev for d in (done_days or ()) if d):
        return None
    return prev


def shift_iso_days(iso, days):
    """A TickTick timestamp moved by whole days with its CLOCK kept as it is
    stored ('2026-10-31T06:00:00.000+0000', -31 -> '2026-09-30T06:00:00.000+0000').
    This is what TickTick itself does when a series rolls across a DST edge
    (probe 2026-10-02: 30 Sep 06:00 UTC became 31 Oct 06:00 UTC), so moving
    a series BACK the same way lands on the hours the occurrence had."""
    if not iso or not isinstance(iso, str):
        return None
    m = _re.match(r"^(\d{4}-\d{2}-\d{2})(T.*)$", iso)
    if not m:
        return None
    try:
        day = _dt.date.fromisoformat(m.group(1)) + _dt.timedelta(days=int(days))
    except (ValueError, TypeError):
        return None
    return f"{day.isoformat()}{m.group(2)}"


REVIEW_SLOTS = ("weekly", "monthly", "quarterly", "yearly")


def late_day(slot, task, today=None):
    """The day of a review routine's OPEN occurrence when that review runs
    LATE, else None: the task is overdue and its day lies in an earlier
    period of the slot than today. The one fact behind every "which period"
    question on a late review: the journal pins to that period's note
    (journal_pin), the note openers and the Start step's note window open
    that period's note, the money door opens that month's note (Vex
    2026-10-02: the September monthly review, run on 2 Oct, opened OCTOBER's
    note). The day rolls at 04:00, so a run at 00:30 is not late."""
    if slot not in REVIEW_SLOTS or not task:
        return None
    if today is None:
        import dayroll
        today = dayroll.today()
    st = due_state(task, today)
    if st["state"] != "overdue" or not st["date"]:
        return None
    import periodic_model as pm
    if pm.period_for(slot, st["date"]) == pm.period_for(slot, today):
        return None
    return st["date"]


def journal_pin(slot, task, today=None):
    """"@2026-12-31" when the review this journal belongs to runs LATE, else
    "". A review finished a day late still closes the occurrence it is for
    (the Finish guard), and its journal has to file into THAT period's note:
    the yearly review done on 1 January is about the year that ended, and
    the journal asked for "this year's" note, the new one (review
    2026-09-27; the quarterly on 1 October and the monthly on the 1st had
    the same hole). `task` is the routine's live task; the pin is the day of
    its OPEN occurrence, given only when that day lies in an earlier period
    of the slot than today (late_day)."""
    day = late_day(slot, task, today)
    return "@" + day.isoformat() if day else ""


def due_state(task, today=None):
    """Which occurrence a start would open:
        {"state": "today"|"ahead"|"overdue"|"undated", "date": date|None,
         "prev": date|None, "rule": str, "days": int}
    "ahead" is the one that needs a question: today's is done, or today is
    not this routine's day, so starting would run the NEXT occurrence."""
    if today is None:
        import dayroll                # a routine's day rolls at 04:00
        today = dayroll.today()
    task = task or {}
    day = local_date(task.get("startDate") or task.get("dueDate"))
    rule = rule_text(task.get("repeatFlag"))
    if day is None:
        return {"state": "undated", "date": None, "prev": None, "rule": rule, "days": 0}
    state = "today" if day == today else ("ahead" if day > today else "overdue")
    return {"state": state, "date": day, "days": (day - today).days, "rule": rule,
            "prev": prev_occurrence(day, task.get("repeatFlag"))}
