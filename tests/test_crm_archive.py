"""ONE archive list + year tags (Vex 2026-09-09): the pure helpers and
the note locator's fallback order."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_archive_list_id", "ARCHIVE")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")
import areas
import crm_records as cr

REC, ARC = "6a4e50e9842a1194a7c681e1", "ARCHIVE"


class YearTags(unittest.TestCase):
    def test_tag_shape(self):
        self.assertEqual(areas.year_tag(2025), "📦crm2025")
        self.assertEqual(areas.year_tag("2019"), "📦crm2019")
        self.assertTrue(areas.is_year_tag("📦crm2019"))
        self.assertTrue(areas.is_year_tag("📦CRM2019"))
        self.assertFalse(areas.is_year_tag("📦crmarchive"))
        self.assertFalse(areas.is_year_tag("🗂️archive"))

    def test_year_of_tags(self):
        self.assertEqual(areas.year_of_tags(["🗂️archive", "📦crm2023"]), "2023")
        self.assertEqual(areas.year_of_tags(["🗂️archive"]), "")
        self.assertEqual(areas.year_of_tags(None), "")

    def test_records_pids_carry_the_archive_list(self):
        self.assertEqual(areas.records_pids()[:2], (REC, ARC))


class YearRule(unittest.TestCase):
    HEAD = "👤 [👤 X](u) · Started 2023-04-28 · Finished 2026-05-14\n"

    def test_started_year_wins(self):
        self.assertEqual(cr.archive_year(self.HEAD), "2023")
        self.assertEqual(cr.archive_year(self.HEAD, "2026-05-14"), "2023")

    def test_unknown_start_falls_back_to_when(self):
        head = "👤 [👤 X](u) · Started - · Finished -\n"
        self.assertEqual(cr.archive_year(head, "2021-06-01"), "2021")
        self.assertEqual(cr.archive_year(head), "")

    def test_note_year_prefers_the_tag(self):
        n = {"tags": ["🗂️archive", "📦crm2019"], "content": self.HEAD}
        self.assertEqual(cr.note_year(n), "2019")
        self.assertEqual(cr.note_year({"tags": [], "content": self.HEAD}), "2023")
        self.assertEqual(cr.note_year({"tags": ["🗂️archive"], "content": ""}), "")

    def test_year_tags_stripped(self):
        self.assertEqual(cr._year_tags_stripped(["🗂️archive", "📦crm2019", "x"]),
                         ["🗂️archive", "x"])


class FakeAPI:
    """get_task 404s unless the pid matches where the note lives."""
    def __init__(self, where):
        self.where = where
        self.calls = []

    def get_task(self, pid, tid):
        self.calls.append(pid)
        if self.where.get(tid) != pid:
            raise KeyError("404")
        return {"id": tid, "projectId": pid, "tags": [], "content": ""}


class Locate(unittest.TestCase):
    def setUp(self):
        self._api = cr._api
        self.fake = FakeAPI({"n1": ARC})
        cr._api = lambda: self.fake

    def tearDown(self):
        cr._api = self._api

    def test_hint_then_cache_then_every_records_pid(self):
        live, pid = cr.locate("n1", REC)
        self.assertEqual(pid, ARC)
        self.assertEqual(live["projectId"], ARC)
        self.assertEqual(self.fake.calls[0], REC)       # the hint first
        self.assertIn(ARC, self.fake.calls)

    def test_nowhere_raises(self):
        self.fake.where = {}
        with self.assertRaises(KeyError):
            cr.locate("ghost", REC)

    def test_get_note_sets_pid(self):
        self.assertEqual(cr.get_note("n1")["projectId"], ARC)


if __name__ == "__main__":
    unittest.main()
