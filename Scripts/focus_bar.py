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
ROW2_H = 38
CHK_H  = 28      # expanded subtask rows pack tight
RADIUS = 20.0
IDLE_EXIT_S = 10


# ── model (pure - probe-testable) ────────────────────────────────────────────
def read_state():
    """One snapshot of the session world (no AppKit)."""
    m = {"kind": "idle", "attributed": False, "pid": "", "tid": "",
         "title": "", "paused": False, "visible": True, "focus_st": None,
         "pomo_remaining": 0}
    try:
        with open(BAR_STATE) as f:
            m["visible"] = bool(json.load(f).get("visible", True))
    except (OSError, ValueError):
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
_lock_f = open(BAR_LOCK, "w")
try:
    fcntl.flock(_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)          # another bar already runs - correct outcome
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
        NSTextAlignmentLeft, NSTextAlignmentRight,
    )
    from AppKit import NSView            # noqa: E402
    from Quartz import (                 # noqa: E402
        CAEmitterLayer, CAEmitterCell, CACurrentMediaTime, kCAEmitterLayerPoint,
        CALayer,
    )
    from PyObjCTools import AppHelper    # noqa: E402
except ImportError as e:
    sys.stderr.write(f"focus_bar: PyObjC missing ({e}) · pip3 install pyobjc\n")
    sys.exit(3)


def _log(msg):
    sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


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


class PillButton(NSButton):
    def acceptsFirstMouse_(self, event):  # act on the first click
        return True


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
        self.expanded = False           # chevron: full subtask list
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
            rect, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
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
        glow = CALayer.layer()
        glow.setBorderWidth_(1.0)
        glow.setBorderColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.15, 0.72, 0.45, 0.4).CGColor())
        glow.setCornerRadius_(RADIUS)
        glow.setMaskedCorners_(3)
        glow.setShadowColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.15, 0.8, 0.45, 1.0).CGColor())
        glow.setShadowOpacity_(0.5)
        glow.setShadowRadius_(5.0)
        glow.setShadowOffset_((0, 0))
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
        self.l_clock = label(23, mono=True,   # dominant but not shiny
                             color=NSColor.colorWithWhite_alpha_(0.68, 1.0))
        self.l_clock.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(
            23, NSFontWeightSemibold))
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

        self._restore_origin()

        from Foundation import NSNotificationCenter, NSProcessInfo
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowMoved:", "NSWindowDidMoveNotification", panel)
        NSWorkspace.sharedWorkspace().notificationCenter(
        ).addObserver_selector_name_object_(
            self, "didWake:", "NSWorkspaceDidWakeNotification", None)
        # Keep the 1 s timer honest when occluded (App Nap coalescing)
        self._activity = NSProcessInfo.processInfo(
        ).beginActivityWithOptions_reason_(0x00FFFFFF, "focus bar timers")
        self._move_save_at = 0

    # ── geometry / visibility ────────────────────────────────────────────
    def _restore_origin(self):
        try:
            with open(BAR_STATE) as f:
                ox, oy = json.load(f).get("origin", [None, None])
        except (OSError, ValueError, TypeError):
            ox = oy = None
        scr = NSScreen.mainScreen()
        vf = scr.visibleFrame() if scr else None
        ok = False
        if ox is not None and oy is not None:
            for s in NSScreen.screens():
                f = s.frame()
                if (f.origin.x - 10 <= ox <= f.origin.x + f.size.width - 60
                        and f.origin.y - 10 <= oy <= f.origin.y + f.size.height):
                    ok = True
                    break
        if not ok and vf:
            ox = vf.origin.x + (vf.size.width - W) / 2.0
            oy = vf.origin.y + vf.size.height - 70
        self.panel.setFrameOrigin_((ox or 100, oy or 100))

    def windowMoved_(self, note):
        self._move_save_at = time.monotonic() + 0.6   # debounce; saved by tick

    def _persist_origin(self):
        try:
            o = self.panel.frame().origin
            st = {}
            try:
                with open(BAR_STATE) as f:
                    st = json.load(f)
            except (OSError, ValueError):
                pass
            st["origin"] = [o.x, o.y]
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
            if m["kind"] == "timer" and m["focus_st"]:
                self.l_clock.setStringValue_(
                    "⏸ " + fmt_timer(xact.focus_elapsed(m["focus_st"]))
                    if m["paused"] else fmt_timer(xact.focus_elapsed(m["focus_st"])))
            elif m["kind"] == "pomo":
                rem, at = self._pomo_anchor
                left = rem if m["paused"] else rem - (time.monotonic() - at)
                self.l_clock.setStringValue_(
                    ("⏸ " if m["paused"] else "") + fmt_pomo(left))
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
                # ONE project-data GET: open children (titles + sortOrder)
                # plus the focus task's childIds - completed children stay
                # in childIds (verified), so done = childIds minus open.
                data = api.get_project_data(pid)
                tasks = data.get("tasks") or []
                open_children = [t for t in tasks
                                 if t.get("parentId") == tid]
                focus = next((t for t in tasks if t.get("id") == tid), None)
                if focus is None:   # completed mid-session stays GET-able
                    focus = api.get_task(pid, tid)
                summary = fsub.children_summary(
                    open_children, focus.get("childIds") or [])
                AppHelper.callAfter(self.applyBlock_, (summary, seq))
            except Exception as e:
                _log(f"content_loop: {e}")
                # Back off hard on rate limits (TickTick also enforces
                # 100 req/min), gently otherwise.
                time.sleep(60 if "rate limit" in str(e).lower() else 15)

    def _content_interval(self):
        return 5.0 if (time.monotonic() - self.content_last_change) < 600 else 20.0

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
            self.content_dirty.set()
        if m["visible"] and m["kind"] != "idle":
            if not self.panel.isVisible():
                self.panel.orderFrontRegardless()
        else:
            if self.panel.isVisible():
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
        """Lazily-built (circle, title, top, up, down, bottom) 6-tuple for
        expanded item row i - the last four are the ⤒↑↓⤓ reorder arrows."""
        while len(self.row_pool) <= i:
            idx = len(self.row_pool)
            b = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 26, 26))
            b.setBordered_(False)
            b.setTitle_("")
            b.setImage_(sym_image("circle", 15))
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
            arrows = []
            for sym, action, tip in (
                    ("arrow.up.to.line", "onRowTop:", "Send to top"),
                    ("chevron.up", "onRowUp:", "Move up"),
                    ("chevron.down", "onRowDown:", "Move down"),
                    ("arrow.down.to.line", "onRowBottom:", "Send to bottom")):
                btn = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 14, 20))
                btn.setBordered_(False)
                btn.setTitle_("")
                btn.setImage_(sym_image(sym, 9, weight=NSFontWeightBold))
                btn.setContentTintColor_(NSColor.tertiaryLabelColor())
                btn.setTarget_(self)
                btn.setAction_(action)
                btn.setTag_(idx)
                btn.setToolTip_(tip)
                self.fx.addSubview_(btn)
                arrows.append(btn)
            self.row_pool.append((b, t, *arrows))
        return self.row_pool[i]

    MAX_ROWS = 10

    def _relayout(self):
        m = self.state
        if m["kind"] == "idle":
            return
        att = m["attributed"]
        all_items = (self.block or {}).get("items", []) if att else []
        # ticked rows leave the BAR - the description keeps them
        items = [it for it in all_items if not it["checked"]]
        nxt = self._first_unchecked() if att else None
        expanded = self.expanded and bool(items)
        overflow = expanded and len(items) > self.MAX_ROWS
        self.scroll_off = max(0, min(self.scroll_off,
                                     max(0, len(items) - self.MAX_ROWS)))
        window = items[self.scroll_off:self.scroll_off + self.MAX_ROWS] if expanded else []
        self.visible_items = window
        n_rows = len(window) if expanded else (1 if all_items else 0)
        H = (ROW1_H + (CHK_H if expanded else ROW2_H) * n_rows
             + (16 if overflow else 0))

        # dynamic width: fit title + clock + buttons
        title_w = 0.0
        if att:
            full = _disp(m["title"]) or "Task"   # links render as [name]🔗
            self.t_title.setTitle_(full[:60])
            self.t_title.setToolTip_(full + "\nOpen in TickTick")
            title_w = min(340.0, max(60.0, self.t_title.intrinsicContentSize().width + 10))
        btn_w = 29 + 29 + ((29 + 29) if att else 0) + 27 + (27 if items else 0)
        left_w = 16 + ((30 + 8 + title_w + 12) if att else 0)
        clock_w = 96
        W_new = max(420.0, min(880.0, left_w + clock_w + 18 + btn_w + 14))
        self.W = W_new
        w = W_new

        fr = self.panel.frame()
        if int(fr.size.height) != H or int(fr.size.width) != int(w):
            # grow/shrink DOWNWARD + rightward: keep the top-left corner put
            top = fr.origin.y + fr.size.height
            self.panel.setFrame_display_(NSMakeRect(fr.origin.x, top - H, w, H), True)
        y1 = H - ROW1_H + (ROW1_H - 28) / 2.0   # row-1 controls baseline

        # two-tone chrome
        one = (n_rows == 0)
        self.bg_top.setFrame_(NSMakeRect(0, H - ROW1_H, w, ROW1_H))
        self.bg_top.layer().setMaskedCorners_(15 if one else 12)  # all / top only
        self.bg_bot.setHidden_(one)
        if not one:
            self.bg_bot.setFrame_(NSMakeRect(0, 0, w, H - ROW1_H))
            self.glow.setFrame_(NSMakeRect(0, 0, w, H - ROW1_H))

        x = 16
        for v, show in ((self.b_done, att), (self.t_title, att)):
            v.setHidden_(not show)
        if att:
            self.b_done.setFrame_(NSMakeRect(x, y1 - 1, 30, 30))
            x += 38
            self.t_title.setFrame_(NSMakeRect(x, y1, title_w, 28))
            x += title_w + 12
        # right side, right→left - near-touching button run, clock set apart
        rx = w - 14
        rx -= 26
        self.b_chev.setHidden_(not items)
        if items:
            self.b_chev.setImage_(sym_image("chevron.up" if expanded else "chevron.down", 14))
            self.b_chev.setToolTip_("Collapse" if expanded else "Show every subtask")
            self.b_chev.setFrame_(NSMakeRect(rx, y1, 26, 28))
            rx -= 27
        self.b_min.setFrame_(NSMakeRect(rx, y1, 26, 28))
        rx -= 29
        self.b_sticky.setHidden_(not att)
        if att:
            self.b_sticky.setFrame_(NSMakeRect(rx, y1, 28, 28))
            rx -= 29
        self.b_stop.setFrame_(NSMakeRect(rx, y1, 28, 28))
        rx -= 29
        self.b_pause.setFrame_(NSMakeRect(rx, y1, 28, 28))
        self.b_pause.setImage_(sym_image("play.fill" if m["paused"] else "pause.fill", 15))
        rx -= 18 + clock_w                       # separation before the clock
        self.l_clock.setFrame_(NSMakeRect(rx, y1, clock_w, 28))

        # collapsed row 2: first unchecked + counter ("All done 🎉" needs the
        # UNfiltered list - with every row ticked, `items` is empty)
        two = (not expanded) and bool(all_items)
        for v, show in ((self.b_tick, two and bool(nxt)),
                        (self.t_item, two), (self.l_count, two)):
            v.setHidden_(not show)
        if two:
            # lower rows sit indented (~25%) under the title
            y2 = (ROW2_H - 26) / 2.0
            self.b_tick.setFrame_(NSMakeRect(30, y2, 26, 26))
            done, total = self.block["done"], self.block["total"]
            self.l_count.setFrame_(NSMakeRect(w - 72, y2 + 3, 56, 20))
            self.l_count.setStringValue_(f"{done}/{total}")
            if nxt:
                nfull = _disp(nxt["title"])
                self.t_item.setTitle_(nfull[:70])
                self.t_item.setToolTip_(nfull + "\nOpen in TickTick")
                self.t_item.setContentTintColor_(NSColor.secondaryLabelColor())
            else:
                self.t_item.setTitle_("All done 🎉")
                self.t_item.setContentTintColor_(GREEN)
            self.t_item.setFrame_(NSMakeRect(64, y2 + 1, w - 64 - 76, 24))

        # expanded: the scrolled window of UNchecked boxes, top→bottom, each
        # with ⤒↑↓⤓ reorder buttons
        for i, views in enumerate(self.row_pool):
            show = expanded and i < n_rows
            for v in views:
                v.setHidden_(not show)
        if expanded:
            for i in range(n_rows):
                it = window[i]
                b, t, top, up, dn, bot = self._row_views(i)
                for v in (b, t, top, up, dn, bot):
                    v.setHidden_(False)
                    v._tid = it.get("tid") or ""   # click-time re-resolution
                ry = H - ROW1_H - CHK_H * (i + 1) + (CHK_H - 26) / 2.0
                b.setFrame_(NSMakeRect(30, ry, 26, 26))
                b.setImage_(sym_image("circle", 15))
                b.setContentTintColor_(GREEN)      # match the glow
                tfull = _disp(it["title"])
                t.setTitle_(tfull[:70])
                t.setToolTip_(tfull + "\nOpen in TickTick")
                t.setContentTintColor_(NSColor.secondaryLabelColor())
                t.setFrame_(NSMakeRect(64, ry + 1, w - 64 - 70, 24))
                abs_i = self.scroll_off + i
                for k, v in enumerate((top, up, dn, bot)):
                    v.setFrame_(NSMakeRect(w - 63 + 14 * k, ry + 3, 14, 20))
                for v in (top, up):
                    v.setEnabled_(abs_i > 0)
                for v in (dn, bot):
                    v.setEnabled_(abs_i < len(items) - 1)

        # overflow strip: "scroll ↑2 · ↓4" under the last row
        self.l_more.setHidden_(not overflow)
        if overflow:
            above = self.scroll_off
            below = len(items) - self.scroll_off - n_rows
            bits = ([f"↑ {above}"] if above else []) + ([f"↓ {below}"] if below else [])
            self.l_more.setStringValue_("scroll  " + " · ".join(bits))
            self.l_more.setFrame_(NSMakeRect(64, 1, w - 84, 13))
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

    def onRowUp_(self, sender):
        self._move_row(sender, "up")

    def onRowDown_(self, sender):
        self._move_row(sender, "down")

    def onRowTop_(self, sender):
        self._move_row(sender, "top")

    def onRowBottom_(self, sender):
        self._move_row(sender, "bottom")

    def _move_row(self, sender, direction):
        """⤒↑↓⤓ reorder: OPTIMISTIC local move first - the bar
        moves the instant you click, same trick as _do_tick - then the
        authoritative xact fx_move write lands in the background (serialized
        on _rmw_lock so rapid clicks stack instead of racing) and a fresh
        poll reconciles. Unchecked items permute among their own slots."""
        it = self._row_item(sender)
        if not (it and it.get("tid")):
            return
        tid = it["tid"]
        items = (self.block or {}).get("items") or []
        un = [k for k, it in enumerate(items) if not it["checked"]]
        pos = next((p for p, k in enumerate(un) if items[k].get("tid") == tid), None)
        if pos is None:
            return
        tgt = {"up": pos - 1, "down": pos + 1,
               "top": 0, "bottom": len(un) - 1}[direction]
        if tgt == pos or tgt < 0 or tgt >= len(un):
            return
        vals = [items[k] for k in un]
        vals.insert(tgt, vals.pop(pos))
        for k, v in zip(un, vals):
            items[k] = v
        self.mutation_seq += 1          # drop in-flight stale polls
        self._relayout()
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
                self._xact_et("notify:🎯 Move didn't stick · TickTick "
                              "rate limit, try again in a minute")
            # either way: polls that READ before this point are stale - bump
            # so they drop at apply, then force one authoritative re-read
            self.mutation_seq += 1
            self.content_dirty.set()

        threading.Thread(target=work, daemon=True).start()

    def onScroll_(self, event):
        """Wheel over the bar: slide the expanded checkbox window."""
        items = [it for it in ((self.block or {}).get("items") or [])
                 if not it["checked"]]
        if not (self.expanded and len(items) > self.MAX_ROWS):
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
            self.scroll_off = max(0, min(self.scroll_off + step,
                                         len(items) - self.MAX_ROWS))
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
