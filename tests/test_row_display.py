#!/usr/bin/env python3
"""Row display fixes of 2026-09-20 (Vex's bug dump), pinned:

  * md_links_display never doubles the chip: a CTA parent's title is
    "💼 P • [Name](url) 🔗" and rendered as "[Name]🔗 🔗" before
  * a dateless subtask borrows its nearest dated ancestor's date as ↑📆
    (build_title / pick_title / browse.task_item with a task_map), never
    without one, never over its own date, never through a cycle
  * search's breadcrumb and browse's children breadcrumb render parent
    titles display-only (no raw "[x](url)" in a subtitle)
  * the buffer's ⌘ menu carries "🎯 Merge/Stage for Focus" with the REAL
    task ids, the tag menu carries "✏️ Rename tag"
  * xact.tag_rename: cancel / unchanged / bad chars / existing name refuse
    before any network; a rename patches every cache pool

    python3 tests/test_row_display.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
TMP = tempfile.mkdtemp(prefix="tickal-rows-")
os.environ["HOME"] = TMP                       # run files, never Vex's
import cache as cache_store                    # noqa: E402
cache_store.CACHE_DIR = os.path.join(TMP, "cache")
os.makedirs(cache_store.CACHE_DIR)

import display                                 # noqa: E402
from display import (md_links_display, build_title, pick_title,  # noqa: E402
                     inherited_date, fmt_date)

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


LIST = "5eed00000000000000000c01"
CTA = "5eed00000000000000000c10"
KID = "5eed00000000000000000c11"
GRANDKID = "5eed00000000000000000c12"
LONER = "5eed00000000000000000c13"
URL = "ticktick:///webapp/#p/6a2ab4686b8e917957000a71/tasks"
PARENT = {"id": CTA, "projectId": LIST, "_projectId": LIST, "_projectName": "🗒N - 📌 CTA",
          "title": f"💼 P • [TickAL • WF]({URL}) 🔗", "priority": 5, "status": 0,
          "startDate": "2026-09-21T18:00:00.000+0000",
          "dueDate": "2026-09-21T20:00:00.000+0000", "isAllDay": False,
          "tags": ["4️⃣vexos"]}
CHILD = {"id": KID, "projectId": LIST, "_projectId": LIST, "_projectName": "🗒N - 📌 CTA",
         "title": "OKRs", "priority": 0, "status": 0, "parentId": CTA,
         "content": "What are these?"}
GRAND = {"id": GRANDKID, "projectId": LIST, "_projectId": LIST, "_projectName": "🗒N - 📌 CTA",
         "title": "🔴 still full md strings", "priority": 0, "status": 0, "parentId": KID}
ALONE = {"id": LONER, "projectId": LIST, "_projectId": LIST, "_projectName": "🗒N - 📌 CTA",
         "title": "Set new dates on OKRs", "priority": 0, "status": 0}
TASKS = [PARENT, CHILD, GRAND, ALONE]
TMAP = {t["id"]: t for t in TASKS}

# ── md_links_display ────────────────────────────────────────────────────────
print("-- md_links_display")
check("a link renders as [name]🔗",
      md_links_display(f"[TickAL • WF]({URL})") == "[TickAL • WF]🔗")
check("a CTA title's own trailing chip collapses into the rendered one",
      md_links_display(PARENT["title"]) == "💼 P • [TickAL • WF]🔗",
      md_links_display(PARENT["title"]))
check("a chip run with several spaces collapses too",
      md_links_display("[a](u)  🔗   🔗") == "[a]🔗")
check("a bare 🔗 on a plain title is untouched",
      md_links_display("Ship it 🔗") == "Ship it 🔗")
check("the legend chip ⌥⌘🔗 is untouched",
      md_links_display("⌥⌘🔗  ⌘⇧➕") == "⌥⌘🔗  ⌘⇧➕")
check("two links stay two chips",
      md_links_display("[a](u) and [b](v)") == "[a]🔗 and [b]🔗")
check("None renders empty", md_links_display(None) == "")

# ── inherited date ──────────────────────────────────────────────────────────
print("-- inherited_date / build_title")
parent_chip = fmt_date(PARENT)
check("fixture: the parent carries a timed span", parent_chip.startswith("📆 21/09/2026 "), parent_chip)
check("a dateless child borrows the parent's date with the ↑ mark",
      inherited_date(CHILD, TMAP) == "↑" + parent_chip, inherited_date(CHILD, TMAP))
check("a dateless grandchild walks up two levels",
      inherited_date(GRAND, TMAP) == "↑" + parent_chip)
check("no task_map, no chip", inherited_date(CHILD, None) == "")
check("a top-level dateless task has nothing to borrow", inherited_date(ALONE, TMAP) == "")
dated_child = dict(CHILD, startDate="2026-09-25T00:00:00.000+0000", isAllDay=True)
check("a child's OWN date wins over the parent's",
      inherited_date(dated_child, TMAP) == "" and "📆 25/09/2026" in build_title(dated_child, task_map=TMAP),
      build_title(dated_child, task_map=TMAP))
loop_a = {"id": "a" * 24, "title": "A", "parentId": "b" * 24}
loop_b = {"id": "b" * 24, "title": "B", "parentId": "a" * 24}
check("a parent cycle ends quietly",
      inherited_date(loop_a, {loop_a["id"]: loop_a, loop_b["id"]: loop_b}) == "")
check("build_title: 'OKRs ⚫️ ↑📆 …' with the map",
      build_title(CHILD, task_map=TMAP) == f"OKRs ⚫️ ↑{parent_chip}", build_title(CHILD, task_map=TMAP))
check("build_title without the map is the old shape", build_title(CHILD) == "OKRs ⚫️")
check("the parent's own title: one chip, its date, its tag",
      build_title(PARENT) == f"💼 P • [TickAL • WF]🔗 🔴 {parent_chip} #4️⃣vexos"
      or build_title(PARENT).startswith(f"💼 P • [TickAL • WF]🔗 🔴 {parent_chip}"),
      build_title(PARENT))
check("pick_title passes the map through",
      pick_title(CHILD, task_map=TMAP).startswith("OKRs ⚫️ ↑📆") and pick_title(CHILD) == "OKRs ⚫️")

# ── browse: task_item + the children breadcrumb ─────────────────────────────
print("-- browse rows")
import browse  # noqa: E402
row = browse.task_item(CHILD, LIST, 1, breadcrumb="x", task_map=TMAP)
check("task_item with a task_map shows the inherited chip",
      row["title"] == f"OKRs ⚫️ ↑{parent_chip}", row["title"])
row0 = browse.task_item(CHILD, LIST, 1, breadcrumb="x")
check("task_item without one does not", row0["title"] == "OKRs ⚫️")
check("task_item keeps task_title RAW", row0["variables"]["task_title"] == "OKRs")

cache_store.set("projects", [{"id": LIST, "name": "🗒N - 📌 CTA"}])
cache_store.set(f"project_data_{LIST}", {"project": {"id": LIST}, "tasks": TASKS,
                                          "columns": []})
cache_store.set("all_tasks", TASKS)
cache_store.set("all_notes", [])
kids = browse.render_children(LIST, CTA, "", "subtasks")
okr = next((r for r in kids if r.get("variables", {}).get("task_id") == KID), None)
check("children screen renders the OKRs row", okr is not None)
if okr:
    check("children breadcrumb renders the parent link display-only",
          "](" not in okr["subtitle"] and "[TickAL • WF]🔗" in okr["subtitle"], okr["subtitle"])
    check("children row borrows the parent's date", "↑📆" in okr["title"], okr["title"])

# ── search: the breadcrumb ──────────────────────────────────────────────────
print("-- search breadcrumb")
import everything_search as es  # noqa: E402
crumb = es.get_task_breadcrumb(GRAND, TMAP)
check("search breadcrumb: list>parent>child, links rendered",
      crumb == "🗒N - 📌 CTA>💼 P • [TickAL • WF]🔗>OKRs", crumb)
check("search breadcrumb has no raw link", "](" not in crumb)

# ── the two ⌘ menus ─────────────────────────────────────────────────────────
print("-- ⌘ menus")
import actions  # noqa: E402


def menu(env):
    saved = dict(os.environ)
    os.environ.update(env)
    argv = sys.argv
    sys.argv = ["actions.py", ""]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            actions.main()
    finally:
        sys.argv = argv
        os.environ.clear()
        os.environ.update(saved)
    return json.loads(buf.getvalue())["items"]


brows = menu({"item_type": "buffer_item", "task_id": KID, "task_list_id": LIST,
              "task_title": "OKRs"})
stage = next((r for r in brows if r["title"] == "🎯 Merge/Stage for Focus"), None)
check("buffer ⌘ menu carries the stage row", stage is not None, [r["title"] for r in brows])
if stage:
    check("… with the REAL task ids, not the BUFFER sentinel",
          stage["arg"] == f"xact:stage_open:{LIST}:{KID}", stage["arg"])
    check("… and real ids in its variables",
          stage["variables"].get("task_id") == KID and stage["variables"].get("task_list_id") == LIST)
titles = [r["title"] for r in brows]
check("stage row sits after 'Add buffer to focus' slot and before 'Remove this'",
      titles.index("🎯 Merge/Stage for Focus") < titles.index("❌ Remove this"))
brows0 = menu({"item_type": "buffer_item", "task_id": "", "task_list_id": "",
               "task_title": "🅿️ Buffer (0)"})
check("no task under the cursor, no stage row",
      all(r["title"] != "🎯 Merge/Stage for Focus" for r in brows0))

trows = menu({"item_type": "tag", "tag_name": "4️⃣vexos", "task_list_id": ""})
ren = next((r for r in trows if r["title"] == "✏️ Rename tag"), None)
check("tag ⌘ menu carries the rename row", ren is not None, [r["title"] for r in trows])
if ren:
    check("… firing xact:tag_rename:<tag>", ren["arg"] == "xact:tag_rename:4️⃣vexos", ren["arg"])
    tt = [r["title"] for r in trows]
    check("… placed before Delete", tt.index("✏️ Rename tag") < tt.index("🗑️ Delete tag"))

# ── xact.tag_rename ─────────────────────────────────────────────────────────
print("-- tag_rename")
import xact  # noqa: E402
import api_v2  # noqa: E402

calls = []


class FakeV2:
    token = "t"

    def __init__(self, *a, **k):
        pass

    def rename_tag(self, name, new):
        calls.append((name, new))
        return True


api_v2.TickTickV2 = FakeV2
answers = []
xact._ask = lambda prompt, *a, **k: answers.pop(0)


def run(tag, answer):
    answers.append(answer)
    calls.clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        xact.tag_rename(tag)
    return buf.getvalue().strip()


cache_store.set("tags", ["4️⃣vexos", "🍳breakfast", "Work"])
cache_store.set("tags_tree", [{"name": "4️⃣vexos", "label": "4️⃣vexos", "parent": None},
                              {"name": "🍳breakfast", "label": "🍳breakfast", "parent": "4️⃣vexos"},
                              {"name": "work", "label": "Work", "parent": None}])
cache_store.set("all_tasks", [dict(PARENT), dict(CHILD, tags=["4️⃣VexOS", "Work"])])
cache_store.set("all_notes", [{"id": "n" * 24, "title": "n", "tags": ["4️⃣vexos"]}])
cache_store.set(f"project_data_{LIST}", {"project": {"id": LIST},
                                          "tasks": [dict(CHILD, tags=["4️⃣vexos"])]})

check("cancel = silence, no call", run("4️⃣vexos", None) == "" and not calls)
check("unchanged = silence, no call", run("4️⃣vexos", "4️⃣vexos") == "" and not calls)
check("empty = silence, no call", run("4️⃣vexos", "   ") == "" and not calls)
out = run("4️⃣vexos", "bad:name")
check("a forbidden character is refused before the network",
      out.startswith("A tag can't contain") and ":" in out and not calls, out)
out = run("4️⃣vexos", "work")
check("an existing tag (case-insensitive) is refused",
      "already exists" in out and not calls, out)
out = run("4️⃣vexos", "#4️⃣VexOS")
check("a case-only change goes through (same tag, new label)",
      calls == [("4️⃣vexos", "4️⃣VexOS")] and out == "Tag #4️⃣vexos → #4️⃣VexOS", (calls, out))
out = run("4️⃣VexOS", "4️⃣ vex os")
check("spaces are squeezed out of the new name",
      calls == [("4️⃣VexOS", "4️⃣vexos")], calls)
out = run("4️⃣vexos", "4️⃣system")
check("a real rename toasts old → new", out == "Tag #4️⃣vexos → #4️⃣system", out)
check("… the label list follows", "4️⃣system" in cache_store.get("tags")
      and "4️⃣vexos" not in cache_store.get("tags"))
tree = {t["name"]: t for t in cache_store.get("tags_tree")}
check("… the tree entry is renamed", "4️⃣system" in tree and tree["4️⃣system"]["label"] == "4️⃣system")
check("… children's parent link follows", tree["🍳breakfast"]["parent"] == "4️⃣system")
kid = next(t for t in cache_store.get("all_tasks") if t["id"] == KID)
check("… all_tasks tags follow (case-insensitive), other tags kept",
      kid["tags"] == ["4️⃣system", "Work"], kid["tags"])
check("… all_notes tags follow", cache_store.get("all_notes")[0]["tags"] == ["4️⃣system"])
pd = cache_store.get(f"project_data_{LIST}")["tasks"][0]
check("… project_data tags follow", pd["tags"] == ["4️⃣system"], pd["tags"])


class RefusingV2(FakeV2):
    def rename_tag(self, name, new):
        return False


api_v2.TickTickV2 = RefusingV2
out = run("Work", "Play")
check("a server refusal toasts and leaves the caches alone",
      out == "Could not rename #Work" and "Work" in cache_store.get("tags"), out)

# ── clip_links (the picker crumb cut) ───────────────────────────────────────
print("-- clip_links")
from display import clip_links  # noqa: E402
check("short text passes through", clip_links("[a]🔗 b", 24) == "[a]🔗 b")
check("a cut inside a link keeps the chip",
      clip_links("🥅 O • [Onboard TickTicks]🔗 · x", 24) == "🥅 O • [Onboard TickTi…]🔗",
      clip_links("🥅 O • [Onboard TickTicks]🔗 · x", 24))
check("a cut on the closing bracket keeps the chip",
      clip_links("[Onboard TickTick]🔗 more", 18) == "[Onboard TickTick]🔗…",
      clip_links("[Onboard TickTick]🔗 more", 18))
check("an earlier closed link never lends its bracket (no phantom chip)",
      clip_links("[a]🔗 and [bcdef]🔗", 12) == "[a]🔗 and […]🔗",
      clip_links("[a]🔗 and [bcdef]🔗", 12))
check("plain text just gets the ellipsis",
      clip_links("Clean up Keyboard Maestro macros", 24) == "Clean up Keyboard Maestr…")
check("a literal bracket with no chip ahead is plain text",
      clip_links("Sleeve [250] and more words here", 12) == "Sleeve [250]…",
      clip_links("Sleeve [250] and more words here", 12))
check("None is empty", clip_links(None, 10) == "")

# ── the ~p parent picker: label fill only when unique, resolver order ──────
print("-- add_task parent resolver")
import add_task as at  # noqa: E402
KM = "kmtrigger://macro=97F0"
POOL = [
    {"id": "1" * 24, "title": "Eagle", "status": 0, "_projectId": "pA"},
    {"id": "2" * 24, "title": f"[Eagle]({KM})", "status": 0, "_projectId": "pB"},
    {"id": "3" * 24, "title": f"[Journal]({KM})", "status": 0, "_projectId": "pB"},
    {"id": "4" * 24, "title": f"[Journal]({KM})", "status": 0, "_projectId": "pC"},
    {"id": "5" * 24, "title": f"💼 P • [TickAL • WF]({URL}) 🔗", "status": 0, "_projectId": "pD"},
    {"id": "6" * 24, "title": f"[Solo]({KM})", "status": 0, "_projectId": "pB"},
    {"id": "7" * 24, "title": f"[Gone]({KM})", "status": 2, "_projectId": "pB"},
    {"id": "8" * 24, "title": "Plan action on [💼 P • TickAL • WF](https://x/y)", "status": 0, "_projectId": "pE"},
]
check("a label shared with a plain title is not unique", not at._label_unique(POOL, "Eagle"))
check("a label repeated across routines is not unique", not at._label_unique(POOL, "Journal"))
check("a label carried by one open task is unique", at._label_unique(POOL, "Solo"))
check("a completed twin does not count", at._label_unique(POOL, "Gone") is False)
check("the CTA label is unique here", at._label_unique(POOL, "💼 P • TickAL • WF"))
r = at._resolve_parent(POOL, "Eagle", open_only=True)
check("raw exact wins: 'Eagle' is the plain task, never the link twin", r and r["id"] == "1" * 24)
r = at._resolve_parent(POOL, f"[Eagle]({KM})", open_only=True)
check("the raw link title resolves its own task", r and r["id"] == "2" * 24)
r = at._resolve_parent(POOL, "Solo", open_only=True)
check("a unique label resolves through the normalized pass", r and r["id"] == "6" * 24)
r = at._resolve_parent(POOL, "💼 P • TickAL • WF", open_only=True)
check("the CTA label finds the CTA parent, not the 'Plan action on' substring hit",
      r and r["id"] == "5" * 24, r and r["title"])
r = at._resolve_parent(POOL, "Journal", open_only=True)
check("an ambiguous label falls to the substring pass (the typed-name road)",
      r and r["id"] == "3" * 24)
r = at._resolve_parent(POOL, "Gone", open_only=False)
check("the note road (open_only False) still finds a completed unique hit", r and r["id"] == "7" * 24)
check("… and the task road does not", at._resolve_parent(POOL, "Gone", open_only=True) is None)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    sys.exit(1)
