# 🥘 Meal Prep · subsystem doc, 2026-09-19

The week's three meals, planned in TickAL from a Mela-fed recipe library.
Written by the Fable session that built it (plan: `~/.claude/plans/
deep-doodling-peach.md`). Read `CLAUDE.md` first (the iron rules bind);
`HANDOFF_ROUTINES.md` §8 for the repeating-task trap this design is shaped
by; `HANDOFF_OKR.md` for the hub pattern it copies.

## 1. What it is (Vex's model)

Every Sunday evening Vex cooks THREE meals for the week: one breakfast, one
lunch, one snack, seven portions each. Recipes live in **Mela** (the recipe
app; Crouton until 2026-09-19). The plan lives in TickTick.

## 2. Where things live

| Thing | Id / path |
|---|---|
| 🍳Meal Prep, the library list (kind TASK, list view) | `6a8abb444e699108a4693fa5` = `config.MEAL_LIST_DEFAULT` |
| 🥘 Meal Prep, the Sunday routine (🌅 Routines, RRULE weekly SU 19:00) | `6a9ed0dc0eecd103a69febee` = `config.MEAL_ROUTINE_DEFAULT`, registry key `meal` |
| its habit | `6aa27acd557832cfc9ea5d77` |
| tags | 🍱mealprep › 🍳breakfast · 🍛lunch · 🌮snack · 🛒groceries |
| Mela categories → tags | `02 • Breakfast`→🍳breakfast · `01 • Meal`→🍛lunch · `03 • Snack`→🌮snack (`mela.DEFAULT_TAG_MAP`, overridable by config `meal_tag_map`) |
| Mela's database (Mac) | `~/Library/Group Containers/66JC38RDUD.recipes.mela/Data/Curcuma.sqlite` (+ -wal/-shm; ALWAYS read a copy: `mela.snapshot()`) |
| the ledger (cooked history) | `~/.ticktick_alfred/meal_ledger.json` |
| the import ledger | `~/.ticktick_alfred/meal_import.json` |
| the lock | `~/.ticktick_alfred/meal.lock` |
| config keys | `meal_list_id`, `meal_routine_id` (defaulted: NO Configure-panel field, the okr_list_id rule), `meal_tag_map`, `meal_wake_mela` (bool, default off) |

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
- **Pointer** (this week's meal): `🍳 [Name](mela://…)` / `🍛` / `🌮`, TEXT,
  child of the routine, in the Routines list, dated the cook Sunday.
  Minted by every commit; last week's are DELETED first (only
  pointer-shaped titles; the routine's own steps never). Never reopened,
  never moved.
- **Grocery list**: `🛒 [Name](mela://…)`, CHECKLIST kind, tag 🛒groceries,
  in the library list, due the Saturday before the cook Sunday (or today),
  `items[]` = ingredient lines scaled to 7 portions, description = the
  yield note (`meal_scale.scaled_ingredients`). Keyed by UUID: kept while
  its meal is still planned (re-dated), deleted when not, ticked ones
  untouched.
- **Weekly note**: `- 🥘 Meal prep` under `##### 💿 Data`, body = three
  plain bullets, link LAST, no checkbox (focus_blocks' LINK_TAIL_RE never
  sees a mela link). Written into the note of the week being cooked FOR
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
| `src/meal.py` | PURE: title grammar, slots, week arithmetic, ledger, picker ctx |
| `src/meal_scale.py` | PURE: yield ladder (field → text → protein estimate → none), quantity parser, half-up scaling, grocery filter |
| `src/mela.py` | Mela DB snapshot + loader, `render_markdown` (byte-identical to the mela2ticktick script), `meal_tag_for`, `freshness` |
| `src/meal_notes.py` | the weekly bullet (`write_block`, seed rule) |
| `src/meal_write.py` | THE writer: `commit`, `rebuild_groceries`, `import_new`, `backfill_descriptions`, `hourly`, `hub_counts` |
| `Scripts/browse.py` | `render_meal` (ctx:meal), `render_mealplan` (ctx:mealplan[:b[:l[:s]]], `-` = pick this next), `render_meallib:<breakfast|lunch|snack>`, `render_mealgroc`; the 🥘 door row in `render_routines`; parse_ctx's alias guard covers `ctx:meal` |
| `Scripts/xact.py` | `_meal_run` (copy of `_okr_run`), `meal_commit`, `meal_import`, `meal_fill`, `meal_groceries`, `meal_setlist` |
| `src/sync.py` | `meal_write.hourly(api)` after the OKR heal: imports (cap 10) then backfill within a 30-request budget at 1 s pacing |
| `src/routines.py` · `routine_runner.py` · `routine_link.py` (`view:meal`) · `link.py` (`VIEW_CTX["meal"]`) | the registry entry and its gates |
| `Scripts/meal_migrate.py` | one-shot NOTE→TEXT + dates cleared: dry-run / `--probe TID` / `--apply` / `--rollback FILE` |
| `tools/plist_surgery/phase_meal.py` | the canvas phase (§7) |

Tests: `tests/test_meal.py` (66) · `test_meal_scale.py` (162) · `test_mela.py`
(59) · `test_meal_write.py` (43, fake api) · `test_meal_screens.py` (45, fake
cache) - all in the Makefile `test:` list.

## 6. Contracts and traps

- **Chords** (the OKR invariants, `_okr_seal` reused): six chords on every
  row, ⌘ dead on non-task rows, no xact on ⌘/⌥, ⏎ navigation via
  `xact:crmbrowse:<ctx>` (BrowseCtx trampoline), ⌥ the same hop by
  variable. Pointer/library rows: ⏎ opens Mela (the cooking action), ⌥⌘
  copies the task link. Picker rows: ⌥⌘ opens Mela.
- **Live reads** in `commit`: routine, its list, the library list - never
  the cache (routine resets invalidate all_tasks; a cached child id may be
  gone). The hub's "This week" reads the routine list live on an EMPTY bar
  only, kept 45 s as cache key `meal_kids`.
- **Budget**: commit ≈ 20 calls; hourly meal work ≤ 30 requests at 1 s;
  foreground backfill 1.5 s. TickTick also enforces **100 requests per
  MINUTE** (hit 2026-09-19 when the migration's paced reads overlapped an
  hourly sync) - `api.RateLimitError` ends any run at once.
- **Ledger paths resolve at call time** (`ledger_path or IMPORT_LEDGER`): a
  test that re-points `mw.IMPORT_LEDGER` after import would otherwise write
  the REAL file (it did once).
- **`_write_note` never raises**; the toast says "note not written" when the
  bullet is absent, the periodic list is off, or the network failed.
- **Mela freshness**: the DB reflects the phone only after Mela.app has
  synced on the Mac. The hub's status row shows the age; `meal_wake_mela`
  lets the hourly sync `open -gj -a Mela` when older than 6 h.
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
6. Routine registry entry + sync hitchhiker.
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

## 8. Open / next

- Two weeks ahead: the plan targets the routine's next Sunday only.
- The hub could show the week's macros (Mela nutrition text) per meal.
- `meal_wake_mela` is off by default; turn it on if the "open Mela to sync"
  status keeps appearing.
- A routine step `[Plan the week](alfred://…view:meal)` can be pasted into
  the 🥘 Meal Prep task via ⌘ Actions › ☑️ TickTick Internals once the view
  slot ships in `internal_links` (not done: the ☑️ row list is pinned by
  tests; add it when Vex wants the link).
