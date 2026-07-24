#!/usr/bin/env python3
"""Unit suite for src/countdowns.py. Pure stdlib.
Run: python3 tests/test_countdowns.py
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import countdowns as cdm  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


T = date(2026, 7, 24)      # Fri


def CD(**kw):
    base = {"type": 4, "date": 20260801, "status": 0, "timerMode": 0}
    base.update(kw)
    return base


# ── days_until ───────────────────────────────────────────────────────────
check("plain-ahead", cdm.days_until(CD(), T) == (8, "ahead"))
check("plain-today", cdm.days_until(CD(date=20260724), T) == (0, "ahead"))
check("plain-past-since", cdm.days_until(CD(date=20260702), T)
      == (22, "since"))
check("countup", cdm.days_until(CD(date=20260702, timerMode=1), T)
      == (22, "since"))
check("yearly-ahead",
      cdm.days_until(CD(type=2, date=19930627, ignoreYear=False,
                        repeatFlag="RRULE:FREQ=YEARLY;INTERVAL=1;"
                                   "BYMONTH=6;BYMONTHDAY=27"), T)
      == ((date(2027, 6, 27) - T).days, "ahead"))
check("yearly-ignoreyear",
      cdm.days_until(CD(type=2, date=20260728, ignoreYear=True,
                        repeatFlag="RRULE:FREQ=YEARLY;INTERVAL=1;"
                                   "BYMONTH=7;BYMONTHDAY=28"), T)
      == (4, "ahead"))
check("weekly-sat",
      cdm.days_until(CD(repeatFlag="RRULE:FREQ=WEEKLY;INTERVAL=1;"
                                   "WKST=SU;BYDAY=SA"), T) == (1, "ahead"))
check("feb29-clamp",
      cdm.days_until(CD(type=2, date=20240229, ignoreYear=False,
                        repeatFlag="RRULE:FREQ=YEARLY;INTERVAL=1;"
                                   "BYMONTH=2;BYMONTHDAY=29"), T)
      == ((date(2027, 2, 28) - T).days, "ahead"))
check("bad-date", cdm.days_until(CD(date=0), T) is None)

# ── age / labels / sort ──────────────────────────────────────────────────
check("age-next", cdm.age_on_next(
    CD(type=2, date=19930627,
       repeatFlag="RRULE:FREQ=YEARLY;INTERVAL=1;BYMONTH=6;BYMONTHDAY=27"),
    T) == 34)
check("age-ignoreyear-none", cdm.age_on_next(
    CD(type=2, date=20260728, ignoreYear=True), T) is None)
check("label-today", cdm.distance_label(CD(date=20260724), T) == "today")
check("label-tomorrow", cdm.distance_label(CD(date=20260725), T)
      == "tomorrow")
check("label-in", cdm.distance_label(CD(date=20260801), T) == "in 8d")
check("label-since", cdm.distance_label(CD(date=20260702, timerMode=1), T)
      == "22d since")
check("sort-ahead-first", cdm.sort_key(CD(date=20260725), T)
      < cdm.sort_key(CD(date=20260702, timerMode=1), T))
check("sort-since-longest-first",
      cdm.sort_key(CD(date=20250101, timerMode=1), T)
      < cdm.sort_key(CD(date=20260702, timerMode=1), T))

# ── milestone ────────────────────────────────────────────────────────────
check("milestone-100", cdm.milestone(
    CD(date=20260415, timerMode=1), T) == "💯 100d")
check("milestone-none", cdm.milestone(
    CD(date=20260702, timerMode=1), T) is None)

# ── parse_cd_date ────────────────────────────────────────────────────────
check("date-ymd", cdm.parse_cd_date("1993/06/27", T) == (19930627, True))
check("date-dmy-dots", cdm.parse_cd_date("27.06.1993", T)
      == (19930627, True))
check("date-dm-future", cdm.parse_cd_date("28.7", T) == (20260728, False))
check("date-dm-passed-rolls", cdm.parse_cd_date("2.7", T)
      == (20270702, False))
check("date-dm-trailing-dot", cdm.parse_cd_date("28.7.", T)
      == (20260728, False))
check("date-swap", cdm.parse_cd_date("7/28", T) == (20260728, False))
check("date-bad", cdm.parse_cd_date("banana", T) is None)
check("date-invalid", cdm.parse_cd_date("31.2.1990", T) is None)
check("date-feb29-clamped-int",
      cdm.parse_cd_date("29.2", date(2028, 3, 1)) == (20290228, False))
check("date-feb29-nonleap-none", cdm.parse_cd_date("29.2", T) is None)

# ── biweekly interval parity (review catch) ──────────────────────────────
bw = CD(date=20260718,   # a Saturday
        repeatFlag="RRULE:FREQ=WEEKLY;INTERVAL=2;WKST=SU;BYDAY=SA")
check("biweekly-off-week", cdm.days_until(bw, T) == (8, "ahead"),
      cdm.days_until(bw, T))
check("biweekly-on-week",
      cdm.days_until(bw, date(2026, 7, 31)) == (1, "ahead"))

# ── new_entity ───────────────────────────────────────────────────────────
e = cdm.new_entity("x" * 24, "Trip", 20260912, 4, appear=-7)
check("ent-kind", e["type"] == 4 and e["iconRes"] == "countdown_countdown")
check("ent-appear", e["typeOfSmartList"] == -7)
check("ent-no-rrule-countdown", e["repeatFlag"] is None)
b = cdm.new_entity("y" * 24, "Vida", 20260705, 2, yearless=True)
check("ent-bday-rrule", "BYMONTH=7" in (b["repeatFlag"] or ""))
check("ent-bday-ignoreyear", b["ignoreYear"] is True
      and b["showAge"] is False)
b2 = cdm.new_entity("z" * 24, "Ivona", 19930627, 2)
check("ent-bday-age", b2["showAge"] is True and b2["ignoreYear"] is False)
u = cdm.new_entity("w" * 24, "Not Smoking", 20260702, 3, countup=True)
check("ent-countup", u["timerMode"] == 1 and u["repeatFlag"] is None)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print(f"all green ({COUNT[0]} checks)")
