"""What lets every suite share ONE run: python3 -m unittest discover -s tests

`make test` runs each suite in its own process and is the gate. The discover
run is the second net, and it is only worth having if a red there is a real
red. On 2026-09-27 it read "Ran 206 tests, FAILED (failures=39, errors=50)"
on a tree where `make test` was green: 50 files ran their checks while the
loader imported them. 34 were reported as loader errors (19 of those had
PASSED and called sys.exit(0)), 16 ran unseen and counted as nothing, and
what they patched on the way stayed patched for the suites that ran after
them. It was not harmless either: test_commute moves HOME to a scratch
dir before it imports anything, but in the shared run cache.py was imported
already, so its two fixture rows replaced all_tasks in the LIVE
~/.ticktick_alfred/cache. Two conventions keep all of that from coming back.

1. A SCRIPT SUITE (checks that run top to bottom and end in an exit code)
   keeps its whole body under the __main__ guard, so importing it runs
   nothing. The file opens, right under its docstring, with

       if __name__ != "__main__":
           import harness
           load_tests = harness.script_suite(__file__)
       else:
           ... the suite, one level in ...

   and discover counts it as ONE test, which runs the file the way `make
   test` does: its own interpreter, the repo root as the working directory,
   the environment the run started with plus TICKAL_NO_SETTLE=1. A script
   suite may patch product modules and os.environ and never put anything
   back. That is fine in a process it owns and poison in a shared one, which
   is why it gets a process and not a tearDown.

2. A UNITTEST SUITE shares the process, so it leaves it the way it found
   it: every patch goes back in tearDown / addCleanup, and NOTHING touches
   os.environ at import. src/areas.py reads the Configure panel from
   os.environ once, when it is first imported, and four modules keep copies
   of what it read (add_task, browse, crm_menu, dispatch), so "set the
   variable, then import" only works for whichever suite imports first. A
   suite that needs the panel filled in says so instead:

       setUpModule, tearDownModule = harness.configured(
           crm_records_list_id="6a4e50e9842a1194a7c681e1",
           crm_archive_list_id="ARCHIVE")

   For as long as that module's tests run, the variables are set, areas is
   read again under them and the copies follow; afterwards all of it is put
   back. The suite is then green whatever ran before it.

KNOWN_RED names the script suites that are red on their OWN, each with the
reason. Discover reports them as expected failures, so the run stays green
until something new breaks, and turns red ("unexpected success") the day
one of them is fixed and its line here is due to go.

A new test file picks one of the two shapes; tests/test_harness.py names
any file that has neither. Run one suite with python3 tests/test_x.py, a
few with discover -s tests -p "test_x*.py".
"""
import importlib
import os
import subprocess
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)

# The environment the run started with, before any suite could touch it:
# what every script suite is handed.
ENV0 = dict(os.environ)
# The switch `make test` exports for the whole run: no background
# follow-ups against the real account (the note catch-up, the repeat settle).
os.environ.setdefault("TICKAL_NO_SETTLE", "1")

TIMEOUT = 600          # seconds one script suite may take
KNOWN_RED = {
    "test_review_20260924":
        "red on its own since 93b0dd9: xact.pn_journal asks journal_seed for "
        "want_body=True and this file's fake _JPE.journal_seed does not take "
        "it, so the run dies with a TypeError in its R13 block (54 of 54 pass "
        "once the fake takes the keyword). It is a review work order, never "
        "edited to pass, and not part of `make test`.",
}
# Modules that read os.environ at IMPORT (the Configure panel).
ENV_READERS = ("areas",)


# ── 1. script suites ────────────────────────────────────────────────────────

def _report(name, code, out):
    lines = out.decode("utf-8", "replace").splitlines()
    fails = [ln for ln in lines if "FAIL" in ln][:40]
    tail = lines[-30:]
    parts = ["%s ended with exit code %s (python3 tests/%s.py)" % (name, code, name)]
    if fails:
        parts += ["", "its FAIL lines:"] + fails
    parts += ["", "its last lines:"] + tail
    return "\n".join(parts)


def script_suite(path):
    """The load_tests of a script suite: ONE test, the file in its own
    process."""
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]

    def test_script(self):
        env = dict(ENV0, TICKAL_NO_SETTLE="1")
        try:
            run = subprocess.run([sys.executable, path], cwd=ROOT, env=env,
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=TIMEOUT)
        except subprocess.TimeoutExpired as e:
            self.fail(_report(name, "none: still running after %ds" % TIMEOUT,
                              e.output or b""))
        if run.returncode:
            self.fail(_report(name, run.returncode, run.stdout))

    test_script.__doc__ = "python3 tests/%s.py, in its own process" % name
    if name in KNOWN_RED:
        test_script.__doc__ = "known red: " + KNOWN_RED[name]
        test_script = unittest.expectedFailure(test_script)
    case = type("OwnProcess", (unittest.TestCase,),
                {"test_script": test_script, "__module__": name})

    def load_tests(loader, standard_tests, pattern):
        return unittest.TestSuite([case("test_script")])

    return load_tests


# ── 2. unittest suites ──────────────────────────────────────────────────────

def _product_modules():
    """Every loaded module of src/ and Scripts/ (the bundled lib aside)."""
    roots = tuple(os.path.join(ROOT, d) + os.sep for d in ("src", "Scripts"))
    lib = os.path.join(ROOT, "src", "lib") + os.sep
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if not path:
            continue
        path = os.path.abspath(path)
        if path.startswith(roots) and not path.startswith(lib):
            yield mod


def _follow(was, now):
    """CRM_ID = areas.CRM_ID and its kind: a loaded module holding a value
    under a reader's own name gets the value the reader holds now."""
    readers = {sys.modules.get(n) for n in ENV_READERS}
    for mod in _product_modules():
        if mod in readers:
            continue
        for key, val in list(vars(mod).items()):
            if key.startswith("__") or key not in was or key not in now:
                continue
            if callable(val) or isinstance(val, type(os)):
                continue
            old, new = was[key], now[key]
            if type(val) is type(old) and val == old and not (
                    type(new) is type(old) and new == old):
                setattr(mod, key, new)


def configured(**env):
    """setUpModule / tearDownModule for a suite written against a filled-in
    Configure panel. Bind BOTH names the call returns:

        setUpModule, tearDownModule = harness.configured(crm_list_id="CRM")
    """
    state = {}

    def setUpModule():
        mods = [importlib.import_module(n) for n in ENV_READERS]
        state["vars"] = [(m, dict(vars(m))) for m in mods]
        state["env"] = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            for m, was in state["vars"]:
                importlib.reload(m)
                _follow(was, dict(vars(m)))
        except BaseException:
            tearDownModule()
            raise

    def tearDownModule():
        for k, v in state.pop("env", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m, was in reversed(state.pop("vars", [])):
            now = dict(vars(m))
            vars(m).clear()
            vars(m).update(was)
            _follow(now, was)

    return setUpModule, tearDownModule
