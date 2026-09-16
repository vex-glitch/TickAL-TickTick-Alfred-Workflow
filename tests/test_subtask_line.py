#!/usr/bin/env python3
"""Unit suite for src/subtask_line.py (the '|' subtask grammar).
Run: python3 tests/test_subtask_line.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import subtask_line as sl  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


# ── splitting ───────────────────────────────────────────────────────────────
check("Vex's line splits head + kids",
      sl.split_line("Buy groceries | Milk | Bread")
      == ("Buy groceries", ["Milk", "Bread"]))
check("no pipe = no subtasks",
      sl.split_line("Buy groceries") == ("Buy groceries", []))
check("empty line survives", sl.split_line("") == ("", []))
check("None survives", sl.split_line(None) == ("", []))
check("a trailing pipe is not a nameless subtask",
      sl.split_line("Buy groceries | ") == ("Buy groceries", []))
check("inner empties drop",
      sl.split_line("A |  | B") == ("A", ["B"]))
check("whitespace is squeezed",
      sl.split_line("  Buy   groceries |   Milk  ") == ("Buy groceries", ["Milk"]))
check("a leading pipe still names the first thing typed",
      sl.split_line("| Milk | Bread") == ("Milk", ["Bread"]))

# a pipe inside a link is TEXT
check("a pipe inside a wikilink is not a separator",
      sl.split_line("Read [[Plan | Q4]] now") == ("Read [[Plan | Q4]] now", []))
check("a pipe inside a markdown link is not a separator",
      sl.split_line("[Start](kmtrigger://macro=A|B) | Milk")
      == ("[Start](kmtrigger://macro=A|B)", ["Milk"]))
check("a real separator after a link still splits",
      sl.split_line("[[Some Task]] | Milk") == ("[[Some Task]]", ["Milk"]))

# ── mode ────────────────────────────────────────────────────────────────────
check("a trailing pipe means we are still adding subtasks",
      sl.in_subtask_mode("Buy groceries | "))
check("no pipe, no mode", not sl.in_subtask_mode("Buy groceries"))
check("a pipe inside a link does not open the mode",
      not sl.in_subtask_mode("Read [[Plan | Q4]]"))

# ── next_query: the ➕ row ───────────────────────────────────────────────────
check("plain line gets one separator",
      sl.next_query("Buy groceries") == "Buy groceries | ")
check("a line already in the mode does not double up",
      sl.next_query("Buy groceries | ") == "Buy groceries | ")
check("the separator lands BEFORE the tokens",
      sl.next_query("Buy groceries ~Money #buy") == "Buy groceries | ~Money #buy",
      sl.next_query("Buy groceries ~Money #buy"))
check("a second round keeps one separator per subtask",
      sl.next_query("Buy groceries | Milk ~Money") == "Buy groceries | Milk | ~Money",
      sl.next_query("Buy groceries | Milk ~Money"))
check("a date token counts as a token",
      sl.next_query("Pay rent *tomorrow") == "Pay rent | *tomorrow")
check("an empty query is survivable", sl.next_query("") == "| ",
      repr(sl.next_query("")))

# the round trip that matters: what the user sees typed, parsed back
q = sl.next_query("Buy groceries ~Money #buy")
check("round trip: tokens stripped, pipes intact",
      sl.split_line(q.replace("~Money", "").replace("#buy", "").strip() + " Bread")
      == ("Buy groceries", ["Bread"]),
      sl.split_line(q.replace("~Money", "").replace("#buy", "").strip() + " Bread"))

# ── chip ────────────────────────────────────────────────────────────────────
check("sibling chip does not claim they are its children",
      sl.chip(["a"], sibling=True) == "+ 1 more"
      and sl.chip(["a", "b"], sibling=True) == "+ 2 more")
check("chip counts", sl.chip(["a"]) == "+ 1 subtask"
      and sl.chip(["a", "b"]) == "+ 2 subtasks" and sl.chip([]) == ""
      and sl.chip(None) == "")

# ── a bare url is opaque too: a pipe inside one is TEXT ─────────────────────
check("a pipe inside a typed url is not a separator",
      sl.split_line("https://fonts.googleapis.com/css?family=A|B Fonts | kid")
      == ("https://fonts.googleapis.com/css?family=A|B Fonts", ["kid"]),
      sl.split_line("https://fonts.googleapis.com/css?family=A|B Fonts | kid"))
check("a url with balanced parens survives whole",
      sl.split_line("https://en.wikipedia.org/wiki/Foo_(bar) | kid")
      == ("https://en.wikipedia.org/wiki/Foo_(bar)", ["kid"]))
check("any scheme, not just http",
      sl.split_line("crouton://viewRecipe?id=A|B | kid")
      == ("crouton://viewRecipe?id=A|B", ["kid"]))
check("and the ordinary pipes still carve",
      sl.split_line("Buy groceries | Milk | Bread")
      == ("Buy groceries", ["Milk", "Bread"]))
check("a url with no pipe is untouched",
      sl.split_line("Read https://x.com/a now") == ("Read https://x.com/a now", []))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
