#!/usr/bin/env python3
"""Every verb Scripts/xact.py's main() dispatches is a function that exists.

Vex 2026-10-05, 🥘 Meal Prep > 🔄 Sync with Mela: "meal_sync failed:
NameError: name 'meal_sync' is not defined". The OKR rewrite (a496ff3,
2026-10-03) deleted the whole meal verb block as collateral of the OKR
block around it, and main() kept dispatching to the nine names for two
days. A static read of the file, no import, no network: parse main()'s
`elif verb == "...": name(` ladder and demand a top-level `def name(`.
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import re
    import sys

    REPO = os.environ.get("TICKAL_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SRC = open(os.path.join(REPO, "Scripts", "xact.py"), encoding="utf-8").read()
    MAIN = SRC[SRC.index("\ndef main():"):]

    called = re.findall(r'(?:if|elif) verb == "([^"]+)":\n\s+([A-Za-z_][A-Za-z_0-9]*)\(', MAIN)
    defined = set(re.findall(r'^def ([A-Za-z_][A-Za-z_0-9]*)\(', SRC, re.M))
    FAILS, COUNT = [], [0]

    def check(label, ok):
        COUNT[0] += 1
        print(("  ok  " if ok else "  FAIL") + label)
        if not ok:
            FAILS.append(label)

    check("main() dispatches a real ladder (100+ verbs)", len(called) >= 100)
    missing = sorted({fn for _, fn in called if fn not in defined})
    check(f"every dispatched function is defined (missing: {missing or 'none'})", not missing)
    for verb in ("meal_sync", "meal_setlist", "meal_cooked", "meal_rate", "meal_comment",
                 "meal_portions", "meal_prices", "meal_price_set", "meal_price_search"):
        check(f"xact:{verb} dispatches and its function exists",
              any(v == verb for v, _ in called) and verb in defined)

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    sys.exit(1 if FAILS else 0)
