#!/usr/bin/env python3
"""
crm_records.py - per-customer notes + per-tattoo logbook notes (the
🗂️CRM • Records list). Pure content engine + API I/O; the UI lives in
browse.py (ctx:crmnew / crmdone / crmlog pickers) and xact.py (dialog verbs).

MODEL (agreed with Vex 2026-07-17):
- One CUSTOMER note per human (tag areas.CUSTOMER_TAG): contact line,
  ## Fun facts, ## Tattoos (one bullet per logbook: link + started/finished/
  paid chip), ## Notes (free-text log lines).
- One LOGBOOK note per tattoo PROJECT (tag areas.LOGBOOK_TAG, retagged
  areas.ARCHIVE_TAG when finished). The consultation is the FIRST entry of a
  fresh logbook, not a separate note kind - a lead converts in place. Header:
  customer link · Started/Finished dates, then a running Paid line.
  ## Sessions holds chronological entries, ## Notes free-text log lines.
- Entry header grammar (4 segments, "-" fills a skipped one):
      ### YYYY-MM-DD · S<n>|consultation · <duration> · <charged>
- Paid totals are RECOMPUTED from the session headers on every write (never
  incremented) - a hand-corrected amount self-heals both chips. The session
  count counts S-entries only (consultations aren't needle sessions).
- Links are native TickTick task links (how the app stores [[ ]] backlinks):
      [Title](https://ticktick.com/webapp/#p/<pid>/tasks/<tid>)
- Session tasks in the CRM calendar list are titled "<logbook link> S<n>" /
  "<logbook link> Consult" (marker is a SUFFIX; legacy prefix tolerated) -
  sessiondone parses the link back to its logbook, and dispatch suppresses
  the Prepare follow-up for S2+ titles.

Every write patches the caches the pickers read (all_notes / all_tasks /
project_data_{records}) so a fresh note is immediately pickable.
"""
import os
import re
import datetime

import config as cfg
import cache as cache_store
import areas
from api import TickTickAPI

LINK_RE = re.compile(
    r"\[([^\]]*)\]\(https://ticktick\.com/webapp/#p/(\w+)/tasks/(\w+)\)")
ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}[^\n]*)$", re.M)
# Session tasks carry their marker as a SUFFIX ("<logbook link> S2",
# Vex ruling 2026-07-17); the prefix form is tolerated as legacy.
SESSION_MARKER_RE = re.compile(r"^(S\d+|Consult)\s|\b(S\d+|Consult)\s*$")


def title_marker(title):
    """'S3' / 'Consult' from a session-task title (suffix, or legacy
    prefix), else None."""
    m = SESSION_MARKER_RE.search(title or "")
    return (m.group(1) or m.group(2)) if m else None


def title_snum(title):
    """The S-number of a session-task title, else None."""
    m = re.fullmatch(r"S(\d+)", title_marker(title) or "")
    return int(m.group(1)) if m else None

_API = None


def _api():
    global _API
    if _API is None:
        _API = TickTickAPI(cfg.get_token())
    return _API


def _today():
    return datetime.date.today().isoformat()


def task_link(pid, tid, title):
    return f"[{title}](https://ticktick.com/webapp/#p/{pid}/tasks/{tid})"


def parse_first_link(text):
    """(title, pid, tid) of the first task link in text, or None."""
    m = LINK_RE.search(text or "")
    return (m.group(1), m.group(2), m.group(3)) if m else None


def is_session_task(title):
    """True ONLY for tasks the records flow minted: an S<n>/Consult marker
    AND a PARSEABLE records-list link (the same parse sessiondone unpacks -
    gate and consumer share one shape definition, so nothing that passes here
    can crash the unpack). Prepare follow-ups fail the marker (their titles
    start 'Prepare for …') - without this shape check they passed every
    session-task gate and sessiondone would complete them and write phantom
    entries into the logbook."""
    t = title or ""
    if not title_marker(t):
        return False
    hit = parse_first_link(t)
    return bool(hit) and hit[1] == areas.RECORDS_ID


def _safe_name(name):
    """Customer/tattoo names ride Alfred-add prefill queries AND [title](url)
    links - strip the grammar/link-breaking characters at the single choke
    point (a ']' broke LINK_RE round-trips; # ~ ! * = & % > | trip the add
    parser's token triggers)."""
    return re.sub(r'[\[\]()#~!*=&%>|"]', "", name or "").strip()


def _ensure_tag(tag):
    """Records tags become REAL tag entities like every other tag-writing
    path (dispatch._ensure_tags_exist: emoji-blind twin guard, v2-token
    best-effort, never blocks the write)."""
    try:
        import dispatch as _disp
        _disp._ensure_tags_exist([tag])
    except Exception:
        pass


PERSON_RE = re.compile(r"^(?:👤|🎣)\s*")   # customer / lead note markers


def customer_display(cust):
    """'👤 Marko' / '🎣 Marko' → 'Marko' (note titles keep the marker,
    prose drops it)."""
    return PERSON_RE.sub("", (cust or {}).get("title") or "").strip()


def contact_of(cust):
    """(phone, mail, bday, insta) parsed from the 📞 header line ('-' → '')."""
    line = ((cust or {}).get("content") or "").split("\n", 1)[0]
    def seg(emoji):
        m = re.search(emoji + r"\s*([^·\n]*)", line)
        v = (m.group(1).strip() if m else "")
        return "" if v == "-" else v
    return seg("📞"), seg("✉️"), seg("🎂"), seg("📸")


def is_lead(note):
    return areas.LEAD_TAG in {str(t).lower() for t in ((note or {}).get("tags") or [])}


def customer_logbooks(cust_tid, include_archived=True):
    """This customer's logbooks (first content link points at them),
    open first."""
    tags = ([areas.LOGBOOK_TAG, areas.ARCHIVE_TAG] if include_archived
            else [areas.LOGBOOK_TAG])
    out, seen = [], set()
    for tag in tags:
        for lb in records_notes(tag):
            if lb["id"] in seen:
                continue
            hit = parse_first_link(lb.get("content") or "")
            if hit and hit[2] == cust_tid:
                seen.add(lb["id"])
                out.append(lb)
    return out


def lifetime(cust_tid):
    """(money_str, tattoo_count, session_count) across ALL the customer's
    logbooks - recomputed, like every money figure here."""
    total, sessions, sym, pre, k = 0.0, 0, "", False, 0
    for lb in customer_logbooks(cust_tid):
        k += 1
        t, n, s, p = _totals_raw(lb.get("content") or "")
        total += t
        sessions += n
        if not sym and s:
            sym, pre = s, p
    if k == 0 or (total == 0 and sessions == 0):
        return "-", k, sessions
    return _fmt_money(total, sym or "€", pre), k, sessions


def next_session_task(log_tid):
    """(local_date_str_or_'', marker, task) of the EARLIEST open calendar
    task linking this logbook, or None."""
    best = None
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) != areas.CRM_ID
                or t.get("status", 0) != 0
                or f"/tasks/{log_tid})" not in (t.get("title") or "")):
            continue
        due = t.get("dueDate") or t.get("startDate") or ""
        key = due or "9999"
        if best is None or key < best[0]:
            best = (key, due, t)
    if best is None:
        return None
    _, due, t = best
    day = ""
    if due:
        try:
            from filtering import utc_str_to_local_date
            day = utc_str_to_local_date(due)
        except Exception:
            day = due[:10]
    return day, (title_marker(t.get("title") or "") or ""), t


def dur_minutes(s):
    """Duration text → minutes: '3h'→180, '2h30'→150, '2.5h'→150, '90m'→90,
    '1:30'→90, bare '3'→180 (≤12 reads as hours, artists say '3'), bare
    '90'→90. None when unparseable."""
    s = (s or "").strip().lower().replace(",", ".")
    if not s or s == "-":
        return None
    m = re.fullmatch(r"(\d+):(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(\d{1,2})?", s)
    if m:
        return int(float(m.group(1)) * 60) + (int(m.group(2)) if m.group(2) else 0)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minutes)", s)
    if m:
        return int(float(m.group(1)))
    m = re.fullmatch(r"\d+(?:\.\d+)?", s)
    if m:
        v = float(s)
        return int(v * 60) if v <= 12 else int(v)
    return None


def payments_sum(content):
    """(money_str_or_'', total_float) of 'payment'-marker entries only -
    the deposit-on-file chip."""
    total, sym, pre = 0.0, "", False
    for segs in _entries(content):
        if len(segs) > 1 and (segs[1] or "").lower() == "payment" and len(segs) > 3:
            v = _num(segs[3])
            if v is not None:
                total += v
                if not sym:
                    m = re.fullmatch(
                        r"\s*([^\d\s.,\-]{1,3})?\s*-?[\d.,]+\s*([^\d\s.,\-]{1,3})?\s*",
                        segs[3])
                    if m and (m.group(1) or m.group(2)):
                        sym, pre = ((m.group(1), True) if m.group(1)
                                    else (m.group(2), False))
    if not total:
        return "", 0.0
    return _fmt_money(total, sym or "€", pre), total


def note_age_days(note):
    """Days since the note was created - TickTick ids embed the unix time in
    their first 8 hex chars, so this needs no extra field."""
    try:
        born = int(str(note.get("id"))[:8], 16)
        return max(0, int((datetime.datetime.now().timestamp() - born) // 86400))
    except Exception:
        return None


def bday_next(bday_str):
    """Days until the next birthday, parsed leniently ('1990-01-05',
    '01-05', '5.1.', '5.1.1990'). None when unparseable."""
    s = (bday_str or "").strip()
    m = (re.fullmatch(r"(?:\d{4}-)?(\d{1,2})-(\d{1,2})", s)
         or re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(?:\d{4})?", s))
    if not m:
        return None
    if "." in s:
        day, month = int(m.group(1)), int(m.group(2))
    else:
        month, day = int(m.group(1)), int(m.group(2))
    try:
        today = datetime.date.today()
        nxt = datetime.date(today.year, month, day)
        if nxt < today:
            nxt = datetime.date(today.year + 1, month, day)
        return (nxt - today).days
    except ValueError:
        return None


def monthly_stats():
    """{ 'YYYY-MM': (total_float, session_count, sym, pre) } across EVERY
    records logbook (open + archived) - the stats screen's data."""
    out = {}
    seen = set()
    for tag in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG):
        for lb in records_notes(tag):
            if lb["id"] in seen:
                continue
            seen.add(lb["id"])
            for m in ENTRY_RE.finditer(lb.get("content") or ""):
                segs = [s.strip() for s in m.group(1).split("·")]
                month = segs[0][:7]
                total, n, sym, pre = out.get(month, (0.0, 0, "", False))
                if len(segs) > 1 and re.fullmatch(r"S\d+", segs[1] or ""):
                    n += 1
                if len(segs) > 3:
                    v = _num(segs[3])
                    if v is not None:
                        total += v
                        if not sym:
                            s2 = re.fullmatch(
                                r"\s*([^\d\s.,\-]{1,3})?\s*-?[\d.,]+\s*([^\d\s.,\-]{1,3})?\s*",
                                segs[3])
                            if s2 and (s2.group(1) or s2.group(2)):
                                sym, pre = ((s2.group(1), True) if s2.group(1)
                                            else (s2.group(2), False))
                out[month] = (total, n, sym, pre)
    return out


def all_entries():
    """Every session-entry across every logbook (open + archived), flat:
    [(date_str, is_needle_session, amount_or_None, sym, pre)] - the money
    screens aggregate date ranges over this."""
    out = []
    seen = set()
    for tag in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG):
        for lb in records_notes(tag):
            if lb["id"] in seen:
                continue
            seen.add(lb["id"])
            for m in ENTRY_RE.finditer(lb.get("content") or ""):
                segs = [s.strip() for s in m.group(1).split("·")]
                is_s = bool(len(segs) > 1
                            and re.fullmatch(r"S\d+", segs[1] or ""))
                amt, sym, pre = None, "", False
                if len(segs) > 3:
                    amt = _num(segs[3])
                    if amt is not None:
                        s2 = re.fullmatch(
                            r"\s*([^\d\s.,\-]{1,3})?\s*-?[\d.,]+\s*([^\d\s.,\-]{1,3})?\s*",
                            segs[3])
                        if s2 and (s2.group(1) or s2.group(2)):
                            sym, pre = ((s2.group(1), True) if s2.group(1)
                                        else (s2.group(2), False))
                mins = dur_minutes(segs[2]) if len(segs) > 2 else None
                if len(segs) > 3 and is_gratis(segs[3]):
                    mins = None   # gratis: hours invisible to rate math
                out.append((segs[0], is_s, amt, sym, pre, mins))
    return out


def cut_percent():
    """Artist's share of charged amounts (crm_cut env var, percent). Default
    50 (Vex's split). <=0 or >=100 disables the 🫵 chip entirely (100 =
    it's all yours anyway, nothing to show)."""
    try:
        v = float(os.environ.get("crm_cut", "50"))
    except ValueError:
        v = 50.0
    return v if 0 < v < 100 else None


def cut_chip(raw_total, money_str=""):
    """' · 🫵 3975€' - the artist's share, appended after money totals.
    Currency symbol recovered from the formatted total it follows."""
    p = cut_percent()
    if not p or not raw_total:
        return ""
    sym = re.sub(r"[-\d.,\s]", "", money_str or "") or "€"
    pre = bool(sym) and (money_str or "").strip().startswith(sym)
    return f" · 🫵 {_fmt_money(raw_total * p / 100.0, sym, pre)}"


def sum_entries(entries, start=None, end=None):
    """(money_str, session_count, hours_float, raw_total) over entries whose
    date is in [start, end] (ISO date strings, inclusive; None = unbounded)."""
    total, n, sym, pre, mins = 0.0, 0, "", False, 0
    for date, is_s, amt, s, p, mm in entries:
        if (start and date < start) or (end and date > end):
            continue
        if is_s:
            n += 1
            if mm:
                mins += mm
        if amt is not None:
            total += amt
            if not sym and s:
                sym, pre = s, p
    hours = round(mins / 60.0, 1)
    if total == 0 and n == 0:
        return "-", 0, hours, 0.0
    return _fmt_money(total, sym or "€", pre), n, hours, total


def lifetime_raw(cust_tid):
    """Numeric lifetime total for sorting the money-per-customer view."""
    total = 0.0
    for lb in customer_logbooks(cust_tid):
        t, _n, _s, _p = _totals_raw(lb.get("content") or "")
        total += t
    return total


def note_created_date(note):
    """ISO creation date from the id-embedded timestamp."""
    try:
        return datetime.date.fromtimestamp(
            int(str(note.get("id"))[:8], 16)).isoformat()
    except Exception:
        return None


def _amount_of(segs):
    """(amount_float_or_None, sym, pre) from an entry's charged segment."""
    if len(segs) < 4:
        return None, "", False
    v = _num(segs[3])
    if v is None:
        return None, "", False
    m = re.fullmatch(
        r"\s*([^\d\s.,\-]{1,3})?\s*-?[\d.,]+\s*([^\d\s.,\-]{1,3})?\s*",
        segs[3])
    if m and (m.group(1) or m.group(2)):
        return v, (m.group(1) or m.group(2)), bool(m.group(1))
    return v, "", False


def entries_detailed():
    """Every entry with its logbook + customer attribution - the stats/CSV
    feed. [{date, marker, is_s, amount, sym, pre, minutes, lb, cust_tid,
    cust_title}]"""
    out, seen = [], set()
    for tag in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG):
        for lb in records_notes(tag):
            if lb["id"] in seen:
                continue
            seen.add(lb["id"])
            hit = parse_first_link(lb.get("content") or "")
            cust_tid = hit[2] if hit else ""
            cust_title = PERSON_RE.sub("", hit[0]).strip() if hit else ""
            for m in ENTRY_RE.finditer(lb.get("content") or ""):
                segs = [s.strip() for s in m.group(1).split("·")]
                marker = segs[1] if len(segs) > 1 else ""
                amt, sym, pre = _amount_of(segs)
                out.append({
                    "date": segs[0][:10], "marker": marker,
                    "is_s": bool(re.fullmatch(r"S\d+", marker or "")),
                    "amount": amt, "sym": sym, "pre": pre,
                    "minutes": dur_minutes(segs[2]) if len(segs) > 2 else None,
                    "gratis": len(segs) > 3 and is_gratis(segs[3]),
                    "lb": lb, "cust_tid": cust_tid, "cust_title": cust_title,
                })
    return out


def period_kpis(start, end):
    """The dashboard numbers for [start, end] (ISO inclusive, None = open):
    money/hours/rate/sessions, new + returning + active customers, tattoos
    started/finished, top customer. Everything recomputed from the logbook
    entries - there is no ledger to drift."""
    ents = entries_detailed()
    def in_p(d):
        return d and (not start or d >= start) and (not end or d <= end)
    money, mins, sessions = 0.0, 0, 0
    sym, pre = "", False
    per_cust, active, first_s = {}, set(), {}
    for e in ents:
        if e["is_s"] and e["cust_tid"]:
            f = first_s.get(e["cust_tid"])
            if f is None or e["date"] < f:
                first_s[e["cust_tid"]] = e["date"]
    for e in ents:
        if not in_p(e["date"]):
            continue
        if e["amount"] is not None:
            money += e["amount"]
            if not sym and e["sym"]:
                sym, pre = e["sym"], e["pre"]
            if e["cust_tid"]:
                prev = per_cust.get(e["cust_tid"], (0.0, e["cust_title"]))
                per_cust[e["cust_tid"]] = (prev[0] + e["amount"],
                                           e["cust_title"] or prev[1])
        if e["is_s"]:
            sessions += 1
            if not e.get("gratis"):   # gratis hours don't dilute the rate
                mins += e["minutes"] or 0
            if e["cust_tid"]:
                active.add(e["cust_tid"])
    returning = sum(1 for c in active
                    if (first_s.get(c) or "9999") < (start or "0000"))
    new_cust = 0
    seen_c = set()
    for c in records_notes(areas.CUSTOMER_TAG) + records_notes(areas.LEAD_TAG):
        if c["id"] in seen_c:
            continue
        seen_c.add(c["id"])
        if in_p(note_created_date(c)):
            new_cust += 1
    finished = started = 0
    seen_l = set()
    for tag in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG):
        for lb in records_notes(tag):
            if lb["id"] in seen_l:
                continue
            seen_l.add(lb["id"])
            c = lb.get("content") or ""
            mf = re.search(r"Finished (\d{4}-\d{2}-\d{2})", c)
            ms = re.search(r"Started (\d{4}-\d{2}-\d{2})", c)
            if mf and in_p(mf.group(1)):
                finished += 1
            if ms and in_p(ms.group(1)):
                started += 1
    hours = round(mins / 60.0, 1)
    top = max(per_cust.items(), key=lambda kv: kv[1][0]) if per_cust else None
    return {
        "money": money, "sym": sym or "€", "pre": pre, "hours": hours,
        "sessions": sessions, "rate": (money / hours) if hours else None,
        "new_customers": new_cust, "returning": returning,
        "active_customers": len(active), "finished": finished,
        "started": started,
        "top": ({"tid": top[0], "money": top[1][0], "name": top[1][1]}
                if top else None),
    }


def last_duration(content):
    """The most recent S-entry's duration text ('' when none) - the
    Session-done duration default."""
    out = ""
    for segs in _entries(content):
        if (len(segs) > 2 and segs[2] and segs[2] != "-"
                and re.fullmatch(r"S\d+", (segs[1] if len(segs) > 1 else "") or "")):
            out = segs[2]
    return out


def last_setup(content):
    """The most recent 'Setup:' line from the session entries ('' when none)
    - needles/inks/machine memory surfaced before the next session."""
    hits = re.findall(r"^Setup: (.+)$", content or "", re.M)
    return hits[-1].strip() if hits else ""


def quote_remainder(content):
    """Open remainder against the quote as display text ('' when no quote or
    settled) - the Session-done charged default."""
    q = quoted_of(content)
    if q is None:
        return ""
    total, _n, sym, pre = _totals_raw(content)
    rem = q[0] - total
    return _fmt_money(rem, sym or "€", pre) if rem > 0 else ""


def _link_text_pat(target_tid):
    return re.compile(r"\[([^\]]*)\](\(https://ticktick\.com/webapp/#p/\w+/tasks/"
                      + re.escape(target_tid) + r"\))")


def _ripple_task_link_text(target_tid, new_text):
    """Open CRM task titles linking target_tid get their link TEXT swapped
    (links resolve by id - this is display consistency, best-effort)."""
    api = _api()
    pat = _link_text_pat(target_tid)
    pool = cache_store.get("all_tasks") or []
    for t in pool:
        if ((t.get("_projectId") or t.get("projectId")) == areas.CRM_ID
                and t.get("status", 0) == 0
                and f"/tasks/{target_tid})" in (t.get("title") or "")):
            new_t = pat.sub(lambda m: f"[{new_text}]{m.group(2)}",
                            t.get("title") or "")
            if new_t != t.get("title"):
                try:
                    live = api.get_task(areas.CRM_ID, t["id"])
                    api.update_task(t["id"], areas.CRM_ID, current=live,
                                    title=new_t)
                    t["title"] = new_t
                except Exception:
                    pass
    cache_store.set("all_tasks", pool)


def _swap_link_text_in_note(note_tid, target_tid, new_text):
    """Same swap inside a records note's content."""
    try:
        api = _api()
        live = api.get_task(areas.RECORDS_ID, note_tid)
        pat = _link_text_pat(target_tid)
        new_c = pat.sub(lambda m: f"[{new_text}]{m.group(2)}",
                        live.get("content") or "")
        if new_c != (live.get("content") or ""):
            api.update_task(note_tid, areas.RECORDS_ID, current=live,
                            content=new_c)
            _patch_cache(note_tid, content=new_c)
    except Exception:
        pass


def rename_logbook(log_tid, new_tattoo):
    """Rename the tattoo with full ripple: note title, customer bullet,
    every open task's link text."""
    api = _api()
    lb = api.get_task(areas.RECORDS_ID, log_tid)
    old = lb.get("title") or ""
    m = re.match(r"^((?:🎨|🏛️) .*? • )", old)
    new_title = (m.group(1) if m else "🎨 ") + _safe_name(new_tattoo)
    api.update_task(log_tid, areas.RECORDS_ID, current=lb, title=new_title)
    _patch_cache(log_tid, title=new_title)
    _ripple_task_link_text(log_tid, new_title)
    sync_customer_bullet({**lb, "title": new_title})
    return new_title


def rename_customer(cust_tid, new_name):
    """Rename the human with full ripple: customer note, every logbook title
    carrying the old name, the links inside them, open task link texts."""
    api = _api()
    cust = api.get_task(areas.RECORDS_ID, cust_tid)
    old_disp = customer_display(cust)
    new_disp = _safe_name(new_name)
    # Keep whichever person marker the note wears (🎣 lead vs 👤 customer).
    old_mark = "🎣" if (cust.get("title") or "").startswith("🎣") else "👤"
    new_title = f"{old_mark} {new_disp}"
    api.update_task(cust_tid, areas.RECORDS_ID, current=cust, title=new_title)
    _patch_cache(cust_tid, title=new_title)
    for lb in customer_logbooks(cust_tid):
        _swap_link_text_in_note(lb["id"], cust_tid, new_title)
        lt = lb.get("title") or ""
        emo = next((e for e in ("🎨", "🏛️")
                    if old_disp and lt.startswith(f"{e} {old_disp} • ")), None)
        if emo:
            tattoo_part = lt[len(f"{emo} {old_disp} • "):]
            new_lt = f"{emo} {new_disp} • {tattoo_part}"
            try:
                live_lb = api.get_task(areas.RECORDS_ID, lb["id"])
                api.update_task(lb["id"], areas.RECORDS_ID, current=live_lb,
                                title=new_lt)
                _patch_cache(lb["id"], title=new_lt)
                _ripple_task_link_text(lb["id"], new_lt)
                sync_customer_bullet({**live_lb, "title": new_lt})
            except Exception:
                pass
    return new_title


def reopen_logbook(log_pid, log_tid):
    """Touch-up: archived → active again (Finished cleared, retagged, 🏛️
    back to 🎨), with a dated trace line. The next Session-done final
    archives it back."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)
    content = re.sub(r"Finished \S+", "Finished -",
                     lb.get("content") or "", count=1)
    content = _append_under(content, "## Notes",
                            f"- {_today()} - reopened (touch-up)", blank=False)
    _ensure_tag(areas.LOGBOOK_TAG)
    tags = [t for t in (lb.get("tags") or [])
            if str(t).lower() not in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG)] \
        + [areas.LOGBOOK_TAG]
    title = lb.get("title") or ""
    fields = {"content": content, "tags": tags}
    if title.startswith("🏛️ "):
        fields["title"] = "🎨 " + title[len("🏛️ "):]
    api.update_task(log_tid, log_pid, current=lb, **fields)
    _patch_cache(log_tid, **fields)
    if "title" in fields:
        _ripple_task_link_text(log_tid, fields["title"])
    sync_customer_bullet({**lb, "content": content,
                          "title": fields.get("title") or title})
    return {**lb, "content": content, "tags": tags,
            "title": fields.get("title") or title}


def convert_lead(cust):
    """Lead → customer (first booking, or explicit). RMW retag + mirrors;
    the 🎣 marker becomes 👤 and any logbook links follow suit."""
    if not is_lead(cust):
        return cust
    api = _api()
    live = api.get_task(areas.RECORDS_ID, cust["id"])
    tags = [t for t in (live.get("tags") or [])
            if str(t).lower() not in (areas.LEAD_TAG, areas.CUSTOMER_TAG)] \
        + [areas.CUSTOMER_TAG]
    _ensure_tag(areas.CUSTOMER_TAG)
    fields = {"tags": tags}
    title = live.get("title") or ""
    if title.startswith("🎣 "):
        fields["title"] = "👤 " + title[len("🎣 "):]
    api.update_task(cust["id"], areas.RECORDS_ID, current=live, **fields)
    _patch_cache(cust["id"], **fields)
    if "title" in fields:
        for lb in customer_logbooks(cust["id"]):
            try:
                _swap_link_text_in_note(lb["id"], cust["id"], fields["title"])
            except Exception:
                pass
    return {**cust, **fields}


# ── cache mirrors (same pattern as dispatch.py's create path) ───────────────

def _inject_cache(task):
    """Make a fresh records note visible to the pickers before the next sync."""
    try:
        entry = dict(task)
        pid = task.get("projectId") or areas.RECORDS_ID
        entry["_projectId"] = pid
        entry["_projectName"] = areas.records_list_name()
        entry["tags"] = list(dict.fromkeys(
            str(t).lower() for t in (task.get("tags") or [])))
        for key, newest_first in (("all_notes", True), ("all_tasks", False)):
            pool = [t for t in (cache_store.get(key) or [])
                    if t.get("id") != task.get("id")]
            pool.insert(0, entry) if newest_first else pool.append(entry)
            cache_store.set(key, pool)
        pd_key = f"project_data_{pid}"
        pd = cache_store.get(pd_key)
        if pd is not None:
            pd = dict(pd)
            pd["tasks"] = ([t for t in pd.get("tasks", [])
                            if t.get("id") != task.get("id")] + [entry])
            cache_store.set(pd_key, pd)
    except Exception:
        pass   # cache mirrors are best-effort; the hourly sync heals them


def _patch_cache(tid, **fields):
    """Mirror content/tag updates into every cache that holds the note."""
    try:
        if "tags" in fields:
            fields = dict(fields, tags=list(dict.fromkeys(
                str(t).lower() for t in (fields["tags"] or []))))
        for key in ("all_notes", "all_tasks"):
            pool = cache_store.get(key) or []
            hit = False
            for t in pool:
                if t.get("id") == tid:
                    t.update(fields); hit = True
            if hit:
                cache_store.set(key, pool)
        pd_key = f"project_data_{areas.RECORDS_ID}"
        pd = cache_store.get(pd_key)
        if pd is not None:
            pd = dict(pd)
            for t in pd.get("tasks", []):
                if t.get("id") == tid:
                    t.update(fields)
            cache_store.set(pd_key, pd)
    except Exception:
        pass


def records_notes(tag=None):
    """Open cached notes living in the records list, newest first,
    optionally filtered by a (lower-form) tag."""
    rid = areas.RECORDS_ID
    out = []
    for n in cache_store.get("all_notes") or []:
        if (n.get("_projectId") or n.get("projectId")) != rid:
            continue
        if n.get("status", 0) != 0:
            continue
        if tag and tag not in {str(t).lower() for t in (n.get("tags") or [])}:
            continue
        out.append(n)
    return out


# ── content engine (pure string work - unit-testable) ───────────────────────

def _append_under(content, heading, block, blank=True):
    """Insert block at the END of heading's section (before the next '## ').
    blank=True separates from existing body with one empty line (### entries);
    blank=False joins directly (bullet lists). Missing heading → appended at
    the end of the note. Returns the new content."""
    lines = (content or "").split("\n")
    idx = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    ins = block.split("\n")
    if idx is None:
        base = (content or "").rstrip("\n")
        head = (base + "\n\n") if base else ""
        return head + heading + "\n\n" + block + "\n"
    end = idx + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    last = end                       # first line AFTER the real section body
    while last > idx + 1 and not lines[last - 1].strip():
        last -= 1
    body = lines[idx + 1:last]
    sep = [""] if (not body or blank) else []
    tail = lines[end:]
    out = lines[:idx + 1] + body + sep + ins + ([""] if tail else [""])
    return "\n".join(out + tail).rstrip("\n") + "\n"


def _num(s):
    """First number in s as float. EU and US separators both tolerated:
    1.250,50 / 1,250.50 / 250,50 / 1.250 / 250.50 all parse right - with
    both separators present the LAST one is the decimal; a lone separator
    grouping exact 3-digit blocks is a thousands separator."""
    m = re.search(r"-?\d[\d.,]*", s or "")
    if not m:
        return None
    v = m.group(0).rstrip(".,")
    if "," in v and "." in v:
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif "," in v:
        v = (v.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", v)
             else v.replace(",", "."))
    elif "." in v:
        v = v.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", v) else v
    try:
        return float(v)
    except ValueError:
        return None


def _entries(content):
    """Session headers as segment lists: ['2026-07-17', 'S1', '3h', '250€']."""
    return [[s.strip() for s in m.group(1).split("·")]
            for m in ENTRY_RE.finditer(content or "")]


GRATIS_RE = re.compile(r"(?i)^(free|gift|gratis|friend|friends|🖤)$")


def is_gratis(seg):
    """A gratis charge segment ('gift', 'free', …): the session is logged and
    counted, but its hours stay OUT of the money-per-hour math (Vex ruling
    2026-07-20 - a friend tattoo must not drag the rate)."""
    return bool(seg and GRATIS_RE.fullmatch(seg.strip()))


def gratis_count(content):
    """How many sessions in this logbook were on the house."""
    n = 0
    for m in ENTRY_RE.finditer(content or ""):
        segs = [s.strip() for s in m.group(1).split("·")]
        if len(segs) > 3 and is_gratis(segs[3]):
            n += 1
    return n


def lifetime_gratis(cust_tid):
    """On-the-house session count across ALL the customer's logbooks."""
    return sum(gratis_count(lb.get("content") or "")
               for lb in customer_logbooks(cust_tid))


def _totals_raw(content):
    """(total_float, session_count, sym, sym_is_prefix) - the numeric core.
    Money sums segment 4 of every entry (consultation charges count); the
    count = max(highest S-number, number of S-entries) - sessions are
    numbered, so a single backlog-import entry marked S5 honestly reads
    '5 sessions'. Currency symbol: only a SHORT pre/suffix of a clean number
    segment counts ('$300', '250€', '250 EUR') - free text ('cash maybe 50',
    '250,-') falls back to €, never absorbed into the chip."""
    total, n, top, sym, pre = 0.0, 0, 0, "", False
    for segs in _entries(content):
        m_s = re.fullmatch(r"S(\d+)", (segs[1] if len(segs) > 1 else "") or "")
        if m_s:
            n += 1
            top = max(top, int(m_s.group(1)))
        if len(segs) > 3:
            v = _num(segs[3])
            if v is not None:
                total += v
                if not sym:
                    m = re.fullmatch(
                        r"\s*([^\d\s.,\-]{1,3})?\s*[\d.,]+\s*([^\d\s.,\-]{1,3})?\s*",
                        segs[3])
                    if m and (m.group(1) or m.group(2)):
                        sym, pre = ((m.group(1), True) if m.group(1)
                                    else (m.group(2), False))
    return total, max(n, top), sym, pre


def _fmt_money(total, sym, pre):
    num = f"{int(total)}" if total == int(total) else f"{total:.2f}"
    return f"{sym}{num}" if pre else f"{num}{sym}"


def totals(content):
    """(money_str, session_count) recomputed from the session headers."""
    total, n, sym, pre = _totals_raw(content)
    if total == 0 and n == 0:
        return "-", 0
    return _fmt_money(total, sym or "€", pre), n


def quoted_of(content):
    """(value_float, display_str) from the header 'Quoted:' line, or None."""
    head = (content or "").partition("\n## ")[0]
    m = re.search(r"^Quoted: (.+)$", head, re.M)
    if not m:
        return None
    v = _num(m.group(1))
    return (v, m.group(1).strip()) if v is not None else None


def paid_summary(content):
    """The one Paid display everyone renders: '750€ · 1 session', or with a
    quote: '550€ of 800€ · 250€ open · 3 sessions'. Recomputed always."""
    total, n, sym, pre = _totals_raw(content)
    q = quoted_of(content)
    word = _sessions_word(n)
    if q is None:
        if total == 0 and n == 0:
            return f"- · 0 sessions"
        return f"{_fmt_money(total, sym or '€', pre)} · {n} {word}"
    remaining = q[0] - total
    money = _fmt_money(total, sym or "€", pre) if (total or n) else "-"
    open_s = (_fmt_money(remaining, sym or "€", pre) + " open"
              if remaining > 0 else "settled")
    return f"{money} of {q[1]} · {open_s} · {n} {word}"


def _sessions_word(n):
    return "session" if n == 1 else "sessions"


def _set_paid_line(content):
    """Rewrite (or insert) the header 'Paid: …' line from the entries.
    Scoped to the HEADER region (before the first '## ') so a body line that
    happens to start with 'Paid:' is never clobbered; lambda replacement so
    user text (currency residue, backslashes) is never a regex template."""
    line = f"Paid: {paid_summary(content)}"
    head, sep, tail = (content or "").partition("\n## ")
    if re.search(r"^Paid: .*$", head, re.M):
        head = re.sub(r"^Paid: .*$", lambda _m: line, head, count=1, flags=re.M)
    else:
        hl = head.split("\n")
        head = "\n".join(hl[:1] + [line] + hl[1:])
    return head + sep + tail


def next_snum(log_content, log_tid, include_tasks=True):
    """Next session number: max(S in logged entries, S in OPEN calendar tasks
    linking this logbook) + 1 - so a scheduled-but-not-yet-done S1 makes the
    next one S2, and entry-less fresh logbooks start at S1.
    include_tasks=False = entries only - LOGGING history (past sessions) must
    not be renumbered by a task that's merely scheduled (the Bruno case: open
    S1 task pushed the first past-session offer to S2)."""
    top = 0
    for segs in _entries(log_content):
        if len(segs) > 1:
            m = re.fullmatch(r"S(\d+)", segs[1] or "")
            if m:
                top = max(top, int(m.group(1)))
    if not include_tasks:
        return top + 1
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) == areas.CRM_ID
                and t.get("status", 0) == 0
                and f"/tasks/{log_tid})" in (t.get("title") or "")):
            sn = title_snum(t.get("title") or "")
            if sn:
                top = max(top, sn)
    return top + 1


# ── note builders / writers ──────────────────────────────────────────────────

def _seg(v):
    v = (v or "").strip()
    return v if v else "-"


def create_customer(name, phone="", mail="", bday="", insta="", tag=None):
    """New person note in the records list: 👤 customer, or 🎣 lead when
    tag=areas.LEAD_TAG (same note shape, different marker + kanban group;
    convert_lead swaps 🎣 → 👤). Returns the created task."""
    tag = tag or areas.CUSTOMER_TAG
    insta = ("@" + insta.lstrip("@")) if (insta or "").strip() else ""
    content = (f"📞 {_seg(phone)} · ✉️ {_seg(mail)} · 🎂 {_seg(bday)}"
               f" · 📸 {_seg(insta)}\n\n"
               "## Fun facts\n\n## Tattoos\n\n## Notes\n")
    _ensure_tag(tag)
    mark = "🎣" if tag == areas.LEAD_TAG else "👤"
    t = _api().create_task(title=f"{mark} {_safe_name(name)}",
                           project_id=areas.RECORDS_ID, content=content,
                           tags=[tag], kind="NOTE")
    _inject_cache(t)
    return t


CONSULT_PREP_FILE = os.path.expanduser("~/.ticktick_alfred/consult_prep.txt")
CONSULT_PREP_DEFAULT = """- Placement:
- Size:
- Style / references:
- Budget:
- Timeline / availability:
- Health notes (allergies, skin, meds):"""


def _consult_prep_lines():
    """The consult question sheet - user-editable file, default on first use."""
    try:
        with open(CONSULT_PREP_FILE) as f:
            return f.read().strip()
    except OSError:
        try:
            with open(CONSULT_PREP_FILE, "w") as f:
                f.write(CONSULT_PREP_DEFAULT)
        except OSError:
            pass
        return CONSULT_PREP_DEFAULT


def create_logbook(cust, tattoo, started=None, quoted="", prep=False):
    """New 🎨 logbook note for a customer + its bullet in the customer note.
    started overrides the Started date (backlog imports); quoted adds the
    'Quoted:' header line the Paid math renders progress against."""
    cust_pid = cust.get("_projectId") or cust.get("projectId") or areas.RECORDS_ID
    title = f"🎨 {_safe_name(customer_display(cust))} • {_safe_name(tattoo)}"
    q_line = f"Quoted: {quoted.strip()}\n" if (quoted or "").strip() else ""
    prep_block = ""
    if prep:
        prep_block = "## Consult prep\n" + _consult_prep_lines() + "\n\n"
    content = (f"👤 {task_link(cust_pid, cust['id'], (cust.get('title') or '').strip())}"
               f" · Started {started or _today()} · Finished -\n"
               f"Paid: - · 0 sessions\n{q_line}\n"
               f"{prep_block}## Sessions\n\n## Notes\n")
    _ensure_tag(areas.LOGBOOK_TAG)
    t = _api().create_task(title=title, project_id=areas.RECORDS_ID,
                           content=content, tags=[areas.LOGBOOK_TAG], kind="NOTE")
    _inject_cache(t)
    sync_customer_bullet({**t, "content": content})
    return t


def _bullet_for(logbook):
    """The customer note's ## Tattoos line, rebuilt from logbook truth."""
    content = logbook.get("content") or ""
    pid = logbook.get("_projectId") or logbook.get("projectId") or areas.RECORDS_ID
    started  = (re.search(r"Started (\S+)", content) or [None, "-"])[1]
    finished = (re.search(r"Finished (\S+)", content) or [None, "-"])[1]
    link = task_link(pid, logbook["id"], logbook.get("title") or "")
    return (f"- {link} - started {started} · finished {finished}"
            f" · {paid_summary(content)}")


def sync_customer_bullet(logbook):
    """Rebuild this logbook's bullet inside its customer's ## Tattoos list
    (replace-by-link-match; hand-deleted bullet → re-appended)."""
    hit = parse_first_link(logbook.get("content") or "")
    if not hit:
        return
    _, cust_pid, cust_tid = hit
    api = _api()
    cust = api.get_task(cust_pid, cust_tid)
    content = cust.get("content") or ""
    bullet = _bullet_for(logbook)
    needle = f"/tasks/{logbook['id']})"
    lines = content.split("\n")
    replaced = False
    for i, l in enumerate(lines):
        if needle in l and l.lstrip().startswith("-"):
            lines[i] = bullet
            replaced = True
            break
    new = "\n".join(lines) if replaced \
        else _append_under(content, "## Tattoos", bullet, blank=False)
    api.update_task(cust_tid, cust_pid, current=cust, content=new)
    _patch_cache(cust_tid, content=new)


def _fresher_content(log_tid, live_content):
    """Stale-read guard: TickTick reads can lag a just-written update (burst
    imports LOST two logbooks' entries this way, 2026-07-20). The cache is
    patched after every successful write - when the cached copy holds MORE
    session entries than the live read, the cache is the fresher truth."""
    for key in ("all_notes", "all_tasks"):
        for c in cache_store.get(key) or []:
            if c.get("id") == log_tid:
                cc = c.get("content") or ""
                if cc.count("### ") > (live_content or "").count("### "):
                    return cc
                return live_content
    return live_content


def append_session(log_pid, log_tid, marker, duration="", charged="", text="",
                   when=None):
    """Log one entry: append under ## Sessions, recompute Paid, sync the
    customer bullet. marker = 'S<n>' or 'consultation'.
    Returns (updated_content, money_str, session_count, live_logbook_title) -
    the title is the CURRENT one (a rename must not leave the S<n+1> prefill
    holding the stale link text frozen in the completed task's title)."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)   # live - dialogs are slow, cache lags
    day = when or _today()
    entry = f"### {day} · {marker} · {_seg(duration)} · {_seg(charged)}"
    if (text or "").strip():
        entry += f"\n{text.strip()}"
    base = _fresher_content(log_tid, lb.get("content") or "")
    content = _append_under(base, "## Sessions", entry)
    content = _set_paid_line(content)
    # Backdated entry BEFORE the Started date → the Started stamp was wrong
    # (adopted mid-project logbooks get created "today"): pull it back.
    ms = re.search(r"Started (\d{4}-\d{2}-\d{2})", content)
    if ms and day < ms.group(1):
        content = content[:ms.start(1)] + day + content[ms.end(1):]
    api.update_task(log_tid, log_pid, current=lb, content=content)
    # Mirror the LIVE title too: the S<n+1> prefill's [[title]] resolves
    # against the cache - an app-side rename otherwise leaves it literal.
    fields = {"content": content}
    if lb.get("title"):
        fields["title"] = lb["title"]
    _patch_cache(log_tid, **fields)
    sync_customer_bullet({**lb, "content": content})
    money, n = totals(content)
    return content, money, n, (lb.get("title") or "")


def _plant_image_ref(content, heading, occurrence, ref):
    """Insert `ref` at the END of one session block - the block whose ###
    heading line equals `heading` (occurrence-th match; non-S markers like
    no-show can repeat). Pure text-in text-out."""
    lines = (content or "").split("\n")
    hits = [i for i, l in enumerate(lines) if l.strip() == heading.strip()]
    if not hits or occurrence >= len(hits):
        raise ValueError(f"heading not found: {heading}")
    start = hits[occurrence]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j].lstrip()
        if s.startswith("### ") or s.startswith("## "):
            end = j
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1   # hug the entry text, keep the blank gap after the block
    lines.insert(end, ref)
    return "\n".join(lines)


def insert_session_image(log_pid, log_tid, heading, occurrence, ref):
    """Plant an ![image](attid/fname) line under one session heading. The
    attachment must already be uploaded to the note or the ref renders
    broken. Returns updated content."""
    return insert_session_images(log_pid, log_tid,
                                 [(heading, occurrence, ref)])


def insert_session_images(log_pid, log_tid, items):
    """Batch plant: [(heading, occurrence, ref)] in ONE read + ONE write -
    a Finder-roll's worth of photos must not burn a rate-limit window.
    Occurrences stay stable across inserts (refs never add ### lines)."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)
    content = lb.get("content") or ""
    for heading, occurrence, ref in items:
        content = _plant_image_ref(content, heading, occurrence, ref)
    api.update_task(log_tid, log_pid, current=lb, content=content)
    _patch_cache(log_tid, content=content)
    return content


def finish_logbook(log_pid, log_tid, when=None):
    """Stamp Finished, retag logbook → archive, retitle 🎨 → 🏛️ (Vex ruling
    2026-07-20: the archive wears its own emoji), sync the customer bullet.
    when = ISO date for backlog imports (the last session's day); None = today."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)
    content = re.sub(r"Finished \S+", f"Finished {when or _today()}",
                     _fresher_content(log_tid, lb.get("content") or ""), count=1)
    _ensure_tag(areas.ARCHIVE_TAG)
    tags = [t for t in (lb.get("tags") or [])
            if str(t).lower() not in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG)] \
        + [areas.ARCHIVE_TAG]
    title = lb.get("title") or ""
    fields = {"content": content, "tags": tags}
    if title.startswith("🎨 "):
        fields["title"] = "🏛️ " + title[len("🎨 "):]
    api.update_task(log_tid, log_pid, current=lb, **fields)
    _patch_cache(log_tid, **fields)
    if "title" in fields:
        _ripple_task_link_text(log_tid, fields["title"])
    sync_customer_bullet({**lb, "content": content,
                          "title": fields.get("title") or title})


def append_note_line(pid, tid, text, section="## Notes", stamp=True):
    """Free-text line under a section (## Notes timestamped by default;
    ## Fun facts takes bare bullets - facts don't age)."""
    api = _api()
    note = api.get_task(pid, tid)
    if stamp:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- {ts} - {text.strip()}"
    else:
        line = f"- {text.strip()}"
    content = _append_under(note.get("content") or "", section, line,
                            blank=False)
    api.update_task(tid, pid, current=note, content=content)
    _patch_cache(tid, content=content)
    return content
