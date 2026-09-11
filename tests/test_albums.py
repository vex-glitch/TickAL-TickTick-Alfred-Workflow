#!/usr/bin/env python3
"""ALBUMS substrate (ALBUMS_SPEC §2 + §6): every pure helper of
src/albums.py, the disk readers over a fixture library, the live movers
+ undo over a FAKE eagle module, and crm_records.merge_logbook_content /
merge_logbooks over fixture notes + a fake TickTick API.
No network, no Eagle, no live TickTick; ~/.ticktick_alfred is never
touched (ledger / stash / cache all point at a tmp dir).
Run: python3 tests/test_albums.py   (or unittest discover)
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_archive_list_id", "ARCHIVE")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")
import eagle as real_eagle  # noqa: E402
import cache  # noqa: E402
import albums  # noqa: E402
import crm_records as cr  # noqa: E402

REC = "6a4e50e9842a1194a7c681e1"
TV_PID = "6a268ea28f081f1de80eaedd"
FM_PID = "6a64d5798f08bf71b4203ba1"

# ─────────────────────────────────────────────── the fixture library
# 01 Raw / Phillip - Samurai (A1), Zeus (B1) · 02 Edit / Erol - Griffin
# (E1) / Video (E1V) · 03 Post (flat) · 04 Portfolio / Phillip - Samurai
# (P1) · 🗑 Deleted (BIN) / Duplicates (DUP)
TREE = [
    {"id": "raw", "name": "01 Raw", "children": [
        {"id": "A1", "name": "Phillip - Samurai", "children": []},
        {"id": "B1", "name": "Zeus", "children": []}]},
    {"id": "edit", "name": "02 Edit", "children": [
        {"id": "E1", "name": "Erol - Griffin", "children": [
            {"id": "E1V", "name": "Video", "children": []}]}]},
    {"id": "post", "name": "03 Post", "children": []},
    {"id": "port", "name": "04 Portfolio", "children": [
        {"id": "P1", "name": "Phillip - Samurai", "children": []}]},
    {"id": "BIN", "name": "🗑 Deleted", "children": [
        {"id": "DUP", "name": "Duplicates", "children": []}]},
]
ITEMS = {
    "I1": ("Phillip - Samurai • Raw • 1", ["A1"], ["Phillip", "Samurai", "tv"], "same"),
    "I2": ("Phillip - Samurai • Raw • 2", ["A1", "post"], ["Phillip", "Samurai"], "two"),
    "I3": ("Zeus • Raw • 1", ["B1"], ["Zeus", "x"], "same"),
    "I4": ("Zeus • Raw • 3", ["B1"], ["Zeus"], "four"),
    "I5": ("IMG_9", ["B1"], ["Zeus", "reel"], "five"),
    "I6": ("Erol - Griffin • Raw • 1", ["E1"], ["Erol", "Griffin"], "six"),
    "I7": ("Erol - Griffin • Raw • 2", ["E1V"], ["Erol", "Griffin"], "seven"),
    "I8": ("Phillip - Samurai • Portfolio • 1", ["P1"], ["Phillip", "Samurai"], "eight"),
}


def build_library(root):
    lib = os.path.join(root, "03 Content Library TV.library")
    os.makedirs(os.path.join(lib, "images"))
    with open(os.path.join(lib, "metadata.json"), "w") as f:
        json.dump({"folders": TREE}, f)
    for iid, (name, folders, tags, data) in ITEMS.items():
        d = os.path.join(lib, "images", f"{iid}.info")
        os.makedirs(d)
        meta = {"id": iid, "name": name, "ext": "jpg", "folders": folders,
                "tags": tags, "isDeleted": False}
        if iid == "I4":
            meta["btime"] = 1_700_000_000_000     # 2023-11-14 (ms)
        with open(os.path.join(d, "metadata.json"), "w") as f:
            json.dump(meta, f)
        with open(os.path.join(d, f"{name}.jpg"), "w") as f:
            f.write(data)
    d = os.path.join(lib, "images", "I9.info")
    os.makedirs(d)
    with open(os.path.join(d, "metadata.json"), "w") as f:
        json.dump({"id": "I9", "name": "gone", "ext": "jpg",
                   "folders": ["A1"], "tags": [], "isDeleted": True}, f)
    return lib


class FakeEagle:
    """The OPEN library as a mutable tree + item table; every mutating
    call is recorded. Pure helpers (item_base, find_folder_suffix, the
    disk readers, EagleError) fall through to the real module."""

    def __init__(self, lib_path):
        self.LIBS = {"tv": ("Content Library TV", lib_path),
                     "fm": ("Content Library FM", lib_path + "-fm"),
                     "studio": ("Content Library Studio", lib_path + "-st"),
                     "crm": ("CRM Library", lib_path + "-crm")}
        self.tree = copy.deepcopy(TREE)
        self.items = {iid: {"id": iid, "name": n, "folders": list(f),
                            "tags": list(t),
                            "filePath": os.path.join(lib_path, "images",
                                                     f"{iid}.info", f"{n}.jpg")}
                      for iid, (n, f, t, _d) in ITEMS.items()}
        self.lib = "Content Library TV"
        self.selected = []
        self.calls = []
        self._n = 0

    def __getattr__(self, name):
        return getattr(real_eagle, name)

    # state
    def ensure_running(self, launch=True, wait=20.0):
        pass

    def current_library(self):
        return self.lib

    def ensure_library(self, key, wait=25.0):
        self.calls.append(("ensure_library", key))
        self.lib = self.LIBS[key][0]

    def folder_tree(self):
        return self.tree

    def folder_node(self, fid, tree=None):
        return real_eagle.folder_node(fid, tree=self.tree)

    def pipeline_folders(self, create=True, tree=None):
        out = {}
        for suffix, canonical in real_eagle.PIPELINE:
            hit = real_eagle.find_folder_suffix(suffix, tree=self.tree)
            out[suffix] = hit["id"] if hit else (
                self.create_folder(canonical) if create else "")
        return out

    # folders
    def create_folder(self, name, parent=None):
        self._n += 1
        fid = f"NEW{self._n}"
        node = {"id": fid, "name": name, "children": []}
        if parent:
            real_eagle.folder_node(parent, tree=self.tree)["children"].append(node)
        else:
            self.tree.append(node)
        self.calls.append(("create_folder", name, parent))
        return fid

    def _detach(self, fid):
        def walk(nodes):
            for i, f in enumerate(nodes):
                if f["id"] == fid:
                    return nodes.pop(i)
                hit = walk(f.get("children") or [])
                if hit:
                    return hit
            return None
        return walk(self.tree)

    def move_folder(self, fid, new_parent):
        node = self._detach(fid)
        if new_parent:
            real_eagle.folder_node(new_parent, tree=self.tree)["children"].append(node)
        else:
            self.tree.append(node)
        self.calls.append(("move_folder", fid, new_parent))

    def rename_folder(self, fid, name):
        real_eagle.folder_node(fid, tree=self.tree)["name"] = name
        self.calls.append(("rename_folder", fid, name))

    # items
    def update_items(self, items):
        for it in items:
            cur = self.items[it["id"]]
            for k in ("name", "folders", "tags"):
                if k in it:
                    cur[k] = it[k]
        self.calls.append(("update_items", [dict(i) for i in items]))

    def add_item_tags(self, ids, tags):
        for i in ids:
            for t in tags:
                if t.lower() not in {x.lower() for x in self.items[i]["tags"]}:
                    self.items[i]["tags"].append(t)
        self.calls.append(("add_item_tags", list(ids), list(tags)))

    def remove_item_tags(self, ids, tags):
        low = {t.lower() for t in tags}
        for i in ids:
            self.items[i]["tags"] = [t for t in self.items[i]["tags"]
                                     if t.lower() not in low]
        self.calls.append(("remove_item_tags", list(ids), list(tags)))

    def get_items(self, ids, full=True):
        return [dict(self.items[i]) for i in ids if i in self.items]

    def selected_items(self):
        return [dict(self.items[i]) for i in self.selected]

    def items_in_folder(self, fid, page=400):
        return [dict(i) for i in self.items.values() if fid in i["folders"]]

    def list_item_names(self, fid):
        return [i["name"] for i in self.items_in_folder(fid)]

    def trash_items(self, ids):
        self.calls.append(("trash_items", list(ids)))


class Base(unittest.TestCase):
    """tmp dir per test: fixture library, ledger, stash, cache."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="albums_")
        self.lib = build_library(self.tmp)
        self.fake = FakeEagle(self.lib)
        self._eagle = albums.eagle
        albums.eagle = self.fake
        self._ledger, self._stash, self._pace = (
            albums.LEDGER_PATH, albums.STASH_PATH, albums.PACE)
        albums.LEDGER_PATH = os.path.join(self.tmp, "albums.jsonl")
        albums.STASH_PATH = os.path.join(self.tmp, "albsel.json")
        albums.PACE = 0
        self._cache_dir = cache.CACHE_DIR
        cache.CACHE_DIR = os.path.join(self.tmp, "cache")

    def tearDown(self):
        albums.eagle = self._eagle
        albums.LEDGER_PATH, albums.STASH_PATH, albums.PACE = (
            self._ledger, self._stash, self._pace)
        cache.CACHE_DIR = self._cache_dir
        shutil.rmtree(self.tmp, ignore_errors=True)


# ─────────────────────────────────────────────────── pure naming

class Naming(unittest.TestCase):
    def test_base_tags(self):
        self.assertEqual(albums.base_tags("Phillip - Samurai"),
                         ["Phillip", "Samurai"])
        self.assertEqual(albums.base_tags("Zeus"), ["Zeus"])
        self.assertEqual(albums.base_tags("Luka - Anubis - Sleeve"),
                         ["Luka", "Anubis - Sleeve"])
        self.assertEqual(albums.base_tags(""), [])

    def test_stage_label_and_tag(self):
        self.assertEqual(albums.stage_label("Raw"), "Raw")
        self.assertEqual(albums.stage_label("Edit"), "Raw")
        self.assertEqual(albums.stage_label("Portfolio"), "Portfolio")
        self.assertEqual(albums.stage_label(""), "Raw")
        self.assertEqual(albums.stage_tag("Raw"), "📸raw")
        self.assertEqual(albums.stage_tag("Edit"), "📸edit")
        self.assertEqual(albums.stage_tag("Portfolio"), "")
        self.assertEqual(albums.stage_tag(""), "")

    def test_rebase_name_shapes(self):
        self.assertEqual(albums.rebase_name("Zeus • Raw • 3", "Zeus", "Tfb - Zeus"),
                         "Tfb - Zeus • Raw • 3")
        self.assertEqual(albums.rebase_name("Zeus • Portfolio • 1", "", "Tfb - Zeus"),
                         "Tfb - Zeus • Portfolio • 1")
        self.assertEqual(albums.rebase_name("Zeus • S2 • 4", "Zeus", "A - B"),
                         "A - B • S2 • 4")
        # a base containing ' • ' survives (parsed from the right)
        self.assertEqual(albums.rebase_name("Luka - Anubis • Sleeve • Raw • 1",
                                            "Luka - Anubis • Sleeve", "L - A"),
                         "L - A • Raw • 1")
        # other base / unknown shapes come back unchanged
        self.assertEqual(albums.rebase_name("Other • Raw • 1", "Zeus", "X"),
                         "Other • Raw • 1")
        self.assertEqual(albums.rebase_name("IMG_3559", "Zeus", "X"), "IMG_3559")
        self.assertEqual(albums.rebase_name("", "Zeus", "X"), "")

    def test_rebased_items_continue_destination_numbering(self):
        items = [{"id": "b", "name": "Zeus • Raw • 3", "tags": ["Zeus"]},
                 {"id": "a", "name": "Zeus • Raw • 1", "tags": ["Zeus", "x"]},
                 {"id": "c", "name": "IMG_9", "tags": ["Zeus", "reel"]}]
        existing = ["Phillip - Samurai • Raw • 1", "Phillip - Samurai • Raw • 2",
                    "Phillip - Samurai • Portfolio • 9"]
        out = albums.rebased_items(items, "Phillip - Samurai", "Raw", existing)
        self.assertEqual([o["id"] for o in out], ["a", "b", "c"])   # shot order
        self.assertEqual([o["name"] for o in out],
                         ["Phillip - Samurai • Raw • 3",
                          "Phillip - Samurai • Raw • 4",
                          "Phillip - Samurai • Raw • 5"])
        self.assertEqual(out[1]["tags"], ["Phillip", "Samurai"])
        self.assertEqual(out[0]["tags"], ["x", "Phillip", "Samurai"])
        # hand-named: the source's tag survives unless old_base names it
        self.assertEqual(out[2]["tags"], ["Zeus", "reel", "Phillip", "Samurai"])
        out2 = albums.rebased_items(items, "Phillip - Samurai", "Raw", existing,
                                    old_base="Zeus")
        self.assertEqual(out2[2]["tags"], ["reel", "Phillip", "Samurai"])
        self.assertEqual(existing, ["Phillip - Samurai • Raw • 1",
                                    "Phillip - Samurai • Raw • 2",
                                    "Phillip - Samurai • Portfolio • 9"])

    def test_rebased_items_keeps_a_conforming_name(self):
        items = [{"id": "a", "name": "Phillip - Samurai • Raw • 7",
                  "tags": ["Phillip", "Samurai"]},
                 {"id": "b", "name": "Phillip - Samurai • Raw • 1", "tags": []}]
        out = albums.rebased_items(items, "Phillip - Samurai", "Raw",
                                   ["Phillip - Samurai • Raw • 1"])
        by = {o["id"]: o["name"] for o in out}
        self.assertEqual(by["a"], "Phillip - Samurai • Raw • 7")   # kept
        # b (index 1) is renumbered first in shot order: 1 is taken → 2
        self.assertEqual(by["b"], "Phillip - Samurai • Raw • 2")
        # label change always renames
        out = albums.rebased_items(items[:1], "Phillip - Samurai", "Portfolio", [])
        self.assertEqual(out[0]["name"], "Phillip - Samurai • Portfolio • 1")

    def test_norm(self):
        self.assertEqual(albums._norm("🗑 Deleted"), "deleted")
        self.assertEqual(albums._norm("04 Portfolio"), "04 portfolio")
        self.assertTrue(albums._is_portfolio_name("04 Portfolio"))
        self.assertTrue(albums._is_portfolio_name("Portfolio"))
        self.assertFalse(albums._is_portfolio_name("Tattoo Portfolio"))


# ──────────────────────────────────────────── stash + ledger (tmp)

class StashLedger(Base):
    def test_stash_round_trip(self):
        self.assertIsNone(albums.unstash())
        sel = {"lib": "tv", "items": [{"id": "I1", "name": "n", "folders": ["A1"],
                                       "tags": [], "annotation": "", "ext": "jpg"}],
               "sources": {"A1": ["I1"]}, "source_names": {"A1": "Phillip - Samurai"}}
        albums.stash(sel)
        got = albums.unstash()
        self.assertEqual(got["items"], sel["items"])
        self.assertEqual(got["sources"], sel["sources"])
        self.assertEqual(got["source_names"], sel["source_names"])
        self.assertTrue(got.get("when"))
        self.assertIsNotNone(albums.unstash())      # unstash does not clear
        albums.clear_stash()
        self.assertIsNone(albums.unstash())
        albums.stash({"lib": "tv", "items": []})
        self.assertIsNone(albums.unstash())          # empty = nothing parked

    def test_ledger_append_last_pop(self):
        led = albums.Ledger()
        self.assertIsNone(led.last())
        self.assertIsNone(led.pop_last())
        self.assertEqual(led.all(), [])
        led.append({"verb": "move", "lib": "tv", "note": "one"})
        led.append({"verb": "new", "lib": "fm"})
        self.assertEqual(led.last()["verb"], "new")
        self.assertEqual(led.last()["items"], [])       # defaults filled
        self.assertTrue(led.last()["when"])
        op = led.pop_last()
        self.assertEqual(op["verb"], "new")
        self.assertEqual(led.last()["verb"], "move")
        self.assertEqual(len(led.all()), 1)
        # undo records are the trail: skipped by last()/pop_last()
        led.append({"verb": "undo", "lib": "tv", "note": "undid new"})
        self.assertEqual(led.last()["verb"], "move")
        self.assertEqual(led.pop_last()["verb"], "move")
        self.assertIsNone(led.last())
        self.assertEqual([o["verb"] for o in led.all()], ["undo"])
        self.assertEqual(albums.new_op("move", "tv", "x")["ticktick"], [])

    def test_ledger_skips_garbage_lines(self):
        os.makedirs(os.path.dirname(albums.LEDGER_PATH), exist_ok=True)
        with open(albums.LEDGER_PATH, "w") as f:
            f.write('{"verb": "move", "lib": "tv"}\nnot json\n\n')
        self.assertEqual(len(albums.Ledger().all()), 1)


# ─────────────────────────────────────────── disk readers (fixture)

class DiskReaders(Base):
    def test_library_albums(self):
        rows = albums.library_albums("tv")
        paths = [r["path"] for r in rows]
        self.assertEqual(paths, ["01 Raw/Phillip - Samurai", "01 Raw/Zeus",
                                 "02 Edit/Erol - Griffin",
                                 "02 Edit/Erol - Griffin/Video",
                                 "04 Portfolio/Phillip - Samurai"])
        by = {r["fid"]: r for r in rows}
        self.assertEqual(by["A1"]["n"], 2)             # deleted I9 skipped
        self.assertEqual(by["B1"]["n"], 3)
        self.assertEqual(by["E1"]["n"], 2)             # subtree count
        self.assertEqual(by["E1V"]["n"], 1)
        self.assertEqual(by["E1V"]["depth"], 2)
        self.assertEqual(by["E1V"]["parent"], "E1")
        self.assertEqual(by["E1"]["parent"], "edit")
        self.assertEqual({r["stage"] for r in rows if r["fid"].startswith("P")},
                         {"Portfolio"})
        self.assertNotIn("BIN", by)
        self.assertNotIn("post", by)
        with self.assertRaises(albums.AlbumError):
            albums.library_albums("nope")

    def test_album_stage(self):
        self.assertEqual(albums.album_stage("tv", "A1"), "Raw")
        self.assertEqual(albums.album_stage("tv", "E1V"), "Edit")
        self.assertEqual(albums.album_stage("tv", "P1"), "Portfolio")
        self.assertEqual(albums.album_stage("tv", "raw"), "")     # a root
        self.assertEqual(albums.album_stage("tv", "BIN"), "")
        self.assertEqual(albums.album_stage("tv", "ZZ"), "")

    def test_items_of_album(self):
        items = albums.items_of_album("tv", "E1")
        by = {i["id"]: i for i in items}
        self.assertEqual(set(by), {"I6", "I7"})
        self.assertEqual(by["I6"]["child"], "")
        self.assertEqual(by["I7"]["child"], "Video")
        self.assertEqual(by["I7"]["child_fid"], "E1V")
        self.assertTrue(os.path.exists(by["I6"]["path"]))
        self.assertEqual({i["id"] for i in albums.items_of_album("tv", "A1")},
                         {"I1", "I2"})
        with self.assertRaises(albums.AlbumError):
            albums.items_of_album("tv", "ZZ")

    def test_row_for_folder(self):
        cache.set("all_tasks", [
            {"id": "t1", "projectId": TV_PID, "status": 0,
             "title": "[Phillip - Samurai](eagle://folder/A1)"},
            {"id": "t1fm", "projectId": FM_PID, "status": 0,
             "title": "[Phillip - Samurai](eagle://folder/A1)"},
            {"id": "t2", "projectId": TV_PID, "status": 2,
             "title": "[Zeus](eagle://folder/B1)"},
            {"id": "t3", "projectId": TV_PID, "status": 0,
             "title": "[Old](http://localhost:41595/folder?id=E1)"},
            {"id": "t4", "projectId": "elsewhere", "status": 0,
             "title": "[x](eagle://folder/P1)"},
            {"id": "t5", "projectId": TV_PID, "status": 0,
             "title": "[x](eagle://folder/A1X)"}])
        cache.set("all_notes", [
            {"id": "n1", "_projectId": TV_PID, "status": 0,
             "title": "[Note row](eagle://folder/E1V)"}])
        self.assertEqual(albums.row_for_folder("tv", "A1")["id"], "t1")
        self.assertEqual(albums.row_for_folder("fm", "A1")["id"], "t1fm")
        self.assertEqual(albums.row_for_folder("studio", "A1")["id"], "t1")
        self.assertIsNone(albums.row_for_folder("tv", "B1"))      # completed
        self.assertEqual(albums.row_for_folder("tv", "E1")["id"], "t3")
        self.assertIsNone(albums.row_for_folder("tv", "P1"))      # not a content list
        self.assertEqual(albums.row_for_folder("tv", "E1V")["id"], "n1")
        self.assertIsNone(albums.row_for_folder("tv", ""))
        self.assertIsNone(albums.row_for_folder("tv", "A"))        # no prefix hit

    def test_capture_days(self):
        items = albums.items_of_album("tv", "B1")     # I3 I4 I5
        p = {i["id"]: i["path"] for i in items}
        seen = []

        def fake_mdls(paths):
            seen.append(list(paths))
            return {p["I3"]: 1_709_251_200,        # 2024-03-01
                    p["I5"]: 1_709_337_600}        # 2024-03-02
        self._mdls, self._bulk = albums._mdls, albums._bulk_dates
        albums._mdls = fake_mdls
        albums._bulk_dates = lambda: set()
        try:
            days = albums.capture_days("tv", items)
            # I4: no mdls → Eagle btime fallback (2023-11-14)
            self.assertEqual(days, ["2023-11-14", "2024-03-01", "2024-03-02"])
            self.assertEqual(len(seen), 1)
            albums._bulk_dates = lambda: {"2024-03-02"}
            self.assertEqual(albums.capture_days("tv", items),
                             ["2023-11-14", "2024-03-01"])
            self.assertEqual(albums.capture_days("tv", []), [])
            # ids without a path are looked up live (the fake's filePath)
            self.assertEqual(albums.capture_days("tv", [{"id": "I3"}]),
                             ["2024-03-01"])
            albums._mdls = lambda paths: {}
            i3 = [i for i in items if i["id"] == "I3"]
            self.assertEqual(albums.capture_days("tv", i3), [])   # no date at all
        finally:
            albums._mdls, albums._bulk_dates = self._mdls, self._bulk

    def test_file_md5_and_hash_items(self):
        items = albums.items_of_album("tv", "A1") + albums.items_of_album("tv", "B1")
        albums.hash_items(items)
        by = {i["id"]: i["hash"] for i in items}
        self.assertEqual(by["I1"], by["I3"])            # byte-identical twins
        self.assertNotEqual(by["I1"], by["I2"])
        self.assertEqual(albums.file_md5("/nope/none.jpg"), "")


# ─────────────────────────────────────────────────── plan_merge

class PlanMerge(unittest.TestCase):
    A = [{"id": "a1", "name": "Phillip - Samurai • Raw • 1", "tags": ["Phillip", "Samurai"],
          "child": "", "hash": "h1"},
         {"id": "a2", "name": "Phillip - Samurai • Raw • 2", "tags": [], "child": "",
          "hash": "h2"},
         {"id": "ap", "name": "Phillip - Samurai • Portfolio • 1", "tags": [],
          "child": "04 Portfolio", "hash": "hp"},
         {"id": "av", "name": "Phillip - Samurai • Raw • 1", "tags": [],
          "child": "Video", "hash": "hv"}]
    B = [{"id": "b3", "name": "Zeus • Raw • 3", "tags": ["Zeus"], "child": "", "hash": "h9"},
         {"id": "b1", "name": "Zeus • Raw • 1", "tags": ["Zeus", "x"], "child": "",
          "hash": "h1"},                                   # twin of a1
         {"id": "bp", "name": "Zeus • Portfolio • 4", "tags": ["Zeus"],
          "child": "Portfolio", "hash": "hq"},
         {"id": "bv", "name": "Zeus • Raw • 2", "tags": [], "child": "video", "hash": "hw"},
         {"id": "bn", "name": "Zeus • Raw • 5", "tags": [], "child": "Sketches", "hash": "hs"},
         {"id": "bd", "name": "IMG_1", "tags": [], "child": "", "hash": "h9"}]  # twin inside B

    def test_plan(self):
        plan = albums.plan_merge(self.A, self.B, "Phillip - Samurai")
        dupes = {d["id"]: d["twin"] for d in plan["dupes"]}
        self.assertEqual(dupes, {"b1": "a1", "bd": "b3"})
        moves = {m["id"]: m for m in plan["moves"]}
        self.assertEqual(set(moves), {"b3", "bp", "bv", "bn"})
        # root: numbering continues A's root (1, 2 taken → 3)
        self.assertEqual(moves["b3"]["name"], "Phillip - Samurai • Raw • 3")
        self.assertEqual(moves["b3"]["child"], "")
        self.assertEqual(moves["b3"]["tags"], ["Phillip", "Samurai"])
        # Portfolio child pairs with A's Portfolio child, Portfolio label
        self.assertEqual(moves["bp"]["child"], "04 Portfolio")
        self.assertEqual(moves["bp"]["label"], "Portfolio")
        self.assertEqual(moves["bp"]["name"], "Phillip - Samurai • Portfolio • 2")
        self.assertFalse(moves["bp"]["create"])
        # children pair by loose name; A's spelling wins
        self.assertEqual(moves["bv"]["child"], "Video")
        self.assertEqual(moves["bv"]["name"], "Phillip - Samurai • Raw • 2")
        self.assertFalse(moves["bv"]["create"])
        # an unknown child is created
        self.assertEqual(moves["bn"]["child"], "Sketches")
        self.assertTrue(moves["bn"]["create"])
        self.assertEqual(moves["bn"]["name"], "Phillip - Samurai • Raw • 1")
        self.assertEqual({r["id"]: r["to"] for r in plan["renames"]},
                         {m: moves[m]["name"] for m in moves})
        self.assertEqual(moves["b3"]["prior_name"], "Zeus • Raw • 3")
        self.assertEqual([m["id"] for m in plan["moves"]],
                         ["bv", "b3", "bp", "bn"])          # shot order

    def test_plan_no_hashes_no_dupes_and_label(self):
        a = [{"id": "a", "name": "X • Portfolio • 1", "tags": [], "child": ""}]
        b = [{"id": "b", "name": "Y • Portfolio • 1", "tags": ["Y"], "child": ""}]
        plan = albums.plan_merge(a, b, "X", label="Portfolio")
        self.assertEqual(plan["dupes"], [])
        self.assertEqual(plan["moves"][0]["name"], "X • Portfolio • 2")
        self.assertEqual(plan["moves"][0]["tags"], ["X"])
        self.assertEqual(albums.plan_merge([], [], "X"),
                         {"moves": [], "dupes": [], "renames": []})


# ───────────────────────────────────── live movers over the fake eagle

class LiveEagle(Base):
    def test_open_lib_and_selection(self):
        self.assertEqual(albums.open_lib(), "tv")
        self.fake.lib = "CRM Library"
        self.assertEqual(albums.open_lib(), "")
        with self.assertRaises(albums.AlbumError) as cm:
            albums.selection()
        self.assertIn("TV/FM/Studio", str(cm.exception))
        self.fake.lib = "Content Library TV"
        with self.assertRaises(albums.AlbumError) as cm:
            albums.selection("fm")
        self.assertIn("FM library", str(cm.exception))
        with self.assertRaises(albums.AlbumError) as cm:
            albums.selection()
        self.assertEqual(str(cm.exception), "Nothing selected in Eagle")
        self.fake.selected = ["I1", "I2"]
        sel = albums.selection()
        self.assertEqual(sel["lib"], "tv")
        self.assertEqual([i["id"] for i in sel["items"]], ["I1", "I2"])
        self.assertEqual(sel["sources"], {"A1": ["I1", "I2"], "post": ["I2"]})
        self.assertEqual(sel["source_names"],
                         {"A1": "Phillip - Samurai", "post": "03 Post"})
        self.assertTrue(sel["items"][0]["path"].endswith(".jpg"))
        self.assertEqual(sel["items"][0]["tags"], ["Phillip", "Samurai", "tv"])
        self.assertEqual(albums.selection("tv")["lib"], "tv")

    def test_move_items_rebases_and_ledgers(self):
        op = albums.new_op("move", "tv")
        items = albums.items_of_album("tv", "B1")        # I3 I4 I5
        res = albums.move_items("tv", items, "A1", "Phillip - Samurai", "Raw",
                                op, old_base="Zeus")
        self.assertEqual(res, {"moved": 3, "renamed": 3})
        self.assertEqual(self.fake.calls[0], ("ensure_library", "tv"))
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Phillip - Samurai • Raw • 3")
        self.assertEqual(it["I4"]["name"], "Phillip - Samurai • Raw • 4")
        self.assertEqual(it["I5"]["name"], "Phillip - Samurai • Raw • 5")
        self.assertEqual(it["I3"]["folders"], ["A1"])
        self.assertEqual(it["I3"]["tags"], ["x", "Phillip", "Samurai"])
        self.assertEqual(it["I5"]["tags"], ["reel", "Phillip", "Samurai"])
        self.assertEqual(len(op["items"]), 3)
        led = {e["id"]: e for e in op["items"]}
        self.assertEqual(led["I3"]["prior_name"], "Zeus • Raw • 1")
        self.assertEqual(led["I3"]["prior_folders"], ["B1"])
        self.assertEqual(led["I3"]["prior_tags"], ["Zeus", "x"])
        self.assertEqual(led["I3"]["folders"], ["A1"])
        ups = [c for c in self.fake.calls if c[0] == "update_items"]
        self.assertEqual(len(ups), 1)                     # ONE batch
        self.assertEqual(albums.move_items("tv", [], "A1", "x", "Raw", op),
                         {"moved": 0, "renamed": 0})

    def test_move_items_keeps_the_post_shelf(self):
        op = albums.new_op("move", "tv")
        items = albums.items_of_album("tv", "A1")        # I2 also on 03 Post
        albums.move_items("tv", items, "P1", "Phillip - Samurai", "Portfolio", op)
        self.assertEqual(self.fake.items["I2"]["folders"], ["P1", "post"])
        self.assertEqual(self.fake.items["I1"]["folders"], ["P1"])
        self.assertEqual(self.fake.items["I1"]["name"],
                         "Phillip - Samurai • Portfolio • 2")   # continues P1's

    def test_new_album_creates_or_adopts(self):
        op = albums.new_op("new", "tv")
        fid = albums.new_album("tv", "Raw", "New Guy - Rose", op)
        self.assertEqual(fid, "NEW1")
        self.assertIn(("create_folder", "New Guy - Rose", "raw"), self.fake.calls)
        self.assertEqual(op["folders"][-1]["created"], True)
        self.assertEqual(op["folders"][-1]["parent"], "raw")
        # loose same-name under the stage: adopted, never twinned
        self.assertEqual(albums.new_album("tv", "Raw", "zeus", op), "B1")
        self.assertIn("adopted existing Zeus", op["note"])
        self.assertFalse(op["folders"][-1]["created"])
        # Edit albums may be nested: adoption searches the whole stage
        self.assertEqual(albums.new_album("tv", "Edit", "VIDEO", op), "E1V")
        # Portfolio child of A1 exists under 04 Portfolio; a Raw twin does not
        self.assertEqual(albums.new_album("tv", "Portfolio", "Phillip - Samurai", op), "P1")
        with self.assertRaises(albums.AlbumError):
            albums.new_album("tv", "Post", "x", op)

    def test_bin_dup_and_husk(self):
        self.assertEqual(albums.bin_folder("tv"), "BIN")
        self.assertEqual(albums.dup_folder("tv"), "DUP")
        # missing bin is minted (create=False reports '')
        self.fake.tree = [n for n in self.fake.tree if n["id"] != "BIN"]
        self.assertEqual(albums.bin_folder("tv", create=False), "")
        self.assertEqual(albums.bin_folder("tv"), "NEW1")
        self.assertEqual(albums.dup_folder("tv"), "NEW2")
        self.assertIn(("create_folder", "Duplicates", "NEW1"), self.fake.calls)
        op = albums.new_op("move", "tv")
        self.assertFalse(albums.husk_to_bin("tv", "B1", op))     # not empty
        self.assertFalse(albums.husk_to_bin("tv", "ZZ", op))     # no such
        self.assertFalse(albums.husk_to_bin("tv", "E1", op))     # child holds I7
        for i in ("I3", "I4", "I5"):
            self.fake.items[i]["folders"] = ["A1"]
        self.assertTrue(albums.husk_to_bin("tv", "B1", op))
        self.assertIn(("move_folder", "B1", "NEW1"), self.fake.calls)
        self.assertEqual(op["folders"][-1], {
            "id": "B1", "prior_name": "Zeus", "prior_parent": "raw",
            "name": "Zeus", "parent": "NEW1", "created": False})
        self.assertTrue(albums.husk_to_bin("tv", "B1", op))      # already there
        self.assertEqual(len(op["folders"]), 1)

    def test_undo_last_reverses_eagle_and_lists_ticktick(self):
        self.assertEqual(albums.undo_last(), "↩️ Nothing to undo")
        op = albums.new_op("new", "tv")
        fid = albums.new_album("tv", "Raw", "Tfb - Zeus", op)
        items = albums.items_of_album("tv", "B1")
        albums.move_items("tv", items, fid, "Tfb - Zeus", "Raw", op, old_base="Zeus")
        self.assertTrue(albums.husk_to_bin("tv", "B1", op))
        op["ticktick"] += [{"kind": "row", "id": "6a01", "pid": TV_PID,
                            "action": "minted"},
                           {"kind": "row", "id": "6a02", "pid": TV_PID,
                            "action": "trashed"},
                           {"kind": "row", "id": "6a03", "pid": TV_PID,
                            "action": "retitled", "prior": {"title": "[Zeus](x)"}}]
        albums.Ledger().append(op)
        self.assertEqual(self.fake.items["I3"]["name"], "Tfb - Zeus • Raw • 1")
        # 'Zeus' is the new tattoo tag too, so it stays; 'Tfb' joins
        self.assertEqual(self.fake.items["I3"]["tags"], ["Zeus", "x", "Tfb"])
        self.assertEqual(self.fake.items["I3"]["folders"], [fid])
        self.fake.calls = []
        toast = albums.undo_last()
        it = self.fake.items
        self.assertEqual(it["I3"]["name"], "Zeus • Raw • 1")
        self.assertEqual(it["I3"]["folders"], ["B1"])
        self.assertEqual(sorted(it["I3"]["tags"]), ["Zeus", "x"])
        self.assertEqual(it["I5"]["name"], "IMG_9")
        self.assertEqual(sorted(it["I5"]["tags"]), ["Zeus", "reel"])
        # husk back under 01 Raw, the created album parked in the bin
        raw = real_eagle.folder_node("raw", tree=self.fake.tree)
        self.assertIn("B1", [c["id"] for c in raw["children"]])
        bin_ = real_eagle.folder_node("BIN", tree=self.fake.tree)
        self.assertIn(fid, [c["id"] for c in bin_["children"]])
        self.assertEqual(self.fake.calls[0], ("ensure_library", "tv"))
        self.assertIn("Undid new", toast)
        self.assertIn("3 shots back", toast)
        self.assertIn("Trash row 6a01", toast)
        self.assertIn("restore row 6a02 from Trash", toast)
        self.assertIn("6a03 was retitled", toast)
        led = albums.Ledger()
        self.assertIsNone(led.last())
        self.assertEqual([o["verb"] for o in led.all()], ["undo"])
        self.assertEqual(albums.undo_last(), "↩️ Nothing to undo")

    def test_undo_rename_and_move_folders(self):
        op = albums.new_op("rename", "tv", "ripple")
        self.fake.rename_folder("B1", "Tfb - Zeus")
        self.fake.move_folder("B1", "edit")
        op["folders"] += [{"id": "B1", "prior_name": "Zeus", "prior_parent": "raw",
                           "name": "Tfb - Zeus", "parent": "edit", "created": False}]
        albums.Ledger().append(op)
        self.fake.calls = []
        toast = albums.undo_last()
        node, parent = albums._find_node(self.fake.tree, "B1")
        self.assertEqual((node["name"], parent), ("Zeus", "raw"))
        self.assertEqual([c[0] for c in self.fake.calls],
                         ["ensure_library", "rename_folder", "move_folder"])
        self.assertIn("2 folder(s) back", toast)
        self.assertIn("0 shots back", toast)

    def test_undo_keeps_a_created_album_that_is_not_empty(self):
        op = albums.new_op("new", "tv")
        fid = albums.new_album("tv", "Raw", "Keep - Me", op)
        self.fake.items["I1"]["folders"] = [fid]     # someone filed into it
        albums.Ledger().append(op)
        toast = albums.undo_last()
        self.assertIn("Keep - Me kept (not empty)", toast)
        node, parent = albums._find_node(self.fake.tree, fid)
        self.assertEqual(parent, "raw")

    def test_eagle_errors_become_album_errors(self):
        def boom(*a, **k):
            raise real_eagle.EagleError("plugin off")
        self.fake.update_items = boom
        op = albums.new_op("move", "tv")
        with self.assertRaises(albums.AlbumError) as cm:
            albums.move_items("tv", albums.items_of_album("tv", "B1"), "A1",
                              "Phillip - Samurai", "Raw", op)
        self.assertEqual(str(cm.exception), "plugin off")
        self.fake.ensure_library = boom
        with self.assertRaises(albums.AlbumError):
            albums.bin_folder("tv")


# ───────────────────────────────────── crm_records: merge (pure)

CUST_A = "[👤 Phillip](https://ticktick.com/webapp/#p/%s/tasks/ca)" % REC
CUST_B = "[👤 Zeus](https://ticktick.com/webapp/#p/%s/tasks/cb)" % REC
NOTE_A = (f"👤 {CUST_A} · Started 2026-03-01 · Finished -\n"
          "Paid: 300€ · 1 session\n"
          "🦅 [Eagle folder](eagle://folder/A1) · TV\n"
          "🎬 TV\n\n"
          "## Sessions\n\n"
          "### 2026-03-01 · S1 · 4h · 300€\nOutline.\n\n"
          "## Notes\n\n- 2026-03-01 10:00 - a note on A\n")
NOTE_B = (f"👤 {CUST_B} · Started 2026-02-10 · Finished 2026-04-05\n"
          "Paid: 300€ · 2 sessions\n"
          "Quoted: 800€\n"
          "🦅 [Eagle folder](eagle://folder/B1) · TV\n"
          "🎬 FM\n\n"
          "## Sessions\n\n"
          "### 2026-02-10 · S1 · 2h · 200€\nFirst.\n![image](att1/one.jpg)\n\n"
          "### 2026-04-05 · S2 · 3h · 100€\nSecond.\n\n"
          "## Design\n\n![image](att2/sketch.jpg)\n\n"
          "## Notes\n\n- 2026-02-10 09:00 - a note on B\n")


class MergeContent(unittest.TestCase):
    def test_merge_shape(self):
        m = cr.merge_logbook_content(NOTE_A, NOTE_B, stamp="- 2026-09-11 - merged B")
        head = m.partition("\n## ")[0]
        self.assertIn("Started 2026-02-10", head)          # the earlier
        self.assertIn("Finished -", head)                  # A active → active
        self.assertIn("Quoted: 800€", head)                # A had none → B's
        self.assertIn("eagle://folder/A1", head)           # A's 🦅 kept
        self.assertIn("🎬 TV", head)
        self.assertNotIn("🎬 FM", m)
        self.assertIn(CUST_A, head)                        # A's customer
        self.assertNotIn("Zeus](", head)
        self.assertEqual(cr.paid_summary(m), "600€ of 800€ · 200€ open · 3 sessions")
        self.assertIn("Paid: 600€ of 800€ · 200€ open · 3 sessions", head)
        entries = [e[0] for e in cr._entries(m)]
        self.assertEqual(entries, ["2026-02-10", "2026-03-01", "2026-04-05"])
        # refs and text travel with their block; other sections carried
        self.assertLess(m.index("First.\n![image](att1/one.jpg)"), m.index("### 2026-03-01"))
        self.assertIn("## Design\n\n![image](att2/sketch.jpg)\n\n## Notes", m)
        notes = m.partition("## Notes")[2]
        self.assertEqual([l for l in notes.split("\n") if l.strip()],
                         ["- 2026-03-01 10:00 - a note on A",
                          "- 2026-02-10 09:00 - a note on B",
                          "- 2026-09-11 - merged B"])
        self.assertTrue(m.endswith("\n"))
        self.assertNotIn("\n\n\n", m)
        # idempotent shape: re-parsing sections gives the same order
        self.assertEqual([h for h, _b in cr._split_sections(m)[1]],
                         ["## Sessions", "## Design", "## Notes"])

    def test_dates_and_quote_rules(self):
        a = NOTE_A.replace("Finished -", "Finished 2026-05-01")
        m = cr.merge_logbook_content(a, NOTE_B)
        self.assertIn("Finished 2026-05-01", m)             # both finished → max
        m = cr.merge_logbook_content(NOTE_B, a)
        self.assertIn("Finished 2026-05-01", m)
        self.assertIn("Started 2026-02-10", m)
        self.assertIn("Quoted: 800€", m)                    # A's own kept
        a_q = NOTE_A.replace("Paid: 300€ · 1 session\n", "Paid: 300€ · 1 session\nQuoted: 500€\n")
        m = cr.merge_logbook_content(a_q, NOTE_B)
        self.assertIn("Quoted: 500€", m)
        self.assertNotIn("Quoted: 800€", m)
        # unknown Started on A: B's date wins; both unknown stays '-'
        a_u = NOTE_A.replace("Started 2026-03-01", "Started -")
        self.assertIn("Started 2026-02-10", cr.merge_logbook_content(a_u, NOTE_B))
        b_u = NOTE_B.replace("Started 2026-02-10", "Started -")
        self.assertIn("Started -", cr.merge_logbook_content(a_u, b_u))
        # tie on a day: A's entry first, markers untouched
        b_same = NOTE_B.replace("2026-02-10 · S1", "2026-03-01 · S1")
        m = cr.merge_logbook_content(NOTE_A, b_same)
        self.assertLess(m.index("Outline."), m.index("First."))
        self.assertEqual([e[1] for e in cr._entries(m)], ["S1", "S1", "S2"])

    def test_preamble_and_missing_sections(self):
        a = ("👤 x · Started 2026-01-01 · Finished -\nPaid: - · 0 sessions\n\n"
             "## Sessions\n![image](att0/hero.jpg)\n\n## Notes\n")
        b = "👤 y · Started - · Finished -\nPaid: - · 0 sessions\n"
        m = cr.merge_logbook_content(a, b)
        self.assertIn("## Sessions\n\n![image](att0/hero.jpg)\n\n## Notes", m)
        self.assertIn("Paid: - · 0 sessions", m)
        m = cr.merge_logbook_content(b, a)                 # A without sections
        self.assertIn("## Sessions\n\n![image](att0/hero.jpg)", m)
        self.assertTrue(m.rstrip().endswith("## Notes"))
        self.assertIn("Started 2026-01-01", m)


# ──────────────────────────────── crm_records: merge (live, fakes)

class FakeAPI:
    def __init__(self, tasks):
        self.tasks = {t["id"]: dict(t) for t in tasks}
        self.updates, self.deleted, self.moves = [], [], []

    def get_task(self, pid, tid):
        t = self.tasks.get(tid)
        if not t or t.get("projectId") != pid:
            raise KeyError("404")
        return dict(t)

    def update_task(self, tid, pid, current=None, **fields):
        self.updates.append((tid, pid, dict(fields)))
        self.tasks[tid].update({k: v for k, v in fields.items() if k != "projectId"})
        return dict(self.tasks[tid])

    def delete_task(self, pid, tid):
        self.deleted.append((pid, tid))
        self.tasks.pop(tid, None)
        return True

    def move_task(self, tid, a, b):
        self.moves.append((tid, a, b))


def _cust(tid, title, bullets):
    return {"id": tid, "projectId": REC, "title": title, "kind": "NOTE",
            "tags": ["🗂️customer"],
            "content": "📞 - · ✉️ - · 🎂 - · 📸 -\n\n## Fun facts\n\n## Tattoos\n"
                       + "".join(b + "\n" for b in bullets) + "\n## Notes\n"}


class MergeLive(Base):
    def setUp(self):
        super().setUp()
        self._api = cr._api
        a_bul = f"- [🎨 Phillip • Samurai](https://ticktick.com/webapp/#p/{REC}/tasks/A) - started 2026-03-01 · finished - · 300€ · 1 session"
        b_bul = f"- [🎨 Zeus • Zeus](https://ticktick.com/webapp/#p/{REC}/tasks/B) - started 2026-02-10 · finished 2026-04-05 · 300€ · 2 sessions"
        self.api = FakeAPI([
            {"id": "A", "projectId": REC, "title": "🎨 Phillip • Samurai",
             "tags": ["🗂️logbook"], "content": NOTE_A, "kind": "NOTE"},
            {"id": "B", "projectId": REC, "title": "🎨 Zeus • Zeus",
             "tags": ["🗂️logbook"], "content": NOTE_B, "kind": "NOTE"},
            _cust("ca", "👤 Phillip", [a_bul]),
            _cust("cb", "👤 Zeus", [b_bul])])
        cr._api = lambda: self.api
        self._reopen = cr.reopen_logbook
        self.reopened = []
        cr.reopen_logbook = lambda pid, tid: self.reopened.append((pid, tid))

    def tearDown(self):
        cr._api = self._api
        cr.reopen_logbook = self._reopen
        super().tearDown()

    def test_merge_keeps_a_customer(self):
        res = cr.merge_logbooks("A", "B")
        self.assertEqual(res["pid"], REC)
        self.assertEqual(res["customer"], "ca")
        self.assertFalse(res["reopened"])
        # A updated under ITS list with projectId explicit (trap 16)
        up = next(u for u in self.api.updates if u[0] == "A")
        self.assertEqual(up[1], REC)
        self.assertEqual(up[2]["projectId"], REC)
        self.assertIn("### 2026-02-10 · S1", up[2]["content"])
        self.assertIn("merged 🎨 Zeus • Zeus into this logbook", up[2]["content"])
        self.assertEqual(self.api.tasks["A"]["content"], res["content"])
        # B → Trash, its bullet gone, A's bullet rebuilt from the merge
        self.assertEqual(self.api.deleted, [(REC, "B")])
        self.assertNotIn("/tasks/B)", self.api.tasks["cb"]["content"])
        ca = self.api.tasks["ca"]["content"]
        self.assertEqual(ca.count("/tasks/A)"), 1)
        self.assertIn("started 2026-02-10 · finished - · 600€ of 800€", ca)
        self.assertNotIn("/tasks/A)", self.api.tasks["cb"]["content"])
        self.assertEqual(self.reopened, [])
        with self.assertRaises(ValueError):
            cr.merge_logbooks("A", "A")

    def test_merge_b_customer_takes_the_tattoo(self):
        res = cr.merge_logbooks("A", "B", keep_customer="b")
        self.assertEqual(res["customer"], "cb")
        head = res["content"].partition("\n## ")[0]
        self.assertIn(CUST_B, head)
        self.assertNotIn("/tasks/ca)", head)
        # A's old customer lost the bullet, B's customer carries A now
        self.assertNotIn("/tasks/A)", self.api.tasks["ca"]["content"])
        cb = self.api.tasks["cb"]["content"]
        self.assertIn("/tasks/A)", cb)
        self.assertNotIn("/tasks/B)", cb)
        # the same by customer tid; 'a' / A's tid keep A's
        self.api.tasks["A"]["content"] = NOTE_A
        self.api.tasks["B"] = {"id": "B", "projectId": REC, "title": "🎨 Zeus • Zeus",
                               "tags": ["🗂️logbook"], "content": NOTE_B, "kind": "NOTE"}
        self.assertEqual(cr.merge_logbooks("A", "B", keep_customer="ca")["customer"], "ca")

    def test_archived_a_absorbing_an_active_b_reopens(self):
        self.api.tasks["A"]["tags"] = ["🗂️archive"]
        self.api.tasks["A"]["title"] = "🏛️ Phillip • Samurai"
        res = cr.merge_logbooks("A", "B")
        self.assertTrue(res["reopened"])
        self.assertEqual(self.reopened, [(REC, "A")])
        # both archived: nothing to reopen
        self.api.tasks["A"]["content"] = NOTE_A
        self.api.tasks["B"] = {"id": "B", "projectId": REC, "title": "🏛️ Zeus • Zeus",
                               "tags": ["🗂️archive"], "content": NOTE_B, "kind": "NOTE"}
        self.assertFalse(cr.merge_logbooks("A", "B")["reopened"])

    def test_merge_finds_b_in_the_archive_list(self):
        self.api.tasks["B"]["projectId"] = "ARCHIVE"
        res = cr.merge_logbooks("A", "B")
        self.assertEqual(self.api.deleted, [("ARCHIVE", "B")])
        self.assertIn("### 2026-04-05 · S2", res["content"])


if __name__ == "__main__":
    unittest.main()
