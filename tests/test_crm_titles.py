"""Session-task title shape: marker suffix, forecast tail (2026-09-08)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
import crm_records as cr

LINK = "[🎨 Marko • Sleeve](https://ticktick.com/webapp/#p/6a4e50e9842a1194a7c681e1/tasks/6a5f18fd8f0846c75ce1d09c)"


class Titles(unittest.TestCase):
    def test_marker_plain(self):
        self.assertEqual(cr.title_marker(f"{LINK} S2"), "S2")
        self.assertEqual(cr.title_marker(f"{LINK} Consult"), "Consult")

    def test_marker_with_forecast(self):
        self.assertEqual(cr.title_marker(f"{LINK} S2 - 400"), "S2")
        self.assertEqual(cr.title_marker(f"{LINK} S12 - 1.200€"), "S12")
        self.assertEqual(cr.title_marker(f"{LINK} Consult - 50"), "Consult")
        self.assertEqual(cr.title_snum(f"{LINK} S3 - 400"), 3)

    def test_forecast(self):
        self.assertEqual(cr.title_forecast(f"{LINK} S2 - 400"), "400")
        self.assertEqual(cr.title_forecast(f"{LINK} S2"), "")

    def test_session_gate_keeps_forecast_titles(self):
        self.assertTrue(cr.is_session_task(f"{LINK} S2 - 400"))
        self.assertFalse(cr.is_session_task(f"Prepare for {LINK}"))
        self.assertFalse(cr.is_session_task(f"{LINK} S2 - notes"))


if __name__ == "__main__":
    unittest.main()
