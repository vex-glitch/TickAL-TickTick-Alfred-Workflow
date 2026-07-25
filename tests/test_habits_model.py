#!/usr/bin/env python3
"""Unit suite for src/habits_model.py. Pure stdlib.
Run: python3 tests/test_habits_model.py
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import habits_model as hm  # noqa: E402

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
TS = hm.stamp(T)
ISO = "2026-07-24T12:00:00.000+0000"


def H(**kw):
    base = {"id": "h1", "type": "Boolean", "goal": 1, "step": 1,
            "repeatRule": "RRULE:FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH,FR,SA",
            "targetStartDate": 20260601, "exDates": []}
    base.update(kw)
    return base


def C(stamp_=TS, status=2, value=1, goal=1):
    return {"id": "c1", "habitId": "h1", "checkinStamp": stamp_,
            "status": status, "value": value, "goal": goal}


# ── due_today ────────────────────────────────────────────────────────────
check("due-daily", hm.due_today(H(), T))
check("due-weekly-sun-not-fri",
      not hm.due_today(H(repeatRule="RRULE:FREQ=WEEKLY;BYDAY=SU"), T))
check("due-weekly-fri",
      hm.due_today(H(repeatRule="RRULE:FREQ=WEEKLY;BYDAY=FR"), T))
check("due-ttimes-always",
      hm.due_today(H(repeatRule="RRULE:FREQ=WEEKLY;TT_TIMES=1"), T))
check("due-interval-hit",
      hm.due_today(H(repeatRule="RRULE:FREQ=DAILY;INTERVAL=30",
                     targetStartDate=20260624), T))
check("due-interval-miss",
      not hm.due_today(H(repeatRule="RRULE:FREQ=DAILY;INTERVAL=30",
                         targetStartDate=20260630), T))
check("due-before-start",
      not hm.due_today(H(targetStartDate=20260801), T))
check("due-exdate", not hm.due_today(H(exDates=[TS]), T))
check("due-unparseable-defaults-true",
      hm.due_today(H(repeatRule="RRULE:FREQ=LUNAR"), T))

# ── chips ────────────────────────────────────────────────────────────────
check("chip-done", hm.state_chip(H(), C()) == "✅")
check("chip-blank", hm.state_chip(H(), None) == "⬜")
check("chip-skip", hm.state_chip(H(), C(status=1)) == "⛔")
check("chip-partial", hm.state_chip(
    H(type="Real", goal=8), C(status=0, value=3, goal=8)) == "3/8")
check("chip-real-done", hm.state_chip(
    H(type="Real", goal=8), C(status=2, value=8, goal=8)) == "✅ 8")

# ── tick / untick / skip payloads ────────────────────────────────────────
e, done, v = hm.tick_payload(H(), TS, None, ISO)
check("tick-bool", e["status"] == 2 and e["value"] == 1 and done)
check("tick-bool-idempotent", hm.tick_payload(H(), TS, C(), ISO) is None)
e, done, v = hm.tick_payload(H(type="Real", goal=3), TS, None, ISO)
check("tick-real-first", e["status"] == 0 and v == 1 and not done)
e, done, v = hm.tick_payload(H(type="Real", goal=3), TS,
                             C(status=0, value=2, goal=3), ISO)
check("tick-real-completes", e["status"] == 2 and v == 3 and done)
e, done, v = hm.tick_payload(H(type="Real", goal=3, step=0.5), TS,
                             C(status=2, value=3, goal=3), ISO)
check("tick-real-overshoot", v == 3.5 and e["status"] == 2)
check("untick", hm.untick_payload(C(), ISO)["status"] == 0)
check("untick-nothing", hm.untick_payload(None, ISO) is None)
check("skip", hm.skip_payload(H(), TS, None, ISO)["status"] == 1)

# ── week quota + dots ────────────────────────────────────────────────────
mon = hm.stamp(date(2026, 7, 20))
check("week-done", hm.week_done(
    [C(stamp_=mon), C(stamp_=TS), C(stamp_=20260712)], T) == 2)
check("week-skip-not-counted", hm.week_done([C(stamp_=mon, status=1)], T)
      == 0)
d = hm.dots(H(), [C(stamp_=TS), C(stamp_=hm.stamp(date(2026, 7, 22)),
                                 status=1)], T, days=5)
check("dots", d == "⬜⬜🟥⬜🟩", d)
d2 = hm.dots(H(repeatRule="RRULE:FREQ=WEEKLY;BYDAY=FR"), [], T, days=3)
check("dots-unscheduled", d2 == "▫️▫️⬜", d2)

# ── entity + presets + review map ────────────────────────────────────────
n = hm.new_entity("a" * 24, "Stretch", rule=hm.RULE_PRESETS[1][1])
check("ent-defaults", n["type"] == "Boolean" and n["goal"] == 1
      and "BYDAY=MO" in n["repeatRule"])
r = hm.new_entity("b" * 24, "Water", real=True, goal=8, unit="Glass")
check("ent-real", r["type"] == "Real" and r["goal"] == 8)
check("preset-count", len(hm.RULE_PRESETS) == 7)
check("review-weekly", hm.review_slot("Weekly Review") == "weekly")
check("review-quarter", hm.review_slot("Quarterly Retreat") == "quarterly")
check("review-none", hm.review_slot("Call mum") is None)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print(f"all green ({COUNT[0]} checks)")
