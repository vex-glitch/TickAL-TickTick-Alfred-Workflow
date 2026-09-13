#!/usr/bin/env python3
"""TickTick's fold comment on a header line must never hide or unfold a section.

2026-09-13: the app stores a folded header's state ON the line,
`#### 🏆 Goals <!-- {"folded":true} -->`. The section engine read the comment
as part of the name, so a folded section went invisible to its filler, and
set_header dropped it, so every data-in-header refresh unfolded the section.

    python3 tests/test_fold_comments.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import periodic_engine as pe     # noqa: E402
import periodic_model as pm      # noqa: E402
import periodic_sections as ps   # noqa: E402

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


F = ' <!-- {"folded":true} -->'

# ── split_fold
check("a folded name splits into name + comment",
      ps.split_fold('🏆 Goals' + F) == ("🏆 Goals", F), ps.split_fold('🏆 Goals' + F))
check("an unfolded name is untouched", ps.split_fold("🏆 Goals") == ("🏆 Goals", ""))
check("a line that is only a comment keeps it as its name",
      ps.split_fold('<!-- {"folded":true} -->')[0] == '<!-- {"folded":true} -->')
check("a plain inline comment that is not the app's state stays in the name",
      ps.split_fold("Notes <!-- mine -->") == ("Notes <!-- mine -->", ""))

# ── the daily note as the server held it on 2026-09-13
DAILY = "\n".join([
    "[[W37]] · Sun 13 Sep · 18°C",
    "---",
    "#### 🌉 Yesterday's bridge" + F,
    "> ship the weekly",
    "---",
    "#### 🏆 Goals" + F,
    "- 🗓️ Weekly",
    "\t- one",
    "",
    "- ☀️ Daily",
    "\t- two",
    "---",
    "#### ☀️ Today" + F,
    "- 🔄 Habits",
    "\t- _(pending)_",
    "---",
    "#### 📓 Journals",
    "- 🌅 Morning journal",
    "",
])
d = ps.parse_sections(DAILY)
check("round trip is byte-preserving with fold comments",
      ps.serialize_sections(d) == DAILY)
check("section names carry no comment",
      [s.name for s in d.sections] == ["🌉 Yesterday's bridge", "🏆 Goals", "☀️ Today", "📓 Journals"],
      [s.name for s in d.sections])
check("the comment is kept on the section", [s.fold for s in d.sections] == [F, F, F, ""])

br = ps.find(d, pm.SEC_YBRIDGE)
check("a folded bridge header is found by name", br is not None and br.name == pm.SEC_YBRIDGE, br)
ps.set_body(d, pm.SEC_YBRIDGE, ["> a new bridge"])
out = ps.serialize_sections(d)
check("filling a folded bridge keeps its header folded",
      "#### 🌉 Yesterday's bridge" + F + "\n> a new bridge\n---" in out, out)
check("a bullet inside a folded group still resolves",
      ps.find(d, "🗓️ Weekly") is not None and ps.find(d, "🔄 Habits") is not None)
check("normalized lookup sees through the fold too", ps.find(d, "Goals") is not None)

# ── a data-in-header section (the weekly's shape), folded
WEEKLY = "\n".join([
    "#### 📌 This Week",
    "##### ✅ Completed: 311 · 🟢 +12" + F,
    "- 🗂 Work: 200",
    "",
    "##### 👽 People",
    "- nobody",
    "",
])
w = ps.parse_sections(WEEKLY)
sec = ps.find_prefix(w, "✅ Completed")
check("find_prefix finds a folded data-in-header section", sec is not None)
check("set_header re-appends the fold comment",
      ps.set_header(sec, "✅ Completed: 400 · 🟢 +89") and sec.header == "##### ✅ Completed: 400 · 🟢 +89" + F,
      sec.header)
check("its name stays clean", sec.name == "✅ Completed: 400 · 🟢 +89", sec.name)
check("the same data again is no change", ps.set_header(sec, "✅ Completed: 400 · 🟢 +89") is False)
check("a caller passing a commented name never doubles the comment",
      ps.set_header(sec, "✅ Completed: 401" + F) and sec.header.count("<!--") == 1, sec.header)

# the real engine writer, end to end
w2 = ps.parse_sections(WEEKLY)
pe._set_headed(w2, "✅ Completed", "12 · 🔴 -3", ["- 🗂 Work: 12"])
o2 = ps.serialize_sections(w2)
check("_set_headed keeps a folded weekly section folded",
      "##### ✅ Completed: 12 · 🔴 -3" + F + "\n- 🗂 Work: 12\n" in o2, o2)
check("and leaves the unfolded neighbour alone", "##### 👽 People\n- nobody" in o2, o2)

# an unfolded header is written exactly as before
u = ps.parse_sections("### 🔥 Top list: old\n- a\n")
ps.set_header(ps.find_prefix(u, "🔥 Top list"), "🔥 Top list: new")
check("an unfolded header gains nothing", ps.serialize_sections(u) == "### 🔥 Top list: new\n- a\n",
      ps.serialize_sections(u))

# ── a folded bullet (defensive: the app may fold list items the same way)
b = ps.parse_sections("#### ☀️ Today\n- Completed: 3" + F + "\n\t- x\n")
blk = ps.find_prefix(b, "Completed")
check("a folded bullet is found by prefix", blk is not None and blk.name == "Completed: 3", blk and blk.name)
ps.set_header(blk, "Completed: 4")
check("and its rewrite keeps the comment",
      ps.serialize_sections(b) == "#### ☀️ Today\n- Completed: 4" + F + "\n\t- x\n", ps.serialize_sections(b))

print(f"fold comments: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
