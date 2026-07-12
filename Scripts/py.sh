#!/bin/bash
# Portable python3 resolver — every canvas node calls this instead of a
# hardcoded interpreter path (Apple-Silicon Homebrew → Intel Homebrew → PATH,
# which on a bare Mac reaches the Xcode CLT stub and prompts the install).
# Invoked as: bash "Scripts/py.sh" "Scripts/x.py" "$1"  (cwd = workflow dir)
for P in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3)"; do
  [ -n "$P" ] && [ -x "$P" ] && exec "$P" "$@"
done
echo "TickAL: python3 not found — install Python 3 (https://brew.sh or xcode-select --install)" >&2
exit 127
