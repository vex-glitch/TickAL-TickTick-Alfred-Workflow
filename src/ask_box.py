"""ask_box.py - the long-answer box.

AppleScript's `display dialog` field is ONE LINE. It does not wrap, you
cannot see what you already wrote, and Return submits instead of starting a
paragraph. Vex 2026-09-16: "I will type and type in there, I consider it free
roam". So the journal asks in a real NSTextView - AppKit, the same runtime
the focus bar already runs on - and falls back to the AppleScript dialog
wherever PyObjC is missing (the 2026-09-15 interpreter ladder made that a
real state, not a theory).

The contract is `xact._ask`'s, exactly: None means CANCEL (stop the run, keep
what is answered), "" means empty-OK (skip this one prompt). The two must
stay distinguishable.

Keys: ⌘⏎ saves, because Return belongs to the paragraph now. Esc cancels.
"""

WIDTH, HEIGHT = 560, 260
HINT = "⌘⏎ saves · Esc cancels · empty saves nothing"


def available():
    """True when the box can actually be drawn."""
    try:
        import AppKit                                   # noqa: F401
        return True
    except Exception:
        return False


def ask(prompt, title="TickAL", default=""):
    """A multi-line answer, "" for empty-OK, None for cancel.

    Raises nothing: an AppKit that will not draw must fall back to the
    AppleScript dialog, so the caller catches and retries there.
    """
    from AppKit import (NSAlert, NSApplication,
                        NSApplicationActivationPolicyAccessory,
                        NSEventModifierFlagCommand, NSFont, NSMakeRect,
                        NSScrollView, NSTextView)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(prompt or "")
    alert.setInformativeText_(f"{title}  ·  {HINT}" if title else HINT)
    ok = alert.addButtonWithTitle_("Save")
    cancel = alert.addButtonWithTitle_("Cancel")
    # Return types a newline in the text view, so Save answers to ⌘⏎ instead.
    ok.setKeyEquivalent_("\r")
    ok.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
    cancel.setKeyEquivalent_("\033")

    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(0, 0, WIDTH, HEIGHT))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(2)                            # NSBezelBorder
    view = NSTextView.alloc().initWithFrame_(
        NSMakeRect(0, 0, WIDTH, HEIGHT))
    view.setFont_(NSFont.systemFontOfSize_(13))
    view.setRichText_(False)                            # a pasted style is noise
    view.setAllowsUndo_(True)
    view.setString_(default or "")
    view.setHorizontallyResizable_(False)
    view.textContainer().setWidthTracksTextView_(True)
    scroll.setDocumentView_(view)
    alert.setAccessoryView_(scroll)

    win = alert.window()
    win.setInitialFirstResponder_(view)
    app.activateIgnoringOtherApps_(True)
    win.makeKeyAndOrderFront_(None)
    # the caret starts AFTER any default text, where a typist expects it
    view.setSelectedRange_((len(view.string()), 0))

    clicked = alert.runModal()
    if clicked != 1000:                                 # NSAlertFirstButtonReturn
        return None
    return _tidy(str(view.string()))


def _tidy(text):
    """Trailing whitespace off every line, and off the answer as a whole.
    Blank lines INSIDE it survive - a paragraph break is something he
    typed on purpose."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n")
             .replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
