#!/usr/bin/env python3
"""
actions.py - Alfred Script Filter (⌘ Actions menu for the selected item).

Reached by pressing ⌘ on a row in any search/browse view. The row's
variables (task_id / task_list_id / task_title, and item_type) ride in via
env, so every action carries context onward through the conditional →
Call-External-Trigger chain (no temp file, no osascript).

Row order matches the conditional:
  open · browse · schedule · tags · priority · move · copy · complete ·
  rename · delete · back

Args:
  • terminal actions carry the full dispatch arg, matched by regex in the
    conditional (open: / copy: / complete:) and forwarded to modOpen /
    modURL / modComplete as the argument.
  • picker actions emit a bare keyword (schedule, tags, …) matched "is equal
    to" and routed to the existing attribute / drill triggers, which read the
    task context from the variables that flow with them.
"""
import sys
import os
import json
import base64
import traceback



# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR, run_path
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

# actions.py's historic error-row shape (no uid) - kept byte-identical
def emit_error(m): emit([{"title": "TickTick Error", "subtitle": m, "valid": False}])

try:
    import alfred
    import fuzzy as fuzz
    import cache as cache_store
    import links as links_util
    import areas
    from display import (fmt_date, fmt_tags, join_breadcrumb, list_name_for,
                         tag_link, md_links_display)
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)

PRIO = {0: "⚫️ No priority", 1: "🟡 Low", 3: "🟠 Medium", 5: "🔴 High"}


def fx_session():
    """Running-session probe for the ⌘ rows:
    ("task", pid, tid, title) task-bound · ("bare",) running-unattributed ·
    None idle. Cheap path first - the pomo defaults read only happens when a
    sidecar file actually exists / no timer file."""
    try:
        with open(run_path("tickal_focus.json")) as f:
            st = json.load(f)
        if st.get("tid"):
            return ("task", st.get("pid", ""), st["tid"], st.get("title", ""))
        return ("bare",)
    except (OSError, ValueError):
        pass
    try:
        from xact import _pomo_sidecar, _pomo_app_state   # Scripts sibling
        ps = _pomo_sidecar()
        if ps and ps.get("tid"):
            return ("task", ps.get("pid", ""), ps["tid"], ps.get("title", ""))
        if _pomo_app_state()[0] != "idle":
            return ("bare",)
    except Exception:
        pass
    return None


def find_task(tid):
    for t in (cache_store.get("all_tasks") or []):
        if t.get("id") == tid:
            return t
    for n in (cache_store.get("all_notes") or []):
        if n.get("id") == tid:
            return n
    return None


def _is_top_level_tag(tag):
    """True when the tag is a legal nest target: ITS OWN tree entry has no
    parent (TickTick nests one level). Membership in the top-level label set
    is NOT enough - emoji-blind keys collide, a child '🔥X' next to a
    top-level 'X' passed (real collision seen live). No tree cached
    (no v2 token) → False - creating tags needs the token anyway."""
    try:
        from display import tag_match_key
        tree = cache_store.get("tags_tree") or []
        exact = (tag or "").strip()
        # exact label/name first - emoji-blind keys collide across REAL
        # sibling tags (📓Logbook top-level vs 🔥Logbook child)
        for t in tree:
            if exact == t.get("label") or exact.lower() == (t.get("name") or ""):
                return not t.get("parent")
        key = tag_match_key(tag)
        hits = [t for t in tree
                if tag_match_key(t.get("label") or t.get("name") or "") == key]
        if len(hits) == 1:
            return not hits[0].get("parent")
        return False   # unknown or ambiguous → no nest row
    except Exception:
        return False


def section_name(task):
    cid = task.get("columnId")
    if not cid:
        return task.get("_columnName", "") or ""
    pid = task.get("_projectId") or task.get("projectId", "")
    pd = cache_store.get(f"project_data_{pid}") if pid else None
    if pd:
        for col in pd.get("columns", []):
            if col.get("id") == cid:
                nm = col.get("name", "").strip()
                return "" if nm.lower() == "not sectioned" else nm
    return ""


# Back is ⌃ everywhere - stamp the ⌃ back-mod on every emitted row
# (mod-level valid=True lets it fire even from invalid prompt/hint rows).
_orig_output = alfred.output
def _output_backstamped(items, **kw):
    for _it in items:
        _it.setdefault("mods", {}).setdefault("ctrl", {"valid": True, "arg": "back", "subtitle": "🔙 Back to search"})
    return _orig_output(items, **kw)
alfred.output = _output_backstamped


def main():
    pid    = os.environ.get("task_list_id", "") or os.environ.get("list_id", "")
    tid    = os.environ.get("task_id", "")
    sid    = os.environ.get("section_id", "")
    title  = os.environ.get("task_title", "task")
    itype  = os.environ.get("item_type", "") or "task"  # act-again re-entry has
    query  = sys.argv[1] if len(sys.argv) > 1 else ""    # no env; only tasks reopen

    # 🗓 View rows: smart-list rows in search get a small ⌘ menu -
    # the headline act is sending the whole view to the focus, in view order.
    if itype == "view":
        try:
            vkey  = os.environ.get("view_key", "")
            vname = os.environ.get("view_name", "") or "view"
            vurl  = os.environ.get("view_url", "")
            vvars = {"item_type": "view", "view_key": vkey, "view_name": vname,
                     "view_url": vurl, "task_id": "", "task_list_id": "",
                     "task_title": vname}
            sendable = vkey in ("today", "tomorrow", "next7", "inbox")
            rows = [
                ("🎯 Send all to focus", f"Every {vname} task → the focus task's today block",
                 f"xact:view_focus:{vkey}", "focus send all stage checkbox",
                 sendable and (fx_session() or ("",))[0] == "task"),
                ("↗️ Open in TickTick",  f"Open {vname}",
                 f"open:{vurl}",          "open app view",          bool(vurl)),
                # Views without a working deep link (Summary) open via the
                # app's List menu - the xact:view_open System-Events click.
                # Won't Do has NEITHER route (no deep link, no List-menu
                # item) - Alfred-inline only, no Open row.
                ("↗️ Open in TickTick",  f"Open {vname}",
                 f"xact:view_open:{vkey}", "open app view",
                 not vurl and vkey in ("summary", "habits", "matrix", "pomo")),
                ("🔙 Go back",           "Back to search", "back",  "back", True),
            ]
            items = [alfred.item(title=t, subtitle=s, arg=a, variables=vvars,
                                 match=f"{kw} {t}")
                     for (t, s, a, kw, show) in rows if show]
            if query:
                items = fuzz.filter_and_score(query, items,
                                              key_fn=lambda x: x.get("match", x["title"]))
            if not items:
                items = [alfred.item(title=f'No action matching "{query}"', valid=False)]
            print(alfred.output(items, skipknowledge=True))
        except Exception as e:
            emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")
        return

    # 🏷️ Tag rows: tags aren't tasks - short-circuit to the tag menu
    # BEFORE the temp-file context recovery below, which would poison pid/tid
    # with the last acted-on task.
    if itype == "tag":
        try:
            tag  = os.environ.get("tag_name", "")
            link = tag_link(tag)
            tvars = {"item_type": "tag", "tag_name": tag, "task_id": "",
                     "task_list_id": pid, "list_id": pid, "section_id": "",
                     "task_title": f"#{tag}"}
            # (title, subtitle, arg, search keywords, show?)
            rows = [
                ("↗️ Open tag",  f"Open {fmt_tags([tag]) or '#' + tag} in web app",
                 f"open:{link}",  "open tag web",       True),
                ("⤵️ Browse tag tasks", "Drill into this tag's tasks", "browse",
                 "browse drill subtasks tasks",          bool(pid)),
                ("➕ Add task",  f"New task tagged {fmt_tags([tag]) or '#' + tag}",
                 "add",          "add new task pretagged",                True),
                # Create a child tag right here (dialog asks the name);
                # only top-level tags are legal nest targets (one level)
                ("➕ Add nested tag",
                 f"New tag under {fmt_tags([tag]) or '#' + tag}",
                 f"xact:tag_create_under:{tag}", "add create nested child tag",
                 _is_top_level_tag(tag)),
                ("🎯 Send all to focus",
                 f"Every open {fmt_tags([tag]) or '#' + tag} task → the focus task's today block",
                 f"xact:tag_focus:{pid}:{tag}", "focus send all stage checkbox",
                 (fx_session() or ("",))[0] == "task"),
                ("🔗 Copy link", "Copy tag URL",  f"copy:{link}", "copy url link", True),
                ("🗑️ Delete tag",
                 f"Remove {fmt_tags([tag]) or '#' + tag} everywhere, tasks survive",
                 f"xact:tag_delete:{tag}", "delete remove tag",   True),
                ("🔙 Go back",   "Back to search", "back",        "back",          True),
            ]
            items = []
            for (t, s, a, kw, show) in rows:
                if not show:
                    continue
                row_vars = dict(tvars)
                if a == "browse":   # unified Browse box reads ctx from env
                    row_vars["browse_ctx"] = f"ctx:tagitems:{pid}:{tag}"
                if a == "add":
                    # Open the Add window pre-tagged - same var
                    # shape as the CRM ⇧⌘ booking wire. task_id must be empty
                    # or the new task becomes a subtask.
                    row_vars = {"task_id": "", "section_id": "",
                                "task_list_id": pid, "list_id": pid,
                                "list_name": (list_name_for(pid, cache_store.get("projects") or [])
                                              if pid else ""),
                                "item_type": "list" if pid else "",
                                "prefill_tag": tag}
                items.append(alfred.item(title=t, subtitle=s, arg=a,
                                         variables=row_vars, match=f"{kw} {t}"))
            if query:
                items = fuzz.filter_and_score(query, items,
                                              key_fn=lambda x: x.get("match", x["title"]))
            if not items:
                items = [alfred.item(title=f'No action matching "{query}"', valid=False)]
            print(alfred.output(items, skipknowledge=True))
        except Exception as e:
            emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")
        return

    # 🧺 Buffer rows: batch menu - tag/move ride the EXISTING pickers
    # with the BUFFER sentinel; dispatch loops the buffer file.
    if itype == "buffer_item":
        try:
            try:
                with open(run_path("tickal_buffer.txt")) as _bf:
                    _n = len([ln for ln in _bf if ln.strip()])
            except OSError:
                _n = 0
            sent = {"task_id": "BUFFER", "task_list_id": "BUFFER", "list_id": "",
                    "section_id": "", "item_type": "buffer_item",
                    "task_title": f"🅿️ Buffer ({_n})"}
            real = dict(sent, task_id=tid, task_list_id=pid)
            rows = [
                ("🏷️ Tag all…",     f"Add tags to all {_n} buffered tasks", "tags",
                 "tags tag all",     True, sent),
                ("📁 Move all…",    f"Move all {_n} to another list",       "move",
                 "move all list",    True, sent),
                ("✔️ Complete all", f"Complete all {_n}",  "xact:buffer_complete",
                 "complete done all", True, sent),
                ("⚡ Priority all…", f"Set priority on all {_n}", "priority",
                 "priority all",      True, sent),
                ("🎯 Add buffer to focus", f"All {_n} → the focus block, clears buffer",
                 "xact:buffer_focus", "focus add all stage checkbox",
                 _n > 0 and (fx_session() or ("",))[0] == "task", sent),
                ("🗑️ Remove this",  "Drop this task from the buffer",
                 f"xact:buffer_remove:{pid}:{tid}", "remove drop", bool(tid), real),
                ("🧹 Clear buffer", "Empty the buffer",    "xact:buffer_clear",
                 "clear empty",      True, sent),
                ("🔙 Go back",      "Back",                "back", "back", True, sent),
            ]
            items = [alfred.item(title=t, subtitle=s, arg=a, variables=v,
                                 match=f"{kw} {t}")
                     for (t, s, a, kw, show, v) in rows if show]
            del_row = alfred.item(title="🗑️ Delete all",
                                  subtitle=f"Delete all {_n}  |  ⏎ confirm",
                                  arg="", valid=False,
                                  match="delete all trash remove 🗑️ Delete all",
                                  variables=sent)
            del_row["autocomplete"] = "delete all yes"
            items.append(del_row)
            if query.strip().lower() == "delete all yes":
                items.insert(0, alfred.item(
                    title=f"🗑️ Confirm · delete all {_n} buffered tasks",
                    subtitle="→ TickTick's Trash",
                    arg="delete", match="delete all yes confirm", variables=sent))
            if query:
                items = fuzz.filter_and_score(query, items,
                                              key_fn=lambda x: x.get("match", x["title"]))
            if not items:
                items = [alfred.item(title=f'No action matching "{query}"', valid=False)]
            print(alfred.output(items, skipknowledge=True))
        except Exception as e:
            emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")
        return

    # Recover task context (go-back path) for task-like items only - never for a
    # list/section, where pulling a stale task_id from the temp file is the bug.
    if itype not in ("list", "section", "buffer_item") and (not pid or not tid):
        try:
            with open("/tmp/ticktick_reattribute.txt") as f:
                parts = f.read().strip().split(":", 1)
                if len(parts) == 2:
                    pid, tid = parts
        except Exception:
            pass

    try:
        task = (find_task(tid) if tid else {}) or {}

        # Infer the item type when the source filter didn't set one.
        if not itype:
            if tid:
                itype = "note" if task.get("kind") == "NOTE" else \
                        ("subtask" if task.get("parentId") else "task")
            elif sid:  itype = "section"
            elif pid:  itype = "list"
            else:      itype = "task"

        is_note      = itype == "note" or task.get("kind") == "NOTE"
        is_container = itype in ("list", "section")   # list/section: no task attributes
        is_task_like = not is_container               # task / subtask / note

        # "Open link" shows only when the item actually has a link - checked
        # cheaply against the cached title + description (no network call). A lone
        # link that lives in the title opens directly (emit open:<url>); anything
        # else (a description link, or several links) hands off to the picker.
        title_links = links_util.extract_links(task.get("title") or title) if is_task_like else []
        desc_links  = links_util.extract_links(task.get("content") or "")  if is_task_like else []
        has_links   = bool(title_links or desc_links)
        if len(title_links) == 1 and not desc_links:
            open_link_arg = f"open:{title_links[0][1]}"
        else:
            open_link_arg = "links"
        # In the direct-open case, ⌘⏎ copies the URL instead (reuses copy: → pbcopy,
        # already reachable from the Actions menu - no extra wiring).
        open_link_mods = None
        if open_link_arg.startswith("open:"):
            _u = open_link_arg[len("open:"):]
            open_link_mods = {"cmd": {"arg": f"copy:{_u}",
                                      "subtitle": f"Copy {_u}"}}
        # The direct-open row also advertises the ⌘ copy shortcut in its subtitle.
        open_link_sub = "Open link" + ("  ⌘ copy URL" if open_link_mods else "")

        # 📝 Note - view/edit the description in a Text View. Subtitle previews it.
        _note = (task.get("content") or "").strip().replace("\n", " ")
        note_sub = (f"Edit: {_note[:48]}…" if len(_note) > 48 else f"Edit: {_note}") \
            if _note else "Add a description"

        if itype == "list":
            link = f"ticktick:///webapp/#p/{pid}/tasks"
        elif itype == "section":
            link = f"ticktick:///webapp/#p/{pid}/tasks/{sid}"
        else:
            link = f"ticktick:///webapp/#p/{pid}/tasks/{tid}"

        # Context every action carries onward (add_task / move / … read these).
        vars_ = {"task_id": tid, "task_list_id": pid, "task_title": title,
                 "item_type": itype, "list_id": pid, "section_id": sid}

        sched = fmt_date(task) or "📅 Not scheduled"
        lname = task.get("_projectName", "") \
            or list_name_for(pid, cache_store.get("projects") or [])
        list_link = f"ticktick:///webapp/#p/{pid}/tasks"
        crumb = join_breadcrumb(task.get("_projectName", ""), section_name(task)) \
            or (task.get("_projectName", "") or "Inbox")
        tags  = fmt_tags(task.get("tags")) or "🏷️ No tags"
        prio  = PRIO.get(task.get("priority", 0), PRIO[0])
        name  = task.get("title") or title
        has_kids = bool(tid) and any(
            s.get("parentId") == tid and s.get("status", 0) == 0
            for s in (cache_store.get("all_tasks") or []))
        add_sub = "Add a subtask" if is_task_like else f"Add a task to this {itype}"

        # 📌 Create CTA / 🔥 Add Prepare - one dynamic row (lists + task-like).
        # areas.classify picks the mode from the item; build_action supplies the
        # label + preview so the row reads correctly before you commit.
        cta_row, cta_vars = None, vars_
        if itype == "list" or is_task_like:
            try:
                _mode = areas.classify(pid, tid, itype, task)
                # CTA rows need a configured 📌CTA list; Prepare rows only need
                # the CRM match (classify already gates that on crm_list_id).
                if _mode != "prepare" and not areas.cta_configured():
                    raise LookupError("cta_list_id not set")
                _act  = areas.build_action(_mode, pid, tid, name)
                _spec = base64.b64encode(json.dumps(
                    {"mode": _mode, "pid": pid, "tid": tid, "title": name}
                ).encode()).decode()
                cta_row = (_act["label"], _act["preview"], f"cta:{_spec}",
                           "cta prepare call to action", True)
                # The CTA opens the Add window from its query alone - it must NOT
                # inherit the selected item's context vars, or add_task turns the new
                # task into a SUBTASK (task_id → parentId). Clear them; carry the
                # parent-list body link as prefill_note (appended to the description)
                # instead of a =note that would block * / and typing.
                cta_vars = {"task_id": "", "task_list_id": "",
                            "list_id": areas.CTA_LIST_ID,
                            "list_name": areas.cta_list_name(),
                            "section_id": "", "item_type": "",
                            "prefill_note": _act.get("note", "")}
            except Exception:
                cta_row = None

        # (title, subtitle, arg, search keywords, show?)
        # Notes get everything but Complete and Priority; list/section get only the
        # container-applicable actions (open / browse / add / copy / back).
        # Every "browse" row re-enters the unified Browse box; the ctx it lands
        # on rides as a row variable, keyed here by row title.
        browse_ctxs = {
            "⤵️ Browse subtasks": f"ctx:subtasks:{pid}:{tid}",
            "⤵️ Browse sections": f"ctx:sections:{pid}",
            "🏷️ Browse tags":     f"ctx:tags:{pid}",
            "⤵️ Browse tasks":    (f"ctx:tasks:{pid}:{sid}" if sid else f"ctx:tasks:{pid}"),
        }

        _sess = fx_session()   # rows below key off the running session

        # One-⏎ scheduling + the 💫 day-goal pin. The rows ride xact:pn_sched
        # (ungated scheduling) - the Actions conditional only routes
        # xact:/bare-verb shapes; attr_date would hit an unwired else.
        try:
            _pn_on = areas.periodic_configured()
        except Exception:
            _pn_on = False

        # ✅ Session done - CRM calendar tasks the crmnew flow minted
        # (S<n>/Consult marker + records-logbook link; the shape check keeps
        # Prepare follow-ups out - their titles carry the link too).
        # 🔗 Link to logbook - the complement: CRM tasks WITHOUT a records
        # link (hand-adds, dormant backlog) get linked + marker-suffixed.
        # Cheap gates FIRST: the crm_records import pulls the api module
        # (~75ms) and this is the hottest render in the workflow.
        _sess_done = _link_row = False
        if (pid and areas.crm_configured() and areas.records_configured()
                and pid == areas.CRM_ID and is_task_like and bool(tid)):
            try:
                import crm_records as _cr
                _sess_done = _cr.is_session_task(name)
                _tags_lc = {str(t).lower()
                            for t in ((task or {}).get("tags") or [])}
                _link_row = (not _sess_done
                             and areas.PREPARE_TAG not in _tags_lc)
            except Exception:
                _sess_done = _link_row = False

        # 📇 Contact copy - customer notes get their phone/mail/insta as
        # copy rows on EVERY surface that reaches ⌘ Actions, not just the
        # hub. Same cheap-gate-first rule as above.
        _phone = _mail = _insta = ""
        if (pid and areas.records_configured() and pid == areas.RECORDS_ID
                and is_note and bool(tid)):
            try:
                import crm_records as _cr2
                _phone, _mail, _bd, _insta = _cr2.contact_of(task or {})
            except Exception:
                pass

        rows = [
            ("↗️ Open",            "Open in TickTick",     f"open:{link}",  "open",              True),
            ("✅ Session done",    "Tick off · log · schedule next",
             f"xact:sessiondone:{pid}:{tid}", "session done log crm tattoo", _sess_done),
            ("🔗 Link to logbook", "Pick logbook · title gains link + S<n>",
             f"xact:crmlink:{pid}:{tid}", "link logbook customer records crm", _link_row),
            ("⤵️ Browse subtasks", "Drill into subtasks",  "browse",        "browse subtasks",   is_task_like and has_kids),
            ("⤵️ Browse sections", "Drill into sections",  "browse",        "browse sections drill", itype == "list"),
            ("🏷️ Browse tags",     "Drill into this list's tags", "browse", "browse tags drill", itype == "list"),
            ("⤵️ Browse tasks",    "Drill into tasks",     "browse",        "browse tasks drill", itype == "section"),
            (sched,                "Schedule…",            "schedule",      "schedule date when", is_task_like),
            ("☀️ Add to today",    "Land it on today",     f"xact:pn_sched:today|{pid}|{tid}",
             "today add schedule now day", is_task_like and bool(tid) and bool(task)),
            ("🌙 Add to tomorrow", "Land it on tomorrow",  f"xact:pn_sched:tomorrow|{pid}|{tid}",
             "tomorrow add schedule next day", is_task_like and bool(tid) and bool(task)),
            ("☀️ Make day goal",   "Today's one thing · pinned in 💫",
             f"xact:pn_day_goal:{pid}:{tid}", "day goal one thing periodic pin",
             is_task_like and bool(tid) and bool(task) and _pn_on),
            ("🔔 Reminder",        "Set a reminder…",      "reminder",      "reminder remind alert", is_task_like),
            (tags,                 "Tags…",                "tags",          "tags tag",          is_task_like),
            (prio,                 "Priority…",            "priority",      "priority",          is_task_like and not is_note),
            (crumb,                "Move…",                "move",          "move list section", is_task_like),
            ("➕ Add task",        add_sub,                "add",           "add new task",      True),
            ("🔗 Copy link",       "Copy item URL",        f"copy:{link}",  "copy url",          True),
            ("🆔 Copy id",         "List id → clipboard",  f"copy:{pid}",   "id copy identifier configure", itype == "list"),
            (f"📞 Copy {_phone}",  "Number → clipboard",   f"copy:{_phone}", "phone copy number contact call", bool(_phone)),
            (f"✉️ Copy {_mail}",   "Mail → clipboard",     f"copy:{_mail}",  "mail copy email contact", bool(_mail)),
            (f"📸 Open {_insta}",  "Instagram profile (DMs)",
             f"open:https://instagram.com/{_insta.lstrip('@')}", "instagram insta dm profile contact", bool(_insta)),
            ("💬 WhatsApp",        f"Chat with {_phone}",
             f"open:https://wa.me/{__import__('re').sub(r'[^0-9]', '', _phone).lstrip('0')}",
             "whatsapp wa chat message contact", bool(_phone)),
            ("📂 Go to list",      f"Open {lname or 'this list'} in TickTick",
             f"open:{list_link}",  "go to list open project folder",        is_task_like and bool(pid)),
            ("🌐 Open link",       open_link_sub,          open_link_arg, "link url web open", has_links),
            ("📝 Note",            note_sub,               "note",          "note description body edit", is_task_like),
            ("🖼️ Add image",       "Clipboard link → description", "attach", "attach add image clipboard screenshot link", is_task_like),
            # One dynamic row - whatever the item is, offer the other
            # kind. Gated on a CACHED (= open) item: completed rows carry a
            # tid too, and converting one mints a status-2 "note" that
            # evaporates at the next sync.
            (f"🔃 Convert to {'task' if is_note else 'note'}",
             "Keeps title, dates, tags",
             f"xact:convert:{pid}:{tid}", "convert note task kind switch turn",
             is_task_like and bool(tid) and bool(task)),
            # ONE 🎯 Focus row replaces Start-focus / Focus
            # (sticky+timer) / Start-pomo - ⏎ opens the ⏱/🍅 flow for THIS task.
            ("🎯 Focus",           "Timer or Pomodoro, sticky optional",
             f"xact:focus_open:{pid}:{tid}", "focus timer pomo pomodoro start track time",
             is_task_like and bool(tid)),
            ("🗒️ Sticky note",     "Open as desktop sticky",
             f"xact:sticky:{pid}:{tid}", "sticky note desktop pin", is_task_like and bool(tid)),
            ("🅿️ Add to buffer",   "Collect tasks, act on all (🅿️ in search)",
             f"xact:buffer_add:{pid}:{tid}", "buffer collect batch", is_task_like and bool(tid)),
            # Focus-block staging: direct add when a task-bound session
            # runs; the stage screen (both directions) always; live-link only
            # while a session runs unattributed.
            (f"🎯 Add to focus ({(_sess[3][:24] if _sess and _sess[0] == 'task' else '')})",
             "→ checkbox in the focus task's today block",
             f"xact:fx_add:{pid}:{tid}", "focus add stage checkbox now",
             is_task_like and bool(tid) and bool(_sess) and _sess[0] == "task"
             and _sess[2] != tid),
            ("🎯 Stage for Focus", "Checkbox-link this task into another task/note…",
             f"xact:stage_open:{pid}:{tid}", "stage focus link checkbox block",
             is_task_like and bool(tid)),
            ("🔗 Link to running focus", "Attribute the RUNNING session to this task",
             f"xact:fx_link:{pid}:{tid}", "link focus attribute session running",
             is_task_like and bool(tid) and bool(_sess) and _sess[0] == "bare"),
            ("✔️ Complete",        "Mark this done",       f"complete:{pid}:{tid}:{title}", "complete done", is_task_like and not is_note),
            # TickTick's third status - off the lists, kept on record
            ("🚫 Won't do",        "Abandon task",         f"xact:wontdo:{pid}:{tid}", "wont do abandon skip cancel", is_task_like and not is_note and bool(tid)),
            (md_links_display(name) if is_task_like else (lname or "Rename"),
                                   "Rename…",              "rename",        "rename title name", is_task_like or itype == "list"),
            ("🗑️ Delete",          "Delete this item",     "delete",        "delete remove",     is_task_like),
            ("🔙 Go back",         "Back to search",       "back",          "back",              True),
        ]

        if cta_row:
            # just after ➕ Add task - found by title, not a raw index that
            # silently drifts when rows are added above it
            _add_idx = next((i for i, r in enumerate(rows)
                             if r[0] == "➕ Add task"), 7)
            rows.insert(_add_idx + 1, cta_row)

        items = []
        for (t, s, a, kw, show) in rows:
            if not show:
                continue
            extra = {"mods": open_link_mods} if (t == "🌐 Open link" and open_link_mods) else {}
            row_vars = cta_vars if a.startswith("cta:") else vars_
            if a == "browse":   # unified Browse box reads ctx from env
                row_vars = dict(row_vars)
                row_vars["browse_ctx"] = browse_ctxs[t]
            if a == "rename" and itype == "list":
                # rename_task.py shows task_title; give it the list's name
                row_vars = dict(row_vars)
                row_vars.update({"task_title": lname, "list_name": lname})
            items.append(alfred.item(title=t, subtitle=s, arg=a, variables=row_vars,
                                     match=f"{kw} {t}", **extra))

        # 🗑️ Delete list - typed confirm, zero canvas: the first row
        # is invalid and autocompletes the bar to "delete list yes"; only then
        # does the valid confirm row (arg "delete" → delete_action list branch)
        # survive the fuzzy filter.
        if itype == "list" and pid:
            del_vars = dict(vars_)
            del_vars.update({"task_title": lname, "list_name": lname})
            del_row = alfred.item(
                title="🗑️ Delete list",
                subtitle=f"Delete “{lname or 'this list'}” + its tasks  |  ⏎ confirm",
                arg="", valid=False, match="delete remove list trash 🗑️ Delete list",
                variables=del_vars)
            del_row["autocomplete"] = "delete list yes"
            items.append(del_row)
            if query.strip().lower() == "delete list yes":
                items.insert(0, alfred.item(
                    title=f"🗑️ Confirm · delete “{lname or 'this list'}”",
                    subtitle="List + tasks → TickTick's Trash",
                    arg="delete", match="delete list yes confirm",
                    variables=del_vars))

        # Running focus timer → a ⏹ Stop row on top of every menu
        # (pause-aware elapsed via xact.focus_elapsed)
        try:
            with open(run_path("tickal_focus.json")) as _f:
                _fs = json.load(_f)
            try:
                from xact import focus_elapsed as _fe    # Scripts sibling
                _secs = _fe(_fs)
            except Exception:
                from datetime import datetime as _dt, timezone as _tz
                _secs = (_dt.now(_tz.utc) - _dt.strptime(
                    _fs["start"], "%Y-%m-%dT%H:%M:%S+0000").replace(tzinfo=_tz.utc)
                    ).total_seconds()
            _mins = max(0, int(_secs // 60))
            _pause_tag = " ⏸" if _fs.get("paused_at") else ""
            items.insert(0, alfred.item(
                title=f"⏹ Stop focus · {_fs.get('title','task')[:30]} · {_mins}m{_pause_tag}",
                subtitle="Log to calendar  |  ⌥ discard",
                arg="xact:focus_stop", match="stop focus timer",
                mods={"alt": {"arg": "xact:focus_discard",
                              "subtitle": "Stop WITHOUT logging"}},
                variables=vars_))
        except OSError:
            pass

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x.get("match", x["title"]))

            # typed “pomo 45” / “log 25” → explicit-minutes confirm rows
            import re as _re
            _m = _re.fullmatch(r"pomo\s+(\d{1,3})", query.strip())
            if _m and is_task_like:
                items.insert(0, alfred.item(
                    title=f"▶️ Start pomo ({_m.group(1)}m)", subtitle="TickTick's real pomodoro",
                    arg=f"xact:pomo:{_m.group(1)}", variables=vars_))
            _m = _re.fullmatch(r"log\s+(\d{1,3})", query.strip())
            if _m and is_task_like and tid:
                items.insert(0, alfred.item(
                    title=f"🎯 Log {_m.group(1)}m on {name[:28]}",
                    subtitle="Record ends now → calendar",
                    arg=f"xact:focus_log:{pid}:{tid}:{_m.group(1)}", variables=vars_))
        if not items:
            items = [alfred.item(title=f'No action matching "{query}"', valid=False)]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
