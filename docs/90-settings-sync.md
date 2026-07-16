# Settings & Sync

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Maintain the workflow from one menu: refresh the cache, re-authenticate, and store the optional v2 token.

**Keyword:** `tup` · **Hotkey:** (set in canvas) - opens the Settings menu. ⌃⏎ on any row returns to the main menu.

## Settings rows

| Row | Effect |
|---|---|
| Sync | Refreshes the entire workflow cache from the TickTick API (same as the `tsy` keyword). With the v2 token this also pulls your tag list + order, folder names + order, and your filters - there is no separate tags/folders/filters setup. |
| Hourly Sync | Installs / removes the hourly background-refresh LaunchAgent - a dialog shows the current state and offers the one valid move. See [below](#hourly-background-sync). |
| Install PyObjC | Installs the focus-bar / image-attach dependency into the workflow's own Python - no terminal, PEP-668 handled, a banner confirms. Says so if already installed. |
| Periodic Agent | Installs / removes the 04:30 note-mint LaunchAgent - same dialog pattern as Hourly Sync. See [Periodic notes](48-periodic.md#the-0430-agent). |
| Login | Starts the browser OAuth flow and stores the API token. |
| Refresh TickTick | Clicks File → Sync in the TickTick desktop app (background, no focus steal) - refreshes the app, not the workflow cache. |
| Help • TickAL Docs | Opens the TickAL GitHub page. |
| Attachment Token | Saves the v2 session token from your clipboard - copy the `t` cookie value first (ticktick.com → DevTools → Application → Cookies), then run this row. Validated against TickTick, stored in the Keychain. Use this path for Sign-in-with-Apple accounts. |
| Attachment Login | One-time v2 sign-in via two dialogs (email, then a masked password field). The password is never written to disk - only the session token is stored (Keychain, or `~/.ticktick_alfred/config.json` chmod 600). |

The v2 token (either row) unlocks image attachments, the Completed smart list, the nested-tag tree, tag creation from the pickers, and the tags/folders/filters auto-config - see [Notes, links & images](44-notes-links-images.md) and [Setup](30-setup.md).

## Cache model

TickAL reads from a local JSON cache (`~/.ticktick_alfred/cache/`), not the API, so every screen renders instantly.

- **Writes patch in place.** Completing, moving, scheduling, or editing a task through TickAL updates the cached copy immediately - your change shows on the next screen without a full refresh.
- **`tsy` rebuilds everything.** The Sync row and the `tsy` keyword pull all lists, tasks, notes, and tags fresh from the API. The cache has no expiry; it lives until a sync or a write op touches it.
- **Staleness symptoms:** changes made in the TickTick apps (phone, web, desktop) don't appear in search; deleted tasks linger; a new list or tag is missing from pickers. Any of these means the cache predates the change - run `tsy`.

## Hourly background sync

Optional, and one row away: `tup` → **Hourly Sync**. It installs a LaunchAgent (`com.tickal.cachesync`) that runs a full sync every hour, plus once on install; logs go to `/tmp/tickal_cachesync.log`. When the agent is already installed, the same row removes it - and after a workflow update it detects the stale install and offers **Repair** instead. No files to edit, no terminal.

Deleting the workflow itself? Toggle Hourly Sync off first - Alfred has no uninstall hook, so a leftover agent must otherwise be cleared by hand (see [Troubleshooting](99-troubleshooting.md#hourly-sync-stale-or-orphaned)).

## Related

- [Setup](30-setup.md) - first-run chain: app credentials, `tlogin`, first sync
- [Notes, links & images](44-notes-links-images.md) - what the v2 token enables
- [Cheatsheet](95-cheatsheet.md) - all keywords and chords on one page
