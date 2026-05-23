WORKFLOW_NAME := TickAL
BUNDLE       := $(WORKFLOW_NAME).alfredworkflow
PYTHON       := /usr/bin/python3

.PHONY: all bundle install test-api test-lists test-tasks clean

all: bundle

# ── Bundle ────────────────────────────────────────────────────────────────
bundle:
	@echo "Packaging $(BUNDLE)…"
	@zip -r $(BUNDLE) info.plist icon.png src/ Scripts/ \
		filters_config.example.py tags_config.example.py \
		--exclude "src/__pycache__/*" \
		--exclude "src/**/__pycache__/*" \
		--exclude "Scripts/__pycache__/*" \
		--exclude "*.pyc" \
		--exclude ".DS_Store"
	@echo "Done → $(BUNDLE)"

# ── Install into Alfred (double-click import) ─────────────────────────────
install: bundle
	open $(BUNDLE)

# ── Smoke tests ───────────────────────────────────────────────────────────
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
	@cd "$(dir $(abspath $(firstword $(MAKEFILE_LIST))))" && \
		$(PYTHON) src/main.py "" | python3 -m json.tool

test-tasks:
	@echo "--- main.py (task search: /) ---"
	@cd "$(dir $(abspath $(firstword $(MAKEFILE_LIST))))" && \
		$(PYTHON) src/main.py "/" | python3 -m json.tool

test-add:
	@echo "--- main.py (add task preview) ---"
	@cd "$(dir $(abspath $(firstword $(MAKEFILE_LIST))))" && \
		$(PYTHON) src/main.py "+Buy milk *tomorrow !2 #shopping" | python3 -m json.tool

test-sync:
	@echo "--- sync.py (do_sync) ---"
	@cd "$(dir $(abspath $(firstword $(MAKEFILE_LIST))))" && \
		$(PYTHON) src/sync.py sync

clean:
	rm -f $(BUNDLE)
	find src -name "*.pyc" -delete
	find src -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
