#!/usr/bin/env python3
"""The floating-window road (Vex 2026-09-17): the pure halves of it.

A sticky note never re-renders, so everything the workflow writes to a note
is invisible in it until it is closed and reopened (he tested File > Sync -
no help). TickTick's own floating task window, the one a double click opens,
IS live. Nothing else opens one: no shortcut, no menu item, no ticktick://
route - so the double click is the mechanism, and these are the two pieces
that must never be wrong:

  _click_points  where a double click lands. NEVER on the title text: that
                 opens an inline rename, not a window (it bumped a task's
                 modifiedTime twice while this was being built).
  _win_match     which open window belongs to a task. A window is NAMED by
                 its task, which is the whole reason this road can be honest
                 where the sticky road cannot.

No AX, no app, no network.

    python3 tests/test_task_window.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import xact  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def on_text(pt, text):
    tx, ty, tw, th = text
    return tx - 2 <= pt[0] <= tx + tw + 2 and ty - 2 <= pt[1] <= ty + th + 2


def inside(pt, row):
    x, y, w, h = row
    return x <= pt[0] <= x + w and y <= pt[1] <= y + h


# Frames read off the live app 2026-09-17: a short kanban card, a tall one
# (title + tags), and a list row. Negative y = his second display.
CARD = (1473, -738, 282, 48)
CTEXT = (1522, -729, 206, 21)
TALL = (2307, -738, 282, 93)
TTEXT = (2356, -729, 206, 21)
LIST = (1461, -698, 634, 44)
LTEXT = (1510, -689, 206, 21)

# ── the double click never lands on the title ───────────────────────────────
for nm, row, txt in (("short card", CARD, CTEXT), ("tall card", TALL, TTEXT),
                     ("list row", LIST, LTEXT)):
    pts = xact._click_points(row, txt, 2)
    check(f"{nm}: has somewhere to aim", bool(pts))
    check(f"{nm}: no point on the title", not any(on_text(p, txt) for p in pts),
          str([p for p in pts if on_text(p, txt)]))
    check(f"{nm}: every point inside the row",
          all(inside(p, row) for p in pts), str(pts))
    check(f"{nm}: clear of the checkbox zone",
          all(p[0] >= row[0] + 48 for p in pts), str(pts))

check("tall card aims UNDER the title first",
      xact._click_points(TALL, TTEXT, 2)[0][1] > TTEXT[1] + TTEXT[3])
check("short card aims under it too (18px band is enough)",
      xact._click_points(CARD, CTEXT, 2)[0][1] > CTEXT[1] + CTEXT[3])

# A title that fills the whole card leaves only the band under it.
FULL = (1473, -738, 282, 48)
FTEXT = (1477, -734, 274, 21)
pts = xact._click_points(FULL, FTEXT, 2)
check("full-width title: still aims, under the text",
      bool(pts) and all(p[1] > FTEXT[1] + FTEXT[3] for p in pts), str(pts))

# A title that fills the card in BOTH directions: no safe point exists, and
# an empty list is the right answer - the caller then says nothing opened
# rather than risking a rename.
CRAMPED = (1473, -738, 282, 26)
CRTEXT = (1477, -736, 274, 22)
check("no safe point → no click at all",
      xact._click_points(CRAMPED, CRTEXT, 2) == [])

# ── a single click keeps the old sweep ──────────────────────────────────────
single = xact._click_points(CARD, CTEXT, 1)
check("single click: middle of the row first",
      single[0] == (CARD[0] + CARD[2] // 2, CARD[1] + CARD[3] // 2), str(single[:1]))
check("single click: the title is fair game (selection, not a rename)",
      any(on_text(p, CTEXT) for p in single))
check("single click ignores the text frame",
      xact._click_points(CARD, CTEXT, 1) == xact._click_points(CARD, (0, 0, 0, 0), 1))

# The finder's older shape (four fields, no title frame) must still aim.
blind = xact._click_points(CARD, (0, 0, 0, 0), 2)
check("no title frame → the plain sweep, never empty", bool(blind))
check("no title frame → same points as a single click", blind == single)

check("no duplicate points", all(
    len(p) == len(set(p)) for p in
    (xact._click_points(CARD, CTEXT, 2), xact._click_points(TALL, TTEXT, 2), single)))

# A zero-height row (a group header TickTick renders collapsed) must not
# produce a point outside itself.
check("zero-height row stays inside itself",
      all(inside(p, (100, 100, 282, 0))
          for p in xact._click_points((100, 100, 282, 0), (0, 0, 0, 0), 1)) or
      xact._click_points((100, 100, 282, 0), (0, 0, 0, 0), 1) == [])

# ── which window is this task's ─────────────────────────────────────────────
WINS = {"2026-09-17 · Thu": (1, 2, 3, 4), "2026-Q3": (5, 6, 7, 8),
        "💼 P • Onboard TickTick 🔗": (9, 10, 11, 12), "TickTick": (0, 0, 1, 1)}
check("exact title", xact._win_match("2026-Q3", WINS) == "2026-Q3")
check("emoji title", xact._win_match("💼 P • Onboard TickTick 🔗", WINS)
      == "💼 P • Onboard TickTick 🔗")
check("whitespace collapses", xact._win_match("2026-09-17  ·   Thu", WINS)
      == "2026-09-17 · Thu")
check("a stranger matches nothing", xact._win_match("2026-Q4", WINS) is None)
check("empty title matches nothing", xact._win_match("", WINS) is None)
check("empty window list", xact._win_match("2026-Q3", {}) is None)
check("an ellipsized window name matches its long title",
      xact._win_match("💼 P • Onboard TickTick 🔗 and then some",
                      {"💼 P • Onboard TickTick 🔗…": (1, 2, 3, 4)})
      == "💼 P • Onboard TickTick 🔗…")
check("a SHORT prefix never matches (it would hand back a stranger's window)",
      xact._win_match("2026-Q3 review", {"2026-Q3": (1, 2, 3, 4)}) is None)
check("the longest prefix wins",
      xact._win_match("Weekly review of the quarter",
                      {"Weekly review": (1, 1, 1, 1),
                       "Weekly review of the": (2, 2, 2, 2)})
      == "Weekly review of the")
check("exact beats a prefix",
      xact._win_match("Weekly review",
                      {"Weekly review of the": (2, 2, 2, 2),
                       "Weekly review": (1, 1, 1, 1)}) == "Weekly review")

# ── the placement env var ───────────────────────────────────────────────────
for bad in ("", "1,2,3", "a,b,c,d", "1,2,0,40", "1,2,40,0"):
    os.environ["TICKAL_WIN_FRAME"] = bad
    check(f"frame env refuses {bad!r}", xact._win_frame_env() is None)
os.environ["TICKAL_WIN_FRAME"] = "10,20,400,500"
check("frame env reads a good one", xact._win_frame_env() == (10, 20, 400, 500))
del os.environ["TICKAL_WIN_FRAME"]
check("frame env unset → None", xact._win_frame_env() is None)

# ── the finder line: shape, title frame, kanban flag ────────────────────────
check("full line parses",
      xact._parse_row("FOUND|1473|-738|282|48|1522|-729|206|21|1")
      == ((1473, -738, 282, 48), (1522, -729, 206, 21), True))
check("list row reads as NOT a card",
      xact._parse_row("FOUND|1461|-472|634|44|1513|-461|562|21|0")[2] is False)
check("no label → zeros, card flag still read",
      xact._parse_row("FOUND|1|2|3|4|0|0|0|0|1")[1] == (0, 0, 0, 0))
check("the short System-Events shape → card UNKNOWN",
      xact._parse_row("FOUND|1|2|3|4")[2] is None)
check("a miss is None", xact._parse_row("") is None)
check("garbage is None", xact._parse_row("FOUND|a|b|c|d") is None)

# ── what may be clicked ─────────────────────────────────────────────────────
WIN = (1094, -848, 1517, 838)
PTS = [(1200, -700), (1300, -700)]
check("a point inside the window and clear is taken",
      xact._pick_point(PTS, [], WIN) == (1200, -700))
check("a covered point is skipped",
      xact._pick_point(PTS, [(1150, -750, 100, 100)], WIN) == (1300, -700))
check("all covered → None",
      xact._pick_point(PTS, [(1000, -800, 600, 300)], WIN) is None)
check("a scrolled-away row is never clicked (the sidebar sits at y -3164)",
      xact._pick_point([(1200, -3164)], [], WIN) is None)
check("a point past the window's right edge is never clicked",
      xact._pick_point([(2700, -700)], [], WIN) is None)
check("no window frame known → the clamp cannot refuse everything",
      xact._pick_point([(1200, -3164)], [], None) == (1200, -3164))
check("window edges are inclusive",
      xact._pick_point([(1094, -848)], [], WIN) == (1094, -848))


print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
