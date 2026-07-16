# Notes, links & images

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Find and edit TickTick notes, pin tasks as desktop stickies, save browser tabs as tasks, wire tasks together with links, and attach clipboard images.

**Keyword:** `tur` · **Hotkey:** `⌥⌘U` - saves the active browser tab as a task. Notes, links, and images otherwise live inside the `tse`, `tad`, and ⌘⏎ flows below.

## Notes

### Find notes

Two search scopes via the `tse` keyword (grammar: `tse [scope] query`):

| Scope | Searches | Result row |
|---|---|---|
| `n` | Note titles | Note name, folder as breadcrumb |
| `nc` | Note bodies | Matching content snippet as the title, note name · folder as breadcrumb |

On a note row: ⏎ opens the note in TickTick, ⌘⏎ opens Actions, ⌥⌘⏎ copies its link, ⌃⏎ goes back. ⇧⏎ (complete) and ⌥⏎ (drill) are suppressed - notes have neither. The note's ⌘⏎ Actions menu drops Complete and Priority but keeps everything else, including **📝 Note** and **🖼️ Add image**.

### Edit a note body

⌘⏎ → **📝 Note** on any task or note opens the description in an editable text view - the row's subtitle previews the current text. It is the description editor for everything, not just notes. Plain ⏎ inserts a newline; act with modifiers:

| Key | Action |
|---|---|
| ⌘⏎ | Save the edited text back to TickTick |
| ⇧⏎ | Open the task in TickTick |
| ⌥⌘⏎ | Copy the task's deep link |
| ⌘⇧⏎ | Open/copy the description's URLs (link picker) |
| ⌃⏎ | Clear the description |

<details><summary>Screenshot</summary>

![Note body open in the text view editor](assets/shots/14-note-editor.png)

</details>

### Create notes

Start an add with a leading `N ` via the `tad` keyword to create a note; the `=` token adds description text to any new task. See [Add](42-add.md).

## Sticky notes

⌘⏎ → **🗒️ Sticky note** opens the selected task as a TickTick desktop sticky: deep link into the app, locate the row, fire the app's own Open-as-Sticky shortcut. If the row can't be located, it reports failure instead of firing on the wrong task.

The focus picker pairs stickies with sessions: **🗒️ Start + sticky note** (timer + sticky) and **🗒️ Sticky note + Nm pomo** rows; on the staging screen's add row, ⌥⏎ adds the checkbox and opens the focus task's sticky so the day's list sits on your desktop. See [Focus](44-focus.md).

## Save a URL

**Keyword:** `tur` · **Hotkey:** `⌥⌘U` - grabs the front browser tab's URL and title, then opens the Add window with a markdown link already riding in the task description. Type the title as usual; every add token still works, and a typed `=` note stays above the link. Also reachable from the main menu's **🔗 Save URL...** row - there Alfred is frontmost, so running browsers are probed instead.

Supported browsers: the Safari family and every Chromium browser (Chrome, Brave, Edge, Arc, Vivaldi, Opera, …). Others get a friendly message in the add window instead of a silent failure.

## Task links

Deep links use the form `ticktick:///webapp/#p/<listId>/tasks/<taskId>`.

| Action | Where | Result |
|---|---|---|
| Type `[[` | In a `tad` add | Picker over all tasks + notes; selecting inserts `[[Title]]`, resolved to a real TickTick task link on create. Unresolved names stay as literal `[[Name]]`. |
| ⌥⌘⏎ | Task, subtask, note, list, section, and tag rows | Copies the item's deep link and shows a toast; task, subtask, and note rows then reopen the ⌘⏎ Actions menu so you can keep acting |
| ⌘⏎ → **🔗 Copy link** | Actions menu | Same copy, as a menu row |
| ⌘⏎ → **🌐 Open link** | Actions menu | Appears only when the title or description contains a link - markdown or bare URI, any scheme `open` handles. A lone title link opens directly (⌘⏎ copies it instead); anything else opens a picker. |

In a CRM add, the `[[` picker scopes to bookings - see [CRM](45-crm.md).

## Images

| Action | Where | Result |
|---|---|---|
| `^` token | In a `tad` add | Uploads the clipboard image to the new task on create. Also available as the `/` menu's **Add image** row. |
| ⌘⏎ → **🖼️ Add image** | Actions menu | Uploads the clipboard image to the selected task as a real attachment - renders inline, syncs to every device |

Both need the one-time v2 session token - see [Setup](30-setup.md). Without it, the attach reports a message pointing at the Settings rows that store one. CRM booking adds attach the clipboard image automatically - see [CRM](45-crm.md).

## Related

- [Search](40-search.md) - all `tse` scopes
- [Add](42-add.md) - the full token grammar, `N ` note creation
- [Actions](43-actions.md) - the ⌘⏎ menu per item type
- [Focus](44-focus.md) - sticky-paired sessions, staging blocks
- [CRM](45-crm.md) - booking image auto-attach, scoped `[[` picker
- [Setup](30-setup.md) - the v2 attachment token
