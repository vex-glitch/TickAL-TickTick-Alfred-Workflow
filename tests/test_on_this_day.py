#!/usr/bin/env python3
"""🕰️ On this day, proven on synthetic past years.

No real daily note is a year old yet (the earliest is 2026-07-11), so the
only way to see this section work before July 2027 is to hand the engine an
index that has one. Everything here is in memory: no API, no writes.

    python3 tests/test_on_this_day.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_engine as pe        # noqa: E402
import periodic_model as pm         # noqa: E402
import periodic_sections as ps      # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


def daily(mood="", rating="", entries=()):
    """A daily note body in Vex's layout with the answers filled in."""
    return "\n".join([
        "#### ⚔️ Workbench",
        "- 📓 Notes",
        *[f"\t- 10:00 {e}" for e in entries],
        "##### 📓 Journals",
        "- 🌅 Morning Journal",
        "\t- *Q1 · Mood 1-5 (1 😢 · 3 😐 · 5 😁)*",
        f"\t\t- A: {mood}",
        "- 🌙 Evening journal",
        "\t- *Q5 · Rate the day, 1-5 stars*",
        f"\t\t- A: {rating}",
        "---",
        "##### 🕰️ On this day",
    ])


def note(tid, content):
    return {"id": tid, "projectId": "PLIST", "content": content}


TODAY = date(2026, 9, 13)
INDEX = {
    ("daily", "2026-09-13"): note("t26", daily()),
    ("daily", "2025-09-13"): note("t25", daily(
        mood="🙂 slept badly", rating="4",
        entries=("🟢 Shipped [the album](https://x/1)", "🔴 traffic",
                 "🏆 an old-glyph win"))),
    ("daily", "2024-09-13"): note("t24", daily()),          # a quiet day
    ("weekly", pm.title_key(pm.period_for("weekly", date(2025, 9, 13)))):
        note("w25", "##### ✨ Highlight\nThe week the shop opened\n---"),
}

mem = pe._otd_memories(TODAY, INDEX)
check("newest-year-first", [m[0].year for m in mem] == [2025, 2024],
      [m[0] for m in mem])
m25 = mem[0]
check("links-to-that-days-note",
      m25[1] == "https://ticktick.com/webapp/#p/PLIST/tasks/t25", m25[1])
check("day-rating", m25[2] == "★★★★", m25[2])
check("mood-with-its-note", m25[3] == "🙂 slept badly", m25[3])
check("only-wins-and-links-flattened",
      m25[4] == ["Shipped the album", "an old-glyph win"], m25[4])
check("that-weeks-highlight", m25[5] == "The week the shop opened", m25[5])
check("a-quiet-day-still-gets-its-line",
      mem[1][2:] == ("", "", [], ""), mem[1])
check("today-is-never-its-own-memory",
      all(m[0] != TODAY for m in mem))

lines = pm.otd_lines(mem)
check("renders",
      lines[:6] == ["- [2025 · Sat](https://ticktick.com/webapp/#p/PLIST/tasks/t25)",
                    "\t- Day: ★★★★", "\t- Mood: 🙂 slept badly",
                    "\t- 🟢 Shipped the album", "\t- 🟢 an old-glyph win",
                    "\t- ⭐️ The week the shop opened"], lines)
check("quiet-year-is-just-its-link",
      lines[6] == "- [2024 · Fri](https://ticktick.com/webapp/#p/PLIST/tasks/t24)"
      and len(lines) == 7, lines)
check("wins-capped-at-three",
      len([l for l in pm.otd_lines([(TODAY, None, "", "", list("abcde"), "")])
           if "🟢" in l]) == 3)

# empty: one quiet line, never a bare header
only_today = {("daily", "2026-09-13"): INDEX[("daily", "2026-09-13")]}
check("no-past-years", pe._otd_memories(TODAY, only_today) == [])
check("empty-state-line",
      pm.otd_lines([]) == ["- _(nothing from past years yet)_"])

# 29 Feb has no anniversary in a common year - skipped, never crashes
check("leap-day-back-one-year", pm.same_day_back(date(2028, 2, 29), 1) is None)
check("leap-day-back-four-years",
      pm.same_day_back(date(2028, 2, 29), 4) == date(2024, 2, 29))
leap_idx = {("daily", "2024-02-29"): note("l24", daily(rating="5")),
            ("daily", "2028-02-29"): note("l28", daily())}
check("leap-day-finds-the-leap-year",
      [m[0] for m in pe._otd_memories(date(2028, 2, 29), leap_idx)]
      == [date(2024, 2, 29)])

# the filler writes into the section and nowhere else
doc = ps.parse_sections(INDEX[("daily", "2026-09-13")]["content"])
before = ps.serialize_sections(doc)
ps.set_body(doc, pm.SEC_OTD, pm.otd_lines(mem))
after = ps.serialize_sections(doc)
check("fills-the-section",
      after.split("##### 🕰️ On this day\n", 1)[1].startswith("- [2025 · Sat]"),
      after[-300:])
check("leaves-everything-above-untouched",
      after.split("##### 🕰️ On this day")[0] == before.split("##### 🕰️ On this day")[0])

# delete the section = kill switch: nothing to find, nothing written
killed = ps.parse_sections(daily().split("---")[0])
check("kill-switch", ps.find(killed, pm.SEC_OTD) is None)

print(f"on this day: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
