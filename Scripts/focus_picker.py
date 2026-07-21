#!/usr/bin/env python3
"""
focus_picker.py - Alfred Script Filter: the standalone Focus action.

ONE script filter running reschedule.py's autocomplete state machine:
valid=False rows advance by rewriting the query bar, a trailing space is a
committed token, only dispatch rows are valid=True, and every row carries the
⌃ back chord to the main menu (mod-level valid=True fires from prompt rows).

  Bar state                     Screen
  ""                            1 · mode - ⏱ timer / 🍅 pomo (default {D}m)
  "timer " | "pomo "            2 · ▶️ start now (unattributed / default) ·
                                     🔗 link a task…
  "{mode} link {frag}"          3 · fuzzy task search (open, non-NOTE, ≤40)
  "{mode} link {title} "        4 · dispatch - start on the task (+ sticky)
  focus file EXISTS             R · status + stop / pause⟷resume / discard
                                    + 🎯 add · 📥 buffer · ➖ remove ·
                                    ✏️ one-liner · 📋 copy · bar
  "add {frag}"   (session+task) A · fuzzy search → ⏎ stage UNDER the focus
                                    task as a subtask (⌥ + open its sticky)
  "remove {frag}" (session+task) RM · open subtasks → ⏎ un-stage (v2 detach
                                    + send home per the origins ledger)
  "tasks {frag}"  (session+task) T · ⏎ on the status row: the staged list -
                                    ⏎✅ complete · ⌥➖ un-stage · ⌘↗️ open
  "link {frag}"  (unattributed) L · fuzzy search → ⏎ fx_link (live attribute)
  "stop "        (unattributed) R2 · log (no task) · link a task…
  "stop link {frag}"            R3 · fuzzy task search
  "stop link {title} "          R4 · dispatch - log onto the picked task
  "stage <pid>:<tid> …"         S · Stage-for-Focus (fired via ET prefill from
                                    ⌘ menus - works in ANY session state):
                                    "" S1 branch picker · "to {frag}" S2 target
                                    search (task → subtask, NOTE → checkbox) ·
                                    "from {t1} | …" S3 multi-pick (tag-picker
                                    pattern, " | " sep) → "Stage N" →
                                    ONE fx_add_multi
  "stage pick {frag}"           S0 · source-task search (the idle menu's 🎯
                                    row / missing handshake) - ⏎ fires
                                    xact:stage_open → the normal S flow

Unmatched trailing-space text falls back to the search screen - no dead ends.
A running TickTick pomo has no focus file → render_pomo; with the sidecar
(~/.ticktick_alfred/run/tickal_pomo.json) it grows the same add/remove/bar rows.

Dispatch args (executed by xact.py): focus_start:: · focus_start:p:t ·
focus_sticky:p:t · pomo:default · pomo_task:p:t:default · pomo_sticky:p:t:default
· focus_stop · focus_stop_as:p:t · focus_pause · focus_resume · focus_discard.
Pomo rows say "+ open", not "for" - TickTick's pomo does NOT bind to the
selection (verified against the app - see xact.pomo_task).
"""
import sys
import os
import json
import traceback

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit_error, run_path
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

try:
    import alfred
    import cache as cache_store
    import xact                       # Scripts sibling: focus state + defaults
    from display import search_key, md_links_display
    from fuzzy import filter_and_score
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)


BACK = {"ctrl": {"valid": True, "arg": "", "subtitle": "🔙 Main menu"}}


def _norm(s):
    return " ".join(search_key(s or "").split()).lower()


def _fmt_hm(secs):
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _open_tasks():
    return [t for t in (cache_store.get("all_tasks") or [])
            if t.get("status", 0) == 0 and t.get("kind") != "NOTE"]


def _task_vars(t):
    pid = t.get("projectId") or t.get("_projectId", "")
    return pid, t["id"], {"task_title": t.get("title", ""), "task_id": t["id"],
                          "task_list_id": pid, "item_type": "task"}


def find_by_title(text):
    tl = _norm(text)
    if not tl:
        return None
    for t in _open_tasks():
        if _norm(t.get("title", "")) == tl:
            return t
    return None


def task_search(prefix, frag):
    """Screens 3/R3: fuzzy rows over open non-NOTE tasks; ⏎ commits the
    normalized title into the bar (trailing space = committed)."""
    hits = filter_and_score(frag, _open_tasks(),
                            key_fn=lambda t: search_key(t.get("title", "")))[:40]
    items = []
    for t in hits:
        nt = " ".join(search_key(t.get("title", "")).split())
        if not nt:
            continue
        items.append(alfred.item(
            uid=f"fp-{t['id']}",
            title=nt,
            subtitle=f"📂 {t.get('_projectName') or 'Inbox'}  ⌃🔙",
            arg="", valid=False,
            autocomplete=f"{prefix}{nt} ",
            mods=BACK,
        ))
    if not items:
        items = [alfred.item(
            uid="fp-nohit",
            title=f'No open task matching "{frag}"' if frag else "Type to search",
            subtitle="⌃🔙",
            valid=False, mods=BACK,
        )]
    return items


# ── Staging / buffer / bar helpers ───────────────────────────────────────────
def _stage_pool():
    """Stage-target pool: open tasks (subtask homes) AND notes (checkbox
    homes - a CTA note can't parent tasks)."""
    pool = list(_open_tasks())
    pool += [n for n in (cache_store.get("all_notes") or [])
             if n.get("status", 0) == 0]
    return pool


def _unpipe(s):
    """S3 uses ' | ' as its commit separator - titles must never carry it."""
    return " ".join((s or "").replace("|", " ").split())


def _find_in_pool(text, pool):
    tl = _norm(_unpipe(text))
    if not tl:
        return None
    for t in pool:
        if _norm(_unpipe(t.get("title", ""))) == tl:
            return t
    return None


def _handshake():
    """pid:tid of the ⌘ row that fired the stage/for prefill - rides
    ~/.ticktick_alfred/run/tickal_stage.txt so the bar shows a clean 'stage '/'for ' query
    instead of id soup."""
    try:
        with open(run_path("tickal_stage.txt")) as f:
            pid, tid = f.read().strip().split(":", 1)
            return pid, tid
    except Exception:
        return "", ""


def _staged_tids(tid):
    """Open SUBTASKS of the task - cache-read (fresh for the workflow's own
    writes via the parent mirror; app-side staging lags one sync). Powers
    the 🎯 already-staged indicator. Completed children left the cache, and
    they left the open-task pools these pickers render - no loss."""
    try:
        return {t["id"] for t in (cache_store.get("all_tasks") or [])
                if t.get("parentId") == tid and t.get("status", 0) == 0}
    except Exception:
        return set()


def _staged_children(tid):
    """Open subtask dicts of the focus task, display order (sortOrder
    ascending) - the remove-from-focus pool."""
    kids = [t for t in (cache_store.get("all_tasks") or [])
            if t.get("parentId") == tid and t.get("status", 0) == 0]
    return sorted(kids, key=lambda t: t.get("sortOrder") or 0)


def _buffer_count():
    try:
        from display import buffer_pairs
        return len(buffer_pairs())   # self-healed count
    except Exception:
        return 0


def _bar_visible():
    try:
        with open(run_path("tickal_focus_bar.json")) as f:
            return bool(json.load(f).get("visible"))
    except (OSError, ValueError):
        return False


def _bulk_add_rows(rest):
    """'add /…' - the bulk scope: a whole tag of a list, a whole
    section, or today's tasks → subtasks in one ⏎. Drill grammar mirrors
    the pickers: list search → ' | ' lock → tag/section search."""
    rest = rest.lstrip()

    def _lists(frag):
        rows = []
        for p in (cache_store.get("projects") or []):
            if p.get("kind") in ("SMART_LIST", "NOTE"):
                continue   # note lists' items can't be sent to a block
            rows.append(p)
        if frag:
            rows = filter_and_score(frag, rows,
                                    key_fn=lambda p: p.get("name", ""))
        return rows[:30]

    for mode, glyph, noun in (("tagged", "🏷", "tag"), ("section", "📑", "section")):
        if rest == mode or rest.startswith(mode + " "):
            body = rest[len(mode):].lstrip()
            if " | " in body or body.endswith(" |"):
                if body.endswith(" |"):        # Alfred strips the trailing
                    body += " "                # space off the autocomplete
                # rpartition: the LAST separator is the lock - list names
                # containing " | " survive
                lname, _, sub = body.rpartition(" | ")
                lname, sub = lname.strip(), sub.strip()
                proj = next((p for p in (cache_store.get("projects") or [])
                             if p.get("name", "").lower() == lname.lower()), None)
                if not proj:
                    return [alfred.item(title=f'List "{lname}" not found',
                                        valid=False, mods=BACK)]
                pid = proj["id"]
                data = cache_store.get(f"project_data_{pid}") or {}
                open_tasks = [t for t in data.get("tasks", [])
                              if t.get("status", 0) == 0 and not t.get("parentId")]
                items = []
                if mode == "tagged":
                    counts = {}
                    for t in open_tasks:
                        for tg in (t.get("tags") or []):
                            counts[tg] = counts.get(tg, 0) + 1
                    for tg in sorted(counts):
                        if sub and sub.lower() not in tg.lower():
                            continue
                        items.append(alfred.item(
                            uid=f"fp-bulk-tag-{tg}",
                            title=f"#{tg}",
                            subtitle=f"{counts[tg]} task{'s' if counts[tg] != 1 else ''} → subtasks  ⌃🔙",
                            arg=f"xact:tag_focus:{pid}:{tg}", valid=True, mods=BACK))
                else:
                    for c in (data.get("columns") or []):
                        if sub and sub.lower() not in c.get("name", "").lower():
                            continue
                        n = sum(1 for t in open_tasks if t.get("columnId") == c.get("id"))
                        items.append(alfred.item(
                            uid=f"fp-bulk-sec-{c.get('id')}",
                            title=c.get("name", "Unnamed"),
                            subtitle=f"{n} task{'s' if n != 1 else ''} → subtasks  ⌃🔙",
                            arg=f"xact:section_focus:{pid}:{c.get('id')}",
                            valid=True, mods=BACK))
                return items or [alfred.item(
                    title=f"No {noun}s in {proj.get('name', 'this list')}",
                    valid=False, mods=BACK)]
            # list step
            rows = [alfred.item(
                uid=f"fp-bulk-list-{p['id']}",
                title=p.get("name", "Untitled"),
                subtitle=f"{glyph} pick a {noun} in this list  ⌃🔙",
                arg="", valid=False,
                autocomplete=f"add /{mode} {p.get('name', '')} | ",
                mods=BACK) for p in _lists(body)]
            return rows or [alfred.item(title=f'No list matching "{body}"',
                                        valid=False, mods=BACK)]

    menu = [
        alfred.item(uid="fp-bulk-tagged", title="🏷 Add tagged",
                    subtitle="Every task of a tag, from a chosen list  ⌃🔙",
                    arg="", valid=False, autocomplete="add /tagged ", mods=BACK),
        alfred.item(uid="fp-bulk-section", title="📑 Add section",
                    subtitle="Every task of a section  ⌃🔙",
                    arg="", valid=False, autocomplete="add /section ", mods=BACK),
        alfred.item(uid="fp-bulk-today", title="📅 Add today",
                    subtitle="Every open task due today → subtasks  ⌃🔙",
                    arg="xact:view_focus:today", valid=True, mods=BACK),
    ]
    if rest:
        menu = [r for r in menu if rest.lower() in r["title"].lower()] or menu
    return menu


def _add_search(frag, focus_tid):
    """Screen A: fuzzy rows that stage straight into the focus task's today
    block on ⏎ (⌥ also opens the focus task's sticky - the list lives there).
    Tasks already staged unchecked show a 🎯 suffix (like the buffer's 🅿️).
    '/' opens the bulk scope (tag / section / today)."""
    if frag.startswith("/"):
        return _bulk_add_rows(frag[1:])
    pool = [t for t in _open_tasks() if t["id"] != focus_tid]
    staged = _staged_tids(focus_tid)
    hits = filter_and_score(frag, pool,
                            key_fn=lambda t: search_key(t.get("title", "")))[:40]
    items = []
    for t in hits:
        pid, tid, tvars = _task_vars(t)
        mark = " 🎯" if tid in staged else ""
        items.append(alfred.item(
            uid=f"fp-add-{tid}",
            title=md_links_display(t.get("title", ""))[:60] + mark,
            subtitle=("Already in focus  ⌃🔙" if mark
                      else "Add to current focus  ⌥🗒  ⌃🔙"),
            arg=f"xact:fx_add:{pid}:{tid}", valid=True, variables=tvars,
            mods={"alt": {"valid": True, "arg": f"xact:fx_add_sticky:{pid}:{tid}",
                          "subtitle": "Add + open the sticky",
                          "variables": tvars}, **BACK},
        ))
    if not items:
        items = [alfred.item(
            uid="fp-add-nohit",
            title=f'No open task matching "{frag}"' if frag else "Type to search",
            subtitle="Add to current focus  ⌃🔙",
            valid=False, mods=BACK)]
    return items


def _subtask_rows(frag, fpid, ftid):
    """Screen T ('tasks …', ⏎ from the status row): the staged list itself.
    ⏎ completes the subtask · ⌥ un-stages it home · ⌘ opens it in the app."""
    kids = _staged_children(ftid)
    total = len(kids)
    if frag:
        kids = filter_and_score(frag, kids,
                                key_fn=lambda t: search_key(t.get("title", "")))
    items = []
    for t in kids[:40]:
        pid = t.get("projectId") or t.get("_projectId", "") or fpid
        items.append(alfred.item(
            uid=f"fp-sub-{t['id']}",
            title=md_links_display(t.get("title", ""))[:60],
            subtitle="⏎✅ done  ⌥➖ un-stage  ⌘↗️ open  ⌃🔙",
            arg=f"xact:fx_tick:{fpid}:{ftid}:{t['id']}", valid=True,
            mods={"alt": {"valid": True,
                          "arg": f"xact:fx_unstage:{pid}:{t['id']}",
                          "subtitle": "Un-stage · send it home"},
                  "cmd": {"valid": True,
                          "arg": f"xact:open_task:{pid}:{t['id']}",
                          "subtitle": "Open in TickTick"},
                  **BACK},
        ))
    if not items:
        items = [alfred.item(
            uid="fp-sub-none",
            title=f'No subtask matching "{frag}"' if frag
                  else "Nothing staged yet",
            subtitle="" if frag else "➕ Add to focus stages subtasks  ⌃🔙",
            valid=False, mods=BACK)]
    elif not frag and total > 40:
        items.append(alfred.item(
            uid="fp-sub-more", title=f"… {total - 40} more",
            subtitle="Type to narrow  ⌃🔙", valid=False, mods=BACK))
    return items


def _remove_search(frag, fpid, ftid):
    """Screen RM ('remove …'): the focus task's open subtasks; ⏎ un-stages
    (v2 detach + send home per the origins ledger)."""
    kids = _staged_children(ftid)
    if frag:
        kids = filter_and_score(frag, kids,
                                key_fn=lambda t: search_key(t.get("title", "")))
    items = []
    for t in kids[:40]:
        pid = t.get("projectId") or t.get("_projectId", "") or fpid
        items.append(alfred.item(
            uid=f"fp-rm-{t['id']}",
            title=md_links_display(t.get("title", ""))[:60],
            subtitle="Un-stage · send it home  ⌃🔙",
            arg=f"xact:fx_unstage:{pid}:{t['id']}", valid=True, mods=BACK))
    if not items:
        items = [alfred.item(
            uid="fp-rm-none",
            title=f'No subtask matching "{frag}"' if frag else "Nothing staged",
            subtitle="⌃🔙", valid=False, mods=BACK)]
    return items


def _link_search(frag):
    """Screen L: fuzzy rows that live-attribute the running session on ⏎."""
    hits = filter_and_score(frag, _open_tasks(),
                            key_fn=lambda t: search_key(t.get("title", "")))[:40]
    items = []
    for t in hits:
        pid, tid, tvars = _task_vars(t)
        items.append(alfred.item(
            uid=f"fp-lk-{tid}",
            title=md_links_display(t.get("title", ""))[:60],
            subtitle="Link the running session  ⌃🔙",
            arg=f"xact:fx_link:{pid}:{tid}", valid=True, variables=tvars,
            mods=BACK))
    if not items:
        items = [alfred.item(
            uid="fp-lk-nohit",
            title=f'No open task matching "{frag}"' if frag else "Type to search",
            subtitle="Link the running session  ⌃🔙",
            valid=False, mods=BACK)]
    return items


def _session_rows(pid, tid):
    """The session toolset shared by the timer and pomo screens:
    add / add-buffer / remove / one-liner / copy / bar visibility."""
    rows = [alfred.item(
        uid="fp-add", title="➕ Add to focus",
        subtitle="Stage task/s as subtasks, / for bulk  ⌃🔙",
        arg="", valid=False, autocomplete="add ", mods=BACK)]
    n = _buffer_count()
    if n:
        rows.append(alfred.item(
            uid="fp-addbuf", title=f"📥 Add buffer ({n})",
            subtitle="In buffer order  ⌃🔙",
            arg="xact:buffer_focus", valid=True, mods=BACK))
    if _staged_children(tid):
        rows.append(alfred.item(
            uid="fp-remove", title="➖ Remove from focus",
            subtitle="Un-stage a subtask, send it home  ⌃🔙",
            arg="", valid=False, autocomplete="remove ", mods=BACK))
    rows.append(alfred.item(
        uid="fp-oneliner", title="✏️ One-liner",
        subtitle="A '- text' bullet onto the note  ⌃🔙",
        arg="xact:fx_oneliner", valid=True, mods=BACK))
    rows.append(alfred.item(
        uid="fp-copy", title="📋 Copy as bullet list",
        subtitle="Open subtasks → clipboard, paste-ready  ⌃🔙",
        arg=f"xact:fx_copy:{pid}:{tid}", valid=True, mods=BACK))
    if _bar_visible():
        rows.append(alfred.item(
            uid="fp-bar", title="🫥 Hide bar",
            subtitle="The session keeps running  ⌃🔙",
            arg="xact:bar_hide", valid=True, mods=BACK))
    else:
        rows.append(alfred.item(
            uid="fp-bar", title="👁 Show bar",
            subtitle="Bring back the pill  ⌃🔙",
            arg="xact:bar_show", valid=True, mods=BACK))
    return rows


# ── Running-timer screens (R/R2/R3/R4) ───────────────────────────────────────
def render_running(st, raw):
    secs   = xact.focus_elapsed(st)
    hm     = _fmt_hm(secs)
    mins   = max(1, int(secs // 60))
    paused = bool(st.get("paused_at"))
    attributed = bool(st.get("tid"))

    # Add-twist: stage a searched task under the focus task
    if attributed and raw.startswith("add"):
        frag = raw[4:] if len(raw) > 3 else ""
        print(alfred.output(_add_search(frag.strip(), st.get("tid")),
                            skipknowledge=True))
        return
    # Remove-twist: un-stage a subtask
    if attributed and raw.startswith("remove"):
        frag = raw[7:] if len(raw) > 6 else ""
        print(alfred.output(_remove_search(frag.strip(), st.get("pid", ""),
                                           st.get("tid")),
                            skipknowledge=True))
        return
    # Subtask-twist (⏎ on the status row): the staged list, act per row
    if attributed and raw.startswith("tasks"):
        frag = raw[6:] if len(raw) > 5 else ""
        print(alfred.output(_subtask_rows(frag.strip(), st.get("pid", ""),
                                          st.get("tid")),
                            skipknowledge=True))
        return
    # Live link-twist (unattributed, distinct from the stop-twist)
    if not attributed and raw.startswith("link"):
        frag = raw[5:] if len(raw) > 4 else ""
        print(alfred.output(_link_search(frag.strip()), skipknowledge=True))
        return

    # Unattributed stop-twist: "stop " → R2, "stop link …" → R3/R4
    if not attributed and raw.startswith("stop"):
        after = raw[4:]
        if after.startswith(" link"):
            frag = after[6:] if len(after) > 5 else ""
            if frag.endswith(" ") and frag.strip():
                t = find_by_title(frag)
                if t:
                    pid, tid, tvars = _task_vars(t)
                    print(alfred.output([alfred.item(
                        uid="fp-stopas",
                        title=f"⏹️ Log {mins}m on {t.get('title', '')[:50]}",
                        subtitle="Stop and record on this task  ⌃🔙",
                        arg=f"xact:focus_stop_as:{pid}:{tid}",
                        valid=True, variables=tvars, mods=BACK,
                    )], skipknowledge=True))
                    return
            print(alfred.output(task_search("stop link ", frag.strip()),
                                skipknowledge=True))
            return
        print(alfred.output([
            alfred.item(uid="fp-stop-notask", title=f"⏹️ Log {mins}m (no task)",
                        subtitle="Unattributed record  ⌃🔙",
                        arg="xact:focus_stop", valid=True, mods=BACK),
            alfred.item(uid="fp-stop-link", title="🔗 Link a task",
                        subtitle="Attribute this time  ⌃🔙",
                        arg="", valid=False, autocomplete="stop link ", mods=BACK),
        ], skipknowledge=True))
        return

    fname = md_links_display(st.get("title", "Focus"))
    items = [alfred.item(
        uid="fp-status",
        title=(f"⏸️ Paused on {fname} - {hm}" if paused
               else f"🎯 Focusing on {fname} - {hm}"),
        subtitle=("Timer paused" if paused else "Timer active")
                 + ("  |  ⏎⤵️ subtasks  ⌃🔙" if attributed
                    else " (no task)  ⌃🔙"),
        valid=False, autocomplete="tasks " if attributed else None,
        mods=BACK,
    )]
    if attributed:
        items.append(alfred.item(
            uid="fp-stop", title=f"⏹️ Stop & log {mins}m",
            subtitle="Finish and record focus  ⌃🔙",
            arg="xact:focus_stop", valid=True, mods=BACK))
    else:
        items.append(alfred.item(
            uid="fp-stop", title="⏹️ Stop…",
            subtitle="Log it, or link a task  ⌃🔙",
            arg="", valid=False, autocomplete="stop ", mods=BACK))
    if paused:
        items.append(alfred.item(
            uid="fp-resume", title="▶️ Resume",
            subtitle="Continue the clock  ⌃🔙",
            arg="xact:focus_resume", valid=True, mods=BACK))
    else:
        items.append(alfred.item(
            uid="fp-pause", title="⏸️ Pause",
            subtitle="Freeze the clock  ⌃🔙",
            arg="xact:focus_pause", valid=True, mods=BACK))
    # Session toolset (attributed: full set; unattributed: link + bar)
    if attributed:
        items.extend(_session_rows(st.get("pid", ""), st.get("tid", "")))
    else:
        items.append(alfred.item(
            uid="fp-live-link", title="🔗 Link a task",
            subtitle="Attribute the running session  ⌃🔙",
            arg="", valid=False, autocomplete="link ", mods=BACK))
        if _bar_visible():
            items.append(alfred.item(
                uid="fp-bar", title="🫥 Hide bar",
                subtitle="The session keeps running  ⌃🔙",
                arg="xact:bar_hide", valid=True, mods=BACK))
        else:
            items.append(alfred.item(
                uid="fp-bar", title="👁 Show bar",
                subtitle="Bring back the pill  ⌃🔙",
                arg="xact:bar_show", valid=True, mods=BACK))
    items.append(alfred.item(
        uid="fp-discard", title="🚮 Discard",
        subtitle="Stop without logging anything  ⌃🔙",
        arg="xact:focus_discard", valid=True, mods=BACK))
    # Typing filters the toolset - twists were handled above.
    frag = raw.strip().lower()
    if frag:
        hits = [r for r in items if frag in r["title"].lower()]
        items = hits or items
    print(alfred.output(items, skipknowledge=True))


# ── Idle screens (1/2/3/4) ────────────────────────────────────────────────────
def render_idle(raw):
    d = xact._pomo_default()
    mode = None
    if raw.startswith("timer"):
        mode, rest = "timer", raw[5:]
    elif raw.startswith("pomo"):
        mode, rest = "pomo", raw[4:]

    if mode and (rest == "" or rest.startswith(" ")):
        rest = rest[1:] if rest.startswith(" ") else rest

        # ── Screens 3/4: link a task ─────────────────────────────────────────
        if rest.startswith("link"):
            frag = rest[5:] if len(rest) > 4 else ""
            if frag.endswith(" ") and frag.strip():
                t = find_by_title(frag)
                if t:
                    pid, tid, tvars = _task_vars(t)
                    name = t.get("title", "")[:50]
                    if mode == "timer":
                        items = [
                            alfred.item(uid="fp-go",
                                        title=f"▶️ Start timer for {name}",
                                        subtitle="Focus bar follows  ⌃🔙",
                                        arg=f"xact:focus_start:{pid}:{tid}",
                                        valid=True, variables=tvars, mods=BACK),
                            alfred.item(uid="fp-go-sticky",
                                        title="🗒️ Start + sticky note",
                                        subtitle="Timer + desktop sticky  ⌃🔙",
                                        arg=f"xact:focus_sticky:{pid}:{tid}",
                                        valid=True, variables=tvars, mods=BACK),
                        ]
                    else:
                        items = [
                            alfred.item(uid="fp-go",
                                        title=f"▶️ Start {d}m pomo + open {name}",
                                        subtitle="Focus bar follows  ⌃🔙",
                                        arg=f"xact:pomo_task:{pid}:{tid}:default",
                                        valid=True, variables=tvars, mods=BACK),
                            alfred.item(uid="fp-go-sticky",
                                        title=f"🗒️ Sticky note + {d}m pomo",
                                        subtitle="Desktop sticky first  ⌃🔙",
                                        arg=f"xact:pomo_sticky:{pid}:{tid}:default",
                                        valid=True, variables=tvars, mods=BACK),
                        ]
                    print(alfred.output(items, skipknowledge=True))
                    return
            print(alfred.output(task_search(f"{mode} link ", frag.strip()),
                                skipknowledge=True))
            return

        # ── Screen 2: start now / link ───────────────────────────────────────
        if mode == "timer":
            rows = [
                alfred.item(uid="fp-start", title="▶️ Start timer",
                            subtitle="No task yet  ⌃🔙",
                            arg="xact:focus_start::", valid=True, mods=BACK),
                alfred.item(uid="fp-link", title="🔗 Link a task",
                            subtitle="Start the timer on a task  ⌃🔙",
                            arg="", valid=False, autocomplete="timer link ", mods=BACK),
            ]
        else:
            rows = [
                alfred.item(uid="fp-start", title="▶️ Start Pomo",
                            subtitle=f"{d}m  ⌃🔙",
                            arg="xact:pomo:default", valid=True, mods=BACK),
                alfred.item(uid="fp-link", title="🔗 Link a task",
                            subtitle="Open task and start pomo  ⌃🔙",
                            arg="", valid=False, autocomplete="pomo link ", mods=BACK),
            ]
        frag = rest.strip().lower()
        hits = [r for r in rows if not frag or frag in r["title"].lower()]
        print(alfred.output(hits or rows, skipknowledge=True))
        return

    # ── Screen 1: mode picker ────────────────────────────────────────────────
    rows = [
        alfred.item(uid="fp-timer", title="⏱️ Start timer",
                    subtitle="Link a task, open focus bar, log, pause...",
                    arg="", valid=False, autocomplete="timer ", mods=BACK),
        alfred.item(uid="fp-pomo", title="🍅 Start Pomodoro",
                    subtitle="Link a task, open focus bar, log, pause...",
                    arg="", valid=False, autocomplete="pomo ", mods=BACK),
        # The ⌘-menu stage flow, reachable without a task -
        # xact:stage_pick clears any leftover handshake, then asks WHICH task.
        alfred.item(uid="fp-stage", title="🎯 Merge/Stage for Focus",
                    subtitle="Stage a task under another task, or into a note…",
                    arg="xact:stage_pick", valid=True, mods=BACK),
    ]
    frag = raw.strip().lower()
    hits = [r for r in rows if not frag or frag in r["title"].lower()]
    print(alfred.output(hits or rows, skipknowledge=True))


def render_pomo(state, remaining, raw):
    """TickTick's OWN pomodoro is running (no focus file): status + the
    controls the app exposes programmatically - pause⟷resume toggle; End /
    Abandon only exist in the Pomodoro view. With the sidecar the
    session is task-bound → same add/sweep/bar toolset as the timer."""
    paused = state.startswith("pomodoroPaused")
    m = remaining // 60
    ps = xact._pomo_sidecar()
    bound = ps if (ps and ps.get("tid")) else None

    # Twists (mirror render_running)
    if bound and raw.startswith("add"):
        frag = raw[4:] if len(raw) > 3 else ""
        print(alfred.output(_add_search(frag.strip(), bound["tid"]),
                            skipknowledge=True))
        return
    if bound and raw.startswith("remove"):
        frag = raw[7:] if len(raw) > 6 else ""
        print(alfred.output(_remove_search(frag.strip(),
                                           bound.get("pid", ""), bound["tid"]),
                            skipknowledge=True))
        return
    if bound and raw.startswith("tasks"):
        frag = raw[6:] if len(raw) > 5 else ""
        print(alfred.output(_subtask_rows(frag.strip(),
                                          bound.get("pid", ""), bound["tid"]),
                            skipknowledge=True))
        return
    if not bound and raw.startswith("link"):
        frag = raw[5:] if len(raw) > 4 else ""
        print(alfred.output(_link_search(frag.strip()), skipknowledge=True))
        return

    tname = md_links_display(bound.get("title", ""))[:36] if bound else ""
    rows = [
        alfred.item(uid="fp-pomo-status",
                    title=(f"🍅 Focusing on {tname} - {m}m left" if bound
                           else f"🍅 Pomodoro - {m}m left"),
                    subtitle=("Pomodoro paused" if paused else "Pomodoro active")
                             + ("  |  ⏎⤵️ subtasks  ⌃🔙" if bound else "  ⌃🔙"),
                    valid=False, autocomplete="tasks " if bound else None,
                    mods=BACK),
        alfred.item(uid="fp-pomo-toggle",
                    title="▶️ Resume" if paused else "⏸️ Pause",
                    subtitle=("Continue the clock" if paused else "Freeze the clock") + "  ⌃🔙",
                    arg="xact:pomo_toggle", valid=True, mods=BACK),
        alfred.item(uid="fp-pomo-end",
                    title="🚮 End pomo",
                    subtitle="End it now  ⌃🔙",
                    arg="xact:pomo_abandon", valid=True, mods=BACK),
        alfred.item(uid="fp-pomo-view",
                    title="↗️ Pomodoro view",
                    subtitle="Open in TickTick  ⌃🔙",
                    arg="xact:view_open:pomo", valid=True, mods=BACK),
    ]
    if bound:
        rows[1:1] = _session_rows(bound.get("pid", ""), bound["tid"])
    else:
        rows.insert(1, alfred.item(
            uid="fp-live-link", title="🔗 Link a task",
            subtitle="Attribute the running session  ⌃🔙",
            arg="", valid=False, autocomplete="link ", mods=BACK))
    frag = raw.strip().lower()
    hits = [r for r in rows if not frag or frag in r["title"].lower()]
    print(alfred.output(hits or rows, skipknowledge=True))


# ── Stage-for-Focus screens (S1/S2/S3) ───────────────────────────────────────
def render_stage(raw):
    """Fired externally: ET Focus prefilled "stage <pid>:<tid> …" from a
    task's ⌘ menu (xact.stage_open). Source task = the menu's task. Two
    directions: stage IT into another task/note ("to"), or multi-pick other
    tasks INTO it ("from", tag-picker accumulate pattern, " | " separator)."""
    import re
    import base64
    m = re.match(r'stage (\S+):([a-f0-9]{24})($| .*$)', raw)
    if m:   # legacy explicit-id form (sims/back-compat)
        spid, stid = m.group(1), m.group(2)
        rest = m.group(3).lstrip(" ")
    else:   # normal path: ids ride the handshake file, the bar stays clean
        spid, stid = _handshake()
        rest = raw[6:].lstrip(" ") if len(raw) > 5 else ""
    # S0 - no handshake (the Focus menu's 🎯 row clears it via
    # xact:stage_pick before opening this screen): pick WHICH task to stage
    # first. ⏎ routes through xact:stage_open (fresh handshake, re-fires
    # "stage ") - from there on it's the exact ⌘-menu flow.
    if not stid:
        frag = rest.strip()
        hits = filter_and_score(frag, _open_tasks(),
                                key_fn=lambda t: search_key(t.get("title", "")))[:40]
        items = []
        for t in hits:
            tpid = t.get("projectId") or t.get("_projectId", "")
            items.append(alfred.item(
                uid=f"fp-st-src-{t['id']}",
                title=md_links_display(t.get("title", ""))[:60],
                subtitle="Stage this task  ⌃🔙",
                arg=f"xact:stage_open:{tpid}:{t['id']}",
                valid=True, mods=BACK))
        if not items:
            items = [alfred.item(
                uid="fp-st-nosrc",
                title=f'No open task matching "{frag}"' if frag
                      else "Type to pick the task to stage",
                subtitle="⌃🔙", valid=False, mods=BACK)]
        print(alfred.output(items, skipknowledge=True))
        return
    src = cache_store.find_task(stid) or {}
    sname = md_links_display(src.get("title") or "this task")[:40]
    prefix = "stage "

    # S2 - "to <frag>": pick the TARGET whose block receives the source
    if rest.startswith("to ") or rest == "to":
        frag = rest[3:].strip()
        pool = [t for t in _stage_pool() if t["id"] != stid]
        hits = filter_and_score(frag, pool,
                                key_fn=lambda t: search_key(t.get("title", "")))[:40]
        items = []
        for t in hits:
            tpid = t.get("projectId") or t.get("_projectId", "")
            kind = "🗒" if t.get("kind") == "NOTE" else "📋"
            items.append(alfred.item(
                uid=f"fp-st-{t['id']}",
                title=f"{kind} {md_links_display(t.get('title', ''))[:56]}",
                subtitle="Into this task's block  ⌃🔙",
                arg=f"xact:fx_add_to:{tpid}:{t['id']}:{spid}:{stid}",
                valid=True, mods=BACK))
        if not items:
            items = [alfred.item(
                uid="fp-st-nohit",
                title=f'No task or note matching "{frag}"' if frag
                      else "Type to search tasks and notes",
                subtitle="⌃🔙",
                valid=False, mods=BACK)]
        print(alfred.output(items, skipknowledge=True))
        return

    # S3 - "from <t1> | <t2> | frag": accumulate picks INTO the source task
    if rest.startswith("from ") or rest == "from":
        body = rest[5:] if len(rest) > 4 else ""
        segments = body.split(" | ")
        committed, frag = segments[:-1], segments[-1].strip()
        committed = [c.strip() for c in committed if c.strip()]
        pool = [t for t in _open_tasks() if t["id"] != stid]
        items = []
        if committed:
            resolved, missing = [], []
            for c in committed:
                t = _find_in_pool(c, pool)
                if t:
                    tpid = t.get("projectId") or t.get("_projectId", "")
                    resolved.append([tpid, t["id"], t.get("title", "")])
                else:
                    missing.append(c)
            if resolved:
                payload = base64.b64encode(json.dumps(
                    {"tpid": spid, "ttid": stid,
                     "items": resolved}).encode()).decode()
                items.append(alfred.item(
                    uid="fp-st-confirm",
                    title=f"✅ Stage {len(resolved)} under {sname}",
                    subtitle=" · ".join(r[2][:24] for r in resolved)[:96],
                    arg=f"xact:fx_add_multi:{payload}", valid=True, mods=BACK))
            if missing:
                items.append(alfred.item(
                    uid="fp-st-missing",
                    title=f"⚠️ Not found: {', '.join(missing)[:60]}",
                    subtitle="Keep typing or confirm the rest",
                    valid=False, mods=BACK))
        picked_ids = set()
        for c in committed:
            t = _find_in_pool(c, pool)
            if t:
                picked_ids.add(t["id"])
        staged = _staged_tids(stid)
        hits = filter_and_score(frag, [t for t in pool if t["id"] not in picked_ids],
                                key_fn=lambda t: search_key(t.get("title", "")))[:30]
        for t in hits:
            nt = _unpipe(search_key(t.get("title", "")))
            if not nt:
                continue
            mark = " 🎯" if t["id"] in staged else ""
            items.append(alfred.item(
                uid=f"fp-st-pick-{t['id']}",
                title=nt[:60] + mark,
                subtitle=("Already in focus  ⌃🔙" if mark
                          else "Queue, confirm on the ✅ row  ⌃🔙"),
                arg="", valid=False,
                autocomplete=f"{prefix}from {' | '.join(committed + [nt])} | ",
                mods=BACK))
        if not items:
            items = [alfred.item(
                uid="fp-st-nohit",
                title=f'No open task matching "{frag}"' if frag
                      else "Type to search",
                subtitle="⌃🔙",
                valid=False, mods=BACK)]
        print(alfred.output(items, skipknowledge=True))
        return

    # S1 - branch picker
    items = [
        alfred.item(uid="fp-st-to",
                    title="⤴️ Out",
                    subtitle="Make this task a subtask elsewhere (note = checkbox)",
                    arg="", valid=False, autocomplete=f"{prefix}to ", mods=BACK),
        alfred.item(uid="fp-st-from",
                    title="⤵️ In",
                    subtitle="Make other tasks subtasks of this task",
                    arg="", valid=False, autocomplete=f"{prefix}from ", mods=BACK),
    ]
    cur = xact._current_focus_task()
    if cur and cur[1] != stid:
        items.append(alfred.item(
            uid="fp-st-curfocus",
            title=f"🎯 Add to current focus ({cur[2][:30]})",
            subtitle="Straight into the running session  ⌃🔙",
            arg=f"xact:fx_add:{spid}:{stid}", valid=True, mods=BACK))
    print(alfred.output(items, skipknowledge=True))


# ── Task-bound start flow ("for" - the ⌘ 🎯 Focus row) ───────────────────────
def render_for(raw):
    """Fired via ET prefill "for " with the task in the handshake file. One
    🎯 Focus row replaces the old Start-focus / sticky+timer / Start-pomo
    trio: ⏱ timer or 🍅 pomodoro, each plain or with the sticky."""
    pid, tid = _handshake()
    src = cache_store.find_task(tid) or {}
    name = md_links_display(src.get("title") or "this task")[:40]
    if not tid:
        print(alfred.output([alfred.item(
            uid="fp-for-bad", title="Focus needs a task",
            subtitle="Use 🎯 Focus from a task's ⌘ menu  |  ⌃ 🔙",
            valid=False, mods=BACK)], skipknowledge=True))
        return
    rest = raw[4:].lstrip(" ") if len(raw) > 3 else ""
    d = xact._pomo_default()
    tvars = {"task_title": src.get("title", ""), "task_id": tid,
             "task_list_id": pid, "item_type": "task"}
    if rest.startswith("timer"):
        rows = [
            alfred.item(uid="fp-for-t", title=f"▶️ Start timer for {name}",
                        subtitle="Focus bar follows  ⌃🔙",
                        arg=f"xact:focus_start:{pid}:{tid}", valid=True,
                        variables=tvars, mods=BACK),
            alfred.item(uid="fp-for-ts", title="🗒️ Start + sticky note",
                        subtitle="Timer + desktop sticky  ⌃🔙",
                        arg=f"xact:focus_sticky:{pid}:{tid}", valid=True,
                        variables=tvars, mods=BACK),
        ]
    elif rest.startswith("pomo"):
        rows = [
            alfred.item(uid="fp-for-p", title=f"▶️ Start {d}m pomo + open {name}",
                        subtitle="Focus bar follows  ⌃🔙",
                        arg=f"xact:pomo_task:{pid}:{tid}:default", valid=True,
                        variables=tvars, mods=BACK),
            alfred.item(uid="fp-for-ps", title=f"🗒️ Sticky note + {d}m pomo",
                        subtitle="Desktop sticky first  ⌃🔙",
                        arg=f"xact:pomo_sticky:{pid}:{tid}:default", valid=True,
                        variables=tvars, mods=BACK),
        ]
    else:
        rows = [
            alfred.item(uid="fp-for-timer", title="⏱️ Start timer",
                        subtitle="Link a task, open focus bar, log, pause...",
                        arg="", valid=False, autocomplete="for timer ", mods=BACK),
            alfred.item(uid="fp-for-pomo", title="🍅 Start Pomodoro",
                        subtitle="Link a task, open focus bar, log, pause...",
                        arg="", valid=False, autocomplete="for pomo ", mods=BACK),
        ]
        frag = rest.strip().lower()
        rows = [r for r in rows if not frag or frag in r["title"].lower()] or rows
    print(alfred.output(rows, skipknowledge=True))


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        # Stage/for modes ride in via ET prefill and work in ANY session state.
        if raw.startswith("stage"):
            render_stage(raw)
            return
        if raw.startswith("for"):
            render_for(raw)
            return
        st = xact._focus_state()
        if st:
            render_running(st, raw)
            return
        pstate, premaining = xact._pomo_app_state()
        if pstate != "idle":
            render_pomo(pstate, premaining, raw)
        else:
            render_idle(raw)
    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
