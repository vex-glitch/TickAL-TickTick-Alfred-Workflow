"""repeat_settle.py - make the TickTick Mac app keep a repeating task's completed copy.

Vex 2026-09-13, finishing 🌆 Shutdown with the Finish link: "Shutdown has
immediately dissapeared from calendar - it was removed from todays timeblock."
He runs the calendar with "show completed tasks" on.

What happens (probed on throwaway ZZVIS repeats + the app's own store,
2026-09-13): the v1 complete of a repeating task makes the server mint a
COMPLETED COPY of that occurrence (new id, repeatTaskId = the series) and roll
the series forward. The Mac app (8.2.02) pulls both, saves the rolled series
and silently drops the copy - no row in its store, nothing in its log - so the
occurrence's slot goes empty. Every copy after a series' first was dropped:
4 real routine copies (09-12, 09-13) and 4 of 4 test copies, with or without a
reminder, tag, column or open sticky. Not a timing race either.

What fixes it: the copy delivered AGAIN, after any real change to it on the
server, is saved - 8 of 8, including tonight's Shutdown and a resend landing
1.3 s after the complete, inside the very same app pull. So right after every
complete, this module finds the new copy and resends it with its sortOrder
nudged by one (invisible: a completed copy sorts by completion). An unchanged
resend does NOT work - the server keeps the old version and nothing is pulled.

Safety (the double-completion lesson, see pm.sweep_verdict): this never
completes anything and never writes the series. It writes only a task whose
repeatTaskId is the completed id, whose own id is not, and whose status is
already 2 - probed: the update keeps it completed and does not roll the series
or mint another copy.

api.complete_task spawns it detached (spawn) so no completion waits on it;
`python3 src/repeat_settle.py <pid> <tid> <since-epoch>` is that child.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

_SRC = os.path.dirname(os.path.abspath(__file__))
LOG = "/tmp/tickal_settle.log"
WAITS = (0.8, 1.5, 3.0)      # the copy showed in the feed ~0.7 s after the complete


def _epoch(iso):
    try:
        return datetime.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def pick_copies(feed, tid, since, slack=90.0):
    """The completed copies this complete just minted: repeatTaskId == tid,
    never the series itself, status 2, completed no earlier than `since`
    (epoch seconds) minus `slack` for clock skew."""
    out = []
    for c in feed or []:
        if c.get("repeatTaskId") != tid or c.get("id") in (None, tid):
            continue
        if c.get("status") != 2:
            continue
        done = _epoch(c.get("completedTime"))
        if done is None or done < since - slack:
            continue
        out.append(c)
    return out


def nudge_body(copy):
    """The copy with a real, invisible change, so the server takes a new
    version and the app pulls it again."""
    body = {k: v for k, v in copy.items() if not k.startswith("_")}
    body["sortOrder"] = (copy.get("sortOrder") or 0) - 1
    return body


def settle(pid, tid, since, api, v2, sleep=time.sleep, log=None):
    """Find and resend the copy. Returns a short verdict string."""
    say = log or (lambda m: None)
    try:
        series = api.get_task(pid, tid) or {}
    except Exception as e:
        # logged: a rate-limited read means the routine vanishes again, and
        # this line is the only trace of why
        msg = f"skip {tid}: series read failed ({type(e).__name__})"
        say(msg)
        return msg
    if not series.get("repeatFlag"):
        return f"skip {tid}: not a repeat"
    pid = series.get("projectId") or pid
    name = series.get("title", tid)
    failed = None
    for wait in WAITS:
        sleep(wait)
        copies = pick_copies(v2.project_completed(pid, days=1, limit=100), tid, since)
        if not copies:
            continue
        if v2.update_tasks([nudge_body(c) for c in copies]):
            msg = f"resent {len(copies)} copy of {name!r}: " + ", ".join(c['id'] for c in copies)
            say(msg)
            return msg
        failed = copies          # a blip on the write gets the remaining waits too
    if failed:
        msg = f"RESEND FAILED {len(failed)} copy of {name!r}: " + ", ".join(c['id'] for c in failed)
    else:
        msg = f"no copy found for {name!r} ({tid})"
    say(msg)
    return msg


def spawn(pid, tid):
    """Run settle() detached. Never raises, never blocks the completion.
    TICKAL_NO_SETTLE=1 turns it off (tests, the settle child itself)."""
    if os.environ.get("TICKAL_NO_SETTLE") or not pid or not tid:
        return False
    try:
        py = os.path.join(os.path.dirname(_SRC), "Scripts", "py.sh")
        with open(LOG, "a") as logf:
            subprocess.Popen(["/bin/bash", py, os.path.abspath(__file__), pid, tid, str(time.time())],
                             stdout=logf, stderr=logf, start_new_session=True,
                             env=dict(os.environ, TICKAL_NO_SETTLE="1"))
        return True
    except Exception:
        return False


def main(argv):
    pid, tid, since = argv[1], argv[2], float(argv[3])
    sys.path.insert(0, _SRC)
    import config as cfg
    import api_v2
    from api import TickTickAPI
    stamp = lambda m: print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {m}", flush=True)
    settle(pid, tid, since, TickTickAPI(cfg.get_token()), api_v2.TickTickV2(), log=stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
