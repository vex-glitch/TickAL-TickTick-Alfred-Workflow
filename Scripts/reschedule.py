#!/usr/bin/env python3
"""
reschedule.py — Alfred Script Filter
Three-screen flow (all in one script filter via autocomplete):

  Screen 1 — Date picker
    Autocomplete shortcuts + free typing.  Pressing ⏎ on a date fills the
    query (e.g. "tomorrow ") and advances to screen 2.

  Screen 2 — Confirm / add time
    Shows one valid dispatch item.  Press ⏎ to set date with no time.
    Type @ to enter the hour picker (screen 3a).

  Screen 3a — Hour picker  (@)
    Autocomplete 00–23 with AM/PM hints.  Pressing ⏎ fills "tomorrow @08:".

  Screen 3b — Minute picker  (@HH:)
    Autocomplete 00 / 15 / 30 / 45.  Pressing ⏎ fills "tomorrow @08:30 "
    and returns to a time-aware confirm screen.

Outputs to dispatch.py:
  attr_date:{list_id}:{task_id}:{iso}   → set date (+ time if provided)
  attr_cleardate:{list_id}:{task_id}    → clear date
"""
import sys
import os
import json
import traceback

# ── Path setup ───────────────────────────────────────────────────────────────
def emit(items):
    print(json.dumps({"items": items}))

def emit_error(msg):
    emit([{"uid": "err", "title": "TickTick Error", "subtitle": msg, "valid": False}])

try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    emit_error(f"Path setup failed: {e}")
    sys.exit(0)

try:
    import alfred
    import cache as cache_store
    from dateutil import (parse_date, utc_to_picker_display, build_date_shortcuts)
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)


# ── Time picker ───────────────────────────────────────────────────────────────
def _hour_ampm(h):
    if h == 0:   return "12 AM"
    if h < 12:   return f"{h} AM"
    if h == 12:  return "12 PM"
    return f"{h - 12} PM"

def time_picker(prefix, fragment):
    """Autocomplete items for hour (no colon) or minute (colon) selection."""
    items = []
    if ':' not in fragment:
        frag     = fragment.strip()
        frag_int = int(frag) if frag.isdigit() else None
        for h in range(24):
            hh      = f"{h:02d}"
            matches = hh.startswith(frag) or str(h).startswith(frag)
            if not matches and frag_int and 1 <= frag_int <= 12:
                matches = (h == frag_int + 12)
            if frag and not matches:
                continue
            items.append(alfred.item(
                title=hh,
                subtitle=f"{_hour_ampm(h)}  ·  ⏎ Confirm and pick minutes",
                arg="", valid=False,
                autocomplete=f"{prefix}@{hh}:",
            ))
    else:
        hour_part = fragment.split(':')[0]
        try:
            hh = f"{int(hour_part):02d}"
        except ValueError:
            hh = hour_part
        for m in (0, 15, 30, 45):
            label = f"{hh}:{m:02d}"
            items.append(alfred.item(
                title=label,
                subtitle=f"⏎ Set time to {label}",
                arg="", valid=False,
                autocomplete=f"{prefix}@{label} ",
            ))
    if not items:
        items = [alfred.item(
            title=f'No hours matching "{fragment}"',
            subtitle="Type 0–23 to filter",
            valid=False,
        )]
    return items


# ── Prefix stripping ─────────────────────────────────────────────────────────
_PREFIXES = ("reschedule for ", "schedule for ")

def strip_prefix(raw):
    lower = raw.lower()
    for p in _PREFIXES:
        if lower.startswith(p):
            return raw[len(p):]
    return raw


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    list_id    = os.environ.get("task_list_id", os.environ.get("list_id", ""))
    tid        = os.environ.get("task_id", "")
    task_title = os.environ.get("task_title", "task")
    raw        = strip_prefix(sys.argv[1] if len(sys.argv) > 1 else "")

    has_date = False
    try:
        all_tasks = cache_store.get("all_tasks") or []
        task      = next((t for t in all_tasks if t["id"] == tid), None)
        if task and (task.get("startDate") or task.get("dueDate")):
            has_date = True
    except Exception:
        pass

    action_verb = "Reschedule" if has_date else "Schedule"

    try:
        # ── Detect @ trigger ──────────────────────────────────────────────────
        at_pos = None
        for i in range(len(raw) - 1, -1, -1):
            if raw[i] == '@' and (i == 0 or raw[i - 1] == ' '):
                at_pos = i
                break

        if at_pos is not None:
            date_raw      = raw[:at_pos]            # may end with space
            time_fragment = raw[at_pos + 1:]
            date_part     = date_raw.strip()

            if not time_fragment.endswith(' '):
                # ── Screen 3: time picker (hour or minute) ────────────────────
                items = time_picker(raw[:at_pos], time_fragment)
                print(alfred.output(items, skipknowledge=True))
                return

            time_str = time_fragment.strip()        # e.g. "08:30"
        else:
            date_raw  = raw
            date_part = raw.strip()
            time_str  = None

        # Date is "committed" when it ends with a space (selected from autocomplete
        # or typed in full) — this triggers the confirm / time screen.
        date_committed = date_raw.endswith(' ') if date_raw else False
        show_confirm   = date_committed or bool(time_str)

        # ── Screen 2: confirm / add-time ─────────────────────────────────────
        if show_confirm:
            base = date_part if date_part else "today"
            combined = f"{base} {time_str}" if time_str else base
            iso = parse_date(combined)
            items = []

            if iso:
                display  = utc_to_picker_display(iso)
                time_tag = f"  @{time_str}" if time_str else ""
                items.append(alfred.item(
                    uid="dispatch",
                    title=f"{display}{time_tag}",
                    subtitle=f"⏎ {action_verb} \"{task_title}\"  |  ⇧⌘ Back",
                    arg=f"attr_date:{list_id}:{tid}:{iso}",
                    valid=True,
                ))
                if not time_str:
                    items.append(alfred.item(
                        uid="add-time",
                        title="@ Add time",
                        subtitle=f"Pick a specific time for {display}",
                        arg="", valid=False,
                        autocomplete=f"{date_part} @",
                    ))
            else:
                items.append(alfred.item(
                    uid="bad-date",
                    title=f"Can't parse \"{date_part}\" as a date",
                    subtitle="Press ⇧⌘ to go back and try again",
                    valid=False,
                ))

            print(alfred.output(items, skipknowledge=True))
            return

        # ── Screen 1: date picker (autocomplete — no dispatches yet) ──────────
        items  = []
        dl     = date_part.lower()

        if not date_part:
            items.append(alfred.item(
                uid="hint",
                title="Pick a date…",
                subtitle="or type: tomorrow · 21/07 · next monday · end of june",
                valid=False,
            ))
            if has_date:
                items.append(alfred.item(
                    uid="clear-date",
                    title="Clear date",
                    subtitle=f"Remove due date from \"{task_title}\"  |  ⇧⌘ Back",
                    arg=f"attr_cleardate:{list_id}:{tid}",
                    valid=True,
                ))

        # Custom free-typed date → autocomplete to commit it
        if date_part:
            iso = parse_date(date_part)
            if iso:
                display = utc_to_picker_display(iso)
                items.append(alfred.item(
                    uid="custom-date",
                    title=display,
                    subtitle=f"\"{date_part}\"  ·  ⏎ Use this date",
                    arg="", valid=False,
                    autocomplete=f"{date_part} ",
                ))

        # Shortcut list
        seen_iso = set()
        for shortcut in build_date_shortcuts():
            parse_str, label = shortcut[0], shortcut[1]
            extra  = shortcut[2] if len(shortcut) > 2 else ""
            search = f"{parse_str} {label.lower()} {extra}".strip()

            if dl and dl not in search:
                continue

            iso = parse_date(parse_str)
            if not iso or iso in seen_iso:
                continue
            seen_iso.add(iso)

            display = utc_to_picker_display(iso)
            items.append(alfred.item(
                uid=f"date-{parse_str}",
                title=label,
                subtitle=display,
                arg="", valid=False,
                autocomplete=f"{parse_str} ",
            ))

        if not [i for i in items if i.get("uid") != "hint" and i.get("uid") != "clear-date"]:
            items.append(alfred.item(
                uid="no-match",
                title=f"Can't parse \"{date_part}\" as a date" if date_part else "Type a date",
                subtitle="e.g. tomorrow · 21/07 · next monday · in 3 days",
                valid=False,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
