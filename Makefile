WORKFLOW_NAME := TickAL
BUNDLE       := $(WORKFLOW_NAME).alfredworkflow
# System python (3.9) can't import the vendored urllib3 (needs 3.10+) — use the
# same homebrew python the cache-sync LaunchAgent runs on.
PYTHON       := /opt/homebrew/bin/python3

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
test:
	@python3 tests/test_periodic.py
	@python3 tests/test_focus_blocks.py

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
		$(PYTHON) src/main.py "" | python3 -m json.tool

test-tasks:
	@echo "--- main.py (task search: /) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/main.py "/" | python3 -m json.tool

test-add:
	@echo "--- main.py (add task preview) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/main.py "+Buy milk *tomorrow !2 #shopping" | python3 -m json.tool

test-sync:
	@echo "--- sync.py (do_sync) ---"
	@cd "$(CURDIR)" && \
		$(PYTHON) src/sync.py sync

clean:
	rm -f $(BUNDLE)
	find src -name "*.pyc" -delete
	find src -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true

# ── Workflow ⇄ repo sync (iron rule: info.plist live→repo ONLY) ───────────
# The live workflow path is personal — define it in untracked local.mk:
#   LIVE := $(HOME)/path/to/Alfred.alfredpreferences/workflows/user.workflow.<your-id>
-include local.mk
LIVE ?= $(error LIVE undefined — create local.mk with your live workflow path)

.PHONY: sync-pull sync-push
# Pull the live canvas into the repo (the ONLY allowed plist direction)
sync-pull:
	@cp "$(LIVE)/info.plist" info.plist
	@git status --short info.plist

# Push ONE .py file repo→live:  make sync-push FILE=Scripts/foo.py
sync-push:
	@test -n "$(FILE)" || (echo "usage: make sync-push FILE=Scripts/foo.py" && exit 1)
	@case "$(FILE)" in *.py) ;; *) echo "REFUSED: only .py files sync repo→live"; exit 1;; esac
	@cp "$(FILE)" "$(LIVE)/$(FILE)"
	@echo "synced $(FILE) → live"
