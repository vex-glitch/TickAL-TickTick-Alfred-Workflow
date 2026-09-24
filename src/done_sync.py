"""done_sync.py - the daily note catches up after a completion TickAL made.

Vex 2026-09-23: "Daily tasks checkboxes in notes are not synced with actual
tasks completions". The ticks followed TickTick only when a refresh happened
to run, so every completion road we own now asks for one: the ⇧ chord and
the Finish link (dispatch complete:), the focus bar's ● and ○, the buffer,
and every xact verb that completes through _complete_cache_patch.

A completion rarely comes alone - a routine ticks a dozen steps in a row, a
CRM session done completes a whole tree in a loop - so the request is a
TRAILING debounce: the catch-up runs once, DELAY seconds after the LAST
completion, and never while they are still coming. One job at a time: a
request while a job is waiting only moves its deadline; the job heartbeats
its slot while it waits, so a job that died frees it after JOB_TTL.

The state is one small JSON file under an exclusive flock:
    {"ts": <last request>, "job": <heartbeat of the waiting job, 0 = none>}

Pure-ish: stdlib + script_base.run_path. The spawn and the sleep are
injected, so the tests drive both sides without a process or a clock.
"""
import contextlib
import json
import os
import time

DELAY = 20.0       # quiet seconds after the last completion before the refresh
JOB_TTL = 120.0    # a waiting job's heartbeat older than this = the job is gone

_PATH = None


def _path():
    global _PATH
    if _PATH is None:
        from script_base import run_path
        _PATH = run_path("tickal_pn_donesync.json")
    return _PATH


@contextlib.contextmanager
def _state(path=None):
    """The state dict under an exclusive lock; what the block leaves in it is
    written back. An unreadable file reads as empty - a broken stamp must
    never cost a completion its catch-up."""
    path = path or _path()
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        # an unopenable state file (a directory in its place, mode 000, a
        # full disk): the catch-up must still happen, so the state reads
        # as empty and nothing is written back (review 2026-09-24)
        yield {}
        return
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            pass
        raw = b""
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            raw += chunk
        try:
            st = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(st, dict):
                st = {}
        except ValueError:
            st = {}
        yield st
        data = json.dumps(st).encode("utf-8")
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, data)
        except OSError:
            pass                        # a failed write-back is a lost stamp, not a lost catch-up
    finally:
        os.close(fd)


def request(spawn, now=None, path=None):
    """A completion happened. Moves the deadline, and calls spawn() to start
    the catch-up job unless one is already waiting. -> True when it spawned.
    spawn() must return something truthy when a job actually STARTED: the
    slot is stamped only then, so a spawn that yields no process (a Popen
    that failed, swallowed upstream) cannot hold it for JOB_TTL and cost
    every completion in that window its catch-up (review 2026-09-24).
    Never raises: the completion it follows already happened."""
    try:
        spawned = False
        with _state(path) as st:
            now = time.time() if now is None else now
            st["ts"] = now
            beat = float(st.get("job") or 0)
            waiting = bool(beat) and 0 <= now - beat < JOB_TTL
            if not waiting:
                spawned = bool(spawn())
                st["job"] = now if spawned else 0
        return spawned
    except Exception:
        return False


def wait_quiet(sleep=time.sleep, clock=time.time, path=None):
    """The job's side: sleep until DELAY has passed since the LAST request,
    then free the slot and return True - the caller runs the catch-up. A
    request that lands after the slot is freed spawns the next job, so no
    completion is ever left without one. False on a broken state file (the
    job then runs anyway: better one refresh too many than a missed tick)."""
    try:
        while True:
            with _state(path) as st:
                now = clock()
                ts = float(st.get("ts") or 0)
                if ts > now:
                    # the clock stepped back since the request: re-anchor,
                    # or the job idles for the whole skew while every new
                    # completion is refused a job (review 2026-09-24)
                    st["ts"] = ts = now
                wait = ts + DELAY - now
                if wait <= 0:
                    st["job"] = 0
                    return True
                st["job"] = now                  # heartbeat: still waiting
            sleep(min(wait, DELAY))
    except Exception:
        return False
