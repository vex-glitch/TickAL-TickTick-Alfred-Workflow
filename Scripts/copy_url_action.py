#!/usr/bin/env python3
"""
copy_url_action.py - Alfred Run Script
Copies a TickTick deep-link URL to the clipboard and shows a macOS notification.
$1 is expected in the form "copy:ticktick://..." - the "copy:" prefix is stripped.
Prints nothing to stdout so Alfred does not route the text into subsequent nodes.
"""
import sys
import os
import subprocess

arg        = sys.argv[1] if len(sys.argv) > 1 else ""
task_title = os.environ.get("task_title", "")

url = arg[len("copy:"):] if arg.startswith("copy:") else arg

if not url:
    sys.exit(1)

subprocess.run("pbcopy", input=url.encode(), check=True)

# Bare TickTick ids ride the same verb as URLs (the 🆔 Copy id rows)
what = "URL" if "://" in url else "id"
title = f"{task_title} · {what} Copied" if task_title else f"{what} Copied"
print(f"{title}\n{url}")

# Act-again: reopen the ⌘ Actions menu after copying - ONLY when the copy
# was fired FROM that menu. Browse rows carry task_list_id/task_id too, so
# the old pid+tid test made every ⌥⌘ row chord pop the Actions menu open
# (Vex smoke 2026-07-28: "that should not happen on a modifier"). The loop
# belongs to ⏎ on an Actions row; actions.py stamps actions_loop on its own.
_pid, _tid = os.environ.get("task_list_id", ""), os.environ.get("task_id", "")
if _pid and _tid and os.environ.get("actions_loop") == "1":
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as _f:
            _f.write(f"{_pid}:{_tid}")
        subprocess.run(["osascript", "-e",
            'tell application id "com.runningwithcrayons.Alfred" to run trigger '
            '"Actions" in workflow "com.vex.tickal"'], check=False)
    except OSError:
        pass
