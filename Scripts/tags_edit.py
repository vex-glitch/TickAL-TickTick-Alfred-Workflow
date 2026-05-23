#!/usr/bin/env python3
"""
tags_edit.py — Run Script
Opens tags_config.py in the default editor.
Creates it from tags_config.example.py if it doesn't exist yet.
"""
import os
import shutil
import subprocess

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.dirname(SCRIPT_DIR)
TAGS_FILE    = os.path.join(WORKFLOW_DIR, "tags_config.py")
EXAMPLE_FILE = os.path.join(WORKFLOW_DIR, "tags_config.example.py")

if not os.path.exists(TAGS_FILE) and os.path.exists(EXAMPLE_FILE):
    shutil.copy(EXAMPLE_FILE, TAGS_FILE)

subprocess.run(["open", TAGS_FILE])
