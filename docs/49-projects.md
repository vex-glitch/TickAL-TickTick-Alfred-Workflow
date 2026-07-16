# Projects

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Bootstrap a project as a list plus one scheduled call-to-action task, then keep it moving with a one-row action - TickAL does the naming, filing, tagging, and linking.

**Entry points:** `P ` prefix in the `tad` Add window · **📌 Create CTA** on the ⌘⏎ Actions menu. No keyword of its own.

> [!IMPORTANT]
> Like the [CRM](45-crm.md), Projects is a workflow, not a single action - 💼 lists, keycap area tags, one rule: **a project is only alive if exactly one scheduled task points at it**. Give this page a full read before first use.

If that shape fits how you work, TickAL automates all of its bookkeeping. If not, skip this page; nothing else depends on it.

## Why

TickTick lists never appear on Today - so a project's list is its *home*, not its *presence*. The presence is a **CTA** (call to action): one task in your 📌CTA list, deep-linked to the project, tagged with the project's area, and scheduled. Your day views show CTAs; the project lists hold the material. Complete a CTA, mint the next one - a project with no open CTA is by definition stalled, and one glance at the 📌CTA list shows every live project ranked by date.

## Setup

Two ids in Configure Workflow (both under [Optional ids](30-setup.md#optional-ids)):

| Field | Role | Blank = |
|---|---|---|
| `cta_list_id` | The list where CTA tasks are created - the heart of the feature | No CTA row on Actions menus; the `P ` flow creates the bare list only |
| `projects_folder_id` | The folder new 💼 project lists land in | New projects created ungrouped |

Copying the ids never leaves Alfred: ⌘⏎ on the CTA list's row → **🆔 Copy id**; ⌥⌘⏎ on the projects folder's row copies the folder id.

Plus **area tags**: any TickTick tag that starts with a keycap number (`1️⃣Work`, `2️⃣Personal`, …) is an area. They arrive with the normal tag sync - nothing to register. With none, the `P ` picker shows a pointer row instead.

## Creating a project: the `P ` flow

In the `tad` Add window type `P name` (case-insensitive; also on the empty field's `/` menu):

1. **Pick an area** - the picker lists your area tags; ⏎ on one fires the whole chain.
2. **The list is created** - `💼P • name 4️⃣` (your area's keycap), inside the projects folder, resolvable immediately.
3. **Its CTA opens for scheduling** - the Add window re-opens prefilled and pinned to the 📌CTA list: the area tag plus a `💼 P • name 🔗` title that deep-links to the new list. Add a date (`*` `@` - every token works) and ⏎ - the CTA is created only then, so it can be scheduled before it ever exists. Same re-open-prefilled flow as CRM bookings.

## The 📌 Create CTA row

⌘⏎ on any list or task-like row (task, subtask, note) offers one dynamic row that mints a CTA for the selection - project or not:

| Selected | CTA title | Area tag comes from |
|---|---|---|
| A 💼 project list | `💼 P • Name 🔗`, linking to the list | The keycap in the list's own name |
| Any other list | `Name 🔗`, linking to the list | The keycap on the list's parent folder |
| A task / subtask / note | `Title 🔗`, linking to the task | Its parent list, same two rules |

Every mode re-opens the Add window prefilled and pinned to the 📌CTA list - schedule, ⏎. Task-mode CTAs also carry a link to the parent list in the description. No keycap found anywhere → the CTA is simply untagged; the row never invents a tag.

On a CRM booking the same row slot reads **🔥 Add Prepare** instead - see [CRM](45-crm.md).

## Area tags: the keycap rule

One convention resolves the area everywhere, with no per-list configuration:

- A **project list** carries its area keycap in its own name: `💼P • Website 4️⃣`.
- A **regular list** inherits the keycap of its parent **folder**: a list inside `2️⃣Personal` is area 2️⃣.
- A **task** resolves through its parent list, by the same two rules.

Matching is by the keycap emoji alone, so folder spelling and spacing never matter. The resolved tag is always one of your existing area tags - assigning it reuses that tag, no duplicates.

## Related

- [Add](42-add.md) - the `L / N / P / T` creation modes and the token grammar
- [Actions](43-actions.md) - the ⌘⏎ menu the CTA row lives on
- [Setup](30-setup.md) - copying the two ids into Configure Workflow
- [CRM](45-crm.md) - the 🔥 Add Prepare sibling of the CTA row
