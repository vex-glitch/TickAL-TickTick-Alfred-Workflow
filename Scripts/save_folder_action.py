#!/usr/bin/env python3
"""
save_folder_action.py — Run Script
Saves a groupId → folder name mapping to config.
Reads folder_group_id and folder_name from environment variables.
"""
import sys
import os

try:
    SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
    WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
    SRC_DIR      = os.path.join(WORKFLOW_DIR, "src")
    sys.path.insert(0, os.path.join(SRC_DIR, "lib"))
    sys.path.insert(0, SRC_DIR)
except Exception as e:
    print(f"Path error: {e}")
    sys.exit(1)

try:
    import config as cfg
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

group_id = os.environ.get("folder_group_id", "").strip()
name     = (sys.argv[1] if len(sys.argv) > 1 else "").strip()

if not group_id or not name:
    print("Error: missing folder_group_id or folder_name")
    sys.exit(1)

cfg.set_folder(group_id, name)
print(f"{name} saved")
