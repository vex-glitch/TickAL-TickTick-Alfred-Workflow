"""🚗 Commute tasks that belong to a CRM booking (Vex 2026-09-26).

"You know CRM and adding a session/tattoo? What I need is commute added
automatically. Hour and a half before and an hour after whatever duration
is set. Find current commute tasks in TickTick, somewhere in calendar
scheduling list, and make them after those. Use same tags so my calendar
is nicely color scheduled."

THE SHAPE (read live from the 📅Calendar scheduling list, 2026-09-26):
plain title "Commute", a timed span (startDate → dueDate, never all-day),
priority 0, no reminders, kind TEXT, tagged 2️⃣personal (the September 22
batch; the ones before wore ⬜️greytag - one config value switches it).
A CRM booking gets TWO of them:

    [start - before] → [start]        🚗 to the session      (default 90 min)
    [end]            → [end + after]  🚗 from the session    (default 60 min)

"whatever duration is set" = the booking's own span. A booking with a
time but no duration is a POINT: there is no end to leave from, so only
the 'to' leg is made (a from-leg would sit inside the session) and the
toast says so; the from-leg arrives when the duration does. An all-day
or undated booking has no time to commute to: nothing is made, and any
legs it still has are removed.

OWNERSHIP rides the CONTENT, never the title: each commute's description
holds a link to its booking, "🚗 to [🎨 Marko • Sleeve S2](…/tasks/<tid>)".
The title stays the bare "Commute" the calendar and the periodics ignore
rule already know (periodic_engine drops "Commute" from the summaries by
exact first word). The link is the find-key for every later road:

  * create   (dispatch create:, a CRM booking tag)   → add the legs
  * reschedule (attr_date / attr_span on a booking)  → MOVE the linked
    legs to the new span; a booking with no legs yet (scheduled dormant,
    crmsched) gets them made; a booking moved to a date WITHOUT a time
    loses them
  * unschedule (attr_cleardate), 🚫 cancelled, 🗑 delete entry, ⌘ Delete
    (delete_action, attr_delete) → the OPEN linked legs go to TickTick
    Trash. A completed commute is a commute that happened - no road
    touches it.
  * done (✅ Session done - Happened AND 👻 No-show, he travelled either
    way; the 📕 backlog's "complete it too"; a plain ⇧ complete on a
    booking row, dispatch complete:) → the OPEN linked legs are TICKED
    OFF with the session (Vex 2026-10-09: "when I mark session as done,
    commute that was added for that session is ticked off as well").
    Only the legs within a day of the booking (`near`), each on its own;
    a leg he ticked in the app is not in the live pool, so it is never
    ticked twice.
  * 🚗 Sync commutes (the manual row under CRM > 📅 Calendar, `sweep`) →
    every upcoming open booking gets its legs, strays (legs whose
    booking is gone, undated or off the calendar) are removed. The road
    for anything changed inside the TickTick app, and for the bookings
    that existed before this feature. Manual by rule (no background
    automation, Vex 2026-09-21).

THE POOL IS READ LIVE (review 2026-09-26): the commute list is one GET
(`live_pool`, open tasks only, rows stamped as this run's reads so a move
posts without a second read). The hourly cache lied two ways - a wiped
or partial cache made a reschedule mint a second pair, and a leg Vex
ticked in the app still read open, so a cancel could trash a commute
that happened. When the live read fails, nothing is moved or removed and
the toast says `not checked`; only a brand-new booking (create, duplicate)
still gets its legs from the cache view, because nothing can exist for
it yet.

A hand-made commute (no booking link in its content) already sitting on
the computed start minute is honoured, not doubled. Another booking's leg
is never adopted (two bookings 90 minutes apart share a minute). A leg
that a 📑 Duplicate or the app copied elsewhere keeps its link, so every
match prefers the candidate nearest the booking's previous span and every
removal is guarded to legs within a day of the booking (`near`).

Every road is best-effort: the booking write already happened, a commute
failure only costs the commute and the toast says which. Writes obey the
no-stale rule (CLAUDE.md iron rule 12): a MOVE goes through
api.update_task on a row this run read live; creates and deletes carry no
body. A move always says isAllDay False - update_task would otherwise
GUESS from the stamp, and a leg edge on local midnight guessed all-day.

Config (config.json; list, tags and title follow the okr_list_id rule - a
default while the key is ABSENT, present-but-blank = OFF, NO Configure-
panel field; the minute counts read 0 as 0 and blank as the default):
  commute_list_id     6a9d214c8f08ea0ec9b69e35   📅Calendar scheduling
  commute_tags        2️⃣personal                  (list, or a space/comma string)
  commute_before_min  90
  commute_after_min   60
  commute_title       Commute
"""
import os
import re
from datetime import datetime, timedelta, timezone

import config as cfg

COMMUTE_LIST_DEFAULT = "6a9d214c8f08ea0ec9b69e35"    # 📅Calendar scheduling
COMMUTE_TAGS_DEFAULT = ["2️⃣personal"]
COMMUTE_BEFORE_DEFAULT = 90
COMMUTE_AFTER_DEFAULT = 60
COMMUTE_TITLE_DEFAULT = "Commute"

ISO_OUT = "%Y-%m-%dT%H:%M:%S+0000"     # the format every TickAL date write uses
NEAR_HOURS = 24                        # a booking's legs live within a day of it
LINK_TID_RE = re.compile(r"/tasks/([^/)\s]+)\)")
LEG_LINE_RE = re.compile(r"^\s*🚗\s+(to|from)\b", re.M)


# ── config ───────────────────────────────────────────────────────────────────
def list_id():
    return cfg._defaulted("commute_list_id", COMMUTE_LIST_DEFAULT)


def tags():
    """The commute's tags. A list in config.json, or a space/comma string
    (env vars are strings). Lowercased: TickTick stores tag NAMES lower."""
    raw = cfg._defaulted("commute_tags", COMMUTE_TAGS_DEFAULT)
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw.strip()) if t]
    return [str(t).lower() for t in (raw or [])]


def _setting(key, default):
    """env-present-wins, then config.json (a PRESENT value wins even when
    it is 0 - unlike cfg._defaulted, which reads a falsy value as OFF),
    then the default."""
    if key in os.environ:
        return os.environ[key]
    c = cfg.load()
    if key in c:
        return c[key]
    return default


def _minutes(key, default):
    raw = _setting(key, default)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def before_min():
    return _minutes("commute_before_min", COMMUTE_BEFORE_DEFAULT)


def after_min():
    return _minutes("commute_after_min", COMMUTE_AFTER_DEFAULT)


def title():
    t = cfg._defaulted("commute_title", COMMUTE_TITLE_DEFAULT)
    return (str(t).strip() if t else "") or COMMUTE_TITLE_DEFAULT


def enabled():
    """OFF when the list id is blanked in config.json / env, or when both
    leg lengths are 0 (nothing to make)."""
    return bool(list_id()) and (before_min() > 0 or after_min() > 0)


# ── time math (pure) ─────────────────────────────────────────────────────────
def parse_iso(s):
    """Aware datetime from any TickTick/TickAL stamp: '2026-09-23T09:00:00+0000',
    '…09:00:00.000+0000', '…+01:00', or a bare date. None when unreadable."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M%z"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return None


def fmt_iso(dt):
    return dt.astimezone(timezone.utc).strftime(ISO_OUT)


def _utc_midnight(iso):
    dt = parse_iso(iso)
    return bool(dt) and dt.astimezone(timezone.utc).strftime("%H:%M:%S") == "00:00:00"


def time_state(task_or_payload):
    """'timed' | 'all-day' | 'undated'. The create payload sets no isAllDay,
    so a lone stamp is judged by api._is_all_day (UTC or LOCAL midnight)
    on its normalised form; a real span (start and due differ, not both
    midnight) is timed."""
    t = task_or_payload or {}
    start, due = t.get("startDate"), t.get("dueDate")
    if not start and not due:
        return "undated"
    if t.get("isAllDay") is True:
        return "all-day"
    if start and due and start != due:
        return "all-day" if (_utc_midnight(start) and _utc_midnight(due)) else "timed"
    dt = parse_iso(due or start)
    if dt is None:
        return "undated"
    try:
        from api import _is_all_day
        return "all-day" if _is_all_day(fmt_iso(dt)) else "timed"
    except Exception:
        return "all-day" if _utc_midnight(due or start) else "timed"


def is_all_day(task_or_payload):
    """A booking with no clock time (all-day or undated)."""
    return time_state(task_or_payload) != "timed"


def is_point(start_iso, due_iso):
    """A booking with a time but no duration (one stamp, or start == due)."""
    s, e = parse_iso(start_iso), parse_iso(due_iso)
    if s is None and e is None:
        return False
    return s is None or e is None or e <= s


def windows(start_iso, due_iso, before=None, after=None):
    """[(leg, start_iso, end_iso), …] for a booking span - 'to' before it,
    'from' after it. A POINT has no end to leave from: only the 'to' leg.
    A zero length drops that leg. [] when there is no readable time."""
    before = before_min() if before is None else before
    after = after_min() if after is None else after
    s, e = parse_iso(start_iso), parse_iso(due_iso)
    if s is None and e is None:
        return []
    if s is None:
        s = e
    point = e is None or e <= s
    out = []
    if before > 0:
        out.append(("to", fmt_iso(s - timedelta(minutes=before)), fmt_iso(s)))
    if after > 0 and not point:
        out.append(("from", fmt_iso(e), fmt_iso(e + timedelta(minutes=after))))
    return out


def _same_minute(a, b):
    da, db = parse_iso(a), parse_iso(b)
    return bool(da and db) and da.astimezone(timezone.utc).replace(second=0, microsecond=0) \
        == db.astimezone(timezone.utc).replace(second=0, microsecond=0)


def near(task, ref, hours=NEAR_HOURS):
    """True when the task's start lies within `hours` of the reference span
    (a task dict with startDate/dueDate, or a (start, due) pair). A ref
    without dates guards nothing (True)."""
    if isinstance(ref, dict):
        rs, rd = ref.get("startDate"), ref.get("dueDate")
    else:
        rs, rd = (tuple(ref) + (None, None))[:2] if ref else (None, None)
    a, b = parse_iso(rs or rd), parse_iso(rd or rs)
    if a is None and b is None:
        return True
    a = a or b
    b = b or a
    if b < a:
        a, b = b, a
    t = parse_iso((task or {}).get("startDate") or (task or {}).get("dueDate"))
    if t is None:
        return False
    pad = timedelta(hours=hours)
    return a - pad <= t <= b + pad


# ── the link that ties a commute to its booking ─────────────────────────────
def booking_link(pid, tid, booking_title):
    """'[🎨 Marko • Sleeve S2 - 400](https://ticktick.com/webapp/#p/<pid>/tasks/<tid>)'.
    The booking title is itself a link (the records link) - flattened to
    its label so the markdown cannot nest."""
    import mdtext
    label = mdtext.link_text(booking_title or "", limit=80) or "session"
    return mdtext.md_link(label, f"https://ticktick.com/webapp/#p/{pid}/tasks/{tid}")


def leg_content(leg, pid, tid, booking_title):
    word = "to" if leg == "to" else "from"
    return f"🚗 {word} {booking_link(pid, tid, booking_title)}"


def links_booking(task, booking_tid):
    """True when this task's content carries the booking's task link."""
    return f"/tasks/{booking_tid})" in str((task or {}).get("content") or "")


def booking_tid_of(task):
    """The booking id a commute's content links, or ''."""
    m = LINK_TID_RE.search(str((task or {}).get("content") or ""))
    return m.group(1) if m else ""


def leg_of(task):
    """'to' | 'from' | '' from the commute's content."""
    m = LEG_LINE_RE.search(str((task or {}).get("content") or ""))
    return m.group(1) if m else ""


def is_commute(task):
    t = task or {}
    if str(t.get("_projectId") or t.get("projectId") or "") != list_id():
        return False
    return (str(t.get("title") or "").strip().lower()
            == title().strip().lower())


def _open(t):
    return (t.get("status") or 0) == 0


def linked(pool, booking_tid, open_only=True):
    """Commutes in the pool that link this booking."""
    out = []
    for t in pool or []:
        if not is_commute(t) or not links_booking(t, booking_tid):
            continue
        if open_only and not _open(t):
            continue
        out.append(t)
    return out


def hand_made_at(pool, start_iso):
    """An OPEN commute in the list sitting on exactly this start minute
    that links NO booking (Vex's own hand-adds until now) - honoured
    instead of doubled. Another booking's leg is never adopted."""
    for t in pool or []:
        if (is_commute(t) and _open(t) and not booking_tid_of(t)
                and _same_minute(t.get("startDate") or t.get("dueDate"), start_iso)):
            return t
    return None


def plan(booking, pool, prev=None, before=None, after=None):
    """What to do for this booking, pure. Returns a dict:
      make:   [(leg, start, end)]           legs with no task yet
      move:   [(task, leg, start, end)]     linked legs whose span differs
      keep:   [(task, leg)]                 linked or hand-made, already right
      stale:  [task]                        linked legs to remove (the booking
                                            has no time now, or lost its end)
      reason: '' | 'all-day' | 'undated'    why nothing is made
      point:  True when the booking has no duration (to-leg only)
    Linked legs are matched to windows by the to/from word in their
    content; when several carry the same word the one nearest the
    booking's PREVIOUS span (`prev`, the row before a reschedule) wins,
    so a copied leg elsewhere is left alone."""
    b = booking or {}
    tid = b.get("id") or ""
    out = {"make": [], "move": [], "keep": [], "stale": [], "reason": "",
           "point": False}
    mine = linked(pool, tid)
    state = time_state(b)
    if state != "timed":
        out["reason"] = state
        out["stale"] = list(mine)
        return out
    wins = windows(b.get("startDate"), b.get("dueDate"), before, after)
    if not wins:
        out["reason"] = "undated"
        out["stale"] = list(mine)
        return out
    out["point"] = is_point(b.get("startDate"), b.get("dueDate"))
    ref_src = prev if (prev or {}).get("startDate") or (prev or {}).get("dueDate") else b
    ref = parse_iso(ref_src.get("startDate") or ref_src.get("dueDate"))

    def dist(t):
        d = parse_iso(t.get("startDate") or t.get("dueDate"))
        return abs((d - ref).total_seconds()) if (d and ref) else 1e12

    by_leg = {}
    for t in mine:
        by_leg.setdefault(leg_of(t), []).append(t)
    for k in by_leg:
        by_leg[k].sort(key=dist)
    for leg, s, e in wins:
        cands = by_leg.get(leg) or by_leg.get("") or []
        if cands:
            t = cands.pop(0)
            if _same_minute(t.get("startDate"), s) and _same_minute(t.get("dueDate"), e):
                out["keep"].append((t, leg))
            else:
                out["move"].append((t, leg, s, e))
            continue
        hand = hand_made_at(pool, s)
        if hand is not None:
            out["keep"].append((hand, leg))
            continue
        out["make"].append((leg, s, e))
    # A booking that LOST its end (span → point) leaves a from-leg with
    # nothing to leave from: the nearest one within a day goes.
    if out["point"]:
        for t in by_leg.get("from") or []:
            if near(t, ref_src):
                out["stale"].append(t)
                break
    return out


# ── the pool ─────────────────────────────────────────────────────────────────
def live_pool(api):
    """The commute list read LIVE: open tasks only, every row stamped as
    this run's read (api.get_project_data), so a move needs no second GET.
    Raises when the read fails - the caller decides what that means."""
    d = api.get_project_data(list_id())
    out = []
    for t in (d or {}).get("tasks") or []:
        t = dict(t)
        t.setdefault("projectId", list_id())
        out.append(t)
    return out


def cached_pool():
    import cache as cache_store
    return cache_store.get("all_tasks") or []


def _cache_add(made):
    try:
        import dispatch
        dispatch._cache_new_tasks(made)
    except Exception:
        pass


def _cache_patch(tid, **fields):
    try:
        import dispatch
        dispatch._patch_task_cache(tid, **fields)
    except Exception:
        pass


def _cache_drop(tid, pid):
    try:
        import cache as cache_store
        for key in ("all_tasks", "all_notes"):
            rows = cache_store.get(key)
            if rows:
                cache_store.set(key, [t for t in rows if t.get("id") != tid])
        import dispatch
        dispatch._patch_project_data(tid, pid_old=pid, remove=True)
    except Exception:
        pass


def _hm(iso):
    dt = parse_iso(iso)
    return dt.astimezone().strftime("%H:%M") if dt else ""


def _delete(api, legs):
    """(n_deleted, n_failed) - each leg on its own, caches patched."""
    n = failed = 0
    for t in legs:
        t_pid = t.get("_projectId") or t.get("projectId") or list_id()
        try:
            api.delete_task(t_pid, t["id"])
        except Exception:
            failed += 1
            continue
        _cache_drop(t["id"], t_pid)
        n += 1
    return n, failed


NOT_CHECKED = "🚗 commutes not checked · list read failed"


# ── writers (best-effort, each leg on its own) ──────────────────────────────
def sync(api, booking, pool=None, prev=None, fresh_booking=False,
         before=None, after=None):
    """Make the booking's commutes match its span: create the missing legs,
    move the linked ones, remove the ones with nothing left to serve,
    leave the right ones alone. Returns (summary, made, moved, removed) -
    summary is the toast line ('' when nothing to say).

    `pool` = the commute list; None reads it live. A failed live read
    checks nothing and says so, unless `fresh_booking` (create, duplicate:
    no leg can exist for it yet) - then the cache view stands in."""
    if not enabled():
        return "", [], [], 0
    b = booking or {}
    pid, tid = b.get("projectId") or b.get("_projectId") or "", b.get("id") or ""
    if not tid:
        return "", [], [], 0
    if pool is None:
        try:
            pool = live_pool(api)
        except Exception:
            if not fresh_booking:
                return NOT_CHECKED, [], [], 0
            pool = cached_pool()
    p = plan(b, pool, prev, before, after)
    bits = []
    removed = failed = 0
    if p["stale"]:
        removed, failed = _delete(api, p["stale"])
    if p["reason"]:
        why = "undated booking" if p["reason"] == "undated" else "all-day booking"
        if removed:
            bits.append(f"🚗 Commute ×{removed} removed · {why}")
        elif not failed:
            bits.append(f"🚗 no commute · {why}")
        if failed:
            bits.append(f"🚗 {failed} commute{'s' if failed > 1 else ''} not removed")
        return "\n".join(bits), [], [], removed
    made, moved = [], []
    lid, ttl, tg = list_id(), title(), tags()
    for leg, s, e in p["make"]:
        try:
            r = api.create_task(title=ttl, project_id=lid, start_date=s,
                                due_date=e, tags=tg or None,
                                content=leg_content(leg, pid, tid, b.get("title")))
        except Exception:
            failed += 1
            continue
        if r and r.get("id"):
            made.append(r)
        else:
            failed += 1
    for t, leg, s, e in p["move"]:
        t_pid = t.get("_projectId") or t.get("projectId") or lid
        try:
            api.update_task(t["id"], t_pid, current=t, startDate=s, dueDate=e,
                            isAllDay=False)
        except Exception:
            failed += 1
            continue
        _cache_patch(t["id"], startDate=s, dueDate=e, isAllDay=False)
        moved.append((t, s, e))
    if made:
        _cache_add(made)
    if made:
        spans = " · ".join(f"{_hm(m.get('startDate'))} → {_hm(m.get('dueDate'))}"
                           for m in made)
        bits.append(f"🚗 Commute ×{len(made)} added · {spans}"
                    + (" · to only, no duration" if p["point"] else ""))
    if moved:
        spans = " · ".join(f"{_hm(s)} → {_hm(e)}" for _t, s, e in moved)
        bits.append(f"🚗 Commute ×{len(moved)} moved · {spans}")
    if removed:
        bits.append(f"🚗 Commute ×{removed} removed · no end to leave from")
    if not made and not moved and not removed and p["keep"]:
        bits.append("🚗 Commute already there"
                    + (" · to only, no duration" if p["point"] else ""))
    if failed:
        bits.append(f"🚗 {failed} commute{'s' if failed > 1 else ''} failed")
    return "\n".join(bits), made, moved, removed


def drop(api, booking_tid, pool=None, ref=None):
    """The booking is gone or off the calendar: its OPEN linked commutes go
    to TickTick Trash. `ref` (the booking row or its (start, due)) guards
    the removal to legs within a day of it, so a copied leg on another day
    is left alone. Returns (summary, n_dropped)."""
    if not enabled() or not booking_tid:
        return "", 0
    if pool is None:
        try:
            pool = live_pool(api)
        except Exception:
            return NOT_CHECKED, 0
    legs = linked(pool, booking_tid)
    if ref is not None:
        legs = [t for t in legs if near(t, ref)]
    n, failed = _delete(api, legs)
    bits = []
    if n:
        bits.append(f"🚗 Commute ×{n} removed")
    if failed:
        bits.append(f"🚗 {failed} commute{'s' if failed > 1 else ''} not removed")
    return " · ".join(bits), n


def _cache_done(t, pid):
    """A ticked leg leaves the open pools and joins the local completed log
    (dispatch.record_completed, the mirror every completion road keeps), so
    the calendar screens drop it at once."""
    try:
        import dispatch
        snap = dict(t)
        snap["status"] = 2
        snap["completedTime"] = datetime.now(timezone.utc).strftime(ISO_OUT)
        dispatch.record_completed(snap)
    except Exception:
        pass
    _cache_drop(t["id"], pid)


def done(api, booking_tid, pool=None, ref=None):
    """The booking happened (✅ Session done, a ⇧ complete on the booking):
    its OPEN linked commutes are ticked off too - he travelled, the legs
    happened (Vex 2026-10-09). `ref` (the booking row or its (start, due))
    guards the tick to legs within a day of it, like drop. Each leg on its
    own, best-effort; a failed live read ticks nothing and says so. Returns
    (summary, n_ticked)."""
    if not enabled() or not booking_tid:
        return "", 0
    if pool is None:
        try:
            pool = live_pool(api)
        except Exception:
            return NOT_CHECKED, 0
    legs = linked(pool, booking_tid)
    if ref is not None:
        legs = [t for t in legs if near(t, ref)]
    n = failed = 0
    for t in legs:
        t_pid = t.get("_projectId") or t.get("projectId") or list_id()
        try:
            api.complete_task(t_pid, t["id"])
        except Exception:
            failed += 1
            continue
        _cache_done(t, t_pid)
        n += 1
    bits = []
    if n:
        bits.append(f"🚗 Commute ×{n} ticked")
    if failed:
        bits.append(f"🚗 {failed} commute{'s' if failed > 1 else ''} not ticked")
    return " · ".join(bits), n


def is_booking(task_or_payload):
    """A CRM-calendar task wearing a booking tag (consultation / tattoo) -
    the same gate the Prepare chain uses, WITHOUT its S2+ exclusion: every
    session needs its commute."""
    import areas
    t = task_or_payload or {}
    pid = str(t.get("projectId") or t.get("_projectId") or "")
    if not areas.CRM_ID or pid != areas.CRM_ID:
        return False
    tl = {str(x).lower() for x in (t.get("tags") or [])}
    return bool(tl & areas.BOOKING_TAGS)


def sweep(api, now=None):
    """🚗 Sync commutes - the manual road. Reads the CRM list and the
    commute list live ONCE each, then: every open booking still ahead
    (or undated) is synced against the pool; every open leg ahead whose
    booking is no longer open in the CRM list is a stray and goes. Past
    legs and past bookings are never touched. Returns the toast line."""
    import areas
    if not enabled():
        return "🚗 Commutes are off (commute_list_id blank)"
    if not areas.CRM_ID:
        return "🚗 No CRM list configured"
    now = now or datetime.now(timezone.utc)
    pool = live_pool(api)
    crm = api.get_project_data(areas.CRM_ID) or {}
    bookings = []
    for t in crm.get("tasks") or []:
        t = dict(t)
        t.setdefault("projectId", areas.CRM_ID)
        if _open(t) and is_booking(t):
            bookings.append(t)
    open_ids = {b["id"] for b in bookings}
    added = moved = removed = fine = failed = 0
    for b in bookings:
        end = parse_iso(b.get("dueDate") or b.get("startDate"))
        if time_state(b) == "timed" and end and end < now:
            continue                                   # happened, or happening
        line, made, mv, rm = sync(api, b, pool=pool)
        if line == NOT_CHECKED:
            failed += 1
            continue
        for m in made:
            m = dict(m)
            m.setdefault("projectId", list_id())
            pool.append(m)
        added += len(made)
        moved += len(mv)
        removed += rm
        if not made and not mv and not rm:
            fine += 1
        if "failed" in line or "not removed" in line:
            failed += 1
    strays = []
    for t in pool:
        if not (is_commute(t) and _open(t)):
            continue
        btid = booking_tid_of(t)
        if not btid or btid in open_ids:
            continue
        start = parse_iso(t.get("startDate") or t.get("dueDate"))
        if start and start >= now:
            strays.append(t)
    n, f = _delete(api, strays)
    removed += n
    failed += f
    parts = []
    if added:
        parts.append(f"{added} added")
    if moved:
        parts.append(f"{moved} moved")
    if removed:
        parts.append(f"{removed} removed")
    if fine:
        parts.append(f"{fine} booking{'s' if fine != 1 else ''} fine")
    if failed:
        parts.append(f"{failed} failed")
    return "🚗 Sync · " + (" · ".join(parts) if parts else "nothing ahead")
