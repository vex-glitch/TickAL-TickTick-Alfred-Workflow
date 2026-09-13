#!/usr/bin/env python3
"""
focus_bar.py - the floating focus pill. PyObjC, ships in the workflow.

A Slash-style always-on-top capsule showing the running session:
  Row 1  ● done · task title (→ open in TickTick) · clock · ⏸/▶ · ⏹ · 🗒 · ⌄
  Row 2  ○ tick (→ confetti, completes the subtask) · first open subtask · 2/5
Unattributed sessions show just the clock + controls; no subtasks → 1 row.

DUMB RENDERER: every mutation exits through an xact verb -
  channel A (direct subprocess, pure API):  focus_pause/resume · fx_tick
  channel B (Alfred ET "XAct", AX + toast): sticky · pomo_toggle/abandon ·
                                            focus_stop · focus_done
Reads: ~/.ticktick_alfred/run/tickal_focus.json · ~/.ticktick_alfred/run/tickal_pomo.json · ~/.ticktick_alfred/run/tickal_focus_bar.json
(xact only touches `visible` in the bar file; the bar owns origin), TickTick's
pomo defaults keys, and ONE LIVE api.get_project_data for the subtask list
(server truth: open children + the parent's childIds, done included).

Polling: 1 s UI clock (timestamps only) · 1 s state files (defaults read every
2nd tick) · content 5 s → 20 s backoff after 10 min without change (rate
budget: the Open API allows 300 req/5 min shared with cachesync). v1 note:
state files are polled, not kqueue-watched - worst-case 1 s show/hide latency,
far fewer moving parts.

Lifecycle: spawned detached by xact (focus_start/pomo/fx_link/bar_show);
flock singleton on ~/.ticktick_alfred/run/tickal_focus_bar.lock; exits after 10 s of idle;
SIGTERM persists position first. stderr → /tmp/tickal_focus_bar.log.
Run `focus_bar.py --probe` to print the model JSON headlessly (test hook).
"""
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

WF_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WF_DIR, "src"))
sys.path.insert(0, os.path.join(WF_DIR, "Scripts"))

import focus_subtasks as fsub       # noqa: E402  (pure)
import xact                          # noqa: E402  (state readers + verb host)
import config as cfg                 # noqa: E402
from script_base import run_path  # noqa: E402
try:
    from display import md_links_display as _disp   # noqa: E402  ([name]🔗)
except Exception:
    def _disp(s):
        return s

FOCUS_FILE = run_path("tickal_focus.json")
POMO_FILE = run_path("tickal_pomo.json")
BAR_STATE = run_path("tickal_focus_bar.json")
BAR_LOCK = run_path("tickal_focus_bar.lock")
PY = sys.executable   # the bar's own python runs xact fine (xact needs no PyObjC)
XACT = os.path.join(WF_DIR, "Scripts", "xact.py")

W = 620          # initial only - width is dynamic per relayout
ROW1_H = 50
ROW2_H = 34
CHK_H  = 25      # expanded subtask rows pack tight (28 → 25, Vex 2026-09-10)
SUB_H  = 23      # nested (sub-subtask) rows sit a little tighter
PAD_V  = 10      # breathing room above the first and below the last row (zoomed; 6 → 10)
CLOCK_PT  = 18   # header clock digits (23 → 18, Vex 2026-09-10: prominent, not huge)
CLOCK_GAP = 2    # clock → first icon (was 18, then 6; halved again, Vex 2026-09-10)
ICON_BOX  = 20   # header icon boxes, edge to edge (were 26-29 px: the gaps halved)
CLOCK_DY  = -0.75  # optical nudge for the clock digits (+ = up), measured on a 2x capture
RADIUS = 20.0
IDLE_EXIT_S = 10
# Drifting smoke inside the body (Vex 2026-09-10, the smoke workflow:
# drifting-smoke won 3 of 3 judges). Assets baked ONCE by
# tools/focus_smoke_bake.py - SMOKE_SLICE / SMOKE_SIDE / SMOKE_TILE must
# match its SLICE / SIDE / TILE_PT.
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SMOKE_SLICE, SMOKE_SIDE = 54.0, 110.0   # mask 9-slice: fixed corner patch, mask square (pt)
SMOKE_TILE = 384.0      # grid A period (pt); grid B = SMOKE_B x, mirrored
SMOKE_B = 1.4
SMOKE_LOOP = 75.0       # s for grid A to rise one period (~5 pt/s: felt, not watched)
SMOKE_B_SPEED = 0.6     # grid B drifts sideways at 0.6x A's speed: the layers shear
SMOKE_OPACITY = (0.50, 0.36)   # grid A, grid B
SMOKE_ALPHA = 0.90      # the whole smoke container (short bodies go lower). 0.72 (the
                        # judges' pick) measured a bottom-band green lift of 22 live:
                        # a faint vignette, not smoke. 0.9 keeps the rim >= 2.4x brighter
SMOKE_MOTION = True     # False = a still frame (SMOKE_STILL_T), same look
SMOKE_STILL_T = 25.0


# ── model (pure - probe-testable) ────────────────────────────────────────────
def read_state():
    """One snapshot of the session world (no AppKit)."""
    m = {"kind": "idle", "attributed": False, "pid": "", "tid": "",
         "title": "", "paused": False, "visible": True, "focus_st": None,
         "pomo_remaining": 0, "place_at": None}
    try:
        with open(BAR_STATE) as f:
            bs = json.load(f)
        m["visible"] = bool(bs.get("visible", True))
        m["place_at"] = bs.get("place_at")      # link.py TICKAL_BAR_AT one-shot
    except (OSError, ValueError, AttributeError):
        pass
    st = xact._focus_state()
    if st:
        m.update(kind="timer", focus_st=st, paused=bool(st.get("paused_at")),
                 attributed=bool(st.get("tid")), pid=st.get("pid", ""),
                 tid=st.get("tid", ""), title=st.get("title", ""))
        return m
    state, remaining = xact._pomo_app_state()
    if state != "idle":
        m.update(kind="pomo", pomo_remaining=remaining,
                 paused=state.startswith("pomodoroPaused"))
        ps = xact._pomo_sidecar()
        if ps and ps.get("tid"):
            m.update(attributed=True, pid=ps.get("pid", ""),
                     tid=ps["tid"], title=ps.get("title", ""))
        return m
    return m


def fmt_timer(secs):
    """mm:ss under an hour, h:mm:ss beyond."""
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    mn, s = divmod(rem, 60)
    return f"{h}:{mn:02d}:{s:02d}" if h else f"{mn:02d}:{s:02d}"


def fmt_pomo(secs):
    secs = max(0, int(secs))
    return f"{secs // 60}:{secs % 60:02d}"


if "--probe" in sys.argv:
    print(json.dumps(read_state(), default=str))
    sys.exit(0)


# ── singleton ────────────────────────────────────────────────────────────────
# open WITHOUT truncating, lock, THEN rewrite: a racing twin (two _bar_wake
# spawns in the same second) used to blank the winner's pid on its way out
_lock_f = os.fdopen(os.open(BAR_LOCK, os.O_RDWR | os.O_CREAT, 0o644), "r+")
try:
    fcntl.flock(_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)          # another bar already runs - correct outcome
_lock_f.seek(0)
_lock_f.truncate()
_lock_f.write(str(os.getpid()))
_lock_f.flush()


# ── AppKit ───────────────────────────────────────────────────────────────────
# Guarded: a python without PyObjC exits clean (code 3, one stderr line) -
# xact._bar_python() gates the spawn, but a stale spawn or a manual run must
# not traceback into the logfile.
try:
    import objc                          # noqa: E402
    from AppKit import (                 # noqa: E402
        NSApplication, NSApplicationActivationPolicyAccessory, NSPanel,
        NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, NSStatusWindowLevel, NSColor, NSFont,
        NSTextField, NSButton, NSImage, NSVisualEffectView, NSAppearance,
        NSAppearanceNameDarkAqua, NSMakeRect, NSMakeSize, NSBezierPath,
        NSScreen, NSTimer, NSObject, NSWorkspace,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorIgnoresCycle,
        NSVisualEffectMaterialHUDWindow, NSVisualEffectBlendingModeBehindWindow,
        NSVisualEffectStateActive, NSEdgeInsetsMake, NSImageResizingModeStretch,
        NSFontWeightSemibold, NSFontWeightBold, NSLineBreakByTruncatingTail,
        NSTextAlignmentLeft, NSTextAlignmentRight, NSWindowStyleMaskResizable,
        NSImageView, NSCursor, NSEvent,
    )
    from AppKit import NSView            # noqa: E402
    from Foundation import NSRunLoop, NSRunLoopCommonModes   # noqa: E402
    from Quartz import (                 # noqa: E402
        CAEmitterLayer, CAEmitterCell, CACurrentMediaTime, kCAEmitterLayerPoint,
        CALayer, CATransaction, CAGradientLayer, CAKeyframeAnimation,
        CAReplicatorLayer, CABasicAnimation, CAMediaTimingFunction,
        CATransform3DMakeTranslation, CATransform3DMakeScale,
        kCAMediaTimingFunctionLinear,
    )
    from PyObjCTools import AppHelper    # noqa: E402
except ImportError as e:
    sys.stderr.write(f"focus_bar: PyObjC missing ({e}) · pip3 install pyobjc\n")
    sys.exit(3)


def _log(msg):
    sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


def _saved_size():
    """The user's last drag/Moom size (w, h) from the bar file, each axis
    validated ON ITS OWN (a width set while collapsed has no height - the
    old all-or-nothing check threw the width away too); None = the bar
    sizes that axis itself."""
    try:
        with open(BAR_STATE) as f:
            raw = json.load(f).get("size") or [None, None]
        w, h = (list(raw) + [None, None])[:2]
    except (OSError, ValueError, TypeError):
        return None, None

    def ok(v, lo):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= 4000 else None
    return ok(w, 300), ok(h, ROW1_H)


class NonActivatingPanel(NSPanel):
    def canBecomeKeyWindow(self):        # NEVER steal key focus
        return False

    def canBecomeMainWindow(self):
        return False

    def scrollWheel_(self, event):
        # >MAX_ROWS subtasks scroll - labels/buttons don't consume
        # wheel events, so they bubble here
        bar = getattr(self, "_bar", None)
        if bar is not None:
            bar.onScroll_(event)

    def magnifyWithEvent_(self, event):
        # trackpad pinch over the bar = zoom the task rows
        bar = getattr(self, "_bar", None)
        if bar is not None:
            bar.on_magnify(event)


class PillButton(NSButton):
    def acceptsFirstMouse_(self, event):  # act on the first click
        return True


def _saved_zooms():
    """{monitor name: zoom} from the bar file - each monitor keeps its own
    ⌘+/⌘− level (Vex 2026-09-10: perfect on the main screen, barely
    readable on the secondary one)."""
    try:
        with open(BAR_STATE) as f:
            raw = json.load(f).get("zoom") or {}
        return {str(k): float(v) for k, v in raw.items()
                if ZOOM_MIN <= float(v) <= ZOOM_MAX}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


FOLD_MAX = 200          # folded tids kept in the bar file (a routine has ~10)


def _saved_folded():
    """The tids folded shut, from the bar file - a fold outlives the bar
    (spawned fresh per session) and a switch to another task and back."""
    try:
        with open(BAR_STATE) as f:
            raw = json.load(f).get("folded") or []
        return [str(t) for t in raw if t][:FOLD_MAX]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def _fourcc(s):
    return int.from_bytes(s.encode("mac_roman"), "big")


class _HoverHotkeys:
    """⌘+ / ⌘− / ⌘0 zoom the bar ONLY while the pointer is over it. The
    panel never takes keyboard focus (by design: ticking a box must not
    pull you out of your app), so no ordinary key binding can reach it -
    Carbon hotkeys armed on mouse-enter and dropped on mouse-exit can, and
    ⌘+ keeps zooming every other app everywhere else. No permissions
    needed. on_key(direction) gets +1 / -1 / 0 (reset)."""
    # (virtual key code, modifiers, direction) - U.S. positions; cmd = 256
    KEYS = ((24, 256, 1), (24, 256 | 512, 1), (69, 256, 1),    # ⌘= ⇧⌘= ⌘keypad+
            (27, 256, -1), (78, 256, -1),                       # ⌘- ⌘keypad-
            (29, 256, 0))                                       # ⌘0

    def __init__(self, on_key):
        import ctypes
        self.ct = ctypes
        c = self.c = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/Carbon.framework/Carbon")
        self.on_key = on_key
        self.refs = []

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]
        self.HKID = EventHotKeyID
        Proc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p)
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p]
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, Proc, ctypes.c_uint32,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]

        def handler(_next, event, _user):
            hk = EventHotKeyID()
            c.GetEventParameter(event, _fourcc("----"), _fourcc("hkid"), None,
                                ctypes.sizeof(hk), None, ctypes.byref(hk))
            try:
                self.on_key(self.KEYS[hk.id][2])
            except Exception as e:
                _log(f"hotkey: {e}")
            return 0
        self._proc = Proc(handler)        # keep a reference: ctypes won't
        self.target = c.GetApplicationEventTarget()
        spec = EventTypeSpec(_fourcc("keyb"), 5)       # kEventHotKeyPressed
        self._href = ctypes.c_void_p()
        c.InstallEventHandler(self.target, self._proc, 1, ctypes.byref(spec),
                              None, ctypes.byref(self._href))

    def arm(self):
        if self.refs:
            return
        for n, (code, mods, _d) in enumerate(self.KEYS):
            ref = self.ct.c_void_p()
            if self.c.RegisterEventHotKey(code, mods, self.HKID(_fourcc("TkAL"), n),
                                          self.target, 0, self.ct.byref(ref)) == 0:
                self.refs.append(ref)
        if len(self.refs) < len(self.KEYS):     # another app owns a chord
            _log(f"hover hotkeys: {len(self.refs)}/{len(self.KEYS)} armed")

    def disarm(self):
        for ref in self.refs:
            self.c.UnregisterEventHotKey(ref)
        self.refs = []


class GripView(NSImageView):
    """A row's drag handle (≡ - replaced the ⤒↑↓⤓ arrows, Vex 2026-09-10;
    it sits in the free column LEFT of the checkboxes, not far right, since
    the right-hand grips ate title room). Press, drag, drop: straight up or
    down reorders among siblings, dragged RIGHT and rested on a row it nests
    under that row (Vex 2026-09-13). The controller does the work; the grip
    never drags the WINDOW (the panel is movable by its background)."""

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDownCanMoveWindow(self):
        return False

    def mouseDown_(self, event):
        bar = getattr(self, "_bar", None)
        if bar is not None:
            bar.grip_down(self, event)

    def mouseDragged_(self, event):
        bar = getattr(self, "_bar", None)
        if bar is not None:
            bar.grip_dragged(self, event)

    def mouseUp_(self, event):
        bar = getattr(self, "_bar", None)
        if bar is not None:
            bar.grip_up(self, event)


class PassThroughView(NSView):
    """Confetti host ABOVE the vibrancy view - sublayers added inside an
    NSVisualEffectView get vibrancy-composited into invisibility, so confetti
    drawn there never shows. Clicks pass straight through."""

    def hitTest_(self, point):
        return None


def capsule_mask(radius):
    sz = NSMakeSize(radius * 2 + 1, radius * 2 + 1)

    def draw(rect):
        NSColor.whiteColor().set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, radius, radius).fill()
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_(sz, False, draw)
    img.setCapInsets_(NSEdgeInsetsMake(radius, radius, radius, radius))
    img.setResizingMode_(NSImageResizingModeStretch)
    return img


def sym_image(name, pt=None, weight=None):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if pt and img:
        try:
            from AppKit import NSImageSymbolConfiguration
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                float(pt), weight if weight is not None else NSFontWeightSemibold)
            img = img.imageWithSymbolConfiguration_(cfg)
        except Exception:
            pass
    return img


# The glow's own green, slightly translucent - systemGreen read fluorescent
# against the HUD chrome.
GREEN = NSColor.colorWithSRGBRed_green_blue_alpha_(0.18, 0.75, 0.47, 0.95)

# Expanded list: px each nesting level below the direct child shifts its
# checkbox + title - just enough to read as nested (Vex 2026-09-10)
INDENT = 14
# drag-to-reparent (Vex 2026-09-13): past this far RIGHT of where the grip
# was pressed, the drag stops reordering and starts nesting; resting over a
# row for NEST_DWELL arms it as the new parent
NEST_DX = 26
NEST_DWELL = 0.35
TLINK_W = 22       # row 1's link icon box (row icons scale with the zoom)
TLINK_GAP = 6      # ...and the room between the title and that icon
TASK_FONT = 15     # row titles (17 → 15, Vex 2026-09-10: the task/sub gap read too big)
SUB_FONT = 14      # sub-subtask titles (13 → 14, Vex 2026-09-10: ~7% under tasks)
CIRCLE_PT = 13     # task checkbox glyph (was 15)
SQUARE_PT = 12     # sub-subtask checkbox glyph - matches the 14 pt text
# Row text: the primary label color (~85% white) - the old secondary grey
# (~55%) on the near-black chrome was the hard-to-read part
ROW_TEXT = NSColor.labelColor()


ZOOM_MIN, ZOOM_MAX = 0.7, 2.0   # ⌘+/⌘− range for the task rows, per monitor


def _row_h(it, z=1.0):
    """An expanded row's height at zoom z: nested rows sit tighter."""
    return (CHK_H if (it or {}).get("depth", 1) <= 1 else SUB_H) * z
# A user resize counts as IN PROGRESS until the frame holds still this long:
# Moom's modifier-drag is a STREAM of AX size sets with no live-resize
# bracket, and snapping each one made the bar fight Moom (it shook)
RESIZE_QUIET = 0.45


def _dot_cgimage(color, d=8):
    img = NSImage.alloc().initWithSize_(NSMakeSize(d, d))
    img.lockFocus()
    color.set()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(0, 0, d, d)).fill()
    img.unlockFocus()
    cg = img.CGImageForProposedRect_context_hints_(None, None, None)
    # PyObjC may return (CGImage, out-rect); feeding the tuple to
    # setContents_ leaves the confetti invisible.
    if isinstance(cg, tuple):
        cg = cg[0]
    return cg


class BarController(NSObject):
    # ── construction ─────────────────────────────────────────────────────
    def init(self):
        self = objc.super(BarController, self).init()
        if self is None:
            return None
        self.state = read_state()
        self.block = None               # block_summary dict
        self.expanded = True            # chevron: full subtask list - OPEN by
                                        # default + per new session (Vex 2026-09-10)
        self._self_frame = False        # our own setFrame, not a user resize
        self._user_rs_at = 0.0          # monotonic stamp of the last user resize step
        self._adopted_at = -1.0         # which step was last adopted
        self._last_H = 0.0              # the height the bar itself last showed
        self._last_rows = False         # ...and whether that layout drew rows
        self._drag = None               # a grip drag in progress (grip_down)
        self._relayout_pending = False  # a relayout deferred by that drag
        self._gap_y = []                # y of each visible row's top edge (+ the bottom)
        self._x0 = 30.0                 # the checkbox column (slides right only when a zoomed grip needs room)
        self._zooms = _saved_zooms()    # {monitor name: zoom}
        self.zoom = 1.0                 # this monitor's, applied in _build
        self._zoom_accum = 0.0          # ⌘-scroll accumulator (scroll points)
        self._pinch_accum = 0.0         # pinch accumulator (magnification) - its OWN:
                                        # a shared one let scroll leftovers slam a pinch to 200%
        self._flash_until = 0.0         # the zoom % owns the clock until then
        self._hot = None                # hover hotkeys (⌘+ / ⌘− / ⌘0)
        self.user_w, self.user_h = _saved_size()   # edge drag / Moom size
        self.folded = _saved_folded()   # tids whose subtree is folded shut
        self.row_pool = []              # lazily-built expanded item rows
        self.visible_items = []         # the filtered+scrolled window
        self.scroll_off = 0             # first visible row index
        self._scroll_accum = 0.0
        self._rmw_lock = threading.Lock()   # serialize tick/move live writes
        self.mutation_seq = 0
        self.pending_tick = None        # (tid_or_None, seq, monotonic)
        self.idle_since = None
        self.content_dirty = threading.Event()
        self.content_last_change = time.monotonic()
        self._shared_lock = threading.Lock()
        self._shared = {}
        self._pomo_anchor = (0, time.monotonic())   # (remaining, at)
        self._build()
        self._start_loops()
        return self

    def _build(self):
        rect = NSMakeRect(0, 0, W, ROW1_H)
        panel = NonActivatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            # Resizable: edge drag like any window, and an AX-settable size
            # for Moom's modifier-drag (Vex 2026-09-10)
            rect, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
            | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        panel.setLevel_(NSStatusWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setMovableByWindowBackground_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))

        # Two-tone flat chrome: no vibrancy - precise colors. Top dark gray
        # (#28282a), bottom near-black (#161617) with an inner dark-green
        # glow. Rounding via layer corners.
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, ROW1_H))
        container.setWantsLayer_(True)

        bg_top = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, ROW1_H))
        bg_top.setWantsLayer_(True)
        bg_top.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.157, 0.157, 0.166, 0.985).CGColor())
        bg_top.layer().setCornerRadius_(RADIUS)
        container.addSubview_(bg_top)

        bg_bot = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 1))
        bg_bot.setWantsLayer_(True)
        bg_bot.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.086, 0.086, 0.09, 0.985).CGColor())
        bg_bot.layer().setCornerRadius_(RADIUS)
        bg_bot.layer().setMaskedCorners_(3)      # bottom corners only
        bg_bot.layer().setMasksToBounds_(True)
        self._build_smoke(bg_bot.layer())      # under the rim, under the rows
        # the 1 px rim, drawn ABOVE the smoke at its exact colour. Its old
        # inner shadow is gone: the smoke is the glow now, and a shadow
        # under the line brightened the corners past the line itself
        glow = CALayer.layer()
        glow.setBorderWidth_(1.0)
        glow.setBorderColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.15, 0.72, 0.45, 0.4).CGColor())
        glow.setCornerRadius_(RADIUS)
        glow.setMaskedCorners_(3)
        bg_bot.layer().addSublayer_(glow)
        container.addSubview_(bg_bot)

        fx = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, ROW1_H))
        fx.setAutoresizingMask_(18)     # width+height sizable
        fx.setWantsLayer_(True)
        container.addSubview_(fx)       # controls host, transparent
        overlay = PassThroughView.alloc().initWithFrame_(NSMakeRect(0, 0, W, ROW1_H))
        overlay.setWantsLayer_(True)
        overlay.setAutoresizingMask_(18)
        container.addSubview_(overlay)   # above fx - confetti lives here
        panel.setContentView_(container)
        self.panel = panel
        panel._bar = self               # scroll-wheel backref
        self.fx = fx
        self.overlay = overlay
        self.bg_top = bg_top
        self.bg_bot = bg_bot
        self.glow = glow
        self.W = W

        def btn(sym, action, size=28, pt=15):
            b = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
            b.setBordered_(False)
            b.setTitle_("")
            b.setImage_(sym_image(sym, pt))
            b.setContentTintColor_(NSColor.secondaryLabelColor())
            b.setTarget_(self)
            b.setAction_(action)
            fx.addSubview_(b)
            return b

        def label(size, weight_bold=False, mono=False, color=None):
            l = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 18))
            l.setBezeled_(False)
            l.setDrawsBackground_(False)
            l.setEditable_(False)
            l.setSelectable_(False)
            if mono:
                l.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(size, 0))
            elif weight_bold:
                l.setFont_(NSFont.systemFontOfSize_weight_(size, NSFontWeightSemibold))
            else:
                l.setFont_(NSFont.systemFontOfSize_(size))
            l.setTextColor_(color or NSColor.labelColor())
            l.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
            fx.addSubview_(l)
            return l

        # row 1 (hover tooltips)
        self.b_done = btn("circle", "onDone:", 30, 18)
        self.b_done.setToolTip_("Complete the task · stops & logs the session")
        self.t_title = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 20))
        self.t_title.setBordered_(False)
        self.t_title.setImage_(None)
        self.t_title.setTarget_(self)
        self.t_title.setAction_("onTitle:")
        self.t_title.setFont_(NSFont.systemFontOfSize_weight_(20, NSFontWeightBold))
        self.t_title.setContentTintColor_(NSColor.colorWithWhite_alpha_(0.72, 1.0))
        self.t_title.setAlignment_(NSTextAlignmentLeft)
        self.t_title.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        self.t_title.setToolTip_("Open in TickTick")
        fx.addSubview_(self.t_title)
        # row 1's own link, when the focused title carries one. It hugs the
        # title instead of joining the right-hand run: that run is controls,
        # and the ⌄ stays the rightmost thing on the bar (Vex 2026-09-12)
        self.b_tlink = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 22, 22))
        self.b_tlink.setBordered_(False)
        self.b_tlink.setTitle_("")
        self.b_tlink.setImage_(sym_image("link", 13))
        self.b_tlink.setContentTintColor_(NSColor.secondaryLabelColor())
        self.b_tlink.setTarget_(self)
        self.b_tlink.setAction_("onTitleLink:")
        self.b_tlink.setToolTip_("Run the link in this title")
        self.b_tlink.setHidden_(True)
        fx.addSubview_(self.b_tlink)
        self.l_clock = label(CLOCK_PT, mono=True,   # prominent, not huge
                             color=NSColor.colorWithWhite_alpha_(0.68, 1.0))
        self.l_clock.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(
            CLOCK_PT, NSFontWeightSemibold))
        self.l_clock.setAlignment_(NSTextAlignmentRight)
        self.l_clock.setToolTip_("Session time")
        self.b_pause = btn("pause.fill", "onPauseResume:")
        self.b_pause.setToolTip_("Pause / resume")
        self.b_stop = btn("stop.fill", "onStop:")
        self.b_stop.setToolTip_("Stop & log the session")
        self.b_sticky = btn("note.text", "onSticky:")
        self.b_sticky.setToolTip_("Open the sticky note")
        self.b_min = btn("minus", "onHide:", 26, 14)
        self.b_min.setToolTip_("Hide the bar · the session keeps running")
        self.b_chev = btn("chevron.down", "onExpand:", 26, 14)
        self.b_chev.setToolTip_("Show every subtask")
        # row 2
        self.b_tick = btn("circle", "onTick:", 26, 15)
        self.b_tick.setContentTintColor_(GREEN)   # the glow's green
        self.b_tick.setToolTip_("Tick · completes the subtask")
        self.t_item = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 18))
        self.t_item.setBordered_(False)
        self.t_item.setTarget_(self)
        self.t_item.setAction_("onItem:")
        self.t_item.setFont_(NSFont.systemFontOfSize_(17))
        self.t_item.setContentTintColor_(NSColor.secondaryLabelColor())
        self.t_item.setAlignment_(NSTextAlignmentLeft)
        self.t_item.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        self.t_item.setToolTip_("Open this task in TickTick")
        fx.addSubview_(self.t_item)
        self.l_count = label(15, color=NSColor.tertiaryLabelColor())
        self.l_count.setToolTip_("Done / total in today's block")
        self.l_more = label(11, color=NSColor.tertiaryLabelColor())
        self.l_more.setToolTip_("Scroll to see the rest")
        self.l_more.setAlignment_(NSTextAlignmentLeft)
        self.l_more.setHidden_(True)

        # drag-drop landing line: on the overlay so it draws ABOVE the rows
        # thin + translucent, both ends fading to clear (Vex 2026-09-10)
        self.drop_line = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 2))
        self.drop_line.setWantsLayer_(True)
        dl = self.drop_line.layer()        # the neon halo of _pulse_drop_line
        dl.setShadowColor_(GREEN.CGColor())
        dl.setShadowRadius_(6.0)
        dl.setShadowOffset_((0, 0))
        dl.setShadowOpacity_(0.0)
        dl.setMasksToBounds_(False)
        grad = CAGradientLayer.layer()
        solid = GREEN.colorWithAlphaComponent_(0.55).CGColor()
        clear = GREEN.colorWithAlphaComponent_(0.0).CGColor()
        bright = GREEN.colorWithAlphaComponent_(1.0).CGColor()
        self._drop_colors = [clear, solid, solid, clear]
        self._drop_bright = [clear, bright, bright, clear]
        grad.setColors_([clear, solid, solid, clear])
        grad.setLocations_([0.0, 0.2, 0.8, 1.0])
        grad.setStartPoint_((0.0, 0.5))
        grad.setEndPoint_((1.0, 0.5))
        self.drop_line.layer().addSublayer_(grad)
        self._drop_grad = grad
        self.drop_line.setHidden_(True)
        self.overlay.addSubview_(self.drop_line)

        # nest target: a capsule around the row that will ADOPT the dragged
        # one - faint while you rest on it, full + a flare once armed
        self.nest_glow = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.nest_glow.setWantsLayer_(True)
        ng = self.nest_glow.layer()
        ng.setCornerRadius_(9.0)
        ng.setBorderWidth_(1.5)
        ng.setBorderColor_(GREEN.colorWithAlphaComponent_(0.95).CGColor())
        ng.setBackgroundColor_(GREEN.colorWithAlphaComponent_(0.10).CGColor())
        ng.setShadowColor_(GREEN.CGColor())
        ng.setShadowRadius_(9.0)
        ng.setShadowOffset_((0, 0))
        ng.setShadowOpacity_(0.7)
        ng.setMasksToBounds_(False)
        self.nest_glow.setHidden_(True)
        self.overlay.addSubview_(self.nest_glow)

        self._restore_origin()

        from Foundation import NSNotificationCenter, NSProcessInfo
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowMoved:", "NSWindowDidMoveNotification", panel)
        # edge drags (live) and Moom (a one-shot AX size set) both land here
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowResized:", "NSWindowDidResizeNotification", panel)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowEndResize:", "NSWindowDidEndLiveResizeNotification", panel)
        # a monitor change picks up THAT monitor's zoom
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "screenChanged:", "NSWindowDidChangeScreenNotification", panel)
        # hidden / covered / other Space = the smoke drift stops (GPU idle)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowOcclusion:", "NSWindowDidChangeOcclusionStateNotification", panel)
        # hover = arm ⌘+/⌘−/⌘0 (a non-key panel still gets enter/exit)
        from AppKit import NSTrackingArea
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            NSMakeRect(0, 0, 0, 0),
            0x01 | 0x80 | 0x200,   # EnteredAndExited | ActiveAlways | InVisibleRect
            self, None)
        panel.contentView().addTrackingArea_(area)
        try:
            self._hot = _HoverHotkeys(lambda d: AppHelper.callAfter(self._zoom_step, d))
        except Exception as e:     # ⌘-scroll + pinch still zoom
            _log(f"hover hotkeys unavailable: {e}")
        self.zoom = self._zooms.get(self._screen_key(), 1.0)
        NSWorkspace.sharedWorkspace().notificationCenter(
        ).addObserver_selector_name_object_(
            self, "didWake:", "NSWorkspaceDidWakeNotification", None)
        # Keep the 1 s timer honest when occluded (App Nap coalescing)
        self._activity = NSProcessInfo.processInfo(
        ).beginActivityWithOptions_reason_(0x00FFFFFF, "focus bar timers")
        self._move_save_at = 0

    # ── drifting smoke (body chrome) ─────────────────────────────────────
    @objc.python_method
    def _build_smoke(self, host):
        """The body's smoke, under the rim and the rows: a static rim floor
        (never an empty edge), then a container masked by a 9-slice edge
        falloff holding two CAReplicator grids of one seamless tile - A
        rises, B (mirrored, 1.4x) drifts sideways slower, so the smoke
        morphs instead of sliding. Both drifts are render-server
        animations: no Python timer, no re-render, ever. A missing asset
        or layer class = the plain rim, never a crash."""
        self.smoke = self.smoke_mask = self.smoke_rim = None
        self.smoke_grids = []
        self._smoke_on = False
        self._smoke_want = False
        self._occl_visible = True
        self._smoke_motion = SMOKE_MOTION
        try:
            from Foundation import NSURL
            from Quartz import (CGImageSourceCreateWithURL,
                                CGImageSourceCreateImageAtIndex)

            def img(name):
                src = CGImageSourceCreateWithURL(
                    NSURL.fileURLWithPath_(os.path.join(ASSETS, name)), None)
                return CGImageSourceCreateImageAtIndex(src, 0, None) if src else None

            tile, mimg, rimg = (img("focus_smoke_tile.png"), img("focus_smoke_mask.png"),
                                img("focus_smoke_rim.png"))
            if tile is None or mimg is None:
                _log("smoke assets missing - plain rim")
                return
            u = SMOKE_SLICE / SMOKE_SIDE
            centre = ((u, u), (1 - 2 * u, 1 - 2 * u))   # the middle 2 pt stretch
            if rimg is not None:
                rim = CALayer.layer()
                rim.setAnchorPoint_((0, 0))
                rim.setContents_(rimg)
                rim.setContentsScale_(2.0)
                rim.setContentsCenter_(centre)
                host.addSublayer_(rim)
                self.smoke_rim = rim
            smoke = CALayer.layer()
            smoke.setAnchorPoint_((0, 0))
            mask = CALayer.layer()            # a mask reads ALPHA only
            mask.setAnchorPoint_((0, 0))
            mask.setContents_(mimg)
            mask.setContentsScale_(2.0)
            mask.setContentsCenter_(centre)
            smoke.setMask_(mask)
            lin = CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionLinear)
            b = SMOKE_TILE * SMOKE_B
            for period, op, mirror, axis, dur in (
                    (b, SMOKE_OPACITY[1], True, "x", SMOKE_LOOP * SMOKE_B / SMOKE_B_SPEED),
                    (SMOKE_TILE, SMOKE_OPACITY[0], False, "y", SMOKE_LOOP)):
                t = CALayer.layer()
                t.setContents_(tile)
                t.setContentsScale_(2.0)
                t.setFrame_(((0, 0), (period, period)))
                if mirror:
                    t.setTransform_(CATransform3DMakeScale(-1, 1, 1))
                row = CAReplicatorLayer.layer()
                row.setInstanceTransform_(CATransform3DMakeTranslation(period, 0, 0))
                row.addSublayer_(t)
                grid = CAReplicatorLayer.layer()
                grid.setInstanceTransform_(CATransform3DMakeTranslation(0, period, 0))
                grid.addSublayer_(row)
                # origin one period below-left of the BOTTOM-left corner: a
                # height change (tick, zoom) never re-seeds the bottom band
                grid.setAnchorPoint_((0, 0))
                grid.setFrame_(((-period, -period), (period, period)))
                grid.setOpacity_(op)
                a = CABasicAnimation.animationWithKeyPath_("transform.translation." + axis)
                a.setFromValue_(0.0)
                a.setToValue_(period)            # one period = a seamless loop
                a.setDuration_(dur)
                a.setRepeatCount_(1e9)
                a.setTimingFunction_(lin)
                a.setRemovedOnCompletion_(False)    # survives hide / show
                # a FIXED begin (not 0 = "at commit"): the phase is then the
                # layer's own clock, so a still frame's timeOffset picks it
                a.setBeginTime_(1e-6)
                try:     # ~0.4 pt per frame: smooth, and the display never runs 120 Hz for it
                    from Quartz import CAFrameRateRangeMake
                    a.setPreferredFrameRateRange_(CAFrameRateRangeMake(8, 15, 12))
                except Exception:
                    pass
                grid.addAnimation_forKey_(a, "drift")
                smoke.addSublayer_(grid)
                self.smoke_grids.append((grid, row, period))
            host.addSublayer_(smoke)
            self.smoke, self.smoke_mask = smoke, mask
            self._smoke_on = True
            try:
                if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion():
                    self._smoke_motion = False
            except Exception:
                pass
            if not self._smoke_motion:       # a still frame, same look
                smoke.setSpeed_(0.0)
                smoke.setTimeOffset_(SMOKE_STILL_T)
                self._smoke_on = False
        except Exception as e:
            _log(f"smoke unavailable: {e}")
            self.smoke = None

    @objc.python_method
    def _layout_smoke(self, w, h):
        """Inside _relayout's no-actions transaction: frames + replicator
        counts only (~0.005 ms) - live resize and Moom never lag, and the
        9-slice keeps the band glued to the edge in the same commit.
        Short bodies (1-2 rows) thin the smoke so it never drowns them."""
        if self.smoke is None:
            return
        for lyr in (self.smoke, self.smoke_mask, self.smoke_rim):
            if lyr is not None:
                lyr.setFrame_(((0, 0), (w, h)))
        for grid, row, p in self.smoke_grids:
            row.setInstanceCount_(int(math.ceil(w / p)) + 2)
            grid.setInstanceCount_(int(math.ceil(h / p)) + 2)
        self.smoke.setOpacity_(SMOKE_ALPHA * min(1.0, max(0.55, h / 160.0)))

    @objc.python_method
    def _smoke_sync(self):
        self._smoke_run(self._smoke_want and self._occl_visible)

    @objc.python_method
    def _smoke_run(self, on):
        """Drift on / off, keeping the phase: a paused layer's clock stops
        at timeOffset, and resuming re-bases beginTime so nothing jumps."""
        s = self.smoke
        if s is None or not self._smoke_motion or bool(on) == self._smoke_on:
            return
        self._smoke_on = bool(on)
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            if on:
                paused = s.timeOffset()
                s.setSpeed_(1.0)
                s.setTimeOffset_(0.0)
                s.setBeginTime_(0.0)
                s.setBeginTime_(s.convertTime_fromLayer_(CACurrentMediaTime(), None) - paused)
            else:
                t = s.convertTime_fromLayer_(CACurrentMediaTime(), None)
                s.setSpeed_(0.0)
                s.setTimeOffset_(t)
        finally:
            CATransaction.commit()

    def windowOcclusion_(self, note):
        try:        # NSWindowOcclusionStateVisible = 1 << 1
            self._occl_visible = bool(int(self.panel.occlusionState()) & 2)
        except Exception:
            self._occl_visible = True
        self._smoke_sync()

    # ── geometry / visibility ────────────────────────────────────────────
    def _restore_origin(self):
        """Put the bar back where it was: the saved TOP-left corner - the
        corner _relayout keeps fixed while the bar grows downward. Restoring
        the bottom-left 'origin' (legacy files still fall back to it) walked
        the bar down by its expanded height on every respawn (Vex
        2026-09-10). Off every screen → top-center of the main screen."""
        try:
            with open(BAR_STATE) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        try:                        # a routine macro's one-shot spot first (_place_at)
            pa = st.get("place_at")
            if pa and self._on_screen(float(pa[0]), float(pa[1])):
                self.panel.setFrameTopLeftPoint_((float(pa[0]), float(pa[1])))
                return
        except (TypeError, ValueError, IndexError):
            pass
        try:
            tl = st.get("top_left")
            if tl:
                x, top = float(tl[0]), float(tl[1])
            else:
                ox, oy = st.get("origin") or [None, None]
                x, top = float(ox), float(oy) + ROW1_H
        except (TypeError, ValueError, IndexError):
            x = top = None
        if x is None or not self._on_screen(x, top):
            scr = NSScreen.mainScreen()
            vf = scr.visibleFrame() if scr else None
            if vf:
                x = vf.origin.x + (vf.size.width - W) / 2.0
                top = vf.origin.y + vf.size.height - 20
            else:
                x, top = 100.0, 800.0
        self.panel.setFrameTopLeftPoint_((x, top))

    def _on_screen(self, x, top):
        """This TOP-left keeps the bar grabbable on some screen."""
        for s in NSScreen.screens():
            f = s.frame()
            if (f.origin.x - 10 <= x <= f.origin.x + f.size.width - 60
                    and f.origin.y + ROW1_H - 10 <= top <= f.origin.y + f.size.height + 10):
                return True
        return False

    def _place_at(self, tl):
        """A routine macro's one-shot spot (link.py TICKAL_BAR_AT writes it
        as place_at next to top_left): move there, shown or hidden, clear
        the key, save the spot. A spot on no screen is dropped. Covers the
        bar that was already up, hidden, or in its idle grace when the macro
        ran - an AX move can't see an ordered-out panel (Vex 2026-09-11)."""
        try:
            x, top = float(tl[0]), float(tl[1])
            if self._on_screen(x, top):
                self.panel.setFrameTopLeftPoint_((x, top))
        except (TypeError, ValueError, IndexError):
            pass
        try:
            with open(BAR_STATE) as f:
                st = json.load(f)
            st.pop("place_at", None)
            tmp = BAR_STATE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, BAR_STATE)
        except (OSError, ValueError, AttributeError) as e:
            _log(f"place_at: {e}")
        self._persist_origin()

    def windowMoved_(self, note):
        self._move_save_at = time.monotonic() + 0.6   # debounce; saved by tick

    # ── zoom (⌘+ / ⌘− / ⌘0 on hover, ⌘-scroll, pinch) - per monitor ───────
    def mouseEntered_(self, event):
        if self._hot is not None:
            self._hot.arm()

    def mouseExited_(self, event):
        if self._hot is not None:
            self._hot.disarm()

    def screenChanged_(self, note):
        if self._self_frame:           # our own zoom-driven resize, not a move
            return
        z = self._zooms.get(self._screen_key(), 1.0)
        if z != self.zoom:
            self.zoom = z
            self._zoom_accum = self._pinch_accum = 0.0
            self._relayout()

    @objc.python_method
    def _screen_key(self):
        """The monitor under the bar's TOP-left corner - the anchor zoom
        never moves. panel.screen() is the majority-area screen, and zoom
        changes the height: between two STACKED monitors each zoom handed
        the majority to the other, forever (zoom review 2026-09-10)."""
        fr = self.panel.frame()
        ax, ay = fr.origin.x + 1, fr.origin.y + fr.size.height - 1
        scr = next((s for s in NSScreen.screens()
                    if s.frame().origin.x <= ax < s.frame().origin.x + s.frame().size.width
                    and s.frame().origin.y <= ay < s.frame().origin.y + s.frame().size.height),
                   None) or self.panel.screen() or NSScreen.mainScreen()
        try:
            return str(scr.localizedName())
        except Exception:
            return str(scr.deviceDescription().get("NSScreenNumber"))

    @objc.python_method
    def _pointer_inside(self):
        p, f = NSEvent.mouseLocation(), self.panel.frame()
        return (f.origin.x <= p.x <= f.origin.x + f.size.width
                and f.origin.y <= p.y <= f.origin.y + f.size.height)

    @objc.python_method
    def _zoom_step(self, direction):
        """+1 / -1 = 10% steps, 0 = back to 100% - for THIS monitor only."""
        if self._hot is not None and not self._pointer_inside():
            self._hot.disarm()     # a missed mouse-exit must never keep ⌘+ captive
            return
        z = 1.0 if direction == 0 else self.zoom + 0.1 * direction
        z = round(max(ZOOM_MIN, min(ZOOM_MAX, z)), 2)
        if direction == 0:
            self._zoom_accum = self._pinch_accum = 0.0
        self.zoom = z
        self._zooms[self._screen_key()] = z
        self._move_save_at = time.monotonic() + 0.6   # persisted by tick
        self._flash_until = time.monotonic() + 1.2    # tick_ leaves the clock alone
        self._relayout()
        self.l_clock.setStringValue_(f"{int(round(z * 100))}%")

    @objc.python_method
    def _clock_w(self):
        """The clock box = the width of its CURRENT shape at its font (a
        template like '88:88' / '8:88:88' / '120%' - tabular digits keep it
        steady as the seconds tick) + a small cushion. A fixed 96 px box
        right-aligned the digits and starved the title ('St...' with room
        to spare, Vex 2026-09-10)."""
        try:
            from Foundation import NSString
            from AppKit import NSFontAttributeName
            cur = str(self.l_clock.stringValue() or "") or "88:88"
            tmpl = "".join("8" if ch.isdigit() else ch for ch in cur)
            size = NSString.stringWithString_(tmpl).sizeWithAttributes_(
                {NSFontAttributeName: self.l_clock.font()})
            return float(size.width) + 8.0
        except Exception:
            return 72.0

    @objc.python_method
    def _clock_frame_y(self, y1):
        """(height, y) for the clock: a text field draws its text from the
        TOP of its frame, so the 18 pt digits sat high in the old 28 px
        frame. The frame hugs the text's cell height and is placed so the
        digits' CAP-HEIGHT centre lands on the icon row's centre (y1 + 14)."""
        try:
            f = self.l_clock.font()
            ch = float(self.l_clock.cell().cellSizeForBounds_(
                NSMakeRect(0, 0, 1000, 1000)).height)
            top_pad = max(0.0, ch - (f.ascender() - f.descender()))   # above the line box
            baseline_from_top = top_pad + f.ascender()
            centre = y1 + 14.0 + CLOCK_DY
            top = centre + f.capHeight() / 2.0 + baseline_from_top - f.capHeight()
            return ch, top - ch
        except Exception:
            return 28.0, y1

    @objc.python_method
    def on_magnify(self, event):
        try:
            ph = event.phase()
        except Exception:
            ph = 0
        if ph & 0x1:                              # NSEventPhaseBegan: a fresh pinch
            self._pinch_accum = 0.0
        self._pinch_accum += event.magnification()
        if self._pinch_accum >= 0.12:             # one step per event at most
            self._pinch_accum -= 0.12
            self._zoom_step(1)
        elif self._pinch_accum <= -0.12:
            self._pinch_accum += 0.12
            self._zoom_step(-1)
        if ph & (0x8 | 0x10):                     # ended / cancelled
            self._pinch_accum = 0.0

    def windowResized_(self, note):
        """A size change WE didn't make is the user's: an edge drag (AppKit
        live resize) or Moom's modifier-drag (a rapid STREAM of AX size
        sets, no live-resize bracket). Either way the content just follows
        the frame; the size is adopted - saved + snapped to whole rows -
        only once the frame holds still (_settle_resize / end of live)."""
        if self._self_frame:
            return
        self._user_rs_at = time.monotonic()
        self._relayout()                          # follow, never fight
        if not self.panel.inLiveResize():
            AppHelper.callLater(RESIZE_QUIET + 0.05, self._settle_resize)

    def windowEndResize_(self, note):
        if not self._self_frame:
            self._adopt_user_size()

    def _settle_resize(self):
        """Fires after every Moom step; only the one that finds the stream
        quiet (and not yet adopted) adopts."""
        if (self.panel.inLiveResize() or self._adopted_at == self._user_rs_at
                or time.monotonic() - self._user_rs_at < RESIZE_QUIET):
            return
        self._adopt_user_size()

    def _resizing(self):
        """True mid-drag (mouse live resize) or within RESIZE_QUIET of the
        last user resize step (Moom's stream): the frame is the authority."""
        return bool(self.panel.inLiveResize()) or (
            time.monotonic() - self._user_rs_at < RESIZE_QUIET)

    def _adopt_user_size(self):
        """Width always; height only while expanded - it sets how many rows
        show before scrolling (a collapsed-mode height means nothing)."""
        fr = self.panel.frame()
        self.user_w = float(fr.size.width)
        # the height becomes the row capacity ONLY when rows were drawn and
        # the height really moved: an unchanged height is the bar's own
        # fitted content height, not a choice (a width-only drag used to
        # pin the capacity to the rows on screen - even to ONE row on a
        # fresh setup, or while the block was still loading)
        if self._last_rows and abs(fr.size.height - self._last_H) >= 1:
            h = max(float(fr.size.height), ROW1_H + (CHK_H + 2 * PAD_V) * self.zoom)
            self.user_h = ROW1_H + (h - ROW1_H) / self.zoom   # saved at 100% scale (_cap)
        self._adopted_at = self._user_rs_at
        self._user_rs_at = 0.0                        # the resize is over
        self._move_save_at = time.monotonic() + 0.6   # persisted by tick
        AppHelper.callAfter(self._relayout)           # snap to whole rows

    def _cap(self, live=False, items=()):
        """Expanded rows that fit from scroll_off down: the live frame
        mid-drag, else the user's saved height, else MAX_ROWS. Rows differ
        in height (nested ones sit tighter, _row_h); the 16 px overflow
        strip only counts when the rest won't all fit."""
        if live:
            h = self.panel.frame().size.height
        elif self.user_h:
            # user_h is saved at 100% scale (the header isn't zoomed): the
            # same ROWS fit at any zoom and the bar grows with it - zooming
            # in to READ must not hide rows behind the scroll strip
            h = ROW1_H + (self.user_h - ROW1_H) * self.zoom
        else:
            h = None
        if not h:
            return self.MAX_ROWS
        rest = list(items)[self.scroll_off:] or [{}]

        def fit(avail):
            n, used = 0, 0.0
            for it in rest:
                used += _row_h(it, self.zoom)
                if used > avail:
                    break
                n += 1
            return n
        pad = 2 * PAD_V * self.zoom                # room above + below the rows
        k = fit(h - ROW1_H - pad)
        if k < len(rest):
            k = fit(h - ROW1_H - pad - 16)
        return max(1, k)

    def _persist_origin(self):
        try:
            fr = self.panel.frame()
            o = fr.origin
            st = {}
            try:
                with open(BAR_STATE) as f:
                    st = json.load(f)
            except (OSError, ValueError):
                pass
            st["origin"] = [o.x, o.y]                    # legacy readers
            # the TOP-left is what the bar keeps fixed (see _restore_origin)
            st["top_left"] = [o.x, o.y + fr.size.height]
            if self.user_w or self.user_h:               # each axis alone
                st["size"] = [self.user_w, self.user_h]
            if self._zooms:
                st["zoom"] = self._zooms                 # per monitor
            st["folded"] = list(self.folded)[:FOLD_MAX]  # folded subtrees
            tmp = BAR_STATE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, BAR_STATE)
        except Exception as e:
            _log(f"persist_origin: {e}")

    def didWake_(self, note):
        self.content_dirty.set()

    # ── loops ────────────────────────────────────────────────────────────
    def _start_loops(self):
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)
        self.timer.setTolerance_(0.1)
        threading.Thread(target=self._state_loop, daemon=True).start()
        threading.Thread(target=self._content_loop, daemon=True).start()

    def tick_(self, timer):
        """1 s UI repaint from timestamps only + housekeeping."""
        try:
            m = self.state
            if time.monotonic() < self._flash_until:
                pass                              # the zoom % flash owns the clock
            elif m["kind"] == "timer" and m["focus_st"]:
                self.l_clock.setStringValue_(
                    "⏸ " + fmt_timer(xact.focus_elapsed(m["focus_st"]))
                    if m["paused"] else fmt_timer(xact.focus_elapsed(m["focus_st"])))
            elif m["kind"] == "pomo":
                rem, at = self._pomo_anchor
                left = rem if m["paused"] else rem - (time.monotonic() - at)
                self.l_clock.setStringValue_(
                    ("⏸ " if m["paused"] else "") + fmt_pomo(left))
            if self._hot is not None and self._hot.refs and not self._pointer_inside():
                self._hot.disarm()          # safety net for a missed mouse-exit
            if self._move_save_at and time.monotonic() > self._move_save_at:
                self._move_save_at = 0
                self._persist_origin()
            if self.pending_tick and time.monotonic() - self.pending_tick[2] > 8:
                self.pending_tick = None          # timed out - poll re-syncs
                self.content_dirty.set()
        except Exception as e:
            _log(f"tick: {e}")

    def _state_loop(self):
        n = 0
        while True:
            try:
                m = read_state()
                AppHelper.callAfter(self.applyState_, m)
            except Exception as e:
                _log(f"state_loop: {e}")
            n += 1
            time.sleep(1.0)

    def _content_loop(self):
        import api as api_mod
        api = None
        while True:
            woke = self.content_dirty.wait(timeout=self._content_interval())
            self.content_dirty.clear()
            with self._shared_lock:
                pid = self._shared.get("pid")
                tid = self._shared.get("tid")
                attributed = self._shared.get("attributed")
                visible = self._shared.get("visible")
            if not (attributed and visible and pid and tid):
                continue
            try:
                if api is None:
                    api = api_mod.TickTickAPI(cfg.get_token())
                seq = self.mutation_seq
                # ONE project-data GET: the open SUBTREE (fsub.descendants -
                # titles + sortOrder + _depth, grandchildren included since
                # 2026-09-09) plus childIds - completed children stay in
                # childIds (verified), so done = childIds minus open; an
                # open descendant's childIds add its completed children.
                data = api.get_project_data(pid)
                tasks = data.get("tasks") or []
                open_children = fsub.descendants(tasks, tid)
                focus = next((t for t in tasks if t.get("id") == tid), None)
                if focus is None:   # completed mid-session stays GET-able
                    focus = api.get_task(pid, tid)
                child_ids = list(focus.get("childIds") or [])
                for t in open_children:
                    child_ids += [c for c in (t.get("childIds") or [])
                                  if c not in child_ids]
                summary = fsub.children_summary(open_children, child_ids)
                self._reconcile_cache(tid, open_children)
                AppHelper.callAfter(self.applyBlock_, (summary, seq))
            except Exception as e:
                _log(f"content_loop: {e}")
                # Back off hard on rate limits (TickTick also enforces
                # 100 req/min), gently otherwise.
                time.sleep(60 if "rate limit" in str(e).lower() else 15)

    def _content_interval(self):
        return 5.0 if (time.monotonic() - self.content_last_change) < 600 else 20.0

    def _reconcile_cache(self, ftid, open_children):
        """Sticky/app-side subtask edits reach the workflow cache within one
        POLL instead of the hourly sync - the picker's tasks/remove screens
        and the 🎯 marks read cache. Scoped to the focus task's open
        SUBTREE (open_children = fsub.descendants of the poll), best-effort
        (a lost write race heals on the next poll); all_tasks only,
        project_data waits for the sync. Caveat: a child DETACHED app-side
        is indistinguishable from a completed one here and drops from the
        cache until the sync - rare, un-staging normally runs through
        fx_unstage which patches properly."""
        try:
            import cache as cache_store
            cached = cache_store.get("all_tasks")
            if cached is None:
                return
            open_ids = {t.get("id") for t in open_children}
            cached_ids = {t.get("id") for t in fsub.descendants(
                [t for t in cached if t.get("status", 0) == 0], ftid)}
            if cached_ids == open_ids:
                return
            stale = cached_ids - open_ids
            keep = [t for t in cached if t.get("id") not in stale]
            have = {t.get("id") for t in keep}
            pnames = {p.get("id"): p.get("name", "")
                      for p in (cache_store.get("projects") or [])}
            for t in open_children:
                if t.get("id") not in have:
                    pid = t.get("projectId", "")
                    # the DFS stamps are per-poll, not cache facts
                    clean = {k: v for k, v in t.items()
                             if k not in ("_depth", "_dfs")}
                    keep.append(dict(clean, _projectId=pid,
                                     _projectName=pnames.get(pid, "")))
            cache_store.set("all_tasks", keep)
        except Exception as e:
            _log(f"cache reconcile: {e}")

    # ── main-thread state application ───────────────────────────────────
    def applyState_(self, m):
        prev = self.state
        with self._shared_lock:
            self._shared = {"pid": m["pid"], "tid": m["tid"],
                            "attributed": m["attributed"],
                            "visible": m["visible"]}
        if m["kind"] == "pomo" and (prev["kind"] != "pomo"
                                    or abs(m["pomo_remaining"]
                                           - (self._pomo_anchor[0]
                                              - (time.monotonic() - self._pomo_anchor[1]))) > 90):
            self._pomo_anchor = (m["pomo_remaining"], time.monotonic())
        if m["kind"] == "pomo" and m["paused"] != prev.get("paused"):
            self._pomo_anchor = (m["pomo_remaining"], time.monotonic())
        task_changed = (m["tid"] != prev.get("tid")) or (m["kind"] != prev.get("kind"))
        self.state = m
        if m.get("place_at"):
            self._place_at(m["place_at"])

        if m["kind"] == "idle":
            if self.idle_since is None:
                self.idle_since = time.monotonic()
            if (not m["visible"]) or time.monotonic() - self.idle_since > IDLE_EXIT_S:
                self.shutdown()
                return
        else:
            self.idle_since = None

        if task_changed:
            self.block = None
            self.expanded = True        # every new session opens fully expanded
            self.scroll_off = 0
            self.content_dirty.set()
        if m["visible"] and m["kind"] != "idle":
            if not self.panel.isVisible():
                self.panel.orderFrontRegardless()
        else:
            if self.panel.isVisible():
                if self._hot is not None:
                    self._hot.disarm()
                self.panel.orderOut_(None)
        self._relayout()

    def applyBlock_(self, payload):
        summary, seq = payload
        if seq != self.mutation_seq:
            return                       # stale poll - a local tick outran it
        old = self.block
        if old != summary:
            self.content_last_change = time.monotonic()
        self.block = summary
        self.pending_tick = None
        self._relayout()

    # ── layout ───────────────────────────────────────────────────────────
    def _first_unchecked(self):
        if not self.block:
            return None
        for it in self.block["items"]:
            if not it["checked"]:
                return it
        return None

    def _row_views(self, i):
        """Lazily-built (circle, title, grip, fold, link) 5-tuple for expanded
        item row i - the grip is the drag-drop reorder handle, the fold
        chevron hugs the text of a row that has subtasks, and the link icon
        sits in the far-right column (mirroring the grip) when the title
        carries one (Vex 2026-09-12)."""
        while len(self.row_pool) <= i:
            idx = len(self.row_pool)
            b = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 26, 26))
            b.setBordered_(False)
            b.setTitle_("")
            b.setImage_(sym_image("circle", CIRCLE_PT))
            b.setContentTintColor_(NSColor.secondaryLabelColor())
            b.setTarget_(self)
            b.setAction_("onTickRow:")
            b.setTag_(idx)
            b.setToolTip_("Tick · completes the subtask")
            self.fx.addSubview_(b)
            t = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 18))
            t.setBordered_(False)
            t.setTarget_(self)
            t.setAction_("onOpenRow:")
            t.setTag_(idx)
            t.setFont_(NSFont.systemFontOfSize_(17))
            t.setContentTintColor_(NSColor.secondaryLabelColor())
            t.setAlignment_(NSTextAlignmentLeft)
            t.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
            t.setToolTip_("Open this task in TickTick")
            self.fx.addSubview_(t)
            grip = GripView.alloc().initWithFrame_(NSMakeRect(0, 0, 18, 20))
            grip.setImage_(sym_image("line.3.horizontal", 11))
            grip.setContentTintColor_(NSColor.tertiaryLabelColor())
            grip.setTag_(idx)
            grip.setToolTip_("Drag to reorder · drag right onto a task to nest it")
            grip._bar = self
            self.fx.addSubview_(grip)
            f = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 20))
            f.setBordered_(False)
            f.setTitle_("")
            f.setImage_(sym_image("chevron.down", 10))
            f.setContentTintColor_(NSColor.tertiaryLabelColor())
            f.setTarget_(self)
            f.setAction_("onFoldRow:")
            f.setTag_(idx)
            f.setToolTip_("Fold subtasks")
            self.fx.addSubview_(f)
            k = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 20, 20))
            k.setBordered_(False)
            k.setTitle_("")
            k.setImage_(sym_image("link", 12))
            k.setContentTintColor_(NSColor.secondaryLabelColor())
            k.setTarget_(self)
            k.setAction_("onLinkRow:")
            k.setTag_(idx)
            k.setToolTip_("Run the link in this title")
            self.fx.addSubview_(k)
            self.row_pool.append((b, t, grip, f, k))
        return self.row_pool[i]

    MAX_ROWS = 10

    def _text_w(self, button, cap):
        """The width of a button's text AS DRAWN, capped at its box. The
        attributed title measures the glyphs alone; intrinsicContentSize adds
        the cell's padding, which at row-1's 20 pt bold left a visible gap
        before the hugging icon (Vex 2026-09-12)."""
        try:
            w = float(button.attributedTitle().size().width)
        except Exception:
            w = float(button.intrinsicContentSize().width) - 8
        return max(0.0, min(w, cap))

    def _relayout(self):
        if self._drag is not None:    # a grip drag owns the rows: a poll or
            self._relayout_pending = True    # the 1 s state tick would snap
            return                           # the lifted row back mid-drag
        m = self.state
        if m["kind"] == "idle":
            return
        att = m["attributed"]
        all_items = (self.block or {}).get("items", []) if att else []
        # ticked rows leave the BAR - the description keeps them
        full_rows = fsub.open_rows(all_items)   # minus a ticked parent's children
        # which rows own a subtree is read off the UNFOLDED list: a folded
        # row has no deeper row left, and its chevron would vanish with them
        kid_tids = fsub.kid_tids(full_rows)
        items = self._open_items()          # ...minus every folded subtree
        nxt = self._first_unchecked() if att else None
        expanded = self.expanded and bool(items)
        live = self._resizing()      # edge drag or Moom stream: frame rules
        cap = self._cap(live, items)
        overflow = expanded and len(items) > cap
        self.scroll_off = max(0, min(self.scroll_off, max(0, len(items) - cap)))
        window = items[self.scroll_off:self.scroll_off + cap] if expanded else []
        self.visible_items = window
        n_rows = len(window) if expanded else (1 if all_items else 0)
        H = (ROW1_H + (sum(_row_h(it, self.zoom) for it in window) if expanded
                       else ROW2_H * self.zoom * n_rows)
             + (2 * PAD_V * self.zoom if expanded else 0)   # room at both ends
             + (16 if overflow else 0))

        # width: fit title + clock + buttons - unless the user sized it (edge
        # drag / Moom): then theirs wins, never narrower than the buttons,
        # and the title takes the extra room
        title_w = 0.0
        natural = 0.0
        tlink = fsub.title_link(m["title"]) if att else None
        if att:
            full = _disp(m["title"]) or "Task"   # links render as [name]🔗
            self.t_title.setTitle_(full[:60])
            self.t_title.setToolTip_(full + "\nOpen in TickTick")
            natural = max(60.0, self.t_title.intrinsicContentSize().width + 10)
        btn_w = ICON_BOX * (3 + (2 if att else 0) + (1 if items else 0))
        clock_w = self._clock_w()   # the digits' real width, not a fixed 96 px box
        # row 1's link icon joins the RIGHT-hand run: it ends CLOCK_GAP before
        # the digits, exactly as the digits end CLOCK_GAP before ⏸ (Vex
        # 2026-09-12: hugging the title left a hole and ate the title). It
        # costs the title only what it is, not the 12 px title gap it replaces.
        link_room = (TLINK_W + CLOCK_GAP + TLINK_GAP - 12) if tlink else 0
        fixed = (16 + ((30 + 8 + 12) if att else 0) + clock_w + CLOCK_GAP + btn_w + 14
                 + link_room)
        min_w = max(420.0, fixed + (60.0 if att else 0.0))
        fr = self.panel.frame()
        if live:
            w = max(min_w, float(fr.size.width))
        elif self.user_w:
            w = max(min_w, self.user_w)
        else:
            w = max(420.0, min(880.0, fixed + min(340.0, natural)))
        if att:
            title_w = max(60.0, min(natural, w - fixed))
        self.W = w
        if expanded:            # rows showing: the height is the user's
            self.panel.setMinSize_(NSMakeSize(min_w, ROW1_H + (CHK_H + 2 * PAD_V) * self.zoom))
            self.panel.setMaxSize_(NSMakeSize(10000, 10000))
        else:                   # collapsed / no rows: width-only resizing (a
            self.panel.setMinSize_(NSMakeSize(min_w, H))    # top-edge drag
            self.panel.setMaxSize_(NSMakeSize(10000, H))    # used to MOVE it)

        if live:
            H = float(fr.size.height)            # never fight the drag
        elif int(fr.size.height) != int(H) or int(fr.size.width) != int(w):
            # grow/shrink DOWNWARD + rightward: keep the top-left corner put
            top = fr.origin.y + fr.size.height
            self._self_frame = True              # not a user resize
            try:
                self.panel.setFrame_display_(NSMakeRect(fr.origin.x, top - H, w, H), True)
            finally:
                self._self_frame = False
        if not live:
            self._last_H = float(H)              # see _adopt_user_size
            self._last_rows = expanded           # rows actually drawn
        y1 = H - ROW1_H + (ROW1_H - 28) / 2.0   # row-1 controls baseline

        # two-tone chrome
        one = (n_rows == 0)
        # no implicit animation: the glow is a bare CALayer, and Core
        # Animation eased every frame change over ~0.25 s - it trailed the
        # window edge during a resize (Vex 2026-09-10)
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            self.bg_top.setFrame_(NSMakeRect(0, H - ROW1_H, w, ROW1_H))
            self.bg_top.layer().setMaskedCorners_(15 if one else 12)  # all / top only
            self.bg_bot.setHidden_(one)
            if not one:
                self.bg_bot.setFrame_(NSMakeRect(0, 0, w, H - ROW1_H))
                self.glow.setFrame_(NSMakeRect(0, 0, w, H - ROW1_H))
                self._layout_smoke(w, H - ROW1_H)
        finally:
            CATransaction.commit()
        # the drift runs only while it is worth watching: rows showing, the
        # timer running (the smoke stills with it), the window on screen
        self._smoke_want = (not one) and expanded and not m["paused"]
        self._smoke_sync()

        x = 16
        for v, show in ((self.b_done, att), (self.t_title, att)):
            v.setHidden_(not show)
        self.b_tlink.setHidden_(not (att and tlink))
        if att:
            self.b_done.setFrame_(NSMakeRect(x, y1 - 1, 30, 30))
            x += 38
            self.t_title.setFrame_(NSMakeRect(x, y1, title_w, 28))
            if tlink:       # CLOCK_GAP before the digits, like the digits
                cx = w - 14 - btn_w - CLOCK_GAP - clock_w   # the clock's left edge
                self.b_tlink.setFrame_(NSMakeRect(cx - CLOCK_GAP - TLINK_W,
                                                  y1 + 3, TLINK_W, 22))
                self.b_tlink.setToolTip_(f"Run this link\n{tlink}")
            x += title_w + 12
        # right side, right→left - a tight run of ICON_BOX icons, edge to
        # edge, the clock just left of it (Vex 2026-09-10: both gaps halved)
        rx = w - 14
        rx -= ICON_BOX
        self.b_chev.setHidden_(not items)
        if items:
            self.b_chev.setImage_(sym_image("chevron.up" if expanded else "chevron.down", 14))
            self.b_chev.setToolTip_("Collapse" if expanded else "Show every subtask")
            self.b_chev.setFrame_(NSMakeRect(rx, y1, ICON_BOX, 28))
            rx -= ICON_BOX
        self.b_min.setFrame_(NSMakeRect(rx, y1, ICON_BOX, 28))
        rx -= ICON_BOX
        self.b_sticky.setHidden_(not att)
        if att:
            self.b_sticky.setFrame_(NSMakeRect(rx, y1, ICON_BOX, 28))
            rx -= ICON_BOX
        self.b_stop.setFrame_(NSMakeRect(rx, y1, ICON_BOX, 28))
        rx -= ICON_BOX
        self.b_pause.setFrame_(NSMakeRect(rx, y1, ICON_BOX, 28))
        self.b_pause.setImage_(sym_image("play.fill" if m["paused"] else "pause.fill", 15))
        rx -= CLOCK_GAP + clock_w                # a small gap before the clock
        ch, cy = self._clock_frame_y(y1)         # digits centred on the icon row
        self.l_clock.setFrame_(NSMakeRect(rx, cy, clock_w, ch))

        # collapsed row 2: first unchecked + counter ("All done 🎉" needs the
        # UNfiltered list - with every row ticked, `items` is empty)
        two = (not expanded) and bool(all_items)
        for v, show in ((self.b_tick, two and bool(nxt)),
                        (self.t_item, two), (self.l_count, two)):
            v.setHidden_(not show)
        if two:
            # lower rows sit indented (~25%) under the title
            z = self.zoom
            bt = 26 * z                            # the tick box, zoomed
            y2 = (ROW2_H * z - bt) / 2.0
            self.b_tick.setFrame_(NSMakeRect(30, y2, bt, bt))
            done, total = self.block["done"], self.block["total"]
            lc_pt = getattr(self, "_lc_pt", None) or self.l_count.font().pointSize()
            self._lc_pt = lc_pt                    # the un-zoomed size, captured once
            self.l_count.setFont_(NSFont.fontWithDescriptor_size_(
                self.l_count.font().fontDescriptor(), lc_pt * z))
            ch = 20 * z                            # centred on the zoomed row
            self.l_count.setFrame_(NSMakeRect(w - 72 - 16 * (z - 1), (ROW2_H * z - ch) / 2.0,
                                              56 * z, ch))
            self.l_count.setStringValue_(f"{done}/{total}")
            if nxt:
                nested = nxt.get("depth", 1) > 1
                self.b_tick.setImage_(sym_image(   # nested next item: square box
                    "square" if nested else "circle",
                    (SQUARE_PT if nested else CIRCLE_PT) * z))
                self.t_item.setFont_(NSFont.systemFontOfSize_(
                    (SUB_FONT if nested else TASK_FONT) * z))
                nfull = _disp(nxt["title"])
                self.t_item.setTitle_(nfull[:70])
                self.t_item.setToolTip_(nfull + "\nOpen in TickTick")
                self.t_item.setContentTintColor_(ROW_TEXT)
            else:
                self.t_item.setFont_(NSFont.systemFontOfSize_(TASK_FONT * z))
                self.t_item.setTitle_("All done 🎉")
                self.t_item.setContentTintColor_(GREEN)
            ix = 30 + bt + 8
            ih = 24 * z
            self.t_item.setFrame_(NSMakeRect(ix, (ROW2_H * z - ih) / 2.0, w - ix - 76, ih))

        # expanded: the scrolled window of UNchecked boxes, top→bottom, each
        # with ⤒↑↓⤓ reorder buttons
        for i, views in enumerate(self.row_pool):
            show = expanded and i < n_rows
            for v in views:
                v.setHidden_(not show)
        if expanded:
            y_top = H - ROW1_H - PAD_V * self.zoom  # rows stack down from here
            self._gap_y = [y_top]                   # drop-line y per gap (grip)
            for i in range(n_rows):
                it = window[i]
                b, t, g, f, k = self._row_views(i)
                for v in (b, t, g, f, k):
                    v._tid = it.get("tid") or ""   # click-time re-resolution
                for v in (b, t, g):
                    v.setHidden_(False)
                # nested subtasks: checkbox AND title shift one INDENT per
                # level below the direct child; their box goes SQUARE and
                # small (matching the 13 pt text) and their row sits tighter
                # (Vex 2026-09-10)
                depth = max(1, it.get("depth", 1))
                nested = depth > 1
                z = self.zoom                          # this monitor's ⌘+/⌘− level
                x0 = self._x0 = max(30.0, 12 + 18 * z) # boxes slide right only if a zoomed grip needs it
                dx = INDENT * z * (depth - 1)
                rh = _row_h(it, z)
                mid = y_top - rh / 2.0                 # this row's centre line
                bw = (21 if nested else 24) * z        # checkbox hit box
                b.setFrame_(NSMakeRect(x0 + dx, mid - bw / 2.0, bw, bw))
                b.setImage_(sym_image("square" if nested else "circle",
                                      (SQUARE_PT if nested else CIRCLE_PT) * z))
                b.setContentTintColor_(GREEN)      # match the glow
                tfull = _disp(it["title"])
                t.setFont_(NSFont.systemFontOfSize_((SUB_FONT if nested else TASK_FONT) * z))
                t.setTitle_(tfull[:70])
                t.setToolTip_(tfull + "\nOpen in TickTick")
                t.setContentTintColor_(ROW_TEXT)
                th = (19 if nested else 22) * z
                tx = x0 + dx + bw + 8
                # right-hand icons take their room BEFORE the title: the
                # link sits in a fixed far-right column (the grip's mirror),
                # the fold chevron hugs the end of the text
                url = fsub.title_link(it["title"])
                folds = it.get("tid") in kid_tids
                kw, fw = 20 * z, 16 * z
                avail = max(24.0, w - tx - 12 - (kw + 6 if url else 0)
                            - (fw + 4 if folds else 0))
                t.setFrame_(NSMakeRect(tx, mid - th / 2.0, avail, th))
                k.setHidden_(not url)
                if url:
                    k.setImage_(sym_image("link", 12 * z))
                    k.setFrame_(NSMakeRect(w - 12 - kw, mid - 10 * z, kw, 20 * z))
                    k.setToolTip_(f"Run this link\n{url}")
                f.setHidden_(not folds)
                if folds:
                    shut = it.get("tid") in self.folded
                    f.setImage_(sym_image("chevron.right" if shut else "chevron.down", 10 * z))
                    f.setToolTip_("Unfold subtasks" if shut else "Fold subtasks")
                    # text width as DRAWN (a truncated title fills avail)
                    tw = self._text_w(t, avail)
                    f.setFrame_(NSMakeRect(tx + tw + 4, mid - 10 * z, fw, 20 * z))
                # grip: a fixed column in the free space LEFT of the
                # checkboxes (x 7.. - the boxes start at 30, unmoved at
                # 100%; Vex 2026-09-10: the right-hand grips ate title room)
                g.setImage_(sym_image("line.3.horizontal", 11 * z))
                g.setFrame_(NSMakeRect(7, mid - 10 * z, 18 * z, 20 * z))
                y_top -= rh
                self._gap_y.append(y_top)
                # no siblings = nowhere to go: the grip dims
                g.setAlphaValue_(1.0 if (len(fsub.sibling_gaps(
                    items, self.scroll_off + i)) > 2
                    or fsub.reparent_targets(items, it.get("tid"))) else 0.35)

        # overflow strip: "scroll ↑2 · ↓4" under the last row
        self.l_more.setHidden_(not overflow)
        if overflow:
            above = self.scroll_off
            below = len(items) - self.scroll_off - n_rows
            bits = ([f"↑ {above}"] if above else []) + ([f"↓ {below}"] if below else [])
            self.l_more.setStringValue_("scroll  " + " · ".join(bits))
            self.l_more.setFrame_(NSMakeRect(64, PAD_V * self.zoom + 1, w - 84, 13))
        self.tick_(None)

    # ── verbs ────────────────────────────────────────────────────────────
    def _xact_direct(self, verb, env_json=False):
        def run():
            env = dict(os.environ)
            if env_json:
                env["TICKAL_JSON"] = "1"
            try:
                r = subprocess.run([PY, XACT, f"xact:{verb}"], env=env,
                                   capture_output=True, text=True, timeout=30)
                return r.stdout.strip()
            except Exception as e:
                _log(f"direct {verb}: {e}")
                return ""
        return run

    def _xact_et(self, verb):
        def run():
            try:
                subprocess.run(
                    ["osascript", "-e",
                     'on run argv\n'
                     'tell application id "com.runningwithcrayons.Alfred" to '
                     'run trigger "XAct" in workflow "com.vex.tickal" '
                     'with argument (item 1 of argv)\nend run',
                     f"xact:{verb}"], capture_output=True, timeout=30)
            except Exception as e:
                _log(f"et {verb}: {e}")
        threading.Thread(target=run, daemon=True).start()

    def onDone_(self, sender):
        self._xact_et("focus_done")

    def onPauseResume_(self, sender):
        m = self.state
        if m["kind"] == "timer":
            verb = "focus_resume" if m["paused"] else "focus_pause"
            threading.Thread(target=self._xact_direct(verb), daemon=True).start()
            m["paused"] = not m["paused"]      # optimistic; poll confirms
            self._relayout()
        else:
            self._xact_et("pomo_toggle")

    def onStop_(self, sender):
        if self.state["kind"] == "timer":
            self._xact_et("focus_stop")
        else:
            self._xact_et("pomo_abandon")

    def onSticky_(self, sender):
        m = self.state
        if m["tid"]:
            self._xact_et(f"sticky:{m['pid']}:{m['tid']}")

    def onTitle_(self, sender):
        m = self.state
        if m["tid"]:
            subprocess.run(["open",
                            f"ticktick:///webapp/#p/{m['pid']}/tasks/{m['tid']}"],
                           check=False)

    def onItem_(self, sender):
        it = self._first_unchecked()
        if it and it.get("tid"):
            subprocess.run(["open",
                            f"ticktick:///webapp/#p/{it['pid']}/tasks/{it['tid']}"],
                           check=False)

    def onHide_(self, sender):
        if self._hot is not None:
            self._hot.disarm()          # hidden: no exit event will come
        self.panel.orderOut_(None)
        try:
            st = {}
            try:
                with open(BAR_STATE) as f:
                    st = json.load(f)
            except (OSError, ValueError):
                pass
            st["visible"] = False
            tmp = BAR_STATE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, BAR_STATE)
        except Exception as e:
            _log(f"hide: {e}")

    def onTick_(self, sender):
        self._do_tick(self._first_unchecked(), self.b_tick)

    def _row_item(self, sender):
        """Resolve the block item a row button addresses - by the tid stashed
        at relayout, so a poll-driven reshuffle between render and click can't
        retarget the action (index is only the freehand-row fallback)."""
        items = self.visible_items
        tid = getattr(sender, "_tid", "")
        if tid:
            return next((x for x in items if x.get("tid") == tid), None)
        i = sender.tag()
        return items[i] if i < len(items) else None

    def _open_url(self, url):
        """Run a link a task title carries (kmtrigger://, alfred://,
        ticktick://, https:// ...). `open` is the same door a click inside
        TickTick uses; the bar never interprets the target itself."""
        if not url:
            return
        try:
            subprocess.run(["open", url], check=False)
        except OSError as e:
            _log(f"open_url: {e}")

    def onLinkRow_(self, sender):
        it = self._row_item(sender)
        self._open_url(fsub.title_link((it or {}).get("title", "")))

    def onTitleLink_(self, sender):
        self._open_url(fsub.title_link(self.state.get("title") or ""))

    def onFoldRow_(self, sender):
        """Fold / unfold this row's subtasks. The tids live in the bar file,
        so a fold survives the bar exiting between sessions."""
        tid = getattr(sender, "_tid", "") or ""
        if not tid:
            return
        if tid in self.folded:
            self.folded = [t for t in self.folded if t != tid]
        else:
            self.folded = ([tid] + [t for t in self.folded if t != tid])[:FOLD_MAX]
        self._persist_origin()
        self._relayout()

    def onTickRow_(self, sender):
        it = self._row_item(sender)
        if it and not it["checked"]:
            self._do_tick(it, sender)

    def onOpenRow_(self, sender):
        it = self._row_item(sender)
        if it and it.get("tid"):
            subprocess.run(["open",
                            f"ticktick:///webapp/#p/{it['pid']}/tasks/{it['tid']}"],
                           check=False)

    # ── drag-drop reorder (the grip) ─────────────────────────────────────
    def _open_items(self):
        """The rows the bar shows (and drags): fsub.open_rows, minus the
        subtrees folded shut. ONE choke point, so relayout, the scroll cap
        and a grip drag always index the same list."""
        rows = fsub.open_rows((self.block or {}).get("items") or [])
        return fsub.fold_rows(rows, set(self.folded)) if self.folded else rows

    @objc.python_method
    def grip_down(self, grip, event):
        """Lift the row: remember its frames + the gaps its SIBLINGS allow
        (fsub.sibling_gaps - a drop never reparents), dim it, grab cursor."""
        if self._drag is not None or not self.expanded:
            return
        items = self._open_items()
        tid = getattr(grip, "_tid", "")
        i = next((k for k, x in enumerate(items) if x.get("tid") == tid), None)
        if i is None:
            return
        row = self._row_views(grip.tag())
        self._drag = {"i": i, "tid": tid, "row": row,
                      "frames": [v.frame() for v in row],
                      # the window is FROZEN for the drag: a wheel scroll
                      # mid-drag shifted scroll_off under the drawn line
                      "so": self.scroll_off, "gap_y": list(self._gap_y),
                      "y0": event.locationInWindow().y,
                      "gaps": fsub.sibling_gaps(items, i),
                      "depth": max(1, items[i].get("depth", 1)),
                      "order": tuple(x.get("tid") for x in items),
                      "pick": None,
                      # nesting: the UNFOLDED rows decide who may adopt it
                      # (a folded row still drags its hidden subtree along)
                      "x0": event.locationInWindow().x,
                      "targets": fsub.reparent_targets(
                          fsub.open_rows((self.block or {}).get("items") or []), tid),
                      "nest": False, "cand": None, "armed": None,
                      "cand_rect": None, "dwell": None}
        for v in row:
            v.setAlphaValue_(0.55)
        NSCursor.closedHandCursor().push()

    @objc.python_method
    def grip_dragged(self, grip, event):
        """The lifted row follows the pointer (clamped to the list); the
        green line snaps to the nearest VISIBLE gap its siblings allow."""
        d = self._drag
        if d is None:
            return
        y = event.locationInWindow().y
        H = self.panel.frame().size.height
        dy = y - d["y0"]
        nest = (event.locationInWindow().x - d["x0"] >= NEST_DX * self.zoom
                and bool(d["targets"]))
        nx = INDENT * self.zoom if nest else 0.0     # the row leans in: "nest"
        for v, fr in zip(d["row"], d["frames"]):
            ny = max(-6.0, min(H - ROW1_H - fr.size.height + 6.0, fr.origin.y + dy))
            v.setFrameOrigin_((fr.origin.x + nx, ny))
        if nest:
            d["nest"] = True
            d["pick"] = None                 # a nest drop is never also a reorder
            self.drop_line.setHidden_(True)
            self._nest_hover(d, y, H)
            return
        if d["nest"]:
            self._nest_clear(d)
        best = None
        for g, tgt in d["gaps"]:
            gv = g - d["so"]
            if gv < 0 or gv >= len(d["gap_y"]):
                continue
            gy = d["gap_y"][gv]                   # the top edge of visible row gv
            if best is None or abs(gy - y) < best[0]:
                best = (abs(gy - y), g, tgt, gy)
        if best is None:
            return
        _dist, g, tgt, gy = best
        changed = d["pick"] != (g, tgt)          # a NEW landing spot → flare
        d["pick"] = (g, tgt)
        x0 = self._x0 + INDENT * self.zoom * (d["depth"] - 1)   # at the siblings' indent
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            self.drop_line.setFrame_(NSMakeRect(x0, gy - 0.75, max(20.0, self.W - x0 - 12), 1.5))
            self._drop_grad.setFrame_(self.drop_line.bounds())
            self.drop_line.setHidden_(False)
        finally:
            CATransaction.commit()
        if changed:
            self._pulse_drop_line()

    @objc.python_method
    def _nest_hover(self, d, y, H):
        """Which row the pointer rests on while nesting. The header row is
        the focus task itself (fsub.ROOT - how a nested row gets back out);
        a list row is a candidate only if fsub.reparent_targets allows it.
        A NEW candidate restarts the dwell; staying on it arms it."""
        cand, rect = None, None
        if y >= H - ROW1_H:
            if fsub.ROOT in d["targets"]:
                cand = fsub.ROOT
                rect = NSMakeRect(8.0, H - ROW1_H + 4.0, self.W - 16.0, ROW1_H - 8.0)
        else:
            gy, vis = d["gap_y"], self._open_items()
            for v in range(len(gy) - 1):
                if gy[v + 1] < y <= gy[v]:
                    k = v + d["so"]
                    tid = vis[k].get("tid") if k < len(vis) else None
                    if tid and tid in d["targets"]:
                        cand = tid
                        x = max(4.0, self._x0 - 10.0)
                        rect = NSMakeRect(x, gy[v + 1] + 1.0, self.W - x - 8.0,
                                          gy[v] - gy[v + 1] - 2.0)
                    break
        if cand == d["cand"]:
            return
        self._nest_clear(d, keep_mode=True)
        d["cand"], d["cand_rect"] = cand, rect
        if cand is None:
            return
        self._nest_show(rect, armed=False)
        t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            NEST_DWELL, self, "armNest:", cand or "root", False)
        # COMMON modes: a timer in the default mode alone can stall while the
        # mouse button is held, which is exactly when this one has to fire
        NSRunLoop.currentRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
        d["dwell"] = t

    def armNest_(self, timer):
        """The dwell ran out on the same candidate: arm it (full glow + a
        flare - 'let go now and it nests here')."""
        d = self._drag
        if d is None or not d["nest"]:
            return
        cand = str(timer.userInfo() or "")
        cand = fsub.ROOT if cand == "root" else cand
        if cand != d["cand"] or d["cand_rect"] is None:
            return
        d["armed"], d["dwell"] = cand, None
        self._nest_show(d["cand_rect"], armed=True)

    @objc.python_method
    def _nest_show(self, rect, armed):
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        try:
            self.nest_glow.setFrame_(rect)
            self.nest_glow.setAlphaValue_(1.0 if armed else 0.35)
            self.nest_glow.setHidden_(False)
        finally:
            CATransaction.commit()
        if armed:
            try:
                a = CAKeyframeAnimation.animationWithKeyPath_("shadowRadius")
                a.setValues_([9.0, 20.0, 9.0])
                a.setKeyTimes_([0.0, 0.25, 1.0])
                a.setDuration_(0.45)
                self.nest_glow.layer().addAnimation_forKey_(a, "nestFlare")
            except Exception as e:
                _log(f"nest flare: {e}")

    @objc.python_method
    def _nest_clear(self, d, keep_mode=False):
        """Drop the candidate: stop its dwell timer, hide the glow. keep_mode
        stays in nesting (the pointer moved to another row); otherwise the
        drag has gone back LEFT and reordering resumes."""
        t = d.get("dwell")
        if t is not None:
            t.invalidate()
        d["dwell"], d["cand"], d["armed"], d["cand_rect"] = None, None, None, None
        self.nest_glow.setHidden_(True)
        if not keep_mode:
            d["nest"] = False

    @objc.python_method
    def _nest_to(self, tid, target):
        """OPTIMISTIC local nest first (fsub.reparent_block - the row and its
        subtree land under the new parent the instant you let go), then the
        authoritative xact fx_parent write in the background, serialized on
        _rmw_lock with every other live write, exactly like _reorder_to. A
        folded target unfolds so you see where it went."""
        items = (self.block or {}).get("items") or []
        open_ = fsub.open_rows(items)
        others = [x for x in items if not any(x is o for o in open_)]
        self.block["items"] = fsub.reparent_block(open_, tid, target) + others
        if target and target in self.folded:
            self.folded = [t for t in self.folded if t != target]
            self._persist_origin()
        self.mutation_seq += 1          # drop in-flight stale polls
        self._relayout_pending = False
        self._relayout()
        runner = self._xact_direct(f"fx_parent:{tid}:{target or 'root'}")

        def work():
            with self._rmw_lock:
                out = runner()
            if "reparented" not in (out or ""):
                _log(f"nest {tid[:8]} -> {(target or 'root')[:8]}: {(out or 'no output')[:120]!r}")
                last = (out or "").strip().splitlines()[-1:] or [""]
                self._xact_et("notify:" + (
                    last[0] if last[0].startswith("🎯")
                    else "🎯 Nest didn't stick · TickTick rate limit, try "
                         "again in a minute"))
            self.mutation_seq += 1
            self.content_dirty.set()

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _pulse_drop_line(self):
        """A brief neon flare each time the line lands on a NEW gap (Vex
        2026-09-10): the halo blooms, the line thickens and goes full green,
        then all three settle (~0.45 s) - 'this is a valid drop'."""
        try:
            times = [0.0, 0.2, 1.0]

            def kf(path, values):
                a = CAKeyframeAnimation.animationWithKeyPath_(path)
                a.setValues_(values)
                a.setKeyTimes_(times)
                a.setDuration_(0.45)
                return a
            layer = self.drop_line.layer()
            layer.addAnimation_forKey_(kf("shadowOpacity", [0.0, 1.0, 0.0]), "flareGlow")
            layer.addAnimation_forKey_(kf("transform.scale.y", [1.0, 2.2, 1.0]), "flareThick")
            self._drop_grad.addAnimation_forKey_(
                kf("colors", [self._drop_colors, self._drop_bright, self._drop_colors]),
                "flareColor")
        except Exception as e:
            _log(f"drop flare: {e}")

    @objc.python_method
    def grip_up(self, grip, event):
        """Drop: a real move → _reorder_to; a no-op drop, a drag with no
        gap, or a list that CHANGED mid-drag (a poll landed) just re-lays
        out - never guess a slot on a reshuffled list."""
        d, self._drag = self._drag, None
        if d is None:
            return
        NSCursor.pop()
        self.drop_line.setHidden_(True)
        for v in d["row"]:
            v.setAlphaValue_(1.0)
        items = self._open_items()
        if d["nest"]:
            armed = d["armed"]
            self._nest_clear(d)
            # only an ARMED target nests, and never on a list that changed
            # mid-drag (a poll landed): same rule as the reorder below
            if armed is not None and tuple(x.get("tid") for x in items) == d["order"]:
                self._nest_to(d["tid"], armed)
                return
            self._relayout_pending = False
            self._relayout()
            return
        pick = d["pick"]
        if pick and tuple(x.get("tid") for x in items) == d["order"]:
            g, tgt = pick
            par = fsub._parents(items)
            sibs = [k for k in range(len(items)) if par[k] == par[d["i"]]]
            cur = sibs.index(d["i"])
            if tgt != cur:
                rest = [items[k].get("tid") for k in sibs if k != d["i"]]
                self._reorder_to(d["i"], g, fsub.drop_anchor(rest, tgt))
                return
        self._relayout_pending = False
        self._relayout()

    @objc.python_method
    def _reorder_to(self, i, g, anchor):
        """OPTIMISTIC local move first (the row + its subtree land the
        instant you let go, same trick as _do_tick), then the authoritative
        xact fx_move <after|before>:<anchor tid> write in the background -
        an ANCHOR, not a slot, so a list changed server-side between polls
        can't misplace it - serialized on _rmw_lock so quick drags stack
        instead of racing; a fresh poll reconciles."""
        items = (self.block or {}).get("items") or []
        open_ = fsub.open_rows(items)
        others = [x for x in items if not any(x is o for o in open_)]
        tid = open_[i].get("tid")
        if not tid:
            return
        self.block["items"] = fsub.move_block(open_, i, g) + others
        self.mutation_seq += 1          # drop in-flight stale polls
        self._relayout_pending = False
        self._relayout()
        direction = f"{anchor[0]}:{anchor[1]}"
        runner = self._xact_direct(f"fx_move:{tid}:{direction}")

        def work():
            with self._rmw_lock:        # queue behind other live writes
                out = runner()
            if "reordered" not in (out or ""):
                # the write DIDN'T land (rate limit around the hourly sync
                # burst was the silent 70%-revert bug - the subprocess
                # printed its error to a discarded stdout while the poll
                # faithfully restored the server's unchanged order)
                _log(f"move {direction} {tid[:8]}: {(out or 'no output')[:120]!r}")
                last = (out or "").strip().splitlines()[-1:] or [""]
                self._xact_et("notify:" + (
                    last[0] if last[0].startswith("🎯")   # the backend said why
                    else "🎯 Move didn't stick · TickTick rate limit, try "
                         "again in a minute"))
            # either way: polls that READ before this point are stale - bump
            # so they drop at apply, then force one authoritative re-read
            self.mutation_seq += 1
            self.content_dirty.set()

        threading.Thread(target=work, daemon=True).start()

    def onScroll_(self, event):
        """Wheel over the bar: slide the expanded checkbox window."""
        if self._drag is not None:      # the window is frozen mid-drag
            return
        if event.modifierFlags() & (1 << 20):     # ⌘ held: zoom, not scroll
            try:
                if event.momentumPhase():         # a flick's coast must not sweep 70-200%
                    return
                if event.phase() & 0x1:           # a fresh scroll gesture
                    self._zoom_accum = 0.0
                dy = event.scrollingDeltaY()
            except Exception:
                dy = event.deltaY() * 10
            self._zoom_accum += dy
            if self._zoom_accum >= 12:            # one step per event at most
                self._zoom_accum -= 12
                self._zoom_step(1)
            elif self._zoom_accum <= -12:
                self._zoom_accum += 12
                self._zoom_step(-1)
            return
        items = self._open_items()
        cap = self._cap(False, items)
        if not (self.expanded and len(items) > cap):
            return
        try:
            dy = event.scrollingDeltaY()
        except Exception:
            dy = event.deltaY() * 10
        self._scroll_accum += dy
        step = 0
        while self._scroll_accum >= 12:
            step -= 1
            self._scroll_accum -= 12
        while self._scroll_accum <= -12:
            step += 1
            self._scroll_accum += 12
        if step:
            self.scroll_off = max(0, min(self.scroll_off + step, len(items) - cap))
            self._relayout()

    def onExpand_(self, sender):
        self.expanded = not self.expanded
        self._relayout()

    def _do_tick(self, it, glyph_view):
        if self.pending_tick:
            return                        # double-click guard
        m = self.state
        if not (m["attributed"] and it):
            return
        self.mutation_seq += 1
        seq = self.mutation_seq
        self.pending_tick = (it.get("tid"), seq, time.monotonic())
        # optimistic apply + confetti at the glyph
        it["checked"] = True
        self.block["done"] += 1
        self.confetti(glyph_view)
        self._relayout()
        ctid = it.get("tid") or ""
        verb = f"fx_tick:{m['pid']}:{m['tid']}" + (f":{ctid}" if ctid else "")
        runner = self._xact_direct(verb, env_json=True)

        def work():
            with self._rmw_lock:        # never race a queued reorder write
                out = runner()
            try:
                data = json.loads(out.splitlines()[-1]) if out else {}
            except ValueError:
                data = {}
            AppHelper.callAfter(self.reconcile_, (data, seq))
        threading.Thread(target=work, daemon=True).start()

    def reconcile_(self, payload):
        data, seq = payload
        if seq != self.mutation_seq:
            return
        self.pending_tick = None
        if data.get("ok"):
            self.block = {"done": data.get("done", 0),
                          "total": data.get("total", 0),
                          "items": data.get("items", []),
                          "date": data.get("date")}
            self.content_last_change = time.monotonic()
        else:
            _log(f"tick failed: {data}")
            self.content_dirty.set()      # revert via a fresh poll
        self._relayout()

    # ── confetti ─────────────────────────────────────────────────────────
    def confetti(self, glyph_view=None):
        try:
            import math
            fr = (glyph_view or self.b_tick).frame()
            fxl = CAEmitterLayer.layer()
            fxl.setEmitterPosition_((fr.origin.x + fr.size.width / 2.0,
                                     fr.origin.y + fr.size.height / 2.0))
            fxl.setEmitterShape_(kCAEmitterLayerPoint)
            fxl.setZPosition_(50)
            fxl.setBeginTime_(CACurrentMediaTime())   # CRITICAL: no back-dating
            cells = []
            for col in (NSColor.systemPinkColor(), NSColor.systemYellowColor(),
                        NSColor.systemTealColor(), NSColor.systemGreenColor()):
                c = CAEmitterCell.emitterCell()
                c.setContents_(_dot_cgimage(col))
                c.setBirthRate_(140.0)
                c.setLifetime_(1.1)
                c.setLifetimeRange_(0.3)
                c.setVelocity_(190.0)
                c.setVelocityRange_(70.0)
                c.setEmissionRange_(2 * math.pi)
                c.setScale_(0.8)
                c.setScaleRange_(0.4)
                c.setAlphaSpeed_(-1.0)
                c.setYAcceleration_(-320.0)
                c.setSpin_(4.0)
                c.setSpinRange_(8.0)
                cells.append(c)
            fxl.setEmitterCells_(cells)
            self.overlay.layer().addSublayer_(fxl)
            AppHelper.callLater(0.18, lambda: fxl.setBirthRate_(0.0))
            AppHelper.callLater(1.5, fxl.removeFromSuperlayer)
        except Exception as e:
            _log(f"confetti: {e}")

    # ── shutdown ─────────────────────────────────────────────────────────
    def shutdown(self):
        try:
            if self._hot is not None:
                self._hot.disarm()
            self._persist_origin()
            if self.timer:
                self.timer.invalidate()
        except Exception:
            pass
        AppHelper.stopEventLoop()


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ctrl = BarController.alloc().init()
    m = ctrl.state
    if m["kind"] != "idle" and m["visible"]:
        ctrl.panel.orderFrontRegardless()
    ctrl._relayout()
    ctrl.content_dirty.set()

    def on_term(signum, frame):
        AppHelper.callAfter(ctrl.shutdown)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    _log("bar up")
    AppHelper.runEventLoop()
    _log("bar down")


if __name__ == "__main__":
    main()
