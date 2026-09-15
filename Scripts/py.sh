#!/bin/bash
# Portable python3 resolver - every canvas node calls this instead of a
# hardcoded interpreter path. TickAL needs Python 3.10+ (`X | Y` types).
# Ladder, Apple Silicon Homebrew before Intel so a stale /usr/local python can
# never outrank it: bin/python3, then the python@3 opt link's libexec/bin/
# python3 (there while that link points at a NON-default python@3.x), the
# same pair under /usr/local, then the newest versioned python3.1x (always
# linked, default or not), then PATH - only when it is 3.10+, and never
# Apple's /usr/bin/python3 stub without Command Line Tools (it pops an install
# dialog, and even installed it is 3.9).
# 2026-09-15: a brew upgrade made python@3.13 non-default and dropped
# /opt/homebrew/bin/python3; the old ladder fell to /usr/bin/python3 (3.9) and
# every screen said "Import failed: unsupported operand type(s) for |".
# Keep xact._python_ladder in step.
# Invoked as: bash "Scripts/py.sh" "Scripts/x.py" "$1"  (cwd = workflow dir)
for P in /opt/homebrew/bin/python3 /opt/homebrew/opt/python@3/libexec/bin/python3 \
         /usr/local/bin/python3 /usr/local/opt/python@3/libexec/bin/python3; do
  [ -x "$P" ] && exec "$P" "$@"
done
shopt -s nullglob
for D in /opt/homebrew/bin /usr/local/bin; do
  C=("$D"/python3.1[0-9])
  for ((i=${#C[@]}-1; i>=0; i--)); do
    [ -x "${C[i]}" ] && exec "${C[i]}" "$@"
  done
done
P="$(command -v python3)"
if [ -n "$P" ] && { [ "$P" != /usr/bin/python3 ] || xcode-select -p >/dev/null 2>&1; } \
   && "$P" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  exec "$P" "$@"
fi
echo "TickAL: Python 3.10+ not found - install it with Homebrew: brew install python3" >&2
printf '{"items":[{"title":"TickAL needs Python 3.10+","subtitle":"Install it with Homebrew: brew install python3","valid":false}]}\n'
exit 127
