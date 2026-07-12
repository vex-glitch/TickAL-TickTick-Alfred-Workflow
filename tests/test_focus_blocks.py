#!/usr/bin/env python3
"""Unit suite for src/focus_blocks.py. Pure stdlib.
Run: python3 tests/test_focus_blocks.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import focus_blocks as fb  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


# ── Fixture: server-shaped note (checkbox block + separator + tail) ────
NOTE = ("### 2026-07-07\n"
      "- [x] [Demo sub one (delete me)](https://ticktick.com/webapp/#p/inbox000000001/tasks/abcabcabcabcabcabcabcabc) \n"
      "- [x] [Demo sub two (delete me)](https://ticktick.com/webapp/#p/inbox000000001/tasks/defdefdefdefdefdefdefdef) \n"
      "- [ ] freehand api-added line\n"
      "---\n"
      "original description line · must survive untouched")

# title containing an embedded markdown link (the TRAILING link must win)
TRICKY = ("### 2026-07-06\n"
          "- [ ] [📁 P • [Nested](ticktick:///webapp/#p/x/tasks) 🔗](https://ticktick.com/webapp/#p/aaaabbbbccccddddeeeeffff/tasks/123412341234123412341234) \n"
          "---")

ROUND_TRIPS = [
    ("note-fixture", NOTE),
    ("empty", ""),
    ("plain-tail-only", "just a description\nwith two lines"),
    ("tail-looks-separator", "notes\n---\nmore notes"),
    ("header-no-separator", "### 2026-07-07\n- [ ] free box"),
    ("trailing-newline-after-sep", "### 2026-07-07\n- [ ] a\n---\n"),
    ("multi-block", "### 2026-07-07\n- [ ] a\n---\n### 2026-07-05\n- [x] b\n---\ntail"),
    ("blanks-between-blocks", "### 2026-07-07\n- [ ] a\n---\n\n\n### 2026-07-05\n- [x] b\n---"),
    ("lead-blanks", "\n\n### 2026-07-07\n- [ ] a\n---\ntail"),
    ("tricky-title-link", TRICKY),
    ("free-lines-in-block", "### 2026-07-07\nsome freehand note\n- [ ] a\n\nmore notes\n---"),
]

print("-- round-trip idempotence --")
for name, c in ROUND_TRIPS:
    got = fb.serialize(fb.parse(c))
    check(f"roundtrip:{name}", got == c, f"\n    in : {c!r}\n    out: {got!r}")

print("-- parse classification (note fixture) --")
doc = fb.parse(NOTE)
check("one block", len(doc.blocks) == 1)
check("date", doc.blocks[0].date == "2026-07-07")
cbs = [l for l in doc.blocks[0].lines if l.kind == "checkbox"]
check("3 checkboxes", len(cbs) == 3)
check("two checked linked", cbs[0].checked and cbs[1].checked
      and cbs[0].tid == "abcabcabcabcabcabcabcabc"
      and cbs[1].tid == "defdefdefdefdefdefdefdef")
check("freehand unchecked no tid", (not cbs[2].checked) and cbs[2].tid is None)
check("tail preserved", doc.tail == "original description line · must survive untouched")
check("pid parsed incl. inbox form", cbs[0].pid == "inbox000000001")

print("-- tricky title (embedded md link) --")
tdoc = fb.parse(TRICKY)
tl = tdoc.blocks[0].lines[0]
check("tid from TRAILING link", tl.tid == "123412341234123412341234")
check("pid from TRAILING link", tl.pid == "aaaabbbbccccddddeeeeffff")

print("-- ensure_today / carry-over --")
c = ("### 2026-07-05\n"
     "- [x] [done then](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/111111111111111111111111) \n"
     "- [ ] [left over](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/222222222222222222222222) \n"
     "session notes stay here\n"
     "---\n"
     "### 2026-07-01\n"
     "- [ ] [ancient](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/333333333333333333333333) \n"
     "---\n"
     "tail")
doc = fb.parse(c)
checked_raw_before = doc.blocks[0].lines[0].raw
blk = fb.ensure_today(doc, "2026-07-07")
check("new block at front", doc.blocks[0] is blk and blk.date == "2026-07-07")
check("carry-over order newest-old first",
      [l.tid for l in blk.lines] == ["222222222222222222222222", "333333333333333333333333"])
check("old block keeps checked+free",
      [l.raw for l in doc.blocks[1].lines] == [checked_raw_before, "session notes stay here"])
out = fb.serialize(doc)
check("emptied old block dropped from output", "### 2026-07-01" not in out)
check("checked line byte-identical after carry-over", checked_raw_before in out)
check("tail still verbatim", out.endswith("\ntail"))

print("-- insert dedupe --")
doc = fb.parse("### 2026-07-07\n"
               "- [ ] [open one](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/111111111111111111111111) \n"
               "- [x] [done one](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/222222222222222222222222) \n"
               "---")
added, skipped = fb.insert_checkboxes(doc, "2026-07-07", [
    ("p", "111111111111111111111111", "open one again"),   # unchecked → skip
    ("p", "222222222222222222222222", "done one again"),   # checked → allowed
    ("p", "444444444444444444444444", "brand new"),
    ("p", "444444444444444444444444", "brand new dupe"),   # dupe within batch → skip
])
check("added 2 / skipped 2", (added, skipped) == (2, 2), f"got {(added, skipped)}")
check("appended at block bottom",
      doc.blocks[0].lines[-1].raw.startswith("- [ ] [brand new]"))

print("-- tick --")
doc = fb.parse(NOTE)
line = fb.tick(doc, "2026-07-07")
check("ticks first unchecked (the freehand)", line is not None and line.tid is None
      and "- [x] freehand api-added line" == line.raw)
check("nothing left to tick", fb.tick(doc, "2026-07-07") is None)
doc = fb.parse("### 2026-07-07\n"
               "- [ ] [a](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/111111111111111111111111) \n"
               "- [ ] [b](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/222222222222222222222222) \n"
               "---")
line = fb.tick(doc, "2026-07-07", target_tid="222222222222222222222222")
check("tick by ctid", line is not None and line.tid == "222222222222222222222222"
      and doc.blocks[0].lines[0].checked is False)
check("midnight fallback: tick on blocks[0] when no exact date",
      fb.tick(doc, "2026-07-08") is not None)

print("-- sweep_targets --")
doc = fb.parse("### 2026-07-07\n"
               "- [x] [a](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/111111111111111111111111) \n"
               "- [ ] [b](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/222222222222222222222222) \n"
               "- [x] freehand done\n"
               "---\n"
               "### 2026-07-05\n"
               "- [x] [a again](https://ticktick.com/webapp/#p/aaaaaaaaaaaaaaaaaaaaaaaa/tasks/111111111111111111111111) \n"
               "- [x] [c](https://ticktick.com/webapp/#p/bbbbbbbbbbbbbbbbbbbbbbbb/tasks/333333333333333333333333) \n"
               "---")
tg = fb.sweep_targets(doc)
check("checked+linked only, deduped, doc order",
      tg == [("aaaaaaaaaaaaaaaaaaaaaaaa", "111111111111111111111111"),
             ("bbbbbbbbbbbbbbbbbbbbbbbb", "333333333333333333333333")], f"got {tg}")

print("-- today_note / block_summary --")
doc = fb.parse(NOTE)
note = fb.today_note(doc, "2026-07-07")
check("note = header + all raw lines",
      note.startswith("### 2026-07-07\n- [x] [Demo sub one")
      and note.endswith("- [ ] freehand api-added line"))
check("note fallback to blocks[0]",
      fb.today_note(doc, "2026-07-09") == note)
s = fb.block_summary(doc, "2026-07-07")
check("summary counts", (s["done"], s["total"]) == (2, 3), f"got {s}")
check("summary titles", s["items"][0]["title"] == "Demo sub one (delete me)"
      and s["items"][2]["title"] == "freehand api-added line")
check("summary url only for linked", s["items"][0]["url"] is not None
      and s["items"][2]["url"] is None)
check("empty doc summary", fb.block_summary(fb.parse(""), "2026-07-07")["total"] == 0)

print("-- ensure_today idempotent on same day --")
doc = fb.parse(NOTE)
b1 = fb.ensure_today(doc, "2026-07-07")
check("returns existing today block", b1 is doc.blocks[0] and len(doc.blocks) == 1)

print("-- empty-block noise guard --")
doc = fb.parse("plain description")
fb.ensure_today(doc, "2026-07-07")  # creates empty block…
check("empty today block not emitted",
      fb.serialize(doc) == "plain description")

print()
if FAILS:
    print(f"❌ {len(FAILS)} failures: {FAILS}")
    sys.exit(1)
print("✅ all green")
