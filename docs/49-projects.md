# Projects

_TickAL docs: [Home](00-index.md) · [Setup](30-setup.md) · [Cheatsheet](95-cheatsheet.md)_

> Bootstrap a project as a list plus one scheduled call-to-action task, then keep it moving with a one-row action - TickAL does the naming, filing, tagging, and linking.

**Entry points:** `P ` prefix in the Add window (keyword `tad`) · **📌 Create CTA** on the ⌘⏎ Actions menu. No keyword of its own.

> [!IMPORTANT]
> Like the [CRM](47-crm.md), Projects is a workflow, not a single action - 💼 lists, keycap [area tags](#area-tags-the-keycap-rule), one rule: **a project is only alive if exactly one scheduled task points at it**. Give this page a full read before first use.

If that shape fits how you work, TickAL automates all of its bookkeeping. If not, skip this page; nothing else depends on it.

## Why

TickTick lists never appear on Today - so a project's list is its *home*, not its *presence*. The presence is a **CTA** (call to action): one task in your 📌CTA list, deep-linked to the project, tagged with the project's area, and scheduled.

Sometimes the honest next step is simply "work on project XY". A CTA is exactly that, minus the friction: the task names the project and carries a link straight to its list in its own title, so scheduling time with a project is one row and one date. Your day views show CTAs; the project lists hold the material. Complete a CTA, mint the next one - a project with no open CTA is by definition stalled, and one glance at the 📌CTA list shows every live project ranked by date. That is the whole concept of projects and CTAs.

> [!TIP]
> One TickTick filter turns this into a board: tasks containing `💼`, in the 📌CTA list, carrying any area tag - grouped by Area tag. A kanban of every project you're giving time to, one column per area.

## The moving parts

Five parts make the automation tick - three you create once, two the automation stamps on everything it makes:

| Part | What it is | Who makes it |
|---|---|---|
| **Area tags** | Tags led by a keycap number - `1️⃣Work`, `2️⃣Personal`, `3️⃣Health` - one per area of your life ([the keycap rule](#area-tags-the-keycap-rule)) | You, once |
| **📌CTA list** | The one list every call-to-action task lands in (`cta_list_id`) | You, once |
| **💼Projects folder** | Where new project lists get filed (`projects_folder_id`) | You, once |
| **`💼P • name` naming** | Every project list is born `💼P • name`, and every project CTA title carries `💼` up front too - the [board filter](#why) keys on the `💼` alone, so exact spacing never matters | The automation |
| **Trailing keycap** | Every project list name ends with its area's keycap (`💼P • Website 4️⃣`) - that is how CTAs inherit the area | The automation |

## Set it up once

1. **Create your area tags** in TickTick - one per area of your life, each starting with a keycap number: `1️⃣Work`, `2️⃣Personal`, `3️⃣Health`… Nest them under a parent if you like; only the leading keycap matters. They arrive in TickAL with the next sync - nothing to register. (No keycap tags yet? The `P ` picker tells you to create one first.) Recommended: lead your regular **folder** names with a keycap too (folder `2️⃣Personal` holding your personal lists) - that is how CTAs minted from ordinary lists and tasks inherit an area.
2. **Create the CTA list** - any name works; `📌CTA` reads well in a Today view. Copy its id: `tse l <name>` → ⌘⏎ → **🆔 Copy id**, then paste it into Configure Workflow → `cta_list_id`. Without it, the CTA row never renders - the `P ` flow still creates, names, and files the list, it just can't mint the CTA.
3. **Create the projects folder** - for example `💼Projects`. Browse to it (`tal` → Browse), ⌥⌘⏎ copies the folder id; paste it into `projects_folder_id`. Skippable: without it, new projects are simply created ungrouped.

That's it - from here `P name` builds every project with the right name, keycap, folder, and CTA on its own.

**Adopting existing lists:** rename any current project list to the convention - `💼P • ` in front, its area keycap at the end - and it joins the system: the ⌘⏎ CTA row resolves its area, and the board filter starts catching its CTAs.

## Creating a project: the `P ` flow

In the `tad` Add window type `P name` (case-insensitive; also on the empty field's `/` menu):

1. **Pick an area** - the picker lists your area tags; ⏎ on one fires the whole chain.
2. **The list is created** - `💼P • name 4️⃣` (your area's keycap), inside the projects folder, ready to use immediately.
3. **Its CTA opens for scheduling** - the Add window re-opens prefilled and pinned to the 📌CTA list: the area tag plus a `💼 P • name 🔗` title that deep-links to the new list. Add a date (`*` `@` - every token works) and ⏎ - nothing is saved until that final ⏎, so the CTA arrives already scheduled (the [CRM](47-crm.md) uses the same trick for its Prepare follow-ups).

## The 📌 Create CTA row

⌘⏎ on any list or task-like row (task, subtask, note) offers one dynamic row that mints a CTA for the selection - project or not:

| Selected | CTA title | Area tag comes from |
|---|---|---|
| A 💼 project list | `💼 P • Name 🔗`, linking to the list | The keycap in the list's own name |
| Any other list | `Name 🔗`, linking to the list | The keycap on the list's parent folder |
| A task / subtask / note | `Title 🔗`, linking to the task | Its parent list, same two rules |

Every mode re-opens the Add window prefilled and pinned to the 📌CTA list - schedule, ⏎. Task-mode CTAs also carry a link to the parent list in the description. No keycap found anywhere → the CTA is simply untagged; the row never invents a tag.

On a CRM booking the same row slot reads **🔥 Add Prepare** instead - see [CRM](47-crm.md).

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
- [CRM](47-crm.md) - the 🔥 Add Prepare sibling of the CTA row
