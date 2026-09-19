#!/usr/bin/env python3
"""
meal_migrate.py - ONE-SHOT migration: 🍳Meal Prep recipe NOTES → dateless TEXT tasks.

WHY. The 🍳Meal Prep list (6a8abb444e699108a4693fa5) holds ~112 recipe entries
titled "[Name](mela://recipe/<UUID>)" (the app may backslash-escape the
brackets). They were created as NOTE-kind items carrying a week-long all-day
span (startDate → dueDate), so every recipe sits on the calendar and in
Today / Next 7 days. Each must become a plain TEXT task with NO dates -
title, content, tags, columnId, projectId and sortOrder kept. Only entries
whose (unescaped) title contains "mela://recipe/" are in scope; of those,
only NOTE-kind or still-dated ones are migrated.

  python3 Scripts/meal_migrate.py [--list <pid>] [--pace 1.5] [--limit N]   DRY RUN
  python3 Scripts/meal_migrate.py --probe <tid>      migrate ONE, read back, verdicts
  python3 Scripts/meal_migrate.py --apply            migrate every in-scope entry + verify
  python3 Scripts/meal_migrate.py --rollback <file>  restore every object in a snapshot

Ladder: dry run → --probe <tid> → --apply --limit 5 → --apply. If anything
looks wrong: --rollback <the snapshot path the run printed>.

TRAPS (each one is a real bug this workflow has already paid for):
  • GET /project/{id}/data OMITS NOTE bodies (content). A full-object write
    built from a project-data row would WIPE every description. So each entry
    is read LIVE with get_task(pid, tid) before it is written, and the write's
    `current` is that live object - never the project-data row, never the cache.
  • The v1 API ignores partial updates: update_task posts the FULL object. A
    field passed as None serialises as JSON null and CLEARS it on the server -
    that is how startDate / dueDate / repeatFlag are removed here, and also why
    a stale or partial `current` is dangerous.
  • Rate budget: 300 requests / 5 min, answered as HTTP 500 → RateLimitError.
    Every call is paced (--pace, default 1.5 s; keep it ≥ 1 s). A full --apply
    is 1 scan + N reads + N writes + 1 verify ≈ 230 calls over ~6 min. Run it
    right AFTER an hourly sync has finished, so the next sync is an hour away
    and cannot collide with it (budget or cache).
  • Snapshot first: --probe / --apply write every live object to
    ~/.ticktick_alfred/run/meal_migrate_<YYYYmmdd-HHMM>.json (0600, atomic)
    BEFORE the first write. That file is the --rollback input. The dry run
    writes nothing at all - not even a snapshot.
  • The Open API may refuse the kind change (NOTE → TEXT). --probe says so
    clearly; the fallback is the internal v2 API (not implemented here).
  • After --apply / --rollback the all_tasks + all_notes caches are
    invalidated: run a sync (tsy) to rebuild them. A --probe leaves the cache
    alone (one stale row until the next sync).
"""
import argparse
import json
import os
import re
import sys
import time

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, run_path
bootstrap()

import config as cfg                          # noqa: E402
import cache as cache_store                   # noqa: E402
from api import TickTickAPI, RateLimitError   # noqa: E402

try:                                          # the app escapes "\[Name\]\(mela://…\)"
    from periodic_model import unescape_md
except Exception:                             # keep the one-shot standalone if that moves
    _MD_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")

    def unescape_md(text):
        text = text or ""
        for _ in range(4):                    # the app can escape an escape again
            out = _MD_ESCAPE_RE.sub(r"\1", text)
            if out == text:
                break
            text = out
        return text

MEAL_LIST_ID = "6a8abb444e699108a4693fa5"      # 🍳Meal Prep
MELA = "mela://recipe/"
# The migration write. None → JSON null → the server clears the field.
MIGRATE_FIELDS = dict(kind="TEXT", startDate=None, dueDate=None,
                      isAllDay=False, repeatFlag=None)
PHASE = ["start"]                              # which step a RateLimitError hit


class Pacer:
    """Sleep --pace seconds between API calls (300 req / 5 min budget)."""

    def __init__(self, pace):
        self.pace = pace
        self.calls = 0

    def __call__(self, phase=None):
        if phase:
            PHASE[0] = phase
        if self.calls:
            time.sleep(self.pace)
        self.calls += 1


# ── helpers ──────────────────────────────────────────────────────────────────
def _title(t):
    return unescape_md(t.get("title") or "")


def in_scope(t):
    """A recipe entry: its unescaped title carries the Mela link."""
    return MELA in _title(t)


def is_dated(t):
    return bool(t.get("startDate") or t.get("dueDate"))


def needs_migration(t):
    """NOTE-kind, or a TEXT entry that still carries its week span."""
    return t.get("kind") == "NOTE" or is_dated(t)


def _d(v):
    """Date cell: the day of a TickTick timestamp, ∅ when absent."""
    return (v or "")[:10] or "∅"


HEADER = (f"{'tid':<24} {'kind':<5} {'startDate':>10}   {'dueDate':>10}   "
          f"{'allDay':<6} {'tags':<18} {'chars':>5}  title")


def _chars(t):
    """Content cell: '-' when the key is ABSENT from the object (the API did
    not return a body at all) vs '0' when it is present but empty."""
    return "-" if "content" not in t else str(len(t.get("content") or ""))


def _row(t):
    tags = ",".join(t.get("tags") or []) or "-"
    return (f"{t.get('id', '?'):<24} {t.get('kind') or '-':<5} "
            f"{_d(t.get('startDate')):>10}→∅ {_d(t.get('dueDate')):>10}→∅ "
            f"{str(t.get('isAllDay')):<6} {tags[:18]:<18} "
            f"{_chars(t):>5}  {_title(t)[:40]}")


def _kinds(rows):
    """'NOTE 98 · TEXT 14' over rows (absent kind = TEXT, the API default)."""
    c = {}
    for t in rows:
        k = t.get("kind") or "TEXT"
        c[k] = c.get(k, 0) + 1
    return " · ".join(f"{k} {n}" for k, n in sorted(c.items())) or "none"


def save_snapshot(pid, tasks):
    """Atomic 0600 write of the live objects - the --rollback input."""
    stamp = time.strftime("%Y%m%d-%H%M")
    path = run_path(f"meal_migrate_{stamp}.json")
    if os.path.exists(path):                   # same minute: never clobber one
        path = run_path(f"meal_migrate_{stamp}-{time.strftime('%S')}.json")
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"list_id": pid, "taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "tasks": tasks}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def scan(api, pid, pace):
    """One project-data read → every recipe (both kinds) + the ones to migrate."""
    pace("scan")
    data = api.get_project_data(pid)
    tasks = data.get("tasks") or []
    recipes = [t for t in tasks if in_scope(t)]
    todo = [t for t in recipes if needs_migration(t)]
    name = (data.get("project") or {}).get("name") or pid
    print(f"🍳 {name} ({pid}): {len(tasks)} entries · {len(recipes)} recipes "
          f"[{_kinds(recipes)}] · {len(todo)} to migrate (NOTE-kind or dated) · "
          f"{len(recipes) - len(todo)} already TEXT + dateless")
    return recipes, todo


def read_live(api, pid, rows, pace, limit):
    """LIVE get_task per entry - project data omits NOTE bodies, so a write
    from those rows would wipe descriptions. --limit caps the batch."""
    if limit is not None:
        rows = rows[:limit]
    live = []
    for i, t in enumerate(rows, 1):
        pace("reads")
        live.append(api.get_task(pid, t["id"]))
        print(f"\r  live read {i}/{len(rows)}", end="", flush=True)
    if rows:
        print()
    return live


def verdicts(before, after):
    """[(name, passed, detail)] - the probe's checks on the read-back object."""
    kind = after.get("kind")
    b_c, a_c = before.get("content") or "", after.get("content") or ""
    b_tags = sorted(before.get("tags") or [])
    a_tags = sorted(after.get("tags") or [])
    return [
        ("kind == TEXT", kind == "TEXT" or kind is None,
         f"kind={kind!r}" + (" (absent - the API default is TEXT)" if kind is None else "")),
        ("startDate cleared", after.get("startDate") is None,
         f"startDate={after.get('startDate')!r}"),
        ("dueDate cleared", after.get("dueDate") is None,
         f"dueDate={after.get('dueDate')!r}"),
        ("content unchanged", a_c == b_c, f"{len(b_c)} → {len(a_c)} chars"),
        ("tags unchanged", a_tags == b_tags, f"{b_tags} → {a_tags}"),
        ("columnId unchanged", after.get("columnId") == before.get("columnId"),
         f"{before.get('columnId')!r} → {after.get('columnId')!r}"),
        ("projectId unchanged", after.get("projectId") == before.get("projectId"),
         f"{before.get('projectId')!r} → {after.get('projectId')!r}"),
    ]


def _invalidate():
    for key in ("all_tasks", "all_notes"):
        cache_store.invalidate(key)
    print("cache invalidated (all_tasks, all_notes) - run a sync (tsy) to rebuild the cache")


# ── modes ────────────────────────────────────────────────────────────────────
def mode_dry(api, pid, pace, limit):
    _, todo = scan(api, pid, pace)
    live = read_live(api, pid, todo, pace, limit)
    if live:
        print(HEADER)
        for t in live:
            print(_row(t))
    dated = sum(1 for t in live if is_dated(t))
    chars = sum(len(t.get("content") or "") for t in live)
    tagged = sum(1 for t in live if t.get("tags"))
    print(f"\ntotals: {len(live)} read live [{_kinds(live)}] · {dated} dated · "
          f"{tagged} tagged · {chars} content chars")
    empty = [t for t in live if not (t.get("content") or "")]
    if empty:
        absent = sum(1 for t in empty if "content" not in t)
        print(f"{len(empty)} with EMPTY live content ({absent} key absent, "
              f"{len(empty) - absent} empty string) - informational. If these notes DO "
              f"show a body in the app, v1 get_task is not returning it: probe one such "
              f"note and check its body in the app before --apply.")
        for t in empty:
            print(f"  {t['id']}  {_title(t)[:60]}")
    capped = f" (--limit {limit})" if limit is not None and limit < len(todo) else ""
    return 0, (f"DRY RUN - nothing written · {len(live)}/{len(todo)} to-migrate entries "
               f"read live{capped} · next: --probe <tid>, then --apply")


def mode_probe(api, pid, tid, pace):
    pace("probe read")
    live = api.get_task(pid, tid)
    print(HEADER)
    print(_row(live))
    if not in_scope(live):
        return 2, f"PROBE refused - {tid}: title carries no {MELA} link (out of scope)"
    if not needs_migration(live):
        return 0, f"PROBE {tid}: already TEXT and dateless - nothing to do, nothing written"
    snap = save_snapshot(pid, [live])
    print(f"snapshot → {snap}")
    pace("probe write")
    api.update_task(tid, pid, current=live, **MIGRATE_FIELDS)
    pace("probe read-back")
    after = api.get_task(pid, tid)
    print(_row(after))
    ok = True
    for name, passed, detail in verdicts(live, after):
        ok = ok and passed
        print(f"  {'✓' if passed else '✗'} {name:<20} {detail}")
    if after.get("kind") == "NOTE":
        print("!! the server kept kind=NOTE: the Open API refused the NOTE → TEXT change.\n"
              "   Fallback: the internal v2 API (batch/task with kind) - not implemented here.\n"
              f"   The dates {'were' if after.get('startDate') is None else 'were NOT'} cleared.")
    print("cache untouched (this one row is stale until the next sync)")
    verdict = "ALL VERDICTS PASS" if ok else "FAILED - see ✗ above"
    return (0 if ok else 1), f"PROBE {tid}: {verdict} · undo: --rollback {snap}"


def _write_loop(api, pid, rows, pace, fields_for, label, resume):
    """Paced full-object writes. RateLimitError STOPS the loop (the budget is
    spent - retrying only deepens the lockout); any other error is logged and
    the loop goes on. Returns (done_ids, failed, limited)."""
    done, failed, limited = [], [], False
    for i, t in enumerate(rows, 1):
        tid = t.get("id")
        try:
            pace(label)
            api.update_task(tid, pid, current=t, **fields_for(t))
            done.append(tid)
            print(f"  {i}/{len(rows)} ✓ {tid}  {_title(t)[:40]}")
        except RateLimitError as e:
            limited = True
            print(f"\n!! RATE LIMIT after {len(done)} written: {e}\n"
                  f"   Stopping. Wait 5 min, then {resume}.")
            break
        except Exception as e:
            failed.append((tid, f"{type(e).__name__}: {e}"))
            print(f"  {i}/{len(rows)} ✗ {tid}  {type(e).__name__}: {e}")
    return done, failed, limited


def verify(api, pid, done, pace):
    """One project-data read: kind, dates and the link for every written id."""
    pace("verify")
    data = api.get_project_data(pid)
    by_id = {t.get("id"): t for t in (data.get("tasks") or [])}
    n_text = n_dated = n_linked = 0
    mism = []
    for tid in done:
        t = by_id.get(tid)
        if t is None:
            mism.append((tid, "missing from project data"))
            continue
        kind = t.get("kind")
        if kind == "TEXT" or kind is None:
            n_text += 1
        else:
            mism.append((tid, f"kind={kind!r}"))
        if is_dated(t):
            n_dated += 1
            mism.append((tid, f"still dated {_d(t.get('startDate'))}→{_d(t.get('dueDate'))}"))
        if in_scope(t):
            n_linked += 1
        else:
            mism.append((tid, "title lost the mela link"))
    recipes = [t for t in by_id.values() if in_scope(t)]
    print(f"verify: of {len(done)} written - {n_text} kind TEXT · {n_dated} still dated · "
          f"{n_linked} titles keep the link · list now [{_kinds(recipes)}], "
          f"{sum(1 for t in recipes if is_dated(t))} recipes still dated")
    for tid, why in mism:
        print(f"  ✗ {tid}  {why}")
    return mism


def mode_apply(api, pid, pace, limit):
    _, todo = scan(api, pid, pace)
    live = read_live(api, pid, todo, pace, limit)
    if not live:
        return 0, "APPLY: nothing to migrate - every recipe is already TEXT and dateless"
    snap = save_snapshot(pid, live)
    print(f"snapshot → {snap}  (the --rollback input)")
    done, failed, limited = _write_loop(
        api, pid, live, pace, lambda t: MIGRATE_FIELDS, "apply",
        "re-run --apply: the scan skips what is already migrated")
    mism = []
    if done:
        try:
            mism = verify(api, pid, done, pace)
        except RateLimitError as e:
            print(f"verify skipped - rate limit: {e}")
            mism = [("verify", "skipped (rate limit) - run a dry run later")]
    _invalidate()
    for tid, why in failed:
        print(f"  failed {tid}: {why}")
    rc = 1 if (failed or mism or limited) else 0
    return rc, (f"APPLY: {len(done)}/{len(live)} written · {len(failed)} failed · "
                f"{len(mism)} verify mismatches"
                f"{' · STOPPED by rate limit' if limited else ''} · undo: --rollback {snap}")


def mode_rollback(api, pid, path, pace, limit):
    with open(path) as f:
        snap = json.load(f)
    rows = snap.get("tasks") or []
    list_id = snap.get("list_id") or pid
    if list_id != pid:
        print(f"note: the snapshot's list {list_id} wins over --list {pid}")
    if limit is not None:
        rows = rows[:limit]
    print(f"rollback {len(rows)} entries from {path} (taken {snap.get('taken')})")

    def fields_for(s):
        f = dict(startDate=s.get("startDate"), dueDate=s.get("dueDate"),
                 isAllDay=s.get("isAllDay", True), repeatFlag=s.get("repeatFlag"))
        if s.get("kind"):                  # absent in the saved object → API default
            f["kind"] = s["kind"]
        return f

    done, failed, limited = _write_loop(
        api, list_id, rows, pace, fields_for, "rollback",
        "re-run --rollback (restoring an already-restored row is harmless)")
    _invalidate()
    for tid, why in failed:
        print(f"  failed {tid}: {why}")
    rc = 1 if (failed or limited) else 0
    return rc, (f"ROLLBACK: {len(done)}/{len(rows)} restored · {len(failed)} failed"
                f"{' · STOPPED by rate limit' if limited else ''}")


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="meal_migrate.py",
        description="ONE-SHOT: 🍳Meal Prep recipe NOTES → dateless TEXT tasks. "
                    "No mode flag = DRY RUN (live reads, nothing written).",
        epilog="Ladder: dry run → --probe <tid> → --apply --limit 5 → --apply. "
               "Undo: --rollback <the snapshot path a run printed>. Run right after "
               "an hourly sync has finished (300 requests / 5 min budget).")
    ap.add_argument("--list", default=MEAL_LIST_ID, metavar="PID",
                    help=f"list id (default: 🍳Meal Prep {MEAL_LIST_ID})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--probe", metavar="TID",
                      help="migrate ONE task, read it back, print a verdict per check")
    mode.add_argument("--apply", action="store_true",
                      help="migrate every in-scope entry, then verify")
    mode.add_argument("--rollback", metavar="FILE",
                      help="restore every object saved in a snapshot file")
    ap.add_argument("--pace", type=float, default=1.5, metavar="S",
                    help="seconds between API calls (default 1.5; keep it >= 1)")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="process at most N entries in any mode (a first small --apply)")
    a = ap.parse_args(argv)
    if a.limit is not None and a.limit < 1:
        ap.error("--limit must be >= 1")
    if a.pace < 1.0:
        print(f"warning: --pace {a.pace} is under 1 s - the budget is 300 requests / 5 min")
    token = cfg.get_token()
    if not token:
        print("no TickTick token in ~/.ticktick_alfred/config.json - authorise the workflow first")
        return 2
    api = TickTickAPI(token)
    pace = Pacer(max(a.pace, 0.0))
    t0 = time.time()
    try:
        if a.probe:
            rc, summary = mode_probe(api, a.list, a.probe, pace)
        elif a.apply:
            rc, summary = mode_apply(api, a.list, pace, a.limit)
        elif a.rollback:
            rc, summary = mode_rollback(api, a.list, a.rollback, pace, a.limit)
        else:
            rc, summary = mode_dry(api, a.list, pace, a.limit)
    except RateLimitError as e:
        wrote = PHASE[0] == "probe read-back"
        rc, summary = 1, (f"RATE LIMIT during {PHASE[0]}: {e} - "
                          + ("the probe write DID go through; check it with a dry run later"
                             if wrote else "nothing was written in this phase")
                          + " · wait 5 min before retrying")
    except KeyboardInterrupt:
        rc, summary = 130, (f"INTERRUPTED during {PHASE[0]} - a snapshot path printed "
                            "above is the --rollback input")
    print(f"\n{summary} · {pace.calls} API calls · {time.time() - t0:.0f} s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
