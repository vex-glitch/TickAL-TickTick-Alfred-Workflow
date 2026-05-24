#!/usr/bin/env python3
"""
tags_edit.py — Run Script
Opens tags_config.py in the default editor.
If the file doesn't exist, seeds it from the tags_var Configure panel value,
or falls back to tags_config.example.py.
"""
import os
import shutil
import subprocess

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
TAGS_FILE    = os.path.join(WORKFLOW_DIR, "tags_config.py")
EXAMPLE_FILE = os.path.join(WORKFLOW_DIR, "tags_config.example.py")

if not os.path.exists(TAGS_FILE):
    tags_var = os.environ.get("tags_var", "").strip()
    if tags_var:
        tags = [t.strip() for t in tags_var.splitlines() if t.strip()]
        with open(TAGS_FILE, "w") as f:
            f.write("# Edit your tags below, one per line.\n")
            f.write("# This list is merged with tags discovered from your tasks on sync.\n")
            f.write("TAGS = [\n")
            for tag in tags:
                escaped = tag.replace("'", "\\'")
                f.write(f"    '{escaped}',\n")
            f.write("]\n")
    elif os.path.exists(EXAMPLE_FILE):
        shutil.copy(EXAMPLE_FILE, TAGS_FILE)

subprocess.run(["open", TAGS_FILE])
