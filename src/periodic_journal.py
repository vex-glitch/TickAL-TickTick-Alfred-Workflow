"""periodic_journal.py - journal prompt-pool loading.

Pools are markdown files: repo defaults in src/periodic_prompts/, user
overrides in ~/.ticktick_alfred/periodic_prompts/ (a non-empty override
section wins per-key; malformed/empty falls back to the repo default, so a
broken user file can never blank the journal).

Selection itself is pure and lives in periodic_model.select_prompts.
"""
import os

import config as cfg

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "periodic_prompts")
USER_DIR = os.path.join(cfg.CONFIG_DIR, "periodic_prompts")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _parse(text):
    out = {"constants": [], "random": []}
    key = None
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.lower().startswith("## "):
            name = s[3:].strip().lower()
            key = name if name in out else None
        elif s.startswith("- ") and key:
            p = s[2:].strip()
            if p:
                out[key].append(p)
    return out


def load_pool(which):
    """which ∈ {'morning','evening'} → {'constants': [...], 'random': [...]}"""
    repo = _parse(_read(os.path.join(REPO_DIR, f"{which}.md")))
    user = _parse(_read(os.path.join(USER_DIR, f"{which}.md")))
    return {k: (user[k] or repo[k]) for k in ("constants", "random")}
