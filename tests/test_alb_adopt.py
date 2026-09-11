#!/usr/bin/env python3
"""👤 Customer later + ↩️ Undo (ALBUMS_SPEC §5 albadopt / albundo):
xact.album_adopt over a fake TickTick API, the test_albums fixture
library + FakeEagle, every dialog scripted, the rename ripple
MONKEYPATCHED (the rename block ships _alb_rename_ripple; this file only
asserts the call and mimics its ledger writes so undo has something to
reverse). The adopt picker screen is rendered read-only. No network, no
Eagle, no live TickTick; ~/.ticktick_alfred is never touched (ledger /
stash / cache all point at a tmp dir through test_albums.Base).
Run: python3 tests/test_alb_adopt.py   (or unittest discover)
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, HERE)
os.environ.setdefault("crm_list_id", "CRMLIST")
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_archive_list_id", "ARCHIVE")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")

from test_albums import Base, REC, TV_PID, _cust  # noqa: E402
import albums  # noqa: E402
import cache  # noqa: E402
import crm_records as cr  # noqa: E402
import xact  # noqa: E402

ARC = "ARCHIVE"
EAGLE_LINE_B1 = "🦅 [Eagle folder](eagle://folder/B1) · TV\n🎬 TV"


def _row(tid, base, fid, content="·", tags=("📸raw",)):
    """A pipeline row in the TV list: title = the eagle folder link."""
    return {"id": tid, "projectId": TV_PID, "_projectId": TV_PID,
            "kind": "TEXT", "title": f"[{base}](eagle://folder/{fid})",
            "content": content, "tags": list(tags), "status": 0}


class FakeAPI:
    """TickTick over a dict: get_task 404s under the wrong list (the live
    API's rule), move_task re-homes, every write recorded."""

    def __init__(self, tasks):
        self.tasks = {t["id"]: dict(t) for t in tasks}
        self.created, self.updates, self.moves, self.deleted = [], [], [], []
        self._n = 0

    def create_task(self, title, project_id=None, content=None, tags=None,
                    kind=None, **_kw):
        self._n += 1
        t = {"id": f"T{self._n}", "projectId": project_id, "title": title,
             "content": content or "", "tags": list(tags or []),
             "kind": kind or "TEXT", "status": 0}
        self.tasks[t["id"]] = t
        self.created.append(dict(t))
        return dict(t)

    def get_task(self, pid, tid):
        t = self.tasks.get(tid)
        if not t or t.get("projectId") != pid:
            raise KeyError("404")
        return dict(t)

    def update_task(self, tid, pid, current=None, **fields):
        self.updates.append((tid, pid, dict(fields)))
        self.tasks[tid].update(fields)
        return dict(self.tasks[tid])

    def move_task(self, tid, a, b):
        self.moves.append((tid, a, b))
        self.tasks[tid]["projectId"] = b

    def delete_task(self, pid, tid):
        self.deleted.append((pid, tid))
        self.tasks.pop(tid, None)


class AdoptBase(Base):
    """Fixture library (test_albums.Base) + a fake TickTick + scripted
    dialogs + the ripple stand-in."""

    def setUp(self):
        super().setUp()
        self.rows = [_row("R1", "Zeus", "B1"),
                     _row("R2", "Griffin", "E1"),
                     _row("R3", "Phillip - Samurai", "A1",
                          content=f"🎨 [🎨 Phillip • Samurai](https://ticktick.com/webapp/#p/{REC}/tasks/LB0)")]
        self.ca = _cust("ca", "👤 Phillip", [])
        cache.set("all_tasks", [dict(r) for r in self.rows])
        cache.set("all_notes", [dict(self.ca)])
        self.api = FakeAPI(self.rows + [self.ca])
        self.toasts, self.asked, self.ripples = [], [], []
        self.answers = {}          # prompt-prefix → answer (None = Esc)
        self.date_answer = None    # what _ask_date returns
        self.state_answer = "Still active"
        self.saved = {}
        patches = {
            (cr, "_api"): lambda: self.api,
            (cr, "_ensure_tag"): lambda *a, **k: None,
            (albums, "_mdls"): lambda paths: {},
            (albums, "_bulk_dates"): lambda: set(),
            (xact, "_records_ready"): lambda: True,
            (xact, "_crm_say"): self.toasts.append,
            (xact, "_ask"): self._ask,
            (xact, "_ask_date"): self._ask_date,
            (xact, "_dialog"): self._dialog,
            (xact, "_alb_rename_ripple"): self._ripple,
        }
        _missing = object()
        for (mod, name), fn in patches.items():
            self.saved[(mod, name)] = getattr(mod, name, _missing)
            setattr(mod, name, fn)
        self._missing = _missing

    def tearDown(self):
        for (mod, name), old in self.saved.items():
            if old is self._missing:
                if hasattr(mod, name):
                    delattr(mod, name)
            else:
                setattr(mod, name, old)
        super().tearDown()

    # scripted dialogs
    def _ask(self, prompt, title="TickAL", hidden=False, default=""):
        self.asked.append((prompt, default))
        for key, ans in self.answers.items():
            if prompt.startswith(key):
                return ans
        return default

    def _ask_date(self, prompt):
        self.asked.append((prompt, None))
        return self.date_answer

    def _dialog(self, prompt, buttons, default):
        self.asked.append((prompt, default))
        return self.state_answer

    def _ripple(self, lib, fid, new_base, op, log_tid=None, row=None):
        """The sibling's contract mimicked: folder + shots renamed on the
        fake Eagle, the row retitled on the fake API, the ledger op fed
        (folders / items / the row piece) exactly as undo_last reads it."""
        self.ripples.append({"lib": lib, "fid": fid, "new_base": new_base,
                             "log_tid": log_tid,
                             "row": row.get("id") if row else None})
        node = self.fake.folder_node(fid)
        op["folders"].append({"id": fid, "prior_name": node["name"],
                              "prior_parent": "raw", "name": new_base,
                              "parent": "raw", "created": False})
        self.fake.rename_folder(fid, new_base)
        for it in self.fake.items_in_folder(fid):
            new = albums.rebase_name(it["name"], "", new_base)
            op["items"].append({"id": it["id"], "prior_name": it["name"],
                                "prior_folders": list(it["folders"]),
                                "prior_tags": list(it["tags"]),
                                "name": new, "folders": list(it["folders"])})
            self.fake.update_items([{"id": it["id"], "name": new}])
        if row:
            title = xact._eagle_title(new_base, fid)
            self.api.tasks[row["id"]]["title"] = title
            op["ticktick"].append({"kind": "row", "id": row["id"],
                                   "pid": TV_PID, "action": "retitled",
                                   "prior": {"title": row.get("title")}})

    # helpers
    def logbook(self):
        return next(t for t in self.api.tasks.values()
                    if (t.get("title") or "").startswith(("🎨", "🏛️"))
                    and t["id"] != "LB0")

    def ledger_ops(self):
        return albums.Ledger().all()


# ─────────────────────────────────────────────────── the happy roads

class AdoptKnownCustomer(AdoptBase):
    def test_known_customer_dates_from_the_shots(self):
        # Zeus (B1): I4 carries an Eagle btime → 2023-11-14, no prompt
        xact.album_adopt("R1", "ca")
        lb = self.logbook()
        self.assertEqual(lb["title"], "🎨 Phillip • Zeus")
        self.assertEqual(lb["projectId"], REC)
        self.assertIn("🗂️logbook", [t.lower() for t in lb["tags"]])
        head = lb["content"].partition("\n## ")[0]
        self.assertIn("· Started 2023-11-14 · Finished -", head)
        self.assertIn(EAGLE_LINE_B1, head)
        self.assertNotIn("Finished 2", head)
        # no date prompt, the tattoo name prefilled with the album name
        prompts = [p for p, _d in self.asked]
        self.assertNotIn(xact._ALB_ADOPT_DATE_PROMPT, prompts)
        self.assertIn(("Tattoo name?", "Zeus"), self.asked)
        self.assertNotIn("New customer name?", prompts)
        # the ripple: the shared signature, the logbook's base
        self.assertEqual(self.ripples, [{"lib": "tv", "fid": "B1",
                                         "new_base": "Phillip - Zeus",
                                         "log_tid": lb["id"], "row": "R1"}])
        # the row body gains the 🎨 link (the _mint_raw_task shape)
        row = self.api.tasks["R1"]
        self.assertEqual(row["content"],
                         f"🎨 [🎨 Phillip • Zeus](https://ticktick.com/webapp/#p/{REC}/tasks/{lb['id']})")
        self.assertEqual(row["title"], "[Phillip - Zeus](eagle://folder/B1)")
        self.assertEqual(row["tags"], ["📸raw"])            # state tag kept
        cached = cache.find_task("R1")
        self.assertEqual(cached["content"], row["content"])
        # the customer note carries the bullet
        self.assertIn(f"/tasks/{lb['id']})", self.api.tasks["ca"]["content"])
        # ONE ledger op, the TickTick pieces listed for undo's toast
        ops = self.ledger_ops()
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual((op["verb"], op["lib"]), ("adopt", "tv"))
        kinds = [(p["kind"], p["action"]) for p in op["ticktick"]]
        self.assertEqual(kinds, [("logbook", "minted"), ("row", "retitled")])
        row_piece = op["ticktick"][1]
        self.assertEqual(row_piece["prior"]["title"], "[Zeus](eagle://folder/B1)")
        self.assertEqual(row_piece["prior"]["content"], "·")
        self.assertEqual(len(op["items"]), 3)                # Zeus' shots
        self.assertEqual(op["folders"][0]["prior_name"], "Zeus")
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.api.moves, [])
        self.assertEqual(len(self.toasts), 1)
        self.assertIn("Phillip - Zeus", self.toasts[0])
        self.assertIn("3 shots", self.toasts[0])
        self.assertNotIn("archived", self.toasts[0])

    def test_typed_customer_prefix_is_not_doubled(self):
        # the album is named 'Phillip - Samurai' but its row has no logbook
        self.rows[2]["content"] = "·"
        cache.set("all_tasks", [dict(r) for r in self.rows])
        self.api.tasks["R3"]["content"] = "·"
        xact.album_adopt("R3", "ca")
        self.assertIn(("Tattoo name?", "Samurai"), self.asked)
        self.assertEqual(self.logbook()["title"], "🎨 Phillip • Samurai")
        self.assertEqual(self.ripples[0]["new_base"], "Phillip - Samurai")


class AdoptNewCustomer(AdoptBase):
    def test_new_customer_unknown_date_finished_archives(self):
        # Griffin (E1): no capture date anywhere → the prompt, OK = unknown
        self.answers = {"New customer name?": "Nina"}
        self.date_answer = None
        self.state_answer = "Finished"
        xact.album_adopt("R2", "new")
        cust = next(t for t in self.api.created if t["title"] == "👤 Nina")
        self.assertEqual(cust["projectId"], REC)
        self.assertIn(("Tattoo name?", "Griffin"), self.asked)
        self.assertIn(xact._ALB_ADOPT_DATE_PROMPT, [p for p, _d in self.asked])
        lb = self.logbook()
        self.assertEqual(lb["title"], "🏛️ Nina • Griffin")
        self.assertEqual(lb["projectId"], ARC)
        self.assertIn((lb["id"], REC, ARC), self.api.moves)
        tags = [t.lower() for t in lb["tags"]]
        self.assertIn("🗂️archive", tags)
        self.assertNotIn("🗂️logbook", tags)
        self.assertFalse(any(t.startswith("📦crm") for t in tags))   # year unknown
        head = lb["content"].partition("\n## ")[0]
        self.assertIn("· Started - · Finished -", head)
        self.assertIn("🦅 [Eagle folder](eagle://folder/E1) · TV\n🎬 TV", head)
        # the row links the ARCHIVED note: its list + 🏛️ title
        row = self.api.tasks["R2"]
        self.assertEqual(row["content"],
                         f"🎨 [🏛️ Nina • Griffin](https://ticktick.com/webapp/#p/{ARC}/tasks/{lb['id']})")
        self.assertEqual(self.ripples[0]["new_base"], "Nina - Griffin")
        self.assertEqual(self.ripples[0]["log_tid"], lb["id"])
        # the customer bullet reads the unknown dates
        bul = next(l for l in self.api.tasks[cust["id"]]["content"].split("\n")
                   if f"/tasks/{lb['id']})" in l)
        self.assertIn("started - · finished -", bul)
        op = self.ledger_ops()[0]
        kinds = [(p["kind"], p["action"]) for p in op["ticktick"]]
        self.assertEqual(kinds, [("customer", "minted"), ("logbook", "minted"),
                                 ("row", "retitled")])
        self.assertEqual(op["ticktick"][1]["pid"], REC)      # minted there
        self.assertIn("archived", self.toasts[0])
        self.assertIn("Nina - Griffin", self.toasts[0])

    def test_typed_date_finished_gets_the_year_tag(self):
        self.answers = {"New customer name?": "Nina"}
        self.date_answer = "2024-05-06"
        self.state_answer = "Finished"
        xact.album_adopt("R2", "new")
        lb = self.logbook()
        head = lb["content"].partition("\n## ")[0]
        self.assertIn("· Started 2024-05-06 · Finished 2024-05-06", head)
        self.assertIn("📦crm2024", [t.lower() for t in lb["tags"]])
        self.assertEqual(lb["projectId"], ARC)

    def test_started_guard_patches_a_today_header(self):
        """A create_logbook that ignores started='-' (writes today) gets
        the header patched under the note's own list, projectId explicit,
        and the bullet re-synced."""
        real = cr.create_logbook

        def stubborn(cust, tattoo, started=None, **kw):
            return real(cust, tattoo, started=None, **kw)
        cr.create_logbook = stubborn
        try:
            self.answers = {"New customer name?": "Nina"}
            self.date_answer = None
            xact.album_adopt("R2", "new")
        finally:
            cr.create_logbook = real
        lb = self.logbook()
        self.assertIn("· Started - · Finished -", lb["content"])
        fix = next(u for u in self.api.updates
                   if u[0] == lb["id"] and "Started -" in (u[2].get("content") or ""))
        self.assertEqual(fix[1], REC)
        self.assertEqual(fix[2]["projectId"], REC)
        cust = next(t for t in self.api.created if t["title"] == "👤 Nina")
        self.assertIn("started - · finished -", self.api.tasks[cust["id"]]["content"])
        self.assertEqual(cache.find_task(lb["id"])["content"], lb["content"])


# ───────────────────────────────────────────── refusals + cancels

class AdoptRefuses(AdoptBase):
    def assert_nothing_written(self):
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.ripples, [])
        self.assertEqual(self.ledger_ops(), [])
        self.assertEqual(len(self.toasts), 1)

    def test_not_a_pipeline_row(self):
        xact.album_adopt("ghost", "ca")
        self.assertIn("Not a pipeline row", self.toasts[0])
        self.assert_nothing_written()

    def test_row_already_linked(self):
        xact.album_adopt("R3", "ca")
        self.assertIn("already has a logbook", self.toasts[0])
        self.assert_nothing_written()

    def test_unknown_customer(self):
        xact.album_adopt("R1", "nobody")
        self.assertIn("Customer not found", self.toasts[0])
        self.assert_nothing_written()

    def test_missing_ripple_refuses_before_any_write(self):
        # tearDown restores the REAL ripple from self.saved - overwriting
        # the saved slot with _missing deleted it for every later test
        # module under unittest discover (the merge suite silently no-oped)
        delattr(xact, "_alb_rename_ripple")
        xact.album_adopt("R1", "ca")
        self.assertIn("Rename ripple missing", self.toasts[0])
        self.assert_nothing_written()

    def test_cancel_at_every_prompt(self):
        # Esc on the customer name
        self.answers = {"New customer name?": None}
        xact.album_adopt("R1", "new")
        self.assertEqual(self.toasts[-1], "Cancelled")
        # empty tattoo name
        self.answers = {"Tattoo name?": ""}
        xact.album_adopt("R1", "ca")
        self.assertEqual(self.toasts[-1], "Cancelled")
        # Esc on the date prompt (Griffin has no capture date)
        self.answers = {}
        self.date_answer = "CANCEL"
        xact.album_adopt("R2", "ca")
        self.assertEqual(self.toasts[-1], "Cancelled")
        # Esc / Cancel on the state dialog
        self.date_answer = None
        for esc in ("", "Cancel"):
            self.state_answer = esc
            xact.album_adopt("R2", "ca")
            self.assertEqual(self.toasts[-1], "Cancelled")
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.ripples, [])
        self.assertEqual(self.ledger_ops(), [])

    def test_ripple_failure_is_closed_and_honest(self):
        def boom(*a, **k):
            raise RuntimeError("Eagle asleep")
        xact._alb_rename_ripple = boom
        xact.album_adopt("R1", "ca")
        self.assertIn("stopped: Eagle asleep", self.toasts[-1])
        self.assertIn("landed: logbook", self.toasts[-1])
        self.assertEqual(self.ledger_ops(), [])              # no op on failure
        self.assertEqual(self.api.tasks["R1"]["content"], "·")   # body untouched


# ─────────────────────────────────────────────────────── ↩️ undo

class Undo(AdoptBase):
    def test_nothing_to_undo(self):
        xact.album_undo()
        self.assertEqual(self.toasts, ["↩️ Nothing to undo"])
        self.assertEqual(self.fake.calls, [])                # Eagle untouched

    def test_undo_reverses_the_adopt_on_eagle_and_lists_ticktick(self):
        xact.album_adopt("R1", "ca")
        lb = self.logbook()
        self.assertEqual(self.fake.folder_node("B1")["name"], "Phillip - Zeus")
        self.assertEqual(self.fake.items["I3"]["name"], "Phillip - Zeus • Raw • 1")
        self.toasts.clear()
        xact.album_undo()
        toast = self.toasts[0]
        self.assertTrue(toast.startswith("↩️ Undid adopt"))
        self.assertIn("3 shots back", toast)
        self.assertIn("1 folder(s) back", toast)
        self.assertIn(f"Trash logbook {lb['id']}", toast)
        self.assertIn("row R1 was retitled", toast)
        self.assertEqual(self.fake.folder_node("B1")["name"], "Zeus")
        self.assertEqual(self.fake.items["I3"]["name"], "Zeus • Raw • 1")
        self.assertEqual(self.fake.items["I5"]["name"], "IMG_9")
        self.assertIsNone(albums.Ledger().last())             # stack popped
        self.assertEqual(self.api.deleted, [])                # TickTick by hand
        self.assertEqual(self.api.tasks["R1"]["title"],
                         "[Phillip - Zeus](eagle://folder/B1)")

    def test_undo_error_toasts(self):
        real = albums.undo_last
        albums.undo_last = lambda: (_ for _ in ()).throw(
            albums.AlbumError("undo stopped: Eagle asleep"))
        try:
            xact.album_undo()
        finally:
            albums.undo_last = real
        self.assertEqual(self.toasts, ["↩️ undo stopped: Eagle asleep"])


# ─────────────────────────────────────── the adopt picker (read-only)

class AdoptPicker(AdoptBase):
    def test_render_albcust_adopt_rows_fire_albadopt(self):
        import browse
        rows = browse.render_albcust(["tv", "Raw", "adopt", "R1"], "")
        self.assertEqual(rows[0]["title"], "👤 Zeus · whose tattoo?")
        self.assertFalse(rows[0].get("valid", True))
        args = [r.get("arg") for r in rows]
        self.assertIn("xact:albadopt:R1:new", args)
        self.assertIn("xact:albadopt:R1:ca", args)
        self.assertNotIn("xact:albnew:tv:Raw:none", args)   # no John Doe row
        self.assertTrue(all(r["variables"]["browse_back"] == "ctx:contentpl:tv"
                            for r in rows))
        # the dispatcher line: albadopt:<tid>:<who> → album_adopt(tid, who)
        rows = browse.render_albcust(["tv", "Raw", "adopt", "R1"], "phil")
        self.assertIn("xact:albadopt:R1:ca", [r.get("arg") for r in rows])


if __name__ == "__main__":
    unittest.main()
