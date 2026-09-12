"""app_sync.py - the ONE throttle in front of TickTick's File ▸ Sync click.

We click File ▸ Sync after a content write so an open sticky redraws in
seconds instead of waiting out the app's own ~1 min cadence. Two clones do
it (Scripts/xact.py:_app_sync and periodic_engine._app_sync_nudge, which
cannot import Scripts/), several call sites fire per user action, and each
ran with no throttle whatsoever.

On 2026-09-12 that wedged the app. Its log shows a manual sync at
21:56:00.777 logging "big sync: will pull", then a SECOND one 220 ms later
at 21:56:00.997 with no "will pull" at all - and from that instant not one
sync in the next 35 minutes ever reached "will pull" again. The in-flight
guard never cleared. The app kept running, kept reporting success to us, and
silently stopped pulling: a Nesko log written at 22:10 and 22:13 was on the
server but invisible in his app, and the daily note he was reading was a
render from before 22:07. Two "nothing saved" bug reports, one wedged sync.

The bursts are ours and they are unmistakable in the log - three clicks
inside 300 ms at 22:10:38 and again at 22:13:10. A human hotkey cannot do
that. So: one click per MIN_GAP, claimed under a file lock so that three
processes racing inside one user action produce ONE click.

Coalescing is safe because File ▸ Sync is a FULL sync, not a per-task one -
a click covers every write that landed before it. MIN_GAP is deliberately
short so a write a few seconds later still gets its own nudge.

Pure-ish: stdlib only, no workflow imports.
"""
import os
import time

STAMP = os.path.expanduser("~/.ticktick_alfred/app_sync.stamp")
MIN_GAP = 3.0          # seconds; every observed wedge burst was < 0.35s apart


def claim(min_gap=MIN_GAP, stamp=STAMP):
    """True when this process may click Sync now, False when a click already
    went out inside `min_gap`.

    The check and the stamp update happen under an exclusive flock, so the
    220 ms double-fire that wedged the app cannot pass twice. A throttle that
    breaks must never cost us the nudge, so every failure path returns True.
    """
    try:
        os.makedirs(os.path.dirname(stamp), mode=0o700, exist_ok=True)
        fd = os.open(stamp, os.O_RDWR | os.O_CREAT, 0o600)
    except Exception:
        return True
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            pass                      # no flock: the mtime check still helps
        now = time.time()
        try:
            last = float(os.read(fd, 64).decode("utf-8", "replace").strip() or 0)
        except Exception:
            last = 0.0
        if 0 < now - last < min_gap:
            return False
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(now).encode("ascii"))
        return True
    except Exception:
        return True
    finally:
        try:
            os.close(fd)              # releases the flock
        except Exception:
            pass
