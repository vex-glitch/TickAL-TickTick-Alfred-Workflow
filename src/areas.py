#!/usr/bin/env python3
"""
areas.py — area-tag derivation + CTA / Prepare action building.

Shared by Scripts/actions.py (row preview) and src/dispatch.py (execution) so the
one dynamic "Add CTA / Prepare" Actions row and its handler agree on exactly one
behaviour per item.

Area-tag derivation (matches Vex's hierarchy):
  • a PROJECT list carries the area keycap in its own NAME  (💼P • Claude 4️⃣)
  • a regular list carries it on its parent FOLDER          (2️⃣Personal)
  • a TASK resolves via its parent list, same rule
Matched by the keycap emoji, so folder-name spacing ("2️⃣ Personal" vs
"2️⃣Personal") is irrelevant. No keycap anywhere → no tag (never invents one).
The resolved label is an existing nested tag under 🎩Area; TickTick matches tags
by a normalised key, so assigning it reuses that tag — no duplicates.
"""
import os
import re

import cache as cache_store
import config as cfg

CTA_LIST_ID        = "6a3413e02522110c0d06e678"   # 📌CTA
CTA_LIST_NAME      = "📌CTA"                       # ~l target used in the Add prefill
CRM_LIST_NAME      = "🔥CRM"
PROJECTS_FOLDER_ID = "69fcaeb9bac7d10a6914dfca"   # 💼Projects
CRM_ID             = "69fed9d51fe6d10d8510bf15"   # 🔥CRM
PREPARE_TAG        = "🔥prepare"                   # normalised (lower) form

WORKFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# keycap number emoji: digit + optional VS-16 + U+20E3 (⃣). Searched anywhere in
# the string so a manual sort prefix like "2) 1️⃣ Work" still yields 1️⃣.
KEYCAP_RE  = re.compile(r"[0-9]️?⃣")
# "💼P • " / "💼 P • " project-list prefix (anchored).
PROJECT_RE = re.compile(r"^\s*💼\s*P\s*•\s*")


def _keycap(text):
    m = KEYCAP_RE.search(text or "")
    return m.group(0) if m else None


def area_tags():
    """[(label, keycap)] from tags_config.py — entries led by a keycap number."""
    try:
        ns = {}
        with open(os.path.join(WORKFLOW_DIR, "tags_config.py"), encoding="utf-8") as f:
            exec(f.read(), ns)
        out = []
        for t in ns.get("TAGS", []):
            kc = _keycap(t)
            if kc and t.strip().startswith(kc):
                out.append((t, kc))
        return out
    except Exception:
        return []


def is_project(name):
    """True for a project list created by the add-project flow (💼P • …)."""
    return bool(PROJECT_RE.match(name or ""))


def clean_project_name(name):
    """'💼P • Claude 4️⃣' → 'Claude' (strip the prefix and the trailing keycap)."""
    n = PROJECT_RE.sub("", name or "")
    n = KEYCAP_RE.sub("", n)
    return n.strip()


def _project(pid):
    for p in (cache_store.get("projects") or []):
        if p.get("id") == pid:
            return p
    return None


def area_tag_for_list(proj):
    """Existing area-tag label for a list/project dict, or None if undecidable."""
    if not proj:
        return None
    kc = _keycap(proj.get("name", ""))                        # project → title keycap
    if not kc:
        gid = proj.get("groupId")
        folder = cfg.get_folders().get(gid, "") if gid else ""
        kc = _keycap(folder)                                  # list → folder keycap
    if not kc:
        return None
    for label, cap in area_tags():
        if cap == kc:
            return label
    return None


def _list_link(pid):
    return f"ticktick:///webapp/#p/{pid}/tasks"


def _task_link(pid, tid):
    # https form = exactly how TickTick stores a [[ ]] internal link (backlink).
    return f"https://ticktick.com/webapp/#p/{pid}/tasks/{tid}"


def classify(pid, tid, itype, task):
    """Pick the action mode for the selected item.

    prepare  — a CRM entry (task in 🔥CRM, not itself a 🔥prepare follow-up)
    project  — a 💼P • … project list
    list     — any other list
    task     — a task / subtask / note
    """
    tags_lc = {str(t).lower() for t in ((task or {}).get("tags") or [])}
    if pid == CRM_ID and itype in ("task", "subtask", "note") \
            and PREPARE_TAG not in tags_lc:
        return "prepare"
    if itype in ("list", "section"):
        name = (_project(pid) or {}).get("name", "")
        return "project" if is_project(name) else "list"
    return "task"


def build_action(mode, pid, tid, title):
    """Build the dynamic row's behaviour: a prefilled Add-window query (so the
    CTA/Prepare task can be SCHEDULED before it's created — same flow as CRM
    bookings) plus the row label + preview, and an optional `note` (the parent-list
    body link).

    `note` rides to the Add window as the `prefill_note` variable, NOT as a `=note`
    in the query: a trailing `=note` is opaque to the parser, so it would swallow
    everything the user then types (blocking * / and every trigger). The query
    therefore ends at the title, keeping the cursor in trigger-land.

    Returns {"query", "note", "mode", "tag", "label", "preview"}.
    """
    if mode == "prepare":
        # The working CRM auto-flow prefill verbatim ([[title]] resolves on ⏎).
        q = f"~l {CRM_LIST_NAME} #{PREPARE_TAG} Prepare for [[{title}]]"
        return {"query": q, "note": "", "mode": mode, "tag": PREPARE_TAG,
                "label": "🔥 Add Prepare",
                "preview": f"Opens {CRM_LIST_NAME} add · Prepare for \"{title}\" — schedule & ⏎"}

    proj    = _project(pid)
    tag     = area_tag_for_list(proj)
    tagpart = f"#{tag} " if tag else ""
    note    = ""
    if mode in ("project", "list"):
        name = (proj or {}).get("name") or title
        link = _list_link(pid)
        cta_title = (f"💼 P • [{clean_project_name(name)}]({link}) 🔗"
                     if mode == "project" else f"[{name}]({link}) 🔗")
        q = f"~l {CTA_LIST_NAME} {tagpart}{cta_title}"
    else:  # task / subtask / note — link the task; parent list goes in the body
        q = f"~l {CTA_LIST_NAME} {tagpart}[{title}]({_task_link(pid, tid)}) 🔗"
        list_name = (proj or {}).get("name", "")
        note = f"[{list_name}]({_list_link(pid)})" if list_name else ""
    return {"query": q, "note": note, "mode": mode, "tag": tag,
            "label": "📌 Create CTA",
            "preview": f"Opens {CTA_LIST_NAME} add" + (f" · {tag}" if tag else "") + " — schedule & ⏎"}
