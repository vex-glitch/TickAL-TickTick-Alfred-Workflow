#!/usr/bin/env python3
"""✏️ Rename + 🔗 Merge album verbs (ALBUMS_SPEC §5 albrename /
albmergeinto, xact.py '# ── Albums: rename + merge ──') proven over the
tests/test_albums.py fixture library, FakeEagle and FakeAPI: the shared
rename ripple (folder · shots · row · logbook), merge with both
logbooks (customer choice, calendar tasks relinked, twins → Duplicates,
later stage wins), merge adopt-only, merge without TickTick pieces, the
cancel roads and the fail-closed partial ledger.
No network, no Eagle, no live TickTick; ~/.ticktick_alfred untouched.
Run: python3 tests/test_alb_merge.py   (or unittest discover)
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_archive_list_id", "ARCHIVE")
os.environ.setdefault("crm_list_id", "CRM")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")
import test_albums as ta  # noqa: E402  (fixture library, FakeEagle, FakeAPI, notes)
import areas  # noqa: E402
import albums  # noqa: E402
import cache  # noqa: E402
import crm_records as cr  # noqa: E402


def _load_xact():
    if "xact" in sys.modules:
        return sys.modules["xact"]
    spec = importlib.util.spec_from_file_location(
        "xact", os.path.join(os.path.dirname(HERE), "Scripts", "xact.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["xact"] = m
    spec.loader.exec_module(m)
    return m


xact = _load_xact()

REC, TV_PID = ta.REC, ta.TV_PID
A_TITLE, B_TITLE = "🎨 Phillip • Samurai", "🎨 Zeus • Zeus"
LINK_A = cr.task_link(REC, "A", A_TITLE)
LINK_B = cr.task_link(REC, "B", B_TITLE)


def _row(tid, base, fid, tag, body="·"):
    return {"id": tid, "projectId": TV_PID, "_projectId": TV_PID, "status": 0,
            "kind": "NOTE", "title": f"[{base}](eagle://folder/{fid})",
            "content": body, "tags": [tag]}


def _note(tid, title, content, tag="🗂️logbook"):
    return {"id": tid, "projectId": REC, "_projectId": REC, "status": 0,
            "title": title, "tags": [tag], "content": content, "kind": "NOTE"}


class AlbBase(ta.Base):
    """Fixture: rows tA (Phillip - Samurai / A1, 📸raw, logbook A) and tB
    (Zeus / B1, 📸edit, John Doe), logbooks A + B with customers ca / cb,
    B's open calendar tasks cS (S3) and cP (Prepare)."""

    def setUp(self):
        super().setUp()
        self._crm_id = areas.CRM_ID
        areas.CRM_ID = "CRM"
        a_bul = (f"- [{A_TITLE}](https://ticktick.com/webapp/#p/{REC}/tasks/A)"
                 " - started 2026-03-01 · finished - · 300€ · 1 session")
        b_bul = (f"- [{B_TITLE}](https://ticktick.com/webapp/#p/{REC}/tasks/B)"
                 " - started 2026-02-10 · finished 2026-04-05 · 300€ · 2 sessions")
        self.rows = [_row("tA", "Phillip - Samurai", "A1", "📸raw", f"🎨 {LINK_A}"),
                     _row("tB", "Zeus", "B1", "📸edit")]
        self.notes = [_note("A", A_TITLE, ta.NOTE_A), _note("B", B_TITLE, ta.NOTE_B),
                      ta._cust("ca", "👤 Phillip", [a_bul]),
                      ta._cust("cb", "👤 Zeus", [b_bul])]
        self.cal = [{"id": "cS", "projectId": "CRM", "_projectId": "CRM", "status": 0,
                     "title": f"{LINK_B} S3", "priority": 5},
                    {"id": "cP", "projectId": "CRM", "_projectId": "CRM", "status": 0,
                     "title": f"Prepare for {LINK_B}"}]
        self._api = cr._api
        self._reopen = cr.reopen_logbook
        cr.reopen_logbook = lambda pid, tid: None
        self.toasts, self.prompts = [], []
        self.script = {"ask": [], "choose": [], "dialog": []}
        self._patched = {}
        for name, fn in (("_crm_say", lambda m: self.toasts.append(m)),
                         ("_ask", self._ask), ("_choose", self._choose),
                         ("_dialog", self._dialog)):
            self._patched[name] = getattr(xact, name)
            setattr(xact, name, fn)
        self.seed()

    def seed(self):
        self.api = ta.FakeAPI(self.rows + self.notes + self.cal)
        cr._api = lambda: self.api
        cache.set("all_tasks", [dict(r) for r in self.rows + self.cal])
        cache.set("all_notes", [dict(n) for n in self.notes + self.rows])

    def link_b(self):
        """tB becomes a logbook-linked row (logbook B)."""
        self.rows[1]["content"] = f"🎨 {LINK_B}"
        self.seed()

    def tearDown(self):
        for name, fn in self._patched.items():
            setattr(xact, name, fn)
        cr._api = self._api
        cr.reopen_logbook = self._reopen
        areas.CRM_ID = self._crm_id
        super().tearDown()

    # scripted dialogs
    def _ask(self, prompt, title="TickAL", hidden=False, default=""):
        self.prompts.append(("ask", prompt, default))
        return self.script["ask"].pop(0)

    def _choose(self, prompt, options, title="TickAL", default=None):
        self.prompts.append(("choose", prompt, list(options), default))
        return self.script["choose"].pop(0)

    def _dialog(self, prompt, buttons, default):
        self.prompts.append(("dialog", prompt, list(buttons), default))
        return self.script["dialog"].pop(0)

    # helpers
    def parent_of(self, fid):
        return albums._find_node(self.fake.tree, fid)[1]

    def name_of(self, fid):
        return albums._find_node(self.fake.tree, fid)[0]["name"]

    def ops(self):
        return albums.Ledger().all()

    def updates(self, tid):
        return [u for u in self.api.updates if u[0] == tid]


# ───────────────────────────────────────────────────────── rename

class Resolve(unittest.TestCase):
    def test_typed_name_resolution(self):
        r = xact._alb_resolve_base
        self.assertEqual(r("Phillip - Samurai", "Dragon", True), "Phillip - Dragon")
        self.assertEqual(r("Phillip - Samurai", "Phillip - Dragon", True), "Phillip - Dragon")
        self.assertEqual(r("Luka - Anubis", "Anubis - Sleeve", True), "Luka - Anubis - Sleeve")
        self.assertEqual(r("Phillip - Samurai", "  Dragon  Sleeve ", True), "Phillip - Dragon Sleeve")
        # John Doe (or a logbook-linked base without ' - '): the whole name
        self.assertEqual(r("Zeus", "Hydra", False), "Hydra")
        self.assertEqual(r("Zeus", "Hydra", True), "Hydra")
        self.assertEqual(r("Phillip - Samurai", "Dragon", False), "Dragon")
        self.assertEqual(xact._alb_split_base("Luka - Anubis - Sleeve"),
                         ("Luka", "Anubis - Sleeve"))
        self.assertEqual(xact._alb_split_base("Zeus"), ("", "Zeus"))


class Rename(AlbBase):
    def test_known_customer_ripple(self):
        self.script["ask"] = ["Dragon"]
        xact.album_rename("tA")
        self.assertEqual(self.prompts[0][2], "Phillip - Samurai")   # prefilled
        # Eagle: folder, every shot (name + tags), ONE update_items
        self.assertEqual(self.name_of("A1"), "Phillip - Dragon")
        self.assertEqual(self.parent_of("A1"), "raw")
        it = self.fake.items
        self.assertEqual(it["I1"]["name"], "Phillip - Dragon • Raw • 1")
        self.assertEqual(it["I1"]["tags"], ["Phillip", "tv", "Dragon"])
        self.assertEqual(it["I2"]["name"], "Phillip - Dragon • Raw • 2")
        self.assertEqual(it["I2"]["tags"], ["Phillip", "Dragon"])
        self.assertEqual(it["I2"]["folders"], ["A1", "post"])         # untouched
        self.assertEqual(it["I3"]["name"], "Zeus • Raw • 1")           # other album
        self.assertEqual(self.fake.calls[0], ("ensure_library", "tv"))
        self.assertEqual([c[0] for c in self.fake.calls if c[0] == "update_items"],
                         ["update_items"])
        # TickTick: logbook tattoo part, row title + body link text, bullet
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Phillip • Dragon")
        self.assertEqual(self.api.tasks["tA"]["title"], "[Phillip - Dragon](eagle://folder/A1)")
        self.assertEqual(self.api.tasks["tA"]["content"],
                         f"🎨 {cr.task_link(REC, 'A', '🎨 Phillip • Dragon')}")
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸raw"])       # no-op swap
        self.assertIn("[🎨 Phillip • Dragon](", self.api.tasks["ca"]["content"])
        self.assertEqual(cache.find_task("tA")["title"],
                         "[Phillip - Dragon](eagle://folder/A1)")
        # ledger: ONE op
        ops = self.ops()
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op["verb"], "rename")
        self.assertEqual(op["folders"], [{
            "id": "A1", "prior_name": "Phillip - Samurai", "prior_parent": "raw",
            "name": "Phillip - Dragon", "parent": "raw", "created": False}])
        led = {e["id"]: e for e in op["items"]}
        self.assertEqual(set(led), {"I1", "I2"})
        self.assertEqual(led["I1"]["prior_name"], "Phillip - Samurai • Raw • 1")
        self.assertEqual(led["I1"]["prior_tags"], ["Phillip", "Samurai", "tv"])
        self.assertEqual(led["I2"]["folders"], ["A1", "post"])
        tt = {(p["kind"], p["action"]): p for p in op["ticktick"]}
        self.assertEqual(tt[("logbook", "renamed")]["prior"], {"title": A_TITLE})
        self.assertEqual(tt[("logbook", "renamed")]["pid"], REC)
        self.assertEqual(tt[("row", "retitled")]["prior"]["title"],
                         "[Phillip - Samurai](eagle://folder/A1)")
        self.assertEqual(tt[("row", "retitled")]["pid"], TV_PID)
        self.assertEqual(self.toasts,
                         ["✏️ Phillip - Samurai → Phillip - Dragon · 2 shots · row · logbook"])

    def test_prefixed_name_is_the_full_base(self):
        self.script["ask"] = ["Phillip - Dragon"]
        xact.album_rename("tA")
        self.assertEqual(self.name_of("A1"), "Phillip - Dragon")
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Phillip • Dragon")

    def test_john_doe_rename_has_no_logbook(self):
        self.script["ask"] = ["Hydra"]
        xact.album_rename("tB")
        self.assertEqual(self.name_of("B1"), "Hydra")
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Hydra • Raw • 1")
        self.assertEqual(it["I3"]["tags"], ["x", "Hydra"])
        self.assertEqual(it["I5"]["name"], "IMG_9")                    # hand-named kept
        self.assertEqual(it["I5"]["tags"], ["reel", "Hydra"])          # tags still rebased
        self.assertEqual(self.api.tasks["tB"]["title"], "[Hydra](eagle://folder/B1)")
        self.assertEqual(self.api.tasks["tB"]["content"], "·")
        self.assertEqual({u[0] for u in self.api.updates}, {"tB"})     # no logbook
        op = self.ops()[0]
        self.assertEqual([p["kind"] for p in op["ticktick"]], ["row"])
        self.assertEqual(self.toasts, ["✏️ Zeus → Hydra · 3 shots · row"])

    def test_subtree_shots_follow(self):
        self.rows.append(_row("tE", "Erol - Griffin", "E1", "📸edit"))
        self.seed()
        self.script["ask"] = ["Erol - Hydra"]
        xact.album_rename("tE")
        it = self.fake.items
        self.assertEqual(it["I6"]["name"], "Erol - Hydra • Raw • 1")
        self.assertEqual(it["I7"]["name"], "Erol - Hydra • Raw • 2")   # in child Video
        self.assertEqual(it["I7"]["folders"], ["E1V"])
        self.assertEqual(it["I6"]["tags"], ["Erol", "Hydra"])
        self.assertEqual(self.name_of("E1V"), "Video")
        self.assertEqual(self.name_of("E1"), "Erol - Hydra")

    def test_cancel_same_and_not_a_row(self):
        self.script["ask"] = [None]
        xact.album_rename("tA")
        self.script["ask"] = ["Phillip - Samurai"]
        xact.album_rename("tA")
        xact.album_rename("nope")
        self.assertEqual(self.toasts, ["Cancelled", "Same name · nothing to do",
                                       "Not a pipeline row · run tsy"])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.ops(), [])

    def test_failure_ledgers_the_partial_work(self):
        def boom(items):
            raise ta.real_eagle.EagleError("plugin off")
        self.fake.update_items = boom
        self.script["ask"] = ["Dragon"]
        xact.album_rename("tA")
        self.assertEqual(self.name_of("A1"), "Phillip - Dragon")      # already renamed
        self.assertEqual(self.api.updates, [])                        # TickTick untouched
        self.assertEqual(len(self.toasts), 1)
        self.assertTrue(self.toasts[0].startswith("✏️ Rename stopped · plugin off"))
        self.assertIn("partial work ledgered", self.toasts[0])
        ops = self.ops()
        self.assertEqual(len(ops), 1)
        self.assertIn("STOPPED: plugin off", ops[0]["note"])
        self.assertEqual(ops[0]["folders"][0]["prior_name"], "Phillip - Samurai")
        # undo takes the folder back
        self.fake.update_items = lambda items: None
        self.assertIn("Undid rename", albums.undo_last())
        self.assertEqual(self.name_of("A1"), "Phillip - Samurai")


# ───────────────────────────────────────────────────────── merge

class Merge(AlbBase):
    def test_both_logbooks_keep_a(self):
        self.link_b()
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Phillip (this)", "Merge"]
        xact.album_merge("tA", "B1")
        # decisions
        kinds = [p[0] for p in self.prompts]
        self.assertEqual(kinds, ["choose", "dialog", "dialog"])
        self.assertEqual(self.prompts[0][2], ["Phillip - Samurai", "Zeus", "✏️ New name…"])
        self.assertEqual(self.prompts[0][3], "Phillip - Samurai")
        self.assertEqual(self.prompts[1][2], ["Cancel", "Zeus (other)", "Phillip (this)"])
        confirm = self.prompts[2][1]
        self.assertIn("2 shots → Phillip - Samurai · 1 twins → Duplicates", confirm)
        self.assertIn("its row → TickTick Trash · this row stays 📸raw", confirm)
        self.assertIn(f"logbook {B_TITLE} → folded into {A_TITLE} · Phillip keeps it", confirm)
        self.assertIn("Zeus husk → 🗑 Deleted", confirm)
        self.assertNotIn("renamed", confirm)
        # (1) logbooks: B folded into A, B + its row trashed in that order
        self.assertEqual(self.api.deleted, [(REC, "B"), (TV_PID, "tB")])
        a = self.api.tasks["A"]
        self.assertIn("### 2026-02-10 · S1", a["content"])
        self.assertIn(ta.CUST_A, a["content"].partition("\n## ")[0])
        self.assertEqual(a["title"], A_TITLE)
        self.assertNotIn("/tasks/B)", self.api.tasks["cb"]["content"])
        self.assertIn("started 2026-02-10", self.api.tasks["ca"]["content"])
        # B's open calendar tasks now link A: S3 = A's next number, Prepare kept
        self.assertEqual(self.api.tasks["cS"]["title"], f"{LINK_A} S3")
        self.assertEqual(self.api.tasks["cS"]["priority"], 5)
        self.assertEqual(self.api.tasks["cP"]["title"], f"Prepare for {LINK_A}")
        self.assertEqual(cache.find_task("cS")["title"], f"{LINK_A} S3")
        # (2) rows: the tag follows the FOLDER - A keeps its own stage
        # (merge-time ruling 2026-09-11: a 01 Raw album must not wear 📸edit)
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸raw"])
        self.assertEqual(self.api.tasks["tA"]["title"], "[Phillip - Samurai](eagle://folder/A1)")
        self.assertIsNone(cache.find_task("tB"))
        # (3) Eagle: twin → Duplicates, the rest continue A's numbering
        it = self.fake.items
        self.assertEqual(it["I3"]["folders"], ["DUP"])
        self.assertEqual(it["I3"]["name"], "Zeus • Raw • 1")
        self.assertEqual(it["I4"]["name"], "Phillip - Samurai • Raw • 3")
        self.assertEqual(it["I4"]["folders"], ["A1"])
        self.assertEqual(it["I4"]["tags"], ["Phillip", "Samurai"])
        self.assertEqual(it["I5"]["name"], "Phillip - Samurai • Raw • 4")
        self.assertEqual(it["I5"]["tags"], ["reel", "Phillip", "Samurai"])
        self.assertEqual(it["I1"]["name"], "Phillip - Samurai • Raw • 1")   # A untouched
        self.assertEqual(self.parent_of("B1"), "BIN")
        self.assertIn(("ensure_library", "tv"), self.fake.calls)
        self.assertNotIn("rename_folder", [c[0] for c in self.fake.calls])
        # (4) ledger + toast
        ops = self.ops()
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op["verb"], "merge")
        self.assertEqual(op["note"], "Zeus → Phillip - Samurai")
        led = {e["id"]: e for e in op["items"]}
        self.assertEqual(set(led), {"I3", "I4", "I5"})
        self.assertEqual(led["I3"]["folders"], ["DUP"])
        self.assertEqual(led["I3"]["prior_folders"], ["B1"])
        self.assertEqual(led["I4"]["prior_name"], "Zeus • Raw • 3")
        self.assertEqual(op["folders"][-1]["id"], "B1")
        self.assertEqual(op["folders"][-1]["parent"], "BIN")
        tt = sorted((p["kind"], p["action"], p["id"]) for p in op["ticktick"])
        self.assertEqual(tt, [("logbook", "merged", "A"), ("logbook", "merged", "B"),
                              ("row", "trashed", "tB"),
                              ("task", "retitled", "cP"), ("task", "retitled", "cS")])
        trashed = next(p for p in op["ticktick"] if p["action"] == "trashed")
        self.assertEqual(trashed["prior"]["title"], "[Zeus](eagle://folder/B1)")
        self.assertEqual(len(self.toasts), 1)
        toast = self.toasts[0]
        self.assertTrue(toast.startswith("🔗 Zeus → Phillip - Samurai · 2 shots · 1 twins → Duplicates"))
        for bit in ("logbook merged", "2 calendar task(s) → this logbook", "row trashed",
                    "B was 📸edit · this row stays 📸raw", "husk → 🗑",
                    "2 image refs point at the trashed note - re-plant from Eagle if needed"):
            self.assertIn(bit, toast)

    def test_b_customer_keeps_it_and_a_new_name(self):
        self.link_b()
        self.script["choose"] = ["✏️ New name…"]
        self.script["ask"] = ["Dragon"]
        self.script["dialog"] = ["Zeus (other)", "Merge"]
        xact.album_merge("tA", "B1")
        self.assertEqual(self.prompts[1][2], "Phillip - Samurai")       # ask prefill
        self.assertIn("renamed → Dragon", self.prompts[3][1])
        self.assertIn("Zeus keeps it", self.prompts[3][1])
        # A's header + TITLE carry B's customer, then the tattoo part renamed
        a = self.api.tasks["A"]
        self.assertIn(ta.CUST_B, a["content"].partition("\n## ")[0])
        self.assertEqual(a["title"], "🎨 Zeus • Dragon")
        cb = self.api.tasks["cb"]["content"]
        self.assertIn("[🎨 Zeus • Dragon](https://ticktick.com/webapp/#p/%s/tasks/A)" % REC, cb)
        self.assertNotIn("/tasks/B)", cb)
        self.assertNotIn("/tasks/A)", self.api.tasks["ca"]["content"])
        # calendar tasks: relinked to A, link text follows the final title
        link = cr.task_link(REC, "A", "🎨 Zeus • Dragon")
        self.assertEqual(self.api.tasks["cS"]["title"], f"{link} S3")
        self.assertEqual(self.api.tasks["cP"]["title"], f"Prepare for {link}")
        # Eagle: merge, then the ripple with the new base
        self.assertEqual(self.name_of("A1"), "Dragon")
        it = self.fake.items
        self.assertEqual(it["I1"]["name"], "Dragon • Raw • 1")
        self.assertEqual(it["I1"]["tags"], ["tv", "Dragon"])
        self.assertEqual(it["I4"]["name"], "Dragon • Raw • 3")
        self.assertEqual(it["I4"]["tags"], ["Dragon"])
        self.assertEqual(it["I3"]["folders"], ["DUP"])
        self.assertEqual(self.parent_of("B1"), "BIN")
        # row: title + 🎨 text, tag from B
        self.assertEqual(self.api.tasks["tA"]["title"], "[Dragon](eagle://folder/A1)")
        self.assertEqual(self.api.tasks["tA"]["content"], f"🎨 {link}")
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸raw"])   # tag follows the folder
        # ledger: a moved-then-rebased shot keeps its FIRST prior state
        op = self.ops()[0]
        self.assertEqual(op["note"], "Zeus → Phillip - Samurai → Dragon")
        led = {e["id"]: e for e in op["items"]}
        self.assertEqual(len(op["items"]), 5)                           # I1 I2 I3 I4 I5 once
        self.assertEqual(led["I4"]["prior_name"], "Zeus • Raw • 3")
        self.assertEqual(led["I4"]["prior_folders"], ["B1"])
        self.assertEqual(led["I4"]["name"], "Dragon • Raw • 3")
        self.assertEqual(led["I1"]["prior_name"], "Phillip - Samurai • Raw • 1")
        self.assertEqual([f["id"] for f in op["folders"]], ["B1", "A1"])
        # the FINAL title rides the merge write (one write to A, no
        # re-GET between writes): A's merged piece carries the prior
        # title, no separate 'renamed' pieces
        self.assertEqual([p["action"] for p in op["ticktick"] if p["kind"] == "logbook"],
                         ["merged", "merged"])
        a_piece = next(p for p in op["ticktick"] if p["id"] == "A")
        self.assertEqual(a_piece["prior"], {"absorbed": "B", "title": A_TITLE})
        self.assertEqual(a_piece["backup"]["content"], ta.NOTE_A)
        ups = self.updates("A")
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0][2]["title"], "🎨 Zeus • Dragon")
        self.assertIn("### 2026-02-10 · S1", ups[0][2]["content"])
        self.assertEqual(ups[0][2]["projectId"], REC)
        self.assertIn("renamed → Dragon", self.toasts[0])
        # undo takes the whole Eagle side back in one go
        albums.undo_last()
        self.assertEqual(it["I4"]["name"], "Zeus • Raw • 3")
        self.assertEqual(it["I4"]["folders"], ["B1"])
        self.assertEqual(it["I1"]["name"], "Phillip - Samurai • Raw • 1")
        self.assertEqual(self.name_of("A1"), "Phillip - Samurai")
        self.assertEqual(self.parent_of("B1"), "raw")

    def test_adopt_only(self):
        # A = Zeus (John Doe), B = Phillip - Samurai (logbook A): A adopts it
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tB", "A1")
        self.assertEqual([p[0] for p in self.prompts], ["choose", "dialog"])
        self.assertIn(f"logbook {A_TITLE} → adopted by this row", self.prompts[1][1])
        self.assertIn("renamed → Phillip - Samurai", self.prompts[1][1])
        # the logbook's 🦅 line → this album, 🎬 kept, nothing trashed
        a = self.api.tasks["A"]
        head = a["content"].partition("\n## ")[0]
        self.assertIn("🦅 [Eagle folder](eagle://folder/B1) · TV", head)
        self.assertNotIn("eagle://folder/A1", head)
        self.assertIn("🎬 TV", head)
        self.assertEqual(a["title"], A_TITLE)
        self.assertEqual(self.api.deleted, [(TV_PID, "tA")])
        # the row: 🎨 link body, title, stage tag stays (raw < edit)
        tb = self.api.tasks["tB"]
        self.assertEqual(tb["content"], f"🎨 {LINK_A}")
        self.assertEqual(tb["title"], "[Phillip - Samurai](eagle://folder/B1)")
        self.assertEqual(tb["tags"], ["📸edit"])
        self.assertEqual(cache.find_task("tB")["content"], f"🎨 {LINK_A}")
        # Eagle: twin → Duplicates, I2 continues Zeus' numbering then rebases
        it = self.fake.items
        self.assertEqual(it["I1"]["folders"], ["DUP"])
        self.assertEqual(it["I2"]["name"], "Phillip - Samurai • Raw • 4")
        self.assertEqual(it["I2"]["folders"], ["B1", "post"])           # shelf kept
        self.assertEqual(it["I3"]["name"], "Phillip - Samurai • Raw • 1")
        self.assertEqual(it["I3"]["tags"], ["x", "Phillip", "Samurai"])
        self.assertEqual(it["I4"]["name"], "Phillip - Samurai • Raw • 3")
        self.assertEqual(it["I5"]["name"], "IMG_9")
        self.assertEqual(it["I5"]["tags"], ["reel", "Phillip", "Samurai"])
        self.assertEqual(self.name_of("B1"), "Phillip - Samurai")
        self.assertEqual(self.parent_of("A1"), "BIN")
        op = self.ops()[0]
        acts = sorted((p["kind"], p["action"]) for p in op["ticktick"])
        # the row's body + title ride ONE write (the ripple's), the
        # logbook's title was already right: no 'renamed' / 'relinked'
        self.assertEqual(acts, [("logbook", "adopted"), ("row", "retitled"),
                                ("row", "trashed")])
        adopted = next(p for p in op["ticktick"] if p["action"] == "adopted")
        self.assertEqual(adopted["prior"], {"eagle": "A1"})
        retitled = next(p for p in op["ticktick"] if p["action"] == "retitled")
        self.assertEqual(retitled["prior"], {"title": "[Zeus](eagle://folder/B1)",
                                             "content": "·"})
        self.assertEqual(len(self.updates("tB")), 1)
        self.assertEqual(len(self.updates("A")), 1)
        self.assertTrue(self.toasts[0].startswith(
            "🔗 Phillip - Samurai → Phillip - Samurai · 1 shots · 1 twins → Duplicates"))
        self.assertIn("logbook adopted", self.toasts[0])
        self.assertNotIn("image refs", self.toasts[0])

    def test_no_ticktick_pieces_children_created(self):
        # B = Erol - Griffin (no row, no logbook) with a Video child
        self.script["choose"] = ["Zeus"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tB", "E1")
        confirm = self.prompts[1][1]
        self.assertIn("2 shots → Zeus · new: Video", confirm)
        self.assertNotIn("row", confirm)
        self.assertNotIn("logbook", confirm)
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.api.deleted, [])
        it = self.fake.items
        self.assertEqual(it["I6"]["name"], "Zeus • Raw • 4")
        self.assertEqual(it["I6"]["folders"], ["B1"])
        self.assertEqual(it["I6"]["tags"], ["Zeus"])
        self.assertIn(("create_folder", "Video", "B1"), self.fake.calls)
        self.assertEqual(it["I7"]["folders"], ["NEW1"])
        self.assertEqual(it["I7"]["name"], "Zeus • Raw • 1")
        self.assertEqual(self.parent_of("NEW1"), "B1")
        self.assertEqual(self.parent_of("E1"), "BIN")
        op = self.ops()[0]
        self.assertEqual([(f["id"], f["created"]) for f in op["folders"]],
                         [("NEW1", True), ("E1", False)])
        self.assertEqual(op["ticktick"], [])
        self.assertEqual(self.toasts, ["🔗 Erol - Griffin → Zeus · 2 shots · husk → 🗑"])

    def test_cancel_roads_write_nothing(self):
        self.link_b()
        self.script["choose"] = [None]
        xact.album_merge("tA", "B1")
        self.script["choose"] = ["Zeus"]
        self.script["dialog"] = ["Cancel"]
        xact.album_merge("tA", "B1")
        self.script["choose"] = ["Zeus"]
        self.script["dialog"] = ["Phillip (this)", ""]
        xact.album_merge("tA", "B1")
        xact.album_merge("tA", "A1")
        xact.album_merge("nope", "B1")
        xact.album_merge("tA", "ZZ")
        self.rows.append(_row("tE", "Erol - Griffin", "E1", "📸edit"))
        self.seed()
        xact.album_merge("tE", "E1V")
        self.assertEqual(self.toasts, [
            "Cancelled", "Cancelled", "Cancelled", "Same album · nothing to merge",
            "Not a pipeline row · run tsy", "Album not found in TV · pick again",
            "One album is inside the other · nothing to merge"])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.ops(), [])

    def test_eagle_failure_after_ticktick_is_ledgered(self):
        self.link_b()

        def boom(items):
            raise ta.real_eagle.EagleError("plugin off")
        self.fake.update_items = boom
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Phillip (this)", "Merge"]
        xact.album_merge("tA", "B1")
        self.assertEqual(self.api.deleted, [(REC, "B"), (TV_PID, "tB")])   # done before
        self.assertEqual(self.fake.items["I4"]["folders"], ["B1"])         # not moved
        self.assertTrue(self.toasts[-1].startswith("🔗 Merge stopped · plugin off"))
        ops = self.ops()
        self.assertEqual(len(ops), 1)
        self.assertIn("STOPPED: plugin off", ops[0]["note"])
        acts = sorted(p["action"] for p in ops[0]["ticktick"])
        self.assertEqual(acts, ["merged", "merged", "retitled", "retitled",
                                "trashed"])


# ─────────────────────────────────── review fixes (2026-09-11, C1-C9)

class LagAPI(ta.FakeAPI):
    """The REAL update semantics (the full `current` object is posted,
    then the fields) plus TickTick's documented read lag: the first GET
    after a write serves the pre-write object once."""

    def __init__(self, tasks):
        super().__init__(tasks)
        self.stale = {}

    def get_task(self, pid, tid):
        if tid in self.stale:
            t = self.stale.pop(tid)
            if t.get("projectId") != pid:
                raise KeyError("404")
            return dict(t)
        return super().get_task(pid, tid)

    def update_task(self, tid, pid, current=None, **fields):
        self.updates.append((tid, pid, dict(fields)))
        self.stale[tid] = dict(self.tasks[tid])
        if current is not None:
            self.tasks[tid].update({k: v for k, v in current.items()
                                    if not k.startswith("_") and k != "projectId"})
        self.tasks[tid].update({k: v for k, v in fields.items() if k != "projectId"})
        return dict(self.tasks[tid])


def _write_tree(lib_path, tree):
    import json
    with open(os.path.join(lib_path, "metadata.json"), "w") as f:
        json.dump({"folders": tree}, f)


class FinalsRule(AlbBase):
    """C1: the merge honours the finals rule the move verb enforces."""

    def test_finals_refused_into_a_raw_survivor(self):
        # A1 (01 Raw) absorbing its own 04 Portfolio twin P1: refused
        # BEFORE any question, nothing written
        xact.album_merge("tA", "P1")
        self.assertEqual(self.toasts,
                         ["🔗 finals live in 04 Portfolio · 1 of 1 shots are finals"])
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.fake.items["I8"]["name"], "Phillip - Samurai • Portfolio • 1")

    def test_raws_into_a_portfolio_survivor_ask_first(self):
        self.rows.append(_row("tP", "Phillip - Samurai", "P1", "📸post"))
        self.seed()
        self.script["dialog"] = ["Cancel"]
        xact.album_merge("tP", "B1")
        self.assertEqual(self.toasts, ["Cancelled"])
        self.assertEqual(self.prompts[0][0], "dialog")
        self.assertIn("Move raws into a Portfolio album? (3 of 3", self.prompts[0][1])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.ops(), [])
        # Move: the merge goes on (name question next) and finals label
        self.toasts.clear()
        self.script["dialog"] = ["Move", "Merge"]
        self.script["choose"] = ["Phillip - Samurai"]
        xact.album_merge("tP", "B1")
        self.assertEqual([p[0] for p in self.prompts[1:]], ["dialog", "choose", "dialog"])
        it = self.fake.items                     # I3's twin I1 lives in A1, not P1
        self.assertEqual(it["I3"]["name"], "Phillip - Samurai • Portfolio • 2")
        self.assertEqual(it["I4"]["name"], "Phillip - Samurai • Portfolio • 3")
        self.assertEqual(it["I4"]["folders"], ["P1"])
        self.assertEqual(it["I3"]["folders"], ["P1"])
        self.assertEqual(self.parent_of("B1"), "BIN")
        self.assertTrue(self.toasts[0].startswith("🔗 Zeus → Phillip - Samurai · 3 shots"))

    def test_same_name_skips_the_choose(self):
        tree = ta.copy.deepcopy(ta.TREE)
        tree[0]["children"][1]["name"] = "Phillip - Samurai"       # B1 twin name
        _write_tree(self.lib, tree)
        self.fake.tree[0]["children"][1]["name"] = "Phillip - Samurai"
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tA", "B1")
        self.assertEqual([p[0] for p in self.prompts], ["dialog"])    # no choose
        self.assertIn("🔗 Merge Phillip - Samurai into Phillip - Samurai?", self.prompts[0][1])
        self.assertNotIn("renamed", self.prompts[0][1])
        self.assertEqual(self.parent_of("B1"), "BIN")
        self.assertEqual(self.name_of("A1"), "Phillip - Samurai")
        self.assertNotIn("rename_folder", [c[0] for c in self.fake.calls])


class PickedName(AlbBase):
    """C2 + C7 + C8: the chosen/typed name resolves under the survivor's
    customer, typed text is sanitised, twins are refused."""

    def test_picked_bare_name_keeps_the_customer_part(self):
        self.link_b()
        self.script["choose"] = ["Zeus"]
        self.script["dialog"] = ["Phillip (this)", "Merge"]
        xact.album_merge("tA", "B1")
        self.assertIn("• renamed → Phillip - Zeus", self.prompts[2][1])
        self.assertEqual(self.name_of("A1"), "Phillip - Zeus")
        it = self.fake.items
        self.assertEqual(it["I1"]["name"], "Phillip - Zeus • Raw • 1")
        self.assertEqual(it["I1"]["tags"], ["Phillip", "tv", "Zeus"])   # customer tag kept
        self.assertEqual(it["I4"]["name"], "Phillip - Zeus • Raw • 3")
        self.assertEqual(it["I4"]["tags"], ["Phillip", "Zeus"])
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Phillip • Zeus")
        self.assertEqual(self.api.tasks["tA"]["title"], "[Phillip - Zeus](eagle://folder/A1)")
        self.assertEqual(self.api.tasks["tA"]["content"],
                         f"🎨 {cr.task_link(REC, 'A', '🎨 Phillip • Zeus')}")
        self.assertIn("[🎨 Phillip • Zeus](", self.api.tasks["ca"]["content"])
        self.assertEqual(len(self.updates("A")), 1)                    # one write to A

    def test_picked_own_name_under_the_other_customer(self):
        # B's customer keeps the tattoo and A's own name is picked: the
        # folder follows the customer like the logbook title does
        self.link_b()
        self.rows[1]["title"] = "[Zeus - Zeus](eagle://folder/B1)"
        self.fake.tree[0]["children"][1]["name"] = "Zeus - Zeus"
        tree = ta.copy.deepcopy(ta.TREE)
        tree[0]["children"][1]["name"] = "Zeus - Zeus"
        _write_tree(self.lib, tree)
        self.seed()
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Zeus (other)", "Merge"]
        xact.album_merge("tA", "B1")
        self.assertIn("• renamed → Zeus - Samurai", self.prompts[2][1])
        self.assertEqual(self.name_of("A1"), "Zeus - Samurai")
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Zeus • Samurai")
        self.assertEqual(self.fake.items["I1"]["tags"], ["Samurai", "tv", "Zeus"])

    def test_typed_names_are_sanitised(self):
        r = xact._alb_resolve_base
        self.assertEqual(r("Phillip - Samurai", "Dragon [left]", True), "Phillip - Dragon left")
        self.assertEqual(r("Zeus", "Hydra (cover-up)", False), "Hydra cover-up")
        self.assertEqual(r("Phillip - Samurai", "Dragon (x)", True, safe=False),
                         "Phillip - Dragon (x)")
        self.script["ask"] = ["Dragon [left]"]
        xact.album_rename("tA")
        self.assertEqual(self.name_of("A1"), "Phillip - Dragon left")
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Phillip • Dragon left")
        self.assertEqual(self.api.tasks["tA"]["title"],
                         "[Phillip - Dragon left](eagle://folder/A1)")
        self.assertEqual(self.fake.items["I1"]["name"], "Phillip - Dragon left • Raw • 1")

    def test_rename_refuses_a_sibling_twin(self):
        self.script["ask"] = ["Phillip - Samurai"]
        xact.album_rename("tB")
        self.assertEqual(self.toasts,
                         ["✏️ Phillip - Samurai exists in 01 Raw/Phillip - Samurai · 🔗 Merge instead"])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.api.updates, [])
        self.assertEqual(self.ops(), [])
        # a same-named album under ANOTHER parent is not a twin (the
        # Raw + Portfolio pair shares its name by design)
        self.rows.append(_row("tE", "Erol - Griffin", "E1", "📸edit"))
        self.seed()
        self.script["ask"] = ["Zeus"]
        xact.album_rename("tE")
        self.assertEqual(self.name_of("E1"), "Zeus")
        self.assertEqual(len(self.ops()), 1)

    def test_merge_typed_name_refuses_a_twin(self):
        self.script["choose"] = ["✏️ New name…"]
        self.script["ask"] = ["Phillip - Samurai"]
        xact.album_merge("tB", "E1")
        self.assertEqual(self.toasts, ["🔗 Phillip - Samurai exists in 01 Raw/Phillip - Samurai"
                                       " · pick that album instead"])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.ops(), [])
        # the album being absorbed does not count as a twin
        self.toasts.clear()
        self.script["choose"] = ["✏️ New name…"]
        self.script["ask"] = ["Zeus"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tA", "B1")
        self.assertTrue(self.toasts[0].startswith("🔗 Zeus → Phillip - Zeus"), self.toasts)


class LedgerPriors(AlbBase):
    """C3: a wrong merge can be reconstructed from the ledger."""

    def test_ledger_carries_both_logbooks_prior_text(self):
        self.link_b()
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Phillip (this)", "Merge"]
        xact.album_merge("tA", "B1")
        op = self.ops()[0]
        a = next(p for p in op["ticktick"] if p["id"] == "A")
        b = next(p for p in op["ticktick"] if p["id"] == "B")
        self.assertEqual(a["prior"], {"absorbed": "B", "title": A_TITLE})
        self.assertEqual(a["backup"], {"content": ta.NOTE_A, "title": A_TITLE,
                                       "tags": ["🗂️logbook"]})
        self.assertEqual(b["prior"], {"into": "A", "title": B_TITLE})
        self.assertEqual(b["backup"], {"content": ta.NOTE_B, "title": B_TITLE,
                                       "tags": ["🗂️logbook"], "pid": REC})
        toast = albums.undo_last()
        self.assertIn(f"logbook A was merged (prior absorbed B · title {A_TITLE})", toast)
        self.assertIn(f"logbook B was merged (prior into A · title {B_TITLE})", toast)
        self.assertNotIn("## Sessions", toast)          # the text stays in the ledger


class LaggingReads(AlbBase):
    """C4 + C6: every TickTick task is written ONCE per verb on carried
    state, so a lagging read between writes cannot revert the first."""

    def seed(self):
        self.api = LagAPI(self.rows + self.notes + self.cal)
        cr._api = lambda: self.api
        cache.set("all_tasks", [dict(r) for r in self.rows + self.cal])
        cache.set("all_notes", [dict(n) for n in self.notes + self.rows])

    def test_keep_b_new_name_survives_the_lag(self):
        self.link_b()
        self.script["choose"] = ["✏️ New name…"]
        self.script["ask"] = ["Dragon"]
        self.script["dialog"] = ["Zeus (other)", "Merge"]
        xact.album_merge("tA", "B1")
        self.assertTrue(self.toasts[0].startswith("🔗 Zeus → Dragon"), self.toasts)
        a = self.api.tasks["A"]
        self.assertEqual(a["title"], "🎨 Zeus • Dragon")
        self.assertIn("### 2026-02-10 · S1", a["content"])
        self.assertIn("merged 🎨 Zeus • Zeus into this logbook", a["content"])
        self.assertIn(ta.CUST_B, a["content"].partition("\n## ")[0])
        self.assertEqual(len(self.updates("A")), 1)
        link = cr.task_link(REC, "A", "🎨 Zeus • Dragon")
        cb = self.api.tasks["cb"]["content"]
        self.assertEqual(cb.count("/tasks/A)"), 1)
        self.assertIn(f"[🎨 Zeus • Dragon](https://ticktick.com/webapp/#p/{REC}/tasks/A)", cb)
        self.assertNotIn("/tasks/B)", cb)
        self.assertNotIn("/tasks/A)", self.api.tasks["ca"]["content"])
        self.assertEqual(self.api.tasks["cS"]["title"], f"{link} S3")
        self.assertEqual(self.api.tasks["cP"]["title"], f"Prepare for {link}")
        self.assertEqual(self.api.tasks["tA"]["title"], "[Dragon](eagle://folder/A1)")
        self.assertEqual(self.api.tasks["tA"]["content"], f"🎨 {link}")
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸raw"])
        self.assertEqual(len(self.updates("tA")), 1)
        self.assertNotIn("B", self.api.tasks)

    def test_same_customer_note_written_once(self):
        # B's logbook under Phillip too: drop B + sync A in ONE write
        b_bul = (f"- [{B_TITLE}](https://ticktick.com/webapp/#p/{REC}/tasks/B)"
                 " - started 2026-02-10 · finished 2026-04-05 · 300€ · 2 sessions")
        self.notes[1] = _note("B", B_TITLE, ta.NOTE_B.replace(ta.CUST_B, ta.CUST_A))
        self.notes[2]["content"] = self.notes[2]["content"].replace(
            "\n## Notes", f"{b_bul}\n\n## Notes", 1)
        self.link_b()
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tA", "B1")
        self.assertEqual([p[0] for p in self.prompts], ["choose", "dialog"])
        ca = self.api.tasks["ca"]["content"]
        self.assertEqual(ca.count("/tasks/A)"), 1)
        self.assertNotIn("/tasks/B)", ca)
        self.assertIn("started 2026-02-10 · finished - · 600€ of 800€", ca)
        self.assertEqual(len(self.updates("ca")), 1)
        self.assertEqual(len(self.updates("A")), 1)

    def test_adopt_with_a_new_name_writes_the_row_once(self):
        # A = Zeus (John Doe) adopts B's logbook under a typed name: the
        # row's 🎨 link text follows the new title, ONE write per task
        self.script["choose"] = ["✏️ New name…"]
        self.script["ask"] = ["Dragon"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tB", "A1")
        self.assertEqual(self.prompts[1][2], "Zeus")                   # ask prefill
        self.assertIn("• renamed → Phillip - Dragon", self.prompts[2][1])
        a = self.api.tasks["A"]
        self.assertEqual(a["title"], "🎨 Phillip • Dragon")
        head = a["content"].partition("\n## ")[0]
        self.assertIn("🦅 [Eagle folder](eagle://folder/B1) · TV", head)
        self.assertEqual(len(self.updates("A")), 1)
        tb = self.api.tasks["tB"]
        self.assertEqual(tb["title"], "[Phillip - Dragon](eagle://folder/B1)")
        self.assertEqual(tb["content"], f"🎨 {cr.task_link(REC, 'A', '🎨 Phillip • Dragon')}")
        self.assertEqual(tb["tags"], ["📸edit"])
        self.assertEqual(len(self.updates("tB")), 1)
        self.assertIn("[🎨 Phillip • Dragon](", self.api.tasks["ca"]["content"])
        self.assertEqual(self.name_of("B1"), "Phillip - Dragon")
        self.assertEqual(self.fake.items["I3"]["name"], "Phillip - Dragon • Raw • 1")
        op = self.ops()[0]
        acts = sorted((p["kind"], p["action"]) for p in op["ticktick"])
        self.assertEqual(acts, [("logbook", "adopted"), ("row", "retitled"), ("row", "trashed")])
        adopted = next(p for p in op["ticktick"] if p["action"] == "adopted")
        self.assertEqual(adopted["prior"], {"eagle": "A1", "title": A_TITLE})


class MergeLogbooksLive(AlbBase):
    """C3 / C4d / C5: cr.merge_logbooks - priors returned, the customer
    note written once, the year tag follows the merged Started, the
    title rides the one write, the reopen runs FIRST on carried state."""

    def setUp(self):
        super().setUp()
        self._ensure = cr._ensure_tag
        cr._ensure_tag = lambda *a, **k: None       # v2 tag POSTs stay dead

    def tearDown(self):
        cr._ensure_tag = self._ensure
        super().tearDown()

    def _archive(self, tid, started, finished, year):
        import re as _re
        n = self.api.tasks[tid]
        n["tags"] = ["🗂️archive"] + ([f"📦crm{year}"] if year else [])
        if not n["title"].startswith("🏛️"):
            n["title"] = "🏛️ " + n["title"][2:]
        n["content"] = _re.sub(r"Started \S+ · Finished \S+",
                               f"Started {started} · Finished {finished}",
                               n["content"], count=1)
        cache.set("all_notes", [dict(self.api.tasks[x]) for x in ("A", "B", "ca", "cb")])

    def test_returns_priors_and_the_carried_state(self):
        res = cr.merge_logbooks("A", "B")
        self.assertEqual(res["prior"], {"content": ta.NOTE_A, "title": A_TITLE,
                                        "tags": ["🗂️logbook"]})
        self.assertEqual(res["b_prior"], {"content": ta.NOTE_B, "title": B_TITLE,
                                          "tags": ["🗂️logbook"], "pid": REC})
        self.assertEqual(res["live"]["content"], res["content"])
        self.assertEqual(res["live"]["title"], A_TITLE)
        self.assertEqual(res["live"]["projectId"], REC)
        self.assertEqual(len(self.updates("A")), 1)
        self.assertNotIn("tags", self.updates("A")[0][2])         # active: no year tag

    def test_year_tag_follows_the_merged_started(self):
        self._archive("A", "2025-06-01", "2025-06-02", "2025")
        self._archive("B", "2023-02-01", "2023-03-01", "2023")
        res = cr.merge_logbooks("A", "B")
        self.assertFalse(res["reopened"])
        up = self.updates("A")
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][2]["tags"], ["🗂️archive", "📦crm2023"])
        self.assertIn("Started 2023-02-01 · Finished 2025-06-02", up[0][2]["content"])
        self.assertEqual(cache.find_task("A")["tags"], ["🗂️archive", "📦crm2023"])
        # A without a year tag gains one; an unchanged year writes no tags
        self.api.tasks["B"] = _note("B", B_TITLE, ta.NOTE_B)
        self._archive("A", "-", "2025-06-02", "")
        self._archive("B", "2024-01-05", "2024-02-01", "2024")
        cr.merge_logbooks("A", "B")
        self.assertEqual(self.updates("A")[-1][2]["tags"], ["🗂️archive", "📦crm2024"])
        self.api.tasks["B"] = _note("B", B_TITLE, ta.NOTE_B)
        self._archive("B", "2025-01-05", "2025-02-01", "2025")
        cr.merge_logbooks("A", "B")
        self.assertNotIn("tags", self.updates("A")[-1][2])

    def test_title_rides_the_merge_write_marker_aligned(self):
        res = cr.merge_logbooks("A", "B", keep_customer="b", title="🏛️ Zeus • Dragon")
        up = self.updates("A")
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][2]["title"], "🎨 Zeus • Dragon")     # A is active
        self.assertEqual(res["live"]["title"], "🎨 Zeus • Dragon")
        self.assertEqual(self.api.tasks["A"]["title"], "🎨 Zeus • Dragon")
        cb = self.api.tasks["cb"]["content"]
        self.assertIn(f"[🎨 Zeus • Dragon](https://ticktick.com/webapp/#p/{REC}/tasks/A)", cb)
        self.assertNotIn("/tasks/B)", cb)
        self.assertEqual(len(self.updates("cb")), 1)                  # drop B + sync A once
        self.assertEqual(len(self.updates("ca")), 1)                  # A's old bullet dropped
        self.assertNotIn("/tasks/A)", self.api.tasks["ca"]["content"])
        # both archived: the marker is 🏛️
        self.api.tasks["A"]["content"] = ta.NOTE_A
        self.api.tasks["B"] = _note("B", B_TITLE, ta.NOTE_B)
        self._archive("A", "2025-06-01", "2025-06-02", "2025")
        self._archive("B", "2023-02-01", "2023-03-01", "2023")
        cr.merge_logbooks("A", "B", title="🎨 Phillip • Samurai")
        self.assertEqual(self.api.tasks["A"]["title"], "🏛️ Phillip • Samurai")

    def test_reopen_runs_first_and_its_state_is_carried(self):
        self._archive("A", "2025-06-01", "2025-06-02", "2025")
        seen = []

        def reopen(pid, tid):
            seen.append((pid, tid, len(self.api.updates)))
            n = self.api.tasks[tid]
            content = n["content"].replace("Finished 2025-06-02", "Finished -") \
                + "- 2026-09-11 - reopened (touch-up)\n"
            n.update(content=content, tags=["🗂️logbook"], title="🎨 " + n["title"][3:])
            return {**n, "projectId": REC, "_projectId": REC}
        cr.reopen_logbook = reopen
        res = cr.merge_logbooks("A", "B", title="🏛️ Phillip • Samurai")
        self.assertTrue(res["reopened"])
        self.assertEqual(seen, [(REC, "A", 0)])                       # before any write
        up = self.updates("A")
        self.assertEqual(len(up), 1)
        self.assertIn("reopened (touch-up)", up[0][2]["content"])
        self.assertIn("### 2026-02-10 · S1", up[0][2]["content"])
        self.assertIn("Finished -", up[0][2]["content"])
        self.assertNotIn("title", up[0][2])                            # already 🎨 … Samurai
        self.assertEqual(res["live"]["title"], A_TITLE)
        self.assertNotIn("tags", up[0][2])


class LivePlan(AlbBase):
    """C9: the plan reads LIVE items when the library is open (disk
    metadata lags a fresh move); the disk fallback says so."""

    def test_live_plan_ignores_a_shot_that_already_left(self):
        self.fake.items["I4"]["folders"] = ["A1"]          # moved live, disk still says B1
        self.fake.items["I4"]["name"] = "Phillip - Samurai • Raw • 3"
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tA", "B1")
        confirm = self.prompts[1][1]
        self.assertIn("• 1 shots → Phillip - Samurai · 1 twins → Duplicates", confirm)
        self.assertNotIn("planned from disk", confirm)
        it = self.fake.items
        self.assertEqual(it["I4"]["folders"], ["A1"])                  # untouched
        self.assertEqual(it["I5"]["name"], "Phillip - Samurai • Raw • 4")
        self.assertEqual(it["I5"]["folders"], ["A1"])
        op = self.ops()[0]
        led = {e["id"]: e for e in op["items"]}
        self.assertEqual(set(led), {"I3", "I5"})
        self.assertEqual(led["I5"]["prior_folders"], ["B1"])
        self.assertNotIn("planned from disk", self.toasts[0])

    def test_disk_fallback_is_named(self):
        self.fake.lib = "CRM Library"                        # TV not open: disk plan
        self.script["choose"] = ["Phillip - Samurai"]
        self.script["dialog"] = ["Merge"]
        xact.album_merge("tA", "B1")
        confirm = self.prompts[1][1]
        self.assertIn("• 2 shots → Phillip - Samurai · 1 twins → Duplicates", confirm)
        self.assertIn("planned from disk metadata", confirm)
        self.assertIn("planned from disk metadata", self.toasts[0])
        self.assertEqual(self.fake.calls[0], ("ensure_library", "tv"))
        self.assertEqual(self.fake.items["I4"]["folders"], ["A1"])


if __name__ == "__main__":
    unittest.main()
