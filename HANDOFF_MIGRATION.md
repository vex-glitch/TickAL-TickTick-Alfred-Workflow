# HANDOFF · THE BIG ROCK (Eagle + CRM migration) - 2026-07-30, EXECUTED 2026-09-07

## 0. STATUS 2026-09-07 - THE MIGRATION IS EXECUTED

**312 groups / 3,822 photos filed. Audited by 4 independent agents (disk,
TickTick, ledger, adversary): every home folder exact, 0 photos left
behind, 0 deleted, 0 engine-minted duplicates.** Vex's 🟢 was 2026-09-07
10:50; autopilot ran 10:53 to 11:30 with two false starts (real TickTick
limit is 100 requests/MINUTE, Eagle refuses library switches while busy).

What exists now:
- Eagle TV/FM: one folder per tattoo under `01 Raw` (303 homes, names
  exact), CRM: 9 homes under `Archive/`. Superseded snapshots (1,011) and
  the 20 frozen duplicate imports stay in their OLD folders untouched.
- TickTick: 7 year lists `🗄 <year> · Logbooks` in 📦Archives holding 61+
  archived logbooks; 32 undated logbooks open in Records; 44 customers (5
  adopted, 39 minted); 273 pipeline entries (📸raw, kind TEXT).
- Ledger `~/.ticktick_alfred/run/migration.sqlite3`: egroup (309 executed,
  3 merged), mover (3,822, prior state for undo), event (full trail).

Post-audit repairs (commit 9b793dd): three spelling twins my ad-hoc SQL
rulings caused (Philip, Octopuss, Professor vs live Profesor) trashed
(TickTick Trash, restorable) and merged; Artsy 2 given its own logbook;
five double-spaced titles fixed. **Lesson: a ruling that is not in
`migration._FIXUPS` does not exist** - a doc re-parse overwrites SQL.

**Afternoon 2026-09-07 (after the compact):** old folders swept to the bins
(291), 92 logbooks given their 🎬 line, 13 To Edit backlog rows folded
into their migration rows (homes → 02 Edit), portfolio finals pulled out
of raw homes (Vex ruling: finals ONLY in 04 Portfolio; 29 finals-only
homes binned), every migrated shot renamed `{folder} • Raw|Portfolio • n`,
Edit this learned the migrated road. A 15-agent audit then found what
rules cannot: 635 byte-identical twins inside tattoos' own folders (the
July pull re-imported backup originals that already existed - now in
`🗑 Deleted/Duplicates`, item.dup_of set) and four doc names that were one
tattoo (merged, pinned in `_FIXUPS`). Cross-tattoo identical shots that
need Vex's ruling are listed in the session's last report (Lil Crow,
Germany - Crow, Wing/Wings/Eye Neck, Bradonja-Yoda⇄Clemens dual placement,
FM Rose Coverup⇄Shoulder Mandala Germany). Tools: scratch `audit_fixes.py`
(dedupe / merges / renumber, guarded by ledger phase 'audit').

Open decisions (Vex's, nothing pending on the engine):
1. 282 old source folders now hold only superseded/frozen copies (113 are
   empty): sweep to each library's `🗑 Deleted` bin, or leave. Nothing
   is deleted either way.
2. Two pre-existing pipeline entries (Erol - Griffin, Phillip - Samurai)
   point at empty CRM folders beside the migration's entries: complete or
   keep.
3. `Svicarac - Athena` (18 items, FM root, created after the doc) was
   never named - migrate later via the doc round-2 road or leave.
4. 39 groups deliberately have no pipeline entry (30 portfolio-only
   sources, 9 CRM-library); 11 two-library tattoos link only their
   first-minted home from the logbook's 🦅 line (the other home is
   reachable from its pipeline entry).

Tools: `migration.reopen(con, gkey)` for a delta on an executed group,
`migundo` / `migredo`, `migcheck`, `run_autopilot`. Archive-by-year UI
wiring (age rule, /year scope, finish_logbook tail, full RECORDS_ID sweep)
is the NEXT round - the substrate (records_pids, create_logbook
project_id=, ensure_archive_list) shipped with the engine.

Written for Fable, taking over mid-job. Vex hit shipped bugs that must be
fixed first; this doc is so the migration work is not lost while that
happens.

**Read order:** [CLAUDE.md](CLAUDE.md) iron rules → [HANDOFF.md](HANDOFF.md)
§1-3 → [HANDOFF_CRM.md](HANDOFF_CRM.md) §2 (the unified home IS the current
tree) → [HANDOFF_CONTENT.md](HANDOFF_CONTENT.md) → this doc → the approved
plan at `~/.claude/plans/bright-orbiting-petal.md` (also mirrored to the top
of `enumerated-humming-blum.md`, which is the only file Vex's sidebar panel
shows).

**Canvas: 393 objects / 350 edges / 1-0-0, userconfig 53.** Unchanged by any
migration work and expected to stay that way - everything here is `.py` and
rides `xact:crmbrowse:ctx:…` through the shared BrowseCtx Call-ET.
**37 commits unpushed** (Vex pushes at wrap; he announces wraps, never
propose one).

---

## 0. THE BUG QUEUE (read this first, it is why you are here)

Vex said: *"I have encountered bugs you shipped that cannot be ignored. We
must sort them first."* He has named ONE so far. **He has not listed the
rest - ask him.**

### 0a. FIXED - the AppleScript prompt box (`ef6a590`, `2206a47`)

Every typed prompt in the workflow (`_ask`, `_dialog`, `_choose`, the v2
login, the new-nested-tag box) goes through **`Scripts/xact.py:_osa_dialog`**.
It broke three ways in one day, all from that one function:

1. **Mangled panel.** `af5a940` had it run the dialog inside
   `tell application (path to frontmost application)` so it would open
   holding the keyboard. Vex's ➕ New customer box came up with the buttons
   stacked at the TOP LEFT, the field a 40px stub, nothing clickable. The
   exact render was **never reproduced** - Eagle, Photos, TickTick and Alfred
   each drew a correct 420x166 panel on demand - so what shipped removes the
   MECHANISM, not a caught culprit. The old guard could never have saved it
   either: it fell back on a NON-ZERO exit, and a mangled-but-answered dialog
   exits 0. **If Vex reports a broken-looking box again, it is something
   else; get a fresh screenshot.**
2. **2 second delay.** The first fix used `tell me to activate`. Timed, 3
   runs each, osascript start to return: bare `.043s` · System Events
   activate `.128s` · `tell me to activate` **`2.089s`**. Activating our own
   osascript is the whole two seconds - it is a background-only process and
   the activation sits in a wait that never resolves.
3. **Wrong monitor.** System Events centres panels on ITS main screen,
   measured `4170,-419` = Vex's portrait 1080x1920.

**Current shape:** System Events hosts and activates the dialog (native,
always running, never busy, still not the roll of the dice that hosting in
the frontmost app was), and `_DIALOG_MOVER` runs as a SECOND process
alongside it - `display dialog` blocks, so it cannot be the same one - which
waits up to 3s for the panel and parks it centre-x, one-third-down on
`NSScreen's screens()` item 1 (the menu-bar screen by definition, AX origin
0,0). Measured after: `1710,301`. It reads the panel's own size so a fat
`choose from list` centres too, and it fails silent: no Accessibility just
means the box opens wherever System Events put it.

**Vex's three screens** (AppKit frames): `0,0 3840x1080 @2x` menu-bar ·
`3840,15 1080x1920` portrait right · `400,1080 3440x1440` above. "Main
monitor" was read as the menu-bar one; he may still correct that.

**Proof it works** (re-run any of these after touching `_osa_dialog`):
synthetic `probeOK` + Return lands IN the field, `window 1 of process
"System Events"` reads `TickAL, 420, 176, 1710, 301`, and the frontmost app
after dismiss is the one from before.

⚠️ **Vex has not smoke-tested it yet.** CRM > Manage > ➕ New customer.

---

## 1. What this job is

Vex has years of tattoo photography in three Eagle content libraries, in a
shape the workflow cannot use. Three tangled problems:

1. **Folder names disagreed with the code** - SOLVED, §3.
2. **Over half the files were downscaled copies**, not originals, because
   they were dragged out of Photos.app instead of exported - SOLVED, §4.
3. **The old material has no CRM identity** - customers and logbooks that
   never existed. NOT started, §6.

**The invariant, stated by Vex and honoured throughout: nothing is ever
deleted.** Originals were added *beside* the copies they supersede and the
copies tagged, never replaced. Keep it.

---

## 2. Decisions Vex has made (binding - do not re-litigate)

| Question | Decision |
|---|---|
| Content-library folders | **Four, FLAT: `01 Raw` / `02 Edit` / `03 Post` / `04 Portfolio`.** No `Content pipeline` parent. Matched by SUFFIX because he renumbers prefixes. |
| Old finished records | **Move to per-year TickTick lists** (`CRM • Archives 2024`…). The workflow reads from several lists. Default views hide >1yr old **unless still active**; a year scope reaches the rest. |
| How much becomes CRM | **Only what he can name.** Unnamed material still gets its Eagle folder and its Content PL entry - it is NOT invisible, it just has no logbook/customer. |
| Naming method | **A markdown document he edits in Obsidian and saves back.** NOT 256 dialogs, NOT browse screens. His idea, and it is better than what was planned. |
| Derivative with no original | **Keep it, tag `no original`.** |
| `Reference/` (4,493 PNGs), `Brand` (458), `Content Ideas` | **Excluded entirely**, left in place. |
| Media type | **Stops being a folder, becomes a tag.** One folder per tattoo. This is the whole point of the reorganisation - he had the same tattoo in three places. |
| Naming convention | Eagle base `Customer - Tattoo` (**hyphen**); TickTick `🎨 Customer • Tattoo` (**bullet**). Items `{base} • {Stage} • {n}`. |
| Order of work | review/name → move into place → **then** archive-by-year + workflow wiring. His call, and it is right: archive-by-year solves a pollution problem that does not exist until the migration creates it. |

---

## 3. SHIPPED - Stage 0, folder reconciliation (`73e92e4`)

`find_folder` was exact AND case-sensitive, so the code's `Content pipeline`
never matched his `Content Pipeline` and minted a **twin** in FM. TV was one
promote away from the same fork.

**New in `src/eagle.py`:**
- `PIPELINE` - `(suffix, canonical-name)` pairs, the `_LIB_SUFFIX` shape.
- `find_folder_suffix(suffix, tree, root_only=True)` - `(NN )?<suffix>$`,
  **case-insensitive**, root only. `Raw` adopts `01 Raw` but never
  `Raw Tattoos`/`Raw Videos`; `Portfolio` never swallows the legacy
  `Tattoo Portfolio` (that is migration material).
- `pipeline_folders(create=True)` - one tree read, adopt-or-create, flat.
- `item_base(name)` → `(base, stage, n)`, the rename-proof inverse of
  `item_name`. Parses **from the right** against a CLOSED stage vocabulary
  (`Consult|Prep|Design|Finished|Healed|Edit|S\d+`), so a base containing
  ` • ` survives and unknown names fail closed. Four readers share it.

`_cp_folders`/`_portfolio_folder` delegate to it; six call sites key off
suffixes. FM's twin was emptied into `02 Edit` (folder moved, so ids and
therefore the TickTick links survived) and the husk retired to a
`🗑 Deleted` bin. Undo record: `~/.ticktick_alfred/run/fm_twin_undo.json`.

**`tests/test_eagle.py` +13 checks and is finally wired into `make test`.**

⚠️ **Vex has NOT smoke-tested this** - he deferred it to prioritise the
originals. 🎬 Edit this / 📥 File edited / ⭐ Portfolio against the new
folders are unverified in his hands.

---

## 4. SHIPPED - Stage 3, the originals (`2b73ad2`, `2059148`, `de91844`)

**Result: 1,011 originals recovered, 2,101 tagged `no original`, 43 held for
review. Both libraries balance `original` == `superseded` exactly.**

`src/migration.py` is the engine. **The ledger is SQLite at
`~/.ticktick_alfred/run/migration.sqlite3`** - a deliberate deviation from
the repo's JSON convention (`cache.set` rewrites a whole file per mutation;
4,727 rows would mean a 3 MB rewrite per decision and corruption on abort).
Tables: `item`, `folder`, `backup`, `event`, `meta`. `event` is the resume
spine - `attempt` before firing, `ok`/`err` after; `unfinished()` returns
anything unpaired.

**How the matching worked, because it is not obvious:** filenames are
useless (Eagle's were rewritten; stem matching found 25 of 1,872). The join
is on **capture instant** - Spotlight's `kMDItemContentCreationDate` against
the backup's `st_birthtime`, with a whole-hour offset ladder for timezones.
Validated against an independent signal: for the 424 matches whose backup
path carries a subject word, the Eagle folder name agreed **92.7%**.

That validation earned its keep twice:
- It exposed that **exact-second ties agreed only 50%** (vs 91-100%
  elsewhere) because an exact tie is an export *batch*, so the tie-break
  picked a neighbour. Those 43 are demoted to `conf='tie'` and **can never
  auto-pull**. They still need eyes.
- It made me suspect the huge gains (x272, 73 MB stills) were videos matched
  to stills. They were not - all 1,011 are still→still, and 89 of the 93
  extreme gains are `jpg → dng`, i.e. **ProRAW originals against
  thumbnails**. The extremes are the best recoveries.

**What landed where:** the original imports into the **same folder** as the
derivative, takes its **name** and tags plus `original`; the old item keeps
its name and gains `superseded`. Annotation `orig:<derivative eid>` is the
idempotency mark.

Two defects found and fixed at the root during the run - both worth knowing
because they are the shape of bug this job produces:
- The retry path marked a row done **without tagging the old item**, so five
  items would have been missed forever by "select superseded, delete".
- **One duplicate import.** The idempotency check asked `item/list`, which
  *lags a fresh import by seconds*. Fix: `new_eid` is written the instant
  `add_items` returns, and **the ledger, not Eagle's listing, is the
  idempotency oracle**. The duplicate went to Eagle Trash.

Backup is untouched and still ~100% dataless except what was pulled
(~5 GB, evictable with `brctl evict`).

---

## 5. SHIPPED - the NOTE-kind fallout (`1692387`)

Vex flipped the three Content PL lists to `kind=NOTE` (verified live via
MCP; the `projects` cache still said TASK and was stale - **trust the MCP,
not the cache**).

**Good news that had to be checked: the pipeline screens are unaffected.**
`sync.py`'s `all_tasks` loop skips only `SMART_LIST`, so NOTE-kind lists land
there as before - proven by CRM Records (always NOTE-kind) holding 66
entries in `all_tasks` right now.

**But** entries now live in **both** `all_tasks` and `all_notes`, and
`cache.find_task` searches them in that order. Four cache patches touched
one pool only, stranding a twin the next lookup would return. Sharpest
consequence: a second ⌥⇧ Posted would have **re-run the entire Eagle
`03 Post` sweep**. Fixed at `_complete_cache_patch`, dispatch's `complete:`
branch, `_patch_task_cache`, and the two content list-move patches.

Two further claims were **REFUTED** and deliberately not acted on (the mint
needing `all_notes` injection; the mint omitting `kind=`). Items are
`kind=TEXT` inside a `kind=NOTE` project and everything works.

**Knowingly left alone:** `delete_action`, `rename_action`,
`everything_search`, focus/periodic still patch one pool. Equally wrong for
CRM Records long before this and never surfaced - kept out of a
migration-critical change.

---

## 6. NOT STARTED - what is next, in Vex's order

### 6a. The naming document
Generate an `.md` into his **Obsidian vault**, one block per folder, ~256
folders, pre-filled where confident:

```markdown
### Bradonja - Cat   · 9 shots · 2023-06 → 2023-08 · TV/Raw Tattoos
C: Bradonja
T: Cat

### Baby Yoda       · 5 shots · 2024-02 · TV/Raw Tattoos
C:
T: Baby Yoda
```

**Empty `C:` = skip.** No separate marker to remember.

Nameability, measured (`folder` table + `eagle.fuzzy_match` vs his 31
customers): **TV 97 conventional / 1 customer-only / 135 need input;
FM 2/1/11; CRM 1/2/6.** For TV the missing half is usually the **client** -
the folder already names the tattoo (`Baby Yoda`, `Black Panther`).

⚠️ **`create_customer` does NO dedupe whatsoever.** Two spellings of Ivona
in the doc means two Ivonas, permanently. The doc must surface near-duplicate
`C:` values before he fills it in.

### 6b. The destination matrix (the spec Vex asked for and has NOT yet seen)

| Source (under `Review`) | Eagle destination | TickTick |
|---|---|---|
| `Raw Tattoos`, `Healed Tattoos`, `Reel Material`, `Raw Videos` | `01 Raw/{C} - {T}` | 📸raw note; `healed`/`reel`/`video` survive as **tags** |
| `Content Pipeline/To Edit` (724) | `02 Edit/{C} - {T}` | 📸edit note |
| `Tattoo Portfolio` (165) | `04 Portfolio/{C} - {T}` | posted |
| CRM `Review` (221, 9 folders) | `CRM/Customers/{C} - {T}/…` | logbook in its year list; content note only if 🎬 set |
| `superseded` copies | **stay in Review** | nothing |
| `Brand`, `Content Ideas`, `Reference` | untouched | nothing |

**State follows destination** - not "raw for everything", which is what was
wrongly said in chat before Vex caught it.

**The move rule, corrected by Vex:** one photo per slot. Where a replacement
was found, the **new original moves and the `superseded` one stays behind**;
where none was found, the old one moves. Same count as before, no duplicates
in the new home. The move set is `everything except superseded` - computable
exactly from the ledger.

**Unnamed folders still get a Content PL note.** Verified: `render_contentpl`
reads `all_tasks` filtered by list + 📸 tag, so **no note = invisible in the
pipeline**. Title uses the folder's existing name until he names it.

### 6c. Then archive-by-year, then the workflow wiring
Design is in the plan file §Stage 1. Key points: one computed table in
`areas.py` mirroring `CONTENT_DESTS`; `records_notes()` (`crm_records.py:768`)
is the **single** read choke point - widening `!= RECORDS_ID` to
`not in records_pids()` costs zero extra cache reads; then an exhaustive
sweep of every hardcoded `RECORDS_ID` used *as a pid*.

⚠️ **Probe first, it can kill the design:** nothing in this repo has ever
moved a `kind="NOTE"` across lists. Test `api.move_task` on a throwaway note
with body, tags and an attachment before building on it.

⚠️ **Silent-corruption trap:** `api.update_task` defaults `projectId` to the
pid you pass, so `update_task(tid, RECORDS_ID, …)` on a note living in an
archive list does not 404 - it **moves it back**.

Vex refined this: logbooks should be **created directly in their year list**,
not created in Records and swept later. One write instead of two.

---

## 7. Traps (everything learned on this job)

**Hook** - `.claude/hooks/protect_alfred_plist.py` denies any Bash command
containing an interpreter name AND `com~apple~CloudDocs`, even when
unrelated. `migration.backup_root()` globs for the path; never put the
literal on a command line with `python`.

**Eagle**
- **No folder-delete API** (probed 404). A wrongly named folder is permanent.
  Create folders only from confirmed names, after the note exists.
- `update_items` **REPLACES** folder membership. Record `prior_folders_json`
  before any batch or a bad call unfiles hundreds of photos irrecoverably.
- `move_folder` needs `time.sleep(0.4)` + a heal pass, or folders end up
  double-parented and Eagle's sidebar wedges (happened once).
- `_heal_double_parents(fids, parent_id=None)` - pass `parent_id` outside
  CRM; it defaults to CRM's `Archive/`, which no content library has.
- **`item/list` lags a fresh import by seconds.** Never use it as an
  idempotency oracle - that is what made the one duplicate.
- Switching libraries drops the Eagle selection.
- `_mcp_call` does a full handshake **per call** - batch aggressively.

**iCloud** - `brctl download` returns **before** the fetch completes. Poll
`st_blocks` until non-zero. `os.stat` never triggers a download; reading
bytes does.

**Spotlight** - `mdls` batching must assert `len(vals) == len(chunk)`. A
short exec pairs every later file with the **wrong** capture date, and
therefore the wrong original.

**TickTick**
- 300 requests / 5 min → HTTP 500 `exceed_query_limit`; `_RETRY` excludes 500
  and POST. ~11-12 requests per migrated tattoo ⇒ ~25 tattoos per window.
  Pace at 80% in `migration.py`, **not** in the shared `api.py`.
- NOTE-kind list entries live in **both** `all_tasks` and `all_notes`.
- `create_customer` has no dedupe.
- The `projects` cache lags list-kind changes - use the MCP.

**CLI** - `browse.py` reads only `sys.argv[1]`; the query rides inside it
after a space. Never pipe with `2>&1` when parsing the JSON. `actions.py`
cannot be CLI-rendered (hangs in `_pomo_app_state`).

**Dialogs** - every AppleScript prompt must go through `xact._osa_dialog` or
it opens unfocused and ignores the keyboard.

---

## 8. Verification

```bash
cd "/Users/vex/Claude/TickTick Alfred Workflow"
export crm_list_id=69fed9d51fe6d10d8510bf15 \
       crm_records_list_id=6a4e50e9842a1194a7c681e1 \
       crm_records_tags="🗂️Customer, 🗂️Logbook, 🗂️Lead, 🗂️Archive"
make test                                   # 150 + 64 + 47 checks
python3 tools/plist_surgery/audit.py        # 393 / 350 / 1-0-0
python3 Scripts/browse.py "ctx:contentpl:tv:all"   # 27 rows, NOTE-kind list
```

Ledger:
```bash
DB=~/.ticktick_alfred/run/migration.sqlite3
sqlite3 "$DB" "select lib,klass,count(*) from item group by 1,2;"
sqlite3 "$DB" "select backup_conf,count(*) from item where backup_conf is not null group by 1;"
sqlite3 "$DB" "select count(*) from item where state='sourced';"   # 1011
```

Backup must stay dataless apart from what was pulled - count materialised
files with `find … -exec stat -f '%b %N' {} + | awk '$1!=0'` (shell only, no
`python` in that command, see the hook trap).

---

## 9. Working with Vex

- He navigates by **leader keys** - describe locations as drill paths
  (CRM > Logbooks > …), never as keywords.
- **A bug report IS the spec.** Fix the behaviour; do not explain the design.
- He **smoke-gates every canvas change**: apply → report → STOP.
- **No en/em dashes anywhere.** Row subtitles stay caveman-terse.
- Blanket "all good" = apply everything listed; "all good, but X" = all
  except X.
- He announces wraps. **Never propose one.**
- Chat is a bad medium for specs - he said so, and he was right. Put
  anything structural in a document he can read top to bottom.
