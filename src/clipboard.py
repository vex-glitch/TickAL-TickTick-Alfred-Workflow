"""Read an image off the macOS clipboard as PNG bytes (no extra deps).

Shared by Scripts/attach_image.py (⌘ Actions → 🖼️ Add image on an existing task)
and src/dispatch.py (the / add-flow "🖼️ Add image", which attaches to the task it
just created). Uses pyobjc's AppKit, already present in the workflow runtime.
"""


def has_image():
    """True if the clipboard holds an image — a cheap type check (no decode), so
    it's safe to call on every keystroke from the add-task preview."""
    try:
        from AppKit import NSPasteboard
    except Exception:
        return False
    types = NSPasteboard.generalPasteboard().types() or []
    return ("public.png" in types) or ("public.tiff" in types)


def png_bytes():
    """Return the clipboard image as PNG bytes, or None if there's no image."""
    try:
        from AppKit import NSPasteboard
    except Exception:
        return None
    pb = NSPasteboard.generalPasteboard()
    data = pb.dataForType_("public.png")
    if data:
        return bytes(data)
    tiff = pb.dataForType_("public.tiff")
    if tiff:
        try:
            from AppKit import NSBitmapImageRep
            rep = NSBitmapImageRep.imageRepWithData_(tiff)
            png = rep.representationUsingType_properties_(4, None)  # 4 = NSPNGFileType
            return bytes(png)
        except Exception:
            return None
    return None
