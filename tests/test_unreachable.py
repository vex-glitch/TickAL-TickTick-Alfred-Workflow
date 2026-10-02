#!/usr/bin/env python3
"""Unit suite for the dead-line rules (Vex 2026-09-28: one VPN relay could not
reach TickTick's servers for 27 minutes while the rest of the net worked. An
add and a manual sync hung ten minutes each and said nothing, the startup
sync put a stack of class names in a banner).

Contract under test:
  * every v1 request carries api.TIMEOUT unless the caller names one, and
    every v1 request goes through the session that adds it;
  * a SILENT server (connect timeout) is asked once; a refused connection
    and a name that does not resolve keep their three retries;
  * a transport failure surfaces as api.Unreachable (never connected:
    nothing changed) or api.NoAnswer (sent, no reply: look before trying
    again). Both are still caught by handlers written for requests' own
    classes, and str() is a sentence;
  * dispatch and sync print that sentence as the toast;
  * a line that dies mid-sync stops the sync BEFORE all_tasks is written;
  * script_base.wait_for_network wants an answer on the port, not a name.

Nothing reaches the network: urllib3's connect is replaced, the real sockets
are on 127.0.0.1, and a guard fails the suite if anything else is dialled.
Run: python3 tests/test_unreachable.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import ast
    import base64
    import contextlib
    import io
    import json
    import os
    import socket
    import sys
    import tempfile
    import threading
    import time
    from types import SimpleNamespace

    SCRATCH = tempfile.mkdtemp(prefix="tickal_unreach_")
    os.environ["HOME"] = SCRATCH               # before ANY repo import
    os.environ["TICKAL_NO_SETTLE"] = "1"
    os.environ["token"] = "fake-token"         # cfg.get_token() reads it; no Keychain
    os.environ["alfred_version"] = "5"         # not headless: no banner, no probe

    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(REPO, "src", "lib"))
    sys.path.insert(0, os.path.join(REPO, "src"))
    import requests                                       # noqa: E402
    import urllib3.util.connection as u3conn              # noqa: E402
    from urllib3.exceptions import (                      # noqa: E402
        ConnectTimeoutError, MaxRetryError, NameResolutionError, NewConnectionError)
    import api          # noqa: E402
    import script_base  # noqa: E402

    FAILS, COUNT = [], [0]


    def check(name, cond, detail=""):
        COUNT[0] += 1
        print(f"  ok  {name}" if cond else f"FAIL  {name}  {detail}")
        if not cond:
            FAILS.append(name)


    SILENT = "TickTick unreachable (server silent) · nothing changed"
    NO_ROUTE = "TickTick unreachable (no route) · nothing changed"
    NO_DNS = "TickTick unreachable (no DNS, offline?) · nothing changed"
    QUIET = "TickTick gave no answer · check before retrying"

    # ── the guard: from here on, only 127.0.0.1 may be dialled ──────────────
    REAL_U3_CONNECT = u3conn.create_connection
    REAL_SOCK_CONNECT = socket.create_connection
    REAL_SLEEP = time.sleep
    DIALLED = []


    def _local_only(real):
        def dial(address, *a, **kw):
            if address[0] not in ("127.0.0.1", "localhost"):
                DIALLED.append(address)
                raise AssertionError(f"the suite dialled {address}")
            return real(address, *a, **kw)
        return dial


    u3conn.create_connection = _local_only(REAL_U3_CONNECT)
    socket.create_connection = _local_only(REAL_SOCK_CONNECT)

    # ── 1. every request is bounded ─────────────────────────────────────────
    from requests.adapters import HTTPAdapter             # noqa: E402

    seen = []
    real_send = HTTPAdapter.send


    def recorder(self, request, **kw):
        """Stands where the wire is: what the client's adapter hands down."""
        seen.append((request.method, request.url, kw.get("timeout")))
        r = requests.Response()
        r.status_code, r.url, r.request = 200, request.url, request
        r._content = b'{"id": "t", "projectId": "p", "tasks": []}'
        return r


    HTTPAdapter.send = recorder
    try:
        c = api.TickTickAPI("tok")
        check("the client's session is a plain requests.Session (the suites' seam)",
              type(c.session) is requests.Session)
        check("https and http both leave through the bounded adapter",
              all(isinstance(c.session.get_adapter(u), api._Adapter)
                  for u in ("https://api.ticktick.com/open/v1", "http://127.0.0.1:1/x")))
        roads = {
            "create_project": lambda: c.create_project("n"),
            "create_focus": lambda: c.create_focus("s", "e"),
            "update_project": lambda: c.update_project("p", name="n"),
            "delete_project": lambda: c.delete_project("p"),
            "get_projects": lambda: c.get_projects(),
            "get_project_data": lambda: c.get_project_data("p"),
            "get_task": lambda: c.get_task("p", "t"),
            "live_tasks": lambda: c.live_tasks([("p", "t")]),
            "create_task": lambda: c.create_task("t"),
            "complete_task": lambda: c.complete_task("p", "t"),
            "update_task (own read)": lambda: c.update_task(
                "t", "p", current={"id": "t", "projectId": "p"}, fresh=True, title="x"),
            "update_task (live read first)": lambda: c.update_task("t", "p", title="x"),
            "move_task": lambda: c.move_task("t", "a", "b"),
            "delete_task": lambda: c.delete_task("p", "t"),
        }
        for name, road in roads.items():
            del seen[:]
            road()
            check(f"{name}: bounded",
                  bool(seen) and all(t == api.TIMEOUT for _, _, t in seen), seen)
        del seen[:]
        c.session.get("https://api.ticktick.com/x", timeout=1)
        check("a caller's own timeout wins", seen[0][2] == 1, seen)
    finally:
        HTTPAdapter.send = real_send

    connect, read = api.TIMEOUT
    check("TIMEOUT is (connect, read), both short enough to wait for",
          0 < connect <= 5 and 0 < read <= 60, api.TIMEOUT)

    # no road around the session: api.py never calls requests.<verb> itself
    tree = ast.parse(open(os.path.join(REPO, "src", "api.py")).read())
    VERBS = {"get", "post", "put", "patch", "delete", "request"}
    direct, via_session = [], 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in VERBS:
            base = node.func.value
            if isinstance(base, ast.Name) and base.id == "requests":
                direct.append(node.lineno)
            elif isinstance(base, ast.Attribute) and base.attr == "session":
                via_session += 1
    check("api.py: no requests.<verb>() around the session", not direct, direct)
    check("api.py: its calls are the session's", via_session >= 13, via_session)

    # the v2 client and the periodic fetchers name a (connect, read) pair
    for rel in ("src/api_v2.py", "src/periodic_fetch.py", "Scripts/auth.py"):
        bare = []
        for node in ast.walk(ast.parse(open(os.path.join(REPO, rel)).read())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in VERBS \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "requests":
                kws = {k.arg: k.value for k in node.keywords}
                if any(k.arg is None for k in node.keywords):
                    continue                       # **kw: checked where it is built
                t = kws.get("timeout")
                if t is None or (isinstance(t, ast.Constant)
                                 and isinstance(t.value, (int, float))
                                 and t.value > 5):
                    bare.append(node.lineno)
        check(f"{rel}: no call waits a bare long timeout per address", not bare, bare)
    import api_v2       # noqa: E402
    check("api_v2._t pairs the connect cap with the read wait",
          api_v2._t(15) == (api_v2.CONNECT, 15) and api_v2.CONNECT <= 5)

    # ── 2. the retry rule ───────────────────────────────────────────────────
    r = api._RETRY
    try:
        r.increment(method="GET", url="/x", error=ConnectTimeoutError(None, "silent"))
        check("silent: not asked again", False, "increment returned")
    except MaxRetryError as e:
        check("silent: not asked again", type(e.reason) is ConnectTimeoutError)
    n = r.increment(method="GET", url="/x", error=NewConnectionError(None, "refused"))
    check("refused: a retry is left", n.total == r.total - 1, n)
    check("the rule survives the copy urllib3 makes", isinstance(n, api._Retry))
    n = r.increment(method="POST", url="/x",
                    error=NameResolutionError("h", None, socket.gaierror(8, "no name")))
    check("no DNS: a retry is left, for a POST too", n.total == r.total - 1, n)

    # ── 3. the whole road, urllib3's connect replaced ───────────────────────
    attempts, naps = [], []
    time.sleep = lambda s: naps.append(s)          # the backoff, not slept


    def silent(address, timeout=None, **kw):
        attempts.append((address, timeout))
        raise socket.timeout("timed out")


    def refused(address, timeout=None, **kw):
        attempts.append((address, timeout))
        raise ConnectionRefusedError(61, "Connection refused")


    def no_dns(address, timeout=None, **kw):
        attempts.append((address, timeout))
        raise socket.gaierror(8, "nodename nor servname provided, or not known")


    def dead(how, road):
        """(exception, connects made) for one road over one kind of dead line."""
        del attempts[:]
        u3conn.create_connection = how
        try:
            road(api.TickTickAPI("tok"))
        except Exception as e:
            return e, len(attempts)
        finally:
            u3conn.create_connection = _local_only(REAL_U3_CONNECT)
        return None, len(attempts)


    e, tries = dead(silent, lambda c: c.get_projects())
    check("silent GET: Unreachable", isinstance(e, api.Unreachable), repr(e))
    check("silent GET: ONE connect, no retry", tries == 1, tries)
    check("silent GET: the connect wait is TIMEOUT's",
          attempts and attempts[0][1] == api.TIMEOUT[0], attempts)
    check("silent GET: the sentence", str(e) == SILENT, str(e))
    check("silent GET: no class names in the toast",
          "HTTPSConnectionPool" not in str(e) and "Max retries" not in str(e))
    check("Unreachable is still a requests ConnectionError and a Timeout",
          isinstance(e, requests.ConnectionError) and isinstance(e, requests.Timeout))

    e, tries = dead(silent, lambda c: c.create_task("consultation", project_id="p" * 24))
    check("silent add: Unreachable after ONE connect",
          isinstance(e, api.Unreachable) and tries == 1, (repr(e), tries))

    e, tries = dead(silent, lambda c: c.update_task("t", "p", title="x"))
    check("silent update: the live read raises, nothing is posted",
          isinstance(e, api.Unreachable) and tries == 1, (repr(e), tries))

    e, tries = dead(silent, lambda c: c.live_tasks([("p", "t"), ("q", "u")]))
    check("silent bulk read: raises at the first list",
          isinstance(e, api.Unreachable) and tries == 1, (repr(e), tries))

    e, tries = dead(refused, lambda c: c.get_projects())
    check("refused GET: three retries kept", tries == 4, tries)
    check("refused GET: the sentence", isinstance(e, api.Unreachable) and str(e) == NO_ROUTE, repr(e))

    e, tries = dead(no_dns, lambda c: c.create_task("t"))
    check("no DNS add: three retries kept (the request never left)", tries == 4, tries)
    check("no DNS add: the sentence", isinstance(e, api.Unreachable) and str(e) == NO_DNS, repr(e))
    check("the backoff between retries is short", sum(naps) <= 8, naps)

    # ── 4. dispatch: the add that hung ──────────────────────────────────────
    import dispatch     # noqa: E402


    def said(fn, argv):
        buf, old = io.StringIO(), sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(buf):
                fn()
        finally:
            sys.argv = old
        return buf.getvalue().strip()


    add = "create:" + base64.b64encode(json.dumps({
        "title": "consultation", "listName": "➕SAL", "projectId": "p" * 24,
        "startDate": "2026-09-29T09:30:00+0000", "dueDate": "2026-09-29T12:30:00+0000",
        "tags": []}).encode()).decode()

    del attempts[:]
    u3conn.create_connection = silent
    t0 = time.monotonic()
    try:
        out = said(dispatch.main, ["dispatch.py", add])
    finally:
        u3conn.create_connection = _local_only(REAL_U3_CONNECT)
    check("add over a silent line: the toast", out == "⚠️ " + SILENT, out)
    check("add over a silent line: one connect", len(attempts) == 1, attempts)

    real_api = dispatch.TickTickAPI
    dispatch.TickTickAPI = lambda token: SimpleNamespace(
        create_task=lambda **kw: (_ for _ in ()).throw(api.NoAnswer(QUIET)))
    try:
        out = said(dispatch.main, ["dispatch.py", add])
    finally:
        dispatch.TickTickAPI = real_api
    check("add sent, no reply: the toast says look first", out == "⚠️ " + QUIET, out)

    # ── 5. sync ─────────────────────────────────────────────────────────────
    import sync         # noqa: E402

    LISTS = [{"id": x * 24, "name": x.upper()} for x in "abc"]


    class Store(dict):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.sets = []

        def set(self, key, value):
            self.sets.append(key)
            self[key] = value

        def invalidate(self, key):
            self.pop(key, None)


    class Lists:
        """get_project_data dies (with `err`) from its `die`-th list on."""
        def __init__(self, die, err):
            self.die, self.err, self.read = die, err, 0

        def get_projects(self):
            return list(LISTS)

        def get_project_data(self, pid):
            if pid == "inbox":
                return {"tasks": []}
            self.read += 1
            if self.read >= self.die:
                raise self.err
            return {"tasks": [{"id": "t" + pid[0], "projectId": pid}], "columns": []}

        def get_task(self, pid, tid):
            return {"id": tid, "content": ""}

        def create_task(self, **kw):
            return {}


    real_store, real_client = sync.cache_store, sync.TickTickAPI
    real_v2 = api_v2.TickTickV2
    api_v2.TickTickV2 = lambda: SimpleNamespace(token="")     # no v2 leg
    try:
        store = Store(all_tasks=["BEFORE"], all_notes=["BEFORE"])
        fake = Lists(die=2, err=api.Unreachable(SILENT))
        sync.cache_store, sync.TickTickAPI = store, lambda token: fake
        try:
            sync.do_sync()
            check("line dies mid-sync: the sync stops", False, "do_sync returned")
        except api.Unreachable:
            check("line dies mid-sync: the sync stops", True)
        check("line dies mid-sync: no list is asked after it", fake.read == 2, fake.read)
        check("line dies mid-sync: all_tasks is NOT rewritten",
              store["all_tasks"] == ["BEFORE"] and "all_tasks" not in store.sets, store.sets)
        check("line dies mid-sync: all_notes is NOT rewritten",
              store["all_notes"] == ["BEFORE"] and "all_notes" not in store.sets, store.sets)

        fake = Lists(die=1, err=api.Unreachable(SILENT))
        sync.TickTickAPI = lambda token: fake
        out = said(sync.main, ["sync.py", "sync"])
        check("manual sync over a dead line: the toast", out == "⚠️ " + SILENT, out)

        banners = []
        real_notify, real_wait = sync._notify, script_base.wait_for_network
        sync._notify = lambda text, title="TickAL sync": banners.append((title, text))
        script_base.wait_for_network = lambda *a, **kw: False
        del os.environ["alfred_version"]                     # headless, like launchd
        try:
            fake = Lists(die=1, err=api.NoAnswer(QUIET))
            sync.TickTickAPI = lambda token: fake
            said(sync.main, ["sync.py", "sync"])
        finally:
            os.environ["alfred_version"] = "5"
            sync._notify, script_base.wait_for_network = real_notify, real_wait
        check("startup sync over a dead line: ONE banner, the sentence",
              banners == [("TickAL sync ⚠️", QUIET)], banners)

        # a list that fails for a reason of its own is still skipped and counted
        import okr_write    # noqa: E402
        real_upkeep = okr_write.upkeep
        okr_write.upkeep = lambda api=None: SimpleNamespace(chip="")
        store = Store(all_tasks=["BEFORE"], all_notes=[])
        fake = Lists(die=3, err=ValueError("one odd list"))
        sync.cache_store, sync.TickTickAPI = store, lambda token: fake
        try:
            out = said(sync.do_sync, ["sync.py", "sync"])
        finally:
            okr_write.upkeep = real_upkeep
        check("one odd list: skipped and counted, the sync goes on",
              "(1 list(s) failed)" in out and fake.read == 3, out)
        check("one odd list: the other lists' tasks are written",
              [t["id"] for t in store["all_tasks"]] == ["ta", "tb"], store.get("all_tasks"))
    finally:
        sync.cache_store, sync.TickTickAPI = real_store, real_client
        api_v2.TickTickV2 = real_v2

    # ── 6. real sockets on 127.0.0.1 (the backoff still not slept) ──────────
    real_base, real_timeout = api.BASE_URL, api.TIMEOUT

    mute = socket.socket()
    mute.bind(("127.0.0.1", 0))
    mute.listen(8)
    held = []


    def accept_and_say_nothing():
        while True:
            try:
                held.append(mute.accept()[0])
            except OSError:
                return


    threading.Thread(target=accept_and_say_nothing, daemon=True).start()
    gone = socket.socket()
    gone.bind(("127.0.0.1", 0))
    closed_port = gone.getsockname()[1]
    gone.close()

    api.TIMEOUT = (1, 0.3)
    try:
        api.BASE_URL = f"http://127.0.0.1:{mute.getsockname()[1]}"
        c = api.TickTickAPI("tok")
        t0 = time.monotonic()
        try:
            c.create_task("t")
            e = None
        except Exception as ex:
            e = ex
        took = time.monotonic() - t0
        check("a server that accepts and says nothing: NoAnswer",
              isinstance(e, api.NoAnswer) and str(e) == QUIET, repr(e))
        check("... within the read wait, not the kernel's", took < 3, took)
        check("NoAnswer is still a requests Timeout and a ConnectionError",
              isinstance(e, requests.Timeout) and isinstance(e, requests.ConnectionError))

        api.BASE_URL = f"http://127.0.0.1:{closed_port}"
        try:
            api.TickTickAPI("tok").get_projects()
            e = None
        except Exception as ex:
            e = ex
        check("a closed port: Unreachable, no route",
              isinstance(e, api.Unreachable) and str(e) == NO_ROUTE, repr(e))
    finally:
        api.BASE_URL, api.TIMEOUT = real_base, real_timeout

    # ── 7. the startup probe wants an answer, not a name ────────────────────
    time.sleep = REAL_SLEEP
    t0 = time.monotonic()
    check("probe: a port that answers passes",
          script_base.wait_for_network("127.0.0.1", timeout=2, step=0.1,
                                       port=mute.getsockname()[1]) is True)
    check("... at once", time.monotonic() - t0 < 1)
    t0 = time.monotonic()
    check("probe: a closed port fails when the wait is over",
          script_base.wait_for_network("127.0.0.1", timeout=0.4, step=0.1,
                                       port=closed_port) is False)
    check("... and not before", 0.4 <= time.monotonic() - t0 < 3, time.monotonic() - t0)

    dials = []


    def resolves_but_silent(address, timeout=None, **kw):
        dials.append((address, timeout))
        raise socket.timeout("timed out")


    socket.create_connection = resolves_but_silent
    time.sleep = lambda s: None
    try:
        check("probe: a name that resolves and a server that stays silent FAILS",
              script_base.wait_for_network("api.ticktick.com", timeout=0.05, step=0.01) is False)
        check("probe: it dialled port 443 with a short wait of its own",
              dials and dials[0][0] == ("api.ticktick.com", 443) and 0 < dials[0][1] <= 5, dials[:1])
    finally:
        socket.create_connection = _local_only(REAL_SOCK_CONNECT)
        time.sleep = REAL_SLEEP
        mute.close()
        for s in held:
            s.close()

    check("the suite never dialled the real network", not DIALLED, DIALLED)

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
    if __name__ == "__main__":            # make test / python3 tests/...: exit code
        sys.exit(1 if FAILS else 0)
    if FAILS:                             # imported by unittest discover: still red on failure
        raise AssertionError(f"{len(FAILS)} checks failed: {FAILS}")
