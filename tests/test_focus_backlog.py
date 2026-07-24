#!/usr/bin/env python3
"""Unit suite for src/focus_backlog.py. Pure stdlib.
Run: python3 tests/test_focus_backlog.py
"""
import sys
import os
import time as _time
from datetime import datetime, timedelta

os.environ["TZ"] = "Europe/Zagreb"       # DST checks need a fixed zone
_time.tzset()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import focus_backlog as fbk  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


NOW = datetime(2026, 7, 24, 18, 0)      # Fri 24 Jul 2026, 18:00 local


def P(text):
    return fbk.parse_when(text, now=NOW)


# ── _hm ──────────────────────────────────────────────────────────────────
check("hm-colon", fbk._hm("14:30") == (14, 30))
check("hm-4dig", fbk._hm("1430") == (14, 30))
check("hm-3dig", fbk._hm("930") == (9, 30))
check("hm-bare", fbk._hm("9") == (9, 0))
check("hm-2dig-bare", fbk._hm("14") == (14, 0))
check("hm-bad-hour", fbk._hm("25") is None)
check("hm-bad-minute", fbk._hm("14:75") is None)
check("hm-bad-4dig", fbk._hm("2860") is None)
check("hm-nonnum", fbk._hm("ab:cd") is None)

# ── parse_when: plain ranges (today) ─────────────────────────────────────
s, e, r = P("14:30-15:45")
check("range-colon", (s, e, r) == (datetime(2026, 7, 24, 14, 30),
                                   datetime(2026, 7, 24, 15, 45), ""))
s, e, r = P("1430-1615 niji logo")
check("range-4dig+frag", s == datetime(2026, 7, 24, 14, 30)
      and e == datetime(2026, 7, 24, 16, 15) and r == "niji logo")
s, e, r = P("9-11")
check("range-bare-hours", (s, e) == (datetime(2026, 7, 24, 9, 0),
                                     datetime(2026, 7, 24, 11, 0)))
s, e, r = P("9-930")
check("range-mixed", (s, e) == (datetime(2026, 7, 24, 9, 0),
                                datetime(2026, 7, 24, 9, 30)))

# ── duration form ────────────────────────────────────────────────────────
s, e, r = P("14:30+45")
check("plus-form", (s, e) == (datetime(2026, 7, 24, 14, 30),
                              datetime(2026, 7, 24, 15, 15)))
s, e, r = P("1430+90 review")
check("plus-4dig+frag", e == datetime(2026, 7, 24, 16, 0) and r == "review")
s, e, r = P("14:30+0")
check("plus-zero-parses", s is not None and e == s)   # validate rejects it

# ── day tokens ───────────────────────────────────────────────────────────
s, e, r = P("y 9-11")
check("yesterday", (s, e) == (datetime(2026, 7, 23, 9, 0),
                              datetime(2026, 7, 23, 11, 0)))
s, e, r = P("yy 22:00+30")
check("day-before", s == datetime(2026, 7, 22, 22, 0))
s, e, r = P("22.7 14-16")
check("date-dm", (s, e) == (datetime(2026, 7, 22, 14, 0),
                            datetime(2026, 7, 22, 16, 0)))
s, e, r = P("22.7. 14-16")
check("date-dm-trailing-dot", s == datetime(2026, 7, 22, 14, 0))
s, e, r = P("31.2 14-16")
check("date-invalid", s is None)
s, e, r = fbk.parse_when("28.12 14-16", now=datetime(2027, 1, 2, 10, 0))
check("date-year-rollback", s == datetime(2026, 12, 28, 14, 0), s)
s, e, r = P("24.7 14-16")
check("date-today-stays", s == datetime(2026, 7, 24, 14, 0))
s, e, r = fbk.parse_when("29.2 14-16", now=datetime(2028, 1, 15, 10, 0))
check("date-leap-rollback-dead", s is None)   # 2027 had no 29.2

# ── midnight cross ───────────────────────────────────────────────────────
s, e, r = P("y 23:30-0:45")
check("midnight-cross", s == datetime(2026, 7, 23, 23, 30)
      and e == datetime(2026, 7, 24, 0, 45))
s, e, r = P("y 22-22")
check("equal-times-cross", e == datetime(2026, 7, 24, 22, 0))   # 24h → cap

# ── non-parses fall through to the task search ───────────────────────────
check("no-range", P("just a task name") == (None, None, "just a task name"))
check("empty", P("") == (None, None, ""))
check("day-only", P("y") == (None, None, "y"))
check("dangling-dash", P("14:30-")[0] is None)
check("bad-end", P("14:30-99:99")[0] is None)
check("frag-with-digits", P("22.7")[0] is None)   # date w/o range = frag

# ── validate ─────────────────────────────────────────────────────────────
def V(s, e):
    return fbk.validate(s, e, now=NOW)


ok_s, ok_e = datetime(2026, 7, 24, 14, 0), datetime(2026, 7, 24, 15, 0)
check("valid-ok", V(ok_s, ok_e) is None)
check("valid-zero", V(ok_s, ok_s) == "0 minutes")
check("valid-cap", V(datetime(2026, 7, 23, 22, 0),
                     datetime(2026, 7, 24, 11, 1)) is not None)
check("valid-12h-exact", V(datetime(2026, 7, 24, 1, 0),
                           datetime(2026, 7, 24, 13, 0)) is None)
check("valid-future", V(datetime(2026, 7, 24, 17, 0),
                        datetime(2026, 7, 24, 19, 0))
      == "ends in the future")
check("valid-ends-now-ok", V(datetime(2026, 7, 24, 17, 0), NOW) is None)

# ── DST: durations run on the EPOCH delta, like the logged record ────────
# EU fall-back 2026-10-25: naive 01:30-03:30 spans 3 REAL hours
fb_s, fb_e = datetime(2026, 10, 25, 1, 30), datetime(2026, 10, 25, 3, 30)
fb_now = datetime(2026, 10, 26, 12, 0)
check("dst-fallback-real-3h",
      fbk.fmt_range(fb_s, fb_e, now=fb_now).endswith("3h 0m"))
check("dst-fallback-valid", fbk.validate(fb_s, fb_e, now=fb_now) is None)
# naive 12h crossing fall-back = 13h real → capped
check("dst-fallback-cap",
      fbk.validate(datetime(2026, 10, 24, 22, 0),
                   datetime(2026, 10, 25, 10, 0), now=fb_now) is not None)
# EU spring-forward 2026-03-29: 02:00-03:00 never existed → 0 real seconds
sf_s, sf_e = datetime(2026, 3, 29, 2, 0), datetime(2026, 3, 29, 3, 0)
check("dst-gap-rejected",
      fbk.validate(sf_s, sf_e, now=datetime(2026, 3, 30, 12, 0))
      == "0 minutes")

# ── fmt helpers ──────────────────────────────────────────────────────────
check("dur-min", fbk.fmt_dur(45 * 60) == "45m")
check("dur-hm", fbk.fmt_dur(75 * 60) == "1h 15m")
check("fmt-today", fbk.fmt_range(ok_s, ok_e, now=NOW)
      == "14:00 → 15:00 · 1h 0m")
check("fmt-yesterday", fbk.fmt_range(datetime(2026, 7, 23, 9, 0),
                                     datetime(2026, 7, 23, 9, 45), now=NOW)
      == "y · 09:00 → 09:45 · 45m")
check("fmt-date", fbk.fmt_range(datetime(2026, 7, 22, 14, 0),
                                datetime(2026, 7, 22, 15, 0), now=NOW)
      .startswith("22.7 · "))
check("fmt-cross", "+1" in fbk.fmt_range(datetime(2026, 7, 23, 23, 30),
                                         datetime(2026, 7, 24, 0, 45),
                                         now=NOW))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print(f"all green ({COUNT[0]} checks)")
