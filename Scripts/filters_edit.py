#!/usr/bin/env python3
"""
filters_edit.py — Run Script
Opens filters_config.py in the default editor.
Creates it from filters_config.example.py if it doesn't exist yet.
"""
import os
import shutil
import subprocess

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR  = os.path.dirname(SCRIPT_DIR)
FILTERS_FILE  = os.path.join(WORKFLOW_DIR, "filters_config.py")
EXAMPLE_FILE  = os.path.join(WORKFLOW_DIR, "filters_config.example.py")

if not os.path.exists(FILTERS_FILE) and os.path.exists(EXAMPLE_FILE):
    shutil.copy(EXAMPLE_FILE, FILTERS_FILE)

subprocess.run(["open", FILTERS_FILE])
