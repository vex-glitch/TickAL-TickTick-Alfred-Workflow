#!/usr/bin/env python3
"""Unit suite for src/mdtext.py (the no-nested-links rule).
Run: python3 tests/test_mdtext.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import mdtext as md  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


STEP = "[Money](kmtrigger://macro=2DC599C6)"

check("a link title flattens to its label", md.flatten_links(STEP) == "Money")
check("plain text is untouched", md.flatten_links("Work") == "Work")
check("empty and None survive",
      md.flatten_links("") == "" and md.flatten_links(None) == "")
check("a link inside a sentence flattens in place",
      md.flatten_links("see [docs](http://x) now") == "see docs now")
check("two links both flatten",
      md.flatten_links("[a](u) and [b](v)") == "a and b")

check("a literal bracket becomes a paren, never vanishes",
      md.link_text("Rebecca • Sleeve [250]") == "Rebecca • Sleeve (250)",
      md.link_text("Rebecca • Sleeve [250]"))
check("so the label can no longer end early",
      "[" not in md.link_text("a ] b [ c") and "]" not in md.link_text("a ] b [ c"))
check("a trailing backslash is dropped", md.link_text("path\\\\") == "path")
check("the limit trims cleanly",
      md.link_text("one two three four", limit=8) == "one two")

check("a wrapped link carries exactly one link",
      md.md_link(STEP, "https://t/x").count("](") == 1,
      md.md_link(STEP, "https://t/x"))
check("the label is the inner one",
      md.md_link(STEP, "https://t/x") == "[Money](https://t/x)")
check("a plain title wraps as itself",
      md.md_link("Work", "https://t/x") == "[Work](https://t/x)")

# the round trip every reader does: label then url, no inner bracket
import re  # noqa: E402
READER = re.compile(r"\[([^\]]*)\]\((https://t/[a-z]+)\)")
m = READER.fullmatch(md.md_link(STEP, "https://t/x"))
check("a reader keyed on [^]]* still parses it", bool(m), md.md_link(STEP, "https://t/x"))
check("and gets the label back", m and m.group(1) == "Money")

# ── 🔗 entry grammar: clipboard is the URL, typed words are the label
check("clipboard url + typed label",
      md.link_entry("Anthropic docs", "https://docs.anthropic.com/en/api")
      == "[Anthropic docs](https://docs.anthropic.com/en/api)")
check("no label falls back to the host",
      md.link_entry("", "https://www.example.com/a/b")
      == "[example.com](https://www.example.com/a/b)")
check("a typed url beats the clipboard",
      md.link_entry("Read this https://example.com/a/b now", "https://other.com")
      == "[Read this now](https://example.com/a/b)")
check("brackets in a label become parens",
      md.link_entry("Sleeve [250] ref", "https://pin.it/abc")
      == "[Sleeve (250) ref](https://pin.it/abc)")
check("a copied markdown link keeps its target, takes a new name",
      md.link_entry("My note", "[Old](https://x.com/1)")
      == "[My note](https://x.com/1)")
check("a copied markdown link alone survives whole",
      md.link_entry("", "[Old](https://x.com/1)") == "[Old](https://x.com/1)")
check("any scheme counts, not just http",
      md.link_entry("KM macro", "kmtrigger://macro=ABC")
      == "[KM macro](kmtrigger://macro=ABC)")
check("no url anywhere is still a note",
      md.link_entry("just a thought", "not a url") == "just a thought")
check("nothing at all is nothing", md.link_entry("", "") is None)
check("the built entry survives the reader",
      md.MD_LINK_RE.fullmatch(md.link_entry("a b", "https://x.com/1")) is not None)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
