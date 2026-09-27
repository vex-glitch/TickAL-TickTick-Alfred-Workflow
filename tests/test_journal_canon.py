#!/usr/bin/env python3
"""The journal's canon aligns questions and answer lines, and leaves an
answer whole.

_canon_journal_indent runs on every refresh and every journal run: every
question to one tab, every dashless "A:" line to two. Until 2026-09-27 it
did that to ANY line that read like one, so a line typed under an answer
that began like a question ("- *Q9 · is what I keep asking myself*") or
like an answer ("A: she said yes") was pulled out from under it and stood
as a question of its own. A line that sits deeper than the answer line
above it, three tabs in or more, is part of that answer now, whatever it
reads like. Everything else is aligned exactly as before: THE CANON AS IT
WAS is kept below and every drifted journal has to come out of both the
same.

Pure: HOME is a temp dir, nothing reaches the network.

    python3.13 tests/test_journal_canon.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import socket
    import sys
    import tempfile

    _TMP = tempfile.mkdtemp(prefix="tickal_jc_")
    os.environ["HOME"] = _TMP
    os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
    os.environ["TT_V2_TOKEN"] = ""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "Scripts")):
        sys.path.insert(0, _p)

    NET = []

    def _no_net(self, *a, **k):
        NET.append(a)
        raise OSError("no network in tests")

    socket.socket.connect = _no_net
    socket.socket.connect_ex = _no_net

    import script_base                  # noqa: E402
    script_base.run_path = lambda name: os.path.join(_TMP, name)

    import periodic_sections as ps      # noqa: E402
    import periodic_model as pm         # noqa: E402
    import periodic_engine as pe        # noqa: E402

    pe.LOG_FILE = os.path.join(_TMP, "periodic.log")

    P = F = 0

    def check(n, c, d=""):
        global P, F
        if c:
            P += 1
        else:
            F += 1
            print("  FAIL", n, d)

    def as_it_was(body):
        """The canon before 2026-09-27, line for line."""
        out = []
        for ln in body:
            q = pm.JOURNAL_Q_RE.match(ln)
            if q:
                out.append(pm.journal_q_line(int(q.group("n")), q.group("q")))
                continue
            a = pm.JOURNAL_A_RE.match(ln)
            if a and ln.strip().startswith("A:"):
                out.append(f"{pm.T2}A: " + a.group("a"))
                continue
            out.append(ln)
        return out

    def canon(body):
        doc = ps.parse_sections("\n".join(["C", "---", "##### 📔 Weekly journal"] + list(body)))
        pe._canon_journal_indent(doc.sections[0])
        return doc.sections[0].body

    TIDY = ["\t- *Q1 · What was the highlight of the week?*", "\t\t- A: The keyboard", "\t\t- and the pan",
            "\t- *Q2 · What is on your mind?*", "\t\t- A: "]
    DRIFTED = {
        "a journal that is as it should be": TIDY,
        "a journal seeded flat": ["- *Q1 · What was the highlight of the week?*", "A: The keyboard",
                                  "- *Q2 · What is on your mind?*", "A: "],
        "questions without their stars": ["Q1 · What was the highlight of the week?", "\tA: The keyboard",
                                          "Q2 · What is on your mind?", "\tA: "],
        "the bold questions of July": ["\t- **Q1 · What was the highlight of the week?**", "\t\tA: The keyboard",
                                       "\t- **Q2 · What is on your mind?**", "\t\tA:"],
        "an answer typed on the phone, one level out": ["\t- *Q1 · What was the highlight of the week?*", "\tA: The keyboard",
                                                        "\t- *Q2 · What is on your mind?*", "A: nothing much"],
        "an answer typed on the phone, one level in": ["\t- *Q1 · What was the highlight of the week?*", "\t\t\tA: The keyboard",
                                                       "\t- *Q2 · What is on your mind?*", "\t\t\t\tA: nothing much"],
        "a question that drifted in": ["\t- *Q1 · What was the highlight of the week?*", "\t\t- A: The keyboard",
                                       "\t\t- *Q2 · What is on your mind?*", "\t\t\t- A: "],
        "a line of his beside the answer that reads like a question": ["\t- *Q1 · What was the highlight of the week?*", "\t\t- A: The keyboard",
                                                                      "\t\t- *Q9 · asked myself*", "\t- *Q2 · What is on your mind?*", "\t\t- A: "],
        "blank lines and a divider between the pairs": ["\t- *Q1 · What was the highlight of the week?*", "\t\tA: The keyboard", "",
                                                        "---", "- *Q2 · What is on your mind?*", "", "A: "],
        "free text and no question": ["Great week, shipped it.", "\tand slept"],
    }
    for name, body in DRIFTED.items():
        check(f"{name}: aligned exactly as before", canon(body) == as_it_was(body), (canon(body), as_it_was(body)))
    check("the canon settles: a second pass changes nothing", all(canon(canon(b)) == canon(b) for b in DRIFTED.values()))

    UNDER = {
        "a line under an answer that reads like a question": "\t\t\t- *Q9 · is what I keep asking myself*",
        "one without the stars": "\t\t\t- Q9 · is what I keep asking myself",
        "a line under an answer that reads like an answer": "\t\t\tA: she said yes, the lease is ours",
        "one four levels in": "\t\t\t\tA: and the keys on Friday",
    }
    for name, line in UNDER.items():
        body = TIDY[:2] + [line] + TIDY[2:]
        got = canon(body)
        check(f"{name}: left where he typed it", got == body, got)
        check(f"{name}: the canon as it was pulled it out", as_it_was(body) != body)
        fam = [l for l in got if l.strip() == line.strip()]
        check(f"{name}: to the tab", fam == [line], fam)
    # up to two tabs nothing changed: that is where a journal drifts, and a
    # question one level in from a flush-left answer is a question
    for body in (["\t- *Q1 · What was the highlight of the week?*", "A: The keyboard", "\tQ2 · What is on your mind?", "A: "],
                 ["Q1 · What was the highlight of the week?", "A: The keyboard", "\t\tQ2 · What is on your mind?", "\t\tA: "]):
        check("a question deeper than a drifted answer, but no deeper than two tabs, is aligned as before", canon(body) == as_it_was(body), canon(body))
    body = TIDY[:2] + ["\t\t\t- deeper, his", "\t\t\t\t- *Q9 · and deeper still*"] + TIDY[2:]
    check("a whole nest under an answer is left alone", canon(body) == body, canon(body))
    # the answers the engine reads are the same ones
    for name, body in DRIFTED.items():
        was = [(n, a) for n, _q, a, _i in pm.journal_pairs(as_it_was(body))]
        now = [(n, a) for n, _q, a, _i in pm.journal_pairs(canon(body))]
        check(f"{name}: the same answers under the same questions", was == now, (was, now))

    check("nothing reached the network", NET == [], NET[:3])
    print(f"journal canon: {P} passed, {F} failed")
    sys.exit(1 if F else 0)
