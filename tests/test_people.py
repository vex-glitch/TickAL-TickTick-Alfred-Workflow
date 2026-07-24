#!/usr/bin/env python3
"""Unit suite for the 👽 People pure model (src/people.py).

No I/O, no credentials. Run:

    python3 tests/test_people.py
"""
import os
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import people as pe

PASS = FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


# ── 1. title grammar ─────────────────────────────────────────────────────────
check("1.title", pe.person_title("Goga") == "👽H • Goga")
check("1.name", pe.person_name("👽H • Goga") == "Goga")
check("1.name-archive", pe.person_name("👽H • Goga · 🗄️ 2026.07.24") == "Goga")
check("1.is-person", pe.is_person("👽H • Goga"))
check("1.not-person-archive",
      not pe.is_person("👽H • Goga · 🗄️ 2026.07.24"))
check("1.not-person-plain", not pe.is_person("Buy milk"))
check("1.is-archive", pe.is_archive("👽H • Goga · 🗄️ 2026.07.24"))
check("1.archive-title",
      pe.archive_title("Goga", date(2026, 7, 24))
      == "👽H • Goga · 🗄️ 2026.07.24")

# ── 2. circles ───────────────────────────────────────────────────────────────
check("2.of", pe.circle_of(["👽family"]) == "👽family")
check("2.of-cased", pe.circle_of(["👽Family"]) == "👽family")
check("2.of-none", pe.circle_of(["📅crm"]) == "")
check("2.chip", pe.circle_chip(["👽friends"]) == "🍻")
check("2.five", len(pe.CIRCLES) == 5)

# ── 3. card fields + birthday grammar ────────────────────────────────────────
CARD = ("## 📇 Card\nBirthday: 1993/06/27\nPhone: +49 151 123\n"
        "Mail: a@b.c\n\n## 🎁 Ideas\n- socks\n\n## 🧾 Log\n")
check("3.field", pe.card_field(CARD, "Phone") == "+49 151 123")
check("3.field-missing", pe.card_field(CARD, "Nope") == "")
check("3.bday-ymd", pe.parse_birthday("1993/06/27") == (1993, 6, 27))
check("3.bday-ymd-dash", pe.parse_birthday("1993-06-27") == (1993, 6, 27))
check("3.bday-dmy-dots", pe.parse_birthday("27.06.1993") == (1993, 6, 27))
check("3.bday-dm-dots", pe.parse_birthday("27.06.") == (None, 6, 27))
check("3.bday-md-slash", pe.parse_birthday("06/27") == (None, 6, 27))
check("3.bday-swapped", pe.parse_birthday("27/06") == (None, 6, 27))
check("3.bday-empty", pe.parse_birthday("") is None)
check("3.bday-junk", pe.parse_birthday("sometime") is None)
check("3.bday-bad-date", pe.parse_birthday("1993/02/31") is None)

# ── 4. log: insert prepends, missing heading appends ─────────────────────────
l1 = pe.log_line("met at market", datetime(2026, 7, 24, 14, 30))
check("4.line", l1 == "- 2026-07-24 14:30 - met at market")
c2 = pe.log_insert(CARD, l1)
check("4.prepend-under-heading",
      "## 🧾 Log\n- 2026-07-24 14:30 - met at market" in c2, repr(c2[-70:]))
c3 = pe.log_insert(c2, "- 2026-07-25 09:00 - called")
check("4.newest-on-top", c3.index("2026-07-25") < c3.index("2026-07-24"))
check("4.card-untouched", "Birthday: 1993/06/27" in c3)
nolog = pe.log_insert("plain text", "- 2026-07-24 10:00 - x")
check("4.heading-minted", "## 🧾 Log\n- 2026-07-24 10:00 - x" in nolog)
mid = ("## 🧾 Log\n- 2026-07-01 08:00 - old\n\n## 📇 Card\nPhone: 1\n")
mid2 = pe.log_insert(mid, "- 2026-07-02 08:00 - new")
check("4.log-not-last-section",
      mid2.index("- 2026-07-02") < mid2.index("- 2026-07-01")
      and "Phone: 1" in mid2)

# ── 5. log body / reset / dates / staleness ──────────────────────────────────
check("5.body", "met at market" in pe.log_body(c3))
check("5.body-empty", pe.log_body(CARD) == "")
r = pe.log_reset(c3)
check("5.reset", pe.log_body(r) == "" and "## 🧾 Log" in r
      and "Birthday: 1993/06/27" in r)
check("5.reset-nolog", pe.log_reset("plain") == "plain")
check("5.last", pe.last_log_date(c3) == date(2026, 7, 25))
check("5.last-max-not-first",
      pe.last_log_date("## 🧾 Log\n- 2026-01-01 - a\n- 2026-06-01 - b\n")
      == date(2026, 6, 1))
check("5.last-none", pe.last_log_date(CARD) is None)
check("5.silent", pe.days_silent(c3, date(2026, 7, 28)) == 3)
check("5.silent-none", pe.days_silent(CARD) is None)
check("5.stale-old", pe.is_stale(c3, date(2026, 9, 1)))
check("5.stale-fresh", not pe.is_stale(c3, date(2026, 7, 28)))
check("5.stale-never", pe.is_stale(CARD))
check("5.chip", pe.age_chip(c3, date(2026, 7, 28)) == "🗨️ 3d")
check("5.chip-never", pe.age_chip(CARD) == "🗨️ never")

# ── 6b. ideas + nudge basis ──────────────────────────────────────────────────
ci = pe.ideas_insert(pe.CARD_SKEL, "- socks")
check("6b.ideas-before-log", "## 🎁 Ideas\n- socks\n\n## 🧾 Log" in ci)
ci2 = pe.ideas_insert(ci, "- vinyl")
check("6b.ideas-append-order", pe.ideas_body(ci2) == "- socks\n- vinyl")
mi = pe.ideas_insert("## 📇 Card\nPhone: 1\n\n## 🧾 Log\n- 2026-01-01 - x\n",
                     "- gift")
check("6b.ideas-minted-before-log",
      mi.index("## 🎁 Ideas") < mi.index("## 🧾 Log")
      and pe.log_body(mi) == "- 2026-01-01 - x")
check("6b.ideas-no-sections",
      pe.ideas_insert("plain", "- gift").endswith("## 🎁 Ideas\n- gift\n"))
li = pe.log_insert(ci2, "- 2026-07-24 10:00 - hey")
check("6b.log-ideas-coexist", pe.last_log_date(li) == date(2026, 7, 24)
      and pe.ideas_body(li) == "- socks\n- vinyl")
check("6b.nudge-from-created", pe.nudge_silent_days(
    {"content": "", "createdTime": "2026-07-10T08:00:00+0000"},
    date(2026, 7, 24)) == 14)
check("6b.nudge-from-log", pe.nudge_silent_days(
    {"content": pe.log_insert("", "- 2026-07-20 09:00 - hi"),
     "createdTime": "2026-07-01T08:00:00+0000"}, date(2026, 7, 24)) == 4)
check("6b.nudge-no-basis",
      pe.nudge_silent_days({"content": ""}, date(2026, 7, 24)) is None)

# ── 6. skeleton sanity ───────────────────────────────────────────────────────
check("6.skel-sections", all(h in pe.CARD_SKEL for h in
                             (pe.SEC_CARD, pe.SEC_IDEAS, pe.SEC_LOG)))
check("6.skel-fields", all(f in pe.CARD_SKEL for f in
                           ("Birthday: ", "Phone: ", "Mail: ")))

print(f"people suite: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
