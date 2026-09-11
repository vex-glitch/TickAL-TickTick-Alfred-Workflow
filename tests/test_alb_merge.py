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
        self.assertIn("its row → TickTick Trash · this row → 📸edit", confirm)
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
        # (2) rows: A takes the later stage tag
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸edit"])
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
                              ("row", "retagged", "tA"), ("row", "trashed", "tB"),
                              ("task", "retitled", "cP"), ("task", "retitled", "cS")])
        trashed = next(p for p in op["ticktick"] if p["action"] == "trashed")
        self.assertEqual(trashed["prior"]["title"], "[Zeus](eagle://folder/B1)")
        self.assertEqual(len(self.toasts), 1)
        toast = self.toasts[0]
        self.assertTrue(toast.startswith("🔗 Zeus → Phillip - Samurai · 2 shots · 1 twins → Duplicates"))
        for bit in ("logbook merged", "2 calendar task(s) → this logbook", "row trashed",
                    "row → 📸edit", "husk → 🗑",
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
        self.assertEqual(self.api.tasks["tA"]["tags"], ["📸edit"])
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
        renamed = [p for p in op["ticktick"] if p["action"] == "renamed"]
        self.assertEqual([p["prior"]["title"] for p in renamed],
                         [A_TITLE, "🎨 Zeus • Samurai"])
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
        self.assertEqual(acts, [("logbook", "adopted"), ("logbook", "renamed"),
                                ("row", "relinked"), ("row", "retitled"),
                                ("row", "trashed")])
        adopted = next(p for p in op["ticktick"] if p["action"] == "adopted")
        self.assertEqual(adopted["prior"], {"eagle": "A1"})
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
        self.assertEqual(acts, ["merged", "merged", "retagged", "retitled", "retitled",
                                "trashed"])


if __name__ == "__main__":
    unittest.main()
