#!/usr/bin/env python3
"""Lock the daily-summary line ORDER.

Vex 2026-09-12: "always keep completed tasks as last bullet point because it
is longest ... People can be below entries, before completed tasks."

Completed drags a nested list of up to ten titles behind it, so anything
appended after it is buried. This suite is the guard: it drives _recap_lines
with every source stubbed, so it asserts the ORDER and nothing else.

    python3 tests/test_recap_order.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_engine as pe          # noqa: E402
import periodic_model as pm           # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


class T2:
    @staticmethod
    def focus_minutes(a, b):
        return 364


def _labels(lines):
    """The top-level bullet labels, nested detail lines dropped."""
    out = []
    for ln in lines:
        body = ln[len(pm.T2):]
        if body.startswith("- ") and not ln.startswith(pm.T2 + "\t"):
            out.append(body[2:].split(":")[0].strip())
    return out


# ── stub every source; only the assembly is under test ──────────────────────
ANSWERS = {"rate the day": "4", "money did you earn": "200"}
pe._answer_in = lambda doc, sec, needle: ANSWERS.get(needle, "")
pe._mood_of_doc = lambda doc: (4, "good")
pe._completed_tops = lambda d: ["one", "two", "three"]
pe._people_logged = lambda d: [("Nesko", "asked for 700"), ("Ivona", "")]

DAY, PREV = date(2026, 9, 12), date(2026, 9, 11)
lines = pe._recap_lines(DAY, T2, object(), pm.T2, pday=PREV, pdoc=object(),
                        extra=[pm.T2 + "- Won't do: 2",
                               pm.T2 + "- Entries: 5 (3 🟢 · 2 💭)"])
labels = _labels(lines)

check("order-is-vex's",
      labels == ["Day", "Mood", "Money", "Focus", "Won't do", "Entries",
                 "People", "Completed"], labels)
check("completed-is-last", labels[-1] == "Completed", labels)
check("nothing-after-the-completed-block",
      lines[-1].startswith(pm.T2 + "\t- "), repr(lines[-3:]))
check("people-sit-above-completed",
      labels.index("People") < labels.index("Completed"), labels)
check("people-names-are-nested",
      any(ln == pm.T2 + "\t- Nesko · asked for 700" for ln in lines),
      repr(lines))
check("a-person-with-no-text-still-shows",
      any(ln == pm.T2 + "\t- Ivona" for ln in lines), repr(lines))

# every source empty → no line at all, never an empty heading
pe._completed_tops = lambda d: None
pe._people_logged = lambda d: []
pe._answer_in = lambda doc, sec, needle: ""
pe._mood_of_doc = lambda doc: None
bare = pe._recap_lines(DAY, None, None, pm.T2)
check("honest-absence", bare == [], repr(bare))

# Completed still lands last when it is the only thing there
pe._completed_tops = lambda d: ["only"]
one = pe._recap_lines(DAY, None, None, pm.T2, extra=[pm.T2 + "- Entries: 1"])
check("extra-still-precedes-completed",
      _labels(one) == ["Entries", "Completed"], _labels(one))

print(f"recap order: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
