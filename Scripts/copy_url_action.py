#!/usr/bin/env python3
"""
copy_url_action.py — Alfred Run Script
Copies a TickTick deep-link URL to the clipboard and shows a macOS notification.
$1 is expected in the form "copy:ticktick://..." — the "copy:" prefix is stripped.
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

title = f"{task_title} · URL Copied" if task_title else "URL Copied"
print(f"{title}\n{url}")
