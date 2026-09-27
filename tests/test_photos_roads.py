#!/usr/bin/env python3
"""The two Photos roads of xact.py after 2026-09-27 (Vex: 'AppleEvent
timed out (-1712)' twice in a row on Send session photos): the
'downloading' banner, the attach road fetching the ♥ shots only, a
set that did not arrive whole stopping the import with NOTHING filed,
each road wording its own verdict and next step (the STAGE to send to
again), and one import at a time. Photos is stubbed at osascript
(the real bridge runs over a fake library) or at the bridge's verb;
Eagle, TickTick and the clipboard are tripwires that RAISE: no
Photos, no Eagle, no network. HOME is a scratch dir before any repo
import and every temp dir the roads make lands inside the test's
own: ~/.ticktick_alfred and the real temp dir stay untouched.
Run: python3 tests/test_photos_roads.py   (or unittest discover)
"""
import atexit
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_REAL_HOME = os.environ.get("HOME")
_SCRATCH = tempfile.mkdtemp(prefix="tickal_prhome_")
os.environ["HOME"] = _SCRATCH              # before ANY repo import
os.environ["TICKAL_NO_SETTLE"] = "1"       # no background follow-ups
atexit.register(shutil.rmtree, _SCRATCH, True)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "src"), os.path.join(_ROOT, "Scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("crm_records_list_id", "6a4e50e9842a1194a7c681e1")
os.environ.setdefault("crm_records_tags",
                      "🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive")
import clipboard  # noqa: E402
import crm_records  # noqa: E402
import eagle  # noqa: E402
import photos_bridge as pb  # noqa: E402
import xact  # noqa: E402

if _REAL_HOME is not None:                 # the suites after this one
    os.environ["HOME"] = _REAL_HOME

UA = "AAAAAAAA-0000-4000-8000-00000000000A"
UB = "BBBBBBBB-0000-4000-8000-00000000000B"


def _it(idx, name, fav=False):
    return {"idx": idx, "id": f"U{idx}/L0/001", "filename": name,
            "favorite": fav}


class Base(unittest.TestCase):
    # everything past the Photos read: reaching any of it is a failure
    WIRES = ((eagle, "ensure_library"), (eagle, "add_items"),
             (eagle, "create_folder"), (eagle, "_raw"),
             (eagle, "_mcp_call"), (crm_records, "_api"),
             (clipboard, "image_file"), (clipboard, "png_bytes"),
             (eagle, "wait_imported"), (eagle, "items_in_folder"),
             (eagle, "folder_node"),
             (xact, "_eagle_ensure_logbook_folder"),
             (xact, "_finder_selection"), (xact, "_attach_file_to"),
             (pb, "file_to_album"))
    PATCH = WIRES + ((xact, "_crm_say"), (xact, "_say_now"),
                     (xact, "_records_ready"), (xact, "_record_by_id"),
                     (xact, "run_path"), (pb, "photos_running"),
                     (pb, "selection_snapshot_export"),
                     (pb, "LIBRARY"))

    def setUp(self):
        self._saved = [(o, n, getattr(o, n)) for o, n in self.PATCH]
        self._sp = pb.subprocess.run
        self.said, self.calls, self.touched = [], [], []
        for o, n in self.WIRES:
            setattr(o, n, self._wire(f"{o.__name__}.{n}"))
        xact._crm_say = self.said.append
        self.now = []                    # banners sent mid-run
        xact._say_now = self.now.append
        xact._records_ready = lambda: True
        xact._record_by_id = lambda tid: {
            "id": tid, "title": "🎨 Erol • Griffin", "content": "",
            "tags": ["🗂️logbook"], "projectId": "REC"}
        pb.photos_running = lambda: True
        self.tmp = tempfile.mkdtemp(prefix="tickal_prtest_")
        # every mkdtemp of the roads (and the bridge's sweep of its
        # siblings) stays inside this test's own dir
        self._tempdir = tempfile.tempdir
        tempfile.tempdir = os.path.join(self.tmp, "T")
        os.makedirs(tempfile.tempdir)
        pb.LIBRARY = os.path.join(self.tmp, "Photos Library.photoslibrary")
        # the lock file lives in a tmp run dir, never ~/.ticktick_alfred
        xact.run_path = lambda name: os.path.join(self.tmp, name)

    def tearDown(self):
        for o, n, v in self._saved:
            setattr(o, n, v)
        pb.subprocess.run = self._sp
        tempfile.tempdir = self._tempdir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snapshots(self):
        return sorted(os.listdir(os.path.join(self.tmp, "T")))

    def _wire(self, name):
        def trip(*a, **k):
            self.touched.append(name)
            raise AssertionError(f"tripwire: {name}")
        return trip

    def _export(self, result):
        def fake(dest, **kw):
            self.calls.append(kw)
            self.dest = dest
            if isinstance(result, Exception):
                raise result
            if result == "one shot":
                p = os.path.join(dest, "1", "IMG_1.HEIC")
                os.makedirs(os.path.dirname(p))
                with open(p, "wb") as f:
                    f.write(b"heic")
                return [{"idx": 1, "id": "U1/L0/001", "path": p,
                         "filename": "IMG_1.HEIC", "favorite": False,
                         "direct": True}]
            return result
        pb.selection_snapshot_export = fake

    def _osascript(self, meta, export_err):
        """The REAL bridge over a stubbed osascript: the selection read
        answers `meta`, every export fails the way Photos did."""
        self.scripts = []

        def fake(cmd, **kw):
            self.scripts.append(cmd[2] if cmd[:1] == ["osascript"] else cmd)
            if cmd[:1] != ["osascript"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "export {" in cmd[2]:
                return subprocess.CompletedProcess(cmd, 1, "", export_err)
            return subprocess.CompletedProcess(cmd, 0, meta, "")
        pb.subprocess.run = fake


def _incomplete(head, tail, cls=pb.PhotosTimeout):
    return pb._facts(cls(f"{head} · {tail}"), head, tail,
                     [{"id": "U6/L0/001"}])


WAITING = ("3 of 4 still in iCloud",
           "237 MB · IMG_6.DNG, IMG_7.MOV +1 · Photos keeps downloading")


class Banner(Base):
    def test_words_and_the_road_they_take(self):
        xact._photos_wait_banner(16, 1034 * 10**6, 2400)
        xact._photos_wait_banner(1, 0, 300)
        # mid-run banners skip the XAct queue, final toasts keep it
        self.assertEqual(self.now,
                         ["📸 16 from iCloud · 1.0 GB · downloading",
                          "📸 1 from iCloud · downloading"])
        self.assertEqual(self.said, [])

    def test_say_now_fires_end_and_never_holds_the_run(self):
        real = [v for o, n, v in self._saved
                if (o, n) == (xact, "_say_now")][0]
        seen = []

        def fake(cmd, **kw):
            seen.append((cmd, kw))
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        sp, xact.subprocess.run = xact.subprocess.run, fake
        try:
            self.assertIsNone(real('📸 4 from "iCloud"'))
        finally:
            xact.subprocess.run = sp
        (cmd, kw), = seen
        self.assertEqual(cmd[0], "osascript")
        self.assertIn('run trigger "End" in workflow "com.vex.tickal"',
                      cmd[2])
        self.assertEqual(cmd[3], "📸 4 from 'iCloud'")
        self.assertEqual(kw["timeout"], 10)


class Trouble(Base):
    """The bridge states facts, the road words the verdict and the
    next step, and both come BEFORE the detail: a banner shows two
    lines."""

    def test_waiting_set_says_what_is_safe_to_run_again(self):
        e = _incomplete(*WAITING)
        self.assertEqual(
            xact._photos_trouble(e),
            "Nothing imported · 3 of 4 still in iCloud · send again in "
            "a few min · 237 MB · IMG_6.DNG, IMG_7.MOV +1 · Photos keeps "
            "downloading")
        self.assertTrue(
            xact._photos_trouble(e, again="send again as S2").startswith(
                "Nothing imported · 3 of 4 still in iCloud · send again "
                "as S2 in a few min · 237 MB"))
        self.assertTrue(
            xact._photos_trouble(e, "attached", "attach again").startswith(
                "Nothing attached · 3 of 4 still in iCloud · attach again "
                "in a few min · "))

    def test_failed_set_promises_no_wait(self):
        e = _incomplete("1 of 4 not exported",
                        "IMG_6.DNG · a selected shot is gone from Photos "
                        "· select again", pb.PhotosError)
        m = xact._photos_trouble(e)
        self.assertEqual(
            m, "Nothing imported · 1 of 4 not exported · send again · "
               "IMG_6.DNG · a selected shot is gone from Photos · select "
               "again")
        self.assertNotIn("few min", m)      # time will not bring it

    def test_failed_set_names_the_stage_too(self):
        e = _incomplete("1 of 4 not exported",
                        "IMG_6.DNG · Photos left no file", pb.PhotosError)
        self.assertEqual(
            xact._photos_trouble(e, again="send again as Consult"),
            "Nothing imported · 1 of 4 not exported · send again as "
            "Consult · IMG_6.DNG · Photos left no file")

    def test_mixed_set_still_says_to_wait(self):
        e = _incomplete("3 of 5 still in iCloud · 1 of 5 not exported",
                        "IMG_3.DNG, IMG_4.DNG +1 · IMG_2.DNG · Photos "
                        "left no file · Photos keeps downloading",
                        pb.PhotosError)
        e.waiting = True
        self.assertTrue(
            xact._photos_trouble(e, again="send again as Consult")
            .startswith("Nothing imported · 3 of 5 still in iCloud · 1 of "
                        "5 not exported · send again as Consult in a few "
                        "min · IMG_3.DNG"))

    def test_photos_quit(self):
        e = _incomplete("Photos quit mid-way", "", pb.PhotosFatal)
        self.assertEqual(
            xact._photos_trouble(e, again="send again as Consult"),
            "Nothing imported · Photos quit mid-way · open Photos · "
            "send again as Consult")

    def test_trouble_reading_the_selection_is_worded_by_the_road(self):
        # no set yet, so no .missing: the step must be named all the
        # same, 'run again' would re-run a road that already wrote
        self.assertEqual(
            xact._photos_trouble(
                pb.PhotosTimeout("Photos did not hand over the selection"),
                again="send again as S3"),
            "Nothing imported · Photos did not hand over the selection "
            "· send again as S3 in a few min")
        self.assertEqual(
            xact._photos_trouble(pb.PhotosFatal("Photos quit mid-way"),
                                 "attached", "attach again"),
            "Nothing attached · Photos quit mid-way · open Photos · "
            "attach again")
        self.assertEqual(
            xact._photos_trouble(pb.PhotosFatal("Photos automation not "
                                                "allowed - System Settings")),
            "Nothing imported · Photos automation not allowed - System "
            "Settings · send again")

    def test_any_other_trouble_is_left_alone(self):
        for e in (pb.PhotosError("no ♥ in selection"),
                  pb.NoSelection("nothing selected in Photos"),
                  pb.PhotosError("3 selected items had unparseable names")):
            self.assertEqual(xact._photos_trouble(e), str(e))

    def test_the_bridge_never_says_run_again(self):
        with open(pb.__file__, encoding="utf-8") as f:
            src = f.read()
        for line in src.splitlines():
            if "raise " in line or "PhotosError(" in line \
                    or "PhotosTimeout(" in line or "PhotosFatal(" in line:
                self.assertNotIn("run again", line, line)


class HeroItems(Base):
    def test_hearts_stills_only(self):
        its = [_it(1, "a.HEIC", True), _it(2, "b.DNG"),
               _it(3, "c.MOV", True), _it(4, "d.jpg", True)]
        self.assertEqual([i["filename"] for i in xact._hero_items(its)],
                         ["a.HEIC", "d.jpg"])

    def test_single_shot_counts_without_a_heart(self):
        self.assertEqual(len(xact._hero_items([_it(1, "a.DNG")])), 1)

    def test_same_words_as_pick_heroes(self):
        for its in ([_it(1, "a.HEIC"), _it(2, "b.HEIC")],
                    [_it(1, "a.MOV", True)], [_it(1, "clip.mp4")]):
            with self.assertRaises(pb.PhotosError) as c:
                xact._hero_items(its)
            shots = [dict(i, path="/x/" + i["filename"]) for i in its]
            self.assertEqual(str(c.exception), xact._pick_heroes(shots)[1])


class SessionPhotos(Base):
    def test_the_1712_of_the_report_end_to_end(self):
        # the real bridge, Photos answering the export the way it did
        # on 2026-09-27: two cloud-only shots, the first one stalls
        self._osascript(
            f"1\t{UA}/L0/001\ttrue\tIMG_5054.DNG\n"
            f"2\t{UB}/L0/001\tfalse\tIMG_5053.MOV\n",
            "25:1126: execution error: Photos got an error: AppleEvent "
            "timed out. (-1712)")
        self.assertIs(xact.session_photos("LB1", ""), False)
        self.assertEqual(self.now, ["📸 2 from iCloud · downloading"])
        self.assertEqual(
            self.said,
            ["📸 Nothing imported · 2 of 2 still in iCloud · send again "
             "in a few min · IMG_5054.DNG, IMG_5053.MOV · Photos keeps "
             "downloading"])
        for s in self.said + self.now:
            self.assertNotIn("-1712", s)
            self.assertNotIn("scripting failed", s)
        # one export asked (the stall stops the rest), none retried,
        # and it carried its own deadline
        exports = [s for s in self.scripts if "export {" in s]
        self.assertEqual(len(exports), 1)
        self.assertTrue(exports[0].startswith(
            f"with timeout of {pb.WAIT_MIN} seconds"))
        self.assertIn(UA, exports[0])
        self.assertEqual(self.touched, [])

    def test_a_set_still_in_icloud_files_nothing(self):
        self._export(_incomplete(*WAITING))
        self.assertIs(xact.session_photos("LB1", ""), False)
        self.assertEqual(len(self.said), 1)
        self.assertTrue(self.said[0].startswith(
            "📸 Nothing imported · 3 of 4 still in iCloud · send again in "
            "a few min · "))
        # nothing downstream ran: no Finder or clipboard fallback, no
        # Eagle, no album, no attach, no TickTick
        self.assertEqual(self.touched, [])
        self.assertIs(self.calls[0]["notice"], xact._photos_wait_banner)
        self.assertNotIn("only", self.calls[0])


class Stage(Base):
    """⏎ on 📸 Send session photos files into the CURRENT session: a
    failed consult or older-session import must name its stage, or the
    rerun lands the shots in the wrong folder."""

    def _said_for(self, stage):
        self.said.clear()
        self._export(_incomplete(*WAITING))
        self.assertIs(xact.session_photos("LB1", stage), False)
        return self.said[0]

    def test_the_callers_own_words_win(self):
        # Session done left its task untouched: running IT again is
        # the step, and one banner must not name a second retry
        self._export(_incomplete(*WAITING))
        self.assertIs(xact.session_photos(
            "LB1", "consult", again="run Session done again"), False)
        self.assertIn("still in iCloud · run Session done again in a few "
                      "min · ", self.said[0])
        self.assertNotIn("send again", self.said[0])
        with open(xact.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('again="run Session done again"', src)

    def test_the_hint_names_the_stage(self):
        for stage, word in (("", "send again in a few min"),
                            ("s", "send again in a few min"),
                            ("consult", "send again as Consult in a few"),
                            ("s2", "send again as S2 in a few min"),
                            ("finished", "send again as Finished in a"),
                            ("healed", "send again as Healed in a few")):
            self.assertIn(f"still in iCloud · {word}",
                          self._said_for(stage), stage)


class Lock(Base):
    def test_one_import_at_a_time(self):
        held = open(os.path.join(self.tmp, "tickal_photos_import.lock"),
                    "a+")
        self.addCleanup(held.close)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self._export([])
        self.assertIs(xact.session_photos("LB1", "consult"), False)
        xact.photo_attach("P", "T")
        # verdict, cause, the step with its stage - and sent past the
        # XAct queue, the running import may be sitting on it
        self.assertEqual(
            self.now,
            ["📸 Nothing imported · another import running · send again "
             "as Consult after its toast",
             "📎 Nothing attached · another import running · attach "
             "again after its toast"])
        self.assertEqual(self.said, [])
        # neither run even read the selection or made a temp dir
        self.assertEqual(self.calls, [])
        self.assertEqual(self.touched, [])
        self.assertEqual(self._snapshots(), [])

    def test_the_lock_is_given_back(self):
        self._export(_incomplete(*WAITING))
        for _ in range(2):
            self.assertIs(xact.session_photos("LB1", ""), False)
            xact.photo_attach("P", "T")
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.now, [])
        self.assertEqual(self._snapshots(), [])
        f = xact._photos_lock()
        self.assertIsNotNone(f)
        self.assertIsNone(xact._photos_lock())   # held by f
        f.close()

    def test_no_run_dir_never_blocks(self):
        xact.run_path = lambda name: os.path.join(self.tmp, "nope", name)
        f = xact._photos_lock()
        self.assertIsNotNone(f)
        f.close()


class TempDir(Base):
    """The snapshot dir dies with the run, except while Eagle may
    still be copying out of it."""

    def _eagle_up_to_add(self):
        xact._eagle_ensure_logbook_folder = lambda lb: "FID"
        eagle.ensure_library = lambda lib: None
        eagle.folder_node = lambda fid: {"children": [
            {"id": "SUB", "name": "04 Sessions"}]}
        eagle.items_in_folder = lambda fid: []
        self._more = [(eagle, n, getattr(eagle, n))
                      for n in ("list_item_names", "next_index")]
        self._more.append((crm_records, "current_snum",
                           crm_records.current_snum))
        eagle.list_item_names = lambda fid: []
        eagle.next_index = lambda names, base, label: 1
        crm_records.current_snum = lambda content, tid: 1
        self.addCleanup(lambda: [setattr(o, n, v)
                                 for o, n, v in self._more])

    def test_trouble_in_photos_leaves_no_dir(self):
        self._export(_incomplete(*WAITING))
        xact.session_photos("LB1", "")
        xact.photo_attach("P", "T")
        self.assertEqual(self._snapshots(), [])

    def test_eagle_trouble_before_the_handover_leaves_no_dir(self):
        self._export("one shot")

        def down(lb):
            raise eagle.EagleError("T9 drive not mounted")
        xact._eagle_ensure_logbook_folder = down
        self.assertIs(xact.session_photos("LB1", ""), False)
        self.assertEqual(self.said, ["📸 Eagle trouble: T9 drive not "
                                     "mounted · shots safe in Photos"])
        self.assertEqual(self._snapshots(), [])

    def test_eagle_still_copying_keeps_the_dir(self):
        self._export("one shot")
        self._eagle_up_to_add()
        handed = []
        eagle.add_items = lambda specs, folder_id=None: (
            handed.extend(specs) or ["I1"])

        def slow(ids):
            raise eagle.EagleError("Eagle did not finish copying")
        eagle.wait_imported = slow
        self.assertIs(xact.session_photos("LB1", ""), False)
        self.assertEqual(self.said, ["📸 Eagle trouble: Eagle did not "
                                     "finish copying · shots safe in Photos"])
        self.assertEqual(len(handed), 1)
        self.assertEqual(self._snapshots(), [os.path.basename(self.dest)])
        self.assertTrue(os.path.isfile(handed[0]["path"]))
        # and the lock came back all the same
        f = xact._photos_lock()
        self.assertIsNotNone(f)
        f.close()

    def test_a_kept_dir_is_swept_by_a_later_import(self):
        old = os.path.join(tempfile.tempdir, "tickal_tph_oldoldol")
        os.makedirs(os.path.join(old, "c1"))
        at = __import__("time").time() - 2 * pb.STALE
        os.utime(old, (at, at))
        self._export(_incomplete(*WAITING))
        xact.session_photos("LB1", "")
        self.assertEqual(self._snapshots(), [])


class PhotoAttach(Base):
    def test_a_closed_photos_is_not_launched(self):
        pb.photos_running = lambda: False
        self._osascript("", "")
        xact.photo_attach("P", "T")
        self.assertEqual(self.said,
                         ["📎 Photos is not running · open it · select · ♥"])
        self.assertEqual(self.scripts, [])
        self.assertEqual(self._snapshots(), [])

    def test_fetches_the_hearts_only(self):
        self._export(pb.PhotosError("no ♥ in selection"))
        xact.photo_attach("P", "T")
        self.assertEqual(self.said, ["📎 no ♥ in selection"])
        self.assertIs(self.calls[0]["only"], xact._hero_items)
        self.assertIs(self.calls[0]["notice"], xact._photos_wait_banner)
        self.assertEqual(self.touched, [])

    def test_timeout_words_the_attach_road(self):
        self._export(_incomplete("1 of 1 still in iCloud",
                                 "60 MB · IMG_6.DNG · Photos keeps "
                                 "downloading"))
        xact.photo_attach("P", "T")
        self.assertEqual(
            self.said,
            ["📎 Nothing attached · 1 of 1 still in iCloud · attach again "
             "in a few min · 60 MB · IMG_6.DNG · Photos keeps "
             "downloading"])
        self.assertEqual(self.touched, [])

    def test_only_the_heart_is_asked_of_photos(self):
        # the real bridge: three cloud-only shots, one ♥ - Photos is
        # asked for that one alone
        self._osascript(
            f"1\t{UA}/L0/001\tfalse\tIMG_1.DNG\n"
            f"2\t{UB}/L0/001\ttrue\tIMG_2.JPG\n"
            f"3\t{UA[:-1]}C/L0/001\tfalse\tIMG_3.MOV\n",
            "25:200: execution error: Photos got an error: AppleEvent "
            "timed out. (-1712)")
        xact.photo_attach("P", "T")
        exports = [s for s in self.scripts if "export {" in s]
        self.assertEqual(len(exports), 1)
        self.assertIn(UB, exports[0])
        self.assertNotIn(UA, exports[0])
        self.assertEqual(self.now, ["📸 1 from iCloud · downloading"])
        self.assertEqual(
            self.said,
            ["📎 Nothing attached · 1 of 1 still in iCloud · attach again "
             "in a few min · IMG_2.JPG · Photos keeps downloading"])
        self.assertEqual(self.touched, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
