#!/usr/bin/env python3
"""Unit suite for src/ask_box.py - the pure half (no window is opened).
Run: python3 tests/test_ask_box.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import ask_box  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


check("available() answers without raising", ask_box.available() in (True, False))

check("trailing space on every line comes off",
      ask_box._tidy("one  \ntwo\t\n") == "one\ntwo", repr(ask_box._tidy("one  \ntwo\t\n")))
check("a paragraph break he typed survives",
      ask_box._tidy("one\n\ntwo") == "one\n\ntwo")
check("blank lines top and bottom go, the indent is left to the merge",
      ask_box._tidy("\n\n  one\n\n") == "  one", repr(ask_box._tidy("\n\n  one\n\n")))
check("leading indent inside a line is his, and stays",
      ask_box._tidy("one\n   two") == "one\n   two")
check("windows and classic-mac line ends normalise",
      ask_box._tidy("a\r\nb\rc") == "a\nb\nc", repr(ask_box._tidy("a\r\nb\rc")))
check("empty stays empty, so an empty Save still reads as skip",
      ask_box._tidy("") == "" and ask_box._tidy("   \n  \n") == ""
      and ask_box._tidy(None) == "")
check("one line is untouched", ask_box._tidy("just this") == "just this")

# ── placement: centred on the menu-bar screen, a third of the spare height down
WIDE = (0, 0, 3840, 1080)            # Vex's main display
check("centred on the wide screen, and the live numbers reproduce",
      ask_box._origin(WIDE, WIDE, (592, 478)) == (1624, 401),
      ask_box._origin(WIDE, WIDE, (592, 478)))
_x, _y = ask_box._origin(WIDE, WIDE, (592, 478))
check("the window centre IS the screen centre", _x + 592 / 2 == 3840 / 2)
check("the gap above is a third of the spare height",
      round(1080 - (_y + 478)) == round((1080 - 478) / 3))
check("a screen with an offset origin is handled",
      ask_box._origin((3840, 15, 1080, 1920), (3840, 15, 1080, 1920), (592, 478))
      == (4084, 976), ask_box._origin((3840, 15, 1080, 1920), (3840, 15, 1080, 1920), (592, 478)))
check("the Dock and menu bar are never covered",
      ask_box._origin(WIDE, (0, 80, 3840, 975), (592, 1040))[1] == 80,
      ask_box._origin(WIDE, (0, 80, 3840, 975), (592, 1040)))
check("a box wider than the screen still starts on it",
      ask_box._origin(WIDE, WIDE, (5000, 478))[0] == 0)

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
