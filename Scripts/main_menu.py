#!/usr/bin/env python3
"""
main_menu.py — Alfred Script Filter
Main entry point for the TickTick workflow.
Replaces the static List Filter to enable modifier key support on Calendar.

Args passed to Alfred (routed by conditional ▷50F14423):
  search   → ET Search
  cal(_*)  → Open Calendar (default/day/week/month/year views)
  add      → ET Add
  URL      → ET SaveURL
  crm      → ET CRM
  update   → ET Update
  open:*   → open the URL (Statistics row)
  tts:*    → tt_shortcut.py (TickTick's own global shortcuts)
(the old View/Filters and Drill entries were retired — search's v / f scopes
and ⌥ drilling replaced them.)
"""
import sys
import os
import json

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR, run_path
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

try:
    import alfred
    import fuzzy as fuzz
except Exception as e:
    print(json.dumps({"items": [{"title": "Import error", "subtitle": str(e), "valid": False}]}))
    sys.exit(0)

# ── Menu items ────────────────────────────────────────────────────────────────
def _focus_subtitle():
    """Idle → static hint; workflow timer running → live status (pause-aware);
    else TickTick's own pomodoro running → its status."""
    try:
        with open(run_path("tickal_focus.json")) as f:
            st = json.load(f)
    except OSError:
        st = None
    if st:
        try:
            import xact
            secs = xact.focus_elapsed(st)
        except Exception:
            secs = 0
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        hm = f"{h}h {m}m" if h else f"{m}m"
        pause = "⏸ " if st.get("paused_at") else ""
        try:
            from display import md_links_display
            name = md_links_display(st.get("title", "Focus"))
        except Exception:
            name = st.get("title", "Focus")
        return f"🎯 {pause}{name} · {hm}"
    try:
        import xact
        pstate, premaining = xact._pomo_app_state()
    except Exception:
        pstate = "idle"
    if pstate != "idle":
        pause = "⏸ " if pstate.startswith("pomodoroPaused") else ""
        return f"🍅 {pause}Pomodoro · {premaining // 60}m left"
    return "Start a timer or pomodoro"


def build_items():
    return [
        # Every row leads with an emoji.
        alfred.item(
            uid="search",
            title="🔎 Search",
            subtitle="Choose criteria",
            arg="search",
        ),
        # View.../Filters... rows were retired (search's v /f scopes own them);
        # the Drill row was redundant with search + ⌥ drilling.
        # Add sits above Calendar.
        alfred.item(
            uid="add",
            title="➕ Add...",
            subtitle="Task, list, note, project",
            arg="add",
        ),
        alfred.item(
            uid="calendar",
            title="📆 Calendar...",
            subtitle="Open  ⌃ Year  ⌥ Month  ⌘⇧ Day  ⇧ Week",
            arg="cal",
            mods={
                "cmd+shift": {"arg": "cal_1"},
                "shift":     {"arg": "cal_w"},
                "alt":       {"arg": "cal_m"},
                "ctrl":      {"arg": "cal_y"},
            },
        ),
        # Focus sits below Calendar.
        alfred.item(
            uid="focus",
            title="🎯 Focus",
            subtitle=_focus_subtitle(),
            arg="focus",
        ),
        # Periodic below Focus — reachable from the main list.
        # arg "periodic" → conditional branch → runscript fires ET Search
        # prefilled "pn ".
        alfred.item(
            uid="periodic",
            title="💫 Periodic Notes",
            subtitle="Daily, weekly, journal, money",
            arg="periodic",
        ),
        alfred.item(
            uid="url",
            title="🔗 Save URL...",
            subtitle="Save browser tab as task",
            arg="URL",
        ),
        alfred.item(
            uid="update",
            title="⚙️ Settings",
            subtitle="Login, sync, attachment token, refresh",
            arg="update",
        ),
        alfred.item(
            uid="statistics",
            title="📊 Statistics",
            subtitle="TickTick stats overview (web)",
            arg="open:https://ticktick.com/webapp/#statistics/overview",
        ),
        # tts: rows (Quick Add / Mini Window / Pomodoro / Sticky Note) were
        # retired — they only re-fired TickTick's own global shortcuts, and
        # the task-bound sticky/pomo in ⌘ Actions are better. tt_shortcut.py
        # stays (xact sticky imports its decoder).
        alfred.item(
            uid="crm",
            title="📈 CRM...",
            subtitle="Search or add a booking",
            arg="crm",
        ),
    ]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    stripped = raw.strip()
    # Treat Alfred placeholder values (e.g. "...", "…") as empty
    import re
    query = stripped if re.search(r'[a-zA-Z0-9]', stripped) else ""

    # A picker's ⌃ that should land on a task's ⌘ Actions menu — not
    # here — rides in as menu_return (the ⌃ canvas wire only knows MainMenu).
    # Honor it: act-again on the task and get out of the way.
    ret = os.environ.get("menu_return", "")
    if ret and ":" in ret:
        try:
            from script_base import reopen_actions
            _pid, _tid = ret.split(":", 1)
            reopen_actions(_pid, _tid)
            print(json.dumps({"items": [{"title": "↩️ Back to task actions…",
                                         "valid": False}]}))
            return
        except Exception:
            pass  # fall through to the normal menu

    try:
        items = build_items()

        if query:
            items = fuzz.filter_and_score(query, items, key_fn=lambda x: x["title"])

        if not items:
            items = [alfred.item(
                title=f'No options matching "{query}"',
                valid=False,
            )]

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        import traceback
        print(json.dumps({"items": [{
            "title": "Error in main_menu.py",
            "subtitle": f"{type(e).__name__}: {e}  |  {traceback.format_exc()}",
            "valid": False,
        }]}))


if __name__ == "__main__":
    main()
