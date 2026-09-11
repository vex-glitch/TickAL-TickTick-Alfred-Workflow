#!/usr/bin/env python3
"""📦 Move Eagle selection (ALBUMS_SPEC §5 albmove / albmoveto / albnew,
xact.py block '# ── Albums: move ──') proven over the fixture library +
FakeEagle + FakeAPI of tests/test_albums.py: the finals rule both ways,
move + rebase + ledger, the emptied-source offer (John Doe row → Trash,
logbook row → retired + 🦅 repointed under ITS list), album_new for a
John Doe / a known customer / a new customer / an unknown date,
create_logbook started='-', and the render_albpick skeleton polish.
No network, no Eagle, no live TickTick, ~/.ticktick_alfred untouched.
Run: python3 tests/test_alb_move.py   (or unittest discover)
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "src"), os.path.join(_ROOT, "Scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_archive_list_id", "ARCHIVE")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")
import test_albums as ta  # noqa: E402  (fixture library, FakeEagle, FakeAPI)
import albums  # noqa: E402
import cache  # noqa: E402
import crm_records as cr  # noqa: E402
import xact  # noqa: E402

REC, TV_PID = ta.REC, ta.TV_PID
CUST_A = "[👤 Phillip](https://ticktick.com/webapp/#p/%s/tasks/ca)" % REC


def _row(tid, title, content="·", pid=TV_PID):
    return {"id": tid, "projectId": pid, "_projectId": pid, "status": 0,
            "title": title, "content": content, "tags": ["📸raw"]}


class FakeAPI(ta.FakeAPI):
    """test_albums' fake + the calls the move verbs add: create_task
    (rows, logbooks, customers), complete_task (content_retire) and a
    move_task that really moves (finish_logbook → archive_note)."""

    def __init__(self, tasks=()):
        super().__init__(list(tasks))
        self.created, self.completed = [], []
        self._n = 0

    def create_task(self, title, project_id=None, content=None, tags=None,
                    kind=None, **_kw):
        self._n += 1
        t = {"id": f"T{self._n}", "projectId": project_id, "title": title,
             "content": content or "", "tags": list(tags or []),
             "kind": kind or "TEXT", "status": 0}
        self.tasks[t["id"]] = dict(t)
        self.created.append(dict(t))
        return dict(t)

    def complete_task(self, pid, tid, task_data=None):
        self.completed.append((pid, tid))
        self.tasks.get(tid, {}).update(status=2)

    def move_task(self, tid, a, b):
        super().move_task(tid, a, b)
        self.tasks.get(tid, {}).update(projectId=b)

    def logbooks(self):
        return [t for t in self.created if t["kind"] == "NOTE"
                and "🗂️logbook" in t["tags"]]

    def rows(self):
        return [t for t in self.created if t["projectId"] == TV_PID]


class MoveBase(ta.Base):
    """tmp library/ledger/stash/cache (ta.Base) + the TickTick fake +
    every dialog scripted: self.answers is consumed in order, a missing
    answer returns the dialog's default."""

    def setUp(self):
        super().setUp()
        self.api = FakeAPI([ta._cust("ca", "👤 Phillip", [])])
        self._saved_cr = (cr._api, cr._ensure_tag)
        cr._api = lambda: self.api
        cr._ensure_tag = lambda *a, **k: None       # v2 tag POSTs stay dead
        self.toasts, self.prompts, self.ctx, self.answers = [], [], [], []
        names = ("_crm_say", "_dialog", "_ask", "_ask_date", "crmbrowse",
                 "_records_ready")
        self._saved_x = {n: getattr(xact, n) for n in names}
        xact._crm_say = lambda m: self.toasts.append(m)
        xact.crmbrowse = lambda c: self.ctx.append(c)
        xact._records_ready = lambda: True

        def dialog(prompt, buttons, default):
            self.prompts.append(("dialog", prompt))
            return self._next(default)

        def ask(prompt, title="TickAL", hidden=False, default=""):
            self.prompts.append(("ask", prompt, default))
            return self._next(default)

        def ask_date(prompt):
            self.prompts.append(("date", prompt))
            return self._next(None)
        xact._dialog, xact._ask, xact._ask_date = dialog, ask, ask_date
        # no capture date anywhere unless a test says so (fixture I4
        # carries an Eagle btime that would otherwise date every album)
        self._saved_alb = (albums._mdls, albums._bulk_dates, albums._btime_epoch)
        albums._mdls = lambda paths: {}
        albums._bulk_dates = lambda: set()
        albums._btime_epoch = lambda path: None

    def tearDown(self):
        cr._api, cr._ensure_tag = self._saved_cr
        for n, f in self._saved_x.items():
            setattr(xact, n, f)
        albums._mdls, albums._bulk_dates, albums._btime_epoch = self._saved_alb
        super().tearDown()

    def _next(self, default):
        return self.answers.pop(0) if self.answers else default

    def stash(self, *ids):
        self.fake.selected = list(ids)
        albums.stash(albums.selection("tv"))

    def ledger(self):
        return albums.Ledger().all()

    def prompted(self, kind):
        return [p for p in self.prompts if p[0] == kind]


# ───────────────────────────────────────────── albmove (selection → stash)

class AlbumMove(MoveBase):
    def test_selection_stashed_and_picker_opened(self):
        self.fake.selected = ["I3", "I4"]
        xact.album_move("")
        self.assertEqual(self.ctx, ["ctx:albpick:move:tv:"])
        st = albums.unstash()
        self.assertEqual([i["id"] for i in st["items"]], ["I3", "I4"])
        self.assertEqual(st["lib"], "tv")
        self.assertEqual(self.toasts, [])
        xact.album_move("tv")
        self.assertEqual(self.ctx[-1], "ctx:albpick:move:tv:")

    def test_wrong_library_or_nothing_selected_toasts(self):
        xact.album_move("")
        self.assertIn("Nothing selected", self.toasts[-1])
        self.fake.lib = "CRM Library"
        xact.album_move("")
        self.assertIn("Open the TV/FM/Studio library", self.toasts[-1])
        xact.album_move("fm")
        self.assertIn("FM library", self.toasts[-1])
        self.assertEqual(self.ctx, [])
        self.assertIsNone(albums.unstash())


# ───────────────────────────────────────────────── albmoveto (the move)

class AlbumMoveTo(MoveBase):
    def test_finals_refuse_a_raw_target(self):
        self.stash("I8")                                   # a Portfolio final
        xact.album_move_to("tv", "A1")
        self.assertIn("finals live in 04 Portfolio", self.toasts[-1])
        self.assertEqual([c for c in self.fake.calls if c[0] == "update_items"], [])
        self.assertIsNotNone(albums.unstash())             # kept for a retry
        self.assertEqual(self.ledger(), [])
        # mixed selection: still refused (one final is enough)
        self.stash("I3", "I8")
        xact.album_move_to("tv", "B1")
        self.assertIn("finals live in 04 Portfolio", self.toasts[-1])
        self.assertIn("1 of 2", self.toasts[-1])

    def test_raws_into_portfolio_ask_first(self):
        self.stash("I3")
        self.answers = ["Cancel"]
        xact.album_move_to("tv", "P1")
        self.assertEqual(self.toasts[-1], "Cancelled")
        self.assertIn("Move raws into a Portfolio album?", self.prompts[0][1])
        self.assertEqual(self.fake.items["I3"]["folders"], ["B1"])
        self.assertIsNotNone(albums.unstash())
        self.answers = ["Move"]
        xact.album_move_to("tv", "P1")
        it = self.fake.items["I3"]
        self.assertEqual(it["folders"], ["P1"])
        self.assertEqual(it["name"], "Phillip - Samurai • Portfolio • 2")  # continues P1's
        self.assertEqual(it["tags"], ["x", "Phillip", "Samurai"])
        self.assertIn("📦 1 shots → Phillip - Samurai · 04 Portfolio", self.toasts[-1])
        self.assertIsNone(albums.unstash())
        # a final already home: nothing asked, nothing moved, stash consumed
        self.prompts = []
        self.stash("I8")
        xact.album_move_to("tv", "P1")
        self.assertEqual(self.prompted("dialog"), [])
        self.assertEqual(self.fake.items["I8"]["name"], "Phillip - Samurai • Portfolio • 1")
        self.assertEqual(self.toasts[-1], "📦 all 1 shots already in Phillip - Samurai · 04 Portfolio")
        self.assertEqual(len(self.ledger()), 1)
        self.assertIsNone(albums.unstash())
        # a final from elsewhere into the Portfolio album: no ask either
        self.fake.items["I8"]["folders"] = ["A1"]
        self.stash("I8", "I3")
        xact.album_move_to("tv", "P1")
        self.assertEqual(self.prompted("dialog"), [])
        self.assertEqual(self.fake.items["I8"]["folders"], ["P1"])
        self.assertIn("1 already there", self.toasts[-1])
        self.assertTrue(self.toasts[-1].startswith("📦 1 shots → Phillip - Samurai"))

    def test_move_rebases_ledgers_and_offers_the_emptied_source(self):
        cache.set("all_tasks", [_row("tz", "[Zeus](eagle://folder/B1)"),
                                _row("tp", "[Phillip - Samurai](eagle://folder/A1)")])
        self.stash("I3", "I4", "I5")                       # all of Zeus
        self.answers = ["Bin + retire"]
        xact.album_move_to("tv", "A1")
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Phillip - Samurai • Raw • 3")
        self.assertEqual(it["I4"]["name"], "Phillip - Samurai • Raw • 4")
        self.assertEqual(it["I5"]["name"], "Phillip - Samurai • Raw • 5")
        self.assertEqual(it["I3"]["folders"], ["A1"])
        self.assertEqual(it["I5"]["tags"], ["reel", "Phillip", "Samurai"])
        self.assertEqual(self.fake.calls[0], ("ensure_library", "tv"))
        # the offer, then the husk under the bin + the John Doe row trashed
        self.assertEqual(self.prompts, [("dialog", "Zeus is empty now · bin it and retire its row?")])
        self.assertIn(("move_folder", "B1", "BIN"), self.fake.calls)
        self.assertEqual(self.api.deleted, [(TV_PID, "tz")])
        self.assertIsNone(cache.find_task("tz"))
        self.assertIsNotNone(cache.find_task("tp"))
        toast = self.toasts[-1]
        self.assertTrue(toast.startswith("📦 3 shots → Phillip - Samurai · 01 Raw"), toast)
        self.assertIn("Zeus → bin", toast)
        self.assertIn("row → Trash", toast)
        # ONE ledger op with the Eagle + TickTick pieces, stash cleared
        ops = self.ledger()
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op["verb"], "move")
        self.assertEqual(op["lib"], "tv")
        self.assertEqual({i["id"] for i in op["items"]}, {"I3", "I4", "I5"})
        self.assertEqual(op["items"][0]["prior_folders"], ["B1"])
        self.assertEqual(op["folders"][-1]["id"], "B1")
        self.assertEqual(op["folders"][-1]["parent"], "BIN")
        self.assertEqual(op["ticktick"], [{"kind": "row", "id": "tz", "pid": TV_PID,
                                           "action": "trashed",
                                           "prior": {"title": "[Zeus](eagle://folder/B1)"}}])
        self.assertIsNone(albums.unstash())

    def test_keep_answer_leaves_the_husk_and_row(self):
        cache.set("all_tasks", [_row("tz", "[Zeus](eagle://folder/B1)")])
        self.stash("I3", "I4", "I5")
        self.answers = [""]                                  # Esc
        xact.album_move_to("tv", "A1")
        self.assertNotIn(("move_folder", "B1", "BIN"), self.fake.calls)
        self.assertEqual(self.api.deleted, [])
        self.assertIn("Zeus kept", self.toasts[-1])
        self.assertEqual(self.ledger()[0]["ticktick"], [])
        # a partial move never asks: the source still holds a shot
        self.prompts = []
        self.stash("I1")
        xact.album_move_to("tv", "B1")
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.fake.items["I1"]["name"], "Zeus • Raw • 1")   # Zeus was emptied

    def test_logbook_row_is_retired_and_its_eagle_line_repointed(self):
        lg = {"id": "LG", "projectId": REC, "kind": "NOTE", "title": "🎨 Erol • Griffin",
              "tags": ["🗂️logbook"],
              "content": (f"👤 {CUST_A} · Started 2026-03-01 · Finished -\n"
                          "Paid: - · 0 sessions\n"
                          "🦅 [Eagle folder](eagle://folder/E1) · TV\n🎬 TV\n\n"
                          "## Sessions\n\n## Notes\n")}
        self.api.tasks["LG"] = dict(lg)
        row = _row("te", "[Erol - Griffin](eagle://folder/E1)",
                   content=f"🎨 [🎨 Erol • Griffin](https://ticktick.com/webapp/#p/{REC}/tasks/LG)")
        cache.set("all_tasks", [row])
        cache.set("all_notes", [dict(lg, _projectId=REC)])
        self.stash("I6", "I7")                              # E1 root + Video child
        self.answers = ["Bin + retire"]
        xact.album_move_to("tv", "A1")
        self.assertEqual(self.api.completed, [(TV_PID, "te")])
        self.assertEqual(self.api.deleted, [])
        self.assertIn(("move_folder", "E1", "BIN"), self.fake.calls)
        ups = [u for u in self.api.updates if u[0] == "LG"]
        self.assertEqual(len(ups), 2)                       # 🎬 ➖, then 🦅
        self.assertEqual(ups[-1][1], REC)
        self.assertEqual(ups[-1][2]["projectId"], REC)      # trap 16
        body = self.api.tasks["LG"]["content"]
        self.assertIn("🦅 [Eagle folder](eagle://folder/A1) · TV", body)
        self.assertIn("🎬 ➖", body)
        self.assertNotIn("eagle://folder/E1", body)
        toast = self.toasts[-1]
        self.assertIn("Erol - Griffin → bin", toast)
        self.assertIn("row retired · logbook 🦅 → destination", toast)
        tt = self.ledger()[0]["ticktick"]
        self.assertEqual([(p["kind"], p["action"]) for p in tt],
                         [("row", "retired"), ("logbook", "repointed")])
        self.assertEqual(tt[1]["prior"], {"eagle": "E1"})
        self.assertEqual(tt[1]["pid"], REC)

    def test_logbook_pointing_elsewhere_is_left_alone(self):
        lg = {"id": "LG", "projectId": REC, "kind": "NOTE", "title": "🎨 Erol • Griffin",
              "tags": ["🗂️logbook"],
              "content": (f"👤 {CUST_A} · Started 2026-03-01 · Finished -\n"
                          "Paid: - · 0 sessions\n"
                          "🦅 [Eagle folder](eagle://folder/OTHER) · CRM\n🎬 TV\n\n"
                          "## Sessions\n\n## Notes\n")}
        self.api.tasks["LG"] = dict(lg)
        cache.set("all_tasks", [_row("te", "[Erol - Griffin](eagle://folder/E1)",
                                     content=f"🎨 [x](https://ticktick.com/webapp/#p/{REC}/tasks/LG)")])
        self.stash("I6", "I7")
        self.answers = ["Bin + retire"]
        xact.album_move_to("tv", "A1")
        self.assertIn("eagle://folder/OTHER", self.api.tasks["LG"]["content"])
        self.assertEqual(len([u for u in self.api.updates if u[0] == "LG"]), 1)
        self.assertIn("row retired", self.toasts[-1])
        self.assertEqual([p["action"] for p in self.ledger()[0]["ticktick"]], ["retired"])

    def test_empty_stash_or_unknown_target_fails_closed(self):
        xact.album_move_to("tv", "A1")
        self.assertIn("select shots in Eagle first", self.toasts[-1])
        self.stash("I3")
        xact.album_move_to("tv", "ZZ")
        self.assertIn("not in the library", self.toasts[-1])
        self.assertEqual(self.fake.items["I3"]["folders"], ["B1"])
        self.assertEqual(self.ledger(), [])

    def test_eagle_failure_toasts_honestly(self):
        def boom(*a, **k):
            raise ta.real_eagle.EagleError("plugin off")
        self.fake.update_items = boom
        self.stash("I3")
        xact.album_move_to("tv", "A1")
        self.assertEqual(self.toasts[-1], "📦 plugin off")
        self.assertEqual(self.api.deleted, [])
        self.assertIsNotNone(albums.unstash())

    def test_child_target_takes_the_album_base(self):
        """Review B1: '02 Edit/Erol - Griffin/Video' is a CHILD of the
        album - shots landing there are named after Erol - Griffin
        (continuing the child's numbering) and wear its tags, never
        'Video • Raw • 1' with a bogus 'Video' tag."""
        self.stash("I3", "I4")
        xact.album_move_to("tv", "E1V")
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Erol - Griffin • Raw • 3")
        self.assertEqual(it["I4"]["name"], "Erol - Griffin • Raw • 4")
        self.assertEqual(it["I3"]["folders"], ["E1V"])
        self.assertEqual(it["I3"]["tags"], ["x", "Erol", "Griffin"])
        self.assertEqual(it["I4"]["tags"], ["Erol", "Griffin"])
        self.assertNotIn("Video", it["I3"]["tags"] + it["I4"]["tags"])
        toast = self.toasts[-1]
        self.assertTrue(toast.startswith("📦 2 shots → Erol - Griffin/Video · 02 Edit"), toast)
        self.assertEqual(self.ledger()[0]["note"], "2 shots → Erol - Griffin/Video")
        # a shot of the album root moved into its own child: same base,
        # the album is not "emptied" (the child holds the shots now)
        self.prompts = []
        self.stash("I6")
        xact.album_move_to("tv", "E1V")
        self.assertEqual(self.prompted("dialog"), [])
        self.assertEqual(it["I6"]["folders"], ["E1V"])
        self.assertTrue(it["I6"]["name"].startswith("Erol - Griffin • Raw • "))
        self.assertEqual(it["I6"]["tags"], ["Erol", "Griffin"])
        # and the depth-1 resolver itself
        albs = albums.library_albums("tv")
        self.assertEqual(xact._alb_album_of(albs, "E1V")["fid"], "E1")
        self.assertEqual(xact._alb_album_of(albs, "E1")["fid"], "E1")
        self.assertEqual(xact._alb_album_of(albs, "A1")["fid"], "A1")
        self.assertIsNone(xact._alb_album_of(albs, "post"))

    def test_emptied_child_rides_its_album(self):
        """Review B1: the album root + its Video child emptied together
        → ONE offer for the album, the husk binned WITH the child inside
        (the child was offered again and torn out of its binned parent);
        a child emptied while the album still holds shots → no offer."""
        cache.set("all_tasks", [_row("te", "[Erol - Griffin](eagle://folder/E1)")])
        self.stash("I6", "I7")                              # E1 root + Video child
        self.answers = ["Bin + retire"]
        xact.album_move_to("tv", "A1")
        self.assertEqual(self.prompts, [("dialog", "Erol - Griffin is empty now · bin it and retire its row?")])
        moves = [c for c in self.fake.calls if c[0] == "move_folder"]
        self.assertEqual(moves, [("move_folder", "E1", "BIN")])
        husk = self.fake.folder_node("E1")
        self.assertEqual([c["id"] for c in husk["children"]], ["E1V"])   # still inside
        self.assertIn("E1", [c["id"] for c in self.fake.folder_node("BIN")["children"]])
        self.assertEqual(self.api.deleted, [(TV_PID, "te")])
        op = self.ledger()[0]
        self.assertEqual([f["id"] for f in op["folders"]], ["E1"])
        self.assertEqual({i["id"] for i in op["items"]}, {"I6", "I7"})
        toast = self.toasts[-1]
        self.assertIn("Erol - Griffin → bin", toast)
        self.assertNotIn("Video", toast)

    def test_child_only_emptied_is_not_offered(self):
        """Review B1: only the Video child emptied while the album still
        holds I6 → nothing offered, the child husk stays inside; the
        group is keyed by the ALBUM so old_base = its name."""
        self.stash("I7")
        xact.album_move_to("tv", "A1")
        self.assertEqual(self.prompted("dialog"), [])
        self.assertEqual([c for c in self.fake.calls if c[0] == "move_folder"], [])
        self.assertEqual([c["id"] for c in self.fake.folder_node("E1")["children"]], ["E1V"])
        self.assertNotIn("kept", self.toasts[-1])
        self.assertNotIn("Video", self.toasts[-1])
        # the group is keyed by the ALBUM: old_base = its name, so the
        # child's shot shed the album's tags for the destination's
        self.assertEqual(self.fake.items["I7"]["tags"], ["Phillip", "Samurai"])


# ───────────────────────────────────────────────── albnew (new album)

class AlbumNew(MoveBase):
    def test_john_doe_album(self):
        self.stash("I3", "I4")                               # Zeus keeps I5
        self.answers = ["Zeus Redux"]
        xact.album_new("tv", "Raw", "none")
        self.assertEqual(self.prompts, [("ask", "Album name (the tattoo)?", "Zeus")])
        self.assertIn(("create_folder", "Zeus Redux", "raw"), self.fake.calls)
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Zeus Redux • Raw • 1")
        self.assertEqual(it["I4"]["name"], "Zeus Redux • Raw • 2")
        self.assertEqual(it["I3"]["folders"], ["NEW1"])
        self.assertEqual(it["I3"]["tags"], ["x", "Zeus Redux"])
        self.assertEqual(it["I5"]["folders"], ["B1"])           # untouched
        rows = self.api.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "[Zeus Redux](eagle://folder/NEW1)")
        self.assertEqual(rows[0]["content"], "·")
        self.assertEqual(rows[0]["tags"], ["📸raw"])
        self.assertEqual(rows[0]["kind"], "TEXT")
        self.assertEqual(self.api.logbooks(), [])
        self.assertIsNotNone(cache.find_task(rows[0]["id"]))
        ops = self.ledger()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["verb"], "new")
        self.assertEqual(ops[0]["folders"][0], {"id": "NEW1", "prior_name": "",
                                                "prior_parent": "", "name": "Zeus Redux",
                                                "parent": "raw", "created": True})
        self.assertEqual(ops[0]["ticktick"], [{"kind": "row", "id": rows[0]["id"],
                                               "pid": TV_PID, "action": "minted"}])
        self.assertEqual(len(ops[0]["items"]), 2)
        self.assertIsNone(albums.unstash())
        toast = self.toasts[-1]
        self.assertTrue(toast.startswith("➕ Zeus Redux · 01 Raw · 2 shots"), toast)
        self.assertIn("📸raw row", toast)

    def test_known_customer_with_capture_days_finished(self):
        items = albums.items_of_album("tv", "B1")
        p = {i["id"]: i["path"] for i in items}
        albums._mdls = lambda paths: {p["I3"]: 1_709_251_200,   # 2024-03-01
                                      p["I5"]: 1_709_337_600}   # 2024-03-02
        self.stash("I3", "I4", "I5")
        self.answers = ["Dragon", "Finished"]
        xact.album_new("tv", "Edit", "ca")
        self.assertEqual(self.prompts[0], ("ask", "Tattoo name for Phillip?", "Zeus"))
        self.assertEqual(self.prompts[1], ("dialog", "Tattoo state?"))
        self.assertEqual(self.prompted("date"), [])
        self.assertIn(("create_folder", "Phillip - Dragon", "edit"), self.fake.calls)
        lbs = self.api.logbooks()
        self.assertEqual(len(lbs), 1)
        lb = lbs[0]
        self.assertEqual(lb["title"], "🎨 Phillip • Dragon")
        self.assertIn("Started 2024-03-01", lb["content"])
        self.assertIn("🦅 [Eagle folder](eagle://folder/NEW1) · TV\n🎬 TV\n", lb["content"])
        # finished on the last capture day: archive tag + year tag + moved
        live = self.api.tasks[lb["id"]]
        self.assertIn("Finished 2024-03-02", live["content"])
        self.assertEqual(live["title"], "🏛️ Phillip • Dragon")
        self.assertIn("🗂️archive", live["tags"])
        self.assertIn("📦crm2024", live["tags"])
        self.assertEqual(self.api.moves, [(lb["id"], REC, "ARCHIVE")])
        self.assertIn("/tasks/%s)" % lb["id"], self.api.tasks["ca"]["content"])
        rows = self.api.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "[Phillip - Dragon](eagle://folder/NEW1)")
        self.assertEqual(rows[0]["tags"], ["📸edit"])
        self.assertIn(f"/tasks/{lb['id']})", rows[0]["content"])
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Phillip - Dragon • Raw • 1")
        self.assertEqual(it["I5"]["name"], "Phillip - Dragon • Raw • 3")
        self.assertEqual(it["I3"]["tags"], ["x", "Phillip", "Dragon"])
        # Zeus is empty now: the offer came (default = bin) and the husk went
        self.assertEqual(self.prompts[2], ("dialog", "Zeus is empty now · bin it and retire its row?"))
        self.assertIn(("move_folder", "B1", "BIN"), self.fake.calls)
        op = self.ledger()[0]
        self.assertEqual([(t["kind"], t["action"]) for t in op["ticktick"]],
                         [("logbook", "minted"), ("row", "minted")])
        self.assertEqual(op["ticktick"][0]["pid"], REC)
        toast = self.toasts[-1]
        self.assertTrue(toast.startswith("➕ Phillip - Dragon · 02 Edit · 3 shots"), toast)
        self.assertIn("🎨 logbook · finished", toast)
        self.assertIn("📸edit row", toast)
        self.assertIn("Zeus → bin", toast)

    def test_known_customer_unknown_date_stays_active(self):
        self.stash("I3")                                     # no mdls, no btime
        self.answers = ["Dragon", None, "Still active"]
        xact.album_new("tv", "Raw", "ca")
        self.assertEqual(self.prompts[1],
                         ("date", "When was it? Date or year (OK = unknown · Esc cancels)"))
        lb = self.api.logbooks()[0]
        self.assertIn("· Started - · Finished -", lb["content"])
        self.assertEqual(self.api.moves, [])
        self.assertEqual(self.api.tasks[lb["id"]]["title"], "🎨 Phillip • Dragon")
        self.assertIn("started - · finished -", self.api.tasks["ca"]["content"])
        self.assertEqual(self.api.rows()[0]["tags"], ["📸raw"])
        self.assertIn("🎨 logbook", self.toasts[-1])
        self.assertNotIn("finished", self.toasts[-1])

    def test_asked_day_is_started_and_finished(self):
        self.stash("I3")
        self.answers = ["Dragon", "2023-05-06", "Finished"]
        xact.album_new("tv", "Raw", "ca")
        lb = self.api.tasks[self.api.logbooks()[0]["id"]]
        self.assertIn("Started 2023-05-06 · Finished 2023-05-06", lb["content"])
        self.assertIn("📦crm2023", lb["tags"])

    def test_cancels_leave_nothing_behind(self):
        self.stash("I3")
        for answers in (["Dragon", "CANCEL"],            # date Esc
                        ["Dragon", None, "Cancel"],      # state Cancel
                        ["Dragon", None, ""],            # state Esc
                        [None],                          # name Esc
                        [""]):                           # empty name
            self.answers = list(answers)
            xact.album_new("tv", "Raw", "ca")
            self.assertEqual(self.toasts[-1], "Cancelled", answers)
        self.assertEqual(self.api.created, [])
        self.assertEqual([c for c in self.fake.calls if c[0] == "create_folder"], [])
        self.assertEqual(self.ledger(), [])
        self.assertIsNotNone(albums.unstash())
        # John Doe: the name prompt only, an Esc cancels
        self.prompts = []
        self.answers = [None]
        xact.album_new("tv", "Raw", "none")
        self.assertEqual(self.toasts[-1], "Cancelled")
        self.assertEqual(len(self.prompts), 1)

    def test_new_customer_is_minted_first(self):
        self.stash("I3")
        self.answers = ["Nadia", "Dragon", None, "Still active"]
        xact.album_new("tv", "Raw", "new")
        self.assertEqual(self.prompts[0], ("ask", "New customer name?", ""))
        self.assertEqual(self.prompts[1], ("ask", "Tattoo name for Nadia?", "Zeus"))
        custs = [t for t in self.api.created if "🗂️customer" in t["tags"]]
        self.assertEqual(len(custs), 1)
        self.assertEqual(custs[0]["title"], "👤 Nadia")
        lb = self.api.logbooks()[0]
        self.assertEqual(lb["title"], "🎨 Nadia • Dragon")
        self.assertIn(f"/tasks/{custs[0]['id']})", lb["content"])
        self.assertIn(("create_folder", "Nadia - Dragon", "raw"), self.fake.calls)
        self.assertEqual(self.fake.items["I3"]["name"], "Nadia - Dragon • Raw • 1")
        self.assertEqual(self.fake.items["I3"]["tags"], ["x", "Nadia", "Dragon"])
        op = self.ledger()[0]
        self.assertEqual([(t["kind"], t["action"]) for t in op["ticktick"]],
                         [("customer", "minted"), ("logbook", "minted"), ("row", "minted")])
        self.assertIn("👤 customer", self.toasts[-1])
        # the empty name cancels BEFORE any mint
        self.api.created = []
        self.stash("I4")
        self.answers = [""]
        xact.album_new("tv", "Raw", "new")
        self.assertEqual(self.toasts[-1], "Cancelled")
        self.assertEqual(self.api.created, [])

    def test_portfolio_album_has_no_row_and_asks_about_raws(self):
        self.stash("I3")
        self.answers = ["Move", "Zeus Final"]
        xact.album_new("tv", "Portfolio", "none")
        self.assertIn("Move raws into a Portfolio album?", self.prompts[0][1])
        self.assertIn(("create_folder", "Zeus Final", "port"), self.fake.calls)
        self.assertEqual(self.fake.items["I3"]["name"], "Zeus Final • Portfolio • 1")
        self.assertEqual(self.api.created, [])                 # no row, no logbook
        self.assertEqual(self.ledger()[0]["ticktick"], [])
        self.assertTrue(self.toasts[-1].startswith("➕ Zeus Final · 04 Portfolio · 1 shots"))
        # finals into a new Raw album: refused before any prompt
        self.prompts = []
        self.stash("I8")
        xact.album_new("tv", "Raw", "none")
        self.assertIn("finals live in 04 Portfolio", self.toasts[-1])
        self.assertEqual(self.prompts, [])

    def test_adopted_album_keeps_its_row(self):
        cache.set("all_tasks", [_row("tz", "[Zeus](eagle://folder/B1)")])
        self.stash("I1")
        self.answers = ["zeus"]                                # loose match → B1 adopted
        xact.album_new("tv", "Raw", "none")
        self.assertEqual([c for c in self.fake.calls if c[0] == "create_folder"], [])
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.fake.items["I1"]["folders"], ["B1"])
        self.assertEqual(self.fake.items["I1"]["name"], "Zeus • Raw • 4")   # the folder's spelling
        self.assertEqual(self.fake.items["I1"]["tags"], ["tv", "Zeus"])
        self.assertEqual(self.ledger()[0]["note"].split(" · ")[0], "zeus in Raw")
        self.assertIn("existing album adopted · its row kept", self.toasts[-1])
        self.assertIn("adopted existing Zeus", self.ledger()[0]["note"])

    def test_adopted_album_without_a_row_says_so(self):
        """Review B4: an adopted folder with no open row gets a row
        minted, and the toast still says the album was adopted."""
        self.stash("I1")
        self.answers = ["zeus"]                                # loose match → B1 adopted
        xact.album_new("tv", "Raw", "none")
        self.assertEqual([c for c in self.fake.calls if c[0] == "create_folder"], [])
        rows = self.api.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "[Zeus](eagle://folder/B1)")
        self.assertEqual(self.fake.items["I1"]["folders"], ["B1"])
        toast = self.toasts[-1]
        self.assertTrue(toast.startswith("➕ Zeus · 01 Raw · 1 shots"), toast)
        self.assertIn("existing album adopted", toast)
        self.assertNotIn("its row kept", toast)
        self.assertIn("📸raw row", toast)

    def _logbook(self, tid, title, eagle=""):
        lb = {"id": tid, "projectId": REC, "_projectId": REC, "kind": "NOTE",
              "title": title, "tags": ["🗂️logbook"], "status": 0,
              "content": (f"👤 {CUST_A} · Started 2026-03-01 · Finished -\n"
                          "Paid: - · 0 sessions\n" + eagle +
                          "\n## Sessions\n\n## Notes\n")}
        cache.set("all_notes", [dict(lb)])
        self.api.tasks[tid] = dict(lb)
        return lb

    def test_existing_logbook_is_linked_not_minted(self):
        """Review B3: Phillip already has '🎨 Phillip • Dragon' (no
        album yet - the booking road) → the new album LINKS it: no
        twin logbook, no date/state prompt, its 🦅 line → the album
        under ITS list (trap 16), the row body carries its link."""
        self._logbook("LBD", "🎨 Phillip • Dragon")
        self.stash("I3")
        self.answers = ["dragon"]                              # casefold match
        xact.album_new("tv", "Edit", "ca")
        self.assertEqual(self.api.logbooks(), [])              # nothing minted
        self.assertEqual(self.prompted("date"), [])
        self.assertEqual(self.prompted("dialog"), [])
        self.assertIn(("create_folder", "Phillip - dragon", "edit"), self.fake.calls)
        ups = [u for u in self.api.updates if u[0] == "LBD"]
        self.assertEqual(len(ups), 1)
        self.assertEqual((ups[0][1], ups[0][2]["projectId"]), (REC, REC))
        body = self.api.tasks["LBD"]["content"]
        self.assertIn("🦅 [Eagle folder](eagle://folder/NEW1) · TV", body)
        self.assertIn("🎬 TV", body)
        self.assertIn("## Sessions", body)
        self.assertEqual(cache.find_task("LBD")["content"], body)
        rows = self.api.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"],
                         f"🎨 [🎨 Phillip • Dragon](https://ticktick.com/webapp/#p/{REC}/tasks/LBD)")
        self.assertEqual(rows[0]["tags"], ["📸edit"])
        self.assertEqual(self.api.moves, [])                    # never archived
        op = self.ledger()[0]
        self.assertEqual([(t["kind"], t["action"]) for t in op["ticktick"]],
                         [("logbook", "repointed"), ("row", "minted")])
        self.assertEqual(op["ticktick"][0]["prior"], {"eagle": ""})
        toast = self.toasts[-1]
        self.assertIn("🎨 existing logbook linked · 🦅 → album", toast)
        self.assertNotIn("🎨 logbook", toast)                  # the mint's bit

    def test_existing_logbook_on_another_album_keeps_its_eagle_line(self):
        """The 01 Raw album's logbook stays pointed there when the
        02 Edit album is born for the same tattoo."""
        self._logbook("LBD", "🏛️ Phillip • Dragon",
                      eagle="🦅 [Eagle folder](eagle://folder/A1) · TV\n🎬 TV\n")
        self.api.tasks["LBD"]["tags"] = ["🗂️archive"]
        cache.set("all_notes", [dict(self.api.tasks["LBD"])])
        self.stash("I3")
        self.answers = ["Dragon"]
        xact.album_new("tv", "Edit", "ca")
        self.assertEqual(self.api.logbooks(), [])
        self.assertEqual([u for u in self.api.updates if u[0] == "LBD"], [])
        self.assertIn("eagle://folder/A1", self.api.tasks["LBD"]["content"])
        rows = self.api.rows()
        self.assertIn("[🏛️ Phillip • Dragon](https://ticktick.com/webapp/#p/%s/tasks/LBD)" % REC,
                      rows[0]["content"])
        self.assertEqual([(t["kind"], t["action"]) for t in self.ledger()[0]["ticktick"]],
                         [("row", "minted")])
        self.assertIn("🎨 existing logbook linked", self.toasts[-1])
        self.assertNotIn("🦅 → album", self.toasts[-1])
        # a different tattoo of the same customer still mints
        self.stash("I4")
        self.answers = ["Phoenix", None, "Still active"]
        xact.album_new("tv", "Edit", "ca")
        self.assertEqual([t["title"] for t in self.api.logbooks()], ["🎨 Phillip • Phoenix"])

    def test_bad_args_fail_closed(self):
        xact.album_new("tv", "Raw", "none")
        self.assertIn("select shots in Eagle first", self.toasts[-1])
        self.stash("I3")
        xact.album_new("tv", "Post", "none")
        self.assertIn("No such stage", self.toasts[-1])
        xact.album_new("tv", "Raw", "nope")
        self.assertIn("Customer not found", self.toasts[-1])
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.ledger(), [])


# ───────────────────────────────────── crm_records.create_logbook started

class CreateLogbookStarted(MoveBase):
    def test_dash_means_unknown(self):
        cust = self.api.tasks["ca"]
        lb = cr.create_logbook(cust, "T", started="-")
        self.assertIn("· Started - · Finished -", lb["content"])
        self.assertEqual(cr.archive_year(lb["content"]), "")
        self.assertEqual(cr.archive_year(lb["content"], "2021-02-03"), "2021")
        lb = cr.create_logbook(cust, "T2", started="2024-01-02")
        self.assertIn("Started 2024-01-02", lb["content"])
        lb = cr.create_logbook(cust, "T3")
        self.assertIn(f"Started {cr._today()}", lb["content"])
        lb = cr.create_logbook(cust, "T4", started="  ")
        self.assertIn(f"Started {cr._today()}", lb["content"])


# ───────────────────────────────────────── render_albpick skeleton polish

class PickerPolish(ta.Base):
    def test_skeleton_husks_hidden(self):
        import browse
        albums.stash({"lib": "tv", "items": [{"id": "I1", "name": "n", "folders": ["A1"],
                                              "tags": []}],
                      "sources": {"A1": ["I1"]}, "source_names": {"A1": "Phillip - Samurai"}})
        rows = [
            {"fid": "E1", "name": "Erol - Griffin", "stage": "Edit", "parent": "edit",
             "depth": 1, "path": "02 Edit/Erol - Griffin", "n": 2},
            {"fid": "K1", "name": "01 Consultation", "stage": "Edit", "parent": "E1",
             "depth": 2, "path": "02 Edit/Erol - Griffin/01 Consultation", "n": 0},
            {"fid": "K2", "name": "04 Sessions", "stage": "Edit", "parent": "E1",
             "depth": 2, "path": "02 Edit/Erol - Griffin/04 Sessions", "n": 3},
            {"fid": "V1", "name": "Video", "stage": "Edit", "parent": "E1",
             "depth": 2, "path": "02 Edit/Erol - Griffin/Video", "n": 0},
            {"fid": "K3", "name": "05 Finished", "stage": "Raw", "parent": "raw",
             "depth": 1, "path": "01 Raw/05 Finished", "n": 0},
        ]
        saved = albums.library_albums
        albums.library_albums = lambda lib: rows
        try:
            out = browse.render_albpick(["move", "tv", ""], "")
        finally:
            albums.library_albums = saved
        titles = [r["title"] for r in out]
        self.assertNotIn("01 Consultation", titles)          # depth 2, empty, skeleton
        self.assertIn("04 Sessions", titles)                  # not empty
        self.assertIn("Video", titles)                        # not a skeleton name
        self.assertIn("05 Finished", titles)                  # depth 1 stays
        self.assertIn("Erol - Griffin", titles)
        self.assertTrue(titles[0].startswith("📦 1 shots from Phillip - Samurai"))
        self.assertEqual(sum(1 for t in titles if t.startswith("➕ New album")), 3)


if __name__ == "__main__":
    unittest.main()
