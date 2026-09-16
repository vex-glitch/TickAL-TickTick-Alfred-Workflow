#!/usr/bin/env python3
"""Unit suite for src/clipboard.py text/url/link_source (the 🔗 read).
No real pasteboard: the AppKit accessor is stubbed, so this runs anywhere.
Run: python3 tests/test_clipboard.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import clipboard as clip  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


class FakePB:
    """Only what clipboard.url() touches."""
    def __init__(self, flavors):
        self._f = flavors

    def stringForType_(self, t):
        return self._f.get(t)


def with_pb(flavors, text=""):
    clip._pasteboard = lambda: (FakePB(flavors) if flavors is not None else None)
    clip.text = lambda: text


# The legacy flavor is a plist ARRAY of [url, title]; read as a string it is a
# whole XML document whose only URL is Apple's DTD. Reading it once linked a
# copied FILE to apple.com, which is why url() validates.
APPLE_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC '
             '"-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/'
             'PropertyList-1.0.dtd">\n<plist version="1.0"><array><string>'
             'file:///Users/v/a.md</string><string></string></array></plist>')

with_pb({"public.url": APPLE_XML})
check("a flavor that is not a bare url is dropped", clip.url() == "", clip.url())

with_pb({"public.url": "crouton://viewRecipe?id=8435"})
check("the Crouton shape comes back whole",
      clip.url() == "crouton://viewRecipe?id=8435", clip.url())

with_pb({"public.url": "  https://x.com/a  "})
check("and is trimmed", clip.url() == "https://x.com/a")

with_pb({"public.file-url": "file:///Users/v/a.md"})
check("a copied file is a link too", clip.url() == "file:///Users/v/a.md")

with_pb({"public.url": "not a url at all"})
check("prose on the url flavor is dropped", clip.url() == "")

with_pb({})
check("no flavor is no url", clip.url() == "")

with_pb(None)
check("no pasteboard at all never raises", clip.url() == "")

# ── link_source: text first, url flavor only when the text holds none ───────
with_pb({"public.url": "https://flavor.example/y"}, text="https://typed.example/x")
check("text that holds a url wins, the slow rung is never paid",
      clip.link_source() == "https://typed.example/x")

with_pb({"public.url": "https://flavor.example/y"}, text="")
check("a url-only clipboard is found (the Crouton case)",
      clip.link_source() == "https://flavor.example/y")

with_pb({"public.url": "https://flavor.example/y"}, text="The page title")
check("a copied hyperlink keeps its href, not its title",
      clip.link_source() == "https://flavor.example/y")

with_pb({}, text="just some words")
check("plain text with no url anywhere comes back as itself",
      clip.link_source() == "just some words")

with_pb({"public.url": APPLE_XML}, text="")
check("and the plist blob never becomes a link", clip.link_source() == "")

with_pb({"public.url": "https://x.com/1"}, text="[Named](https://x.com/1)")
check("a copied markdown link is text, so it stays text",
      clip.link_source() == "[Named](https://x.com/1)")

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
