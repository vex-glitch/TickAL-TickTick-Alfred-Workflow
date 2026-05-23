#!/usr/bin/env python3
"""
delete_folder_action.py — Run Script
Removes a groupId → folder name mapping from config.
Reads folder_group_id from environment variable.
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

if not group_id:
    print("Error: missing folder_group_id")
    sys.exit(1)

folder_name = cfg.get_folders().get(group_id, "Folder")
cfg.delete_folder(group_id)
print(f"{folder_name} removed")
