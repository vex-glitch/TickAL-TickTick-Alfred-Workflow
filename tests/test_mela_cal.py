#!/usr/bin/env python3
"""Unit suite for src/mela_cal.py (Mela's plan in Apple Calendar's store) -
NO real store: a throwaway sqlite with the Calendar + CalendarItem tables
carrying the REAL column names, events in three calendars (two named
"Mela", one "Inbox"), a hidden one, a cancelled one, a phantom master,
timed vs all-day, start_tz 'Europe/London' vs NULL, a non-mela url and
Mela's own "…/note" tail. The snapshot machinery runs on that file: reuse
by mtimes, TTL expiry, pruning, a torn copy, and chmod 000 for the
PermissionError → MelaCalError(Full Disk Access) road.

    python3 tests/test_mela_cal.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import mela_cal  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


# ── the store: the live schema's subset, real column names ──────────────────
SCHEMA = """
CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, store_id INTEGER, title TEXT,
  flags INTEGER, color TEXT, type TEXT, UUID TEXT, external_id TEXT);
CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT, description TEXT,
  start_date REAL, start_tz TEXT, end_date REAL, end_tz TEXT, all_day INTEGER,
  calendar_id INTEGER, orig_item_id INTEGER, orig_date REAL, status INTEGER,
  url TEXT, hidden INTEGER, has_recurrences INTEGER, unique_identifier TEXT,
  UUID TEXT, entity_type INTEGER, phantom_master INTEGER, last_modified REAL,
  creation_date REAL);
"""
CALENDARS = [(28, 5, "Inbox"), (48, 8, "Mela"), (49, 8, "Mela")]
E = mela_cal.APPLE_EPOCH


def apple(iso_utc):
    """'2026-09-27T06:00' (UTC) -> seconds since the Apple epoch."""
    dt = datetime.fromisoformat(iso_utc).replace(tzinfo=timezone.utc)
    return dt.timestamp() - E


CAL_ID = "35B15451-185E-4B53-8D5E-BC376BFB43BB"
U_POCKETS = "F3F9B0BC-E4FD-4CE0-A463-608A5603C218"
U_WRAPS = "B8FA5751-1A14-47D5-AA70-5111B73371EC"
U_BAGELS = "843526B2-7788-4FD6-8FA0-A40740435241"
U_DUMPL = "800F4A5D-CDC0-4C3B-A645-3F7859D7D474"
U_LOWER = "d9411dd7-dde4-47cf-9bae-785c2267b1e7"
U_GHOST = "0B8EFD26-3C6B-428F-A749-48A0830FD05E"


def murl(event_id, uuid):
    return f"mela://calendar/{CAL_ID}:{event_id}/{uuid}"


# (ROWID, summary, start_date, start_tz, all_day, calendar_id, status, url, hidden, phantom)
ITEMS = [
    # the live plan: Sundays at 08:00 Berlin (06:00 UTC), iCloud "Inbox"
    (1, "Bacon And Egg Cheese Hot Pockets", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 28, 1,
     murl("EV-POCKETS", U_POCKETS), 0, 0),
    (2, "Breakfast Crunchwraps", apple("2026-10-04T06:00"), "Europe/Berlin", 0, 28, 1,
     murl("EV-WRAPS", U_WRAPS), 0, 0),
    # 23:30 UTC on the 27th = 00:30 BST on the 28th: the LOCAL date is the 28th
    (3, "Cottage Cheese Wrap", apple("2026-09-27T23:30"), "Europe/London", 0, 28, 1,
     murl("EV-LONDON", U_LOWER), 0, 0),
    # NULL start_tz: the machine's zone; 12:00 UTC lands on the same date in any zone
    (4, "Blanket Dumplings", apple("2026-09-22T12:00"), None, 0, 49, 0,
     murl("EV-DUMPL", U_DUMPL), 0, 0),
    # all-day: midnight UTC, "_float" (the store's convention)
    (5, "Breakfast Bagels - Instagram", apple("2026-09-22T00:00"), "_float", 1, 48, 0,
     murl("EV-ALLDAY", U_BAGELS), 0, 0),
    # same day, timed, other "Mela" calendar: sorts after the all-day one
    (6, "Breakfast Bagels - Instagram", apple("2026-09-22T06:00"), "Europe/Berlin", 0, 48, 0,
     murl("EV-BAGELS-2", U_BAGELS), 0, 0),
    # skipped: hidden (Apple's soft delete)
    (7, "Hidden Pockets", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 28, 1,
     murl("EV-HIDDEN", U_GHOST), 1, 0),
    # skipped: cancelled (EKEventStatusCanceled = 3)
    (8, "Cancelled Pockets", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 28,
     mela_cal.STATUS_CANCELLED, murl("EV-CANCELLED", U_GHOST), 0, 0),
    # skipped: phantom master of a recurrence set
    (9, "Phantom Pockets", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 28, 1,
     murl("EV-PHANTOM", U_GHOST), 0, 1),
    # skipped: not a Mela url
    (10, "Dentist", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 28, 1,
     "https://example.com/booking", 0, 0),
    # skipped: Mela's "…/note" tail is not a recipe
    (11, "test", apple("2026-09-27T06:00"), "Europe/Berlin", 0, 49, 0,
     f"mela://calendar/{CAL_ID}:EV-NOTE/note", 0, 0),
    # skipped: no start_date
    (12, "Undated", None, "Europe/Berlin", 0, 28, 1, murl("EV-UNDATED", U_GHOST), 0, 0),
    # phantom_master NULL (49 rows in the live store) is NOT a phantom
    (13, "Pizza Baguettes", apple("2026-10-25T07:00"), "Europe/Berlin", 0, 28, 1,
     murl("EV-PIZZA", "9C5ADA81-FFA3-4EF6-8A46-631BEC1EBE6D"), 0, None),
]


def build_store(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO Calendar (ROWID, store_id, title) VALUES (?,?,?)", CALENDARS)
    con.executemany("INSERT INTO CalendarItem (ROWID, summary, start_date, start_tz, all_day, "
                    "calendar_id, status, url, hidden, phantom_master, entity_type) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,2)", ITEMS)
    con.execute("UPDATE CalendarItem SET creation_date = start_date")   # newest plan = latest day
    con.commit()
    con.close()


# ── parse_url ───────────────────────────────────────────────────────────────
real = ("mela://calendar/35B15451-185E-4B53-8D5E-BC376BFB43BB:"
        "4E38030F-9343-4841-A23C-DAEFBAA19843/F3F9B0BC-E4FD-4CE0-A463-608A5603C218")
check("parse_url splits the real shape",
      mela_cal.parse_url(real) == ("35B15451-185E-4B53-8D5E-BC376BFB43BB",
                                   "4E38030F-9343-4841-A23C-DAEFBAA19843", U_POCKETS),
      mela_cal.parse_url(real))
check("parse_url upper-cases the recipe id",
      mela_cal.parse_url(murl("x", U_LOWER))[2] == U_LOWER.upper())
check("parse_url survives whitespace and a trailing slash",
      mela_cal.parse_url(f"  {real}/ \n")[2] == U_POCKETS)
check("parse_url refuses a non-mela url", mela_cal.parse_url("https://example.com/x") is None)
check("parse_url refuses mela://recipe/ (a title link, not a plan)",
      mela_cal.parse_url(f"mela://recipe/{U_POCKETS}") is None)
check("parse_url refuses the …/note tail",
      mela_cal.parse_url(f"mela://calendar/{CAL_ID}:EV/note") is None)
check("parse_url refuses a short id",
      mela_cal.parse_url(f"mela://calendar/{CAL_ID}:EV/F3F9B0BC") is None)
check("parse_url on None / empty", mela_cal.parse_url(None) is None
      and mela_cal.parse_url("") is None)

# ── _when: the date arithmetic ──────────────────────────────────────────────
d, s = mela_cal._when(apple("2026-09-27T23:30"), "Europe/London", False)
check("a London event at 23:30 UTC is the 28th locally",
      d == date(2026, 9, 28) and s.hour == 0 and s.minute == 30 and s.tzinfo is not None, (d, s))
d, s = mela_cal._when(apple("2026-09-27T06:00"), "Europe/Berlin", False)
check("a Berlin event at 06:00 UTC is 08:00 on the 27th",
      d == date(2026, 9, 27) and (s.hour, s.minute) == (8, 0), (d, s))
d, s = mela_cal._when(apple("2026-09-22T00:00"), "_float", True)
check("an all-day row is its UTC date, start None", d == date(2026, 9, 22) and s is None, (d, s))
d, s = mela_cal._when(apple("2026-09-22T12:00"), None, False)
machine = datetime(2026, 9, 22, 12, tzinfo=timezone.utc).astimezone().utcoffset()
check("NULL start_tz falls back to the machine's zone",
      d == date(2026, 9, 22) and s is not None and s.tzinfo is not None
      and s.utcoffset() == machine, (d, s))
d, s = mela_cal._when(apple("2026-09-22T12:00"), "Mars/Olympus_Mons", False)
check("an unknown zone name falls back too", d == date(2026, 9, 22) and s is not None, (d, s))
check("junk start_date is None", mela_cal._when(None, "Europe/Berlin", False) is None
      and mela_cal._when("soon", None, False) is None)

# ── plan() over the throwaway store ─────────────────────────────────────────
TMP = tempfile.mkdtemp(prefix="test_mela_cal-")
SAVED = (mela_cal.STORE_PATH, mela_cal.SNAP_DIR, mela_cal._RETRY_S)
try:
    store_dir = os.path.join(TMP, "group.com.apple.calendar")
    os.makedirs(store_dir)
    store = os.path.join(store_dir, "Calendar.sqlitedb")
    build_store(store)

    rows = mela_cal.plan(path=store)
    check("plan() keeps exactly the readable Mela rows", len(rows) == 7,
          [(r.date.isoformat(), r.title) for r in rows])
    titles = [r.title for r in rows]
    check("hidden, cancelled, phantom, non-mela, note, undated rows are gone",
          not any(t in titles for t in ("Hidden Pockets", "Cancelled Pockets",
                                         "Phantom Pockets", "Dentist", "test", "Undated")),
          titles)
    check("sorted by (date, all-day first, start, title)",
          [(r.date.isoformat(), r.all_day, r.title) for r in rows] == [
              ("2026-09-22", True, "Breakfast Bagels - Instagram"),
              ("2026-09-22", False, "Breakfast Bagels - Instagram"),
              ("2026-09-22", False, "Blanket Dumplings"),
              ("2026-09-27", False, "Bacon And Egg Cheese Hot Pockets"),
              ("2026-09-28", False, "Cottage Cheese Wrap"),
              ("2026-10-04", False, "Breakfast Crunchwraps"),
              ("2026-10-25", False, "Pizza Baguettes")],
          [(r.date.isoformat(), r.all_day, r.title) for r in rows])
    by_ev = {r.event_id: r for r in rows}
    p = by_ev["EV-POCKETS"]
    check("a Planned row carries the local date, an aware start, uuid, calendar, url",
          p.date == date(2026, 9, 27) and p.start.hour == 8 and p.start.tzinfo is not None
          and not p.all_day and p.uuid == U_POCKETS and p.calendar == "Inbox"
          and p.url == murl("EV-POCKETS", U_POCKETS) and p.recipe_url == f"mela://recipe/{U_POCKETS}",
          p)
    check("the London event lands on the 28th", by_ev["EV-LONDON"].date == date(2026, 9, 28))
    check("a lower-case uuid in the url is UPPERCASE on the row",
          by_ev["EV-LONDON"].uuid == U_LOWER.upper(), by_ev["EV-LONDON"].uuid)
    check("all-day: date only, start None, all_day True",
          by_ev["EV-ALLDAY"].all_day and by_ev["EV-ALLDAY"].start is None
          and by_ev["EV-ALLDAY"].date == date(2026, 9, 22))
    check("every calendar is read, never by name",
          {r.calendar for r in rows} == {"Inbox", "Mela"}
          and by_ev["EV-DUMPL"].calendar == "Mela" and by_ev["EV-ALLDAY"].calendar == "Mela")
    check("phantom_master NULL is not a phantom", "EV-PIZZA" in by_ev)
    check("status 0 (none) and 1 (confirmed) both count as planned",
          "EV-DUMPL" in by_ev and "EV-POCKETS" in by_ev)

    win = mela_cal.plan(since=date(2026, 9, 27), until=date(2026, 10, 4), path=store)
    check("since/until are inclusive local-date bounds",
          [r.event_id for r in win] == ["EV-POCKETS", "EV-LONDON", "EV-WRAPS"],
          [r.event_id for r in win])
    check("since alone", [r.event_id for r in mela_cal.plan(since=date(2026, 10, 4), path=store)]
          == ["EV-WRAPS", "EV-PIZZA"])
    check("until alone", len(mela_cal.plan(until=date(2026, 9, 22), path=store)) == 3)
    check("an empty window is an empty list",
          mela_cal.plan(since=date(2027, 1, 1), until=date(2027, 1, 7), path=store) == [])

    # a store without the tables: a schema change, worded for a toast
    bare = os.path.join(TMP, "bare.sqlitedb")
    sqlite3.connect(bare).close()
    try:
        mela_cal.plan(path=bare)
        check("a store without the tables raises", False, "no error")
    except mela_cal.MelaCalError as e:
        check("a store without the tables raises MelaCalError", "unreadable" in str(e), str(e))

    # ── the snapshot machinery on the throwaway file ────────────────────────
    mela_cal.STORE_PATH = store
    mela_cal.SNAP_DIR = os.path.join(TMP, "snap")
    mela_cal._RETRY_S = 0
    check("store_present sees the file", mela_cal.store_present())
    p1 = mela_cal.snapshot(now=1000.0)
    check("the first call copies into SNAP_DIR/<now>-<pid>",
          os.path.isfile(p1) and os.path.dirname(p1)
          == os.path.join(mela_cal.SNAP_DIR, f"1000-{os.getpid()}"), p1)
    check("SNAP_DIR is 0700", (os.stat(mela_cal.SNAP_DIR).st_mode & 0o777) == 0o700)
    check("stamp.json is written", os.path.isfile(os.path.join(mela_cal.SNAP_DIR, "stamp.json")))
    check("the copy reads as the plan", len(mela_cal.plan(path=p1)) == 7)
    p2 = mela_cal.snapshot(now=1030.0)
    check("a second call within the TTL reuses the copy", p2 == p1, (p1, p2))
    st = os.stat(store)
    os.utime(store, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    p3 = mela_cal.snapshot(now=1040.0)
    check("a touched source forces a new copy", p3 != p1 and os.path.isfile(p3), (p1, p3))
    p4 = mela_cal.snapshot(now=1040.0 + mela_cal.SNAP_TTL + 1)
    check("an expired copy is replaced", p4 != p3 and os.path.isfile(p4), (p3, p4))
    old = os.path.join(mela_cal.SNAP_DIR, "1-1")
    os.makedirs(old)
    p5 = mela_cal.snapshot(now=5000.0)
    check("old sibling copies are pruned, the fresh one kept",
          not os.path.exists(old) and os.path.isfile(p5) and not os.path.exists(p1), (old, p5))
    check("stamp records the copy", mela_cal._read_stamp()["dir"] == os.path.dirname(p5))

    # -wal / -shm travel with the main file
    with open(store + "-wal", "wb") as f:
        f.write(b"")
    with open(store + "-shm", "wb") as f:
        f.write(b"")
    p6 = mela_cal.snapshot(now=6000.0)
    check("the -wal and -shm are copied beside the store",
          os.path.isfile(p6 + "-wal") and os.path.isfile(p6 + "-shm"), os.listdir(os.path.dirname(p6)))
    os.remove(store + "-wal")
    os.remove(store + "-shm")

    live = mela_cal.plan()               # real clock: a fresh copy, then reused
    check("plan() without a path snapshots end to end", len(live) == 7)
    fr = mela_cal.freshness()
    check("freshness reports present, age and count",
          fr["present"] and isinstance(fr["age_s"], float) and fr["count"] == 7
          and fr["error"] == "", fr)

    # the Full Disk Access road: an unreadable store is PermissionError → one toast line
    st = os.stat(store)                  # chmod moves ctime only: touch mtime too, or a
    os.chmod(store, 0)                   # still-fresh copy is (rightly) reused untouched
    os.utime(store, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    try:
        try:
            mela_cal.snapshot(now=7000.0)
            check("an unreadable store raises", False, "no error")
        except mela_cal.MelaCalError as e:
            check("PermissionError becomes the Full Disk Access toast",
                  "Full Disk Access" in str(e) and "System Settings" in str(e), str(e))
        fr = mela_cal.freshness()
        check("freshness carries the same line, count None",
              fr["present"] and fr["count"] is None and "Full Disk Access" in fr["error"], fr)
    finally:
        os.chmod(store, 0o644)

    # a torn copy: not a database at all
    with open(store, "wb") as f:
        f.write(b"not a database at all")
    try:
        mela_cal.snapshot(now=9000.0)
        check("a torn copy raises", False, "no error")
    except mela_cal.MelaCalError as e:
        check("a torn copy raises MelaCalError after one retry", "unreadable" in str(e), str(e))

    mela_cal.STORE_PATH = os.path.join(TMP, "nowhere", "Calendar.sqlitedb")
    check("store_present is False when missing", not mela_cal.store_present())
    try:
        mela_cal.snapshot()
        check("a missing store raises", False, "no error")
    except mela_cal.MelaCalError as e:
        check("a missing store names the path", mela_cal.STORE_PATH in str(e), str(e))
    fr = mela_cal.freshness()
    check("freshness without a store",
          fr["present"] is False and fr["age_s"] is None and fr["count"] is None
          and "not found" in fr["error"], fr)
finally:
    mela_cal.STORE_PATH, mela_cal.SNAP_DIR, mela_cal._RETRY_S = SAVED
    shutil.rmtree(TMP, ignore_errors=True)


# ── which calendar (Vex 2026-09-21: two stale local "Mela" calendars) ─────────
print("-- calendars")
store2 = os.path.join(tempfile.mkdtemp(prefix="test_mela_cal2-"), "cal2.sqlitedb")   # TMP is locked by the FDA check above
build_store(store2)
rec = mela_cal.calendars_by_recency(path=store2)
check("calendars_by_recency: the calendar Mela wrote to last comes first, names deduped",
      rec[:1] == ["Inbox"] and rec.count("Mela") == 1, rec)
check("choose_calendars: a preference wins", mela_cal.choose_calendars(["Mela"], path=store2) == ["Mela"])
check("choose_calendars: blank preference = the most recent one only", mela_cal.choose_calendars([], path=store2) == ["Inbox"])
check("choose_calendars: '  ' entries are ignored", mela_cal.choose_calendars(["  "], path=store2) == ["Inbox"])
all_rows = mela_cal.plan(path=store2)
inbox = mela_cal.plan(path=store2, calendars=["Inbox"])
check("plan(calendars=) keeps only those calendars",
      inbox and all(p.calendar == "Inbox" for p in inbox) and len(inbox) < len(all_rows), (len(inbox), len(all_rows)))
check("plan(calendars=[]) is empty, plan(calendars=None) is everything",
      mela_cal.plan(path=store2, calendars=[]) == [] and len(mela_cal.plan(path=store2, calendars=None)) == len(all_rows))

print(f"\nmela_cal: {COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":
    sys.exit(1 if FAILS else 0)
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
