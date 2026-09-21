"""mela_cal.py - Mela's meal plan, read from a COPY of Apple Calendar's store.

WHY: "I will be scheduling in Mela, it is nicer" (Vex, 2026-09-21). Mela
keeps NO plan in its own database: "Add to Calendar…" (⌘⌥A) writes an
Apple Calendar event whose url is

    mela://calendar/<calendarId>:<eventId>/<RECIPE-UUID>

and the last path segment IS the recipe id, the same one the
mela://recipe/<UUID> links in TickTick titles carry. So the plan is the set
of calendar events with that url prefix, and this module lists them as
Planned rows (local date, recipe uuid, event summary) for the screens and
the one manual sync. Nothing here ever writes to the calendar.

The store is ~/Library/Group Containers/group.com.apple.calendar/
Calendar.sqlitedb with -wal / -shm beside it, held open by calaccessd, so
the live file is NEVER opened: the three are copied into a snapshot dir
first (the src/mela.py shape: reused while the sources' mtimes are
unchanged, quick_check'ed, older copies pruned). EVERY calendar is read and
the rows are filtered on the url prefix - the calendar's NAME is never
assumed (Vex's live plan sits in the iCloud "Inbox" calendar; two local
calendars named "Mela" hold test events).

Dates: CalendarItem.start_date is seconds since 2001-01-01 UTC
(APPLE_EPOCH). A timed event is placed in its start_tz (zoneinfo), or the
machine's zone when the column is NULL or unknown. An all-day event is
stored as midnight UTC with start_tz "_float": its UTC date is the date,
and Planned.start is None.

Skipped rows: hidden = 1 (Apple's soft delete), phantom_master = 1 (the
detached master of a recurrence set, not an occurrence), and cancelled
events. STATUS: the column follows EventKit's EKEventStatus - 0 none,
1 confirmed, 2 tentative, 3 CANCELLED (STATUS_CANCELLED). Vex's store
holds only 0 and 1 today (2026-09-21).

Full Disk Access: the store is TCC protected. The CLI reads it; Alfred must
be granted Full Disk Access or every read fails with PermissionError, which
becomes MelaCalError(FDA_TEXT), one line worded for a toast.

    python3 src/mela_cal.py            # lists the plan, read only
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date as _date, datetime, timezone
from typing import List, Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                    # macOS 3.9 ships zoneinfo too; belt and braces
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

STORE_PATH = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb")
SNAP_DIR = os.path.expanduser("~/.ticktick_alfred/run/melacal")   # 0700, on demand
SNAP_TTL = 600                         # seconds an unchanged copy is reused
PRUNE_AFTER = 600                      # older sibling copies are removed
APPLE_EPOCH = 978307200                # 2001-01-01 UTC as a unix timestamp
URL_PREFIX = "mela://calendar/"
URL_RE = re.compile(r"^mela://calendar/([^:/]+):([^/]+)/([0-9A-Fa-f-]{36})/?$")
STATUS_CANCELLED = 3                   # EKEventStatusCanceled (see docstring)
FDA_TEXT = ("Calendar store unreadable · give Alfred Full Disk Access "
            "(System Settings › Privacy › Full Disk Access)")

_RETRY_S = 0.5                                 # pause before the one re-copy
_SNAP_NAME_RE = re.compile(r"^(\d+)-\d+")      # <int(now)>-<pid>[-n]


class MelaCalError(RuntimeError):
    """One line, worded for a notification toast: what happened · what to do."""


@dataclass
class Planned:
    date: _date                        # LOCAL date the meal is planned on
    start: Optional[datetime]          # aware, in the event's zone; None all-day
    all_day: bool
    uuid: str                          # recipe id, UPPERCASE
    title: str                         # the event's summary
    calendar: str                      # the calendar's title ("" when unknown)
    event_id: str                      # <eventId> from the url
    url: str

    @property
    def recipe_url(self):
        return f"mela://recipe/{self.uuid}"


# ── pure ────────────────────────────────────────────────────────────────────
def parse_url(url):
    """(calendar_id, event_id, RECIPE-UUID) from a mela://calendar/ url, or
    None for anything else - including Mela's own "…/note" tail, which is
    not a recipe."""
    m = URL_RE.match((url or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3).upper()


def _zone(name):
    """The event's zone, or the machine's when NULL / "_float" / unknown."""
    if name and name != "_float" and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return None                        # fromtimestamp(..., tz=None) = local


def _when(start_date, start_tz, all_day):
    """(local date, aware start or None) for a row; None for junk."""
    try:
        ts = float(start_date) + APPLE_EPOCH
    except (TypeError, ValueError):
        return None
    try:
        if all_day:                    # midnight UTC, floating: the UTC date IS the date
            return datetime.fromtimestamp(ts, tz=timezone.utc).date(), None
        zone = _zone(start_tz)
        start = datetime.fromtimestamp(ts, tz=zone)
        if zone is None:               # stamp the machine's zone on it
            start = start.astimezone()
        return start.date(), start
    except (OverflowError, OSError, ValueError):
        return None


def _sort_key(p):
    return (p.date, 0 if p.all_day else 1,
            p.start.timestamp() if p.start else 0.0, (p.title or "").casefold())


# ── the snapshot: calaccessd holds the live file, so read a copy ────────────
def store_present():
    """True when the store exists - ALSO when it exists but TCC forbids the
    stat (PermissionError): that is the Full Disk Access case, and
    snapshot() is the one to say so."""
    try:
        os.stat(STORE_PATH)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _sources():
    """(live path, basename) for the main file and the -wal / -shm beside
    it - only those that exist. The three travel together or the copy is torn."""
    out = []
    for suffix in ("", "-wal", "-shm"):
        src = STORE_PATH + suffix
        if os.path.exists(src):
            out.append((src, os.path.basename(STORE_PATH) + suffix))
    return out


def _mtimes(sources):
    return {name: os.stat(src).st_mtime_ns for src, name in sources}


def _stamp_path():
    return os.path.join(SNAP_DIR, "stamp.json")


def _read_stamp():
    try:
        with open(_stamp_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_stamp(stamp):
    tmp = _stamp_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamp, f)
    os.replace(tmp, _stamp_path())


def _verify(path):
    """Raise sqlite3.DatabaseError unless the copy opens and checks clean."""
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
    finally:
        con.close()
    if not row or row[0] != "ok":
        raise sqlite3.DatabaseError(row[0] if row else "quick_check: no result")


def _copy_into(dest, sources):
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, 0o700)
    for src, name in sources:
        shutil.copy2(src, os.path.join(dest, name))


def _prune(keep, now):
    """Remove sibling copies older than PRUNE_AFTER - never the one in use."""
    try:
        names = os.listdir(SNAP_DIR)
    except OSError:
        return
    for name in names:
        m = _SNAP_NAME_RE.match(name)
        path = os.path.join(SNAP_DIR, name)
        if not m or path == keep or not os.path.isdir(path):
            continue
        if now - int(m.group(1)) > PRUNE_AFTER:
            shutil.rmtree(path, ignore_errors=True)


def snapshot(max_age=SNAP_TTL, now=None):
    """Path of a readable copy of the store. A copy younger than `max_age`
    whose sources have not changed is reused; otherwise the files are
    copied into their own SNAP_DIR/<int(now)>-<pid>/ and checked. A torn
    copy (calaccessd mid-write) is copied once more after a short pause.
    PermissionError anywhere on the live files is the Full Disk Access
    case and raises MelaCalError(FDA_TEXT)."""
    if not store_present():
        raise MelaCalError(f"Calendar store not found at {STORE_PATH} · "
                           "Apple Calendar never run on this Mac?")
    now = time.time() if now is None else now
    try:
        sources = _sources()
        mtimes = _mtimes(sources)
    except PermissionError as e:
        raise MelaCalError(FDA_TEXT) from e
    if not sources:                    # exists() lied under TCC: same case
        raise MelaCalError(FDA_TEXT)
    base = os.path.basename(STORE_PATH)
    os.makedirs(SNAP_DIR, 0o700, exist_ok=True)
    stamp = _read_stamp()
    if stamp and stamp.get("db") == STORE_PATH and stamp.get("src") == mtimes:
        copy = os.path.join(str(stamp.get("dir") or ""), base)
        age = now - float(stamp.get("copied_at") or 0)
        if 0 <= age < max_age and os.path.isfile(copy):
            return copy
    dest = os.path.join(SNAP_DIR, f"{int(now)}-{os.getpid()}")
    n = 1
    while os.path.exists(dest):        # same second, same pid: stay fresh
        n += 1
        dest = os.path.join(SNAP_DIR, f"{int(now)}-{os.getpid()}-{n}")
    copy = os.path.join(dest, base)
    for attempt in (1, 2):
        try:
            _copy_into(dest, sources)
            _verify(copy)
            break
        except PermissionError as e:
            shutil.rmtree(dest, ignore_errors=True)
            raise MelaCalError(FDA_TEXT) from e
        except (sqlite3.DatabaseError, FileNotFoundError) as e:
            if attempt == 2:
                shutil.rmtree(dest, ignore_errors=True)
                raise MelaCalError("Calendar store copy unreadable (Calendar busy?) "
                                   "· try again") from e
            time.sleep(_RETRY_S)
            try:
                sources = _sources()
                mtimes = _mtimes(sources)
            except PermissionError as e2:
                raise MelaCalError(FDA_TEXT) from e2
    _write_stamp({"db": STORE_PATH, "dir": dest, "copied_at": now, "src": mtimes})
    _prune(dest, now)
    return copy


# ── the reader ──────────────────────────────────────────────────────────────
_SQL = ("SELECT ci.summary, ci.start_date, ci.start_tz, ci.all_day, ci.status, "
        "ci.hidden, ci.phantom_master, ci.url, c.title "
        "FROM CalendarItem ci LEFT JOIN Calendar c ON c.ROWID = ci.calendar_id "
        "WHERE ci.url LIKE ? ORDER BY ci.ROWID")


def plan(since=None, until=None, path=None, now=None, calendars=None) -> List[Planned]:
    """Every planned meal in every calendar: rows whose url starts with
    mela://calendar/, minus hidden, cancelled (status 3) and phantom
    masters, as Planned sorted by (date, start, title). `since` / `until`
    are inclusive LOCAL date bounds. `calendars` (names) keeps only those
    calendars; None = every calendar. `path` reads that copy (tests);
    otherwise a fresh snapshot(now=now)."""
    path = path or snapshot(now=now)
    keep = None if calendars is None else {str(c) for c in calendars}
    out = []
    try:
        con = sqlite3.connect(path)
        try:
            rows = con.execute(_SQL, (URL_PREFIX + "%",)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise MelaCalError(f"Calendar store unreadable ({e}) · schema changed?") from e
    for summary, start_date, start_tz, all_day, status, hidden, phantom, url, cal in rows:
        if hidden or phantom or status == STATUS_CANCELLED:
            continue
        parsed = parse_url(url)
        if not parsed:
            continue
        when = _when(start_date, start_tz, bool(all_day))
        if not when:
            continue
        day, start = when
        if since and day < since:
            continue
        if until and day > until:
            continue
        if keep is not None and (cal or "") not in keep:
            continue
        _cal_id, event_id, uuid = parsed
        out.append(Planned(date=day, start=start, all_day=bool(all_day), uuid=uuid,
                           title=(summary or "").strip(), calendar=cal or "",
                           event_id=event_id, url=url))
    out.sort(key=_sort_key)
    return out


_SQL_RECENT = ("SELECT c.title, MAX(ci.creation_date) FROM CalendarItem ci "
               "LEFT JOIN Calendar c ON c.ROWID = ci.calendar_id "
               "WHERE ci.url LIKE ? AND (ci.hidden IS NULL OR ci.hidden = 0) "
               "GROUP BY ci.calendar_id ORDER BY 2 DESC")


def calendars_by_recency(path=None, now=None):
    """Calendar names holding Mela events, the one Mela wrote to most
    recently first (its current "Add to Calendar" target). Names deduped
    (two local calendars can share a name)."""
    path = path or snapshot(now=now)
    try:
        con = sqlite3.connect(path)
        try:
            rows = con.execute(_SQL_RECENT, (URL_PREFIX + "%",)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise MelaCalError(f"Calendar store unreadable ({e}) · schema changed?") from e
    out = []
    for title, _newest in rows:
        name = (title or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def choose_calendars(pref=None, path=None, now=None):
    """The calendars the plan is read from: `pref` (names from config) when
    given, else the single most recently written one, else [] (no plan)."""
    pref = [str(x).strip() for x in (pref or []) if str(x).strip()]
    if pref:
        return pref
    recent = calendars_by_recency(path=path, now=now)
    return recent[:1]


def _age_s(now=None):
    """Seconds since Calendar last wrote: the newer of the store and -wal."""
    now = time.time() if now is None else now
    try:
        stamps = [os.stat(p).st_mtime for p in (STORE_PATH, STORE_PATH + "-wal")
                  if os.path.exists(p)]
    except OSError:
        return None
    return now - max(stamps) if stamps else None


def freshness(path=None):
    """{present, age_s, count, error} for the hub's status row: whether the
    store is there, how long since Calendar wrote, how many meals are
    planned (None with `error` set when the store cannot be read)."""
    out = {"present": store_present(), "age_s": None, "count": None, "error": ""}
    if not out["present"]:
        out["error"] = f"Calendar store not found at {STORE_PATH}"
        return out
    out["age_s"] = _age_s()
    try:
        out["count"] = len(plan(path=path))
    except MelaCalError as e:
        out["error"] = str(e)
    return out


def main():
    """The plan, read only: one line per planned meal."""
    try:
        rows = plan()
    except MelaCalError as e:
        sys.exit(f"mela_cal: {e}")
    fr = freshness()
    age = fr["age_s"]
    print(f"{len(rows)} planned · store wrote {age:.0f} s ago" if age is not None
          else f"{len(rows)} planned")
    for p in rows:
        when = "all day" if p.all_day else p.start.strftime("%H:%M %Z")
        print(f"  {p.date:%a %d %b %Y}  {when:>10}  {p.title}  ·  {p.uuid}  ·  {p.calendar}")


if __name__ == "__main__":
    main()
