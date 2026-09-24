#!/usr/bin/env python3
"""verify.py - acceptance for the 2026-09-24 review work order.

Prints, per round-1 item, red or green (from tests/test_review_20260924.py),
then: make test, the diff's file list against the allowed list, no en or em
dashes in added lines, info.plist untouched, and every changed .py byte
identical to its live copy (read-only compare; the live path comes from
local.mk). Exit 0 only when everything is clean. Read-only: it changes
nothing.

    python3.13 tests/verify_review_20260924.py [--no-make]
"""
import filecmp
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "340553e"
ALLOWED = {
    "src/day_move.py", "src/periodic_engine.py", "src/fuzzy.py", "src/done_sync.py",
    "src/goal_handoff.py", "Scripts/xact.py", "Scripts/periodic_rows.py", "Scripts/link.py",
    "tests/test_routine_link.py", "tests/test_journal_goal.py", "tests/test_pn_sync.py",
    "tests/test_monthly_note.py", "tests/test_quarterly_note.py", "tests/test_review_20260924.py",
    "tests/verify_review_20260924.py", "Makefile", "docs/48-periodic.md", "CLAUDE.md",
}
DASHES = re.compile("[–—]")
PY = sys.executable


def sh(*cmd, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)


def main():
    bad = 0
    env = dict(os.environ, TICKAL_NO_SETTLE="1")

    print("== review tests ==")
    r = sh(PY, "tests/test_review_20260924.py", env=env)
    for ln in r.stdout.splitlines():
        if ln.startswith("ITEM ") or ln.startswith("review 2026-09-24"):
            print("  " + ln)
    if r.returncode != 0:
        bad += 1
        for ln in r.stdout.splitlines():
            if ln.startswith("  FAIL"):
                print("  " + ln.strip()[:200])

    if "--no-make" not in sys.argv:
        print("== make test ==")
        r = sh("make", "test", env=env)
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        print("  " + (" | ".join(t.strip() for t in tail) if tail else "(no output)"))
        if r.returncode != 0:
            bad += 1
            print("  FAIL make test exit", r.returncode)

    print("== diff ==")
    committed = sh("git", "diff", "--name-only", f"{BASE}..HEAD").stdout.split()
    tree = [ln[3:].strip().strip('"') for ln in sh("git", "status", "--porcelain").stdout.splitlines()
            if ln and not ln.startswith("??")]
    changed = sorted(set(committed) | set(tree))
    for f in changed:
        flag = "" if f in ALLOWED else "   NOT IN THE ALLOWED LIST"
        if flag:
            bad += 1
        print(f"  {f}{flag}")
    if "info.plist" in changed:
        bad += 1
        print("  FAIL info.plist changed: the canvas is Vex's")

    print("== dashes in added lines ==")
    added = sh("git", "diff", BASE, "-U0").stdout
    hits = [ln for ln in added.splitlines() if ln.startswith("+") and not ln.startswith("+++") and DASHES.search(ln)]
    for ln in hits[:10]:
        print("  " + ln[:120])
    if hits:
        bad += 1
        print(f"  FAIL {len(hits)} added line(s) carry an en or em dash")
    else:
        print("  none")

    print("== live sync (read-only compare) ==")
    live = None
    try:
        with open(os.path.join(ROOT, "local.mk"), encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("LIVE"):
                    live = ln.split(":=", 1)[1].strip().replace("$(HOME)", os.path.expanduser("~"))
    except OSError:
        pass
    if not live or not os.path.isdir(live):
        print("  local.mk has no usable LIVE path: skipped")
    else:
        for f in changed:
            if not f.endswith(".py") or not f.startswith(("src/", "Scripts/")):
                continue
            here, there = os.path.join(ROOT, f), os.path.join(live, f)
            if not os.path.exists(there):
                print(f"  {f}: no live copy")
                bad += 1
            elif filecmp.cmp(here, there, shallow=False):
                print(f"  {f}: synced")
            else:
                print(f"  {f}: STALE, run make sync-push FILE={f}")
                bad += 1

    print("== result ==")
    print("  CLEAN" if not bad else f"  {bad} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
