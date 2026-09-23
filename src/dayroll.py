"""dayroll.py - when Vex's day rolls over: 04:00 local, not midnight.

Vex 2026-09-23: "I tried doing shutdown for that day after midnight and I
couldn't." The 🌆 Shutdown finished at 00:00:31 landed on the NEXT calendar
day everywhere the workflow said "today": its habit check-in, its focus block
(written into a 23rd note that did not exist yet), and every later step of
the routine opened the 23rd's daily note and timer instead of the 22nd's.
A night that runs past midnight still belongs to the day it started.

ONE rule, read by every road that asks "which day is this for Vex": the
periodic notes (mint, refresh, sweep, the daily note a routine opens), the
routine hub and its start guard, the routine habit ripple, the focus-session
note block. 04:00 sits before the 04:30 mint agent (so the agent still mints
TODAY) and after any plausible late night. TickTick's own habit calendar and
the calendar views keep the real date - this is the workflow's day, not
the clock's.
"""
import datetime as _dt

ROLL = _dt.time(4, 0)          # the day starts here, local time


def today(now=None):
    """The workflow's current day (a date): the local calendar day, or the
    day BEFORE it while the clock is still short of ROLL."""
    now = now or _dt.datetime.now()
    d = now.date()
    return d - _dt.timedelta(days=1) if now.time() < ROLL else d


def today_iso(now=None):
    return today(now).isoformat()
