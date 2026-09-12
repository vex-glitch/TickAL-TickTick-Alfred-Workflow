#!/usr/bin/env python3
"""The File ▸ Sync throttle.

On 2026-09-12 two unthrottled clones of the sync nudge fired three clicks
inside 300 ms, the app's sync in-flight guard never cleared, and it silently
stopped pulling for 35 minutes - surfacing as two separate "it did not save"
reports over writes that were on the server all along.

The property that matters is the CONCURRENT one: several processes racing
inside one user action must produce exactly ONE click. A single-process
check would pass even with the race wide open, so this drives real
subprocesses.

    python3 tests/test_app_sync.py
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import app_sync  # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


def _stamp(tag):
    return os.path.join(tempfile.mkdtemp(), f"{tag}.stamp")


s = _stamp("basic")
check("first-claim-wins", app_sync.claim(stamp=s) is True)
check("second-inside-the-gap-loses", app_sync.claim(stamp=s) is False)
check("third-inside-the-gap-loses", app_sync.claim(stamp=s) is False)

s2 = _stamp("gap")
app_sync.claim(stamp=s2)
time.sleep(0.12)
check("claim-reopens-after-the-gap", app_sync.claim(min_gap=0.1, stamp=s2) is True)

# THE regression: the 220 ms double-fire that wedged the app, and the
# three-inside-300 ms bursts, came from SEPARATE processes. Only a
# cross-process claim stops them.
s3 = _stamp("burst")
code = ("import sys; sys.path.insert(0, %r); import app_sync; "
        "print(1 if app_sync.claim(stamp=%r) else 0)" % (SRC, s3))
procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
         for _ in range(8)]
wins = sum(int(p.communicate()[0].strip() or 0) for p in procs)
check("a-burst-of-8-processes-clicks-once", wins == 1, f"clicked {wins}x")

# A throttle that breaks must never cost us the nudge entirely - a missed
# redraw is a papercut, a suppressed sync is the bug we are fixing.
check("unwritable-stamp-still-nudges",
      app_sync.claim(stamp="/nonexistent-dir-xyz/app_sync.stamp") is True)
s4 = _stamp("garbage")
with open(s4, "w") as fh:
    fh.write("not a number at all")
check("garbage-stamp-is-treated-as-never-clicked",
      app_sync.claim(stamp=s4) is True)

# both nudge clones must actually be behind the claim
xact = open(os.path.join(ROOT, "Scripts", "xact.py")).read()
eng = open(os.path.join(SRC, "periodic_engine.py")).read()
check("xact-clone-is-throttled",
      "app_sync.claim()" in xact.split("def _app_sync()")[1][:600], "")
check("engine-clone-is-throttled",
      "app_sync.claim()" in eng.split("def _app_sync_nudge()")[1][:600], "")

print(f"app sync throttle: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
