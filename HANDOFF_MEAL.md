# 🥘 Meal Prep · subsystem doc, 2026-09-19 (remodelled 2026-09-21)

The week's meals, planned in MELA'S CALENDAR and mirrored into TickTick by
one manual sync, from a Mela-fed recipe library. Written by the Fable
session that built it (plan: `~/.claude/plans/deep-doodling-peach.md`),
remodelled 2026-09-21 on Vex's decision (§0). Read `CLAUDE.md` first (the
iron rules bind); `HANDOFF_ROUTINES.md` §8 for the repeating-task trap this
design is shaped by; `HANDOFF_OKR.md` for the hub pattern it copies.

## 0. Decisions (2026-09-21)

Vex, verbatim where it matters: "this python script that runs in the
background is unacceptable. We should only have a row that says sync
TickTick with Mela"; "I will be scheduling in Mela, it is nicer"; "get rid of
Plan the week / Schedule a meal"; "the sync should also pull dates for
meals"; "see this week's breakfast, lunch, snack, and all the next meals for
a quarter, by week"; "on a meal: open the link to Mela and a link to the
web".

- **D11 · Mela plans, in Apple Calendar.** Mela keeps NO plan in its own DB
  (Curcuma.sqlite has recipes, tags, feeds, images only). "Add to
  Calendar…" (⌘⌥A) writes an event whose url is
  `mela://calendar/<calendarId>:<eventId>/<RECIPE-UUID>`; the last segment
  IS the recipe id, the same one `mela://recipe/<UUID>` uses. The plan is
  read from `~/Library/Group Containers/group.com.apple.calendar/
  Calendar.sqlitedb` (tables Calendar, CalendarItem; start_date = seconds
  since 2001-01-01 UTC, +978307200). EVERY calendar is read and the rows are
  filtered on the url prefix; the calendar's name is never assumed (Vex's
  live plan sits in the iCloud "Inbox" calendar, two local calendars named
  "Mela" hold test events). Nothing is ever written to the calendar.
- **D12 · One manual sync.** The 🔄 Sync with Mela row is the ONLY writer
  and runs ONLY when pressed: import new recipes (cap 40) → backfill
  descriptions (cap 60) → mirror the cook week (pointers, groceries, note).
  No hourly hitchhiker, no wake-Mela, no LaunchAgent. `src/sync.py` has no
  meal lines any more.
- **D13 · Mirror the cook week only.** The routine's cook Sunday
  (`meal.cook_sunday(routine_task, today)`, the LIVE routine) picks the week;
  that week's pointers are deleted-then-created (HANDOFF_ROUTINES §8, §4
  below), its groceries made/kept/dropped, its note bullet written. Weeks
  after it live in the calendar until their Sunday comes round. An empty
  week clears the pointers and the OPEN stale groceries; the bullet and the
  toast say "nothing planned in Mela".
- **D14 · The quarter view reads the calendar.** ctx:mealq lists
  HORIZON_WEEKS = 13 rows from the cook Sunday, one per week, this week
  starred, empty weeks shown (valid False, "Plan it in Mela: ⌘⌥A Add to
  Calendar"); ctx:mealw:<sunday> is one week's meal rows. Read side only
  (`meal_write.plan_view`), never a write.
- **D15 · Picker, ledger, hourly: removed.** ctx:mealplan, 🎲 Surprise,
  ✅ Commit, the cooked-history ledger (`meal_ledger.json`), 📥 Import and
  📝 Fill as rows, `meal_write.hourly`, `_wake_mela`, `config.meal_wake_mela`.
  The IMPORT ledger (`meal_import.json`) STAYS: it is the dedupe memory of
  what was imported, not a plan. "Cooked N weeks ago" / "next Sun …" now
  come from the calendar (`meal.last_cooked` / `next_planned`, new
  signatures).
- **D16 · Slot from category.** 🍳/🍛/🌮 comes from the RECIPE's Mela
  category through `mela.meal_tag_for` + `config.get_meal_tag_map`, never
  from the event's time. A recipe in none of the three maps to slot "x",
  glyph 🍽️, shown and mirrored, never dropped. A planned uuid with no recipe
  in Mela's DB still yields a meal named after the event's summary, slot "x".

## 1. What it is (Vex's model)

Every Sunday evening Vex cooks THREE meals for the week: one breakfast, one
lunch, one snack, seven portions each. Recipes live in **Mela** (the recipe
app; Crouton until 2026-09-19). The PLAN lives in Mela's calendar (D11); the
doing lives in TickTick, mirrored by one row (D12).

## 2. Where things live

| Thing | Id / path |
|---|---|
| 🍳Meal Prep, the library list (kind TASK, list view) | `6a8abb444e699108a4693fa5` = `config.MEAL_LIST_DEFAULT` |
| 🥘 Meal Prep, the Sunday routine (🌅 Routines, RRULE weekly SU 19:00) | `6a9ed0dc0eecd103a69febee` = `config.MEAL_ROUTINE_DEFAULT`, registry key `meal` |
| its habit | `6aa27acd557832cfc9ea5d77` |
| tags | 🍱mealprep › 🍳breakfast · 🍛lunch · 🌮snack · 🛒groceries |
| Mela categories → tags | `02 • Breakfast`→🍳breakfast · `01 • Meal`→🍛lunch · `03 • Snack`→🌮snack (`mela.DEFAULT_TAG_MAP`, overridable by config `meal_tag_map`) |
| Mela's database (Mac) | `~/Library/Group Containers/66JC38RDUD.recipes.mela/Data/Curcuma.sqlite` (+ -wal/-shm; ALWAYS read a copy: `mela.snapshot()`) |
| the plan = Apple Calendar's store | `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` (+ -wal/-shm; ALWAYS a copy: `mela_cal.snapshot()` into `~/.ticktick_alfred/run/melacal/`, reused while the source mtimes hold, 600 s) |
| the import ledger (dedupe memory, KEPT) | `~/.ticktick_alfred/meal_import.json` |
| the lock | `~/.ticktick_alfred/meal.lock` |
| config keys | `meal_list_id`, `meal_routine_id` (defaulted: NO Configure-panel field, the okr_list_id rule), `meal_tag_map` |

**The join key is the Mela UUID.** Mela kept Crouton's ids on import, every
TickTick title carries `mela://recipe/<UUID>`, and `mela://recipe/<UUID>`
opens the recipe on the Mac (verified 2026-09-19). Titles the app saved may
be backslash-escaped: every reader goes through `meal.parse_title` /
`mela.link_uuid` (`pm.unescape_md` first).

## 3. The shapes

- **Library entry**: `[Name](mela://recipe/<UUID>)`, TEXT kind, no dates,
  one meal tag, the recipe as markdown in the description (the
  mela2ticktick format: `> 🔗`, `> 🌐`, Serves, ## Ingredients, ## Steps,
  ## Nutrition). Migrated from NOTE-kind + week-long dates by
  `Scripts/meal_migrate.py` (snapshot in `~/.ticktick_alfred/run/`).
- **Planned meal** (the calendar side, `mela_cal.Planned`): one calendar
  event per meal, url `mela://calendar/<cal>:<event>/<UUID>`, on the SUNDAY
  it is cooked (Vex's convention; the event's time is ignored, all-day rows
  are date only). `meal.cook_week_of(d)` = the Sunday on or before d; the
  week cooked FOR is the Mon..Sun after it (`meal.week_label` says "Week of
  <Mon>"). Hidden, cancelled and phantom-master rows are skipped.
- **Pointer** (this week's meal): `🍳 [Name](mela://…)` / `🍛` / `🌮` /
  `🍽️` (slot "x", D16), TEXT, child of the routine, in the Routines list,
  dated the cook Sunday. Minted by every sync; last week's are DELETED
  first (only pointer-shaped titles; the routine's own steps never). Never
  reopened, never moved.
- **Grocery list**: `🛒 [Name](mela://…)`, CHECKLIST kind, tag 🛒groceries,
  in the library list, due the Saturday before the cook Sunday (or today),
  `items[]` = ingredient lines scaled to 7 portions, description = the
  yield note (`meal_scale.scaled_ingredients`). Keyed by UUID: kept while
  its meal is still planned (re-dated), deleted when not, ticked ones
  untouched.
- **Weekly note**: `- 🥘 Meal prep` under `##### 💿 Data`, body = one line
  per slot (🍳 🍛 🌮) plus one per extra meal (a second breakfast, a 🍽️
  recipe), or a single "nothing planned in Mela" line for an empty week
  (`meal_write.note_lines`); link LAST, no checkbox (focus_blocks'
  LINK_TAIL_RE never sees a mela link). Written into the note of the week being cooked FOR
  (Monday after the cook Sunday), `ensure_note` mints it. Kill switch = the
  bullet deleted; a note minted before `meal.NOTE_SINCE` (2026-09-20) gets
  the bullet seeded once.

## 4. Why the pointers are deleted, not reset (the design's spine)

HANDOFF_ROUTINES §8: only the APP resets a repeating task's children; API
completion leaves them completed and absent from the next occurrence, and
the app's own completion REOPENS them. Both roads are wrong for a routine
whose children change every week. Delete-then-create is right on both. So:
`routines.ROUTINES["meal"]` carries `"reset": False`, and both
`xact.routine_checkin` (⇧ Done) and `xact._routine_steps` /
`routine_runner.default_steps(reset=False)` honour it. A routines.json entry
for `meal` must never contain `{"do": "reset"}`.

## 5. Modules

| File | Role |
|---|---|
| `src/mela_cal.py` | IMPURE, stdlib: the calendar reader. `STORE_PATH`, `MelaCalError` (one toast line), `Planned` (date · start · all_day · uuid UPPER · title · calendar · event_id · url), `store_present`, `snapshot` (the mela.py shape, PermissionError → the FDA toast), `parse_url`, `plan(since, until)` (every calendar, url LIKE `mela://calendar/%`, skips hidden / cancelled / phantom_master, local date from start_tz), `freshness` |
| `src/meal.py` | PURE: title grammar, slots (b/l/s/x), week arithmetic (`cook_week_of`, `cook_sunday`, `week_label`), `Meal` / `Week`, `slot_for_recipe`, `weeks_plan` (every week present, meals b,l,s,x → date → name), `week_meals`, `last_cooked` / `next_planned` (over the calendar plan), `sort_for_lib`, `sync_payload`, `sync_text` |
| `src/meal_scale.py` | PURE: yield ladder (field → text → protein estimate → none), quantity parser, half-up scaling, grocery filter |
| `src/mela.py` | Mela DB snapshot + loader, `render_markdown` (byte-identical to the mela2ticktick script), `meal_tag_for`, `freshness` |
| `src/meal_notes.py` | the weekly bullet (`write_block`, seed rule) |
| `src/meal_write.py` | THE writer: `sync` (under `_lock`: `import_new` cap 40 → `backfill_descriptions` cap 60 → calendar → LIVE routine → `week_meals` → pointers deleted-then-created → `_write_groceries` → `_write_note` → cache mirror; `dry` / `TICKAL_MEAL_DRY=1` prints and writes nothing), `plan_view` (the read side: never raises, `error` carries the toast line, injectable), `hub_counts`, `PACE` 1.0 s, `HORIZON_WEEKS` 13 |
| `Scripts/browse.py` | `render_meal` (ctx:meal), `render_mealq` (ctx:mealq, the 13 weeks), `render_mealw` (ctx:mealw:<YYYY-MM-DD sunday>), `render_meallib` (ctx:meallib:<slot>), `render_mealgroc`; the 🥘 door row in `render_routines`; parse_ctx's alias guard covers `ctx:meal*` |
| `Scripts/xact.py` | `_meal_run` (copy of `_okr_run`), `meal_sync`, `meal_setlist`, `_dry_meal` |
| `src/routines.py` · `routine_runner.py` · `routine_link.py` (`view:meal`) · `link.py` (`VIEW_CTX["meal"]`) | the registry entry and its gates |
| `Scripts/meal_migrate.py` | one-shot NOTE→TEXT + dates cleared: dry-run / `--probe TID` / `--apply` / `--rollback FILE` |
| `tools/plist_surgery/phase_meal.py` | the canvas phase (§7) |

Gone 2026-09-21 (D15): `render_mealplan` / ctx:mealplan, `meal_commit`,
`meal_import`, `meal_fill`, `meal_groceries`, `meal_write.commit` /
`preview` / `rebuild_groceries` / `hourly` / `_wake_mela`, the meal block
in `src/sync.py`, `config.get_meal_wake_mela`, and in `meal.py` the ledger,
surprise, `sort_for_pick`, `slots_from_ids` / `ctx_for` / `next_slot` /
`commit_payload` / `outcome_text`.

Tests: `tests/test_mela_cal.py` (throwaway sqlite with the two tables, no
real store) · `test_meal.py` · `test_meal_scale.py` (162) · `test_mela.py`
(59) · `test_meal_write.py` (FakeAPI, injected planned/recipes) ·
`test_meal_screens.py` (fake cache, injected plan_view) - all in the
Makefile `test:` list. No network, never the real calendar.

## 6. Contracts and traps

- **Chords** (the OKR invariants, `_okr_seal`): six chords
  as fresh dicts on every row, no xact on ⌘/⌥ EVER, ⏎ navigation via
  `xact:crmbrowse:<ctx>` (BrowseCtx trampoline, clean bar), ⌥ the same hop
  by variable. THE MEAL ROW (hub this-week, ctx:mealw, ctx:meallib): ⏎
  `open:mela://recipe/<UUID>`, ⇧ `open:<web>` (dead, "No web page", when
  the recipe has no ZLINK; the Browse SF's ⇧ road is dispatch.py, which
  executes open: args), ⌥⌘ `copy:mela://recipe/<UUID>`, ⌘ live ONLY when
  the meal resolves to a library task (the row then carries task_id /
  task_list_id / task_title / item_type=task), ⌥ and ⌥⇧ dead on plan rows
  (library rows keep ⌥ = drill subtasks), ⌃ back.
- **Full Disk Access (the FDA caveat).** The calendar store is TCC
  protected. The CLI reads it; ALFRED must be granted Full Disk Access
  (System Settings › Privacy & Security › Full Disk Access) or every read
  raises `MelaCalError("Calendar store unreadable · give Alfred Full Disk
  Access …")`. The screens never crash on it: `plan_view` returns `error`,
  the hub's status row shows the line and the head row wears a "cache"
  chip; `sync` refuses with the same text. A test or a render from the
  shell can pass while Alfred fails - check the status row in Alfred before
  calling the reader done.
- **Live reads** in `sync`: the routine task (`api.get_task`), its list, the
  library list - never the cache for the cook Sunday or the pointer ids
  (routine resets invalidate all_tasks; a cached child id may be gone). The
  hub's this-week rows read the routine list live on an EMPTY bar only,
  kept 45 s as cache key `meal_kids`; the plan itself comes from the
  calendar snapshot.
- **Budget**: sync ≈ 20 calls + up to 40 imports + 60 backfills, all at
  `PACE` 1.0 s. TickTick enforces **100 requests per MINUTE** (hit
  2026-09-19 when the migration's paced reads overlapped an hourly sync) -
  `api.RateLimitError` ends any run at once; the toast says how far it got.
- **Ledger paths resolve at call time** (`ledger_path or IMPORT_LEDGER`): a
  test that re-points `mw.IMPORT_LEDGER` after import would otherwise write
  the REAL file (it did once). Only the IMPORT ledger exists now.
- **`_write_note` never raises**; the toast says "note not written" when the
  bullet is absent, the periodic list is off, or the network failed.
- **Mela freshness**: the DB reflects the phone only after Mela.app has
  synced on the Mac; the calendar store reflects the phone once iCloud has
  delivered the event. The hub's status row shows Mela's data age and the
  calendar's planned count. Nothing wakes Mela any more (D12).
- **Cancelled events**: `mela_cal.plan` skips them by the store's status
  column; the module docstring records which value marks cancelled (read it
  there, this doc will not repeat a number that a macOS update can move).
- **Yield inference** is a heuristic (2/3 of the library resolves); the
  grocery description always says which rung answered so a wrong guess is
  visible. Rounding is half-up, never `round()` (banker's).

## 7. Phase log

1. Model + config - zero canvas. `f` 2026-09-19.
2. Migration - `--probe` on Berry and Apple Crumble passed all 7 verdicts
   (kind TEXT, dates null, 959-char description intact, verified through
   the TickTick MCP); `--apply` in progress / done (see the session bridge).
3. Screens - zero canvas; reachable from the Routines hub's 🥘 row.
4. Writers + verbs - zero canvas.
5. Weekly note block + template synced live.
6. Routine registry entry + sync hitchhiker (the hitchhiker is GONE since
   phase 9, D12; the registry entry stays).
7. **Canvas phase** `phase_meal.py` - APPLIED LIVE 2026-09-19 20:59:
   main-menu leg `ctx:meal` → B31D6E02, caller chain keyword `{var:meal_kw}`
   (default `tml`) + UNSET hotkey → Arg&Vars → BrowseCtx 60A44279, Settings
   row `14-` → `xact:meal_setlist` → End. 415/375/7-0-0 → 419/381/7-0-0,
   userconfig 55 → 56 (audit verified after `make sync-pull`). `main_menu.py`
   pushed in the same breath. Migration `--apply` done the same evening:
   112/112, 0 mismatches. Vex smoke-gates the canvas (tal → 🥘, tml,
   ⚙️ Meal Prep List).
8. Docs: vault `X • docs/X • 51-meal-prep.md` (+ index, cheatsheet, 48-periodic,
   CHANGELOG), `Scripts/docs_menu.py`.
9. **Remodel 2026-09-21 (D11 to D16) - zero canvas.** Vex pulled the hourly
   hitchhiker the morning after it shipped ("this python script that runs
   in the background is unacceptable"). New `src/mela_cal.py` reads the
   plan from Apple Calendar's store (a snapshot copy, every calendar, url
   prefix filter). `meal.py` lost the ledger / surprise / picker helpers
   and gained `cook_week_of`, `Meal` / `Week`, `slot_for_recipe`,
   `weeks_plan`, `week_meals`, `last_cooked` / `next_planned` (calendar
   signatures), `sort_for_lib`, `sync_payload` / `sync_text`.
   `meal_write.py` lost `hourly`, `_wake_mela`, `commit`, `preview`,
   `rebuild_groceries`, `_resolve_picks` and the cooked ledger, gained
   `sync` (one writer, cook week only) and `plan_view` (the read side).
   `src/sync.py` has no meal lines; `config.get_meal_wake_mela` is gone.
   `xact.py`: `meal_sync` replaces `meal_commit` / `meal_import` /
   `meal_fill` / `meal_groceries`. `browse.py`: ctx:mealplan replaced by
   ctx:mealq (13 weeks) + ctx:mealw:<sunday>; the meal row got ⇧ web and
   ⌥⌘ copy-Mela-link. Tests rewritten (`test_mela_cal.py` new, throwaway
   sqlite), Makefile list extended. The existing canvas rides untouched:
   the `ctx:meal` leg, the `tml` chain and the Settings row `14-` all land
   on ctxs that still exist. Docs: this file's §0, the vault 51 page, the
   cheatsheet's meal rows, 48-periodic's 🥘 line, CHANGELOG [Unreleased].
   Vex smoke-gates: the hub on an empty calendar week, ⇧ on a meal with
   and without a web page, one dry sync (`TICKAL_MEAL_DRY=1`), then a real
   one, then the status row inside ALFRED (the FDA caveat, §6).

## 8. Open / next

- **Alfred's Full Disk Access is unverified from Alfred itself.** The CLI
  reads the store; the first hub open in Alfred tells (status row). Until
  Vex confirms the grant, treat the reader as CLI-proven only.
- The hub could show the week's macros (Mela nutrition text) per meal.
- A routine step `[This week](alfred://…view:meal)` can be pasted into the
  🥘 Meal Prep task via ⌘ Actions › ☑️ TickTick Internals once the view slot
  ships in `internal_links` (not done: the ☑️ row list is pinned by tests;
  add it when Vex wants the link).
- `docs/00-index.md` (vault `X • 00-index.md`) still describes the hub as
  "the week's three meals from a Mela-fed recipe library" - one line to
  re-word to the calendar model on the next docs pass.
