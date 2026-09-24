"""periodic_journal.py - journal prompt-pool loading.

Pools are markdown files: repo defaults in src/periodic_prompts/, user
overrides in ~/.ticktick_alfred/periodic_prompts/. A pool file is a set of
"## <category>" sections holding "- prompt" bullets; a "### chain: <name>"
block inside a section lists steps that are asked IN ORDER on a chain night
(numbered or bulleted lines). A non-empty user section wins per category;
malformed or empty falls back to the repo default, so a broken user file can
never blank the journal.

All five tier files carry the categories periodic_model draws from
(MORNING_CATEGORIES / EVENING_CATEGORIES / WEEKLY_CATEGORIES /
MONTHLY_CATEGORIES / QUARTERLY_CATEGORIES, Vex 2026-09-24); a user override
is per category, and a user file with only "## random" is not drawn from
(it only feeds the legacy draw for dates before a tier's epoch). quotes.md
is the quote pool: "## stoic" and "## others", one `- “text” · Author` per
line.

Selection itself is pure and lives in periodic_model.select_prompts.
"""
import os
import re

import config as cfg

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "periodic_prompts")
USER_DIR = os.path.join(cfg.CONFIG_DIR, "periodic_prompts")

_CHAIN_RE = re.compile(r"^###\s*chain:\s*(.+?)\s*$", re.I)
_STEP_RE = re.compile(r"^(?:\d+[.)]|-)\s+(.*)$")
_QUOTE_RE = re.compile(r"^-\s*[“\"](.+?)[”\"]\s*·\s*(.+?)\s*$")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _parse(text):
    """{'sections': {name: [prompts]}, 'chains': [{category, name, prompts}]}
    in file order. "# ..." lines are comments; any header that is not a
    "## section" or a "### chain:" ends the chain being read."""
    sections, chains = {}, []
    sec, chain = None, None
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        m = _CHAIN_RE.match(s)
        if m:
            chain = None
            if sec is not None:
                chain = {"category": sec, "name": m.group(1), "prompts": []}
                chains.append(chain)
            continue
        if s.startswith("## "):
            sec = s[3:].strip().lower()
            chain = None
            sections.setdefault(sec, [])
            continue
        if s == "#" or s.startswith("# "):
            continue                       # a comment: it ends nothing
        if s.startswith("#"):
            chain = None                   # any other header ends a chain
            continue
        m = _STEP_RE.match(s)
        if not m or sec is None:
            continue
        p = m.group(1).strip()
        if not p:
            continue
        if chain is not None:
            chain["prompts"].append(p)
        else:
            sections[sec].append(p)
    return {"sections": sections, "chains": [c for c in chains if c["prompts"]]}


def load_pool(which):
    """which ∈ {'morning','evening','weekly','monthly','quarterly'} →
    {'categories': {name: [...]}, 'chains': [...], 'random': [...],
     'constants': [...]}.

    categories keeps the repo file's section order (user-only sections
    follow); a non-empty user section replaces the repo's. A user file that
    names a chain in a category replaces the repo's chains of that category.
    random is every prompt of every section but constants, so the single-pool
    tiers and older callers keep working."""
    repo = _parse(_read(os.path.join(REPO_DIR, f"{which}.md")))
    user = _parse(_read(os.path.join(USER_DIR, f"{which}.md")))
    cats = {}
    names = list(repo["sections"]) + [n for n in user["sections"] if n not in repo["sections"]]
    for name in names:
        cats[name] = list(user["sections"].get(name) or repo["sections"].get(name) or [])
    user_cats = {c["category"] for c in user["chains"]}
    chains = [c for c in repo["chains"] if c["category"] not in user_cats] + list(user["chains"])
    rnd = [p for n, v in cats.items() if n != "constants" for p in v]
    return {"categories": cats, "chains": chains, "random": rnd,
            "constants": list(cats.get("constants", []))}


def _parse_quotes(text):
    out, sec = {}, None
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith("## "):
            sec = s[3:].strip().lower()
            out.setdefault(sec, [])
            continue
        m = _QUOTE_RE.match(s)
        if m and sec is not None:
            out[sec].append((m.group(1).strip(), m.group(2).strip()))
    return out


def load_quotes():
    """{'stoic': [(text, author)], 'others': [...]} from quotes.md; a
    non-empty user section wins."""
    merged = {}
    for d in (REPO_DIR, USER_DIR):
        for k, v in _parse_quotes(_read(os.path.join(d, "quotes.md"))).items():
            if v:
                merged[k] = v
    return {"stoic": list(merged.get("stoic", [])), "others": list(merged.get("others", []))}
