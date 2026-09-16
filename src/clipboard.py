"""Read the macOS clipboard (no extra deps): an image, or plain text.

Shared by Scripts/attach_image.py (⌘ Actions → 🖼️ Add image on an existing task),
src/dispatch.py (the / add-flow "🖼️ Add image", which attaches to the task it
just created) and the CRM photo road (xact.py session_photos - the Session
done / past-session clipboard catch). Uses pyobjc's AppKit, already present in
the workflow runtime.

What counts as a clipboard image (2026-09-09, the silent miss died):
- raster data: public.png, public.tiff, public.jpeg (a screenshot, a copied
  image from a browser or Preview)
- a FILE URL to an image file (Finder ⌘C, a Photos drag): image_file() gives
  the path so the ORIGINAL rides on (HEIC / RAW stay whole for Eagle;
  xact._attach_file_to sips-renders the TickTick hero); png_bytes() still
  decodes it for the plain attach roads.
"""
import os

_RASTER = ("public.png", "public.tiff", "public.jpeg")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff",
              ".gif", ".webp", ".bmp", ".dng", ".raw")


def _pasteboard():
    try:
        from AppKit import NSPasteboard
        return NSPasteboard.generalPasteboard()
    except Exception:
        return None


# Flavors a copied LINK can arrive in. NOT the legacy "Apple URL pasteboard
# type": that one is a plist ARRAY of [url, title], so reading it as a string
# hands back 289 bytes of XML whose only URL is Apple's DTD - a copied file
# would have linked the task to apple.com (caught in review, 2026-09-16).
_URL_FLAVORS = ("public.url", "public.file-url")


def text():
    """The clipboard as plain TEXT, or "" when it holds none. Never raises.

    `pbpaste`, not AppKit: the add bar reads the clipboard on every keystroke
    and a script filter is a FRESH process each time, so the AppKit import is
    always cold. Measured 2026-09-16 on python3.13, five cold runs each:
    ~10 ms to fork pbpaste, ~95 ms to import AppKit and read.
    """
    try:
        import subprocess
        r = subprocess.run(["pbpaste"], capture_output=True, timeout=5)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def url():
    """The clipboard's URL flavor, or "". The half pbpaste cannot see.

    Validated, never trusted: a pasteboard flavor is whatever the copying app
    wrote there, so anything that is not a plain URL is dropped rather than
    passed on to be linked.
    """
    pb = _pasteboard()
    if pb is None:
        return ""
    import mdtext
    for flavor in _URL_FLAVORS:
        try:
            raw = (pb.stringForType_(flavor) or "")
        except Exception:
            continue
        raw = str(raw).strip()
        if raw and mdtext.find_url(raw) == raw:
            return raw
    return ""


def link_source():
    """What a 🔗 road should read the clipboard as.

    Text first - a copied URL, and a copied markdown link, are both text, and
    that rung costs a tenth of the other one. But a link copied out of a
    native app arrives with its href in the URL flavor ALONE (verified
    2026-09-16 on a real Crouton copy: pbpaste and every `pbpaste -Prefer`
    came back empty while public.url held crouton://viewRecipe?id=…), and a
    link copied off a web page arrives with the page TITLE in the text flavor
    and the href beside it. So when the text carries no URL, the URL flavor
    answers.
    """
    import mdtext
    t = text()
    if mdtext.find_url(t):
        return t
    return url() or t


def image_file():
    """POSIX path of the image FILE the clipboard points at (a copied file,
    not pixels), or None. Cheap: one string read + an isfile."""
    pb = _pasteboard()
    if pb is None:
        return None
    try:
        if "public.file-url" not in (pb.types() or []):
            return None
        raw = pb.stringForType_("public.file-url")
        if not raw:
            return None
        from AppKit import NSURL
        url = NSURL.URLWithString_(str(raw))
        path = str(url.path()) if url and url.path() else ""
    except Exception:
        return None
    if (path and os.path.isfile(path)
            and os.path.splitext(path)[1].lower() in IMAGE_EXTS):
        return path
    return None


def has_image():
    """True if the clipboard holds an image - a cheap type check (no decode),
    so it's safe to call on every keystroke from the add-task preview."""
    pb = _pasteboard()
    if pb is None:
        return False
    try:
        types = pb.types() or []
    except Exception:
        return False
    if any(t in types for t in _RASTER):
        return True
    return image_file() is not None


def _to_png(data):
    """Any ImageIO-decodable bytes (TIFF, JPEG, HEIC, …) → PNG bytes, or
    None when the codec is missing (a RAW without a preview)."""
    try:
        from AppKit import NSBitmapImageRep
        rep = NSBitmapImageRep.imageRepWithData_(data)
        if rep is None:
            return None
        png = rep.representationUsingType_properties_(4, None)  # 4 = NSPNGFileType
        return bytes(png) if png else None
    except Exception:
        return None


def png_bytes():
    """Return the clipboard image as PNG bytes, or None if there's no image.
    Raster data first (png as-is, tiff/jpeg re-encoded), then a copied
    image file (decoded - the original stays where it is)."""
    pb = _pasteboard()
    if pb is None:
        return None
    try:
        data = pb.dataForType_("public.png")
        if data:
            return bytes(data)
        for t in ("public.tiff", "public.jpeg"):
            data = pb.dataForType_(t)
            if data:
                png = _to_png(data)
                if png:
                    return png
    except Exception:
        pass
    path = image_file()
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if path.lower().endswith(".png"):
        return raw
    return _to_png(raw)
