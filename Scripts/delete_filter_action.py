#!/usr/bin/env python3
"""
delete_filter_action.py — Run Script
Removes a filter from filters_config.py by index.
$1 format: delete:<index>
"""
import sys
import os
import re

try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
    sys.path.insert(0, WORKFLOW_DIR)
except Exception as e:
    print(f"Path error: {e}")
    sys.exit(1)

arg = sys.argv[1] if len(sys.argv) > 1 else ""

try:
    index = int(arg.replace("delete:", "").strip())
except ValueError:
    print(f"Error: invalid arg '{arg}'")
    sys.exit(1)

try:
    from filters_config import FILTERS
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

if index < 0 or index >= len(FILTERS):
    print(f"Error: index {index} out of range")
    sys.exit(1)

name = FILTERS[index].get("name", f"Filter {index+1}")
updated = [f for i, f in enumerate(FILTERS) if i != index]

# ── Rewrite filters_config.py ─────────────────────────────────────────────────
config_path = os.path.join(WORKFLOW_DIR, "filters_config.py")

with open(config_path) as f:
    content = f.read()

# Replace everything from FILTERS = [ to end of file
filters_repr = "FILTERS = [\n"
for f in updated:
    filters_repr += "    {\n"
    for k, v in f.items():
        filters_repr += f"        {repr(k)}: {repr(v)},\n"
    filters_repr += "    },\n"
filters_repr += "]\n"

# Find where FILTERS = [ starts and replace to end of file
new_content = re.sub(r'FILTERS\s*=\s*\[.*', filters_repr, content, flags=re.DOTALL)

with open(config_path, "w") as f:
    f.write(new_content)

print(f"{name} filter deleted")
