WORKFLOW_NAME := TickAL
BUNDLE       := $(WORKFLOW_NAME).alfredworkflow
# System python (3.9) can't import the vendored urllib3 (needs 3.10+) - use
# Homebrew's, by the same ladder as Scripts/py.sh (a brew upgrade can drop
# bin/python3 while the python@3 alias stays, 2026-09-15).
PYTHON       := $(firstword $(wildcard /opt/homebrew/bin/python3 /opt/homebrew/opt/python@3/libexec/bin/python3 /usr/local/bin/python3 /usr/local/opt/python@3/libexec/bin/python3) $(lastword $(sort $(wildcard /opt/homebrew/bin/python3.1[0-9]))) $(lastword $(sort $(wildcard /usr/local/bin/python3.1[0-9]))) python3)

.PHONY: all bundle install test test-api test-lists test-tasks test-add test-sync clean

all: bundle

# ── Bundle ────────────────────────────────────────────────────────────────
bundle:
	@echo "Packaging $(BUNDLE)…"
	@zip -r $(BUNDLE) info.plist icon.png src/ Scripts/ \
		--exclude "src/__pycache__/*" \
		--exclude "src/**/__pycache__/*" \
		--exclude "Scripts/__pycache__/*" \
		--exclude "*.pyc" \
		--exclude ".DS_Store"
	@echo "Done → $(BUNDLE)"

# ── Install into Alfred (double-click import) ─────────────────────────────
install: bundle
	open $(BUNDLE)

# ── Unit tests (pure stdlib, no credentials or network needed) ────────────
# Tests never start background follow-ups against the real account (the
# daily note catch-up, the repeat settle). The suites that run a completion
# road set it themselves too, for standalone runs.
test: export TICKAL_NO_SETTLE := 1
test:
	@$(PYTHON) tests/test_periodic.py
	@$(PYTHON) tests/test_focus_blocks.py
	@$(PYTHON) tests/test_habits_model.py
	@$(PYTHON) tests/test_on_this_day.py
	@$(PYTHON) tests/test_recap_order.py
	@$(PYTHON) tests/test_money.py
	@$(PYTHON) tests/test_weekly_note.py
	@$(PYTHON) tests/test_monthly_note.py
	@$(PYTHON) tests/test_quarterly_note.py
	@$(PYTHON) tests/test_task_window.py
	@$(PYTHON) tests/test_okr.py
	@$(PYTHON) tests/test_okr_screens.py
	@$(PYTHON) tests/test_okr_write.py
	@$(PYTHON) tests/test_okr_pickers.py
	@$(PYTHON) tests/test_okr_notes.py
	@$(PYTHON) tests/test_okr_stats.py
	@$(PYTHON) tests/test_people.py
	@$(PYTHON) tests/test_eagle.py
	@$(PYTHON) tests/test_routine_link.py
	@$(PYTHON) tests/test_routine_runner.py
	@$(PYTHON) tests/test_subtask_line.py
	@$(PYTHON) tests/test_mdtext.py
	@$(PYTHON) tests/test_clipboard.py
	@$(PYTHON) tests/test_browser_tab.py
	@$(PYTHON) tests/test_ask_box.py
	@$(PYTHON) tests/test_api_update.py
	@$(PYTHON) tests/test_albums.py
	@$(PYTHON) tests/test_alb_move.py
	@$(PYTHON) tests/test_alb_merge.py
	@$(PYTHON) tests/test_alb_adopt.py
	@$(PYTHON) tests/test_repeat_settle.py
	@$(PYTHON) tests/test_fold_comments.py
	@$(PYTHON) tests/test_journal_goal.py
	@$(PYTHON) tests/test_journal_pools.py
	@$(PYTHON) tests/test_pn_sync.py
	@$(PYTHON) tests/test_day_shift.py
	@$(PYTHON) tests/test_no_stale_revert.py
	@$(PYTHON) tests/test_meal.py
	@$(PYTHON) tests/test_meal_scale.py
	@$(PYTHON) tests/test_meal_price.py
	@$(PYTHON) tests/test_mela.py
	@$(PYTHON) tests/test_meal_write.py
	@$(PYTHON) tests/test_meal_screens.py
	@$(PYTHON) tests/test_mela_cal.py
	@$(PYTHON) tests/test_row_display.py

# ── Smoke tests (need a logged-in setup) ──────────────────────────────────
test-api:
	@echo "--- GET /project ---"
	@cd src && $(PYTHON) -c "\
import sys; sys.path.insert(0,'lib'); \
from config import get_token; from api import TickTickAPI; \
import json; api = TickTickAPI(get_token()); \
ps = api.get_projects(); \
print(f'Projects: {len(ps)}'); \
[print(f'  {p[\"id\"]}  {p[\"name\"]}  kind={p.get(\"kind\",\"\")}') for p in ps[:5]]"

test-lists:
	@echo "--- main.py (list browser, no query) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/main.py "" | $(PYTHON) -m json.tool

test-tasks:
	@echo "--- main.py (task search: /) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/main.py "/" | $(PYTHON) -m json.tool

test-add:
	@echo "--- main.py (add task preview) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/main.py "+Buy milk *tomorrow !2 #shopping" | $(PYTHON) -m json.tool

test-sync:
	@echo "--- sync.py (do_sync) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/sync.py sync

clean:
	rm -f $(BUNDLE)
	find src -name "*.pyc" -delete
	find src -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true

# ── Workflow ⇄ repo sync (iron rule: info.plist live→repo ONLY) ───────────
# The live workflow path is personal - define it in untracked local.mk:
#   LIVE := $(HOME)/path/to/Alfred.alfredpreferences/workflows/user.workflow.<your-id>
-include local.mk
LIVE ?= $(error LIVE undefined - create local.mk with your live workflow path)

.PHONY: sync-pull sync-push
# Pull the live canvas into the repo (the ONLY allowed plist direction)
sync-pull:
	@cp "$(LIVE)/info.plist" info.plist
	@git status --short info.plist

# Push ONE .py file (a baked Scripts/assets/*.png, or a periodic-note
# template) repo→live:
#   make sync-push FILE=Scripts/foo.py
# Templates and journal PROMPT POOLS are shipped code, not docs: create_note
# renders the LIVE copy at mint time and periodic_journal reads the LIVE pool
# when a journal seeds, so either one fixed only in the repo never reaches a
# note (the template case bit us 2026-09-12 - the live weekly.md was months
# behind - and the monthly pool would have seeded ZERO drawn questions).
sync-push:
	@test -n "$(FILE)" || (echo "usage: make sync-push FILE=Scripts/foo.py" && exit 1)
	@case "$(FILE)" in *.py|Scripts/*.sh|Scripts/assets/*.png|src/periodic_templates/*.md|src/periodic_prompts/*.md) ;; *) echo "REFUSED: only .py files, Scripts/*.sh, Scripts/assets/*.png, src/periodic_templates/*.md and src/periodic_prompts/*.md sync repo→live"; exit 1;; esac
	@mkdir -p "$(LIVE)/$(dir $(FILE))"
	@cp "$(FILE)" "$(LIVE)/$(FILE)"
	@echo "synced $(FILE) → live"
