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

# Act-again: reopen the ⌘ Actions menu on the task after copying (loop UX).
_pid, _tid = os.environ.get("task_list_id", ""), os.environ.get("task_id", "")
if _pid and _tid:
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as _f:
            _f.write(f"{_pid}:{_tid}")
        subprocess.run(["osascript", "-e",
            'tell application id "com.runningwithcrayons.Alfred" to run trigger '
            '"Actions" in workflow "com.vex.tickal"'], check=False)
    except OSError:
        pass
