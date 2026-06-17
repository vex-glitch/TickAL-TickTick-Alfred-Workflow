#!/usr/bin/env python3
"""
attach_image.py — Alfred Run Script

Method 3 (the only one that renders a screenshot): open the task in TickTick —
which brings up that task's floating detail pop-up — then paste the clipboard
image into its description. The Open API can't embed a raw image, so this drives
TickTick's own paste, exactly like doing it by hand but fully automated.

How the click is made robust: the pop-up is its own window. We read its live
bounds via Quartz and click a point *relative to it* (centre width, ~72% height —
between the description and the footer, clear of any link), so it works wherever
the pop-up lands. Everything stays in one (Quartz) coordinate space.

Reads task_list_id / task_id from session vars (with /tmp fallback).
Wire e.g.  ⌘ Actions "🖼️ Add image" → conditional "attach" →
           ensure_task_context.py → this → End.

Needs Accessibility permission for whatever runs it (synthetic click + ⌘V).
Tunables (env, optional):
  ATTACH_OPEN_TIMEOUT  seconds to wait for the pop-up   (default 4)
  ATTACH_CLICK_FRAC    vertical click position in pop-up (default 0.72)
"""
import sys
import os
import time
import subprocess

import Quartz

pid        = os.environ.get("task_list_id") or os.environ.get("list_id", "")
tid        = os.environ.get("task_id", "")
task_title = os.environ.get("task_title", "Task")

if not pid or not tid:
    try:
        with open("/tmp/ticktick_reattribute.txt") as _f:
            _parts = _f.read().strip().split(":", 1)
            if len(_parts) == 2:
                pid, tid = _parts
    except Exception:
        pass

if not tid:
    print("Error: no task selected")
    sys.exit(1)


def find_popup(timeout):
    """Frontmost small TickTick window = the task detail pop-up (just opened)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID)
        for w in wins:  # front-to-back order
            if w.get("kCGWindowOwnerName") != "TickTick":
                continue
            b = w["kCGWindowBounds"]
            if 300 <= b["Width"] <= 820 and 250 <= b["Height"] <= 900:
                return b
        time.sleep(0.2)
    return None


def click(x, y):
    Quartz.CGWarpMouseCursorPosition((x, y))
    time.sleep(0.1)
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.05)


try:
    timeout = float(os.environ.get("ATTACH_OPEN_TIMEOUT", "4"))
except ValueError:
    timeout = 4.0
try:
    frac = float(os.environ.get("ATTACH_CLICK_FRAC", "0.72"))
except ValueError:
    frac = 0.72

# 1) Open the task → its detail pop-up.
subprocess.run(["open", f"ticktick:///webapp/#p/{pid}/tasks/{tid}"], check=False)

# 2) Locate the pop-up window.
box = find_popup(timeout)
if not box:
    print("Couldn't find the TickTick task pop-up — is TickTick running?")
    sys.exit(1)

cx = box["X"] + box["Width"] * 0.5
cy = box["Y"] + box["Height"] * frac

# 3) Focus the description (click) and paste.
subprocess.run(["osascript", "-e", 'tell application "TickTick" to activate'], check=False)
time.sleep(0.25)
click(cx, cy)
time.sleep(0.3)
subprocess.run(
    ["osascript", "-e",
     'tell application "System Events" to keystroke "v" using command down'],
    check=False,
)

print(f"{task_title} · Pasted into TickTick")
