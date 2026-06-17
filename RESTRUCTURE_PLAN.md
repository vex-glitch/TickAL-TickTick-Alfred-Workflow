# TickAL "Restructure" Refactor — Phased Plan

> Goal (from the Restructure note): simplify the canvas to match shipped features, **without breaking it.**
> Source: mapped 2026-06-18 via a 6-area canvas audit + synthesis. Phase 0 re-audits before any surgery.

## Reality-check corrections to the mapping (read first)
- **Temp-file readers = 22 files, not 8.** `grep ticktick_reattribute`: actions, attach_image, change_attributes, change_priority, change_reminder, change_tag_picker, copy_task_url, drill_tags, ensure_task_context, lists, move_action, move_list_picker, note_clear, note_load, note_save, open_links, open_task, rename_task, sections, subtasks, tag_manager, tasks. → **Killing the temp file is a 22-file change**, its own high-risk project — not folded into this refactor unless you pick D4-ii.
- **`ticktick_sync.sh` syncs the TickTick *app*, not the workflow.** Spec item 10 ("keep the workflow synced") is net-new (git ⇄ Alfred live copy), unrelated to that script.

## Make-or-break risks
1. **`Add` ET rename** → `src/dispatch.py:504` hardcodes `run trigger "Add"`. Rename only in lockstep, or not at all (silent CRM-prefill breakage).
2. **Echo nodes are terminal; their predecessors are the real task-selection filters.** Deleting an echo orphans its predecessor's output — confirm each predecessor still reaches a live successor first.
3. **`ensure_task_context.py` + 21 readers depend on the temp file for go-back.** Echo-node removal and temp-file removal must stay decoupled.
4. **Never delete an active ET before removing every `callexternaltrigger` caller** (dangling pointers).
5. **`delete_filter_action.py` rewrites `filters_config.py` via regex** — fragile; back up before the filters review.
6. **All bulk plist edits via `plistlib`, never hand-edited XML.** And per the iron rule: info.plist is **live→repo only** (hook-enforced).

## DESIGN DECISIONS needed before coding (blocking — answer at the start of next session)
- **D1 — Drill-to-one-box (spec 2):** Drill is *already* ~1 script filter (`drill_tags.py`); the 39 nodes are Alfred modifier-routing, not bloat. Choose: **(a)** accept "already done", just delete the dead `drill` keyword/Folders entry-point duplication; or **(b)** merge the `drill` keyword into Filters (variable-namespace risk).
- **D2 — Unify go-back (spec 6):** Adopt `back_context.py` + single `ET:Back`? Decide the context store: keep `/tmp` (→ tagged+timestamped `ticktick_state.json`) vs Alfred-native vars. Confirm the "reopen previous action with task name prefilled" UX (today's `ET:TT` can't do this).
- **D3 — "Add another" (spec 9):** **(a)** Alfred "don't close on action" toggle on the add node, or **(b)** `ET:End` runs a script that re-fires the last action with last task name prefilled (mirrors the working `dispatch.py:502-507` `osascript run trigger "Add"` pattern).
- **D4 — Temp-file fate:** **(i)** keep it, consolidate 11 echo nodes → 1 shared node (low risk, big canvas win — **recommended**); or **(ii)** full removal + rewire all 22 readers to env-var seeding (separate project).
- **D5 — Filters/smart-lists into Actions (spec 7/8):** Confirm `filter_view` / `smart_list` rows should gain the full ⌘ Actions menu (no-ops there today).

---

## Phases (ordered by dependency + risk)

**PHASE 0 — Prep, backup, inventory freeze (zero risk).**
Claude: `plistlib` read-only audit dumping every ET (triggerid→uid), every `callexternaltrigger` caller, every Run Script body, and the predecessor/successor edges of the 11 echo nodes + 8 unused ETs. You: **Export the workflow** (.alfredworkflow = rollback) and commit/stash the current WIP (add_task.py, dispatch.py, crm_menu.py, api_v2.py, …). Verify the audit table on paper.

**PHASE 1 — Delete provably-dead nodes (lowest risk).**
Orphaned echo node `AA2F3D6F…` (no predecessors) + the 8 unused ETs (`againAttributes, goLists, goSections, goSubsubtasks, goTasks, modUncomplete, upRefresh, upSync`). Claude provides a `plistlib` removal script; you approve/run. Verify: workflow loads, main search + ⌥ drill + ⌘ Actions still work; `goSubtasks` (the used one) untouched.

**PHASE 2 — Delete the legacy "change attributes" flow (spec 1+3+4). Biggest blast radius — own session.**
Delete generic `Attributes` ET `29C9B46B`, the 2 legacy Call-ETs `86DE3C1F`/`6A67D56C`, the 2 legacy junctions `B5E07F90`/`374ABCE9`; remove the ⌘ "Change Attributes" modifier (`modifiers=262144`) from the 10 search/browse filters. Echo nodes per **D4** (recommend consolidate 11→1). Verify: ⌘ Actions menu still routes everything via the `719FBC51` conditional; go-back still lands on the task.

**PHASE 3 — Rename ET triggers safely (spec 5).**
Atomic `plistlib` rename of `triggerid` + every caller `config.externaltriggerid`. If `Add` is renamed, edit `dispatch.py:504` in the same commit. Verify the CRM prefill still fires.

**PHASE 4 — Unify "go back" into one dynamic box (spec 6) — needs D2.**
Claude writes `back_context.py` + `context_restore.py`; migrate one action (Rename) first, prove it, then the other ~15 one-by-one. You create `ET:Back` + wire migrated outputs. Old `ET:TT` paths keep working until fully migrated (partial migration never breaks).

**PHASE 5 — Wire filters & smart lists into Actions (spec 7) + review (spec 8) — needs D5.**
Claude: `filter_view.py`/`smart_list.py` emit `task_id`/`task_list_id`/`item_type` in row vars; standardize inline mods onto `display.mods_for()`. You: wire those nodes' ⌘ output → Actions node `0E34EE05`; resolve the duplicate `filter_view` node (`6ED8FD21` vs `FBBA0DE0`).

**PHASE 6 — Reimplement "add another" cleanly (spec 9) — needs D3.**
Per D3-a (canvas toggle) or D3-b (End-script re-fires last action prefilled). Remove the old per-loop conditional popup. Verify: "add another" reopens add prefilled, no lag.

**PHASE 7 — Automate workflow sync (spec 10) — net-new.**
Options for your call: launchd/cron rsync (respecting the info.plist live→repo iron rule), git hook, or event-driven on-save. NOT `ticktick_sync.sh`.

**PHASE 8 — READMEs (spec 11).**
Rewrite `README.md` + the install-time workflow readme to the simplified architecture; append a TickTick changelog-note entry.

---

## Suggested session batching
- **A:** D-decisions + Phase 0–1 (prep + dead-node deletion)
- **B:** Phase 2 alone (legacy attribute flow)
- **C:** Phase 3–4 (renames + go-back)
- **D:** Phase 5–6 (filters/smart-lists + add-another)
- **E:** Phase 7–8 (sync + docs)
- **Deferred (only if D4-ii):** full temp-file removal across all 22 readers — separate project.

## Key references
- Cross-file ET dependency: `src/dispatch.py:504` (hardcoded `"Add"`).
- Go-back affordance constant: `src/display.py:30` (`MOD_BACK`).
- Actions entry + router: nodes `0E34EE05` (actions.py), `719FBC51` (conditional).
- Legacy to delete (Phase 2): `29C9B46B`, `86DE3C1F`, `6A67D56C`, `B5E07F90`, `374ABCE9` + echo nodes.
- 8 unused ETs (Phase 1): againAttributes, goLists, goSections, goSubsubtasks, goTasks, modUncomplete, upRefresh, upSync.
