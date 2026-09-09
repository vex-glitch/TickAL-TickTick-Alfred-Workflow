#!/usr/bin/env python3
"""Unit suite for the Session-done money + memory helpers in
src/crm_records.py (pure text-in text-out, no I/O, no credentials):
unapplied_deposit, session_charge (the deposit math - Vex ruling
2026-09-08: the Charged answer IS the price), quote_remainder,
paid_summary's 'over' word, last_next / last_setup.

Run: python3 tests/test_crm_deposit.py   (or unittest discover)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import crm_records as cr  # noqa: E402


HEAD = ("🎨 Erol - Griffin\n[👤 Erol](https://ticktick.com/webapp/#p/p1/tasks/t1)"
        " · Started 2026-08-01 · Finished -\nPaid: -\n")


def note(*entries, quoted=None):
    head = HEAD + (f"Quoted: {quoted}\n" if quoted else "")
    body = "\n\n".join(entries)
    return f"{head}\n## Sessions\n\n{body}\n\n## Notes\n"


DEP = "### 2026-08-02 · payment · - · 100€\nDeposit."
S1 = ("### 2026-08-10 · S1 · 3h · 300€\nOutline.\nSetup: 3RL · black\n"
      "Next: colour the wings")
DEP2 = "### 2026-08-12 · payment · - · 50€\nSecond deposit."
S2 = "### 2026-08-20 · S2 · 4h · 400€\nShading."
REFUND = "### 2026-08-21 · payment · - · -20€\nRefund."
CONSULT = "### 2026-07-30 · consultation · - · -\nTalked."


class UnappliedDeposit(unittest.TestCase):
    def test_none(self):
        self.assertEqual(cr.unapplied_deposit(note()), 0.0)
        self.assertEqual(cr.unapplied_deposit(note(S1)), 0.0)
        self.assertEqual(cr.unapplied_deposit_text(note(S1)), "")

    def test_all_when_no_session_yet(self):
        self.assertEqual(cr.unapplied_deposit(note(CONSULT, DEP)), 100.0)
        self.assertEqual(cr.unapplied_deposit_text(note(CONSULT, DEP)), "100€")

    def test_absorbed_by_a_session(self):
        self.assertEqual(cr.unapplied_deposit(note(DEP, S1)), 0.0)

    def test_only_after_last_session_counts(self):
        self.assertEqual(cr.unapplied_deposit(note(DEP, S1, DEP2)), 50.0)
        self.assertEqual(cr.unapplied_deposit(note(DEP, S1, DEP2, S2)), 0.0)

    def test_refund_floors_at_zero(self):
        self.assertEqual(cr.unapplied_deposit(note(S1, REFUND)), 0.0)
        self.assertEqual(cr.unapplied_deposit(note(S1, DEP2, REFUND)), 30.0)

    def test_prefix_currency(self):
        c = note("### 2026-08-02 · payment · - · $80\nDeposit.")
        self.assertEqual(cr.unapplied_deposit(c), 80.0)
        self.assertEqual(cr.unapplied_deposit_text(c), "$80")


class SessionCharge(unittest.TestCase):
    def test_no_deposit_passes_through(self):
        self.assertEqual(cr.session_charge(note(S1), "400€"), ("400€", ""))
        self.assertEqual(cr.session_charge(note(S1), " 400 "), ("400", ""))

    def test_deposit_subtracted_price_kept(self):
        seg, line = cr.session_charge(note(DEP), "400€")
        self.assertEqual(seg, "300€")
        self.assertEqual(line, "(price 400€ · 100€ deposit applied)")

    def test_bare_number_takes_logbook_currency(self):
        seg, line = cr.session_charge(note(DEP), "400")
        self.assertEqual(seg, "300€")
        self.assertIn("price 400€", line)
        seg, _ = cr.session_charge(
            note("### 2026-08-02 · payment · - · $100\nDeposit."), "400")
        self.assertEqual(seg, "$300")

    def test_floor_zero(self):
        seg, line = cr.session_charge(note(DEP), "60€")
        self.assertEqual(seg, "0€")
        self.assertEqual(line, "(price 60€ · 100€ deposit applied)")

    def test_gratis_and_blank_untouched(self):
        self.assertEqual(cr.session_charge(note(DEP), "gift"), ("gift", ""))
        self.assertEqual(cr.session_charge(note(DEP), ""), ("", ""))
        self.assertEqual(cr.session_charge(note(DEP), "cash later"),
                         ("cash later", ""))

    def test_paid_total_equals_the_price(self):
        # deposit 100, session priced 400 → logged 300 → Paid reads 400
        seg, line = cr.session_charge(note(DEP), "400€")
        c = note(DEP, f"### 2026-08-10 · S1 · 3h · {seg}\n{line}")
        self.assertEqual(cr.totals(c), ("400€", 1))
        self.assertEqual(cr.paid_summary(c), "400€ · 1 session")

    def test_decimals(self):
        seg, line = cr.session_charge(note(DEP), "250,50€")
        self.assertEqual(seg, "150.50€")


class QuoteRemainder(unittest.TestCase):
    def test_deposit_does_not_shrink_the_remaining_price(self):
        # quote 800, deposit 100 unapplied → the next session's PRICE
        # default is still 800 (the deposit is subtracted at log time)
        self.assertEqual(cr.quote_remainder(note(DEP, quoted="800€")), "800€")

    def test_logged_sessions_count_in_prices(self):
        # S1 priced 400 = 300 logged + 100 deposit absorbed → 400 left
        c = note(DEP, "### 2026-08-10 · S1 · 3h · 300€\n"
                 "(price 400€ · 100€ deposit applied)", quoted="800€")
        self.assertEqual(cr.quote_remainder(c), "400€")
        # a fresh deposit after S1 keeps the remaining PRICE at 400
        self.assertEqual(cr.quote_remainder(c + DEP2 + "\n"), "400€")

    def test_settled(self):
        self.assertEqual(cr.quote_remainder(note(S2, quoted="400€")), "")
        self.assertEqual(cr.quote_remainder(note(S2)), "")


class PaidSummaryOver(unittest.TestCase):
    def test_open_settled_over(self):
        self.assertEqual(cr.paid_summary(note(S1, quoted="800€")),
                         "300€ of 800€ · 500€ open · 1 session")
        self.assertEqual(cr.paid_summary(note(S1, quoted="300€")),
                         "300€ of 300€ · settled · 1 session")
        self.assertEqual(cr.paid_summary(note(S1, quoted="250€")),
                         "300€ of 250€ · 50€ over · 1 session")


class Memory(unittest.TestCase):
    def test_last_next(self):
        self.assertEqual(cr.last_next(note()), "")
        self.assertEqual(cr.last_next(note(S1)), "colour the wings")
        c = note(S1, "### 2026-08-20 · S2 · 4h · 400€\nShading.\nNext: heal check ")
        self.assertEqual(cr.last_next(c), "heal check")

    def test_last_setup_unchanged(self):
        self.assertEqual(cr.last_setup(note(S1, S2)), "3RL · black")


if __name__ == "__main__":
    unittest.main()
