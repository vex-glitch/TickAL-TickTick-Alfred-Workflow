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
- Session tasks in the CRM calendar list are titled "S<n> <logbook link>" /
  "Consult <logbook link>" - sessiondone parses the link back to its logbook,
  and dispatch suppresses the Prepare follow-up for S2+ titles.

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
SNUM_RE  = re.compile(r"^S(\d+)\s")
ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}[^\n]*)$", re.M)
SESSION_TITLE_RE = re.compile(r"(?:S\d+|Consult)\s")

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
    """True ONLY for tasks the records flow minted: an S<n>/Consult prefix
    AND a PARSEABLE records-list link (the same parse sessiondone unpacks -
    gate and consumer share one shape definition, so nothing that passes here
    can crash the unpack). Prepare follow-ups fail the prefix (their titles
    start 'Prepare for …') - without this shape check they passed every
    session-task gate and sessiondone would complete them and write phantom
    entries into the logbook."""
    t = title or ""
    if not SESSION_TITLE_RE.match(t):
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


def customer_display(cust):
    """'👤 Marko' → 'Marko' (note titles keep the marker, prose drops it)."""
    return re.sub(r"^👤\s*", "", (cust or {}).get("title") or "").strip()


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
    m = re.search(r"\d[\d.,]*", s or "")
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


def totals(content):
    """(money_str, session_count) recomputed from the session headers.
    Money sums segment 4 of every entry (consultation charges count);
    the count counts S-entries only. Currency symbol: only a SHORT pre/suffix
    of a clean number segment counts ('$300', '250€', '250 EUR') - free text
    ('cash maybe 50', '250,-') falls back to €, never absorbed into the chip."""
    total, n, sym, pre = 0.0, 0, "", False
    for segs in _entries(content):
        if len(segs) > 1 and re.fullmatch(r"S\d+", segs[1] or ""):
            n += 1
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
    if total == 0 and n == 0:
        return "-", 0
    num = f"{int(total)}" if total == int(total) else f"{total:.2f}"
    sym = sym or "€"
    return (f"{sym}{num}" if pre else f"{num}{sym}"), n


def _sessions_word(n):
    return "session" if n == 1 else "sessions"


def _set_paid_line(content):
    """Rewrite (or insert) the header 'Paid: …' line from the entries.
    Scoped to the HEADER region (before the first '## ') so a body line that
    happens to start with 'Paid:' is never clobbered; lambda replacement so
    user text (currency residue, backslashes) is never a regex template."""
    money, n = totals(content)
    line = f"Paid: {money} · {n} {_sessions_word(n)}"
    head, sep, tail = (content or "").partition("\n## ")
    if re.search(r"^Paid: .*$", head, re.M):
        head = re.sub(r"^Paid: .*$", lambda _m: line, head, count=1, flags=re.M)
    else:
        hl = head.split("\n")
        head = "\n".join(hl[:1] + [line] + hl[1:])
    return head + sep + tail


def next_snum(log_content, log_tid):
    """Next session number: max(S in logged entries, S in OPEN calendar tasks
    linking this logbook) + 1 - so a scheduled-but-not-yet-done S1 makes the
    next one S2, and entry-less fresh logbooks start at S1."""
    top = 0
    for segs in _entries(log_content):
        if len(segs) > 1:
            m = re.fullmatch(r"S(\d+)", segs[1] or "")
            if m:
                top = max(top, int(m.group(1)))
    for t in cache_store.get("all_tasks") or []:
        if ((t.get("_projectId") or t.get("projectId")) == areas.CRM_ID
                and t.get("status", 0) == 0
                and f"/tasks/{log_tid})" in (t.get("title") or "")):
            m = SNUM_RE.match(t.get("title") or "")
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


# ── note builders / writers ──────────────────────────────────────────────────

def _seg(v):
    v = (v or "").strip()
    return v if v else "-"


def create_customer(name, phone="", mail="", bday=""):
    """New 👤 customer note in the records list. Returns the created task."""
    content = (f"📞 {_seg(phone)} · ✉️ {_seg(mail)} · 🎂 {_seg(bday)}\n\n"
               "## Fun facts\n\n## Tattoos\n\n## Notes\n")
    _ensure_tag(areas.CUSTOMER_TAG)
    t = _api().create_task(title=f"👤 {_safe_name(name)}",
                           project_id=areas.RECORDS_ID, content=content,
                           tags=[areas.CUSTOMER_TAG], kind="NOTE")
    _inject_cache(t)
    return t


def create_logbook(cust, tattoo):
    """New 🎨 logbook note for a customer + its bullet in the customer note.
    Returns the created task."""
    cust_pid = cust.get("_projectId") or cust.get("projectId") or areas.RECORDS_ID
    title = f"🎨 {_safe_name(customer_display(cust))} • {_safe_name(tattoo)}"
    content = (f"👤 {task_link(cust_pid, cust['id'], (cust.get('title') or '').strip())}"
               f" · Started {_today()} · Finished -\n"
               f"Paid: - · 0 sessions\n\n"
               "## Sessions\n\n## Notes\n")
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
    money, n = totals(content)
    link = task_link(pid, logbook["id"], logbook.get("title") or "")
    return (f"- {link} - started {started} · finished {finished}"
            f" · {money} / {n} {_sessions_word(n)}")


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


def append_session(log_pid, log_tid, marker, duration="", charged="", text=""):
    """Log one entry: append under ## Sessions, recompute Paid, sync the
    customer bullet. marker = 'S<n>' or 'consultation'.
    Returns (updated_content, money_str, session_count, live_logbook_title) -
    the title is the CURRENT one (a rename must not leave the S<n+1> prefill
    holding the stale link text frozen in the completed task's title)."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)   # live - dialogs are slow, cache lags
    entry = f"### {_today()} · {marker} · {_seg(duration)} · {_seg(charged)}"
    if (text or "").strip():
        entry += f"\n{text.strip()}"
    content = _append_under(lb.get("content") or "", "## Sessions", entry)
    content = _set_paid_line(content)
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


def finish_logbook(log_pid, log_tid):
    """Stamp Finished, retag logbook → archive, sync the customer bullet."""
    api = _api()
    lb = api.get_task(log_pid, log_tid)
    content = re.sub(r"Finished \S+", f"Finished {_today()}",
                     lb.get("content") or "", count=1)
    _ensure_tag(areas.ARCHIVE_TAG)
    tags = [t for t in (lb.get("tags") or [])
            if str(t).lower() not in (areas.LOGBOOK_TAG, areas.ARCHIVE_TAG)] \
        + [areas.ARCHIVE_TAG]
    api.update_task(log_tid, log_pid, current=lb, content=content, tags=tags)
    _patch_cache(log_tid, content=content, tags=tags)
    sync_customer_bullet({**lb, "content": content})


def append_note_line(pid, tid, text):
    """Timestamped free-text line under ## Notes (customer OR logbook)."""
    api = _api()
    note = api.get_task(pid, tid)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    content = _append_under(note.get("content") or "", "## Notes",
                            f"- {stamp} - {text.strip()}", blank=False)
    api.update_task(tid, pid, current=note, content=content)
    _patch_cache(tid, content=content)
    return content
