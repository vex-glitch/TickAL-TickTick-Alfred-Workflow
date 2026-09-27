#!/usr/bin/env python3
"""tests/harness.py itself, the two conventions that keep `unittest
discover` worth running: a script suite is ONE test in its own process
(green, red with its FAIL lines, known red), harness.configured fills in
the Configure panel for a module's tests and puts everything back, and
every file in tests/ has one of the two shapes.
No network, no Eagle, no live TickTick; ~/.ticktick_alfred untouched.
Run: python3 tests/test_harness.py   (or unittest discover)
"""
import ast
import glob
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import harness  # noqa: E402
import areas  # noqa: E402
import dispatch  # noqa: E402  (keeps its own copy of areas.CRM_ID)

PROBE = "TICKAL_HARNESS_PROBE"      # a variable nothing else reads


class ScriptSuite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_script(self, body, name="test_tmp_script"):
        path = os.path.join(self.tmp, name + ".py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        suite = harness.script_suite(path)(None, None, None)
        self.assertEqual(suite.countTestCases(), 1)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.testsRun, 1)
        return result

    def test_a_green_script_is_one_passing_test(self):
        r = self.run_script("print('3/3 passed')\nimport sys\nsys.exit(0)\n")
        self.assertTrue(r.wasSuccessful())
        self.assertEqual((r.failures, r.errors), ([], []))

    def test_a_red_script_fails_and_shows_its_fail_lines(self):
        r = self.run_script("print('  ok  one')\nprint('FAIL  two  got 3')\n"
                            "print('1/2 passed')\nimport sys\nsys.exit(1)\n")
        self.assertEqual(len(r.failures), 1)
        text = r.failures[0][1]
        self.assertIn("test_tmp_script ended with exit code 1", text)
        self.assertIn("FAIL  two  got 3", text)
        self.assertIn("1/2 passed", text)

    def test_a_script_that_raises_is_a_failure_too(self):
        r = self.run_script("raise AssertionError('2 checks failed')\n")
        self.assertEqual(len(r.failures), 1)
        self.assertIn("AssertionError: 2 checks failed", r.failures[0][1])

    def test_the_script_gets_the_starting_environment(self):
        # what a suite of this process set is not handed down; the make
        # test switch and the repo root are
        self.assertNotIn(PROBE, harness.ENV0)
        os.environ[PROBE] = "set by a suite"
        self.addCleanup(os.environ.pop, PROBE, None)
        r = self.run_script(
            "import os, sys\n"
            "bad = [w for w, ok in (\n"
            "    ('probe', %r not in os.environ),\n"
            "    ('settle', os.environ.get('TICKAL_NO_SETTLE') == '1'),\n"
            "    ('cwd', os.path.realpath(os.getcwd()) == os.path.realpath(%r)),\n"
            "    ('main', __name__ == '__main__')) if not ok]\n"
            "print('FAIL', bad)\n"
            "sys.exit(1 if bad else 0)\n" % (PROBE, _ROOT))
        self.assertTrue(r.wasSuccessful(), r.failures)

    def test_a_known_red_script_is_an_expected_failure(self):
        saved = dict(harness.KNOWN_RED)
        self.addCleanup(lambda: (harness.KNOWN_RED.clear(),
                                 harness.KNOWN_RED.update(saved)))
        harness.KNOWN_RED["test_tmp_known"] = "the reason"
        r = self.run_script("import sys\nsys.exit(1)\n", name="test_tmp_known")
        self.assertEqual((len(r.expectedFailures), r.failures), (1, []))
        self.assertTrue(r.wasSuccessful())
        # and the day it is fixed, the run says so
        r = self.run_script("import sys\nsys.exit(0)\n", name="test_tmp_known")
        self.assertEqual(len(r.unexpectedSuccesses), 1)
        self.assertFalse(r.wasSuccessful())


class Configured(unittest.TestCase):
    def test_sets_rereads_follows_and_puts_back(self):
        before = (os.environ.get("crm_list_id"), os.environ.get("crm_records_tags"),
                  areas.CRM_ID, areas.LOGBOOK_TAG, dispatch.CRM_ID)
        year_tag, crm_tags = areas.year_tag, areas.CRM_TAGS
        up, down = harness.configured(crm_list_id="HARNESS",
                                      crm_records_tags="🗂️Customer, 🗂️Logbook")
        up()
        try:
            self.assertEqual(os.environ["crm_list_id"], "HARNESS")
            self.assertEqual(areas.CRM_ID, "HARNESS")           # read again
            self.assertEqual(areas.LOGBOOK_TAG, "🗂️logbook")
            self.assertEqual(dispatch.CRM_ID, "HARNESS")        # the copy followed
        finally:
            down()
        self.assertEqual((os.environ.get("crm_list_id"), os.environ.get("crm_records_tags"),
                          areas.CRM_ID, areas.LOGBOOK_TAG, dispatch.CRM_ID), before)
        self.assertIs(areas.year_tag, year_tag)                 # the very objects
        self.assertIs(areas.CRM_TAGS, crm_tags)

    def test_a_variable_that_was_set_comes_back(self):
        os.environ[PROBE] = "mine"
        self.addCleanup(os.environ.pop, PROBE, None)
        up, down = harness.configured(**{PROBE: "the suite's"})
        up()
        try:
            self.assertEqual(os.environ[PROBE], "the suite's")
        finally:
            down()
        self.assertEqual(os.environ[PROBE], "mine")


def _at_import(tree):
    """The nodes that run when the file is imported: not the function
    bodies, not what sits under `if __name__ == "__main__":`."""
    todo = list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.If) and ast.unparse(node.test) in (
                "__name__ == '__main__'", "'__main__' == __name__"):
            todo.extend(node.orelse)
            continue
        yield node
        todo.extend(ast.iter_child_nodes(node))


def _is_environ(node):
    return ast.unparse(node) in ("os.environ", "environ")


def _breaks(path):
    """What in this file would run against the shared process."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    doc = 1 if ast.get_docstring(tree, clean=False) is not None else 0
    guard = tree.body[doc] if len(tree.body) > doc else None
    if (isinstance(guard, ast.If) and len(tree.body) == doc + 1
            and ast.unparse(guard.test) == "__name__ != '__main__'"
            and [ast.unparse(n) for n in guard.body]
            == ["import harness", "load_tests = harness.script_suite(__file__)"]):
        return []                                   # a script suite
    out = []
    for node in _at_import(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = (node.targets if not isinstance(node, ast.AugAssign)
                       else [node.target])
            if any(isinstance(t, ast.Subscript) and _is_environ(t.value)
                   for t in targets):
                out.append("line %d sets os.environ at import: say it with "
                           "harness.configured(...)" % node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (node.func.attr in ("setdefault", "update", "pop", "clear")
                    and _is_environ(node.func.value)) \
                    or ast.unparse(node.func) in ("os.putenv", "os.unsetenv"):
                out.append("line %d sets os.environ at import: say it with "
                           "harness.configured(...)" % node.lineno)
            elif ast.unparse(node.func) == "sys.exit":
                out.append("line %d exits at import: a script suite keeps its "
                           "body under the __main__ guard" % node.lineno)
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if not classes and "load_tests" not in src:
        out.append("no TestCase and no load_tests: discover would count "
                   "nothing here")
    return sorted(out)


class Conventions(unittest.TestCase):
    def test_every_suite_has_one_of_the_two_shapes(self):
        bad = []
        for path in sorted(glob.glob(os.path.join(_HERE, "test_*.py"))):
            bad += ["tests/%s: %s" % (os.path.basename(path), why)
                    for why in _breaks(path)]
        if bad:
            self.fail("\n" + "\n".join(bad)
                      + "\n(the two shapes are in tests/harness.py)")

    def test_the_check_sees_what_it_is_for(self):
        tmp = tempfile.mkdtemp(prefix="harness_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def breaks(src):
            path = os.path.join(tmp, "test_x.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            return _breaks(path)

        case = "import unittest\nclass T(unittest.TestCase):\n    pass\n"
        self.assertEqual(breaks(case), [])
        self.assertEqual(breaks(case + "if __name__ == '__main__':\n"
                                "    import sys\n    sys.exit(0)\n"), [])
        self.assertIn("line 1 sets os.environ at import",
                      breaks("import os; os.environ.setdefault('a', 'b')\n" + case)[0])
        self.assertIn("line 1 sets os.environ at import",
                      breaks("import os; os.environ['a'] = 'b'\n" + case)[0])
        self.assertEqual(breaks("import os\n" + case + "    def setUp(self):\n"
                                "        os.environ['a'] = 'b'\n"), [])
        old = "import sys\nprint('1 passed')\nsys.exit(0)\n"
        self.assertEqual(len(breaks(old)), 2)       # exits, and counts nothing
        self.assertEqual(breaks(
            '"""doc"""\nif __name__ != "__main__":\n    import harness\n'
            "    load_tests = harness.script_suite(__file__)\nelse:\n"
            "    import os, sys\n    os.environ['HOME'] = '/tmp/x'\n    sys.exit(0)\n"), [])


if __name__ == "__main__":
    unittest.main()
