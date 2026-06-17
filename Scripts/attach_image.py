#!/usr/bin/env python3
"""
attach_image.py — Alfred Run Script

Attaches the clipboard image (e.g. a CleanShot X screenshot) to the selected task
as a REAL TickTick attachment, via the internal v2 API (src/api_v2.py). It renders
inline on the task and syncs to every device — exactly like pasting in the app,
but with no UI automation.

Reads task_list_id / task_id / task_title from session vars (with /tmp fallback).
Wire: ⌘ Actions "🖼️ Add image" → conditional "attach" → ensure_task_context.py
      → this → End.

Auth is handled by src/api_v2 — it uses the TickTick session token captured into
the Keychain (service ticktick_v2_token) by Scripts/save_token.py. Sign-in-with-
Apple accounts have no password, so there's no auto-login; if the token expires,
api_v2 returns a clear "recapture your token" message.
"""
import sys
import os

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
sys.path.insert(0, SRC_DIR)

import api_v2
import clipboard as clip_util


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

if not pid or not tid:
    print("Error: missing task context")
    sys.exit(1)

img = clip_util.png_bytes()
if not img:
    print("Clipboard has no image — take a screenshot first")
    sys.exit(1)

try:
    api_v2.TickTickV2().upload_attachment(pid, tid, img, "screenshot.png")
    print(f"{task_title} · Image attached")
except api_v2.V2AuthError as e:
    print(f"Image attach failed — {e}")
    sys.exit(1)
except Exception as e:
    print(f"Image attach failed: {type(e).__name__}: {e}")
    sys.exit(1)
