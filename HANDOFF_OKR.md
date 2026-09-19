# HANDOFF_OKR - the goals (OKR) workflow

Started 2026-09-18. Source of truth for every phase of the OKR workflow: Vex's
model, his decisions, the defaults he did not object to, the data rules, and
the build order. Read this before touching `src/okr.py` or anything that
shows an objective. Vex's raw brain dump is `Scratchpad Vex.md` (repo root).

## 1. What it is (Vex's model, in his words where it matters)

"I see OKRs more like forecasting ... set OKRs once yearly or whenever, review
them quarterly and monthly. They should serve more like 'guiding star' rather
than daily work plan. Cause as we all know reality drifts from plans."

- ONE list holds the plan. Vex schedules it BY HAND in TickTick's timeline
  view (drag and drop) - the workflow never replaces that, it supports it.
- Every OKR item is ALL-DAY with no time, so it sits on top of his calendar
  outside the time blocks. Time blocks stay with the goals the periodic
  automations set.
- The list holds PLANNING COPIES. An item links (in its title) to the real
  thing it plans: an Objective links to its project's 📌CTA task or a list; a
  KR links to a task, subtask or note. Text-only items are allowed and get a
  link later ("if something comes up my mind, I need to be able to offload
  it"). Moving a copy NEVER moves the real task: the copy is the plan, the
  original is reality, and the gap between them is the point.
- KRs are DELIVERABLES (subtasks), never numbers. The only number is an
  objective's progress: ticked KRs over all KRs.
- Areas = the subtags of `0️⃣Area` (Vex's link `#t/MO-4j-KDo2FyZWE` is that tag,
  base64): 1️⃣Work, 2️⃣Personal, 3️⃣Learning, 4️⃣VexOS, 5️⃣Interests, 6️⃣Manager.
  MONEY GOES UNDER 2️⃣Personal (decided 2026-09-18) - no new tag. Today the
  list is tagged by PROJECT tags (💼tickal, 💼workflows ...) because all his
  focus is one project; that is expected to broaden later.

## 2. Levels and naming (the list's rules)

| Level | Prefix | Parent | Example |
|---|---|---|---|
| Year objective | `🏔️ Y • ` | none | `🏔️ Y • Productivity System` |
| Objective | `🥅 O • ` | a Y (or none) | `🥅 O • TickAL` |
| Key result | `🔑 KR • ` + ` - <CODE>` suffix | an O | `🔑 KR • Goals wf - TA` |

- Y objectives are one per area, "a step above objectives ... treated as
  objectives". Decided prefix: 🏔️ Y • (2026-09-18).
- A linked item keeps prefix and suffix OUTSIDE the link:
  `🔑 KR • [Goals wf](https://ticktick.com/webapp/#p/<pid>/tasks/<tid>) - TA`.
  A list link uses `ticktick:///webapp/#p/<pid>/tasks` (areas._list_link).
- CODE = the objective's short code (TickAL → TA, Onboard TickTick → OT).
  Proposed from initials when the O is created (several words: first letter
  of each; one word in capitals: its capitals, a plural s ignored - YNAB →
  YNA, OKRs → OKR; one mixed-case word: its humps - TickAL → TA, VexOS →
  VO; at most three), Vex confirms or types his own, stored in the O's
  DESCRIPTION (a `🏷️ TA` line), inherited by every KR added under it.
  Existing items keep whatever suffix they carry (the live ones say TT for
  Onboard TickTicks, his note said OT - never rewrite his).
- Codes are not always caps: 16 live KRs end ` - Shortcuts`, 6 ` - Audit`,
  and those ARE codes. So a title only yields a CANDIDATE suffix; it is
  settled against the KR's O (okr.settle_codes): the O's code = its 🏷️
  line, else its title code, else the MAJORITY candidate among its KRs
  (more than half; a tie names nothing). A KR candidate that differs from
  that AND is not all caps (2-6 letters/digits, a letter among them) folds
  back into the name: `Call Anna - Monday` keeps its whole name.
- Parse TOLERANTLY: VS16 on the emoji optional, `•`/`·`/`-` separators (the
  en dash, em dash and minus sign count as `-`), extra spaces, a code right
  after a link's closing paren with no space (`[x](url)- TA`), one level of
  brackets inside a link label, the app's backslash escapes in titles
  (pm.unescape_md).

## 3. Dates (read this before any date math)

- All-day ranges: TickTick stores the due of a MULTI-day all-day item as the
  NEXT day's midnight (exclusive end): `start 2026-12-21, due 2026-12-25` =
  21-24 Dec. A single-day item comes in BOTH forms in his live list: `start ==
  due` and `due == start + 1 day`. Both read as one day. So:
  `end_inclusive = due - 1 day if due > start else start`.
- Times arrive in two shapes: `2026-12-25T00:00:00+0100` (timeZone
  Europe/Berlin) and `2026-09-24T22:00:00+0000` (timeZone "") - the second is
  midnight Berlin written in UTC. Convert to the task's timeZone, else
  Europe/Berlin, THEN take the date.
- Evidence the exclusive reading is right: his chains hand over on the due
  date (Backups WF due 21 Dec, Files and folders WF starts 21 Dec; Onboard
  TickTicks due 29 Sep, TickAL starts 29 Sep).
- Writing: a SHIFT adds the same delta to both fields and keeps the item's
  own form - only for an item already ALL-DAY (raw isAllDay true). Setting
  a new length, an undated item, and a TIMED item even at the same length
  write the exclusive midnight all-day form (a shifted timed due would read
  as an exclusive end, a day short).
- Undated items exist (a fresh copy is undated until he drags it). They never
  count in pace, never ripple, never heal a parent.

## 4. Behaviours (decided)

- **Parent span**: an O runs from its first dated KR's start to its last
  dated KR's end; a Y the same over its O's. Healed after every TickAL write,
  on hub open, and on the hourly sync. A drag in TickTick does NOT ripple
  (nothing can see a drag happen) but its parent heals on the next pass.
  A DONE or WON'T-DO Y/O is history and is never healed.
- **Ripple** (decided 2026-09-18: SAME Y OBJECTIVE): a schedule action that
  moves an item's end by D days shifts, by the same D, every dated item in
  the same Y lane whose start is AFTER the moved item's inclusive end (one
  starting ON that day is parallel and stays). The moved item's descendants
  move with it, by its START delta. Ancestors are healed, not shifted.
  Items that overlap it (parallel) stay put. No Y ancestor → the lane is
  its top-level O. Negative D (pulling in) is symmetric for now - flag it
  to Vex when phase 2 ships. Decided in review 2026-09-18:
  - HEAL BEFORE PLANNING: the plan is made on a healed copy, every Y/O on
    its WANTED span, so the deltas and the successor threshold never read
    a stale stored span (live: TickAL stored 29 Sep - 14 Oct, wanted
    19 Sep - 14 Oct; putting it on 19 Sep - 14 Oct is a no-op, where the
    stale span read it as pulling every KR in ten days). The heals a plan
    returns are still judged against what is STORED, so a stale span
    elsewhere is healed too.
  - EXTEND ON A PARENT goes to its LAST KR: a Y/O with dated deliverables
    whose END alone changes (extend +N, or pulling its end in) hands the
    change to its last-ending open dated deliverable, recursively down to
    a KR (a Y through its O's); that KR takes the same D and ripples, and
    the Y/O heals to the new end. A START change (move to tomorrow, pick a
    date) shifts the whole subtree by the start delta, as before. Every
    deliverable done = refused (nothing open to extend).
  - DONE AND WON'T-DO ARE HISTORY: they never move - skipped by the
    successor shift and by the descendant shift alike.
- **Period overlap** (the plan for a note's period): a Y/O is tested on its
  WANTED span, the same fallback pace uses (live: Workflows stored 1-24 Dec
  while its Typinator WF runs 26-30 Nov - it IS in November's plan).
- **Schedule actions** on an OKR item: extend (+N days), move to tomorrow,
  pick a date. NO time entry ("we can remove add time").
- **Progress**: done KRs / all KRs of an O, children by PARENTID only (the
  tree's own link). A completed KR still counts in the total because the
  loader reads it (v2 project_completed) with its parentId. childIds are
  read only to report dangling ids (deleted or won't-do children): a KR
  moved to another O stays in the old O's childIds, and counting those put
  it under both. A Y aggregates the KRs of all its O's plus any KR hung
  straight under it.
- **Pace**: from the dates alone. Expected = dated KRs whose end is before
  today; actual = done KRs (an undated done KR counts too); "behind N d" =
  today minus the end of the earliest open KR that is already past its
  end; elapsed = day N of M, TODAY COUNTED AS ELAPSED ((today - start) + 1
  over the span's days, clamped to 0-1, 0 before the start - the first day
  reads 1/M, the last 100%), on the wanted span. ⚠ marks a KR inside its
  window whose linked real task has not moved in days (replaces the
  "gone quiet" idea, which Vex rightly killed for dated items).
- **Auto-tick** (decided: YES): an open KR whose link points at a SINGLE task
  that is completed gets ticked, on refresh and hourly sync. A KR linked to a
  list, a note, or nothing is ticked by hand. Only status 2 ticks: v1
  get_task answers a TRASHED task as status 0, and a failed GET is unknown,
  which never ticks.
- **Writers refuse on a partial read**: every phase-2 writer (heal,
  auto-tick, ripple) must refuse unless the snapshot is `source == "live"`
  and `done_complete` (okr.Snapshot.writable) - v2 completed answered, under
  its row limit. A cache read, or one missing completed KRs, reads a ticked
  KR as deleted.
- **Goal pickers** (every tier): first row(s) "🔮 <what the plan says for
  this period>" (⏎ sets it as the goal), then "📋 Pick a goal" (the picker as
  it is). TRAP: a daily goal set from a task MOVES that task onto the day
  (`set_period_goal` → `_goal_task_to_day`). A 🔮 row must target the LINKED
  ORIGINAL, never the copy, or the daily goal drags the KR copy into a time
  block and breaks the timeline. A text-only KR sets a text goal.
- **Periodic notes**: an OKR section in ALL FIVE tiers, "prominent ... this is
  the most important part of our productivity system". Forecast (the plan
  for that period) and the hand-picked goal on the SAME line, like the other
  comparisons. Layout is Vex's; propose a mock, he adjusts.
  Tier → plan level: 🎉 Year: Y's (+ their O's) · 🌓 Quarter: O's overlapping
  it · 🗓️ Month: O's + KRs in it · ♻️ Week: KRs overlapping it · ☀️ Day: KRs
  overlapping today.
- **Countdowns**: auto-maintained, one per active objective, to its end
  ("show ends of goals periods"). Written via api_v2.countdown_batch.
- **Routines + reviews**: an OKR step in every routine and every review.
- **Hub**: its own keyword + hotkey (caller chain → shared Call-ET BrowseCtx,
  the phase_logbooks shape). Main list includes a 📈 Pace row that opens
  Quarterly / Monthly / Weekly / Daily pace rows; ⌥ goes to the hub.
- **Import**: ONE ⌘ Actions drill row "🥅 Add to OKRs" on any task, note or
  list: as 🏔️ Y, as 🥅 O, or as 🔑 KR under a chosen O. Stamps naming and
  suffix, then a tag picker limited to OKR tags (0️⃣Area subtags + tags
  already used in the OKR list). KRs inherit their O's tag. KRs rapid-fire
  with the pipe, like subtasks. "Link…" on any OKR item links a task, note
  or list later.

Not wanted: KRs as numbers. The weekly confidence score (skipped, Vex may ask).

## 5. Where things live

| What | Where |
|---|---|
| OKR list | `config.get_okr_list_id()` - key `okr_list_id`, env wins; default 🏆Goals Planning `6aac1b808f089e43641f5e90` (timeline view) ONLY while the key is absent from config.json - a blank value (env or config.json) means OFF. Set from ⚙️ Settings → OKR List (xact:okr_setlist: a dialog, 24-hex id, blank = OFF, never flips the view mode - the list is a TIMELINE). |
| Old lists (leave alone) | 💫 OKRs 2026 `6a268ea18f081f1de80eaeae`, 💫 OKRs 2027 `6a268ea18f081f1de80eaeaf` - migrated later, not now |
| 📌CTA list | `6a3413e02522110c0d06e678` (project CTA tasks: `💼 P • [name](list link) 🔗`) |
| Area tag root | `0️⃣area` (tags_tree cache: name `0️⃣area`, children parent=`0️⃣area`) |
| Model | `src/okr.py` (pure + a loader), tests `tests/test_okr.py` |

## 6. Build order (each phase smoke-gated by Vex)

1. **Model** - `src/okr.py`: parse/build titles, dates, tree, spans + heal
   diff, progress, pace, period overlap, ripple plan, auto-tick candidates,
   code proposal; a live loader (v1 project data + v2 project_completed, cache
   fallback); `python3 src/okr.py` prints the live tree. READ-ONLY. Tests.
2. **Hub** - canvas phase (keyword + hotkey), rows, schedule actions with
   ripple, link, rapid-fire KRs, tag, done, span heal after writes.
3. **Import** - "🥅 Add to OKRs", text-only add, naming, code, tag picker.
4. **Periodic notes** - OKR section in five templates + filler + repair
   tool; 🔮 rows in every goal picker.
5. **Rest** - countdowns, routine/review steps, quarter-end carry-over
   screen, aligned-work ratio, focus per objective (read off the LINKED
   originals, low priority), capacity check (KRs per week, not focus).

Then the parked quarterly journal (HANDOFF_ROUTINES section 12) resumes on top.

## 7. Phase log

- 2026-09-18: spec written, decisions taken (prefix, ripple scope, money,
  auto-tick). Phase 1 started.
- 2026-09-18: phase 1 model reviewed; fixed in `src/okr.py`, `src/config.py`,
  `tests/test_okr.py` (still read-only, nothing writes):
  - ripple plans on a HEALED copy (the live TickAL stale span no longer
    reads as a ten-day pull-in); `overlapping()` tests Y/O on wanted spans
    (Workflows shows in November).
  - extend on a Y/O goes to its last open KR; a start change still shifts
    the whole subtree.
  - done / won't-do never move (successor and descendant shifts) and a done
    Y/O is never healed.
  - `write_fields` shifts only an all-day item; a timed one gets the
    exclusive all-day form.
  - loader honesty: `Snapshot.done_complete` + `writable`; "v2 completed
    unavailable" and a TRUNCATED warning in the detail; a malformed v1
    answer is OkrLoadError; an all_tasks fallback with no row of the list is
    an error unless the cached lists show it exists; the 3.9 hint only on an
    import-time ImportError/TypeError; no "newest 0 only" for an empty feed.
    The writer rule is in the module docstring.
  - `done_lookup`: a failed GET is None; the caches answer only when no
    client can be built, open cache first; trashed = status 0 never ticks.
    The dangling report line now reads "deleted or won't-do".
  - config: the default only when `okr_list_id` is absent; blank = OFF.
  - progress by parentId only (a moved KR no longer counts under both O's).
  - codes: all-caps words propose their capitals (YNAB → YNA, OKRs → OKR);
    suffixes settled in context (`settle_codes`, majority O code, non-caps
    stray suffix folds into the name).
  - parsing: nested-bracket link labels, `[x](url)- TA`, en dash / em dash
    / minus as separators.
  - pace elapsed counts today (day N of M).
  - tests for the mutations that survived review; a /tmp mutation run of 38
    targeted mutations kills all of them.
- 2026-09-18, second review round (fixed by hand, 497/497):
  - an extend handed down from a Y/O gives its last open deliverable the
    PARENT's requested end (not just +D), and the lane ripples from the
    PARENT's old end: a done last KR no longer leaves the O short with a
    hole before the next one, and an O running inside the parent's tail
    stays put.
  - a child Y/O dated by hand with no dated KR is a span leaf (it shapes
    its parent in wanted_spans, so an extend can land on it).
  - post-condition: if the parent still cannot land on the requested end
    (a pull-in with another open KR ending later, or a done one), the plan
    is REFUSED with the KR to move named - never a plan the heal undoes.
  - a schedule action on a done / won't-do item is refused (its stored
    span is never healed, so a delta off it is stale by design).
  - `schedule_plan(items, id, "extend"|"tomorrow"|"date", arg, today)` is
    the ONLY way phase 2 computes dates: it reads them off healed(items).
  - an O's code from a KR majority needs at least TWO KRs carrying a word
    that is not all caps (one "Call Anna - Monday" cannot vote itself in).
  - v1 answering {} (a list id that does not exist) says "list not found".
  Reviewers' probes rerun: 44,141 random plans, 0 parents missing their
  requested end (was ~4,300); property and pipeline probes clean.
- 2026-09-19: PHASE 2 SHIPPED (smoke-green from Vex). Code `5ccd77f`, canvas
  `f2cedd3` (phase_okr: main-menu leg `ctx:okr` → B31D6E02, caller chain
  keyword {var:okr_kw} + hotkey → Arg&Vars ctx:okr → BrowseCtx 60A44279,
  ⚙️ Settings "OKR List" 13- → xact:okr_setlist → End; 415/375/7-0-0).
  Vex bound the hotkey the same day: ⇧⌃⌥⌘R (`5c2730c`). What ships:
  - screens `ctx:okr` (root / `:y:<id>` / `:o:<id>`), `ctx:okrpace[:tier]`,
    `ctx:okrsched:<id>`, `ctx:okraddkr:<oid>`, `ctx:okrlink:<id>`,
    `ctx:okrtag:<id>` (Scripts/browse.py); ⌘ Actions OKR rows (Schedule…,
    Link…, Tag…, Add KRs, Done) with the generic verbs pruned (actions.py).
  - `src/okr_write.py` = the ONLY writer: flock `~/.ticktick_alfred/okr.lock`,
    live read, `Snapshot.writable` gate for dates and ticks, STORED items to
    write_fields, v2 full-object batches with a v1 fallback, `patch_cache`
    rebuilds okr_rows from the fresh snap and writes it LAST.
  - verbs `xact:okr_sched|okr_addkr|okr_link|okr_tag|okr_heal|okr_setlist`.
  - the hourly sync (`src/sync.py`, after `_people_nudge`) and a debounced
    detached heal on hub open run `heal_and_tick`: spans healed, KRs whose
    linked single task is done ticked (re-read inside the lock first).
  - rulings taken while building (review 2026-09-18/19): a leading +/- on
    the schedule screen is ALWAYS a length (+3, +3d, +2w; the minus sign,
    en and em dash count as "-"), a typed time is refused, a date before
    today is refused, an extend ending before today is refused; the tag
    pool = 0️⃣Area children + every tag on a Y or O, retag replaces the
    pool tags and keeps the rest, an O cascades to its open KRs; ⇧ reopens
    a done KR (uncomplete:) and a won't-do one (xact:wontdo_undo); a link
    target inside the plan list is refused.
  - A throwaway list "🧪 OKR scratch (delete me)" `6aad841a8f082f9dd43967c8`
    was used for live write tests (archived, empty); Vex removes it by hand.
- 2026-09-19: phase 3 (import) started - contract: `xact:okr_add` (Y / O /
  KR, text-only or linked, dedupe, CTA substitution for a list, tag picker
  after a Y/O), `okr_write.import_source`, `ctx:okrimport:<kind>:<pid>:<tid>`,
  ⌘ Actions "🥅 Add to OKRs", typed ➕ rows on the hub screens.
- 2026-09-19: PHASE 3 BUILT (import). `xact:okr_add` (Y / O / KR, linked or
  text-only, several via the pipe) over `okr_write.add_items`; the ⌘ Actions
  row "🥅 Add to OKRs" (or "🥅 In the OKRs · <name>") and the screen
  `ctx:okrimport:<task|note|list>:<pid>:<tid|->`; typed ➕ rows on the hub
  root (objective / year objective), a Y screen (objective) and an O screen
  (KR). Rulings taken while building:
  - ONE question, one answer: `okr_write.import_plan` is the only thing the
    ⌘ Actions row and the import screen ask, and `add_items` asks the same
    `planned()` / `plan_of` inside its lock - a screen never offers a ⏎ the
    verb can only refuse (a 140-state x 10-target agreement matrix, 682 real
    verb runs, 0 disagreements outside the transient cases below).
  - dedupe: the exact task / list for any item; a list and its 📌CTA task
    count as one only when the hit is a 🏔️ Y / 🥅 O. A LIST import links the
    project's 📌CTA task when one exists, so it asks with that link.
  - the last COMPLETE read is kept under `okr_complete` (never overwritten
    by an incomplete one); an incomplete live read adds its closed rows,
    and a hit on a row that vanished since (done or deleted - unknowable)
    refuses rather than risking a second copy. No v2 token = linked adds
    blocked on every surface (no read is ever complete without it).
  - names: a CTA "💼 P • " lead, a notes-list "N - " lead, a trailing 🔗,
    zero-width marks and a plain list's leading emoji are dropped; a name
    that would read back as a code ("Trip - USA") is a dead row, and so is a
    KR under an O whose 🏷️ code does not read back.
  - new O: code proposed (`okr_write` filters one that would not read back)
    or `=XY`, written as the O's 🏷️ line; "=XY" with several objectives is
    refused (two O's cannot share one code); a new Y / O opens the tag
    picker; a KR takes its O's tag; created undated in typed order (tied
    server sortOrders are re-dealt).
  - KNOWN EXCEPTION to "no ⏎ the verb refuses": a v1 rate limit between the
    cached read and the ⏎ (nothing local can see it) - the toast says wait.
