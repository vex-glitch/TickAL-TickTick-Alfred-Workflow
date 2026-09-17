#!/usr/bin/env python3
"""Unit suite for the 💰 money road: where a day's money is written, what a
retrospective entry does, and the day strip's rows.

Vex 2026-09-17: "Can I add money entries retrospectively to chosen day of the
week? like if I skip evening journal or whatever?" - and "if money is entered
already for the day that I am trying to enter it again, it shows entered
amount first row, enter confirms or second row to adjust entry."

No network: ensure_note, _pn_rmw and journal_seed are stubbed, and the day
strip reads a fake note list.
Run: python3 tests/test_money.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))

import periodic_sections as ps      # noqa: E402
import periodic_model as pm         # noqa: E402
import periodic_engine as pe        # noqa: E402
import periodic_rows as prows       # noqa: E402

FAILS, COUNT = [], [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


Q = "\t- *Q1 · How much money did you earn today?*\n\t\tA: "
EVENING = "#### 📓 Journals\n- 🌅 Morning journal\n\n- 🌙 Evening journal\n" + Q + "%s\n"
BARE = "#### 📓 Journals\n- 🌅 Morning journal\n\n- 🌙 Evening journal\n"
LEGACY = ("#### 📓 Journals\n- 🌙 Evening journal\n" + Q + "\n"
          "#### 💰 Money\n- 120 · old client\n**Total = 120**\n")
DAY = date(2026, 9, 15)                      # a Tuesday
STATE = {}


def _install(content):
    STATE["content"], STATE["seeded"] = content, 0
    pe.ensure_note = lambda p, index=None: ({"id": "t1", "projectId": "p1"}, False)

    def rmw(pid, tid, mutate):
        doc = ps.parse_sections(STATE["content"])
        r = mutate(doc, {})
        if r:
            STATE["content"] = ps.serialize_sections(doc)
        return r, doc
    pe._pn_rmw = rmw

    def seed(slot, day=None):
        STATE["seeded"] += 1
        if "How much money" not in STATE["content"]:
            STATE["content"] = STATE["content"].replace(
                "- 🌙 Evening journal", "- 🌙 Evening journal\n" + Q)
        return {}, [], None
    pe.journal_seed = seed


def log(content, amount=485, label="tattoo", **kw):
    _install(content)
    msg = pe.append_income(amount, label, day=DAY, **kw)
    doc = ps.parse_sections(STATE["content"])
    return msg, pe._answer_in(doc, pm.SEC_EVENING, "money did you earn"), doc


# ── where the number lands ───────────────────────────────────────────────────
msg, ans, _d = log(EVENING % "")
check("fresh answer", ans == "485 · tattoo", ans)
check("toast names the DAY, never 'today'", msg == "💰 Tue 15 Sep · 485 · tattoo", msg)

msg, ans, _d = log(EVENING % "100 · deposit")
check("sums into what is there", ans == "585 · deposit, tattoo", ans)
check("toast shows the arithmetic", msg == "💰 Tue 15 Sep · 100 + 485 = 585", msg)

msg, ans, _d = log(EVENING % "100 · deposit", replace=True)
check("replace swaps the number", ans == "485 · tattoo", ans)
check("replace toast says what it was",
      msg == "💰 Tue 15 Sep · 485 (was 100)", msg)

msg, ans, _d = log(EVENING % "500 for the sleeve, 2 sessions")
check("a hand-typed answer survives a sum",
      ans == "985 · 500 for the sleeve, 2 sessions, tattoo", ans)

# Vex's literal case: the evening journal was never run, so that note has no
# money QUESTION - and a back-minted one has none either, because create_note
# renders the template and the questions are planted on refresh.
msg, ans, _d = log(BARE)
check("a skipped journal is seeded, then answered", ans == "485 · tattoo", ans)
check("seeded exactly once", STATE["seeded"] == 1, STATE["seeded"])

msg, ans, doc = log(LEGACY)
msec = ps.find(doc, pm.SEC_MONEY)
body = [l.strip() for l in (msec.body if msec else []) if l.strip()]
check("a legacy 💰 section keeps its history",
      body[:2] == ["- 120 · old client", "- 485 · tattoo"], body)
check("and its total is recomputed", "605" in " ".join(body), body)
check("the answer is left alone on a legacy note", ans == "", repr(ans))

# ── reading a day back (the fail-safe's source) ──────────────────────────────
def note(day, content):
    return {"projectId": pe.areas.PERIODIC_LIST_ID,
            "title": f"{day.isoformat()} · Tue", "content": content}


rows = [note(DAY, EVENING % "100 · deposit")]
check("answered reads its amount",
      pe.day_money_state(DAY, rows)[:2] == ("answered", 100.0),
      pe.day_money_state(DAY, rows))
check("blank is NOT the same as answered",
      pe.day_money_state(DAY, [note(DAY, EVENING % "")])[:2] == ("blank", None))
check("a note with no money question reads unasked",
      pe.day_money_state(DAY, [note(DAY, BARE)])[:2] == ("unasked", None))
check("no note at all reads unasked",
      pe.day_money_state(DAY, [])[:2] == ("unasked", None))
check("answered with words but no number keeps the state",
      pe.day_money_state(DAY, [note(DAY, EVENING % "nothing today")])[:2]
      == ("answered", None))
check("a note in another list is not this day's",
      pe.day_money_state(DAY, [dict(note(DAY, EVENING % "100"),
                                    projectId="somewhere-else")])[0] == "unasked")

# ── the rows ─────────────────────────────────────────────────────────────────
WEEK = {date(2026, 9, 17): ("blank", None, ""),
        date(2026, 9, 16): ("blank", None, ""),
        date(2026, 9, 15): ("answered", 100.0, "100"),
        date(2026, 9, 14): ("blank", None, "")}
prows._money_week = lambda today: [(d, ) + WEEK[d] for d in sorted(WEEK, reverse=True)]


class _FakeEngine:
    """The confirm screen re-reads the day LIVE rather than trusting the
    strip it came from, so the stub has to cover that road too."""
    @staticmethod
    def day_money_state(day, notes=None):
        return WEEK.get(day, ("unasked", None, ""))


prows._pe = lambda: _FakeEngine
TODAY = date(2026, 9, 17)
_real_date = prows.date


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


prows.date = _FakeDate

r = prows.income_rows("")
check("idle strip prompts then lists the week",
      r[0]["title"].startswith("💰 Type the amount")
      and len(r) == 5 and not any(x.get("valid") for x in r), [x["title"] for x in r])
check("junk instead of an amount says so",
      prows.income_rows("abc")[0]["subtitle"] == "Numbers first")

r = prows.income_rows("485 tattoo")
check("today is the first row, so plain ⏎ is today",
      r[0]["title"].startswith("☀️ Today") and r[0]["valid"] is True, r[0]["title"])
check("a day with nothing writes straight away",
      r[0]["arg"].startswith("xact:pn_income:") and "autocomplete" not in r[0])
day_with = next(x for x in r if "15 Sep" in x["title"])
check("a day that ALREADY has money cannot be written by accident",
      day_with.get("valid") is False
      and day_with["autocomplete"] == "pn $ !2026-09-15 485 tattoo",
      day_with)
check("and it says what it holds", "Has 100" in day_with["subtitle"], day_with["subtitle"])

r = prows.income_rows("485 tattoo *mon")
check("a typed day targets one day",
      len(r) == 1 and "14 Sep" in r[0]["title"], [x["title"] for x in r])

r = prows.income_rows("!2026-09-15 485 tattoo")
check("the confirm screen leads with what is there",
      r[0]["title"] == "💰 Tue 15 Sep · 100 + 485 = 585", r[0]["title"])
check("⏎ on it adds", r[0]["valid"] is True and "Add it" in r[0]["subtitle"])
check("changing the number is a SECOND row",
      r[1]["title"] == "✏️ Tue 15 Sep · 100 → 485"
      and "Replace" in r[1]["subtitle"], r[1]["title"])
check("and there is a way back", r[2]["autocomplete"] == "pn $ 485 tattoo")
import base64 as _b64mod
import json as _json
pay = _json.loads(_b64mod.b64decode(r[1]["arg"].split(":", 2)[2]))
check("the replace row really means replace",
      pay == {"amount": 485.0, "label": "tattoo", "day": "2026-09-15",
              "replace": True}, pay)

# ── the entry legend ─────────────────────────────────────────────────────────
legend = prows.entry_rows("")
check("💰 Money is back under ➕ Entry",
      any(x["title"] == "💰 Money" for x in legend),
      [x["title"] for x in legend])
check("and it leads to the same one screen",
      next(x for x in legend if x["title"] == "💰 Money")["autocomplete"] == "pn + $ ")
check("pn + $ renders the money screen",
      prows.entry_rows("$ 485 tattoo")[0]["title"].startswith("☀️ Today"))
# `pn + $ 485` used to log a THOUGHT called "$ 485", valid and unwarned
bad = prows.entry_rows("m 485")
check("an unknown kind letter never logs a thought",
      bad[0]["valid"] is False and "No entry kind" in bad[0]["title"], bad[0])
check("plain text is still a thought",
      prows.entry_rows("shipped the thing")[0]["title"].startswith("💭 Thought"))

prows.date = _real_date
print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    raise AssertionError(f"{len(FAILS)} failed: {FAILS}")
