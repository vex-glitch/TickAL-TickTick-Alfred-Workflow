#!/usr/bin/env python3
"""okr_write.py - every TickTick write the 🥅 OKR hub makes (HANDOFF_OKR
phase 2). okr.py plans, this module writes; okr.py stays pure.

Why src/ and not Scripts/xact.py: the hourly agent (src/sync.py) auto-ticks
and keeps the countdowns too, and it cannot import Scripts/. So the xact
verbs (okr_add, okr_addkr, okr_link, okr_tag, okr_carry, okr_upkeep) are
thin wrappers over the functions here, and sync.py calls upkeep() directly. Phase 3 (import) adds add_items (every new Y / O / KR, typed or
linked; add_krs is its KR alias), import_source (what the import screen
previews, pure over the caches) and import_plan - THE answer to "can this
be added, and if not why", which the ⌘ Actions row and the import screen
ask and nothing else. It asks plan_of / _verdict / planned exactly as
add_items asks them of its live read, so the row, the screen and the verb
never disagree, and a screen never offers a ⏎ the verb can only refuse.

NO DATE WRITES (Vex 2026-09-23, scheduling out, then "Heal off"): nothing
here moves an OKR item or a parent's span. The writes left are titles,
tags, new copies, ticks, won't do / someday, and the countdowns.

THE WRITER RULE (okr.py module docstring). The auto-tick and the countdowns
write only from a Snapshot that is .writable: a live read with every
completed KR. A cache read, or one missing completed KRs, reads a ticked
deliverable as deleted. Title, tag and new-KR writes need a LIVE read
(settled names and codes, the O's KRs) but not the completed feed.

THE LOCK (~/.ticktick_alfred/okr.lock). Every writer loads INSIDE it, so no
plan comes from a snapshot another writer has already made stale. User verbs
wait for it (LOCK_WAIT, then refuse "busy" rather than hang); the background
upkeep takes it non-blocking and leaves when it is taken. Full-object
writes clobber whatever changed since the read (a KR ticked in between
would be posted back open), so load -> write stays inside one hold. The
upkeep's ticks come from a SECOND hold (its done lookups run between the
two), so each candidate is re-read inside that hold and ticked only while
still open: two overlapping passes tick a KR once.

WRITES: one v2 batch per 50 items (the road the app itself writes on), and
v1 one full object each when there is no v2 token or a batch is refused.
The values are absolute titles / tags on full objects, so a v1 retry after
a half-applied batch lands the same.

CACHE: patch_cache() mirrors every write into all_tasks, all_notes, the
list's project_data_<pid> (the browse screens read that) and the hub's own
okr_rows snapshot ({"list_id", "name", "done_complete", "detail", "rows":
[raw tasks]}), in one pass. okr_rows is REBUILT from the writer's own live
read, never patched: an older copy re-stamped by a patch would pass the
hub's freshness test and show a plan the app has moved on from. It never
invalidates all_tasks: the next keystroke would refetch every list live
against the 300-per-5-min budget (map trap 10).

okr_complete ({"list_id", "ts", "rows"}) is the last COMPLETE read, kept
apart from okr_rows (the LAST read, complete or not): written only from a
live read with every completed KR (remember_complete; patch_cache with the
writes over it), it is how a later read that comes back without completed
KRs still knows which closed items exist (plan_of).

NO SYNC CLICK HERE. Every road a verb runs on ends at ET End, which already
clicks File > Sync; a second click inside the same breath is the double
click that wedged TickTick's sync on 2026-09-12. The detached upkeep banners
through the same End (xact _crm_say), and the hourly sync's headless banner
does too.
"""
import fcntl
import json
import os
import re
import subprocess
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import cache as cache_store
import config as cfg
import mdtext
import okr
import periodic_model as pm

LOCK_FILE = os.path.join(cfg.CONFIG_DIR, "okr.lock")
UPKEEP_STAMP = os.path.join(cfg.CONFIG_DIR, "okr_heal.stamp")   # the file predates the rename
UPKEEP_LOG = "/tmp/tickal_okr.log"
LOCK_WAIT = 90.0          # seconds a user verb waits out a running upkeep
BATCH = 50                # v2 batch/task bodies per request
ROWS_KEY = "okr_rows"     # the hub's cached snapshot (browse ctx:okr)
COMPLETE_KEY = "okr_complete"   # the last COMPLETE read (remember_complete)
AREA_ROOT = "0️⃣area"


class Refusal(Exception):
    """A write that was NOT made, worded for the toast. The xact wrapper
    prints it once - left to escape, main()'s catch-all would print AND
    banner it (two notices, map trap 17). `reopen` is a ctx to land on
    INSTEAD of the payload's back: "Already in the plan" takes Vex to the
    item that already plans it, because the screen he came from has nothing
    left to offer."""

    def __init__(self, msg="", reopen=None):
        super().__init__(msg)
        self.reopen = reopen


# What a writer that CHOOSES where Vex lands returns: the toast, the ctx to
# reopen (None = the payload's back) and the ids it made. add_items needs it -
# a new Y/O goes on to its tag picker, not back to where the add started.
Outcome = namedtuple("Outcome", "msg reopen ids")


# ── plumbing ─────────────────────────────────────────────────────────────────
@contextmanager
def _lock(wait=None):
    """Hold the OKR write lock; yields True when held, False when another
    writer kept it past `wait` seconds (0 = one non-blocking try, the
    background upkeep). A lock file that cannot even be opened yields True:
    a broken lock must not block every write (app_sync.claim fails open
    the same way)."""
    wait = LOCK_WAIT if wait is None else wait
    try:
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        fd = open(LOCK_FILE, "a")
    except OSError:
        yield True
        return
    got = False
    try:
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
        yield got
    finally:
        try:
            if got:
                fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass


def _clients(api=None, v2=None):
    """(v1 client, v2 client or None). Built once per verb so the read, the
    writes and the done lookups share them."""
    if api is None:
        from api import TickTickAPI
        api = TickTickAPI(cfg.get_token())
    if v2 is None:
        try:
            from api_v2 import TickTickV2
            v2 = TickTickV2()
        except Exception:
            v2 = None
    return api, v2


def _has_token(v2):
    return v2 is not None and bool(getattr(v2, "token", None))


def _load(api, v2, writable):
    """The live snapshot a writer may use, else Refusal. writable=True is
    the writer rule (spans, ticks); False needs a live read only."""
    pid = cfg.get_okr_list_id()
    if not pid:
        raise Refusal("🥅 OKRs are off · ⚙️ Settings → OKR List")
    try:
        snap = okr.load(api=api, v2=v2, list_id=pid)
    except okr.OkrLoadError as e:
        raise Refusal(RATE_LIMITED if _rate_limited(str(e)) else f"🥅 Not written · {e}")
    remember_complete(snap)
    if snap.source != "live" or (writable and not snap.writable):
        raise Refusal(_why_not(snap, v2))
    return snap


# api.RateLimitError (300 requests / 5 min, answered as HTTP 500) is the v1
# client's: okr.load names the class in its detail when v1 failed ("live
# read failed (RateLimitError: ...)", the cache answering) or in its
# OkrLoadError when no cache could, and waiting is the whole cure - so the
# toast says to wait, never "unreachable" or a bare "try again": a retry
# inside the window deepens the lockout. v2 never gets here:
# api_v2.project_completed never raises, a v2 limit answers None, which
# reads "completed KRs unreadable".
RATE_LIMITED = "🥅 Not written · TickTick rate limit · try again in a minute"


def _rate_limited(text):
    return "RateLimitError" in (text or "")


def _why_not(snap, v2):
    """Why a read cannot feed this writer, worded like wontdo's toast: a
    rate limit says so first (v1's, the only read that raises one), a
    cache read never can, a live one only with every completed KR."""
    if _rate_limited(snap.detail):
        return RATE_LIMITED
    if snap.source != "live":
        return "🥅 Not written · TickTick unreachable, only the cache answered"
    if "TRUNCATED" in (snap.detail or ""):
        return "🥅 Not written · too many completed KRs to read them all"
    if not _has_token(v2):
        return ("🥅 Not written · completed KRs need the Attachment Login "
                "token (⚙️ Settings)")
    return "🥅 Not written · completed KRs unreadable right now · try again"


def _pd_key(pid):
    """dispatch._pd_key (the inbox is cached under the literal 'inbox')."""
    return ("project_data_inbox" if str(pid).startswith("inbox")
            else f"project_data_{pid}")


def _norm_tags(tags):
    """dispatch._norm_tags: deduped, lowercase (TickTick lowercases names)."""
    return list(dict.fromkeys(str(t).lower() for t in (tags or []) if t))


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


# ── the cache mirror ─────────────────────────────────────────────────────────
def _complete_of(list_id):
    """okr_complete when it is this list's and well formed, else None."""
    try:
        c = cache_store.get(COMPLETE_KEY)
    except Exception:
        return None
    if not (isinstance(c, dict) and list_id and c.get("list_id") == list_id
            and isinstance(c.get("rows"), list)):
        return None
    c["rows"] = [t for t in c["rows"] if isinstance(t, dict) and t.get("id")]
    return c


def _set_complete(list_id, rows):
    cache_store.set(COMPLETE_KEY, {"list_id": list_id, "ts": int(time.time()),
                                   "rows": [dict(t) for t in rows
                                            if isinstance(t, dict) and t.get("id")]})


def remember_complete(snap):
    """Keep a COMPLETE read as okr_complete ({"list_id", "ts", "rows":
    every raw row of that read}): the dedupe's memory of which closed items
    exist, for the reads that come back without them (plan_of). Written
    only from a live read with every completed KR (done_complete) - a
    partial read is never remembered as whole. Called by every writer's
    _load, by patch_cache (with the writes over it), by upkeep, and
    by browse._okr_snapshot after its own live read. -> True when kept.
    Never raises."""
    try:
        if not (snap is not None and snap.source == "live" and snap.done_complete
                and snap.list_id):
            return False
        _set_complete(snap.list_id, [i.raw for i in snap.items])
        return True
    except Exception:
        return False


def patch_cache(snap, patches=None, done=(), add=(), rebuild=True):
    """Mirror OKR writes into every cache a screen reads, one pass:

      patches  {id: fields} merged into each cached copy of the task
      done     ids completed: out of the OPEN pools (all_tasks, all_notes,
               project_data_<pid>), status 2 in okr_rows (the hub reads
               completed KRs too, for progress), and onto the front of
               completed_tasks - the dispatch complete: mirror
      add      new raw tasks (the caller restates parentId: the v1 create
               response says null, map trap 12), appended everywhere

    okr_rows is REBUILT from `snap` - the live read the caller wrote from,
    loaded inside the lock - with the writes over it, in the shape
    browse._okr_snapshot keeps ({"list_id", "name", "done_complete",
    "rows"}) plus the read's "detail" (import_plan words a blocked answer
    from it). An older okr_rows copy is never patched: the hub kept it
    minutes ago, the app may have moved things since, and patched and
    re-stamped it would pass browse._okr_fresh as the new plan. rebuild=False
    drops okr_rows instead - for a caller whose snap may be OLDER than a
    copy another writer left (the upkeep's second hold). Written LAST: the
    hub trusts okr_rows only while its mtime is not older than
    project_data / all_tasks / completed_tasks.

    okr_complete follows a COMPLETE snap: rebuilt from it with okr_rows
    (before it: okr_rows stays the last write); with rebuild=False only
    this write's ticks go into the copy that is there, when it is this
    list's. A snap missing completed KRs never touches it.

    The written rows are folded back into snap.items (what TickTick now
    holds), so a second mirror in the same hold builds on the first
    (add_krs: the O's 🏷️ line, then its KRs).
    Never raises. A failure drops okr_rows only - never all_tasks (map
    trap 10): the hub re-reads live on its next empty bar."""
    patches = {k: v for k, v in (patches or {}).items() if k and v}
    gone = {d for d in (done or ()) if d}
    add = [a for a in (add or ()) if isinstance(a, dict) and a.get("id")]
    if not (patches or gone or add):
        return
    try:
        list_id = snap.list_id
        stamp = _stamp()
        pname = next((p.get("name") or "" for p in (cache_store.get("projects") or [])
                      if isinstance(p, dict) and p.get("id") == list_id), "")
        entries = []
        for a in add:
            e = dict(a)
            e["projectId"] = e.get("projectId") or list_id
            e["_projectId"] = list_id
            e["_projectName"] = pname
            e["_columnName"] = e.get("_columnName", "")
            entries.append(e)
        new_ids = {e["id"] for e in entries}
        opened = {}

        def fix(rows, keep_done):
            out = []
            for t in rows:
                if not isinstance(t, dict):
                    out.append(t)
                    continue
                tid = t.get("id")
                if tid in new_ids:
                    continue                  # re-added below: idempotent
                if tid in patches:
                    t = {**t, **patches[tid]}
                if tid in gone:
                    opened.setdefault(tid, t)
                    if not keep_done:
                        continue
                    t = {**t, "status": 2, "completedTime": stamp}
                out.append(t)
            return out

        # the snap first: it is what TickTick holds now, whatever the caches do
        plan_rows = fix([i.raw for i in snap.items], True) + [dict(e) for e in entries]
        snap.items = okr.items_from(plan_rows)
        for key in ("all_tasks", "all_notes"):
            rows = cache_store.get(key)
            if isinstance(rows, list):
                rows = fix(rows, False)
                if key == "all_tasks":
                    rows += [dict(e) for e in entries]
                cache_store.set(key, rows)
        pk = _pd_key(list_id)
        pd = cache_store.get(pk)
        if isinstance(pd, dict) and isinstance(pd.get("tasks"), list):
            pd = dict(pd)
            pd["tasks"] = fix(pd["tasks"], False) + [dict(e) for e in entries]
            cache_store.set(pk, pd)
        if gone and opened:
            feed = [t for t in (cache_store.get("completed_tasks") or [])
                    if isinstance(t, dict) and t.get("id") not in gone]
            fresh = [{**opened[i], "status": 2, "completedTime": stamp}
                     for i in opened]
            cache_store.set("completed_tasks", (fresh + feed)[:200])
        # okr_complete (the last complete read, remember_complete) before
        # okr_rows: from this snap when it is a complete live read and the
        # newest one about (rebuild); else only this write's ticks go into
        # the copy that is there, when it is this list's - never an older
        # read over a newer one
        live_full = snap.source == "live" and snap.done_complete
        if rebuild and live_full:
            _set_complete(list_id, plan_rows)
        elif live_full and gone:
            c = _complete_of(list_id)
            if c is not None:
                c["rows"] = [{**t, "status": 2, "completedTime": stamp}
                             if t.get("id") in gone and t.get("status") == 0 else t
                             for t in c["rows"]]
                cache_store.set(COMPLETE_KEY, c)
        # okr_rows LAST: the hub trusts it only while its mtime is not older
        # than project_data / all_tasks / completed_tasks (browse
        # _okr_fresh), and a mirror must not make the rebuilt copy look stale
        if rebuild and snap.source == "live":
            cache_store.set(ROWS_KEY, {"list_id": list_id, "name": snap.name,
                                       "done_complete": snap.done_complete,
                                       "detail": snap.detail or "",
                                       "rows": plan_rows})
        else:
            cache_store.invalidate(ROWS_KEY)
    except Exception:
        try:
            cache_store.invalidate(ROWS_KEY)
        except Exception:
            pass


# ── the one writer of full objects ───────────────────────────────────────────
def _write(snap, todo, api, v2):
    """[(Item, fields)] -> (written ids, failed ids). Bodies are the item's
    STORED raw with the fields over it. v2 batch first, 50 a request; a
    chunk v2 refuses (or no token at all) goes v1, one object each -
    update_task is TASK id first, list id second (map trap 2), and the
    fields carry isAllDay whenever they carry dates, so v1 never guesses it
    (trap 3)."""
    written, failed = [], []
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        ok = False
        if _has_token(v2):
            try:
                ok = bool(v2.update_tasks([{**(it.raw or {}), **f} for it, f in chunk]))
            except Exception:
                ok = False
        if ok:
            written += [it.id for it, _f in chunk]
            continue
        for it, f in chunk:
            try:
                api.update_task(it.id, it.pid or snap.list_id, current=it.raw, **f)
                written.append(it.id)
            except Exception:
                failed.append(it.id)
    return written, failed


# ── 🔑 KRs under an O from one piped line ────────────────────────────────────
def code_ok(code):
    """A code a KR title reads back: one word, capital or digit first.
    "xy" is not one - the title would end " - xy" and read as part of the
    name - so the verb refuses it; a screen can mark such a row dead with
    this same test."""
    return okr.parse_title(okr.build_title("KR", "x", code=code))[3] == code


def _title_for(kind, name, url=None, code=None):
    """The title of a new item, or None when it would not read back (map
    trap 13). A KR: with no code, a name ending " - USA" reads USA as its
    code, and nothing in a title can escape an all-caps word; a lower-case
    or mixed word ("Call Anna - Monday") is fine - okr.settle_codes folds
    it back into the name. A Y / O carries no suffix at all, and settle
    leaves their titles as parsed, so ANY candidate there ("Trip - USA",
    "Plan - Monday") would cut the name short: refused. A linked name is
    the link's label, where no suffix can hide, so it always reads back."""
    title = okr.build_title(kind, name, link=url, code=code)
    cand = okr.parse_title(title)[3]
    if kind == "KR":
        ok = cand == code or (code is None and not okr._caps(cand or ""))
    else:
        ok = cand is None
    return title if ok else None


def _kr_title(name, code):
    """The text-only KR title (phase 2's name for _title_for("KR", ...))."""
    return _title_for("KR", name, None, code)


def kr_code(o, items, given=None):
    """(code, have): the code a new KR under the 🥅 O `o` is stamped with,
    and the O's own code (None = it has none yet, so the verb writes the
    stamped one as the O's 🏷️ line). `given` wins (the verb has refused it
    already unless code_ok), then the O's own (okr.code_of - its 🏷️ line,
    its title, its KRs' majority; NOT re-checked: a hand-typed one that
    does not read back is code_problem's to word), then okr.propose_code
    over its name when that reads back - a caseless name proposes none,
    and no code beats a lost name. The screens ask this for the code they
    show, the verb for the code it writes."""
    have = okr.code_of(o, okr.krs_of(o, items))
    proposed = okr.propose_code(o.name) or None
    if proposed and not code_ok(proposed):
        proposed = None
    return (given or have or proposed), have


def code_problem(o_name, code):
    """Why KRs stamped with `code` cannot be added under the O `o_name`
    (the O's own code, typed by hand, that a KR title cannot read back),
    else None. The import screen's dead KR row and add_items' skip say
    it in these words."""
    if code is None or code_ok(code):
        return None
    return f"{o_name}'s code '{code}' does not read back · fix its 🏷️ line"


def _live(api, snap, it):
    """The item's live v1 object (the u_append pattern), else its raw."""
    try:
        t = api.get_task(it.pid or snap.list_id, it.id)
        if isinstance(t, dict) and t.get("id"):
            return t
    except Exception:
        pass
    return it.raw


def _stamp_code(api, snap, o, code):
    """Write "🏷️ XY" at the bottom of the O's description, where
    okr.code_of reads it first (HANDOFF section 2: the code lives in the
    O's DESCRIPTION). LIVE GET first - appending to a stale description
    would drop whatever was typed since. -> "" or a toast suffix."""
    try:
        live = _live(api, snap, o)
        old = live.get("content") or ""
        line = okr.code_line(code)
        new = (old.rstrip() + "\n" + line) if old.strip() else line
        api.update_task(o.id, o.pid or snap.list_id, current=live, content=new)
        patch_cache(snap, patches={o.id: {"content": new}})
        return ""
    except Exception:
        return " · 🏷️ not saved"


ORDER_STEP = 2 ** 30      # the gap between synthesized sibling sortOrders


def _typed_orders(made, sibs=()):
    """The sortOrder each new sibling gets, in TYPED order (ascending =
    shown first). The server's own values dealt back out ascending - the
    magnitude TickTick chose, which keeps the block clear of the siblings
    already there (dispatch._order_children). TIED values (the server gave
    two new items the same one, or none at all) cannot be dealt into an
    order, so strictly increasing ones are synthesized ORDER_STEP apart,
    ending at the server's lowest and staying below every existing
    sibling's (`sibs`): the block stays where the server put it, on top."""
    orders = sorted(_order_num(k.get("sortOrder")) for k in made)
    if len(set(orders)) == len(orders):
        return orders
    top = orders[0]
    known = [o for o in (_order_num(s, None) for s in sibs or ()) if o is not None]
    if known:
        top = min(top, min(known) - ORDER_STEP)
    n = len(orders)
    return [top - (n - 1 - i) * ORDER_STEP for i in range(n)]


def _order_num(v, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _settle_kids(api, v2, made, pid, parent_id, tz, sibs=()):
    """The one full-object body each new item gets after its create, posted
    once for all of them:

      order     dispatch._order_children's fix: v1 creates subtasks with
                DESCENDING sortOrder (Milk, Bread shows Bread first), so the
                server's own values are dealt back out ascending in TYPED
                order (two or more items; _typed_orders - TIED values are
                replaced by synthesized ones below the existing siblings,
                `sibs` = their sortOrders)
      timeZone  the parent's (the caller's `tz`): v1 create takes no zone,
                and an item read in another zone than the one its all-day
                dates were written in lands a day off once it is dated
      parentId  restated on every body under a parent (the create response
                says null, and posting it back as null would detach the
                lot). A root Y / O has none: its body carries no parentId
                at all, so nothing is ever posted as "no parent" by accident

    One v2 batch; an item whose body changes nothing (one KR already in the
    zone) is no reason to post. v2 refused or no token: v1, one object
    each, only for the items that need it - the zone is not cosmetic, the
    order is. Updates `made` in place with what landed."""
    orders = _typed_orders(made, sibs) if len(made) >= 2 else []
    todo = []                     # (made item, the fields its body changes)
    for i, k in enumerate(made):
        f = {"parentId": parent_id, "timeZone": tz} if parent_id else {"timeZone": tz}
        if len(made) >= 2:
            f["sortOrder"] = orders[i]
        todo.append((k, f, f.get("sortOrder", k.get("sortOrder")) != k.get("sortOrder")
                     or (k.get("timeZone") or "") != tz))
    if not any(n for _k, _f, n in todo):
        return

    def clean(k):
        return {kk: vv for kk, vv in k.items() if not kk.startswith("_")
                and not (kk == "parentId" and not parent_id)}
    bodies = [{**clean(k), "projectId": k.get("projectId") or pid, **f}
              for k, f, _n in todo]
    ok = False
    if _has_token(v2):
        try:
            ok = bool(v2.update_tasks(bodies))
        except Exception:
            ok = False
    for k, f, n in todo:
        if not ok and n:
            try:
                api.update_task(k["id"], pid, current=clean(k), **f)
            except Exception:
                continue
        k.update(f)


# ── ➕ new Y / O / KR items: typed, piped, or imported with a link ──────────
GLYPH = {"Y": "🏔️", "O": "🥅", "KR": "🔑"}
_KIND_WORD = {"Y": "year objective", "O": "objective", "KR": "KR"}


def _glyph(kind):
    return GLYPH.get(kind, "▫️")


def _names(raw):
    """The names of a payload, spacing collapsed, empty ones dropped (the
    screen split the pipes; "a | | b" leaves an empty segment behind)."""
    if isinstance(raw, str):
        raw = [raw]
    return [" ".join(n.split()) for n in (raw or []) if isinstance(n, str) and n.strip()]


def _link_arg(link):
    """The payload's link -> None | (to, pid, tid). A malformed one is a
    Refusal, never "no link": the row promised a linked copy, and a
    text-only one would be a different item than the one he picked."""
    if link in (None, "", {}):
        return None
    if not isinstance(link, dict):
        raise Refusal("🔗 Nothing to link")
    to = link.get("to")
    pid = str(link.get("pid") or "")
    tid = str(link.get("tid") or "")
    if tid == "-":
        tid = ""
    if to not in ("task", "list") or not pid or (to == "task" and not tid):
        raise Refusal("🔗 Nothing to link")
    return to, pid, (tid if to == "task" else None)


# ── the dedupe: what "already in the plan" means ─────────────────────────────
def _cta_pid():
    """The 📌CTA list (areas.CTA_LIST_ID, the Configure field), read at call
    time so a test or a later Configure change is seen."""
    try:
        import areas
        return getattr(areas, "CTA_LIST_ID", "") or ""
    except Exception:
        return ""


def _cached_rows():
    rows = []
    for key in ("all_tasks", "all_notes"):
        v = cache_store.get(key)
        if isinstance(v, list):
            rows += [t for t in v if isinstance(t, dict)]
    return rows


def _row_pid(t):
    return t.get("projectId") or t.get("_projectId") or ""


def _title_targets(title):
    """Every TickTick task / list a title links ("💼 P • [TickAL](list) 🔗"
    links the list). The app backslash-escapes a saved title's markdown, so
    it is unescaped first (pm.unescape_md, as okr.parse_title does)."""
    out = []
    for m in okr._LINK_RE.finditer(pm.unescape_md(title or "")):
        label = m.group(1)
        tg = okr.link_target(m.group(0)[len(label) + 3:-1].strip())
        if tg and tg[0] in ("task", "list"):
            out.append(tg)
    return out


def _cta_tasks_for(list_id, rows):
    """The cached 📌CTA tasks whose title links list `list_id` - a project's
    CTA ("💼 P • [name](list link) 🔗", areas.build_action)."""
    cta = _cta_pid()
    if not cta or not list_id:
        return []
    return [t for t in rows if _row_pid(t) == cta and t.get("id")
            and ("list", list_id, None) in _title_targets(t.get("title"))]


def _same_keys(to, pid, tid, rows):
    """What counts as the SAME thing: the task (by id - a task keeps its id
    when it moves lists) or the list itself, plus a project's other face.
    A list import links its 📌CTA task when one exists, and an O made
    before the CTA links the list: either way it is one project, and a
    second O for it is exactly the duplicate the dedupe is for. The other
    face is a GOAL's: planned() lets only a Y / O match through it."""
    if to == "task":
        keys = {("task", tid)}
        t = next((r for r in rows if r.get("id") == tid), None)
        if t is not None and _cta_pid() and _row_pid(t) == _cta_pid():
            keys |= {("list", tg[1]) for tg in _title_targets(t.get("title"))
                     if tg[0] == "list"}
        return keys
    return {("list", pid)} | {("task", t["id"]) for t in _cta_tasks_for(pid, rows)}


def _item_key(it):
    tg = it.target
    if not tg:
        return None
    if tg[0] == "task":
        return ("task", tg[2])
    if tg[0] == "list":
        return ("list", tg[1])
    return None


def planned(items, to, pid, tid=None, doubt=()):
    """The plan item (open or CLOSED - a done O still plans that project,
    and a second copy would restart it by accident) that already links this
    task, note or list, else None. Open ones answer first, closed ones
    next, and the ids in `doubt` last (plan_of: rows the last complete read
    held open that the read in hand no longer shows - a hit there is no
    answer, _verdict turns it into a refusal).

    Which hits count: the EXACT thing (the task by its id, the list by its
    id) for any item; the project's other face (a list <-> its 📌CTA task,
    _same_keys) only for a 🏔️ Y / 🥅 O - a goal plans the whole project,
    while a 🔑 KR is one deliverable and plans exactly what it links. A
    LIST import asks with the link it will write - the project's 📌CTA task
    when there is one - so a KR on that CTA task does plan the list, while a
    KR on the bare list does not stop an objective for the project.

    Pure over `items` and the caches (the CTA face of a project); a cache
    that cannot be read narrows it to the exact task / list, never to
    "nothing". Asked ONCE per question, through _verdict: import_plan (the
    ⌘ Actions row and the import screen) and add_items inside its lock,
    each over plan_of - one question, one answer, every place."""
    tid = None if tid in (None, "", "-") else str(tid)
    pid = str(pid or "")
    exact = ("task", tid) if to == "task" else ("list", pid)
    try:
        keys = _same_keys(to, pid, tid, _cached_rows())
    except Exception:
        keys = {exact}
    doubt = set(doubt or ())

    def hit(it):
        k = _item_key(it)
        return k is not None and (k == exact or (k in keys and it.kind in okr.PARENT_KINDS))
    hits = [it for it in items if hit(it)]
    hits.sort(key=lambda it: (it.id in doubt, it.history))
    return hits[0] if hits else None


_CLOSED = (2, -1)                 # done, won't do


def closed_cached(list_id):
    """The CLOSED rows (done, won't do) of the last COMPLETE read
    (okr_complete, remember_complete) of this list, else None (no such
    read: the cache cannot say which closed items exist). Never okr_rows:
    that is the LAST read, complete or not."""
    c = _complete_of(list_id)
    if c is None:
        return None
    return [t for t in c["rows"] if t.get("status") in _CLOSED]


# What the dedupe asks planned() over (plan_of):
#   items  the read in hand, plus the last complete read's rows it lacks
#          when it is missing completed KRs
#   doubt  ids of those added rows that were OPEN then: gone now = closed
#          or deleted, and the two cannot be told apart
#   blind  missing completed KRs with no complete read stored: a "not
#          planned" cannot be told from "not readable"
Plan = namedtuple("Plan", "items doubt blind")


def plan_of(items, list_id, complete):
    """The Plan for a read of the OKR list: `items` its items, `complete`
    whether it holds every completed KR (Snapshot.done_complete). A
    complete read is the whole plan. One missing completed KRs would let a
    DONE O's project be planned a second time, so the last complete read's
    rows it does not hold are added (okr_complete; the read in hand wins on
    any id both hold - a KR reopened since is open): a closed one is known
    closed, an open one is gone since (doubt). No complete read stored =
    blind. Pure over the cache; never raises."""
    items = list(items or ())
    if complete:
        return Plan(items, frozenset(), False)
    c = _complete_of(list_id)
    if c is None:
        return Plan(items, frozenset(), True)
    seen = {i.id for i in items}
    extra = [t for t in c["rows"] if t["id"] not in seen]
    if not extra:
        return Plan(items, frozenset(), False)
    doubt = frozenset(t["id"] for t in extra if t.get("status") not in _CLOSED)
    return Plan(okr.items_from([i.raw for i in items] + extra), doubt, False)


def plan_items(snap):
    """The Plan add_items' dedupe asks over, from its live read."""
    return plan_of(snap.items, snap.list_id, snap.done_complete)


def _verdict(plan, to, pid, tid):
    """(hit, blocked) for one link over a Plan: planned() asked ONCE. A hit
    on a row the plan can vouch for is the answer ("Already in the plan",
    closed ones too). A hit only on a doubt row, or no hit on a blind plan,
    is blocked: the item may exist, closed, and nothing here can say. Else
    (None, False): free to add."""
    hit = planned(plan.items, to, pid, tid, doubt=plan.doubt)
    if hit is not None and hit.id not in plan.doubt:
        return hit, False
    return None, (hit is not None or plan.blind)


# A task that already lives IN the plan list is never copied into it. A
# planning copy (an OKR prefix) is refused as one; an unprefixed item (a
# loose note Vex offloaded there) needs its prefix, not a copy of itself.
IN_PLAN_COPY = "🥅 That is a planning copy · add the original"
IN_PLAN_LOOSE = "🥅 Already in the plan list · give it a 🏔️ / 🥅 / 🔑 prefix"
PLAN_LIST = "🥅 That is the plan list · add the real one"
# A periodic note (or its list) plans nothing: it is a dated page ABOUT the
# work, the task it names is the thing to plan.
PERIODIC = "🥅 Periodic notes stay out · add the task it names"


def _periodic_pid():
    """The 💫 periodic notes list (areas.PERIODIC_LIST_ID), read at call
    time like _cta_pid."""
    try:
        import areas
        return getattr(areas, "PERIODIC_LIST_ID", "") or ""
    except Exception:
        return ""


def _in_plan(it):
    """The refusal for a task of the plan list: `it` is its Item or raw
    row (None = not known, the planning-copy wording)."""
    if it is None:
        return IN_PLAN_COPY
    kind = it.kind if isinstance(it, okr.Item) else okr.from_task(it).kind
    return IN_PLAN_COPY if kind in okr.KINDS else IN_PLAN_LOOSE


def _cached_row(tid):
    try:
        return next((r for r in _cached_rows() if r.get("id") == tid), None)
    except Exception:
        return None


def screen_of(item, items):
    """The screen that SHOWS an item: a Y / O's own screen, a KR's (or a
    loose item's) parent Y / O screen, else the hub root - browse._okr_home
    for the children, the item itself for a parent."""
    if item.kind in okr.PARENT_KINDS:
        return f"ctx:okr:{item.kind.lower()}:{item.id}"
    p = okr.index(items).get(item.parent) if item.parent else None
    return (f"ctx:okr:{p.kind.lower()}:{p.id}"
            if p is not None and p.kind in okr.PARENT_KINDS else "ctx:okr")


# ── import_source: what "🥅 Add to OKRs" copies ──────────────────────────────
# A CTA-style lead "<emoji> P • " ("💼 P • ", "💼P • "): the project CTA's
# own naming, which the planning copy replaces with its level's prefix.
_CTA_LEAD_RE = re.compile(r"^\s*[^\w\s]{1,4}\s*P\s*[•·]\s*")
# Vex's notes lists lead with "N - " / "N • " ("🗒N - Work", live 2026-09-19):
# the list's filing, not its name (the emoji before it is stripped first)
_NOTES_LEAD_RE = re.compile(r"^\s*N\s*[•·\-]\s+")
_CF_RE = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff]")  # zero-width marks
_LINK_TAIL_RE = re.compile(r"\s*\U0001F517️?\s*$")      # a trailing " 🔗"


def _clean_name(text):
    """A source title as a plan item's NAME: markdown unescaped, links
    flattened to their labels, the CTA lead and the trailing 🔗 dropped,
    spacing collapsed. A title that is already a planning copy's (an item
    of the old 💫 OKRs lists) loses its level prefix and an all-caps code:
    the new copy stamps its own, and "🔑 KR • 🔑 KR • x - TA - OT" helps
    no one. A code that is not all caps stays in the name - it may be one
    ("Call Anna - Monday")."""
    t = okr._flatten(pm.unescape_md(_CF_RE.sub("", text or "")))
    t = mdtext.flatten_links(t)
    t = " ".join(t.split())
    t = _CTA_LEAD_RE.sub("", t, count=1)
    t = _LINK_TAIL_RE.sub("", t)
    if okr._PREFIX_RE.match(t):
        _k, name, _l, code = okr.parse_title(t)
        t = name if (code is None or okr._caps(code)) else f"{name}{okr.CODE_SEP}{code}"
    return " ".join(t.split())


_KEYCAP_AT = re.compile("[0-9#*]\ufe0f?\u20e3")     # 1️⃣: digit, VS16?, keycap ring
# what an emoji is made of: symbols (So: pictographs, regional
# indicators; Sk: the skin tones), marks (Mn VS16, Me the keycap's
# enclosing ring) and format characters (Cf: the zero-width joiner of a
# family emoji)
_EMOJI_CATS = ("So", "Sk", "Mn", "Me", "Cf")


def _emoji_part(ch):
    """True for a character an emoji run is made of. Sk counts only past
    ASCII: the skin tones are Sk, and so are the backtick and the caret,
    which start words ("`dev` tools", "^Top") and stay."""
    import unicodedata
    cat = unicodedata.category(ch)
    return cat in _EMOJI_CATS and (cat != "Sk" or ord(ch) > 127)


def _strip_lead_emoji(name):
    """A list name without its leading emoji run ("🌅 Routines" ->
    "Routines", "🏆🎯Goals" -> "Goals", "1️⃣ Work" -> "Work", "⚙️
    Settings" -> "Settings", "👍🏽 Approved" -> "Approved"): a plain list's
    emoji is decoration, and in a planning copy's link label it would sit
    between the level prefix and the name. Words and punctuation stop the
    run ("[Draft] x" keeps its bracket, "`dev` tools" its backtick); a
    name that is ALL emoji keeps itself, a name is better than none."""
    t = (name or "").strip()
    i = 0
    while i < len(t):
        m = _KEYCAP_AT.match(t, i)
        if m:
            i = m.end()
        elif _emoji_part(t[i]) or (i and t[i].isspace()):
            i += 1
        else:
            break
    rest = t[i:].strip()
    return rest if (i and rest) else t


def import_source(kind, pid, tid=None):
    """What the import screen (ctx:okrimport:<kind>:<pid>:<tid>) shows and
    puts in its xact:okr_add payloads, for a task, note or list:

        {"name", "link": {"to", "pid", "tid"}, "kind_hint": "O" | "KR"}

    task / note  name = its title cleaned (_clean_name), link = the task
                 itself, under the list the CACHED task says it is in (it
                 may have moved since the row that opened the screen)
    list         name = the list name ("💼P • Website 4️⃣" -> "Website",
                 areas.clean_project_name; a plain list loses its leading
                 emoji run, "🌅 Routines" -> "Routines" - a task or note
                 title keeps its emoji, it is the title Vex typed); link =
                 the project's 📌CTA TASK
                 when one links the list ("a project CTA should be linked in
                 title" - Vex), else the list itself
    kind_hint    "O" for a list or a 📌CTA task (a goal is mostly a
                 project), else "KR" (a deliverable): the screen leads with
                 those rows

    PURE over the caches (projects, all_tasks, all_notes): a script filter
    render calls it on every keystroke, so it never reads live. Never
    raises: a problem RETURNS a Refusal (isinstance-test it; str() is the
    dead row's title) - OKRs off, the plan list, a task already IN it (a
    planning copy is never copied again; an unprefixed one wants its
    prefix, _in_plan - the verb's wording too), not cached yet, nothing
    left to name it by. Whether it is already planned is planned()'s
    question, against the snapshot."""
    try:
        okr_pid = cfg.get_okr_list_id()
        if not okr_pid:
            return Refusal("🥅 OKRs are off · ⚙️ Settings → OKR List")
        pid = str(pid or "")
        tid = None if tid in (None, "", "-") else str(tid)
        if kind not in ("task", "note", "list"):
            return Refusal("🥅 Nothing to add")
        per = _periodic_pid()
        if kind == "list":
            if not pid:
                return Refusal("🥅 Nothing to add")
            if pid == okr_pid:
                return Refusal(PLAN_LIST)
            if per and pid == per:
                return Refusal(PERIODIC)
            import areas
            p = next((p for p in (cache_store.get("projects") or [])
                      if isinstance(p, dict) and p.get("id") == pid), None)
            if p is None:
                return Refusal("🥅 List not cached yet · sync or reopen")
            raw = p.get("name") or ""
            if areas.is_project(raw):
                name = _clean_name(areas.clean_project_name(raw))
            else:
                name = _NOTES_LEAD_RE.sub("", _strip_lead_emoji(_clean_name(raw)), count=1)
            cta = _cta_tasks_for(pid, _cached_rows())
            link = ({"to": "task", "pid": _cta_pid(), "tid": cta[0]["id"]} if cta
                    else {"to": "list", "pid": pid, "tid": None})
            hint = "O"
        else:
            if not tid:
                return Refusal("🥅 Nothing to add")
            t = next((r for r in _cached_rows() if r.get("id") == tid), None)
            if t is None:
                return Refusal("🥅 Not cached yet · sync or reopen")
            real = _row_pid(t) or pid
            if okr_pid in (real, pid):
                return Refusal(_in_plan(t))
            if per and per in (real, pid):
                return Refusal(PERIODIC)
            name = _clean_name(t.get("title"))
            link = {"to": "task", "pid": real, "tid": tid}
            hint = "O" if _cta_pid() and real == _cta_pid() else "KR"
        if not name:
            return Refusal("🥅 No name to copy · give it a title first")
        return {"name": name, "link": link, "kind_hint": hint}
    except Exception as e:
        return Refusal(f"🥅 Unreadable · {type(e).__name__}")


def _mtime(key):
    try:
        return os.path.getmtime(os.path.join(cache_store.CACHE_DIR, f"{key}.json"))
    except Exception:
        return None


def cached_plan(list_id):
    """The OKR plan's items from the CACHES only, picked the way the hub
    screens pick them (browse._okr_cached): the last live read (okr_rows,
    completed KRs included) while nothing newer has touched the list's
    project_data; else the synced OPEN rows plus every closed one still
    known - okr_rows', the last complete read's (okr_complete), then the
    account-wide completed feed's. Never the network. [] when nothing is
    cached."""
    c = cache_store.get(ROWS_KEY)
    c = c if isinstance(c, dict) and c.get("list_id") == list_id else None
    pk = _pd_key(list_id)
    pd = cache_store.get(pk)
    pd = pd if isinstance(pd, dict) and isinstance(pd.get("tasks"), list) else None
    if c and (pd is None or (_mtime(ROWS_KEY) or 0) >= (_mtime(pk) or 0)):
        rows = list(c.get("rows") or [])
    else:
        if pd is not None:
            rows = list(pd["tasks"])
        else:
            rows = [t for t in cache_store.get("all_tasks") or []
                    if isinstance(t, dict) and t.get("projectId") == list_id]
        seen = {t.get("id") for t in rows if isinstance(t, dict)}
        full = _complete_of(list_id) or {}
        feed = [t for t in cache_store.get("completed_tasks") or []
                if isinstance(t, dict) and t.get("projectId") == list_id]
        for t in list((c or {}).get("rows") or []) + list(full.get("rows") or []) + feed:
            if isinstance(t, dict) and t.get("status") in _CLOSED and t.get("id") not in seen:
                seen.add(t.get("id"))
                rows.append(t)
    return okr.items_from([t for t in rows if isinstance(t, dict) and t.get("id")])


def _lazy_v2():
    try:
        from api_v2 import TickTickV2
        return TickTickV2()
    except Exception:
        return None


def _why_not_cached(last, v2=None):
    """_why_not for the read the screens last saw (okr_rows: its detail,
    when the writer that kept it stored one) - the wording the verb's own
    refusal will carry. The v2 token is looked up only when the detail
    has not already answered (a Keychain read, and this runs in renders)."""
    detail = str((last or {}).get("detail") or "")
    if v2 is None and not _rate_limited(detail) and "TRUNCATED" not in detail:
        v2 = _lazy_v2()
    return _why_not(okr.Snapshot([], "live", detail, ""), v2)


def import_plan(kind, pid, tid=None, items=None, list_id=None, v2=None):
    """THE answer to "can this task, note or list be added to the OKRs,
    and if not, why" - the ⌘ Actions "🥅 Add to OKRs" row and the import
    screen (ctx:okrimport) ask it and nothing else, and add_items asks the
    same questions of its live read (plan_of, _verdict), so all three
    agree. Pure over the caches, never raises:

        {"name", "link": {"to", "pid", "tid"} | None, "kind_hint",
         "hit": <plan Item already linking it> | None,
         "screen": <ctx that shows the hit> | None,
         "blocked": <refusal text> | None}

    source   import_source (name, link, kind_hint); its Refusal is
             `blocked` with link None - OKRs off, the plan list, a task of
             it, the periodic list, not cached, nothing to name it by
    plan     `items` when given (the screen's own snapshot), else
             cached_plan - the rows the hub screens read
    hit      planned() asked ONCE, with the payload's link (a list's
             📌CTA task when it has one; the list <-> CTA face is a Y /
             O's), through _verdict: open, then closed, answer
    blocked  also the predictable no-complete-read case: the last live
             read (okr_rows) missed completed KRs, so the verb's will
             too, and then the verb has only okr_complete to go on - none
             stored, or the only hit a row gone since, and the verb
             refuses with _why_not: that wording, here first. A copy of
             the plan list found in the plan (a closed one) is _in_plan's.

    `v2` only words a blocked answer (the Attachment Login token), built
    lazily when needed."""
    out = {"name": "", "link": None, "kind_hint": None, "hit": None,
           "screen": None, "blocked": None}
    try:
        src = import_source(kind, pid, tid)
        if isinstance(src, Refusal):
            out["blocked"] = str(src)
            return out
        out.update(src)
        list_id = list_id or cfg.get_okr_list_id()
        if items is None:
            items = cached_plan(list_id)
        last = cache_store.get(ROWS_KEY)
        last = last if isinstance(last, dict) and last.get("list_id") == list_id else None
        # the verb's read is predicted by the last one. None known (the hub
        # never opened, or the list just switched): a stored complete read
        # says the feed works; else the v2 token decides - without it no
        # read is ever complete (a Keychain look, only in this rare state)
        if last is None:
            complete = bool(_complete_of(list_id)) or _has_token(v2 or _lazy_v2())
        else:
            complete = last.get("done_complete") is True
        plan = plan_of(items, list_id, complete)
        link = src["link"]
        to, lpid, ltid = link["to"], link.get("pid"), link.get("tid")
        if to == "task":
            known = okr.index(plan.items).get(ltid)
            if known is not None:              # a (closed) copy of the plan list
                out["blocked"] = _in_plan(known)
                return out
        hit, blocked = _verdict(plan, to, lpid, ltid)
        if hit is not None:
            out["hit"], out["screen"] = hit, screen_of(hit, plan.items)
        elif blocked:
            out["blocked"] = _why_not_cached(last, v2)
    except Exception as e:
        out["blocked"] = f"🥅 Unreadable · {type(e).__name__}"
    return out


# ── add_items: the one creator ───────────────────────────────────────────────
def add_items(spec, api=None, v2=None):
    """xact:okr_add {"kind": Y|O|KR, "parent": id|null, "names": [...],
    "code": str|null, "link": {"to": task|list, "pid", "tid"}|null,
    "then": "tag"|null, "back": ctx}. Every name becomes a planning copy in
    the OKR list: UNDATED (a fresh copy stays undated until Vex drags it -
    and v1 create with both dates forces isAllDay false, map trap 3), under
    `parent`, siblings in TYPED order, in the parent's timeZone (else
    Europe/Berlin) - the body _settle_kids posts anyway. No heal: undated
    items shape no span.

    Levels (HANDOFF_OKR section 2): a 🏔️ Y has no parent; a 🥅 O goes
    under an OPEN Y or none; a 🔑 KR under an OPEN O. Anything else is a
    Refusal. A link names ONE item (the row that imports a task sends one
    name); several names are text-only siblings, the pipe's rapid fire.

    Codes: a KR takes kr_code's - the given one, else its O's (okr.code_of),
    else a proposal that reads back - written into the O's description
    when the O had none, AFTER the creates and only when a KR landed with
    it (nothing made, nothing to name); an existing code is never
    rewritten (add_krs's rule, and add_krs is now this with kind KR). An
    O's own hand-typed code that a title cannot read back skips every
    name, worded by code_problem ("TickAL's code 'xy' does not read back
    · fix its 🏷️ line"), never as "reads as a code" - that is a NAME's
    skip. An O takes the given code (one O only: a code names ONE
    objective) or okr.propose_code(its name), written as ITS OWN 🏷️
    description line at the create; its title carries no suffix. A Y
    carries no code; a given one is ignored.

    Tags: a KR inherits its O's tags (every tag an O carries is a pool tag,
    tag_pool); a Y / O inherits nothing - the tag picker follows.

    DEDUPE (one smart action), import_plan's questions asked of the live
    read: a link whose task / list the plan already plans (_verdict over
    plan_items: planned(), open or closed) is refused "Already in the
    plan" and lands on THAT item's screen. A link to a task of the OKR
    list is refused by what it is (_in_plan): a planning copy (a closed
    one the live read missed too, found in okr_complete), or an unprefixed
    item that wants its prefix; the plan list itself too, and the periodic
    notes (PERIODIC).

    Needs a LIVE read (settled names, the O's code, the dedupe) but not the
    completed feed - except a LINKED add, whose dedupe must see closed
    items: without them it takes the last complete read (okr_complete),
    and a hit only on a row gone since, or no complete read at all and no
    hit, is refused in _why_not's words. The lock as every writer.

    Toasts: an imported KR (a link, one made) reads like the other levels
    ("🥅 Added · 🔑 Goals wf under TickAL · code TA"); typed KRs and the
    add_krs alias keep phase 2's count ("🔑 3 KRs under TickAL · code TA").
    An import that did not land says so and why ("🥅 Not added · 🔑 Goals
    wf under TickAL · TickTick refused the create · try again"; a rate
    limit says to wait).
    -> Outcome(msg, reopen, ids): reopen = the new item's tag picker
    (ctx:okrtag:<id>) when then == "tag" and exactly one Y / O was made,
    else None (the payload's back)."""
    kind = spec.get("kind")
    if kind not in okr.KINDS:
        raise Refusal("🥅 Add what? A 🏔️ Y, 🥅 O or 🔑 KR")
    glyph = GLYPH[kind]
    parent_id = str(spec.get("parent") or "") or None
    names = _names(spec.get("names"))
    if not names:
        raise Refusal("🔑 No KR names" if kind == "KR" else f"{glyph} No names")
    link = _link_arg(spec.get("link"))
    if link and len(names) != 1:
        raise Refusal("🔗 A link copies ONE item · one name, or no link")
    given = spec.get("code")
    given = str(given).strip() if given not in (None, "") and kind != "Y" else None
    if given is not None and not code_ok(given):
        raise Refusal(f"{glyph} Code {given!r} would not read back · one word, capital first")
    if kind == "O" and given is not None and len(names) > 1:
        raise Refusal("🥅 =XY codes ONE objective · add them one at a time")
    if kind == "Y" and parent_id:
        raise Refusal("🏔️ A year objective is top level · no parent")
    if kind == "KR" and not parent_id:
        raise Refusal("🔑 KRs go under a 🥅 O · pick one")
    okr_pid = cfg.get_okr_list_id()
    if link and okr_pid and link[1] == okr_pid:
        raise Refusal(_in_plan(_cached_row(link[2])) if link[0] == "task" else PLAN_LIST)
    per = _periodic_pid()
    if link and per and (link[1] == per or (
            link[0] == "task" and _row_pid(_cached_row(link[2]) or {}) == per)):
        raise Refusal(PERIODIC)
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        by = okr.index(snap.items)
        url = None
        if link:
            to, lpid, ltid = link
            if to == "list" and lpid == snap.list_id:
                raise Refusal(PLAN_LIST)
            if to == "task" and (ltid in by or lpid == snap.list_id):
                raise Refusal(_in_plan(by.get(ltid) or _cached_row(ltid)))
            # the dedupe: import_plan's questions, asked of the live read
            plan = plan_items(snap)
            known = okr.index(plan.items).get(ltid) if to == "task" else None
            if known is not None:              # a closed copy the live read missed
                raise Refusal(_in_plan(known))
            hit, blocked = _verdict(plan, to, lpid, ltid)
            if hit is not None:
                raise Refusal(f"🥅 Already in the plan · {_glyph(hit.kind)} {hit.name}",
                              reopen=screen_of(hit, plan.items))
            if blocked:
                raise Refusal(_why_not(snap, v2))
            url = okr.task_link(lpid, ltid) if to == "task" else okr.list_link(lpid)
        parent = None
        if parent_id:
            parent = by.get(parent_id)
            want = "O" if kind == "KR" else "Y"
            if parent is None:
                raise Refusal("🔑 That objective is gone from the list" if kind == "KR"
                              else "🥅 That year objective is gone from the list")
            if parent.kind != want:
                raise Refusal(f"🔑 KRs go under a 🥅 O · {parent.name} is not one"
                              if kind == "KR" else
                              f"🥅 Objectives go under a 🏔️ Y · {parent.name} is not one")
            if parent.history:
                # done or won't do; a KR's refusals all speak 🔑 (phase 2's add_krs)
                raise Refusal(f"{glyph if kind == 'KR' else GLYPH[want]} {parent.name} "
                              f"is closed · reopen it first")
        note, code, have, tags, bad = "", None, None, None, None
        if kind == "KR":
            code, have = kr_code(parent, snap.items, given)
            bad = code_problem(parent.name, code)    # the O's own, typed by hand
            tags = list((parent.raw or {}).get("tags") or []) or None
        made, codes, skipped, failed, rate = [], [], [], [], False
        for name in names:
            own = None
            if kind == "O":
                own = given or okr.propose_code(name) or None
                if own and not code_ok(own):
                    own = None
            title = _title_for(kind, name, url, code if kind == "KR" else None)
            if title is None:
                skipped.append(name)
                continue
            content = okr.code_line(own) if own else None
            kw = {"content": content} if content else {}
            try:
                t = api.create_task(title=title, project_id=snap.list_id,
                                    parent_id=parent.id if parent else None,
                                    tags=tags, **kw)
            except Exception as e:
                failed.append(name)
                rate = rate or _rate_limited(type(e).__name__)
                continue
            if isinstance(t, dict) and t.get("id"):
                t = dict(t)
                t["parentId"] = parent.id if parent else None   # the response says null
                t["projectId"] = t.get("projectId") or snap.list_id
                if content and not t.get("content"):
                    t["content"] = content
                made.append(t)
                codes.append((name, own))
            else:
                failed.append(name)
        # the O's new code lands only when a KR carries it: nothing made,
        # nothing to name
        if kind == "KR" and made and code and have is None:
            note = _stamp_code(api, snap, parent, code)
        under = parent.id if parent else None
        sibs = [(i.raw or {}).get("sortOrder") for i in snap.items
                if (i.parent or None) == under]
        _settle_kids(api, v2, made, snap.list_id, under,
                     (parent.tz if parent else None) or okr.DEFAULT_TZ, sibs)
        patch_cache(snap, add=made)
    n = len(made)
    ids = [t["id"] for t in made]
    # a skip is worded by its cause: a KR code that does not read back is
    # the O's (every name fails on it), else the name itself reads as a code
    by_code = skipped if bad else []
    by_name = [] if bad else skipped
    busy = "TickTick rate limit · try again in a minute"
    if kind == "KR":
        where = f" under {parent.name}"
    else:
        where = f" under {GLYPH[parent.kind]} {parent.name}" if parent else ""
    if url and not n:                 # an import that did not land: say why
        why = (bad if by_code else "the name reads as a code" if by_name
               else busy if rate else "TickTick refused the create · try again")
        return Outcome(f"🥅 Not added · {glyph} {names[0]}{where} · {why}", None, [])
    if kind == "KR":
        if url and n == 1:           # an import: the other levels' toast
            msg = f"🥅 Added · {glyph} {codes[0][0]}{where}"
        elif n:
            msg = f"🔑 {n} KR{'' if n == 1 else 's'}{where}"
        else:
            msg = f"🔑 No KR added{where}"
        msg += f" · {bad}" if bad else f" · code {code}" if code else " · no code"
        msg += note
    else:
        word = _KIND_WORD[kind]
        if n == 1:
            msg = f"🥅 Added · {glyph} {codes[0][0]}{where}"
        elif n:
            msg = f"🥅 Added · {n} {glyph} {word}s{where}"
        else:
            msg = f"🥅 No {word} added"
        if kind == "O" and n:
            mine = [c for _nm, c in codes if c]
            msg += (f" · code{'' if n == 1 else 's'} {', '.join(mine)}" if mine
                    else " · no code")
    if by_name:
        msg += " · skipped " + ", ".join(repr(s) for s in by_name[:3]) + " (reads as a code)"
    if failed:
        msg += f" · ⚠️ {len(failed)} not created" + (f" · {busy}" if rate else "")
    reopen = (f"ctx:okrtag:{ids[0]}" if spec.get("then") == "tag" and kind != "KR"
              and n == 1 else None)
    return Outcome(msg, reopen, ids)


def add_krs(spec, api=None, v2=None):
    """xact:okr_addkr {"oid", "names": [...], "code": str|null} - phase 2's
    KR rapid fire, kept so its rows (ctx:okraddkr) keep working: add_items
    with kind KR under `oid`, the toast as it always read ("🔑 3 KRs under
    TickAL · code TA")."""
    return add_items({"kind": "KR", "parent": spec.get("oid"),
                      "names": spec.get("names"), "code": spec.get("code")},
                     api, v2).msg


# ── 🔗 link a task, note or list ─────────────────────────────────────────────
def _target_name(to, pid, tid):
    try:
        if to == "list":
            p = next((p for p in (cache_store.get("projects") or [])
                      if isinstance(p, dict) and p.get("id") == pid), None)
            return f"📂 {p.get('name')}" if p and p.get("name") else "the list"
        t = cache_store.find_task(tid) or {}
        import mdtext
        return mdtext.link_text(t.get("title") or "", 40) or "the task"
    except Exception:
        return "the task" if to == "task" else "the list"


def link(spec, api=None, v2=None):
    """xact:okr_link {"id", "to": task|list, "pid", "tid"}. Rewrites ONLY
    the planning copy's title: prefix and code outside the link, the name
    as its label ("🔑 KR • [Goals wf](<task link>) - TA"). The target is
    never touched - "moving a copy NEVER moves the real task". Built from
    the SETTLED Item (items_from), never raw parse_title candidates, so
    "Call Anna - Monday" does not gain the code Monday (map trap 14); a
    title with a link inside other words comes back as one whole-body link
    (build_title writes no other shape). NOTHING inside the OKR list is a
    target: not another planning copy (by its list, or by its id when the
    payload's list is stale), not the plan list itself."""
    iid = str(spec.get("id") or "")
    to = spec.get("to")
    pid = str(spec.get("pid") or "")
    tid = str(spec.get("tid") or "")
    if not iid or to not in ("task", "list") or not pid or (to == "task" and not tid):
        raise Refusal("🔗 Nothing to link")
    copy = "🔗 That is a planning copy · link the original"
    plan = "🔗 That is the plan list · link the real one"
    if pid == cfg.get_okr_list_id():
        raise Refusal(copy if to == "task" else plan)
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        by = okr.index(snap.items)
        it = by.get(iid)
        if it is None:
            raise Refusal("🔗 Not in the OKR list any more")
        if it.kind not in okr.KINDS:
            raise Refusal("🔗 Not an OKR item · give it a 🏔️ / 🥅 / 🔑 prefix first")
        if pid == snap.list_id or (to == "task" and tid in by):
            raise Refusal(copy if to == "task" else plan)
        url = okr.task_link(pid, tid) if to == "task" else okr.list_link(pid)
        new = okr.build_title(it.kind, it.name, link=url, code=it.code)
        if new == it.title:
            return f"🔗 Already linked · {it.name}"
        current = _live(api, snap, it)
        api.update_task(it.id, it.pid or snap.list_id, current=current, title=new)
        patch_cache(snap, patches={it.id: {"title": new}})
    return f"🔗 {it.name} → {_target_name(to, pid, tid)}"


# ── 🏷 tag from the OKR pool ─────────────────────────────────────────────────
def _area_tags():
    import tagtree
    return {str(t).lower() for t in tagtree.children_of(AREA_ROOT) if t}


def tag_pool(items):
    """The OKR tags (HANDOFF_OKR section 4, the picker's pool; Vex's ruling
    2026-09-18): the 0️⃣Area subtags plus every tag a 🏔️ Y or 🥅 O of the
    list carries (the LANE tags - done ones too, a closed O still names its
    lane), lowercase. A tag only KRs or loose items carry is theirs, never
    the pool's: a retag keeps it."""
    pool = _area_tags()
    for it in items:
        if it.kind in okr.PARENT_KINDS:
            pool.update(_norm_tags(it.tags))
    return pool


def _tag_label(name):
    for t in cache_store.get("tags_tree") or []:
        if isinstance(t, dict) and (t.get("name") or "").lower() == name:
            return t.get("label") or name
    return name


def retag(spec, api=None, v2=None):
    """xact:okr_tag {"id", "tag"}. REPLACES the item's OKR-pool tags
    (tag_pool: 0️⃣Area + the Y/O lane tags) with the picked one and keeps
    every other tag. On an 🥅 O it cascades to its OPEN KRs whose pool tags
    share one with the O's old ones, or that carry no pool tag at all ("KRs
    inherit their O's tag") - a KR tagged into another lane on purpose
    keeps it. Tags compare as SETS: the same tags in another order is
    "already", no write. The picked tag must be in the pool: no area tag is
    ever created here (HANDOFF trap 11)."""
    iid = str(spec.get("id") or "")
    tag = str(spec.get("tag") or "").strip().lstrip("#").lower()
    if not iid or not tag:
        raise Refusal("🏷 No tag picked")
    api, v2 = _clients(api, v2)
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=False)
        it = okr.index(snap.items).get(iid)
        if it is None:
            raise Refusal("🏷 Not in the OKR list any more")
        pool = tag_pool(snap.items)
        if tag not in pool:
            raise Refusal(f"🏷 {_tag_label(tag)} is not an OKR tag · 0️⃣Area or a Y / O tag")

        def pool_tags(x):
            return {t for t in _norm_tags(x.tags) if t in pool}

        old = pool_tags(it)
        targets = [it]
        if it.kind == "O":
            for kr in okr.krs_of(it, snap.items):
                if kr.history or kr.id == it.id:
                    continue
                mine = pool_tags(kr)
                if not mine or mine & old:
                    targets.append(kr)
        todo = []
        for x in targets:
            now = _norm_tags(x.tags)
            drop = pool_tags(x)
            new = _norm_tags([tag] + [t for t in now if t not in drop])
            if set(new) != set(now):
                todo.append((x, {"tags": new}))
        if not todo:
            return f"🏷 {it.name} already {_tag_label(tag)}"
        written, failed = _write(snap, todo, api, v2)
        ok = set(written)
        patch_cache(snap, patches={x.id: f for x, f in todo if x.id in ok})
    krs = sum(1 for x, _f in todo if x.id != it.id and x.id in ok)
    mine_ok = it.id in ok or all(x.id != it.id for x, _f in todo)
    msg = f"🏷 {_tag_label(tag)} · {it.name}" if mine_ok else f"🏷 {it.name} not retagged"
    if krs:
        msg += f" · {krs} KR{'' if krs == 1 else 's'} too"
    if failed:
        msg += f" · ⚠️ {len(failed)} not written"
    return msg


# ── upkeep: auto-tick + the countdowns (hub open, hourly sync) ──────────────
Upkeep = namedtuple("Upkeep", "ticked chip note")


def upkeep(api=None, v2=None, is_done=None, today=None):
    """The background pass: the ⏳ countdowns kept in step (sync_countdowns),
    then every open KR whose linked single task is COMPLETED gets ticked
    ("Auto-tick: YES", only a live status 2 ticks). NO span heal since
    2026-09-23 ("Heal off"): a parent's dates are Vex's. Silent unless it
    wrote: -> Upkeep(ticked, chip, note); chip is "" when nothing changed,
    note always says what happened (the detached run's log line).

    Never blocks: the lock is taken non-blocking and a busy lock skips the
    pass - a user verb holds it. The done lookups (one GET per task-linked
    open KR) run OUTSIDE the lock so a hub open never makes a verb wait on
    them; the ticks take the lock again, and inside that second hold every
    candidate is RE-READ and ticked only while still open (status 0):
    another pass (the hourly one and a hub open overlap) or Vex may have
    ticked it since the first read, and only the ticks that happened are
    counted. okr_rows is rebuilt from the first hold's read only while no
    other writer has left a copy since; otherwise it is dropped (patch_cache
    rebuild=False). Never raises (the hourly sync must not die on a
    nicety)."""
    try:
        pid = cfg.get_okr_list_id()
        if not pid:
            return Upkeep(0, "", "okr list off")
        api, v2 = _clients(api, v2)
        with _lock(wait=0) as got:
            if not got:
                return Upkeep(0, "", "busy: another OKR write holds the lock")
            try:
                snap = okr.load(api=api, v2=v2, list_id=pid)
            except okr.OkrLoadError as e:
                return Upkeep(0, "", f"unreadable: {e}")
            if not snap.writable:
                return Upkeep(0, "", f"refused (not a complete live read): {snap.detail}")
            remember_complete(snap)
            cd_chip, cd_note = sync_countdowns(snap, v2, today)
            linked = [k for k in snap.items if k.kind == "KR" and not k.history
                      and (k.target or ("",))[0] == "task"]
            left = cache_store.get(ROWS_KEY) if linked else None
        ticked, tick_fail, moved_on = [], 0, 0
        if linked:
            look = is_done or okr.done_lookup(api)
            cands = okr.autotick_candidates(linked, look)
            if cands:
                with _lock(wait=30) as got:
                    if got:
                        for kr in cands:
                            p = kr.pid or snap.list_id
                            try:
                                now = api.get_task(p, kr.id)
                            except Exception:
                                now = None
                            if not (isinstance(now, dict) and now.get("status") == 0
                                    and not now.get("deleted")):
                                moved_on += 1     # ticked, gone or unreadable since
                                continue
                            try:
                                api.complete_task(p, kr.id)
                                ticked.append(kr.id)
                            except Exception:
                                tick_fail += 1
                        if ticked:
                            patch_cache(snap, done=ticked,
                                        rebuild=cache_store.get(ROWS_KEY) == left)
                    else:
                        tick_fail = len(cands)
        parts = []
        if ticked:
            parts.append(f"🔑 {len(ticked)} KR{'' if len(ticked) == 1 else 's'} ticked · "
                         f"original{'' if len(ticked) == 1 else 's'} done")
        if cd_chip:
            parts.append(cd_chip)
        note = (f"ticked {len(ticked)} (failed {tick_fail}, no longer open {moved_on}), "
                f"{len(linked)} linked open KRs · {cd_note} · {snap.detail}")
        return Upkeep(len(ticked), " · ".join(parts), note)
    except Exception as e:
        return Upkeep(0, "", f"failed: {type(e).__name__}: {e}")


def spawn_upkeep(debounce_s=300):
    """Fire-and-forget "xact:okr_upkeep", detached (xact._pn_bg's shape): safe
    from a script filter render, returns at once. Debounced through
    app_sync.claim on its own stamp - the hub re-renders on every
    keystroke, and one pass per `debounce_s` is plenty. The child never
    inherits the render's stdout (it would corrupt the Alfred JSON, map
    trap 9): stdout/stderr go to UPKEEP_LOG, stdin is /dev/null, and it runs
    in its own session with TICKAL_DETACHED=1 (so it banners, not prints).
    -> True when a child was started."""
    try:
        if not cfg.get_okr_list_id():
            return False
        import app_sync
        if not app_sync.claim(min_gap=debounce_s, stamp=UPKEEP_STAMP):
            return False
        wf = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(UPKEEP_LOG, "a") as logf:
            subprocess.Popen(
                ["/bin/bash", os.path.join(wf, "Scripts", "py.sh"),
                 os.path.join(wf, "Scripts", "xact.py"), "xact:okr_upkeep"],
                stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                start_new_session=True, env=dict(os.environ, TICKAL_DETACHED="1"))
        return True
    except Exception:
        return False


# ── ⏳ countdowns: one per active objective, to its end (phase 5) ─────────────
# HANDOFF_OKR section 4: "auto-maintained, one per active objective, to its
# end" (okr.countdown_targets: an open Y/O that has started). A countdown has
# no list, tag or link to say whose it is, so OURS carry a marker in their
# remark ("🥅 OKR · <item id>", shown on no card: showRemark false), and
# ~/.ticktick_alfred/okr_countdowns.json remembers what was minted - {item
# id: {"cid", "by_us"}} - so one Vex archived or deleted is never minted
# again, while one WE archived (its objective closed, or lost its dates)
# comes back when the objective does. Kind ⏳ Countdown (4, one-shot), no
# reminders (the objective sits on the calendar already), dated on the
# objective's INCLUSIVE end - it reads "today" on the last day.
CD_KEY = "countdowns"
CD_REGISTRY = os.path.join(cfg.CONFIG_DIR, "okr_countdowns.json")
CD_MARK = "🥅 OKR · "
_CD_MARK_RE = re.compile(re.escape(CD_MARK) + r"([0-9A-Za-z]+)")
CD_STEP = 1048576         # xact.countdown_new's sortOrder gap (new = on top)

CdPlan = namedtuple("CdPlan", "add update archive registry known")


def cd_owner(cd):
    """The plan item a countdown follows (its remark marker), else None."""
    m = _CD_MARK_RE.search((cd or {}).get("remark") or "")
    return m.group(1) if m else None


def cd_name(it):
    return f"{_glyph(it.kind)} {it.name}"


def cd_date(d):
    return d.year * 10000 + d.month * 100 + d.day


def _cd_live(c):
    return (c or {}).get("status", 0) == 0 and not (c or {}).get("archivedTime")


def countdown_plan(items, existing, registry, today=None, new_id=None):
    """Pure: what the OKR countdowns should become -> CdPlan(add, update,
    archive, registry, known). Entities are FULL (the batch takes whole
    objects: an update is the listed entity with the fields over it, as
    xact's countdown_edit posts it). `registry` is the file's next content
    once the batch landed; `known` is what is safe to save even when it did
    not: the file reconciled with what the LIST shows (a live countdown of
    ours is recorded as minted, not by us - back-filled after a lost save,
    and a stale by_us cleared, so a later archive by Vex is never undone)
    plus the archives this pass makes (by_us - a closed item is archived
    again next pass if this one did not land). Adds and un-archives wait
    for the ack (review 2026-09-19).

      an open Y/O with an end    its countdown follows its name and end;
                                 one it lacks is minted once it has STARTED
                                 (okr.countdown_targets), unless Vex removed
                                 an earlier one (minted, not by_us)
      closed, or no dates left   its live countdown is archived (by_us)
      gone from the plan         the same (a writable read is complete, so
                                 absent = deleted or won't do)

    One archived by us comes back for a started objective: updated back to
    live when the list still shows it, minted afresh when it does not."""
    import countdowns as cds
    today = today or date.today()
    if new_id is None:
        from api_v2 import new_object_id as new_id
    known = {k: dict(v) for k, v in (registry or {}).items()
             if isinstance(k, str) and isinstance(v, dict)}
    reg = known                  # read below; what is planned goes to `landed`
    landed = {}
    listed = [c for c in existing or [] if isinstance(c, dict) and c.get("id")]
    by_cid = {c["id"]: c for c in listed}
    ours = {}
    for c in listed:
        o = cd_owner(c)
        if o and (o not in ours or _cd_live(c)):
            ours[o] = c
    for iid, rec in reg.items():
        c = by_cid.get(rec.get("cid"))
        if c is not None and iid not in ours:
            ours[iid] = c                 # its remark was edited: still ours
    active = {it.id for it, _e in okr.countdown_targets(items, today)}
    top = min((c.get("sortOrder") or 0 for c in listed), default=0)
    add, update, archive = [], [], []
    for it in items:
        if it.kind not in okr.PARENT_KINDS:
            continue
        c, rec = ours.get(it.id), reg.get(it.id)
        e = it.end                       # STORED: the bar Vex drew
        if it.history or e is None:
            if c is not None and _cd_live(c):
                archive.append({**c, "status": 1})
                known[it.id] = {"cid": c["id"], "by_us": True}
            continue
        name, d = cd_name(it), cd_date(e)
        if c is not None:
            if _cd_live(c):
                known[it.id] = {"cid": c["id"], "by_us": False}
                if c.get("name") != name or c.get("date") != d:
                    update.append({**c, "name": name, "date": d})
            elif rec and rec.get("by_us") and it.id in active:
                update.append({**c, "name": name, "date": d, "status": 0,
                               "archivedTime": None})
                landed[it.id] = {"cid": c["id"], "by_us": False}
            continue
        if it.id in active and (rec is None or rec.get("by_us")):
            top -= CD_STEP
            ent = cds.new_entity(new_id(), name, d, 4, appear=0, sort_order=top)
            ent.update(reminders=[], remark=CD_MARK + it.id, showRemark=False)
            add.append(ent)
            landed[it.id] = {"cid": ent["id"], "by_us": False}
    # "gone" = no longer a Y/O in the plan: deleted, won't do (a writable read
    # is complete, so absent means one of those), or retitled into a KR or
    # plain task - its countdown must not live on (review 2026-09-19)
    present = {it.id for it in items if it.kind in okr.PARENT_KINDS}
    for iid, c in ours.items():
        if iid not in present and _cd_live(c):
            archive.append({**c, "status": 1})
            known[iid] = {"cid": c["id"], "by_us": True}
    return CdPlan(add, update, archive, {**known, **landed}, dict(known))


def _cd_registry():
    try:
        with open(CD_REGISTRY) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cd_save(reg):
    tmp = CD_REGISTRY + ".tmp"
    with open(tmp, "w") as f:
        json.dump(reg, f, indent=1, sort_keys=True)
    os.replace(tmp, CD_REGISTRY)


def _cd_patch_cache(plan):
    """The countdowns cache (the ⏳ hub and search read it) follows the
    write: new and updated live ones in, archived ones out - xact
    _cd_patch's rule, which Scripts/ keeps and src/ cannot import."""
    try:
        rows = cache_store.get(CD_KEY)
        if not isinstance(rows, list):
            return
        drop = {c["id"] for c in plan.archive}
        put = {c["id"]: c for c in plan.add + plan.update}
        out = [put.pop(c.get("id"), c) for c in rows
               if isinstance(c, dict) and c.get("id") not in drop]
        cache_store.set(CD_KEY, out + list(put.values()))
    except Exception:
        try:
            cache_store.invalidate(CD_KEY)
        except Exception:
            pass


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def sync_countdowns(snap, v2, today=None):
    """Bring the OKR countdowns in step with `snap` (countdown_plan) -> (chip,
    note): chip "" when nothing was written. Only from a WRITABLE snap (a
    partial read would archive the countdown of an objective it merely did
    not see) and only with the v2 token (countdowns have no Open API road).
    The registry's adds and un-archives are saved only after TickTick took
    the batch: a registry naming a countdown that was never made would block
    it for good; what the list itself shows (plan.known) is saved either
    way. Call it inside the OKR lock. Never raises."""
    try:
        if snap is None or not snap.writable:
            return "", "countdowns: not a complete live read"
        if not _has_token(v2):
            return "", "countdowns: no v2 token"
        existing = v2.get_countdowns()
        if existing is None:
            return "", "countdowns: list unreadable"
        loaded = _cd_registry()
        plan = countdown_plan(snap.items, existing, loaded, today)

        def keep(reg):
            if reg != loaded:
                try:
                    _cd_save(reg)
                except OSError:
                    pass

        if not (plan.add or plan.update or plan.archive):
            keep(plan.known)
            return "", "countdowns: in step"
        if not v2.countdown_batch(add=plan.add, update=plan.update + plan.archive):
            keep(plan.known)
            return "", "countdowns: TickTick refused the batch"
        keep(plan.registry)
        _cd_patch_cache(plan)
        parts = []
        if plan.add:
            parts.append(f"⏳ {_plural(len(plan.add), 'countdown')} added")
        if plan.update:
            parts.append(f"⏳ {_plural(len(plan.update), 'countdown')} updated")
        if plan.archive:
            parts.append(f"⏳ {_plural(len(plan.archive), 'countdown')} archived")
        chip = " · ".join(parts)
        return chip, "countdowns: " + chip
    except Exception as e:
        return "", f"countdowns failed: {type(e).__name__}: {e}"


# ── ↪️ the quarter carry-over: carry / won't do / someday (phase 5) ──────────
CARRY_ACTIONS = ("wontdo", "someday")


def _carry_item(snap, iid):
    """The item one carry-over decision is about, else Refusal: in the
    plan, open, and a LEAF (okr.carry_candidates) - a parent follows its
    KRs, and deciding one of its KRs is the decision."""
    by = okr.index(snap.items)
    it = by.get(iid)
    if it is None:
        raise Refusal("🥅 Not in the OKR list any more")
    if it.history:
        raise Refusal(f"🥅 {it.name} is closed already")
    if not okr.carry_leaf(it, okr.wanted_spans(snap.items), by):
        raise Refusal(f"🥅 {it.name} follows its KRs · decide those")
    return it


def _open_below(snap, it):
    """The open items hanging under `it` (undated KRs under a hand-dated O,
    a KR's own subtasks): a won't do on it alone would strand them under a
    parent no later read returns (review 2026-09-19)."""
    by = okr.index(snap.items)
    return [by[x] for x in okr._descendants(it.id, okr._kids(snap.items))
            if x in by and not by[x].history]


def _mirror_wontdo(snap, it, live, stamp):
    """xact.wontdo's cache mirror, from src/: the wontdo_tasks log (the 🚫
    screen and ⇧ undo read it), out of all_tasks, completed_tasks and the
    list's project_data; then patch_cache folds status -1 into snap.items
    (so nothing that follows counts it) and rebuilds okr_rows
    LAST, where the hub shows it 🚫 with ⇧ ↩️ until the next live read."""
    tid = it.id
    try:
        row = dict(it.raw or live or {}, status=-1, completedTime=stamp)
        log = [t for t in (cache_store.get("wontdo_tasks") or [])
               if isinstance(t, dict) and t.get("id") != tid]
        cache_store.set("wontdo_tasks", ([row] + log)[:200])
        for key in ("all_tasks", "completed_tasks"):
            rows = cache_store.get(key)
            if isinstance(rows, list):
                cache_store.set(key, [t for t in rows
                                      if not (isinstance(t, dict) and t.get("id") == tid)])
        pk = _pd_key(it.pid or snap.list_id)
        pd = cache_store.get(pk)
        if isinstance(pd, dict) and isinstance(pd.get("tasks"), list):
            pd = dict(pd)
            pd["tasks"] = [t for t in pd["tasks"]
                           if not (isinstance(t, dict) and t.get("id") == tid)]
            cache_store.set(pk, pd)
    except Exception:
        pass
    patch_cache(snap, patches={tid: {"status": -1, "completedTime": stamp}})


def _after_close(snap, api, v2, today):
    """A decision took an item off the timeline: the countdowns follow (a
    parent's span is Vex's - no heal). -> toast tail."""
    chip, _note = sync_countdowns(snap, v2, today)
    return f" · {chip}" if chip else ""


def carry(spec, api=None, v2=None, today=None):
    """xact:okr_carry {"id", "action", "back"} - ONE decision on an item a
    quarter leaves open (okr.carry_candidates). Carrying it INTO the next
    quarter is a drag in TickTick (2026-09-23: TickAL moves no dates); the
    two decisions that are not a date are here:

      wontdo   TickTick's won't do (v2 status -1 + a stamped completedTime,
               the write xact.wontdo makes): out of progress, pace and
               the carry-over
      someday  undated (v1 nulls - the proven clear, dispatch
               attr_cleardate): off the timeline, still in the plan and in
               its O's KR count

    Both from a writable read inside the lock (the countdowns follow)."""
    iid = str(spec.get("id") or "")
    action = spec.get("action")
    if not iid or action not in CARRY_ACTIONS:
        raise Refusal("↪️ Nothing to decide")
    today = today or date.today()
    api, v2 = _clients(api, v2)
    if action == "wontdo" and not _has_token(v2):
        raise Refusal("🚫 Won't do needs the Attachment Login token (⚙️ Settings)")
    with _lock() as got:
        if not got:
            raise Refusal("🥅 Busy · another OKR write is running · try again")
        snap = _load(api, v2, writable=True)
        it = _carry_item(snap, iid)
        if action == "wontdo":
            below = _open_below(snap, it)
            if below:
                raise Refusal(f"🚫 {it.name} has {_plural(len(below), 'open item')} "
                              f"under it · decide those first")
            live = _live(api, snap, it)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
            if not v2.abandon_task(dict(live, completedTime=stamp)):
                raise Refusal(f"🚫 TickTick refused won't do on {it.name} · try again")
            _mirror_wontdo(snap, it, live, stamp)
            return f"🚫 Won't do: {it.name}" + _after_close(snap, api, v2, today)
        if not it.dated:
            raise Refusal(f"💤 {it.name} is off the timeline already")
        live = _live(api, snap, it)
        try:
            api.update_task(it.id, it.pid or snap.list_id, current=live,
                            startDate=None, dueDate=None)
        except Exception as e:
            raise Refusal(f"💤 Not written · {type(e).__name__}")
        patch_cache(snap, patches={it.id: {"startDate": None, "dueDate": None,
                                           "isAllDay": False}})
        return (f"💤 {it.name} → someday · off the timeline, still in the plan"
                + _after_close(snap, api, v2, today))


# ── ⚙️ Settings → OKR List ───────────────────────────────────────────────────
_LIST_ID_RE = re.compile(r"[0-9a-fA-F]{24}")


def parse_list_answer(answer):
    """The Settings dialog's answer -> the value to save: "" = OFF (a blank
    okr_list_id means off, HANDOFF_OKR section 5), a 24-hex list id as
    typed, None = not a list id (nothing saved)."""
    a = (answer or "").strip()
    if not a:
        return ""
    return a if _LIST_ID_RE.fullmatch(a) else None
