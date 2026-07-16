#!/usr/bin/env python3
"""
docs_menu.py - Alfred Script Filter: the TickAL docs surface (tdo keyword +
the main menu's 📜 Docs row, both via ET OpenDocs).

One window does both jobs: the top row live-searches the GitHub repo for
whatever is typed (⏎ opens GitHub code search scoped to the repo), and the
rows below open each doc page directly. Typing filters the page rows AND
feeds the search row, so there is no second window to hop through.

Args emitted: open:<url> - routed to src/dispatch.py by the canvas.
⌃⏎ goes back to the main menu (canvas ctrl edge; rows carry the mod).
"""
import sys
import os
import json
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap
    bootstrap()
    import alfred
    import fuzzy as fuzz
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

REPO = "vex-glitch/TickAL-TickTick-Alfred-Workflow"
BLOB = f"https://github.com/{REPO}/blob/main"

# (emoji, name, path, subtitle) - numeric doc order; README first.
PAGES = [
    ("📄", "README", "README.md", "The front page"),
    ("🏠", "Home", "docs/00-index.md", "Docs map - every page"),
    ("🚀", "Getting started", "docs/10-getting-started.md", "Install to first task"),
    ("🧠", "Concepts", "docs/20-concepts.md", "The vocabulary every page assumes"),
    ("🔧", "Setup", "docs/30-setup.md", "Credentials, login, token, ids"),
    ("🔎", "Search", "docs/40-search.md", "One bar, thirteen scopes"),
    ("⤵️", "Browse & drill", "docs/41-browse-drill.md", "The ⌥⏎ ladder"),
    ("➕", "Add", "docs/42-add.md", "The token grammar"),
    ("⚡", "Actions", "docs/43-actions.md", "Everything behind ⌘⏎"),
    ("📝", "Notes, links & images", "docs/44-notes-links-images.md", "Notes, stickies, task links, attachments"),
    ("🖥", "Views", "docs/45-views.md", "Habits, Pomodoro, Matrix, Calendar, Stats"),
    ("🎯", "Focus", "docs/46-focus.md", "Sessions, staging, sweep, the bar"),
    ("📈", "CRM", "docs/47-crm.md", "Bookings, 🔥 tags, Prepare follow-ups"),
    ("💫", "Periodic notes", "docs/48-periodic.md", "Daily to yearly, journals, roll-ups"),
    ("💼", "Projects", "docs/49-projects.md", "P flow, CTAs, keycap areas"),
    ("⚙️", "Settings & sync", "docs/90-settings-sync.md", "The tup menu, cache, agents"),
    ("⌨️", "Cheatsheet", "docs/95-cheatsheet.md", "Every keyword and keystroke"),
    ("🚑", "Troubleshooting", "docs/99-troubleshooting.md", "Symptom, cause, fix"),
]

BACK = {"ctrl": {"valid": True, "arg": "", "subtitle": "🔙 Main menu"}}


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip()

    if query:
        q = urllib.parse.quote_plus(f"repo:{REPO} {query}")
        search_url = f"https://github.com/search?q={q}&type=code"
        search = alfred.item(
            uid="docs-search",
            title=f'🔎 Search docs for "{query}"',
            subtitle="⏎ GitHub search across the whole repo",
            arg=f"open:{search_url}",
            mods=BACK,
        )
    else:
        search = alfred.item(
            uid="docs-search",
            title="🔎 Search docs for…",
            subtitle="Type, then ⏎ searches the repo on GitHub",
            valid=False,
            mods=BACK,
        )

    rows = [alfred.item(
        uid=f"doc-{path}",
        title=f"{emoji} {name}",
        subtitle=sub,
        arg=f"open:{BLOB}/{path}",
        mods=BACK,
    ) for emoji, name, path, sub in PAGES]

    if query:
        rows = fuzz.filter_and_score(query, rows, key_fn=lambda r: r["title"])

    print(alfred.output([search] + rows, skipknowledge=True))


if __name__ == "__main__":
    main()
