#!/usr/bin/env python3
"""Unit suite for api.update_task's list-id rules + display.buffer_pairs'
pid repair (Vex bugs 2026-09-10: staging, ⌘ Move to a subtask and 👽 attach
broke when the 09-09 current-wins rule met a PRE-move `current`). A fake
session plays TickTick: a write under the wrong list answers an EMPTY body
and changes nothing (probe-verified). No network, no real files.
Run: python3 tests/test_api_update.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
from script_base import bootstrap  # noqa: E402
bootstrap()
import api      # noqa: E402
import cache    # noqa: E402
import display  # noqa: E402

FAILS = []
COUNT = [0]


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


class Reply:
    def __init__(self, text):
        self.text, self.status_code = text, 200

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass


class Server:
    """Accepts a task write only under the list the task really lives in."""
    def __init__(self, real_pid):
        self.real, self.posted = real_pid, []

    def post(self, url, json=None):
        self.posted.append(json["projectId"])
        ok = json["projectId"] == self.real
        return Reply('{"id": "%s", "projectId": "%s"}' % (json["id"], json["projectId"]) if ok else "")


def client(real_pid):
    c = api.TickTickAPI.__new__(api.TickTickAPI)   # no token, no network
    c.session = Server(real_pid)
    return c


OLD, NEW, T = "o" * 24, "n" * 24, "t" * 24

# the bug: move-then-update with a PRE-move current (its list = OLD)
c = client(NEW)
r = c.update_task(T, NEW, current={"id": T, "projectId": OLD, "title": "x"}, parentId="p" * 24)
check("pre-move current: retries the positional list", c.session.posted == [OLD, NEW], c.session.posted)
check("pre-move current: write lands", r.get("projectId") == NEW)

# the 09-09 case must keep working: stale positional, live current knows best
c = client(NEW)
c.update_task(T, OLD, current={"id": T, "projectId": NEW}, tags=["a"])
check("records case: current wins, one post", c.session.posted == [NEW], c.session.posted)

# explicit projectId (the contract for moves): no guessing, loud on empty
c = client(NEW)
c.update_task(T, NEW, current={"id": T, "projectId": OLD}, projectId=NEW)
check("explicit projectId: one post under it", c.session.posted == [NEW], c.session.posted)
c = client(NEW)
try:
    c.update_task(T, NEW, current={"id": T, "projectId": NEW}, projectId=OLD)
    check("explicit wrong projectId raises (no retry)", False)
except RuntimeError:
    check("explicit wrong projectId raises (no retry)", c.session.posted == [OLD], c.session.posted)

# neither candidate is right: two posts, then the loud error
c = client("z" * 24)
try:
    c.update_task(T, NEW, current={"id": T, "projectId": OLD})
    check("both wrong raises", False)
except RuntimeError as e:
    check("both wrong raises after 2 posts", c.session.posted == [OLD, NEW] and "empty reply" in str(e))

# current without a list: positional only, no bogus retry
c = client("z" * 24)
try:
    c.update_task(T, NEW, current={"id": T})
    check("no current list: raises after 1 post", False)
except RuntimeError:
    check("no current list: raises after 1 post", c.session.posted == [NEW], c.session.posted)

# ── display.buffer_pairs: stale pid follows the task, dead lines drop ────────
tmp = tempfile.mkdtemp()
buf = os.path.join(tmp, "tickal_buffer.txt")
with open(buf, "w") as f:
    f.write(f"{OLD}:{'a' * 24}\n{NEW}:{'b' * 24}\n{OLD}:{'d' * 24}\n")
real_run_path, real_get = display.run_path, cache.get
display.run_path = lambda name: os.path.join(tmp, name)
pools = {"all_tasks": [{"id": "a" * 24, "projectId": NEW, "status": 0},        # moved
                       {"id": "b" * 24, "projectId": NEW, "status": 0},        # unchanged
                       {"id": "d" * 24, "projectId": OLD, "status": 2}],       # completed
         "all_notes": []}
cache.get = lambda key: pools.get(key)
try:
    got = display.buffer_pairs()
    check("stale pid healed, dead dropped", got == [[NEW, "a" * 24], [NEW, "b" * 24]], got)
    check("file rewritten", open(buf).read() == f"{NEW}:{'a' * 24}\n{NEW}:{'b' * 24}\n")
    pools["all_tasks"][0]["projectId"] = None
    pools["all_tasks"][0]["_projectId"] = "inbox"
    with open(buf, "w") as f:
        f.write(f"{OLD}:{'a' * 24}\n")
    check("alias fallback when projectId missing", display.buffer_pairs() == [["inbox", "a" * 24]])
    A = "a" * 24
    cache.get = lambda key: {"all_tasks": [{"id": A, "projectId": NEW, "status": 0}],
                             "all_notes": []}.get(key)
    with open(buf, "w") as f:
        f.write(f"{OLD}:{A}\n{NEW}:{A}\n")
    check("two lines of one task → one pair", display.buffer_pairs() == [[NEW, A]])
    cache.get = lambda key: {"all_tasks": [{"id": A, "projectId": "inbox131772140",
                                            "_projectId": "inbox", "status": 0}],
                             "all_notes": []}.get(key)
    with open(buf, "w") as f:
        f.write(f"inbox:{A}\n")
    check("inbox alias line left alone (no churn)",
          display.buffer_pairs() == [["inbox", A]] and open(buf).read() == f"inbox:{A}\n")
    cache.get = lambda key: {"all_tasks": [{"id": A, "projectId": NEW, "status": 0}],
                             "all_notes": [{"id": A, "projectId": OLD, "status": 0}]}.get(key)
    with open(buf, "w") as f:
        f.write(f"{OLD}:{A}\n")
    check("all_tasks twin wins over all_notes", display.buffer_pairs() == [[NEW, A]])
    notes_only = {"all_tasks": None,
                  "all_notes": [{"id": "n" * 24, "projectId": NEW, "status": 0}]}
    cache.get = lambda key: notes_only.get(key)
    with open(buf, "w") as f:
        f.write(f"{OLD}:{'a' * 24}\n")
    check("task pool missing → no judgement (notes can't judge tasks)",
          display.buffer_pairs() == [[OLD, "a" * 24]])
    check("task pool missing → file untouched", open(buf).read() == f"{OLD}:{'a' * 24}\n")
    cache.get = lambda key: None
    with open(buf, "w") as f:
        f.write(f"{OLD}:{'a' * 24}\n")
    check("no cache → no judgement", display.buffer_pairs() == [[OLD, "a" * 24]])
finally:
    display.run_path, cache.get = real_run_path, real_get

# ── link_label: a title that IS a markdown link (every routine step) ────────
check("a link title contributes only its label",
      display.link_label("[Shutdown • Start](alfred://runtrigger/x)") == "Shutdown • Start")
check("a plain title is used whole",
      display.link_label("🌆 Shutdown") == "🌆 Shutdown")
check("a plain title keeps a bare URL (search_key would strip it)",
      display.link_label("Read https://example.com later")
      == "Read https://example.com later")
check("empty and None survive",
      display.link_label("") == "" and display.link_label(None) == "")
check("a label never carries brackets that would nest in [[ ]]",
      "](" not in display.link_label("[A](u)"))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if __name__ == "__main__":            # make test / python3 tests/...: exit code
    sys.exit(1 if FAILS else 0)
if FAILS:                             # imported by unittest discover: still red on failure
    raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
