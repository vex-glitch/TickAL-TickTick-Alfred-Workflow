"""Photos.app bridge - AppleScript channel (probe-verified 2026-07-25).

Contracts that shaped this module:
- AS object refs DIE with the osascript process → every operation is a
  ONE-SHOT script; later runs re-address items by `media item id "X"`
  (direct reference, no whose-scan).
- Selection survives Photos being in the background - reading it does
  not need Photos frontmost.
- `export ... with using originals` yields the true originals (HEIC,
  metadata intact). LIVE PHOTOS export as an HEIC+MOV PAIR: the .MOV
  sidecar is skipped (primary = the image; a real video item exports
  just its .MOV and IS the primary). Each item exports into its own
  numbered subdir so item→file mapping is exact even when two items
  share a filename.
- Deleting photos is NOT scriptable (no AS verb). Stage 1 files
  imported shots into the "✅ In Eagle" album instead; Vex purges it
  manually. (Stage 2 someday: PhotoKit delete via PyObjC.)
- Automation permission: first run pops the macOS dialog; a -1743
  error means it was denied → System Settings → Privacy → Automation.
"""

import os
import subprocess

ALBUM = "✅ In Eagle"


class PhotosError(Exception):
    """Toast-ready message; callers fail closed."""


def _esc(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _run(script, timeout=300):
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PhotosError("Photos took too long (big videos still "
                          "downloading from iCloud?)")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "-1743" in err:
            raise PhotosError("Photos automation not allowed - System "
                              "Settings → Privacy & Security → Automation")
        raise PhotosError(f"Photos scripting failed: {err[:160]}")
    return r.stdout


def selection_snapshot_export(dest_dir, timeout=600):
    """Export the CURRENT Photos selection as originals.

    Returns [{'id', 'filename', 'favorite', 'path'}] in selection order,
    path = the exported primary file (Live-Photo .MOV sidecars skipped).
    Raises PhotosError on empty selection - honest, never guesses."""
    os.makedirs(dest_dir, exist_ok=True)
    # Metadata line = counter TAB id TAB favorite TAB filename: the
    # counter (not enumerate) keys the subdir so a dropped line can
    # never shift the item→file mapping, and filename sits LAST so a
    # tab inside it survives the split (review find 2026-07-25).
    script = f'''
set outRoot to "{_esc(dest_dir)}"
set out to ""
tell application "Photos"
    set sel to selection
    if (count of sel) is 0 then error "EMPTY_SELECTION"
    set i to 0
    repeat with mi in sel
        set i to i + 1
        set sub to outRoot & "/" & i
        do shell script "mkdir -p " & quoted form of sub
        export {{contents of mi}} to (POSIX file sub) with using originals
        set out to out & i & tab & (id of mi) & tab & (favorite of mi) & \
tab & (filename of mi) & linefeed
    end repeat
end tell
return out'''
    try:
        raw = _run(script, timeout=timeout)
    except PhotosError as e:
        if "EMPTY_SELECTION" in str(e):
            raise PhotosError("nothing selected in Photos")
        raise
    items, bad = [], 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) != 4 or not parts[0].strip().isdigit():
            bad += 1
            continue
        idx, mid, fav, fname = parts
        sub = os.path.join(dest_dir, idx.strip())
        items.append({"id": mid, "filename": fname.strip(),
                      "favorite": fav.strip().lower() == "true",
                      "path": _primary_file(sub)})
    if bad:
        # fail CLOSED: an unmapped item means a possible wrong-file
        # import - never guess
        raise PhotosError(f"{bad} selected items had unparseable names")
    good = [it for it in items if it["path"]]
    if not good:
        raise PhotosError("export produced no files")
    return good


def _primary_file(subdir):
    """The exported file that counts: the image half of a Live-Photo
    pair, or the lone file. None when the export left nothing."""
    try:
        files = sorted(f for f in os.listdir(subdir) if not f.startswith("."))
    except OSError:
        return None
    if not files:
        return None
    stills = [f for f in files
              if not f.lower().endswith((".mov", ".mp4", ".m4v"))]
    pick = stills[0] if stills else files[0]
    return os.path.join(subdir, pick)


def file_to_album(media_ids, album=ALBUM):
    """Add items (by Photos id) to the album, creating it if missing.
    Called only AFTER the Eagle import verified - the album means
    'safely in Eagle', it must never lie."""
    if not media_ids:
        return
    refs = ", ".join(f'media item id "{_esc(m)}"' for m in media_ids)
    _run(f'''
tell application "Photos"
    if not (exists album "{_esc(album)}") then
        make new album named "{_esc(album)}"
    end if
    add {{{refs}}} to album "{_esc(album)}"
end tell''')


def export_by_id(media_id, dest_dir, timeout=300):
    """Export ONE item by id (the ♥ hero for a TickTick attach).
    Returns the exported primary file path."""
    os.makedirs(dest_dir, exist_ok=True)
    _run(f'''
tell application "Photos"
    export {{media item id "{_esc(media_id)}"}} to \
(POSIX file "{_esc(dest_dir)}") with using originals
end tell''', timeout=timeout)
    return _primary_file(dest_dir)


def photos_running():
    """True when Photos.app is up. Surfaces check this BEFORE
    selection_count - an AS call would otherwise LAUNCH Photos as a
    render side effect."""
    try:
        return subprocess.run(["pgrep", "-x", "Photos"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def selection_count():
    """Cheap peek for surfaces that want to show '3 selected'. 0 on any
    scripting trouble - display only, never a gate."""
    if not photos_running():
        return 0
    try:
        return int(_run('tell application "Photos" to count of selection',
                        timeout=30).strip() or "0")
    except (PhotosError, ValueError):
        return 0


def photokit_delete(ids):
    """Move media items to Photos' Recently Deleted via PhotoKit -
    AppleScript has NO delete (probed; parked stage 2, unparked on
    Vex's ask 2026-07-26). macOS ALWAYS shows its own 'Delete N
    photos?' confirm - one click per run, Apple's design, cancel =
    honest keep. First run prompts for Photos-library access
    (attributed to Alfred). Returns (n_deleted, "") or (0, reason) -
    never raises; the '✅ In Eagle' album stays the manual-purge
    fallback whenever this skips. Recently Deleted keeps 30 days."""
    def _log(msg):
        try:
            import datetime
            with open("/tmp/tickal_photokit.log", "a") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
        except OSError:
            pass

    if not ids:
        return 0, "nothing to delete"
    try:
        import Photos
    except ImportError:
        _log("Photos framework missing")
        return 0, "PyObjC Photos framework missing"
    try:
        st = Photos.PHPhotoLibrary.authorizationStatus()
        _log(f"auth status pre: {st}")
        if st == 0:                       # notDetermined - block on ask,
            import threading              # PUMPING the runloop (a headless
            import time as _t             # wait can starve the callback)
            from Foundation import NSRunLoop, NSDate
            ev = threading.Event()
            got = {}

            def _cb(s):
                got["s"] = s
                ev.set()
            Photos.PHPhotoLibrary.requestAuthorization_(_cb)
            end = _t.time() + 120
            while not ev.is_set() and _t.time() < end:
                NSRunLoop.currentRunLoop().runMode_beforeDate_(
                    "kCFRunLoopDefaultMode",
                    NSDate.dateWithTimeIntervalSinceNow_(0.2))
            st = got.get("s", 0)
            _log(f"auth status post-request: {st}")
        if st not in (3, 4):              # authorized · limited
            return 0, "Photos access not granted (Privacy settings)"
        assets = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_(
            list(ids), None)
        _log(f"fetched {assets.count()} of {len(ids)} ids")
        if assets.count() == 0:
            return 0, "no matching assets"

        def _change():
            Photos.PHAssetChangeRequest.deleteAssets_(assets)
        ok, err = Photos.PHPhotoLibrary.sharedPhotoLibrary() \
            .performChangesAndWait_error_(_change, None)
        _log(f"performChanges ok={ok} err={err}")
        if not ok:
            return 0, "cancelled" if err is None else f"refused: {err}"
        return assets.count(), ""
    except Exception as e:
        _log(f"EXC {type(e).__name__}: {e}")
        return 0, f"{type(e).__name__}: {e}"
