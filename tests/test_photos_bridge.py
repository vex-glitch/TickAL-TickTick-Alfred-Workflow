#!/usr/bin/env python3
"""Unit suite for src/photos_bridge.py - the direct-disk snapshot road.
Run: python3 tests/test_photos_bridge.py  (or unittest discover).
Photos.app itself is never touched: _run / _export_chunk are stubbed
and a fake library tree stands in for ~/Pictures/Photos Library.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import photos_bridge as pb  # noqa: E402

U1 = "1A2B3C4D-0000-4000-8000-000000000001"
U2 = "F0000000-0000-4000-8000-000000000002"
U3 = "F0000000-0000-4000-8000-000000000003"   # not on disk (iCloud)
U4 = "0BADF00D-0000-4000-8000-000000000004"   # video item
U5 = "0BADF00D-0000-4000-8000-000000000005"   # jpg spelt jpeg on disk


def _touch(p, data=b"\xffJPEG"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


class FakeLib(unittest.TestCase):
    def setUp(self):
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


class Chunks(unittest.TestCase):
    def test_size_and_stem_collision(self):
        items = [{"filename": f"IMG_{i}.HEIC"} for i in range(5)]
        self.assertEqual([len(c) for c in pb._chunks(items, size=2)],
                         [2, 2, 1])
        twins = [{"filename": "IMG_1.HEIC"}, {"filename": "img_1.MOV"},
                 {"filename": "IMG_2.HEIC"}]
        cs = pb._chunks(twins, size=20)
        self.assertEqual([[i["filename"] for i in c] for c in cs],
                         [["IMG_1.HEIC"], ["img_1.MOV", "IMG_2.HEIC"]])
        self.assertEqual(pb._chunks([]), [])


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


class Snapshot(FakeLib):
    """selection_snapshot_export end to end with Photos stubbed: on-disk
    originals ride the fast road, the iCloud straggler rides ONE
    chunked export, order and the return contract hold."""

    def setUp(self):
        super().setUp()
        self._run, self._exp = pb._run, pb._export_chunk
        self.exports = []
        raw = (f"1\t{U1}/L0/001\ttrue\tIMG_1.HEIC\n"
               f"2\t{U3}/L0/001\tfalse\tIMG_3.HEIC\n"
               f"3\t{U4}/L0/001\tfalse\tIMG_4.MOV\n"
               f"4\t{U5}/L0/001\tfalse\tIMG_5.JPG\n")
        pb._run = lambda script, timeout=300: raw

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
        # ONE export session, only for the straggler
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
        pb._run = lambda script, timeout=300: (_ for _ in ()).throw(
            pb.PhotosError("Photos scripting failed: EMPTY_SELECTION"))
        with self.assertRaises(pb.NoSelection):
            pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertTrue(issubclass(pb.NoSelection, pb.PhotosError))

    def test_bad_line_fails_closed(self):
        pb._run = lambda script, timeout=300: "garbage line\n"
        with self.assertRaises(pb.PhotosError):
            pb.selection_snapshot_export(self.dest, lib=self.lib)
        self.assertEqual(self.exports, [])

    def test_nothing_produced(self):
        pb._run = lambda script, timeout=300: f"1\t{U3}/L0/001\tfalse\tx.HEIC\n"
        pb._export_chunk = lambda ids, dest, timeout=600: os.makedirs(dest)
        with self.assertRaises(pb.PhotosError):
            pb.selection_snapshot_export(self.dest, lib=self.lib)


class PrimaryFile(FakeLib):
    def test_export_by_id_helper(self):
        d = os.path.join(self.tmp, "one")
        for f in ("IMG_1.HEIC", "IMG_1.MOV"):
            _touch(os.path.join(d, f))
        self.assertTrue(pb._primary_file(d).endswith("IMG_1.HEIC"))
        self.assertIsNone(pb._primary_file(d + "zz"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
