#!/usr/bin/env python3
"""
open_calendar.py — Alfred Script Filter
Lists TickTick calendar views to open in the browser.
Outputs the URL as arg → connected to Open URL action.
"""
import sys
import os

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
sys.path.insert(0, SRC_DIR)

import alfred
import fuzzy as fuzz

VIEWS = [
    ("Day",   "d"),
    ("Week",  "w"),
    ("Month", "m"),
    ("Year",  "y"),
]

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""

    items = [
        alfred.item(title=label, subtitle=url, arg=url)
        for label, url in VIEWS
    ]

    if query:
        items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

    if not items:
        items = [alfred.item(title=f'No views matching "{query}"', valid=False)]

    print(alfred.output(items, skipknowledge=True))

if __name__ == "__main__":
    main()
