# Troubleshooting

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Symptom → cause → fix for every known failure mode, plus where the logs live.

First moves for any problem: run `tsy` (refreshes the cache), then open Alfred Preferences → Workflows → TickAL → debug (🐞) and reproduce - most errors print their cause there.

## No results, or stale results

| Symptom | Cause | Fix |
|---------|-------|-----|
| Search/browse shows nothing at all | Cache never primed after login | Run `tsy` once - see [Setup](30-setup.md) |
| A task you just added elsewhere is missing | Local cache is behind the server | Run `tsy`; for hands-off freshness, install the optional hourly LaunchAgent - see [Settings & sync](90-settings-sync.md) |
| Results stale even right after edits | Cache dir corrupted | Delete `~/.ticktick_alfred/cache/` and run `tsy` |

Writes made through TickAL patch the cache in place, so your own adds/edits appear immediately; only outside changes need a `tsy`.

## Login fails

| Symptom | Cause | Fix |
|---------|-------|-----|
| The TickTick app opens instead of a browser, then nothing | The desktop app claims ticktick.com links (universal links) and swallows the consent page | Update to 2.5 - `tlogin` now opens your default browser explicitly |
| Browser opens, TickTick rejects the redirect | Redirect URI in your dev app is not exactly `http://localhost:8080` | Fix it at developer.ticktick.com/manage - see [Setup](30-setup.md) |
| "invalid client" or similar | Client ID/Secret mistyped | Re-paste both in Configure Workflow, run `tlogin` again |
| Browser approves but nothing comes back | Another process holds port 8080 (the login runs a local server there) | Free the port, retry `tlogin` |

## Tags or folders missing

| Symptom | Cause | Fix |
|---------|-------|-----|
| `#` picker in add / tag screens missing your tags | Cache stale, or no v2 token | Run `tsy` - with an Attachment-Login token the list and order come from TickTick itself; without one, only tags found on your tasks appear (new ones are creatable from any picker's ➕ row once you have the token) |
| Folder grouping absent in browse / search | No v2 token, or never synced since login | Run `tsy` after Settings → **Attachment Login** - folders auto-name and auto-order |

## Filters empty

| Symptom | Cause | Fix |
|---------|-------|-----|
| `tfi` / the `f` search scope shows nothing | No v2 token, or never synced since login | Run `tsy` after Settings → **Attachment Login** - your TickTick filters sync over, rules included. Tokenless fallback: hand-write `filters_config.py` in the workflow folder - see [Setup](30-setup.md#filters) |

## Attachments fail / Completed list sparse

| Symptom | Cause | Fix |
|---------|-------|-----|
| Image attach errors out | No v2 session token stored | `tup` → **Attachment Login** (one-time, password masked, only the token is kept) - see [Setup](30-setup.md) |
| Completed smart list shows few or no items | Same - Completed is served by the v2 API | Same fix; Sign-in-with-Apple accounts use `tup` → **Attachment Token** instead (paste the `t` cookie) - see [Setup](30-setup.md) |
| Nested-tag tree flat | Same v2 token missing | Same fix |

## Focus bar never appears

| Symptom | Cause | Fix |
|---------|-------|-----|
| Session starts but no floating bar; a "Focus bar needs PyObjC" notification fires (at most hourly) | PyObjC not installed - the bar is the only feature that needs it | `/opt/homebrew/bin/pip3 install --break-system-packages pyobjc` (the workflow's own Python; Intel: `/usr/local/bin/pip3`), start a new session - see [Setup](30-setup.md#focus-bar) |
| No bar and no notification | Bar crashed at launch | Read `/tmp/tickal_focus_bar.log` - a `PyObjC missing` exit-code-3 line means PyObjC is absent or partial - install the full set with the workflow's own Python (see [Setup](30-setup.md#focus-bar)) |
| Bar vanished mid-session | It was hidden, or the session ended (the bar exits ~10 s after going idle) | Via the `tfo` keyword: **👁 Show bar** to unhide, or start a new session |

Every other focus feature - timer, pomodoro, staging blocks, sweep - works without PyObjC.

## CRM shows "CRM needs setup"

| Symptom | Cause | Fix |
|---------|-------|-----|
| `tcr` renders one row: "CRM needs setup" | `crm_list_id` is empty | Copy the 24-char id from your CRM list's URL in the TickTick **web** app (`ticktick.com/webapp/#p/<id>/tasks`) and set it in Configure Workflow - see [CRM](45-crm.md) (screenshot of the pointer row there) |

## "python3 not found"

| Symptom | Cause | Fix |
|---------|-------|-----|
| Every keyword errors with `TickAL: python3 not found - install Python 3` | No usable Python 3 on the machine | Install one: `brew install python` or `xcode-select --install` |

The workflow resolves Python via `Scripts/py.sh`: Apple-Silicon Homebrew → Intel Homebrew → `PATH`. Any of those works; no configuration needed. Install PyObjC (focus bar only) into whichever one wins.

## Sticky note opens the wrong task, nothing, or slowly

Sticky actions drive the TickTick desktop app itself, so the app's state matters.

| Symptom | Cause | Fix |
|---------|-------|-----|
| Nothing happens; error mentions Accessibility or System Events | Alfred lacks Accessibility permission | System Settings → Privacy & Security → Accessibility → enable Alfred |
| "No TickTick shortcut set" | The app's Open-as-Sticky-Note shortcut is unassigned | Assign one in TickTick → Settings → Shortcuts |
| "Couldn't locate … sticky not opened" | Task row not visible in the app (subtask collapsed, view still loading) | Open TickTick, expand the parent / let the view load, retry |
| First sticky after launch is slow or misses | TickTick wasn't running - TickAL launches it and waits, but a cold start can outlast the wait | Keep TickTick running; retry once it's up |

## Where the logs live

| Path | What it is |
|------|-----------|
| `/tmp/tickal_focus_bar.log` | Focus bar stderr - launch failures, PyObjC import errors |
| `/tmp/tickal_cachesync.log` | Optional hourly LaunchAgent output - see [Settings & sync](90-settings-sync.md) |
| `~/.ticktick_alfred/run/tickal_focus.json`, `…/tickal_pomo.json`, `…/tickal_focus_bar.json`, `…/tickal_stage.txt` | Focus/pomodoro session and staging state; safe to delete when no session is running |
| `~/.ticktick_alfred/run/tickal_buffer.txt` | The 🅿️ buffer queue |
| Alfred debug (🐞) | Live stderr/stdout of every script - the fastest diagnosis of all |

## Related

- [Setup](30-setup.md) - credentials, OAuth, v2 token, optional ids
- [Settings & sync](90-settings-sync.md) - Configure Workflow options, cache, background sync
- [Cheatsheet](95-cheatsheet.md) - every keyword and keystroke
