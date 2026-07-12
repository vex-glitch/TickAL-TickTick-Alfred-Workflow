"""script_base.py — shared bootstrap + Alfred emitters for Scripts/*.py.

Kills the copy-pasted per-script header (fallback emit/emit_error defs plus the
SCRIPT_DIR/WORKFLOW_DIR/SRC_DIR sys.path block). Every script now opens with a
byte-identical one-line stanza followed by a guarded import:

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    try:
        from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
        bootstrap()
    except Exception as e:
        print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                     "subtitle": f"Path setup failed: {e}", "valid": False}]}))
        sys.exit(0)

Failure property (the whole point of the old inline pattern, preserved here):
Alfred must receive valid JSON even when src/ imports explode.

* script_base imports NOTHING outside the stdlib, so `from script_base import…`
  can only fail if src/ itself is missing/unreadable — and the stanza's inline
  `except` covers exactly that case with a hand-rolled JSON print (that print is
  the only fallback code left in each script; Run-Script nodes use a plain-text
  `print(f"Path error: {e}")` variant instead, matching their old channel).
* The per-script `try: import config …` blocks stay in each file: their failure
  messages are script-specific ("Import failed: {e}", "| SRC_DIR=…", etc.) and
  by the time they run, script_base's emit_error is safely importable.

sys.path after bootstrap(): [SRC_DIR, SRC_DIR/lib, <Scripts/ auto-entry>, …] —
the exact order the old per-script header produced (src shadows lib). bootstrap
is idempotent: it removes any pre-existing entries (including the stanza's own
src insert) before re-inserting, so repeated calls can't stack duplicates.
"""
import json
import os
import sys

SRC_DIR      = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SRC_DIR)
LIB_DIR      = os.path.join(SRC_DIR, "lib")

# Runtime state (buffer, focus session, bar position, …) lives per-user with
# 0700 perms — a shared /tmp would let any local account read or pre-create it.
RUN_DIR = os.path.join(os.path.expanduser("~"), ".ticktick_alfred", "run")


def run_path(name):
    """Absolute path for a runtime-state file, creating RUN_DIR on first use
    and adopting any pre-move copy still sitting in /tmp (one-time)."""
    try:
        if not os.path.isdir(RUN_DIR):
            os.makedirs(RUN_DIR, exist_ok=True)
        os.chmod(RUN_DIR, 0o700)
    except OSError:
        pass
    new = os.path.join(RUN_DIR, name)
    old = os.path.join("/tmp", name)
    if not os.path.exists(new) and os.path.isfile(old):
        try:
            os.replace(old, new)
        except OSError:
            pass
    return new


def bootstrap():
    """Idempotent sys.path setup: ensure [SRC_DIR, LIB_DIR, …] at the front."""
    for _p in (SRC_DIR, LIB_DIR):
        while _p in sys.path:
            sys.path.remove(_p)
    sys.path.insert(0, LIB_DIR)
    sys.path.insert(0, SRC_DIR)


def emit(items):
    """Print an Alfred script-filter JSON document (canonical fallback shape)."""
    print(json.dumps({"items": items}))


def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])


def notify(text, title="TickAL"):
    """User-visible notification. Primary route: Alfred's own
    notification chain — fire ET XAct with the pass-through `notify` verb;
    Alfred has Notification-Center permission, while bare osascript under
    launchd usually doesn't (the invisible-hourly-sync bug). Fallback: plain
    `display notification` for when Alfred isn't running."""
    import subprocess
    msg = f"{title} · {text}" if title else text
    msg = msg.replace("\\", "").replace('"', "'")
    r = subprocess.run(
        ["osascript", "-e",
         'tell application id "com.runningwithcrayons.Alfred" to run trigger '
         f'"XAct" in workflow "com.vex.tickal" with argument "xact:notify:{msg}"'],
        capture_output=True, check=False)
    if r.returncode != 0:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "TickAL"'],
                       check=False)


def reopen_actions(pid, tid):
    """Act-again: reopen the ⌘ Actions menu on a task with fresh values.
    Writes the context temp file (single-writer convention) and fires the
    Actions trigger — Alfred is closed when executors run, so the window opens
    live. No-ops silently without full context."""
    if not pid or not tid:
        return
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as f:
            f.write(f"{pid}:{tid}")
    except OSError:
        return
    import subprocess
    subprocess.run(
        ["osascript", "-e",
         'tell application id "com.runningwithcrayons.Alfred" to run trigger '
         '"Actions" in workflow "com.vex.tickal"'],
        check=False)
