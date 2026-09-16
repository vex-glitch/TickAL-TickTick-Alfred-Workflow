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

# ── bar_safe: text from somewhere else, typed into the bar ──────────────────
check("a page title's pipe stops carving subtasks",
      sl.bar_safe("Easy chicken curry | BBC Good Food")
      == "Easy chicken curry · BBC Good Food",
      sl.bar_safe("Easy chicken curry | BBC Good Food"))
check("and the result really does survive the splitter",
      sl.split_line(sl.bar_safe("Easy chicken curry | BBC Good Food"))
      == ("Easy chicken curry · BBC Good Food", []))
check("a tag would have been minted", sl.bar_safe("Recipe #5") == "Recipe 5")
check("so would a date span", sl.bar_safe("Best *tonight") == "Best tonight")
check("and a note marker", sl.bar_safe("Rate = love") == "Rate love")
check("ordinary punctuation survives: & is only a repeat before a preset",
      sl.bar_safe("Fish & Chips") == "Fish & Chips"
      and sl.bar_safe("Q&A: the best") == "Q&A: the best"
      and sl.bar_safe("Daily &weekly planner") == "Daily weekly planner")
check("% is only a reminder before a token",
      sl.bar_safe("Sale 50% off") == "Sale 50% off")
check("> is only a duration before a digit",
      sl.bar_safe("2020 > 2021") == "2020 > 2021"
      and sl.bar_safe("Top >3 picks") == "Top 3 picks")
check("! is only a priority before 1-3, and only the trigger goes",
      sl.bar_safe("Wait! Really") == "Wait! Really"
      and sl.bar_safe("Do it !2 now") == "Do it 2 now",
      sl.bar_safe("Do it !2 now"))
check("a pile of triggers is peeled to the words",
      sl.bar_safe("~*#=/ nested") == "nested", sl.bar_safe("~*#=/ nested"))
check("mid-word triggers are text", sl.bar_safe("C# in 2026") == "C# in 2026")
check("a trailing trigger would open an empty picker",
      sl.bar_safe("Top 10 tips #") == "Top 10 tips")
check("dropping one exposes the next",
      sl.bar_safe("~/.config explained") == ".config explained",
      sl.bar_safe("~/.config explained"))
check("wikilink brackets cannot reopen the picker",
      sl.bar_safe("[[Weekly note]] tips") == "((Weekly note)) tips")
check("whitespace is squeezed, empties survive",
      sl.bar_safe("  a   b  ") == "a b" and sl.bar_safe("") == ""
      and sl.bar_safe(None) == "")

check("the standalone markers cannot be armed by a page title",
      sl.bar_safe("Top ^ picks") == "Top picks"
      and sl.bar_safe("Build +focus habits") == "Build focus habits"
      and sl.bar_safe("The +stage show") == "The stage show"
      and sl.bar_safe("A +web of lies") == "A web of lies",
      sl.bar_safe("Build +focus habits"))
check("a word-initial @ always goes: the time picker opens on any of them",
      sl.bar_safe("Wine & Dine @ Nobu") == "Wine & Dine Nobu"
      and sl.bar_safe("Best of @user") == "Best of user")
check("but a + that is not a marker is text",
      sl.bar_safe("C++ notes") == "C++ notes"
      and sl.bar_safe("1 + 1 = 2") == "1 + 1 2", sl.bar_safe("1 + 1 = 2"))

# ── splice_title: the name joins the TITLE, not whatever token is last ──────
check("with no tokens it simply joins",
      sl.splice_title("u +web ", "Monday Night Football")
      == "u +web Monday Night Football")
check("an open date span does not swallow the name",
      sl.splice_title("u +web *sat ", "Monday Night Football")
      == "u +web Monday Night Football *sat",
      sl.splice_title("u +web *sat ", "Monday Night Football"))
check("every token keeps its place",
      sl.splice_title("u +web ~l Reading *sat ", "Big Game")
      == "u +web Big Game ~l Reading *sat")
check("an empty name changes nothing",
      sl.splice_title("u +web *sat ", "") == "u +web *sat ")
check("a token inside a link is not a token",
      sl.splice_title("u [a](https://x.com/a?b=1) ", "Name")
      == "u [a](https://x.com/a?b=1) Name",
      sl.splice_title("u [a](https://x.com/a?b=1) ", "Name"))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
