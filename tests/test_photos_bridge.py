#!/usr/bin/env python3
"""Unit suite for src/photos_bridge.py - the direct-disk snapshot road
and the export road's patience (2026-09-27: -1712 on a batch export).
Run: python3 tests/test_photos_bridge.py  (or unittest discover).
Photos.app itself is never touched: _run / _export_chunk /
subprocess.run are stubbed and a fake library tree (with a fake
Photos.sqlite) stands in for ~/Pictures/Photos Library.
"""
import ast
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import photos_bridge as pb  # noqa: E402

U1 = "1A2B3C4D-0000-4000-8000-000000000001"
U2 = "F0000000-0000-4000-8000-000000000002"
U3 = "F0000000-0000-4000-8000-000000000003"   # not on disk (iCloud)
U4 = "0BADF00D-0000-4000-8000-000000000004"   # video item
U5 = "0BADF00D-0000-4000-8000-000000000005"   # jpg spelt jpeg on disk


U6 = "C0FFEE00-0000-4000-8000-000000000006"   # iCloud, 60 MB DNG
U7 = "C0FFEE00-0000-4000-8000-000000000007"   # iCloud, 178 MB video


def _touch(p, data=b"\xffJPEG", age=60):
    """A fixture file that has sat untouched for `age` seconds (a file
    of unknown size must have settled before the direct road takes
    it); age=0 = being written right now."""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    if age:
        at = time.time() - age
        os.utime(p, (at, at))


def _fake_db(lib, rows):
    """A Photos.sqlite the way the real one is: a WAL database with a
    connection held open beside it (photolibraryd), so -wal and -shm
    exist. rows = [(uuid, resource type, data store subtype, bytes)].
    Returns the open writer: the caller closes it."""
    p = os.path.join(lib, "database", "Photos.sqlite")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT)")
    con.execute("CREATE TABLE ZINTERNALRESOURCE (Z_PK INTEGER PRIMARY KEY,"
                " ZASSET INTEGER, ZRESOURCETYPE INTEGER,"
                " ZDATASTORESUBTYPE INTEGER, ZDATALENGTH INTEGER)")
    pks = {}
    for uuid, rtype, stype, n in rows:
        if uuid not in pks:
            pks[uuid] = len(pks) + 1
            con.execute("INSERT INTO ZASSET VALUES (?, ?)",
                        (pks[uuid], uuid))
        con.execute("INSERT INTO ZINTERNALRESOURCE (ZASSET, ZRESOURCETYPE,"
                    " ZDATASTORESUBTYPE, ZDATALENGTH) VALUES (?, ?, ?, ?)",
                    (pks[uuid], rtype, stype, n))
    con.commit()
    return con


class FakeLib(unittest.TestCase):
    def setUp(self):
        self._running = pb.photos_running
        pb.photos_running = lambda: True
        self.addCleanup(setattr, pb, "photos_running", self._running)
        self.tmp = tempfile.mkdtemp(prefix="tickal_pbtest_")
        self.lib = os.path.join(self.tmp, "Photos Library.photoslibrary")
        o = os.path.join(self.lib, "originals")
        _touch(os.path.join(o, "1", f"{U1}.heic"))
        _touch(os.path.join(o, "1", f"{U1}_3.mov"))      # live sidecar
        _touch(os.path.join(o, "F", f"{U2}.png"))
        _touch(os.path.join(o, "0", f"{U4}.mov"))
        _touch(os.path.join(o, "0", f"{U5}.jpeg"))
        _touch(os.path.join(o, "0", f"{U5}_3.mov"))
        self.dest = os.path.join(self.tmp, "snap")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ParseMeta(unittest.TestCase):
    def test_lines(self):
        raw = (f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n"
               f"2\t{U2}/L0/001\tfalse\tweird\tname.png\n"
               "\n"
               f"3\t{U3}/L0/001\tfalse\tIMG_3.HEIC\n")
        items, bad = pb.parse_meta(raw)
        self.assertEqual(bad, 0)
        self.assertEqual([i["idx"] for i in items], [1, 2, 3])
        self.assertEqual(items[0]["id"], f"{U1}/L0/001")
        self.assertTrue(items[0]["favorite"])
        self.assertFalse(items[1]["favorite"])
        # a tab INSIDE the filename survives (filename sits last)
        self.assertEqual(items[1]["filename"], "weird\tname.png")

    def test_bad_lines_counted(self):
        items, bad = pb.parse_meta("x\ty\tz\n1\tonly-two\n")
        self.assertEqual(items, [])
        self.assertEqual(bad, 2)

    def test_empty(self):
        self.assertEqual(pb.parse_meta(""), ([], 0))


class OriginalPath(FakeLib):
    def test_still_with_sidecar(self):
        p = pb.original_path(f"{U1}/L0/001", "IMG_1.HEIC", lib=self.lib)
        self.assertTrue(p and p.endswith(f"/originals/1/{U1}.heic"), p)

    def test_video_item(self):
        p = pb.original_path(f"{U4}/L0/001", "IMG_4.MOV", lib=self.lib)
        self.assertTrue(p and p.endswith(f"{U4}.mov"), p)

    def test_jpg_alias(self):
        p = pb.original_path(f"{U5}/L0/001", "IMG_5.JPG", lib=self.lib)
        self.assertTrue(p and p.endswith(f"{U5}.jpeg"), p)

    def test_unknown_ext_scans_dir_skips_sidecar(self):
        cache = {}
        p = pb.original_path(f"{U1}/L0/001", "IMG_1", lib=self.lib,
                             dir_cache=cache)
        self.assertTrue(p and p.endswith(f"{U1}.heic"), p)
        self.assertEqual(len(cache), 1)        # one scan, cached
        p2 = pb.original_path(f"{U5}/L0/001", "IMG_5.bogus", lib=self.lib,
                              dir_cache=cache)
        self.assertTrue(p2 and p2.endswith(f"{U5}.jpeg"), p2)

    def test_missing_is_none(self):
        self.assertIsNone(
            pb.original_path(f"{U3}/L0/001", "IMG_3.HEIC", lib=self.lib))

    def test_lowercase_uuid_maps(self):
        p = pb.original_path(f"{U2.lower()}/L0/001", "a.png", lib=self.lib)
        self.assertTrue(p and p.endswith(f"{U2}.png"), p)

    def test_foreign_id_is_none(self):
        self.assertIsNone(pb.original_path("", "a.png", lib=self.lib))
        self.assertIsNone(pb.original_path("../../etc", "a", lib=self.lib))
        self.assertIsNone(pb.original_path("not-a-uuid/L0/001", "a.png",
                                           lib=self.lib))

    def test_no_library_is_none(self):
        self.assertIsNone(pb.original_path(
            f"{U1}/L0/001", "IMG_1.HEIC", lib=os.path.join(self.tmp, "nope")))


class Run(unittest.TestCase):
    """_run: the Apple Event waits as long as the process, and the
    event's own deadline always comes first (the 2026-09-27 bug: no
    `with timeout`, so every event died at AppleScript's 120 s)."""

    def setUp(self):
        self._sp = pb.subprocess.run
        self.calls = []

    def tearDown(self):
        pb.subprocess.run = self._sp

    def _stub(self, rc=0, out="", err="", boom=False):
        def fake(cmd, **kw):
            self.calls.append((cmd, kw))
            if boom:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return subprocess.CompletedProcess(cmd, rc, out, err)
        pb.subprocess.run = fake

    def test_script_is_wrapped_and_the_process_outlives_the_event(self):
        self._stub(out="ok")
        self.assertEqual(pb._run('tell application "Photos" to beep',
                                 timeout=900), "ok")
        cmd, kw = self.calls[0]
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        self.assertTrue(cmd[2].startswith("with timeout of 900 seconds\n"))
        self.assertTrue(cmd[2].rstrip().endswith("end timeout"))
        self.assertIn('tell application "Photos" to beep', cmd[2])
        self.assertGreater(kw["timeout"], 900)
        self.assertEqual(kw["timeout"], 900 + pb.AE_GRACE)

    def test_total_is_the_process_limit_never_under_the_event(self):
        self._stub()
        pb._run("x", timeout=120, total=600)
        pb._run("x", timeout=120, total=30)
        self.assertEqual([kw["timeout"] for _, kw in self.calls],
                         [600, 120 + pb.AE_GRACE])
        self.assertTrue(all(c[2].startswith("with timeout of 120 seconds")
                            for c, _ in self.calls))

    def test_every_photos_script_rides_run(self):
        # no function talks to osascript past _run, so none can lose
        # the wrapper again: the word may only appear in a docstring
        # or inside _run, however the call is spelt
        with open(pb.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        docs = set()
        for n in ast.walk(tree):
            body = getattr(n, "body", None)
            if (isinstance(body, list) and body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))

        def mentions(node):
            return [c for c in ast.walk(node)
                    if isinstance(c, ast.Constant)
                    and isinstance(c.value, str) and id(c) not in docs
                    and "osascript" in c.value.lower()]
        owners = {}
        for top in tree.body:
            hits = mentions(top)
            if hits:
                owners[getattr(top, "name", "<module>")] = len(hits)
        self.assertEqual(owners, {"_run": 1})

    def test_1712_is_a_timeout(self):
        self._stub(rc=1, err="25:1126: execution error: Photos got an "
                             "error: AppleEvent timed out. (-1712)")
        with self.assertRaises(pb.PhotosTimeout) as c:
            pb._run("x", timeout=600)
        self.assertIn("10 min", str(c.exception))
        self.assertTrue(issubclass(pb.PhotosTimeout, pb.PhotosError))

    def test_the_code_is_read_off_the_tail(self):
        # the text quotes the media item id, and a UUID can hold a
        # group that reads like a code
        self._stub(rc=1, err='25:180: execution error: Photos got an '
                             'error: Can’t get media item id "7C3E9A10-'
                             '1712-4B2D-9E11-0A1B2C3D4E5F/L0/001". (-1728)')
        with self.assertRaises(pb.PhotosError) as c:
            pb._run("x")
        self.assertNotIsInstance(c.exception, pb.PhotosTimeout)
        self.assertIn("gone from Photos", str(c.exception))
        self._stub(rc=1, err='25:180: execution error: Photos got an '
                             'error: media item id "7C3E9A10-1743-4B2D-'
                             '9E11-0A1B2C3D4E5F/L0/001" AppleEvent timed '
                             'out. (-1712)\n')
        with self.assertRaises(pb.PhotosTimeout):
            pb._run("x")
        self._stub(rc=1, err="no number at all")
        with self.assertRaises(pb.PhotosError) as c:
            pb._run("x")
        self.assertIn("Photos scripting failed", str(c.exception))

    def test_killed_process_is_a_timeout(self):
        self._stub(boom=True)
        with self.assertRaises(pb.PhotosTimeout):
            pb._run("x", timeout=30)

    def test_codes_read_as_words(self):
        for err, word, fatal in (
                ("… (-1743)", "automation not allowed", True),
                ("… got an error: … (-600)", "Photos quit", True),
                ("… (-609)", "Photos quit", True),
                ("… Can’t get media item id … (-1728)",
                 "gone from Photos", False)):
            self._stub(rc=1, err=err)
            with self.assertRaises(pb.PhotosError) as c:
                pb._run("x")
            self.assertIn(word, str(c.exception))
            self.assertNotIsInstance(c.exception, pb.PhotosTimeout)
            self.assertEqual(isinstance(c.exception, pb.PhotosFatal), fatal)
        self._stub(rc=1, err="1:2: syntax error (-2741)")
        with self.assertRaises(pb.PhotosError) as c:
            pb._run("x")
        self.assertIn("Photos scripting failed", str(c.exception))

    def test_export_script_shape(self):
        self._stub()
        d = tempfile.mkdtemp(prefix="tickal_pbtest_")
        try:
            pb._export_chunk([f"{U6}/L0/001"], os.path.join(d, "c1"),
                             timeout=1234)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        script = self.calls[0][0][2]
        self.assertIn("with timeout of 1234 seconds", script)
        self.assertIn(f'media item id "{U6}/L0/001"', script)
        self.assertIn("with using originals", script)

    def test_selection_read_has_its_own_limit_and_words(self):
        # three events per shot: the per-event deadline cannot bound
        # the whole read, the process limit does
        self._stub(out=f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n")
        self.assertEqual(len(pb.selection_meta()), 1)
        cmd, kw = self.calls[0]
        self.assertEqual(kw["timeout"], pb.META_TOTAL)
        self.assertTrue(cmd[2].startswith("with timeout of 120 seconds"))
        self.assertIn("EMPTY_SELECTION", cmd[2])
        self._stub(boom=True)
        with self.assertRaises(pb.PhotosTimeout) as c:
            pb.selection_meta()
        self.assertIn("did not hand over the selection", str(c.exception))
        self._stub(rc=1, err="40:60: execution error: EMPTY_SELECTION "
                             "(-2700)")
        with self.assertRaises(pb.NoSelection):
            pb.selection_meta()


class Budget(unittest.TestCase):
    def test_floor_bytes_cap_blind(self):
        self.assertEqual(pb.export_budget(1, 8 * 10**6), pb.WAIT_MIN)
        # 178 MB video: two minutes of slack + the pull at WAIT_BPS
        self.assertEqual(pb.export_budget(1, 178 * 10**6),
                         120 + 178 * 10**6 // pb.WAIT_BPS)
        self.assertEqual(pb.export_budget(1, 50 * 10**9), pb.WAIT_MAX)
        self.assertEqual(pb.export_budget(1), pb.WAIT_MIN)
        self.assertEqual(pb.export_budget(4), 4 * pb.WAIT_BLIND)
        self.assertEqual(pb.export_budget(0), pb.WAIT_MIN)
        # the bug's own numbers: every budget is past AppleScript's 120 s
        self.assertGreater(pb.export_budget(1, 60 * 10**6), 120)

    def test_fmt_size(self):
        self.assertEqual(pb.fmt_size(0), "")
        self.assertEqual(pb.fmt_size(None), "")
        self.assertEqual(pb.fmt_size(400000), "1 MB")
        self.assertEqual(pb.fmt_size(343 * 10**6), "343 MB")
        self.assertEqual(pb.fmt_size(1234 * 10**6), "1.2 GB")


class Sizes(FakeLib):
    def _db(self, rows):
        con = _fake_db(self.lib, rows)
        self.addCleanup(con.close)
        return con

    def _dbdir(self):
        return sorted(os.listdir(os.path.join(self.lib, "database")))

    def test_reads_the_library(self):
        self._db([
            (U6, 0, 1, 59500000), (U6, 0, 3, 3100000),   # 3 = a render
            (U7, 1, 1, 177800000),
            (U1, 0, 1, 1229822), (U1, 3, 18, 4597816),   # live photo
            (U2, 0, 1, 5119672), (U2, 4, 17, 11534686),  # RAW + JPEG
        ])
        z = pb.original_sizes([f"{U6}/L0/001", f"{U7.lower()}/L0/001",
                               f"{U1}/L0/001", f"{U2}/L0/001",
                               f"{U3}/L0/001", "junk"], lib=self.lib)
        self.assertEqual(z[U6], {"bytes": 59500000, "pull": 59500000})
        self.assertEqual(z[U7], {"bytes": 177800000, "pull": 177800000})
        self.assertEqual(z[U1], {"bytes": 1229822,
                                 "pull": 1229822 + 4597816})
        self.assertEqual(z[U2], {"bytes": 5119672,
                                 "pull": 5119672 + 11534686})
        self.assertNotIn(U3, z)

    def test_any_trouble_is_empty(self):
        ids = [f"{U6}/L0/001"]
        self.assertEqual(pb.original_sizes(ids, lib=self.lib), {})  # no db
        p = os.path.join(self.lib, "database", "Photos.sqlite")
        _touch(p, b"not a database at all")
        _touch(p + "-shm", b"x")
        self.assertEqual(pb.original_sizes(ids, lib=self.lib), {})
        os.remove(p)
        os.remove(p + "-shm")
        con = sqlite3.connect(p)                  # the schema moved
        self.addCleanup(con.close)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE ZASSET (Z_PK INTEGER, ZUUID TEXT)")
        con.commit()
        self.assertIn("Photos.sqlite-shm", self._dbdir())
        self.assertEqual(pb.original_sizes(ids, lib=self.lib), {})
        self.assertEqual(pb.original_sizes([], lib=self.lib), {})

    def test_a_library_nobody_has_open_is_not_read(self):
        # a reader of a WAL database that finds no -shm CREATES one:
        # that would be a file added to the Photos library
        _fake_db(self.lib, [(U6, 0, 1, 10)]).close()
        self.assertEqual(self._dbdir(), ["Photos.sqlite"])
        self.assertEqual(pb.original_sizes([f"{U6}/L0/001"],
                                           lib=self.lib), {})
        self.assertEqual(self._dbdir(), ["Photos.sqlite"])

    def test_the_library_is_opened_read_only(self):
        self._db([(U6, 0, 1, 10)])
        before = self._dbdir()
        self.assertEqual(before, ["Photos.sqlite", "Photos.sqlite-shm",
                                  "Photos.sqlite-wal"])
        real, seen = sqlite3.connect, []

        def spy(*a, **kw):
            seen.append((a, kw))
            return real(*a, **kw)
        sqlite3.connect = spy
        try:
            z = pb.original_sizes([f"{U6}/L0/001"], lib=self.lib)
        finally:
            sqlite3.connect = real
        self.assertEqual(z, {U6: {"bytes": 10, "pull": 10}})
        (args, kw), = seen
        self.assertIn("?mode=ro", args[0])
        self.assertTrue(args[0].startswith("file:"))
        self.assertIs(kw.get("uri"), True)
        self.assertEqual(self._dbdir(), before)
        # and that address really cannot write
        con = real(args[0], uri=True)
        self.addCleanup(con.close)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("INSERT INTO ZASSET VALUES (99, 'X')")

    def test_complete(self):
        p = os.path.join(self.tmp, "f.bin")
        _touch(p, b"12345")
        self.assertTrue(pb._complete(p))
        self.assertTrue(pb._complete(p, 5))
        self.assertFalse(pb._complete(p, 6))        # still being written
        self.assertFalse(pb._complete(p + "zz", 5))
        _touch(p, b"12345", age=0)
        # no size known: a file touched a moment ago has not settled;
        # a known size settles it at once
        self.assertFalse(pb._complete(p))
        self.assertTrue(pb._complete(p, 5))
        _touch(p, b"")
        self.assertFalse(pb._complete(p))


class MatchExported(FakeLib):
    def test_pair_and_video(self):
        d = os.path.join(self.tmp, "c1")
        for f in ("IMG_1.HEIC", "IMG_1.MOV", "clip.mov"):
            _touch(os.path.join(d, f))
        self.assertTrue(pb._match_exported(d, "IMG_1.HEIC").endswith("IMG_1.HEIC"))
        self.assertTrue(pb._match_exported(d, "img_1.heic").endswith("IMG_1.HEIC"))
        self.assertTrue(pb._match_exported(d, "IMG_1.JPG").endswith("IMG_1.HEIC"))
        self.assertTrue(pb._match_exported(d, "CLIP.MP4").endswith("clip.mov"))
        self.assertIsNone(pb._match_exported(d, "IMG_9.HEIC"))
        self.assertIsNone(pb._match_exported(d + "zz", "IMG_1.HEIC"))
        # three shots share this folder: no lone file, alone or not
        self.assertIsNone(pb._match_exported(d, "IMG_9.MOV", alone=True))

    def test_a_sidecar_is_never_the_shot(self):
        # an edited shot exports with its recipe beside it, and
        # 'IMG_2.AAE' sorts before 'IMG_2.jpeg'
        d = os.path.join(self.tmp, "c2")
        for f in ("IMG_2.AAE", "IMG_2.xmp", "IMG_2.jpeg"):
            _touch(os.path.join(d, f))
        self.assertTrue(pb._match_exported(d, "IMG_2.JPG")
                        .endswith("IMG_2.jpeg"))
        for n, side in enumerate(("IMG_3.AAE", "IMG_3.xmp", "IMG_3.XMP")):
            e = os.path.join(self.tmp, f"only{n}")
            _touch(os.path.join(e, side))
            self.assertIsNone(pb._match_exported(e, "IMG_3.HEIC"), side)
            self.assertIsNone(
                pb._match_exported(e, "IMG_3.HEIC", alone=True), side)

    def test_normal_form_blind(self):
        import unicodedata
        d = os.path.join(self.tmp, "c4")
        _touch(os.path.join(d, unicodedata.normalize("NFD", "Šešir.HEIC")))
        got = pb._match_exported(
            d, unicodedata.normalize("NFC", "Šešir.heic"))
        self.assertIsNotNone(got)
        self.assertTrue(os.path.isfile(got))

    def test_a_folder_of_its_own_needs_no_name(self):
        # one shot per export folder: Photos spelt the file its own
        # way, the lone file of the right kind is still the shot
        d = os.path.join(self.tmp, "c5")
        for f in ("Export 0001.heic", "Export 0001.mov", "x.AAE"):
            _touch(os.path.join(d, f))
        self.assertIsNone(pb._match_exported(d, "IMG_5.HEIC"))
        self.assertTrue(pb._match_exported(d, "IMG_5.HEIC", alone=True)
                        .endswith("Export 0001.heic"))
        self.assertTrue(pb._match_exported(d, "IMG_5.MOV", alone=True)
                        .endswith("Export 0001.mov"))
        _touch(os.path.join(d, "second.heic"))
        self.assertIsNone(pb._match_exported(d, "IMG_5.HEIC", alone=True))


class Snapshot(FakeLib):
    """selection_snapshot_export end to end with Photos stubbed: on-disk
    originals ride the fast road, the iCloud straggler gets ONE export
    event into a folder of its own, order and the return contract
    hold."""

    def setUp(self):
        super().setUp()
        self._run, self._exp = pb._run, pb._export_chunk
        self.exports = []
        raw = (f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n"
               f"2\t{U3}/L0/001\tfalse\tIMG_3.HEIC\n"
               f"3\t{U4}/L0/001\tfalse\tIMG_4.MOV\n"
               f"4\t{U5}/L0/001\tfalse\tIMG_5.JPG\n")
        pb._run = lambda script, timeout=300, **kw: raw

        def fake_export(ids, dest, timeout=600):
            self.exports.append(list(ids))
            _touch(os.path.join(dest, "IMG_3.HEIC"))
            _touch(os.path.join(dest, "IMG_3.MOV"))
        pb._export_chunk = fake_export

    def tearDown(self):
        pb._run, pb._export_chunk = self._run, self._exp
        super().tearDown()

    def test_fast_road_plus_one_export(self):
        out = pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertEqual([o["filename"] for o in out],
                         ["IMG_1.HEIC", "IMG_3.HEIC", "IMG_4.MOV", "IMG_5.JPG"])
        self.assertEqual([o["direct"] for o in out],
                         [True, False, True, True])
        self.assertTrue(out[0]["favorite"])
        # ONE export event, only for the straggler, into its own c1
        self.assertEqual(self.exports, [[f"{U3}/L0/001"]])
        self.assertTrue(out[1]["path"].endswith("c1/IMG_3.HEIC"))
        # direct items: a link inside the snapshot dir (same volume) or
        # the library path itself - either way the bytes are the original
        for o in (out[0], out[2], out[3]):
            self.assertTrue(os.path.isfile(o["path"]), o["path"])
            self.assertTrue(o["path"].startswith(self.dest)
                            or o["path"].startswith(self.lib), o["path"])
        self.assertTrue(out[3]["path"].lower().endswith(".jpeg"))
        # cleanup of the snapshot dir leaves the library intact
        shutil.rmtree(self.dest)
        self.assertTrue(os.path.isfile(
            os.path.join(self.lib, "originals", "1", f"{U1}.heic")))
        for k in ("id", "filename", "favorite", "path", "direct"):
            self.assertIn(k, out[0])

    def test_empty_selection(self):
        pb._run = lambda script, timeout=300, **kw: (_ for _ in ()).throw(
            pb.PhotosError("Photos scripting failed: EMPTY_SELECTION"))
        with self.assertRaises(pb.NoSelection):
            pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertTrue(issubclass(pb.NoSelection, pb.PhotosError))

    def test_bad_line_fails_closed(self):
        pb._run = lambda script, timeout=300, **kw: "garbage line\n"
        with self.assertRaises(pb.PhotosError):
            pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertEqual(self.exports, [])

    def test_nothing_produced(self):
        pb._run = lambda script, timeout=300, **kw: f"1\t{U3}/L0/001\tfalse\tx.HEIC\n"
        asks = []

        def empty(ids, dest, timeout=600):
            asks.append(dest)
            os.makedirs(dest, exist_ok=True)
        pb._export_chunk = empty
        with self.assertRaises(pb.PhotosError) as c:
            pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertNotIsInstance(c.exception, pb.PhotosTimeout)
        self.assertEqual(str(c.exception),
                         "1 of 1 not exported · x.HEIC · "
                         "Photos left no file")
        self.assertEqual(c.exception.missing, [f"{U3}/L0/001"])
        # asked twice, each ask into a folder of its own
        self.assertEqual([os.path.basename(a) for a in asks], ["c1", "c1r"])


class Patience(FakeLib):
    """The export road after 2026-09-27: one event per shot, each
    waiting by its bytes, one banner, all or nothing, each missing
    shot's own reason, and only files that are provably whole survive
    an export that ended badly."""

    DNG, MOV, LIVE = 59500000, 177800000, 400000000

    def setUp(self):
        super().setUp()
        self._run, self._exp = pb._run, pb._export_chunk
        # U3 is a Live Photo: 7 bytes of still, a big movie beside it
        self.db = _fake_db(self.lib, [
            (U1, 0, 1, 5), (U6, 0, 1, self.DNG), (U7, 1, 1, self.MOV),
            (U3, 0, 1, 7), (U3, 3, 18, self.LIVE)])
        self.addCleanup(self.db.close)
        raw = (f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n"
               f"2\t{U6}/L0/001\tfalse\tIMG_6.DNG\n"
               f"3\t{U7}/L0/001\tfalse\tIMG_7.MOV\n"
               f"4\t{U3}/L0/001\ttrue\tIMG_3.HEIC\n")
        pb._run = lambda script, timeout=300, **kw: raw
        self.asks = []       # (ids, folder name, timeout)
        self.notes = []
        self.plan = {}       # uuid → what each ask does, in order
        self.photos_up = True
        pb.photos_running = lambda: self.photos_up

    def tearDown(self):
        pb._run, pb._export_chunk = self._run, self._exp
        super().tearDown()

    def _install(self):
        names = {U6: "IMG_6.DNG", U7: "IMG_7.MOV", U3: "IMG_3.HEIC"}
        sizes = {U6: self.DNG, U7: self.MOV, U3: 7}
        seen = {}

        def write(p, n):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.truncate(n)

        def fake(ids, dest, timeout=600):
            self.asks.append((list(ids), os.path.basename(dest), timeout))
            os.makedirs(dest, exist_ok=True)
            u = ids[0].split("/")[0]
            todo = self.plan.get(u) or ["ok"]
            act = todo[min(seen.get(u, 0), len(todo) - 1)]
            seen[u] = seen.get(u, 0) + 1
            out = os.path.join(dest, names[u])
            lib = os.path.join(self.lib, "originals", u[0],
                               f"{u}.{names[u].rsplit('.', 1)[1].lower()}")
            if act == "ok":
                write(out, sizes[u])
            elif act == "silent":
                pass
            elif act == "half+timeout":
                write(out, sizes[u] // 2)
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "whole+timeout":      # the answer got lost
                write(out, sizes[u])
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "library+timeout":    # landed in originals/ only
                write(lib, sizes[u])
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "halflib+timeout":    # still coming down there
                write(lib, sizes[u] // 2)
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "timeout":
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "error":
                raise pb.PhotosError("Photos scripting failed: boom (-1)")
            elif act == "gone":
                raise pb.PhotosError("a selected shot is gone from "
                                     "Photos · select again")
            elif act == "quit":
                raise pb.PhotosFatal("Photos quit mid-way")
            elif act == "renamed":            # Photos spelt it its way
                write(os.path.join(dest, "Export 0001."
                                   + names[u].rsplit(".", 1)[1]), sizes[u])
            elif act == "renamed+timeout":
                write(os.path.join(dest, "Export 0001."
                                   + names[u].rsplit(".", 1)[1]), sizes[u])
                raise pb.PhotosTimeout("Photos silent for 5 min")
            elif act == "ok+photos quits":
                write(out, sizes[u])
                self.photos_up = False
            else:
                raise AssertionError(act)
        pb._export_chunk = fake

    def _go(self, **kw):
        return pb.selection_snapshot_export(
            self.dest, lib=self.lib,
            notice=lambda n, b, s: self.notes.append((n, b, s)), **kw)

    def _folders(self):
        return [a[1] for a in self.asks]

    def test_one_event_per_shot_each_waiting_by_what_it_pulls(self):
        self._install()
        out = self._go()
        self.assertEqual([o["filename"] for o in out],
                         ["IMG_1.HEIC", "IMG_6.DNG", "IMG_7.MOV",
                          "IMG_3.HEIC"])
        self.assertEqual([o["direct"] for o in out],
                         [True, False, False, False])
        self.assertEqual([sorted(o) for o in out],
                         [sorted(("idx", "id", "filename", "favorite",
                                  "path", "direct"))] * 4)
        self.assertEqual([a[0] for a in self.asks],
                         [[f"{U6}/L0/001"], [f"{U7}/L0/001"],
                          [f"{U3}/L0/001"]])
        self.assertEqual(self._folders(), ["c1", "c2", "c3"])
        waits = [a[2] for a in self.asks]
        # the Live Photo waits for its MOVIE too, not for 7 bytes
        self.assertEqual(waits, [pb.export_budget(1, self.DNG),
                                 pb.export_budget(1, self.MOV),
                                 pb.export_budget(1, 7 + self.LIVE)])
        self.assertGreater(waits[2], pb.WAIT_MIN)
        self.assertTrue(all(w > 120 for w in waits))
        # ONE banner: three shots, all they pull, the sum of the waits
        self.assertEqual(
            self.notes,
            [(3, self.DNG + self.MOV + 7 + self.LIVE, sum(waits))])

    def test_no_banner_when_everything_is_on_disk(self):
        pb._run = lambda script, timeout=300, **kw: (
            f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n")
        self._install()
        out = self._go()
        self.assertEqual(len(out), 1)
        self.assertEqual(self.notes, [])
        self.assertEqual(self.asks, [])

    def test_a_broken_banner_never_stops_the_import(self):
        self._install()
        out = pb.selection_snapshot_export(
            self.dest, lib=self.lib,
            notice=lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(len(out), 4)

    def test_timeout_stops_asking_and_nothing_is_handed_over(self):
        self.plan = {U6: ["timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        m = str(c.exception)
        self.assertEqual(
            m, "3 of 4 still in iCloud · "
               + pb.fmt_size(self.DNG + self.MOV + 7 + self.LIVE)
               + " · IMG_6.DNG, IMG_7.MOV +1 · Photos keeps downloading")
        # facts only: the road that asked words the ending
        self.assertNotIn("nothing imported", m)
        self.assertNotIn("again", m)
        self.assertEqual(c.exception.head, "3 of 4 still in iCloud")
        self.assertEqual(f"{c.exception.head} · {c.exception.tail}", m)
        self.assertEqual(c.exception.missing,
                         [f"{U6}/L0/001", f"{U7}/L0/001", f"{U3}/L0/001"])
        # one ask only: no retry, no ask for the shots behind it
        self.assertEqual(self._folders(), ["c1"])

    def test_half_file_after_a_timeout_is_never_an_original(self):
        self.plan = {U6: ["half+timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        self.assertIn("3 of 4 still in iCloud", str(c.exception))

    def test_half_library_copy_after_a_timeout_is_refused(self):
        self.plan = {U3: ["halflib+timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        self.assertIn("1 of 4 still in iCloud", str(c.exception))
        self.assertEqual(c.exception.missing, [f"{U3}/L0/001"])
        self.assertFalse(os.path.exists(os.path.join(self.dest, "4")))

    def test_lost_answer_stops_nothing(self):
        # the event timed out but the file is there byte for byte:
        # that shot counts and the shots behind it are still asked
        self.plan = {U6: ["whole+timeout"]}
        self._install()
        out = self._go()
        self.assertEqual(len(out), 4)
        self.assertEqual(self._folders(), ["c1", "c2", "c3"])
        self.assertTrue(out[1]["path"].endswith("c1/IMG_6.DNG"))
        self.assertFalse(any("why" in o for o in out))

    def test_library_copy_after_a_timeout_is_kept(self):
        self.plan = {U6: ["library+timeout"]}
        self._install()
        out = self._go()
        self.assertEqual(len(out), 4)
        self.assertTrue(out[1]["direct"])
        self.assertEqual(os.path.getsize(out[1]["path"]), self.DNG)
        self.assertEqual(self._folders(), ["c1", "c2", "c3"])

    def test_without_a_size_nothing_is_salvaged(self):
        self.db.close()
        shutil.rmtree(os.path.join(self.lib, "database"))
        self.plan = {U3: ["whole+timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        self.assertEqual(str(c.exception),
                         "1 of 4 still in iCloud · IMG_3.HEIC · "
                         "Photos keeps downloading")
        # blind patience: no size, the per-shot floor
        self.assertTrue(all(a[2] == pb.WAIT_MIN for a in self.asks))

    def test_unknown_size_a_fresh_file_takes_the_export_road(self):
        # no size to prove it whole and touched a moment ago: Photos
        # may still be writing it
        self.db.close()
        shutil.rmtree(os.path.join(self.lib, "database"))
        p = os.path.join(self.lib, "originals", "C", f"{U6}.dng")
        _touch(p, b"x" * 10, age=0)
        self._install()
        out = self._go()
        self.assertFalse(out[1]["direct"])
        self.assertIn([f"{U6}/L0/001"], [a[0] for a in self.asks])
        self.asks.clear()
        _touch(p, b"x" * 10, age=60)             # it has settled
        shutil.rmtree(self.dest)
        out = self._go()
        self.assertTrue(out[1]["direct"])
        self.assertNotIn([f"{U6}/L0/001"], [a[0] for a in self.asks])

    def test_silent_miss_is_asked_again(self):
        self.plan = {U7: ["silent", "ok"]}
        self._install()
        out = self._go()
        self.assertEqual(len(out), 4)
        self.assertEqual(self._folders(), ["c1", "c2", "c2r", "c3"])
        self.assertTrue(out[2]["path"].endswith("c2r/IMG_7.MOV"))

    def test_error_is_asked_again_and_the_others_still_come_down(self):
        self.plan = {U6: ["error"]}
        self._install()
        with self.assertRaises(pb.PhotosError) as c:
            self._go()
        self.assertNotIsInstance(c.exception, pb.PhotosTimeout)
        self.assertEqual(str(c.exception),
                         "1 of 4 not exported · IMG_6.DNG · boom (-1)")
        self.assertEqual(c.exception.missing, [f"{U6}/L0/001"])
        # U6 twice, then U7 and U3 all the same: they stay in the
        # library for the next run
        self.assertEqual(self._folders(), ["c1", "c1r", "c2", "c3"])

    def test_a_cured_error_is_nobodys_reason(self):
        self.plan = {U6: ["gone", "ok"], U7: ["silent", "silent"]}
        self._install()
        with self.assertRaises(pb.PhotosError) as c:
            self._go()
        self.assertEqual(str(c.exception),
                         "1 of 4 not exported · IMG_7.MOV · "
                         "Photos left no file")
        self.assertEqual(c.exception.missing, [f"{U7}/L0/001"])

    def test_a_hard_error_is_not_hidden_by_a_later_timeout(self):
        self.plan = {U6: ["gone", "gone"], U7: ["timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosError) as c:
            self._go()
        self.assertNotIsInstance(c.exception, pb.PhotosTimeout)
        e = c.exception
        self.assertEqual(e.head, "2 of 4 still in iCloud · "
                                 "1 of 4 not exported")
        self.assertEqual(
            e.tail,
            pb.fmt_size(self.MOV + 7 + self.LIVE)
            + " · IMG_7.MOV, IMG_3.HEIC · IMG_6.DNG · a selected shot is "
              "gone from Photos · select again · Photos keeps downloading")
        self.assertEqual(str(e), f"{e.head} · {e.tail}")
        self.assertEqual(sorted(e.missing),
                         sorted(f"{u}/L0/001" for u in (U6, U7, U3)))
        self.assertEqual(self._folders(), ["c1", "c1r", "c2"])

    def test_smallest_pull_is_asked_first(self):
        # selection order U6 (60 MB), U7 (178 MB), U3 (7 bytes here):
        # asked U3, U6, U7 - handed back in selection order
        self.db.execute("DELETE FROM ZINTERNALRESOURCE "
                        "WHERE ZDATASTORESUBTYPE = 18")
        self.db.commit()
        self._install()
        out = self._go()
        self.assertEqual([a[0][0][:36] for a in self.asks], [U3, U6, U7])
        self.assertEqual([o["filename"] for o in out],
                         ["IMG_1.HEIC", "IMG_6.DNG", "IMG_7.MOV",
                          "IMG_3.HEIC"])
        self.assertTrue(out[3]["path"].endswith("c1/IMG_3.HEIC"))
        self.assertTrue(out[2]["path"].endswith("c3/IMG_7.MOV"))

    def test_a_stall_leaves_only_the_bigger_shots_unasked(self):
        self.db.execute("DELETE FROM ZINTERNALRESOURCE "
                        "WHERE ZDATASTORESUBTYPE = 18")
        self.db.commit()
        self.plan = {U6: ["timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        self.assertEqual(c.exception.head, "2 of 4 still in iCloud")
        self.assertEqual(c.exception.missing,
                         [f"{U6}/L0/001", f"{U7}/L0/001"])

    def test_photos_quitting_ends_the_run_at_once(self):
        self.plan = {U6: ["quit"]}
        self._install()
        with self.assertRaises(pb.PhotosFatal) as c:
            self._go()
        e = c.exception
        self.assertEqual((e.head, e.tail), ("Photos quit mid-way", ""))
        self.assertEqual(len(e.missing), 3)
        # no second ask, no ask for the others: each `tell` would
        # launch the Photos that was just closed
        self.assertEqual(self._folders(), ["c1"])

    def test_no_tell_is_sent_to_a_photos_that_is_gone(self):
        self._install()
        self.photos_up = False
        with self.assertRaises(pb.PhotosFatal) as c:
            self._go()
        self.assertEqual(self.asks, [])
        self.assertEqual(len(c.exception.missing), 3)

    def test_photos_is_checked_before_every_ask(self):
        # it quits after the first shot came down: the second shot is
        # never asked
        self.plan = {U6: ["ok+photos quits"]}
        self._install()
        with self.assertRaises(pb.PhotosFatal) as c:
            self._go()
        self.assertEqual(self._folders(), ["c1"])
        self.assertEqual(c.exception.missing,
                         [f"{U7}/L0/001", f"{U3}/L0/001"])

    def test_photos_is_checked_before_the_second_ask_too(self):
        real = pb._export_chunk

        def silent_then_gone(ids, dest, timeout=600):
            self.asks.append((list(ids), os.path.basename(dest), timeout))
            os.makedirs(dest, exist_ok=True)
            self.photos_up = False
        pb._export_chunk = silent_then_gone
        self.addCleanup(setattr, pb, "_export_chunk", real)
        with self.assertRaises(pb.PhotosFatal):
            self._go()
        self.assertEqual(self._folders(), ["c1"])      # never c1r

    def test_a_file_photos_named_its_own_way_is_the_shot(self):
        # the verb's folders hold one shot each (alone=True), on the
        # plain road and on the salvage road
        self.plan = {U6: ["renamed"], U7: ["renamed+timeout"]}
        self._install()
        out = self._go()
        self.assertEqual(self._folders(), ["c1", "c2", "c3"])
        self.assertTrue(out[1]["path"].endswith("c1/Export 0001.DNG"))
        self.assertTrue(out[2]["path"].endswith("c2/Export 0001.MOV"))
        self.assertEqual(os.path.getsize(out[2]["path"]), self.MOV)

    def test_each_failed_shot_keeps_its_own_reason(self):
        for plan, tail in (
                ({U6: ["gone", "gone"], U7: ["silent", "silent"]},
                 "IMG_6.DNG · a selected shot is gone from Photos · "
                 "select again · IMG_7.MOV · Photos left no file"),
                ({U6: ["silent", "silent"], U7: ["gone", "gone"]},
                 "IMG_6.DNG · Photos left no file · IMG_7.MOV · a "
                 "selected shot is gone from Photos · select again"),
                ({U6: ["silent", "silent"], U7: ["silent", "silent"]},
                 "IMG_6.DNG, IMG_7.MOV · Photos left no file")):
            self.asks.clear()
            shutil.rmtree(self.dest, ignore_errors=True)
            self.plan = plan
            self._install()
            with self.assertRaises(pb.PhotosError) as c:
                self._go()
            self.assertEqual(c.exception.head, "2 of 4 not exported")
            self.assertEqual(c.exception.tail, tail)
            self.assertFalse(c.exception.waiting)

    def test_a_size_is_said_only_when_every_shot_has_one(self):
        # U7 has no row: 60 MB + 400 MB would pass for the whole pull
        self.db.execute("DELETE FROM ZINTERNALRESOURCE WHERE ZASSET = "
                        "(SELECT Z_PK FROM ZASSET WHERE ZUUID = ?)", (U7,))
        self.db.commit()
        self.plan = {U7: ["timeout"]}
        self._install()
        with self.assertRaises(pb.PhotosTimeout) as c:
            self._go()
        self.assertEqual(self.notes[0][:2], (3, 0))
        # and the shot of unknown size counts as the smallest: first
        self.assertEqual(self.asks[0][0], [f"{U7}/L0/001"])
        self.assertEqual(self.asks[0][2], pb.WAIT_MIN)
        self.assertEqual(c.exception.tail,
                         "IMG_6.DNG, IMG_7.MOV +1 · Photos keeps "
                         "downloading")
        self.assertTrue(c.exception.waiting)
        self.assertEqual(pb._told({}, [{"id": f"{U6}/L0/001"}]), 0)
        self.assertEqual(pb._told({}, []), 0)

    def test_half_file_on_disk_takes_the_export_road(self):
        # originals/ holds a file that is not whole yet (Photos is
        # writing it): the fast road must not hand it over, however
        # long it has sat there
        p = os.path.join(self.lib, "originals", "C", f"{U6}.dng")
        _touch(p, b"x" * 10)
        self._install()
        out = self._go()
        self.assertFalse(out[1]["direct"])
        self.assertIn([f"{U6}/L0/001"], [a[0] for a in self.asks])

    def test_timeout_override(self):
        self._install()
        self._go(timeout=42)
        self.assertEqual({a[2] for a in self.asks}, {42})

    def test_only_narrows_before_anything_is_fetched(self):
        self._install()
        out = self._go(only=lambda its: [i for i in its if i["favorite"]])
        self.assertEqual([o["filename"] for o in out],
                         ["IMG_1.HEIC", "IMG_3.HEIC"])
        self.assertEqual([a[0] for a in self.asks], [[f"{U3}/L0/001"]])
        self.assertEqual(self.notes[0][:2], (1, 7 + self.LIVE))

    def test_only_empty_and_only_raising(self):
        self._install()
        self.assertEqual(self._go(only=lambda its: []), [])
        self.assertEqual(self.asks, [])

        def no(its):
            raise pb.PhotosError("no ♥ in selection")
        with self.assertRaises(pb.PhotosError) as c:
            self._go(only=no)
        self.assertEqual(str(c.exception), "no ♥ in selection")
        self.assertFalse(getattr(c.exception, "missing", None))
        self.assertEqual(self.asks, [])

    def test_the_verb_sweeps_what_earlier_runs_left(self):
        root = os.path.join(self.tmp, "T")
        mine = os.path.join(root, "tickal_tph_aaaaaaaa")
        old = os.path.join(root, "tickal_tph_bbbbbbbb")
        _touch(os.path.join(old, "c1", "IMG_9.MOV"))
        at = time.time() - 2 * pb.STALE
        os.utime(old, (at, at))
        self._install()
        out = pb.selection_snapshot_export(mine, lib=self.lib)
        self.assertEqual(len(out), 4)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(all(os.path.isfile(o["path"]) for o in out))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="tickal_pbtest_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _dir(self, name, age=0):
        p = os.path.join(self.root, name)
        os.makedirs(os.path.join(p, "c1"))
        _touch(os.path.join(p, "c1", "IMG_1.HEIC"))
        if age:
            at = time.time() - age
            os.utime(p, (at, at))
        return p

    def test_only_old_siblings_with_the_same_prefix(self):
        mine = self._dir("tickal_tph_aaaaaaaa")
        old = self._dir("tickal_tph_bbbbbbbb", age=2 * pb.STALE)
        fresh = self._dir("tickal_tph_cccccccc", age=60)
        other = self._dir("tickal_att_dddddddd", age=2 * pb.STALE)
        odd = self._dir("tickal_tph_long_name_here", age=2 * pb.STALE)
        _touch(os.path.join(self.root, "tickal_tph_ffffffff"))
        os.utime(os.path.join(self.root, "tickal_tph_ffffffff"), (1, 1))
        pb._sweep_stale(mine)
        self.assertFalse(os.path.exists(old))
        for p in (mine, fresh, other, odd,
                  os.path.join(self.root, "tickal_tph_ffffffff")):
            self.assertTrue(os.path.exists(p), p)

    def test_a_run_at_the_longest_wait_is_never_swept(self):
        # the dir's own mtime stands still while a shot is awaited and
        # while Eagle copies: STALE must be far past all of that
        tail = 1800
        self.assertGreater(pb.STALE, pb.WAIT_MAX + pb.AE_GRACE + tail)
        mine = self._dir("tickal_tph_aaaaaaaa")
        live = self._dir("tickal_tph_bbbbbbbb",
                         age=pb.WAIT_MAX + pb.AE_GRACE + tail)
        pb._sweep_stale(mine)
        self.assertTrue(os.path.exists(live))

    def test_foreign_dest_sweeps_nothing(self):
        old = self._dir("snapshot_bbbbbbbb", age=2 * pb.STALE)
        pb._sweep_stale(os.path.join(self.root, "snapshot_aaaaaaaa"))
        pb._sweep_stale(os.path.join(self.root, "snap"))
        pb._sweep_stale(os.path.join(self.root, "missing",
                                     "tickal_x_12345678"))
        self.assertTrue(os.path.exists(old))


class PrimaryFile(FakeLib):
    def test_export_by_id_helper(self):
        d = os.path.join(self.tmp, "one")
        for f in ("IMG_1.HEIC", "IMG_1.MOV"):
            _touch(os.path.join(d, f))
        self.assertTrue(pb._primary_file(d).endswith("IMG_1.HEIC"))
        self.assertIsNone(pb._primary_file(d + "zz"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
