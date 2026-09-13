#!/usr/bin/env python3
"""confetti.py - a one-shot screen-wide confetti burst, then gone.

Vex 2026-09-13: "It would be nice if our complete function on routines
produces confetti on screen". Fired by xact.routine_checkin, which every
routine completion road already calls (the ⇧ done chord, the [Finish …]
link, the focus bar's ●), so a routine celebrates the same way however it
was finished.

A transparent, borderless, CLICK-THROUGH window over the screen the pointer
is on, above everything (full-screen apps included), that never takes focus.
Two cannons fire up and inward from the bottom corners in the focus bar's
own palette and dot, then the process exits. Nothing is written anywhere.

Needs PyObjC, so it is spawned with xact._bar_python() - the same python the
focus bar runs on. `--hold N` keeps it N seconds (a test hook).
"""
import math
import sys

try:
    import objc                              # noqa: F401
    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory, NSWindow,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered, NSColor,
        NSScreen, NSEvent, NSImage, NSMakeRect, NSMakeSize, NSBezierPath,
        NSScreenSaverWindowLevel,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorIgnoresCycle, NSView,
    )
    from Quartz import (CAEmitterLayer, CAEmitterCell, CACurrentMediaTime,
                        kCAEmitterLayerPoint)
    from PyObjCTools import AppHelper
except ImportError as e:
    sys.stderr.write(f"confetti: PyObjC missing ({e})\n")
    sys.exit(3)

BURST_S = 0.35        # how long the cannons fire
LIFE_S = 2.6          # when the window closes and the process exits
PALETTE = ("systemPinkColor", "systemYellowColor", "systemTealColor",
           "systemGreenColor", "systemPurpleColor", "systemOrangeColor")


def _dot(color, d=10):
    """The focus bar's confetti dot (focus_bar._dot_cgimage), a little larger
    for a whole screen."""
    img = NSImage.alloc().initWithSize_(NSMakeSize(d, d))
    img.lockFocus()
    color.set()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(0, 0, d, d)).fill()
    img.unlockFocus()
    cg = img.CGImageForProposedRect_context_hints_(None, None, None)
    return cg[0] if isinstance(cg, tuple) else cg     # PyObjC may hand a tuple


def _screen_under_pointer():
    p = NSEvent.mouseLocation()
    for s in NSScreen.screens():
        f = s.frame()
        if (f.origin.x <= p.x < f.origin.x + f.size.width
                and f.origin.y <= p.y < f.origin.y + f.size.height):
            return s
    return NSScreen.mainScreen()


def _cannon(x, y, angle, scale):
    """One emitter at (x, y) firing along `angle` (radians, 0 = right)."""
    layer = CAEmitterLayer.layer()
    layer.setEmitterPosition_((x, y))
    layer.setEmitterShape_(kCAEmitterLayerPoint)
    layer.setBeginTime_(CACurrentMediaTime())     # no back-dated first frame
    cells = []
    for name in PALETTE:
        c = CAEmitterCell.emitterCell()
        c.setContents_(_dot(getattr(NSColor, name)()))
        c.setBirthRate_(90.0)
        c.setLifetime_(2.4)
        c.setLifetimeRange_(0.5)
        c.setVelocity_(1150.0 * scale)
        c.setVelocityRange_(380.0 * scale)
        c.setEmissionLongitude_(angle)
        c.setEmissionRange_(math.pi / 7)
        c.setYAcceleration_(-1250.0 * scale)
        c.setScale_(0.9)
        c.setScaleRange_(0.5)
        c.setSpin_(5.0)
        c.setSpinRange_(10.0)
        c.setAlphaSpeed_(-0.35)
        cells.append(c)
    layer.setEmitterCells_(cells)
    return layer


def main():
    hold = LIFE_S
    if "--hold" in sys.argv:
        try:
            hold = float(sys.argv[sys.argv.index("--hold") + 1])
        except (IndexError, ValueError):
            pass
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # no Dock icon

    screen = _screen_under_pointer()
    frame = screen.frame()
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)
    win.setIgnoresMouseEvents_(True)            # clicks go straight through
    win.setLevel_(NSScreenSaverWindowLevel)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle)
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width,
                                                    frame.size.height))
    view.setWantsLayer_(True)
    win.setContentView_(view)

    w, h = frame.size.width, frame.size.height
    scale = max(0.6, min(1.6, h / 900.0))       # the same arc on a laptop or a 4K panel
    cannons = [_cannon(w * 0.04, 0.0, math.radians(62), scale),
               _cannon(w * 0.96, 0.0, math.radians(118), scale)]
    if w / max(h, 1.0) > 2.0:
        # an ultrawide panel leaves the middle empty between two corner
        # cannons (seen on Vex's screen, 2026-09-13) - one more straight up
        cannons.append(_cannon(w * 0.5, 0.0, math.radians(90), scale))
    for c in cannons:
        view.layer().addSublayer_(c)
    win.orderFrontRegardless()                  # show without stealing focus

    def stop_firing():
        for c in cannons:
            c.setBirthRate_(0.0)

    AppHelper.callLater(BURST_S, stop_firing)
    AppHelper.callLater(hold, lambda: AppHelper.stopEventLoop())
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
