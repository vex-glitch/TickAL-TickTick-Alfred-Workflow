"""Read an image off the macOS clipboard (no extra deps).

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
