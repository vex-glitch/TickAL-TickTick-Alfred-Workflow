#!/usr/bin/env python3
"""Unit suite for src/browser_tab.py (the front tab, and its 2 second cache).
No real browser and no AppleScript: the osascript door and the process list
are stubbed, so this runs anywhere.
Run: python3 tests/test_browser_tab.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import browser_tab as bt  # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


TOLD = []


def stub(running, tabs, answers=None):
    """Pretend `running` apps exist and each has the tab in `tabs`."""
    del TOLD[:]
    bt.running_apps = lambda: set(running)

    def _osa(script, timeout=5):
        for app in sorted(tabs, key=len, reverse=True):
            if f'application "{app}"' in script:
                TOLD.append(app)
                return tabs[app]
        if "frontmost" in script:
            return (answers or {}).get("front", "")
        return None
    bt._osa = _osa


TAB = "https://bbcgoodfood.com/r/1\nEasy curry | BBC"

# ── family ──────────────────────────────────────────────────────────────────
check("the two dialects are told apart",
      bt.family("Safari") == "safari" and bt.family("Arc") == "chromium"
      and bt.family("TickTick") is None and bt.family("") is None)

# ── read ────────────────────────────────────────────────────────────────────
stub(["Safari"], {"Safari": TAB})
check("url and title come back from ONE call",
      bt.read("Safari") == ("https://bbcgoodfood.com/r/1", "Easy curry | BBC"),
      bt.read("Safari"))
check("and that really was one call", len(TOLD) == 2, TOLD)   # two read() calls

stub(["Safari"], {"Safari": "https://x.com/a"})
check("a tab with no title is still a tab",
      bt.read("Safari") == ("https://x.com/a", ""))

stub(["Safari"], {"Safari": "about:blank\nNew Tab"})
check("a non-web scheme is not a link", bt.read("Safari") == (None, None))

stub(["Safari"], {})
check("an app that answers nothing is not a tab",
      bt.read("Safari") == (None, None))

check("a non-browser is never asked at all",
      bt.read("TickTick") == (None, None) and TOLD == [])

# ── front_tab ───────────────────────────────────────────────────────────────
stub(["Arc", "Safari"], {"Safari": TAB, "Arc": "https://arc.example/x\nArc page"})
app, url, title = bt.front_tab(prefer_front=False)
check("PRIORITY order decides when several browsers run",
      (app, url) == ("Safari", "https://bbcgoodfood.com/r/1"), (app, url))

stub(["Arc"], {"Safari": TAB, "Arc": "https://arc.example/x\nArc page"})
app, url, _t = bt.front_tab(prefer_front=False)
check("a browser that is NOT running is never told (it would launch it)",
      (app, url) == ("Arc", "https://arc.example/x") and "Safari" not in TOLD,
      (app, url, TOLD))

stub(["TickTick", "Crouton"], {"Safari": TAB})
check("no browser running is an honest empty answer",
      bt.front_tab(prefer_front=False) == ("", None, None))
check("and nothing was told anything", TOLD == [], TOLD)

stub(["Safari"], {"Safari": TAB}, answers={"front": "Safari"})
app, url, _t = bt.front_tab(prefer_front=True)
check("the frontmost browser is read first (the hotkey road)",
      (app, url) == ("Safari", "https://bbcgoodfood.com/r/1"))

# ── cached ──────────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
bt._cache_path = lambda: os.path.join(tmp, "tab.json")

stub(["Safari"], {"Safari": TAB})
hit = bt.cached(now=1000.0)
check("a miss probes and answers",
      hit == {"app": "Safari", "url": "https://bbcgoodfood.com/r/1",
              "title": "Easy curry | BBC"}, hit)
check("and it was written down", os.path.isfile(bt._cache_path()))

stub([], {})                                   # nothing runs any more
check("inside the window the cache answers, nothing is probed",
      bt.cached(now=1001.0)["url"] == "https://bbcgoodfood.com/r/1"
      and TOLD == [], TOLD)
check("past the window it probes again",
      bt.cached(now=1100.0)["url"] == "")

stub(["Safari"], {"Safari": TAB})
check("a MISS is cached too, or a browserless machine re-probes every letter",
      bt.cached(now=1101.0)["url"] == "" and TOLD == [], TOLD)

with open(bt._cache_path(), "w") as f:
    f.write("{not json")
stub(["Safari"], {"Safari": TAB})
check("a corrupt cache re-probes instead of raising",
      bt.cached(now=2000.0)["url"] == "https://bbcgoodfood.com/r/1")

bt._cache_path = lambda: "/nope/not/a/dir/tab.json"
stub(["Safari"], {"Safari": TAB})
check("an unwritable cache still answers",
      bt.cached(now=3000.0)["url"] == "https://bbcgoodfood.com/r/1")

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
