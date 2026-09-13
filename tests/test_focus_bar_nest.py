#!/usr/bin/env python3
"""Drag-to-reparent in the focus bar, driven through the REAL BarController.

Vex 2026-09-13: "make a task a subtask of another task in focus bar by
dragging ... to the right and holding over a task we want to be a parent".

Headless: a fake subtask list, synthetic grip events, and the actual dwell
timer spun in NSEventTrackingRunLoopMode - the mode AppKit sits in while a
mouse button is held, where a default-mode timer can stall. The xact writes
are captured, never sent.

Isolation: importing focus_bar takes the bar's singleton flock and exits
quietly when a real bar is running (the right outcome for a second bar, and
a silent no-op test). So this file re-runs itself under a scratch HOME: its
own lock, its own bar-state file, and the running bar and its saved position
are never touched.

    python3 tests/test_focus_bar_nest.py        # needs PyObjC (the bar's python)
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.environ.get("TICKAL_NEST_TEST") != "1":
    home = tempfile.mkdtemp(prefix="tickal-nest-")
    env = dict(os.environ, HOME=home, TICKAL_NEST_TEST="1",
               PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "src"),
                                           os.path.join(ROOT, "Scripts")]))
    sys.exit(subprocess.call([sys.executable, os.path.abspath(__file__)], env=env))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import time
import focus_bar as fb
from AppKit import NSApplication, NSEventTrackingRunLoopMode
from Foundation import NSRunLoop, NSDate

NSApplication.sharedApplication()
calls = []
fb.BarController._start_loops = lambda self: None          # no live polling
fb.BarController.tick_ = lambda self, timer: None            # no clock/state files
fb.BarController._persist_origin = lambda self: calls.append("persist")
fb.BarController._xact_et = lambda self, verb: calls.append("et:" + verb)
def _direct(self, verb, env_json=False):
    calls.append(verb)
    return lambda: "reparented"
fb.BarController._xact_direct = _direct

class P:
    def __init__(self, x, y): self.x, self.y = x, y
class Ev:
    def __init__(self, x, y): self._p = P(x, y)
    def locationInWindow(self): return self._p

def item(tid, depth):
    return {"idx": 0, "title": f"task {tid}", "url": None, "tid": tid, "pid": "P",
            "checked": False, "depth": depth}
BASE = [item("a", 1), item("a1", 2), item("b", 1), item("c", 1), item("c1", 2)]

def fresh():
    c = fb.BarController.alloc().init()
    c.panel.orderOut_(None)
    c.state = dict(c.state if isinstance(getattr(c, "state", None), dict) else {},
                   kind="timer", attributed=True, pid="P", tid="ROOT",
                   title="Focus task", paused=False, visible=True)
    c.folded = []
    c.block = {"items": [dict(x) for x in BASE], "done": 0, "total": 5}
    c.expanded = True
    c._relayout()
    return c

def row_y(c, tid):
    vis = c._open_items()
    v = next(k for k, x in enumerate(vis) if x["tid"] == tid) - c.scroll_off
    return (c._gap_y[v] + c._gap_y[v + 1]) / 2.0

def grip(c, tid):
    vis = c._open_items()
    v = next(k for k, x in enumerate(vis) if x["tid"] == tid) - c.scroll_off
    return c._row_views(v)[2]

def spin(mode, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        NSRunLoop.currentRunLoop().runMode_beforeDate_(mode, NSDate.dateWithTimeIntervalSinceNow_(0.05))

def tree(c):
    return [(x["tid"], x["depth"]) for x in fb.fsub.open_rows(c.block["items"])]

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("  ok  " if cond else "  FAIL") + " " + name + ("" if cond else f"  {detail}"))

X0 = 16.0   # the grip column
# 1. drag b right, rest on c, the timer fires in TRACKING mode, drop -> b under c
c = fresh(); H = c.panel.frame().size.height
g = grip(c, "b")
c.grip_down(g, Ev(X0, row_y(c, "b")))
check("targets for b exclude nothing but its own parent (root)",
      c._drag["targets"] == {"a", "a1", "c", "c1"}, c._drag["targets"])
c.grip_dragged(g, Ev(X0 + 10, row_y(c, "c")))
check("a small rightward drag still reorders (no nest yet)", not c._drag["nest"])
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "c")))
check("past NEST_DX it nests, candidate = c, not armed yet",
      c._drag["nest"] and c._drag["cand"] == "c" and c._drag["armed"] is None, c._drag)
check("drop line hidden while nesting", c.drop_line.isHidden())
check("faint glow while dwelling", not c.nest_glow.isHidden() and c.nest_glow.alphaValue() < 0.5)
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.25)
check("dwell timer FIRED in event-tracking mode and armed c", c._drag["armed"] == "c", c._drag["armed"])
check("armed glow is full strength", c.nest_glow.alphaValue() > 0.9)
c.grip_up(g, Ev(X0 + 40, row_y(c, "c")))
time.sleep(0.2)
check("optimistic tree: b is now c's last child",
      tree(c) == [("a", 1), ("a1", 2), ("c", 1), ("c1", 2), ("b", 2)], tree(c))
check("write fired as fx_parent:b:c", "fx_parent:b:c" in calls, calls)
check("glow gone after drop", c.nest_glow.isHidden())

# 2. releasing BEFORE the dwell does nothing
calls.clear(); c = fresh(); g = grip(c, "b")
c.grip_down(g, Ev(X0, row_y(c, "b")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "c")))
c.grip_up(g, Ev(X0 + 40, row_y(c, "c")))
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.2)     # a stale timer must not act
check("quick release: no write, tree unchanged", not any(x.startswith("fx_") for x in calls)
      and tree(c) == [(x["tid"], x["depth"]) for x in BASE], (calls, tree(c)))

# 3. nested row out to the header (ROOT) - the undo road
calls.clear(); c = fresh(); g = grip(c, "c1"); H = c.panel.frame().size.height
c.grip_down(g, Ev(X0, row_y(c, "c1")))
c.grip_dragged(g, Ev(X0 + 40, H - fb.ROW1_H / 2.0))
check("header is a candidate for a nested row", c._drag["cand"] == fb.fsub.ROOT, c._drag["cand"])
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.25)
c.grip_up(g, Ev(X0 + 40, H - fb.ROW1_H / 2.0))
time.sleep(0.2)
check("c1 back at the top level, last", tree(c)[-1] == ("c1", 1), tree(c))
check("write fired as fx_parent:c1:root", "fx_parent:c1:root" in calls, calls)

# 4. never onto its own child; header refused for a direct child
calls.clear(); c = fresh(); g = grip(c, "a"); H = c.panel.frame().size.height
c.grip_down(g, Ev(X0, row_y(c, "a")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "a1")))
check("own child is never a candidate", c._drag["cand"] is None, c._drag["cand"])
c.grip_dragged(g, Ev(X0 + 40, H - fb.ROW1_H / 2.0))
check("header refused for a direct child (already there)", c._drag["cand"] is None)
c.grip_up(g, Ev(X0 + 40, H - fb.ROW1_H / 2.0))

# 5. drag right then back LEFT: nesting cancels, reorder resumes
calls.clear(); c = fresh(); g = grip(c, "b")
c.grip_down(g, Ev(X0, row_y(c, "b")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "c")))
c.grip_dragged(g, Ev(X0 + 2, row_y(c, "c")))
check("back left: nest off, glow hidden, timer dropped",
      not c._drag["nest"] and c.nest_glow.isHidden() and c._drag["dwell"] is None, c._drag)
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.2)
check("the cancelled timer never armed anything", c._drag["armed"] is None)
c.grip_up(g, Ev(X0 + 2, row_y(c, "c")))

# 6. a FOLDED target unfolds on drop
calls.clear(); c = fresh(); c.folded = ["a"]; c._relayout(); g = grip(c, "b")
c.grip_down(g, Ev(X0, row_y(c, "b")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "a")))
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.25)
c.grip_up(g, Ev(X0 + 40, row_y(c, "a")))
time.sleep(0.2)
check("folded target unfolds and persists", "a" not in c.folded and "persist" in calls, (c.folded, calls))
check("b lands after a's hidden child", tree(c)[:3] == [("a", 1), ("a1", 2), ("b", 2)], tree(c))

# 7. a poll that reshuffles the list mid-drag: never nest on a stale picture
calls.clear(); c = fresh(); g = grip(c, "b")
c.grip_down(g, Ev(X0, row_y(c, "b")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "c")))
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.25)
c.block["items"] = [c.block["items"][k] for k in (0, 1, 3, 2, 4)]   # c before b now
c.grip_up(g, Ev(X0 + 40, row_y(c, "c")))
time.sleep(0.2)
check("list changed mid-drag: no write", not any(x.startswith("fx_parent") for x in calls), calls)

# 8. TickTick refuses: the reason reaches a notification and a re-read is forced
calls.clear(); c = fresh(); g = grip(c, "b")
fb.BarController._xact_direct = lambda self, verb, env_json=False: (
    calls.append(verb) or (lambda: "🎯 TickTick refused the move · try again in a minute"))
c.content_dirty.clear()
c.grip_down(g, Ev(X0, row_y(c, "b")))
c.grip_dragged(g, Ev(X0 + 40, row_y(c, "c")))
spin(NSEventTrackingRunLoopMode, fb.NEST_DWELL + 0.25)
c.grip_up(g, Ev(X0 + 40, row_y(c, "c")))
time.sleep(0.3)
check("a refused write surfaces its reason", any(x.startswith("et:notify:🎯 TickTick refused") for x in calls), calls)
check("and forces an authoritative re-read", c.content_dirty.is_set())

print(f"\nnest harness: {sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
