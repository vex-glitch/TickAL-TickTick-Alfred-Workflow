#!/usr/bin/env python3
"""
gridfeed.py - feeds the 🖼 Grid View (canvas phase_grid).

Road: folder-screen row ⏎ arg "xact:peek:<b64>" → xact img_peek fires
ET GridPeek (osascript trampoline - fresh session, row variables DROP)
→ this script (argv = the b64 payload) → Grid View. The payload is
b64 JSON {"fid","sess","lib","lb","ret"}; the output is the Alfred
envelope {"alfredworkflow": {"arg": <grid items JSON>, "variables":
{lb_tid, peek_lib, peek_ret}}} - the variables RE-SEED the session so
the grid's chord edges can ride {var:lb_tid}/{var:peek_ret} and the
xact img verbs read lb_tid from env.

Reads the library straight from DISK (eagle.py disk readers - closed
libraries read fine, no switch just to LOOK). Item icon = Eagle's own
*_thumbnail.png beside the file when present (never the multi-MB
original when a thumb exists - the grid stays snappy); arg = the media
file's absolute path (item id stays parseable - xact._img_id_lib).

Chords on a grid shot land on canvas edges (phase_grid), NOT here:
⏎ open in Eagle · ⌘ Edit this · ⇧ → To post · ⌥⌘ copy link ·
⌘⇧ stage picker · ⌥⇧ 📎 attach · ⌃⇧ 🗑 trash · ⌃ back.
"""
import sys
import os
import json
import re
import base64

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}",
                                 "valid": False}]}))
    sys.exit(0)


def _rows(fid, sess, lib):
    import eagle
    lib_path = eagle.LIBS.get(lib, eagle.LIBS["crm"])[1]
    _root, ids_all = eagle.disk_subtree_ids(lib_path, fid)
    items = eagle.disk_items_in(lib_path, ids_all)
    m = re.match(r"^s(\d+)$", sess or "")
    if m:
        k = int(m.group(1))
        if k:
            items = [i for i in items if f"• S{k} •" in (i.get("name") or "")]
        else:
            # the "unnumbered" bucket - shots without any S-token
            items = [i for i in items
                     if not re.search(r"• S\d+ •", i.get("name") or "")]
    items = sorted({i["id"]: i for i in items}.values(),
                   key=lambda i: (i.get("name") or "").lower())
    rows = []
    for it in items:
        p = it.get("path") or ""
        thumb = os.path.splitext(p)[0] + "_thumbnail.png"
        rows.append({"uid": it["id"], "title": it.get("name") or "?",
                     "subtitle": os.path.splitext(p)[1].lstrip(".").upper(),
                     "arg": p, "match": it.get("name") or "",
                     "icon": {"path": thumb if os.path.exists(thumb) else p}})
    if not rows:
        rows = [{"title": "Empty folder",
                 "subtitle": "Nothing filed here yet", "valid": False}]
    return rows


def main():
    raw = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    ctx = {}
    try:
        ctx = json.loads(base64.b64decode(raw).decode())
    except Exception:
        pass
    fid = ctx.get("fid") or ""
    lib = ctx.get("lib") or "crm"
    try:
        rows = _rows(fid, ctx.get("sess") or "", lib)
    except Exception as e:
        rows = [{"title": f"🦅 {type(e).__name__}: {e}",
                 "subtitle": "T9 plugged in?", "valid": False}]
    print(json.dumps({"alfredworkflow": {
        "arg": json.dumps({"items": rows}),
        "variables": {"lb_tid": ctx.get("lb") or "",
                      "peek_lib": lib,
                      "peek_ret": ctx.get("ret") or "ctx:clbs"}}}))


if __name__ == "__main__":
    main()
