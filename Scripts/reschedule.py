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

  Reminders (%):  available once a date is set, through the whole flow. Type %
  (or pick "🔔 Add reminder") for presets / custom offsets; multiple allowed.
  They ride into the dispatch arg as a ';R:tok,tok' suffix.

Outputs to dispatch.py:
  attr_date:{list_id}:{task_id}:{iso}[;R:tok,tok]            → set date (+ time)
  attr_span:{list_id}:{task_id}:{startIso}|{endIso}[;R:tok]  → date + duration
  attr_cleardate:{list_id}:{task_id}                         → clear date
"""
import sys
import os
import json
import traceback

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    from script_base import bootstrap, emit, emit_error, WORKFLOW_DIR, SRC_DIR
    bootstrap()
except Exception as e:
    print(json.dumps({"items": [{"uid": "err", "title": "TickTick Error",
                                 "subtitle": f"Path setup failed: {e}", "valid": False}]}))
    sys.exit(0)

try:
    import re
    import alfred
    import cache as cache_store
    from dateutil import (parse_date, utc_to_picker_display, utc_to_local_display,
                          build_date_shortcuts)
    import reminders as rem
except Exception as e:
    emit_error(f"Import failed: {e}")
    sys.exit(0)


# ── Back chord ────────────────────────────────────────────────────────────────
def back_mod(list_id, tid):
    """⌘⇧ back must work even on invalid rows — a mod-level valid=True
    overrides the row's valid=False (Alfred ignores action chords on invalid
    rows). Mod variables REPLACE item-level ones, so carry the full context."""
    return {"ctrl": {"valid": True, "arg": "",
                          "subtitle": "🔙 Back to ⌘ Actions",
                          "variables": {"task_list_id": list_id,
                                        "task_id": tid}}}


# ── Time picker ───────────────────────────────────────────────────────────────
def _hour_ampm(h):
    if h == 0:   return "12 AM"
    if h < 12:   return f"{h} AM"
    if h == 12:  return "12 PM"
    return f"{h - 12} PM"

def time_picker(prefix, fragment, back):
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
                subtitle=f"{_hour_ampm(h)}  ⏎ Pick minutes",
                arg="", valid=False,
                autocomplete=f"{prefix}@{hh}:",
                mods=back,
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
                mods=back,
            ))
    if not items:
        items = [alfred.item(
            title=f'No hours matching "{fragment}"',
            subtitle="Type 0–23 to filter",
            valid=False,
            mods=back,
        )]
    return items


# ── Duration helpers ───────────────────────────────────────────────────────
def _duration_label(start_hm, end_hm):
    """Human duration between two HH:MM strings (end may wrap to next day)."""
    sh, sm = (int(x) for x in start_hm.split(":"))
    eh, em = (int(x) for x in end_hm.split(":"))
    mins = (eh * 60 + em) - (sh * 60 + sm)
    if mins <= 0:
        mins += 24 * 60
    h, m = divmod(mins, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def duration_picker(prefix, fragment, start_hm, back):
    """End-time picker after a start time is set. Accepts an end time
    (14, 14:30) or a length (2h, 90m, 1h30); autocompletes to >HH:MM."""
    sh, sm = (int(x) for x in start_hm.split(":"))
    frag = fragment.strip()

    # Length syntax → resolve to an end time
    m = re.match(r'^(\d+)h(\d+)?m?$|^(\d+)m$', frag)
    if m:
        mins = int(m.group(3)) if m.group(3) else int(m.group(1)) * 60 + int(m.group(2) or 0)
        total = sh * 60 + sm + mins
        eh, em = divmod(total % (24 * 60), 60)
        end = f"{eh:02d}:{em:02d}"
        return [alfred.item(
            title=f"{start_hm} → {end}",
            subtitle=f"⏳ {_duration_label(start_hm, end)}  ⏎ ✅",
            arg="", valid=False, autocomplete=f"{prefix}>{end} ",
            mods=back,
        )]

    items = []
    if ':' not in frag:
        for h in range(sh, 24):
            hh = f"{h:02d}"
            if frag and not (hh.startswith(frag) or str(h).startswith(frag)):
                continue
            end_preview = f"{hh}:{sm:02d}"
            items.append(alfred.item(
                title=hh,
                subtitle=f"⏳ {_duration_label(start_hm, end_preview)} (at :{sm:02d})  ⏎ Pick minutes",
                arg="", valid=False, autocomplete=f"{prefix}>{hh}:",
                mods=back,
            ))
    else:
        hour_part = frag.split(':')[0]
        try:
            hh = f"{int(hour_part):02d}"
        except ValueError:
            hh = hour_part
        for mi in (0, 15, 30, 45):
            end = f"{hh}:{mi:02d}"
            items.append(alfred.item(
                title=end,
                subtitle=f"⏳ {_duration_label(start_hm, end)}  ⏎ End at {end}",
                arg="", valid=False, autocomplete=f"{prefix}>{end} ",
                mods=back,
            ))
    if not items:
        items = [alfred.item(
            title=f'No end times matching "{frag}"',
            subtitle="Type an hour, 14:30, or a length like 2h / 90m / 1h30",
            valid=False,
            mods=back,
        )]
    return items


# ── Reminder picker (% trigger) ──────────────────────────────────────────────
def reminder_picker(prefix, fragment, back):
    """Reminder presets for the schedule flow (mirrors add_task's % picker).
    Each row autocompletes %{token} into the query; multiple reminders allowed."""
    frag = fragment.strip().lower()
    # Free-typed custom offset (45, 2h, 3d…) that isn't a preset
    if frag and frag not in rem.PRESET_TOKENS and rem.trigger(frag):
        return [alfred.item(
            uid="rem-custom",
            title=f"🔔 {rem.human(frag)}",
            subtitle="Custom offset  ⏎ Add  |  ⌃ 🔙",
            arg="", valid=False,
            autocomplete=f"{prefix}%{frag} ",
            mods=back,
        )]
    items = []
    for tok, label, hint in rem.PRESETS:
        if frag and frag not in tok and frag not in label.lower():
            continue
        items.append(alfred.item(
            uid=f"rem-{tok}",
            title=f"🔔 {label}",
            subtitle=f"{hint}  |  ⌃ 🔙",
            arg="", valid=False,
            autocomplete=f"{prefix}%{tok} ",
            mods=back,
        ))
    if not items:
        items = [alfred.item(
            uid="rem-none",
            title=f'No reminder matching "{fragment}"',
            subtitle="Try: at  15  30  1h  1d  45  2h",
            valid=False,
            mods=back,
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
        back = back_mod(list_id, tid)

        # ── Reminders: active % being typed → picker; else extract committed ──
        mrem = re.search(r'(?<!\S)%(\S*)$', raw)
        if mrem:
            items = reminder_picker(raw[:mrem.start()], mrem.group(1), back)
            print(alfred.output(items, skipknowledge=True))
            return
        reminder_tokens = [t.lower() for t in re.findall(r'(?<!\S)%(\S+)', raw)]
        raw = re.sub(r'(?<!\S)%\S+\s*', '', raw)   # strip for clean date/time parsing

        # ── Detect active trigger (@ time or > duration) ──────────────────────
        # Find the last @ or > that starts a word; whichever is open wins.
        at_pos  = None
        gt_pos  = None
        for i in range(len(raw) - 1, -1, -1):
            if raw[i] in ('@', '>') and (i == 0 or raw[i - 1] == ' '):
                if raw[i] == '@' and at_pos is None:
                    at_pos = i
                elif raw[i] == '>' and gt_pos is None:
                    gt_pos = i

        # ── Screen 3c: duration picker (> after a committed time) ─────────────
        if gt_pos is not None:
            dur_fragment = raw[gt_pos + 1:]
            if not dur_fragment.endswith(' '):
                # Need the start time from the @ token before >
                tm = re.search(r'(?<!\S)@(\d{1,2}:\d{2})\b', raw[:gt_pos])
                if tm:
                    items = duration_picker(raw[:gt_pos], dur_fragment, tm.group(1), back)
                    print(alfred.output(items, skipknowledge=True))
                    return

        if at_pos is not None:
            date_raw      = raw[:at_pos]            # may end with space
            time_fragment = raw[at_pos + 1:]
            date_part     = date_raw.strip()

            # Strip any trailing > duration token from the time fragment
            time_fragment_clean = re.sub(r'\s*>\S*\s*$', '', time_fragment)

            if not time_fragment_clean.endswith(' ') and '>' not in time_fragment:
                # ── Screen 3: time picker (hour or minute) ────────────────────
                items = time_picker(raw[:at_pos], time_fragment_clean, back)
                print(alfred.output(items, skipknowledge=True))
                return

            time_str = time_fragment_clean.strip()  # e.g. "08:30"
        else:
            date_raw  = raw
            date_part = raw.strip()
            time_str  = None

        # >end duration — committed (HH:MM) once present anywhere in the query
        end_str = None
        em = re.search(r'(?<!\S)>(\d{1,2}:\d{2})(?=\s|$)', raw)
        if em:
            end_str = em.group(1)

        # Date is "committed" when it ends with a space (selected from autocomplete
        # or typed in full) — this triggers the confirm / time screen.
        date_committed = date_raw.endswith(' ') if date_raw else False
        show_confirm   = date_committed or bool(time_str)

        # ── Screen 2: confirm / add-time / add-duration ──────────────────────
        if show_confirm:
            base = date_part if date_part else "today"
            combined = f"{base} {time_str}" if time_str else base
            iso = parse_date(combined)
            items = []

            if iso:
                display  = utc_to_picker_display(iso)

                rem_suffix   = (";R:" + ",".join(reminder_tokens)) if reminder_tokens else ""
                rem_tag      = ("  🔔 " + ", ".join(reminder_tokens)) if reminder_tokens else ""
                rem_tag_lead = ("🔔 " + ", ".join(reminder_tokens) + "  ·  ") if reminder_tokens else ""
                rem_q        = "".join(f" %{t}" for t in reminder_tokens)
                committed_dt = date_part + (f" @{time_str}" if time_str else "") + \
                               (f" >{end_str}" if end_str else "")

                # Duration span: resolve end time on the same date (wrap if needed)
                end_iso = None
                if end_str and time_str:
                    end_iso = parse_date(f"{base} {end_str}")
                    if end_iso and end_iso <= iso:
                        from datetime import datetime, timedelta
                        dt = datetime.strptime(end_iso[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(days=1)
                        end_iso = dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

                if end_iso:
                    dur = _duration_label(time_str, end_str)
                    items.append(alfred.item(
                        uid="dispatch",
                        title=f"{display}  @{time_str} → {end_str}",
                        subtitle=f"⏳ {dur}{rem_tag}  ⏎ {action_verb} \"{task_title}\"  |  ⌃ 🔙",
                        arg=f"attr_span:{list_id}:{tid}:{iso}|{end_iso}{rem_suffix}",
                        valid=True,
                        mods=back,
                    ))
                else:
                    time_tag = f"  @{time_str}" if time_str else ""
                    items.append(alfred.item(
                        uid="dispatch",
                        title=f"{display}{time_tag}",
                        subtitle=f"{rem_tag_lead}⏎ {action_verb} \"{task_title}\"  |  ⌃ 🔙",
                        arg=f"attr_date:{list_id}:{tid}:{iso}{rem_suffix}",
                        valid=True,
                        mods=back,
                    ))
                    if not time_str:
                        items.append(alfred.item(
                            uid="add-time",
                            title="@ Add time",
                            subtitle=f"Pick time for {display}",
                            arg="", valid=False,
                            autocomplete=f"{date_part}{rem_q} @",
                            mods=back,
                        ))
                    else:
                        items.append(alfred.item(
                            uid="add-duration",
                            title="> Add duration",
                            subtitle=f"Set end time for {display} @{time_str}",
                            arg="", valid=False,
                            autocomplete=f"{date_part} @{time_str}{rem_q} >",
                            mods=back,
                        ))

                # Always available once a date is set — even with no time/duration
                items.append(alfred.item(
                    uid="add-reminder",
                    title="🔔 Add another reminder" if reminder_tokens else "🔔 Add reminder",
                    subtitle=(f"Current: {', '.join(reminder_tokens)}  ⏎ add another  |  ⌃ 🔙"
                              if reminder_tokens else "Remind before due  |  ⌃ 🔙"),
                    arg="", valid=False,
                    autocomplete=f"{committed_dt}{rem_q} %",
                    mods=back,
                ))
            else:
                items.append(alfred.item(
                    uid="bad-date",
                    title=f"Can't parse \"{date_part}\" as a date",
                    subtitle="⌃ 🔙",
                    valid=False,
                    mods=back,
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
                mods=back,
            ))
            if has_date:
                items.append(alfred.item(
                    uid="clear-date",
                    title="Clear date",
                    subtitle=f"Remove due date from \"{task_title}\"  |  ⌃ 🔙",
                    arg=f"attr_cleardate:{list_id}:{tid}",
                    valid=True,
                    mods=back,
                ))

        # Custom free-typed date → autocomplete to commit it
        if date_part:
            iso = parse_date(date_part)
            if iso:
                display = utc_to_picker_display(iso)
                items.append(alfred.item(
                    uid="custom-date",
                    title=display,
                    subtitle=f"\"{date_part}\"  ⏎ Use date",
                    arg="", valid=False,
                    autocomplete=f"{date_part} ",
                    mods=back,
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
                mods=back,
            ))

        if not [i for i in items if i.get("uid") != "hint" and i.get("uid") != "clear-date"]:
            items.append(alfred.item(
                uid="no-match",
                title=f"Can't parse \"{date_part}\" as a date" if date_part else "Type a date",
                subtitle="e.g. tomorrow · 21/07 · next monday · in 3 days",
                valid=False,
                mods=back,
            ))

        print(alfred.output(items, skipknowledge=True))

    except Exception as e:
        emit_error(f"{type(e).__name__}: {e} | {traceback.format_exc()}")


if __name__ == "__main__":
    main()
