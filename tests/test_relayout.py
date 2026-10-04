#!/usr/bin/env python3
"""The relayout tools for the weekly, the monthly and the quarterly note:
what the yearly tool learned on 2026-09-27, held for the three before it.

A relayout rebuilds a note that was minted under an old skeleton in the
current template's layout. The one outcome that cannot be undone is losing a
line Vex typed, so every nasty variant below goes through plan(), the call
the tool itself writes by, and has to come out one of two ways: the line is
in the rebuilt note as often as it was in the old one, or the plan is
"refused" and names the line. Never neither.

What the three tools got wrong before, each one a check here:
  1. homes read off the REBUILT note, so a section carried over verbatim
     counted as homed and verify() never looked inside it; and off the new
     template's BULLET names, so a section of his called "Focus" was dropped
  2. a "## heading" he typed was filed as decor and dropped, in a body and
     as the last line of a section (the parser moves that one into the next
     section's pre)
  3. a section whose only text of his is in its HEADER was dropped
  4. any line shaped like _(text)_ was taken for the template's aside
  5. a note already in the current layout was rebuilt again, losing what
     was typed since
  6. verify() asked whether a line was there, never how often
and what two reviews of the port found (2026-09-27, wf_9a03e69a-b35 and
wf_3604211e-04e): the sections the old fillers wrote are frozen on an old
note, so a line typed in one lasts and has to be read; a header he wrote
into makes the section his, whatever it is called; the journal, the review
and the head of the note hold lines of his too; a goal has to stay under the
goal it was a step of; and in a real run the review mirror is REBUILT from
its source, so section G gives every tier a source (in memory) and runs the
same checks through the filler's rewrite.

The tools live in tools/pnrepair, which is local to the maintainer's machine
(/tools/ is ignored), so a checkout without them skips this suite.

Pure: HOME is a temp dir, today is pinned, Tier-2 and the completed feed are
stubbed, the run-state path cannot adopt a file out of /tmp, and a socket
guard proves nothing reached the network. No tool's main() is ever called.

    python3.13 tests/test_relayout.py
"""
if __name__ != "__main__":      # imported by unittest: tests/harness.py
    import harness
    load_tests = harness.script_suite(__file__)
else:
    import os
    import re
    import socket
    import sys
    import tempfile
    from datetime import date

    _TMP = tempfile.mkdtemp(prefix="tickal_rl_")
    os.environ["HOME"] = _TMP
    os.environ["TICKAL_CACHE_DIR"] = os.path.join(_TMP, "cache")
    os.environ["TT_V2_TOKEN"] = ""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    TOOLS = os.path.join(ROOT, "tools", "pnrepair")
    # skipped only when NONE of the four is there: one that is missing
    # beside the others is a broken tool, and the import below says so
    if not any(os.path.exists(os.path.join(TOOLS, f"relayout_{n}.py"))
               for n in ("common", "weekly", "monthly", "quarterly")):
        print("relayout: skipped (tools/pnrepair is local to the maintainer's machine)")
        sys.exit(0)
    for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "Scripts"), TOOLS):
        sys.path.insert(0, _p)

    NET = []

    def _no_net(self, *a, **k):
        NET.append(a)
        raise OSError("no network in tests")

    socket.socket.connect = _no_net
    socket.socket.connect_ex = _no_net

    # periodic_engine asks for its run-state path when it is imported, and
    # the real run_path MOVES a copy it finds in /tmp: the live sweep file
    # would end up in this run's temp dir
    import script_base                  # noqa: E402
    script_base.run_path = lambda name: os.path.join(_TMP, name)

    import periodic_sections as ps      # noqa: E402
    import periodic_model as pm         # noqa: E402
    import periodic_engine as pe        # noqa: E402

    pe.LOG_FILE = os.path.join(_TMP, "periodic.log")        # never the real log
    pe._today = lambda: date(2026, 9, 17)                   # week 38, September, Q3 all running
    pe._tier2 = lambda: None                                # never the v2 API
    pe._completed_batch = lambda: []                        # nor its completed feed

    def _no_api():
        raise RuntimeError("no API in tests")

    pe._api = _no_api

    P = F = 0
    EM = chr(0x2014)                    # by number: this file must pass the dash scan
    MINUS = chr(0x2212)                 # the old chips' minus sign
    DASH = re.compile("[" + chr(0x2013) + EM + "]")

    def check(n, c, d=""):
        global P, F
        if c:
            P += 1
        else:
            F += 1
            print("  FAIL", n, d)

    import relayout_common as rc        # noqa: E402
    import relayout_weekly as rw        # noqa: E402
    import relayout_monthly as rm       # noqa: E402
    import relayout_quarterly as rq     # noqa: E402

    import focus_blocks as fb           # noqa: E402

    DAY = date(2026, 9, 17)
    LIST = "aaaaaaaaaaaaaaaaaaaaaaaa"
    LINK = f"https://ticktick.com/webapp/#p/{LIST}/tasks/"
    T1, T2, T3 = "bbbbbbbbbbbbbbbbbbbbbbb1", "bbbbbbbbbbbbbbbbbbbbbbb2", "bbbbbbbbbbbbbbbbbbbbbbb3"

    def crumb(kind, day=DAY):
        """The head line as the engine writes it, every neighbour linked."""
        return pm.render_breadcrumb(pm.breadcrumb_segments(
            pm.period_for(kind, day), lambda q: LINK + "c" * 24))

    def box(tid, title, ticked=False):
        """A box of the review mirror, as the filler writes one."""
        ln = fb.make_line(LIST, tid, title).raw
        return ln.replace("- [ ]", "- [x]", 1) if ticked else ln

    # ── the old skeletons, as the templates shipped them before 2026-09-17,
    # filled line for line the way the fillers of the time filled them
    # (git show 9f8d648:src/periodic_engine.py) ──────────────────────────────
    JOURNAL = [
        "##### 📔 Weekly journal",
        "\t- *Q1 · What was the highlight of the week? Think of one thing that stands out.*",
        "\t\t- A: The keyboard",
        "\t- *Q2 · Did you achieve your weekly goals?*", "\t\t- A: ",
        "\t- *Q3 · What is on your mind?*", "\t\t- A: ",
        "\t- *Q4 · What would you tell a friend in your place?*", "\t\t- A: ", "---"]
    OPEN = f"[♻️ Open the review](https://ticktick.com/webapp/#p/{LIST}/tasks)"

    def mirror(name):
        return [f"##### {name}", OPEN, "", "**Inboxes**",
                box(T1, "Process inboxes", True), box(T2, "Money"), ""]

    REVIEW = mirror("♻️ Weekly Review")
    OLD_WEEKLY = "\n".join([
        crumb("weekly"), "---",
        "##### 🏆 Goals", "\t- [ ] Ship the weekly", "",
        "##### ✨ Highlight", "---",
        "#### 📌 This Week",
        "##### 🔥 Top list: 📌CTA · 13 done · 14 added", "",
        "##### 🚀 Top tasks: Commute, Paint it, Call mum", "",
        "##### ➕ Created: 214 · 🟢 12 tasks ahead of last week (+6%)", "\t- 🗂 📌CTA · 14", "\t- 🗂 Inbox · 9", "",
        "##### 📈 Stats", "\t- Mon ▇ 12", "\t- Tue ▇ 5", "\t- Wed ▇▇▇▇▇▇▇ 60", "\t- Thu ▇ 2", "\t- Fri 0", "",
        f"##### 🎯 Focus: 17h 41m · 🔴 2h 05m behind last week ({MINUS}11%)",
        "\t- Mon · 7h 43m · Paint it", "\t- Tue · 58m", "\t\t\t- **Total = 17h 41m**", "",
        "##### 📨 Entries", "\t\t**🟢 Wins**", "\t\t\t- Finished the note · Thu 11:56", "",
        "##### 😊 Moods", "\t- Tue 😐 · slept badly", "\t- Wed 🙂", "\t- Average: 3.5", "",
        "##### 🔄 Habit consistency", "\t- Weekly Review · 0/1 · 0%", "",
        "##### 💰 Income: 100", "\t- Mon 14 Sep 2026 • 100", "\t- Tue 15 Sep 2026 • 0", "\t\t\t- **Total = 100**",
        "##### 👽 People", "\t- 🎂 Andres · in 9d", "\t- 🕸️ Ana · 41d silent", "",
        "##### ✅ Completed: 79", "\t- 🗂 📌CTA · 13", "---",
        "##### ⏪ Last week", "\t- 🔥 Top list: 📌CTA · 40 done · 12 added", "\t- Completed: 387",
        "\t\t- top: Commute, Paint", "\t\t- 🗂 📌CTA · 40", "\t- Created: 120", "\t- Income: 250",
        "\t- Focus: 19h 46m", "\t- Mood: 3.2 avg", "---"] + JOURNAL + REVIEW)
    # the skeleton of July: ### headers, the group heading an H1, nav links
    JULY_WEEKLY = "\n".join([
        # a crumb whose neighbours are not this week's, and the two nav rows
        crumb("weekly", date(2026, 9, 3)),
        "[📅 Today](ticktick://v1/show?smartlist=today) · [🌄 Tomorrow](ticktick://v1/show?smartlist=tomorrow) · "
        "[7️⃣ Next 7](ticktick://v1/show?smartlist=next_7_days) · [✔️ Completed](ticktick://v1/show?smartlist=completed) · "
        "[🔄 Habits](ticktick://habit)",
        f"[👥 Customers]({LINK[:-1]}) · [💫 Periodic]({LINK[:-1]}) · [♻️ Review]({LINK[:-1]})", "---",
        "### 🏆 Goals", "- [ ] Ship the weekly", "",
        "### ✨ Highlight", "---",
        "# 📌 This Week",
        "### 🔥 Top list", "", "### 🚀 Top tasks", "",
        "### ➕ Created: 3", "", "### ✅ Completed: 1", "\t- 🗂 Inbox · 1", "",
        "### 📈 Stats", "\t_(pending)_", "", "### 🎯 Focus", "",
        "### 📨 Entries", "\t_(pending)_", "", "### 😊 Moods", "\t_(pending)_", "",
        "### 🔄 Habit consistency", "\t_(pending)_", "",
        "### 💰 Income: 0", "---",
        "### ⏪ Last week", "\t_(pending)_", "---",
        "### 📔 Weekly journal", "---",
        "### ♻️ Weekly Review",
        '\t_(set "Weekly review list id" in Settings to mirror your review here)_', ""])
    OLD_MONTHLY = "\n".join([
        crumb("monthly"), "---",
        "##### 🎯 Month goal", "- [ ]", "\t- [ ] Onboard TickTick", "",
        "##### 📈 Stats", "_(pending)_", "",
        "##### 📊 Sparklines", "_(pending)_", "",
        "##### 🏆 Top wins", "_(pending)_", "",
        "##### 👽 People", "- 🎂 Andres · in 9d", "",
        "##### 💡 Observations", "",
        "##### 💰 Money",
        "_week lines may straddle months - Total counts this month's days only_",
        "- W36 (31-06 Sep) • 100", "- W37 (07-13 Sep) • 0", "\t\t- **Total = 100**", ""])
    OLD_QUARTERLY = "\n".join([
        crumb("quarterly"), "---",
        "##### 🎯 OKR review", f"_(score last quarter's OKRs {EM} keep / kill / change)_", "\t- [ ] TickAL out", "",
        "##### 🚀 Next-Q OKRs", "",
        "##### ⚖️ Decision log", "The one decision:", "",
        "##### 🔋 Energy audit", "_(pending)_", "",
        "##### 📈 Stats", "_(pending)_", "",
        "##### 💰 Money", "- 2026-07 July • 1110", "- 2026-08 August • 0", "\t\t- **Total = 1110**", "",
        "##### 💡 Observations", ""])

    TIERS = [
        # tool, kind, old body, the bullet his goals land in, a goal line, a
        # section of the old skeleton no filler ever wrote (whole, and it has
        # a section after it), an old GENERATED section and a line typed
        # there, the journal
        (rw, "weekly", OLD_WEEKLY, pm.SEC_WK_WEEK, "\t- [ ] Ship the weekly",
         "#### 📌 This Week\n", "##### 😊 Moods", pm.SEC_WEEKLY_JNL),
        (rm, "monthly", OLD_MONTHLY, pm.SEC_MTH_MONTH, "\t- [ ] Onboard TickTick",
         "##### 📊 Sparklines\n_(pending)_\n", "##### 💰 Money", pm.SEC_MONTHLY_JNL),
        (rq, "quarterly", OLD_QUARTERLY, pm.SEC_QTR_QTR, "\t- [ ] TickAL out",
         "##### 🔋 Energy audit\n_(pending)_\n", "##### 💰 Money", pm.SEC_QTR_JNL),
    ]

    def names(doc):
        return [s.name.split(":")[0].strip() for s in doc.sections]

    def stripped(text):
        return [l.strip() for l in text.split("\n")]

    def template(kind):
        return ps.parse_sections(pm.render_template(
            pe._load_template(kind), {"breadcrumbs": "C", "daylinks": "- x", "weeklinks": "- x", "monthlinks": "- x"}))

    def named(needle, problems):
        n = needle.strip()[:40]
        return any(n in x or repr(n)[1:-1] in x for x in problems)

    def cut(text, line):
        """The text without the first line that reads `line`."""
        out, done = [], False
        for l in text.split("\n"):
            if not done and l.strip() == line.strip():
                done = True
                continue
            out.append(l)
        return "\n".join(out)

    for tool, kind, OLD, BULLET, GOAL, EMPTY, GENERATED, JNL in TIERS:
        p = pm.period_for(kind, DAY)
        T = f"{kind}."
        EMPTY_H = EMPTY.split("\n")[0]

        def held(name, body, *needles, keep=None, tool=tool, p=p, T=T):
            """The variant through plan(): every needle is in the rebuilt
            note as often as in the old one, or the plan is refused and
            names it. keep=True / False pins which of the two."""
            od = ps.parse_sections(body)
            before = ps.serialize_sections(od)
            got = tool.plan(od, p, {})
            st, problems = got.get("status"), got.get("problems") or []
            new = stripped(ps.serialize_sections(got["new"])) if got.get("new") is not None else []
            was = stripped(body)
            kept = {n: new.count(n.strip()) >= max(1, was.count(n.strip())) for n in needles}
            check(f"{T}{name}: the plan is ok or refused", st in ("ok", "refused"), st)
            check(f"{T}{name}: the old note is untouched", ps.serialize_sections(od) == before)
            if st == "ok":
                check(f"{T}{name}: ok, so every line is there", all(kept.values()) and not problems, (kept, problems))
            else:
                check(f"{T}{name}: refused, so what is not there is named",
                      bool(problems) and all(kept[n] or named(n, problems) for n in needles), (kept, problems))
            if keep is True:
                check(f"{T}{name}: kept", st == "ok" and all(kept.values()), (st, kept, problems))
                twice = {n: (was.count(n.strip()), new.count(n.strip())) for n in needles if new.count(n.strip()) > max(1, was.count(n.strip()))}
                check(f"{T}{name}: and not doubled", not twice, twice)
            if keep is False:
                check(f"{T}{name}: refused and named", st == "refused" and all(named(n, problems) for n in needles), (st, problems))
            return got

        # ── A. the untouched old note ───────────────────────────────────────
        old = ps.parse_sections(OLD)
        new = tool.build(old, p, {})
        text = ps.serialize_sections(new)
        check(f"{T}the old note is told apart from a current one",
              not tool.in_current_layout(old) and tool.in_current_layout(new) and tool.in_current_layout(template(kind)))
        check(f"{T}nothing of his is lost", tool.verify(old, new) == [], tool.verify(old, new))
        check(f"{T}the rebuilt note is the template's layout, nothing hangs at the end", names(new) == names(template(kind)), names(new))
        check(f"{T}his goal sits in its bullet", [l.strip() for l in ps.find(new, BULLET, pm.SEC_GOALS).body if l.strip()] == [GOAL.strip()],
              ps.find(new, BULLET, pm.SEC_GOALS).body)
        check(f"{T}the old generated sections are gone", GENERATED not in text and "##### 💰 Money" not in text
              and "Total = 1" not in text and "🎂 Andres" not in text, [l for l in text.split("\n") if "Total" in l or "Andres" in l])
        check(f"{T}the old template's own lines are nobody's", "The one decision:" not in text and "straddle months" not in text
              and "keep / kill / change" not in text)
        check(f"{T}no dashes of mine in the output", not DASH.search(text))
        check(f"{T}the old note itself is untouched", ps.serialize_sections(old) == ps.serialize_sections(ps.parse_sections(OLD)))
        roles = dict((s.name, r) for s, r in tool.TIER.classify(old))
        check(f"{T}every section of the old note has a role, none of them his", "his" not in roles.values() and len(roles) == len(old.sections), roles)

        # ── B. what a human can have typed ──────────────────────────────────
        check(f"{T}the fixture has the section this block writes into", EMPTY in OLD + "\n", EMPTY)
        held("1.a heading in a section nobody filled", OLD.replace(EMPTY, EMPTY_H + "\n## Big idea\nand a line under it\n"),
             "## Big idea", "and a line under it", keep=True)
        tailed = OLD.replace(EMPTY, EMPTY_H + "\nKeep Fridays free.\n## Chapter two\n")
        check(f"{T}2.the variant reaches the parser's pre", any("## Chapter two" in s.pre for s in ps.parse_sections(tailed).sections),
              [s.pre for s in ps.parse_sections(tailed).sections if s.pre])
        held("2.a heading as the last line of a section he wrote in", tailed, "Keep Fridays free.", "## Chapter two", keep=True)
        held("3.text in a header", OLD.replace(EMPTY, EMPTY_H + ": keep Fridays free\n"), EMPTY_H + ": keep Fridays free", keep=True)
        held("3.a renamed header", OLD.replace(EMPTY, "##### 💡 My own notes\n"), "##### 💡 My own notes", keep=True)
        held("4.his own aside in italics", OLD.replace(EMPTY, EMPTY_H + "\n_(no more free work)_\n"), "_(no more free work)_", keep=True)
        held("4.an aside the app escaped", OLD.replace(EMPTY, EMPTY_H + "\n\\_\\(no more free work\\)\\_\n"), "\\_\\(no more free work\\)\\_", keep=True)
        hl = (OLD.replace("##### ✨ Highlight\n", "##### ✨ Highlight\n## Big day\nThe flat\n") if "✨ Highlight" in OLD
              else OLD + "\n##### ✨ Highlight\n## Big day\nThe flat\n")
        held("1.a heading typed in the highlight", hl, "## Big day", "The flat", keep=True)
        held("3.text in the highlight's header", OLD + "\n##### ✨ Highlight: the flat\nand the keys\n", "##### ✨ Highlight: the flat", "and the keys", keep=True)
        held("two highlight sections", hl + "\n##### ✨ Highlight\nThe second one\n", "The flat", "The second one", keep=True)
        got = held("an empty box and a rule of his own in the highlight", hl.replace("The flat\n", "The flat\n- [ ]\n\t- under the box\n--- the second half\n---- cut here\n"),
                   "- under the box", "--- the second half", "---- cut here", keep=True)
        fam = rc.Tier.family(ps.find(got["new"], pm.SEC_HIGHLIGHT).body)
        check(f"{T}an empty box in the highlight is one he typed, and what is under it stays under it", ("- [ ]", "- under the box") in fam, fam)
        held("a rule of his own in a section of his", OLD + "\n##### 🧪 Experiments\n- Cold showers\n--- and then\n- Sauna\n", "--- and then", "- Sauna", keep=True)
        joined = hl + "\n##### ✨ Highlight\n\t- Keys handed over on Friday\n\t\t- by Ana\n"
        got = held("two highlight sections, the second one indented", joined, "The flat", "- Keys handed over on Friday", "- by Ana", keep=True)
        fam = rc.Tier.family(ps.find(got["new"], pm.SEC_HIGHLIGHT).body)
        check(f"{T}the second one's lines do not hang under the first one's last", ("", "- Keys handed over on Friday") in fam
              and ("- Keys handed over on Friday", "- by Ana") in fam, fam)
        out = ps.serialize_sections(got["new"])
        probs = tool.verify(ps.parse_sections(joined), ps.parse_sections(out.replace("\t- by Ana", "- by Ana")))
        check(f"{T}verify names a line of the highlight that lost its place", any("moved" in x and "by Ana" in x for x in probs), probs)
        lines = out.split("\n")
        i, j = lines.index("The flat"), lines.index("- Keys handed over on Friday")
        lines[i], lines[j] = lines[j], lines[i]
        probs = tool.verify(ps.parse_sections(joined), ps.parse_sections("\n".join(lines)))
        check(f"{T}verify names lines of the highlight that changed places", any("out of order" in x or "moved" in x for x in probs), probs)
        held("3.text in the journal's header", OLD + f"\n##### {JNL}: a hard one\nI will write it on Sunday\n", f"##### {JNL}: a hard one", "I will write it on Sunday", keep=True)
        held("3.text in the goals' header", OLD + "\n##### 🏆 Goals: the focus ones\n- [ ] Sleep before midnight\n", "##### 🏆 Goals: the focus ones", "- [ ] Sleep before midnight", keep=True)
        held("2.a heading above a section the rebuild drops",
             OLD.replace(GENERATED, "## Typed above a generated section\n" + GENERATED, 1), "## Typed above a generated section")
        held("2.a heading above a section of his at the end", OLD + "\n## My notes\n##### 🧪 Experiments\n- Cold showers\n",
             "## My notes", "##### 🧪 Experiments", "- Cold showers", keep=True)
        held("1.a section named like a generated bullet", OLD + "\n##### Focus\n- Deep work mornings only\n", "##### Focus", "- Deep work mornings only", keep=True)
        held("1.a section named like one of the template's", OLD + "\n##### 💿 Data\nA hard stretch, moved house\n", "A hard stretch, moved house", keep=True)
        held("1.a section of his own", OLD + "\n##### 🧪 Experiments\n- Cold showers\n\t- two weeks\n", "- Cold showers", "- two weeks", keep=True)
        held("1.lines that read like a filler's, in a section of his",
             OLD + "\n##### 🧪 Experiments\n- 🗂 Studio · 99\n- W01 (01-07 Jan) • 5\n- Sun ▇ 99\n\t\t- **Total = 99**\n- 2026-01 January • 5\n- 🎂 Mum · in 3d\n",
             "- 🗂 Studio · 99", "- W01 (01-07 Jan) • 5", "- Sun ▇ 99", "- **Total = 99**", "- 2026-01 January • 5", "- 🎂 Mum · in 3d", keep=True)
        held("a line typed in a section a filler wrote", OLD.replace(GENERATED + "\n", GENERATED + "\nRough stretch, did not log\n", 1),
             "Rough stretch, did not log", keep=False)
        held("a bullet typed in a section a filler wrote", OLD.replace(GENERATED + "\n", GENERATED + "\n- Owe Ana 50\n", 1), "- Owe Ana 50", keep=False)
        # the last line of the generated section's body, so the parser hands
        # it to the section after it (or leaves it, where there is none)
        gsec = next(s for s in ps.parse_sections(OLD).sections if s.header == GENERATED)
        last = [l for l in gsec.body if l.strip()][-1]
        held("a heading at the end of a section a filler wrote", OLD.replace(last + "\n", last + "\n## After the numbers\n", 1),
             "## After the numbers", keep=False)
        held("a line in the head of the note", OLD.replace("---\n", "Dentist on Friday\n---\n", 1), "Dentist on Friday", keep=False)
        for mine in ("- [Studio calendar](https://calendar.example.com/studio)", "[Budget sheet](https://x.example/b) · [Bank](https://x.example/k)",
                     "Call [Ana](https://x.example/ana) about the flash", "![Moodboard](https://x.example/m.png)",
                     "[◀ the old flat](https://x.example/f) · [Bank](https://x.example/k)",
                     "[📅 Today](ticktick://v1/show?smartlist=today) · [Bank](https://x.example/k)",
                     # a day link, a nav label, an arrow: and words of his
                     "- Fri, 18th Sep dentist at 3, move the walk-ins", "- [Fri, 18th Sep](https://x.example/d) · dentist at 3",
                     "- [Mon, 7th Sep](https://x.example/d)", "- W9 · 1st-6th Sep", "- M7 · July",
                     "👥 Team dinner Friday, [the menu](https://x.example/menu)", "[👥 Ana's portfolio](https://x.example/ana)",
                     "[💫 Periodic](https://x.example/p) · [👥 My agent](https://x.example/agent)", "[♻️ Review](https://x.example/my-own-review-doc)",
                     "[📅 Today](ticktick://v1/show?smartlist=today)",
                     "▲ Big rocks first: portfolio, taxes", "◀ Monday: dentist · Friday: walk-ins ▶", "Studio move ▶",
                     "[◀ 2026-W37](https://x.example/w) · and then the dentist ▶",
                     "◀ [2026-W37](https://x.example/w) · [2026-W39 ▶](https://x.example/n)"):
            held(f"a line of his in the head: {mine[:30]}", OLD.replace("---\n", mine + "\n---\n", 1), mine, keep=False)
        plain = pm.render_breadcrumb(pm.breadcrumb_segments(pm.period_for(kind, date(2026, 3, 3)), lambda q: None))
        for theirs in (plain, pm.child_link_lines(p, lambda q: None)[0], pm.child_link_lines(p, lambda q: LINK + "c" * 24)[-1]):
            got = tool.plan(ps.parse_sections(OLD.replace("---\n", "---\n" + theirs + "\n", 1).replace(crumb(kind) + "\n---\n", crumb(kind) + "\n", 1)
                                              if False else OLD.replace(crumb(kind) + "\n", crumb(kind) + "\n" + theirs + "\n", 1)), p, {})
            check(f"{T}a head line the engine writes is the engine's: {theirs[:30]}", got.get("status") == "ok", (got.get("status"), got.get("problems")))
        got = tool.plan(ps.parse_sections(OLD.replace(crumb(kind), crumb(kind, date(2026, 3, 3)))), p, {})
        check(f"{T}a crumb is the engine's whatever it points at", got.get("status") == "ok", (got.get("status"), got.get("problems")))
        held("a line above the first section", OLD.replace("---\n", "---\n## The year of the move\n", 1), "## The year of the move", keep=False)

        # ── the goals ───────────────────────────────────────────────────────
        twice = OLD.replace(GOAL, "\t- [ ] Goal A\n\t\t- [ ] Weekly check\n\t- [ ] Goal B\n\t\t- [ ] Weekly check")
        got = held("6.the same line under two goals", twice, "- [ ] Goal A", "- [ ] Goal B", "- [ ] Weekly check", keep=True)
        gb = [l.strip() for l in ps.find(got["new"], BULLET, pm.SEC_GOALS).body]
        check(f"{T}6.and it is there twice, under its goals", gb.count("- [ ] Weekly check") == 2, gb)
        fam = rc.Tier.family(ps.find(got["new"], BULLET, pm.SEC_GOALS).body)
        check(f"{T}6.each under its own goal", fam == [("", "- [ ] Goal A"), ("- [ ] Goal A", "- [ ] Weekly check"),
                                                       ("", "- [ ] Goal B"), ("- [ ] Goal B", "- [ ] Weekly check")], fam)
        # the template's empty box (or its aside) goes: what stood under it
        # must not slide under the goal above
        for gone in ("- [ ]", "- [x]", "_(pending)_"):
            ind = GOAL[:len(GOAL) - len(GOAL.lstrip("\t"))]
            nest = OLD.replace(GOAL, f"{ind}- [ ] Big goal\n{ind}\t- [ ] step one\n{ind}{gone}\n{ind}\t- [ ] Second goal\n{ind}\t\t- [ ] its step")
            got = held(f"goals under a line that goes ({gone})", nest, "- [ ] Big goal", "- [ ] step one", "- [ ] Second goal", "- [ ] its step", keep=True)
            fam = rc.Tier.family(ps.find(got["new"], BULLET, pm.SEC_GOALS).body)
            check(f"{T}a goal under {gone!r} stays a goal, not a step of the one above",
                  fam == [("", "- [ ] Big goal"), ("- [ ] Big goal", "- [ ] step one"), ("", "- [ ] Second goal"), ("- [ ] Second goal", "- [ ] its step")], fam)
            out = ps.serialize_sections(got["new"])
            slid = out.replace("\t- [ ] Second goal", "\t\t- [ ] Second goal").replace("\t\t- [ ] its step", "\t\t\t- [ ] its step")
            probs = tool.verify(ps.parse_sections(nest), ps.parse_sections(slid))
            check(f"{T}verify names a goal that slid under another ({gone})", any("moved" in x and "Second goal" in x for x in probs), probs)
        ind = GOAL[:len(GOAL) - len(GOAL.lstrip("\t"))]
        for gone in ("- [ ]", "_(pending)_"):
            deep = OLD.replace(GOAL, f"{ind}- [ ] Earn more\n{ind}{gone}\n{ind}\t\t- [ ] Onboard two clients\n{ind}\t\t\t- [ ] its step")
            got = held(f"a goal two levels under a line that goes ({gone})", deep, "- [ ] Earn more", "- [ ] Onboard two clients", "- [ ] its step", keep=True)
            fam = rc.Tier.family(ps.find(got["new"], BULLET, pm.SEC_GOALS).body)
            check(f"{T}it takes that line's place, however deep it was typed ({gone})",
                  fam == [("", "- [ ] Earn more"), ("", "- [ ] Onboard two clients"), ("- [ ] Onboard two clients", "- [ ] its step")], fam)
            out = ps.serialize_sections(got["new"])
            slid = out.replace("\t- [ ] Onboard two clients", "\t\t- [ ] Onboard two clients").replace("\t\t- [ ] its step", "\t\t\t- [ ] its step")
            probs = tool.verify(ps.parse_sections(deep), ps.parse_sections(slid))
            check(f"{T}verify reads the old note, not the rebuild: a goal that slid under the one above is named ({gone})",
                  any("moved" in x and "Onboard two clients" in x for x in probs), probs)
        under = OLD.replace(GOAL, f"{ind}- [ ] Big goal\n{ind}\t- [ ]\n{ind}\t\t- [ ] Under the box\n{ind}- [ ] Next goal")
        got = held("a step under an empty box that is itself a step", under, "- [ ] Big goal", "- [ ] Under the box", "- [ ] Next goal", keep=True)
        fam = rc.Tier.family(ps.find(got["new"], BULLET, pm.SEC_GOALS).body)
        check(f"{T}it stays under the goal the box was under", fam == [("", "- [ ] Big goal"), ("- [ ] Big goal", "- [ ] Under the box"), ("", "- [ ] Next goal")], fam)
        held("a goal indented with spaces", OLD.replace(GOAL, GOAL + "\n" + ind + "    - [ ] four spaces in"), "- [ ] four spaces in", keep=False)
        homes2 = OLD + f"\n##### {BULLET}\n\t\t- (pasted from the old note)\n\t- [ ] Onboard two clients\n"
        got = held("goals in two homes, the second opening deeper than it goes on", homes2, GOAL, "- (pasted from the old note)", "- [ ] Onboard two clients", keep=True)
        fam = rc.Tier.family(ps.find(got["new"], BULLET, pm.SEC_GOALS).body)
        check(f"{T}a home never hangs under the last goal of the one before",
              fam == [("", GOAL.strip()), ("", "- (pasted from the old note)"), ("", "- [ ] Onboard two clients")], fam)
        flatg = ps.parse_sections(re.sub(r"(?m)^\t+(- \[ \] (?:Weekly check|Goal [AB]))$", r"\t\1", ps.serialize_sections(held(
            "the same nest again", twice, "- [ ] Goal A")["new"])))
        check(f"{T}verify names goals that were flattened", any("moved" in x for x in tool.verify(ps.parse_sections(twice), flatg)),
              tool.verify(ps.parse_sections(twice), flatg))
        held("a heading as the last line of the goals", OLD.replace(GOAL + "\n", GOAL + "\n## Stretch goals\n", 1), "## Stretch goals", keep=False)
        short = ps.parse_sections(cut(ps.serialize_sections(got["new"]), "- [ ] Weekly check"))
        check(f"{T}6.verify counts: once is not twice", named("- [ ] Weekly check", tool.verify(ps.parse_sections(twice), short)),
              tool.verify(ps.parse_sections(twice), short))
        held("a plain text goal", OLD.replace(GOAL, "\tEarn more\n" + GOAL), "Earn more", GOAL, keep=True)
        held("a goal the app escaped", OLD.replace(GOAL, "\t- [ ] \\[Ship\\]\\(" + LINK + "cccccccccccccccccccccccc\\)"),
             "- [ ] \\[Ship\\]\\(" + LINK + "cccccccccccccccccccccccc\\)", keep=True)
        held("a goal that reads like a line of the plan", OLD.replace(GOAL, "\t- 🥅 Ship TickAL 2/5\n" + GOAL), "- 🥅 Ship TickAL 2/5", GOAL)
        held("a goal named like a tier", OLD.replace(GOAL, "\t- [ ] Monthly report\n\t- 🗓️ Monthly\n" + GOAL), "- [ ] Monthly report", "- 🗓️ Monthly", GOAL)
        held("a heading among his goals", OLD.replace(GOAL, "## This one matters\n" + GOAL), "## This one matters", keep=False)
        got = held("the template's empty box is not a goal", OLD.replace(GOAL, "\t- [ ]\n" + GOAL), GOAL, keep=True)
        gb = [l.strip() for l in ps.find(got["new"], BULLET, pm.SEC_GOALS).body if l.strip()]
        check(f"{T}and it is not carried as one", gb == [GOAL.strip()], gb)
        for s in ("##### 📊 Sparklines", "##### 🏆 Top wins", "##### 📈 Stats", "##### 🚀 Next-Q OKRs", "##### ⚖️ Decision log",
                  "##### 🔋 Energy audit", "##### 💡 Observations", "#### 📌 This Week"):
            if s + "\n" in OLD and not (kind == "weekly" and s == "##### 📈 Stats"):
                held(f"text in {s.split(' ', 1)[1]}, which no filler ever wrote", OLD.replace(s + "\n", s + "\nThe month I stopped smoking\n", 1),
                     "The month I stopped smoking", keep=True)

        # ── verify reads the OLD note for what is his: a rebuilt note that
        # lost a line of a kept section, its header or its last line is
        # named, whatever the rebuilt note says about itself ───────────────
        own = OLD.replace(GENERATED, "##### 🧪 Experiments\n- Cold showers\n\t- two weeks\n- Cold showers\n## Afterthought\n" + GENERATED, 1)
        got = held("a section of his with a heading as its last line", own, "##### 🧪 Experiments", "- Cold showers", "- two weeks", "## Afterthought", keep=True)
        od, out = ps.parse_sections(own), ps.serialize_sections(got["new"])
        flat_kept = out.replace("\t- two weeks", "- two weeks")
        probs = tool.verify(od, ps.parse_sections(flat_kept))
        check(f"{T}1.verify names a kept section that was flattened", any("changed" in x and "two weeks" in x for x in probs), probs)
        lines = out.split("\n")
        i = lines.index("##### 🧪 Experiments")
        lines[i + 1], lines[i + 2] = lines[i + 2].lstrip("\t"), "\t" + lines[i + 1]
        probs = tool.verify(od, ps.parse_sections("\n".join(lines)))
        check(f"{T}1.verify names a kept section whose lines changed places", any("changed" in x for x in probs), probs)
        probs = tool.verify(od, ps.parse_sections(out.replace("- two weeks\n", "- two weeks\n- a line nobody wrote\n", 1)))
        check(f"{T}1.verify names a line a kept section gained", any("a line nobody wrote" in x for x in probs), probs)
        for what, line in (("a line of its body", "- two weeks"), ("one of two equal lines", "- Cold showers"),
                           ("its header", "##### 🧪 Experiments"), ("its last line, the heading", "## Afterthought")):
            probs = tool.verify(od, ps.parse_sections(cut(out, line)))
            check(f"{T}1.verify names a kept section that lost {what}", named(line, probs), probs)
        tailed = OLD + "\n##### ✨ Highlight\nThe flat\n## And the keys\n##### 🧫 Cultures\nx\n" if "✨ Highlight" not in OLD \
            else OLD.replace("##### ✨ Highlight\n", "##### ✨ Highlight\nThe flat\n## And the keys\n")
        check(f"{T}2.the highlight's last line reaches the parser's pre", any("## And the keys" in s.pre for s in ps.parse_sections(tailed).sections))
        got = held("2.a heading as the last line of the highlight", tailed, "The flat", "## And the keys", keep=True)
        hb = [l.strip() for l in ps.find(got["new"], pm.SEC_HIGHLIGHT).body]
        check(f"{T}2.and it stays in the highlight", "## And the keys" in hb and "The flat" in hb, hb)
        withtwin = hl + "\n##### 🧫 Cultures\nThe flat\n"
        got = held("a line of the highlight with a twin in a section of his", withtwin, "The flat", keep=True)
        probs = tool.verify(ps.parse_sections(withtwin), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "The flat")))
        check(f"{T}verify looks in the highlight, the twin does not stand in", any("Highlight" in x and "The flat" in x for x in probs), probs)
        held("a heading as the last line of a plan section he wrote", OLD.replace(GENERATED, "#### 🥅 OKRs\n- my own note on the plan\n## After the plan\n" + GENERATED, 1),
             "- my own note on the plan", "## After the plan", keep=True)
        two = OLD + "\n##### 🧪 Experiments\n- Cold showers\n## Between the two\n##### 🧫 Cultures\nSourdough\n"
        got = held("a heading between two sections of his", two, "## Between the two", "- Cold showers", "Sourdough", keep=True)
        check(f"{T}2.and it is carried once", stripped(ps.serialize_sections(got["new"])).count("## Between the two") == 1)
        planned = OLD + "\n#### 🥅 OKRs\n- my own note on the plan\n"
        got = held("a plan section he wrote himself", planned, "- my own note on the plan", keep=True)
        plans = [s for s in got["new"].sections if s.name == pm.SEC_OKR]
        check(f"{T}it is kept as his, behind the template's own", len(plans) == 2 and "- my own note on the plan" in [l.strip() for l in plans[1].body]
              and "- my own note on the plan" not in [l.strip() for l in plans[0].body], [s.body for s in plans])
        probs = tool.verify(ps.parse_sections(planned), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "- my own note on the plan")))
        check(f"{T}verify names a line the plan section lost", named("- my own note on the plan", probs), probs)
        # the refresh's plan writer, the plan on: it rewrites the FIRST
        # section of the name whole, which is why his is not carried into it
        import okr_board as _ob
        _cols = [{"id": f"c{m}", "name": f"{_ob.keycap(m)} {DAY.year}"} for m in range(1, 13)]
        _rows = [r for m in range(1, 13) for r in (
            {"id": f"a{m:02d}" + "a" * 21, "projectId": "L" * 24, "title": "🏔️ VexOS 4️⃣", "columnId": f"c{m}", "status": 0, "sortOrder": 1},
            {"id": f"o{m:02d}" + "o" * 21, "projectId": "L" * 24, "title": "🥅 Ship TickAL", "columnId": f"c{m}",
             "parentId": f"a{m:02d}" + "a" * 21, "status": 0, "sortOrder": 1})]
        real_board = pe._okr_board
        pe._okr_board = lambda: ("L" * 24, _ob.build("L" * 24, "🔑OKRs", _cols, _rows))
        again = ps.parse_sections(ps.serialize_sections(got["new"]))
        pe._fill_okr(again, p, {})
        pe._okr_board = real_board
        plans = [s for s in again.sections if s.name == pm.SEC_OKR]
        check(f"{T}the plan writer fills the template's section and leaves his alone", len(plans) == 2
              and any("Ship TickAL" in l for l in plans[0].body) and [l.strip() for l in plans[1].body if l.strip()] == ["- my own note on the plan"],
              [s.body for s in plans])
        twin = held("6.the same line twice in the highlight", hl.replace("The flat\n", "The flat\nThe flat\n"), "The flat", keep=True)
        probs = tool.verify(ps.parse_sections(hl.replace("The flat\n", "The flat\nThe flat\n")),
                            ps.parse_sections(cut(ps.serialize_sections(twin["new"]), "The flat")))
        check(f"{T}6.verify counts in the highlight too", named("The flat", probs) and any("1 of 2" in x for x in probs), probs)
        both = OLD + "\n##### 🧪 Experiments\nSame words\n##### 🧫 Cultures\nSame words\n"
        got = held("6.the same line in two sections of his", both, "Same words", keep=True)
        probs = tool.verify(ps.parse_sections(both), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "Same words")))
        check(f"{T}6.a line is looked for where it was, a twin elsewhere does not stand in", named("Same words", probs), probs)

        # ── C. a note already in the current layout is left alone ───────────
        got = tool.plan(ps.parse_sections(text), p, {})
        check(f"{T}5.a second run does nothing", got.get("status") == "current" and got.get("new") is None, got.get("status"))
        typed = ps.parse_sections(text.replace("#### ✨ Highlight\n", "#### ✨ Highlight\nTyped since\n"))
        before = ps.serialize_sections(typed)
        got = tool.plan(typed, p, {})
        check(f"{T}5.and what was typed since stays where it is", got.get("status") == "current" and ps.serialize_sections(typed) == before)
        for line in ("- Focus: mornings only", "- Completed the move", "- Created a studio fund", "- Top lists: mine"):
            sec = "##### 📈 Stats"
            body = OLD.replace(sec + "\n", sec + "\n" + line + "\n", 1) if sec + "\n" in OLD else OLD + "\n" + sec + "\n" + line + "\n"
            got = tool.plan(ps.parse_sections(body), p, {})
            check(f"{T}5.an old note is not called current for {line!r}", got.get("status") in ("ok", "refused"), got.get("status"))
        got = tool.plan(ps.parse_sections(OLD), p, {})
        check(f"{T}the old note plans clean", got.get("status") == "ok" and got.get("problems") == []
              and ps.serialize_sections(got["new"]) == text, (got.get("status"), got.get("problems")))
        closed = tool.plan(ps.parse_sections(OLD), pm.period_for(kind, date(2025, 3, 3)), {})
        check(f"{T}a period that is over is refused", closed.get("status") == "closed" and closed.get("new") is None, closed.get("status"))
        ahead = tool.plan(ps.parse_sections(OLD), pm.period_for(kind, date(2027, 3, 3)), {})
        check(f"{T}and one that has not started", ahead.get("status") == "closed", ahead.get("status"))
        from datetime import timedelta
        for days, want in ((0, "ok"), (1, "ok"), (2, "closed"), (40, "closed")):
            pe._today = lambda d=p.end + timedelta(days=days): d
            got = tool.plan(ps.parse_sections(OLD), p, {})
            check(f"{T}{days} days after its last day the period is {want}", got.get("status") == want, got.get("status"))
        pe._today = lambda d=p.start - timedelta(days=1): d
        check(f"{T}the day before its first it has not started", tool.plan(ps.parse_sections(OLD), p, {}).get("status") == "closed")
        pe._today = lambda: DAY
        own = OLD + "\n##### 📊 Stats\n- my numbers\n\t- Focus: mornings\n\t- Created\n"
        held("a section of his named like the group, the group's bullets one level down", own, "- my numbers", "- Focus: mornings", keep=True)
        held("a section of his named like the group, bullets that only START like the group's",
             OLD + "\n##### 📊 Stats\n- Focus on mornings\n- Created a studio fund\n- Completed the move\n", "- Focus on mornings", "- Created a studio fund", keep=True)
        got = tool.plan(ps.parse_sections(OLD + "\n##### 📊 Stats\n- Focus\n"), p, {})
        check(f"{T}a note that holds the group with one of its bullets is left alone, nothing done", got.get("status") == "current" and got.get("new") is None,
              got.get("status"))

    # ── D. the weekly's own: the six headed sections, the journal, the review
    p = pm.period_for("weekly", DAY)

    def wheld(name, body, *needles, keep=None):
        od = ps.parse_sections(body)
        got = rw.plan(od, p, {})
        st, problems = got.get("status"), got.get("problems") or []
        new = stripped(ps.serialize_sections(got["new"])) if got.get("new") is not None else []
        kept = {n: new.count(n.strip()) >= max(1, stripped(body).count(n.strip())) for n in needles}
        check(f"weekly.{name}: kept, or refused and named", st in ("ok", "refused")
              and all(kept[n] or (st == "refused" and named(n, problems)) for n in needles)
              and (st == "refused" or not problems), (st, kept, problems))
        if keep is True:
            check(f"weekly.{name}: kept", st == "ok" and all(kept.values()), (st, kept, problems))
        if keep is False:
            check(f"weekly.{name}: refused and named", st == "refused" and all(named(n, problems) for n in needles), (st, problems))
        return got

    got = rw.plan(ps.parse_sections(JULY_WEEKLY), pm.period_for("weekly", DAY), {})
    out = ps.serialize_sections(got["new"]) if got.get("new") is not None else ""
    check("weekly.the skeleton of July plans clean, its H1 group heading is nobody's",
          got.get("status") == "ok" and "# 📌 This Week" not in stripped(out) and names(got["new"]) == names(template("weekly")),
          (got.get("status"), got.get("problems")))
    check("weekly.and its goal is carried", "- [ ] Ship the weekly" in stripped(out))

    wheld("a header the filler wrote goes with its section", OLD_WEEKLY, "\t- [ ] Ship the weekly", keep=True)
    wheld("his words in a header the filler wrote into", OLD_WEEKLY.replace("##### ➕ Created: 214 · 🟢 12 tasks ahead of last week (+6%)", "##### ➕ Created: 214 and counting"),
          "##### ➕ Created: 214 and counting", keep=True)
    wheld("his words in the income header", OLD_WEEKLY.replace("##### 💰 Income: 100", "##### 💰 Income: 100 plus the deposit"),
          "##### 💰 Income: 100 plus the deposit", keep=True)
    wheld("his words in the money section's header", OLD_WEEKLY + "\n##### 💰 Money: saving for the car\n- 200 aside in August\n",
          "##### 💰 Money: saving for the car", "- 200 aside in August", keep=True)
    wheld("a line under Top list, which only ever got a header", OLD_WEEKLY.replace("added\n", "added\n\tthe studio list, really\n", 1),
          "the studio list, really", keep=False)
    wheld("a line in People the filler could not have written", OLD_WEEKLY.replace("\t- 🎂 Andres · in 9d\n", "\t- 🎂 Andres · in 9d\n\t- Ana: ask about the flash sheet\n"),
          "- Ana: ask about the flash sheet", keep=False)
    wheld("a line in Last week", OLD_WEEKLY.replace("\t- Mood: 3.2 avg\n", "\t- Mood: 3.2 avg\n\t- Focus on the family\n"), "- Focus on the family", keep=False)
    wheld("text under This Week", OLD_WEEKLY.replace("#### 📌 This Week\n", "#### 📌 This Week\nThe week of the move\n"), "The week of the move", keep=True)
    wheld("a Top tasks header no filler could have written", OLD_WEEKLY.replace("##### 🚀 Top tasks: Commute, Paint it, Call mum",
          "##### 🚀 Top tasks: finish the flash sheet for the Saturday walk-ins"), "##### 🚀 Top tasks: finish the flash sheet for the Saturday walk-ins", keep=True)
    wheld("a focus line with more words than the filler writes", OLD_WEEKLY.replace("\t- Tue · 58m\n",
          "\t- Tue · 58m\n\t- Sat · 3h 00m · painting at the studio, the timer app was off all day\n"),
          "- Sat · 3h 00m · painting at the studio, the timer app was off all day", keep=False)
    wheld("a top line in Last week he rewrote", OLD_WEEKLY.replace("\t\t- top: Commute, Paint\n", "\t\t- top: finally moved the whole studio into the new place\n"),
          "- top: finally moved the whole studio into the new place", keep=False)
    # each generated section takes ITS filler's lines only
    for where, line in (("##### 😊 Moods\n", "\t- Meditate · 5/7 · 71%"), ("##### 🔄 Habit consistency\n", "\t- Tue 😐 · slept badly"),
                        ("##### 💰 Income: 100\n", "\t- 🎂 Mum · in 3d"), ("##### 👽 People\n", "\t- Mon 14 Sep 2026 • 100"),
                        ("##### 📈 Stats\n", "\t- Mon · 7h 43m"), ("##### 📨 Entries\n", "\t- Average: 3.5"),
                        ("##### ⏪ Last week\n", "\t- W36 (31-06 Sep) • 100")):
        check(f"weekly.the fixture has {where.strip()}", where in OLD_WEEKLY)
        wheld(f"another filler's line in {where.strip()[6:]}", OLD_WEEKLY.replace(where, where + line + "\n", 1), line, keep=False)
    wheld("the week's total typed into 📈 Stats", OLD_WEEKLY.replace("\t- Fri 0\n", "\t- Fri 0\n**Week: 79**\n"), "**Week: 79**", keep=False)
    wheld("a goal named like the tier bullet, one level in", OLD_WEEKLY.replace("\t- [ ] Ship the weekly", "\t- [ ] Ship the weekly\n\t- ♻️ Weekly"),
          "- [ ] Ship the weekly", "- ♻️ Weekly", keep=True)
    wheld("a heading as the last line of the journal", OLD_WEEKLY.replace("\t- *Q4 · What would you tell a friend in your place?*\n\t\t- A: \n",
          "\t- *Q4 · What would you tell a friend in your place?*\n\t\t- A: \n## Next week\n"), "## Next week", keep=True)
    wheld("a line three levels under an answer", OLD_WEEKLY.replace("\t\t- A: The keyboard\n", "\t\t- A: The keyboard\n\t\t\t- the one with the brown switches\n"),
          "- the one with the brown switches", keep=True)
    wheld("a heading as the last line of the review, a generated section after it",
          OLD_WEEKLY + "## Parked\n##### 🔄 Habit consistency\n\t- Meditate · 5/7 · 71%\n", "## Parked", keep=False)
    goaltwin = OLD_WEEKLY.replace("\t\t- A: The keyboard\n", "\t\t- A: The keyboard\n\t\t- [ ] Ship the weekly\n")
    got = wheld("a goal with a twin in the journal", goaltwin, "- [ ] Ship the weekly", keep=True)
    probs = rw.verify(ps.parse_sections(goaltwin), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "- [ ] Ship the weekly")))
    check("weekly.verify looks under the goal bullet, the twin does not stand in", any("♻️ Weekly" in x and "Ship the weekly" in x for x in probs), probs)

    wk = OLD_WEEKLY.replace("##### ✨ Highlight\n", "##### ✨ Highlight\nThe keyboard arrived\n")
    wk = wk.replace("\t\t- A: The keyboard\n", "\t\t- A: The keyboard\n\t\t- and the pan\n\t\t- ## Plans\n")
    od = ps.parse_sections(wk)
    nd = rw.build(od, p, {})
    out = ps.serialize_sections(nd)
    check("weekly.the highlight he typed is carried", "The keyboard arrived" in [l.strip() for l in ps.find(nd, pm.SEC_HIGHLIGHT).body], ps.find(nd, pm.SEC_HIGHLIGHT).body)
    check("weekly.every answer with its continuation lines", all(x in out for x in ("- A: The keyboard", "- and the pan", "- ## Plans")) and rw.verify(od, nd) == [],
          rw.verify(od, nd))
    rb = pm.checkbox_tids(ps.find(nd, pm.SEC_REVIEW).body)
    check("weekly.the review's ticks with their state", rb == {"bbbbbbbbbbbbbbbbbbbbbbb1": True, "bbbbbbbbbbbbbbbbbbbbbbb2": False}, rb)
    flipped = ps.parse_sections(out.replace("- [x] [Process inboxes]", "- [ ] [Process inboxes]"))
    check("weekly.verify notices a tick that changed", any("tick" in x for x in rw.verify(od, flipped)), rw.verify(od, flipped))
    gone = ps.parse_sections(cut(out, "- and the pan"))
    check("weekly.verify notices a lost answer line", named("- and the pan", rw.verify(od, gone)), rw.verify(od, gone))
    check("weekly.the old journal keeps its own questions", "What was the highlight of the week?" in out
          and "What would you tell a friend in your place?" in out)
    free = ps.parse_sections(cut(out, "- *Q4 · What would you tell a friend in your place?*"))
    check("weekly.a question the engine does not own is held like a line of his", named("What would you tell a friend", rw.verify(od, free)), rw.verify(od, free))

    jtwin = wk + "##### 🧫 Cultures\n- and the pan\n"
    got = wheld("a line of the journal with a twin in a section of his", jtwin, "- and the pan", keep=True)
    probs = rw.verify(ps.parse_sections(jtwin), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "- and the pan")))
    check("weekly.verify looks in the journal, the twin does not stand in", any("journal" in x and "lost" in x and "and the pan" in x for x in probs), probs)
    probs = rw.verify(od, ps.parse_sections(out.replace("\t\t- and the pan", "\t- and the pan")))
    check("weekly.verify names an answer's line that came out from under it", any("moved" in x and "and the pan" in x for x in probs), probs)
    lines = out.split("\n")
    i, j = lines.index("\t\t- and the pan"), lines.index("\t\t- ## Plans")
    lines[i], lines[j] = lines[j], lines[i]
    probs = rw.verify(od, ps.parse_sections("\n".join(lines)))
    check("weekly.verify names answer lines that changed places", any("out of order" in x for x in probs), probs)
    # three tabs in, the journal's canon leaves an answer whole (since
    # 2026-09-27); beside the answer it still reads such a line as a
    # question of its own and moves it, and that is refused and named
    for mine in ("\t\t\t- *Q9 · is what I keep asking myself*", "\t\t\tA: she said yes, the lease is ours"):
        wheld(f"a line under an answer that reads like the engine's ({mine.strip()[:12]})",
              OLD_WEEKLY.replace("\t\t- A: The keyboard\n", "\t\t- A: The keyboard\n" + mine + "\n"), mine, keep=True)
    wheld("a line beside an answer that reads like a question", OLD_WEEKLY.replace("\t\t- A: The keyboard\n",
          "\t\t- A: The keyboard\n\t\t- and the pan\n\t\t\t- for the eggs\n\t\t- *Q9 · is what I keep asking myself*\n"),
          "- *Q9 · is what I keep asking myself*")
    starred = OLD_WEEKLY.replace("\t- [ ] Ship the weekly", "\t- [ ] Read *Deep Work*\n\t- [ ] Sleep before midnight").replace(
        "\t- *Q2 · Did you achieve your weekly goals?*", "\t- *Q2 · Did you achieve your weekly goals, Read *Deep Work*? Describe success/fail factors on each.*")
    got = rw.plan(ps.parse_sections(starred), p, {})
    check("weekly.a set question that quotes a goal with stars in it is still the engine's", got.get("status") == "ok", (got.get("status"), got.get("problems")))
    wheld("a journal of plain text, no question in it", OLD_WEEKLY.replace("\n".join(JOURNAL[1:-1]), "Great week, shipped it.\n\tand slept"),
          "Great week, shipped it.", "and slept", keep=True)
    wheld("text typed after a question's closing star",
          OLD_WEEKLY.replace("\t- *Q2 · Did you achieve your weekly goals?*", "\t- *Q2 · Did you achieve your weekly goals?* Mostly, two of three"),
          "- *Q2 · Did you achieve your weekly goals?* Mostly, two of three")
    wheld("a line under an answer that reads like a question",
          OLD_WEEKLY.replace("\t\t- A: The keyboard\n", "\t\t- A: The keyboard\n\t\t\t- Q9 · is what I keep asking myself\n"),
          "- Q9 · is what I keep asking myself")
    got = wheld("a plain line and a box of his own in the review",
                OLD_WEEKLY.replace("**Inboxes**\n", "**Inboxes**\nCall the accountant first\n- [ ] the shoebox of receipts\n"),
                "Call the accountant first", "- [ ] the shoebox of receipts", keep=True)
    rv = ps.parse_sections(OLD_WEEKLY.replace("**Inboxes**\n", "**Inboxes**\nCall the accountant first\n- [ ] the shoebox of receipts\n"))
    for line in ("Call the accountant first", "- [ ] the shoebox of receipts"):
        probs = rw.verify(rv, ps.parse_sections(cut(ps.serialize_sections(got["new"]), line)))
        check(f"weekly.verify names {line!r} once the mirror is rebuilt without it", named(line, probs), probs)
    wheld("text in the review's header", OLD_WEEKLY.replace("##### ♻️ Weekly Review\n", "##### ♻️ Weekly Review: before Sunday lunch\n"),
          "##### ♻️ Weekly Review: before Sunday lunch", keep=True)
    TIERED = ("##### 🏆 Goals\n- 🌓 Quarterly\n\t- [ ] The quarter's own\n- 🗓️ Monthly\n- ♻️ Weekly\n\t- [ ] Goal A\n\t\t- [ ] step of A\n"
              "\t- [ ]\n\t\t- [ ] Goal B\n")
    tiered = OLD_WEEKLY.replace("##### 🏆 Goals\n\t- [ ] Ship the weekly\n", TIERED)
    got = wheld("an old note whose goals already hold the tier bullets", tiered, "- [ ] Goal A", "- [ ] step of A", "- [ ] Goal B", "- [ ] The quarter's own", keep=True)
    own = rc.Tier.family(ps.find(got["new"], pm.SEC_WK_WEEK, pm.SEC_GOALS).body)
    check("weekly.the week's own goals under ♻️ Weekly, and only those", own == [("", "- [ ] Goal A"), ("- [ ] Goal A", "- [ ] step of A"), ("", "- [ ] Goal B")], own)
    up = [l.strip() for l in ps.find(got["new"], pm.SEC_WK_QTR, pm.SEC_GOALS).body if l.strip()]
    check("weekly.what stood under the quarter's bullet is under it again", up == ["- [ ] The quarter's own"], up)
    probs = rw.verify(ps.parse_sections(tiered), ps.parse_sections(cut(ps.serialize_sections(got["new"]), "- [ ] The quarter's own")))
    check("weekly.verify names a line a tier bullet lost", named("- [ ] The quarter's own", probs), probs)
    folded = tiered.replace("- ♻️ Weekly\n", '- ♻️ Weekly <!-- {"folded":true} -->\n')
    got = wheld("the goal bullet folded in the app", folded, "- [ ] Goal A", "- [ ] step of A", "- [ ] Goal B", "- [ ] The quarter's own", keep=True)
    own = rc.Tier.family(ps.find(got["new"], pm.SEC_WK_WEEK, pm.SEC_GOALS).body)
    check("weekly.a folded goal bullet is still the goal bullet", own == [("", "- [ ] Goal A"), ("- [ ] Goal A", "- [ ] step of A"), ("", "- [ ] Goal B")], own)
    killed = OLD_WEEKLY.replace("##### 🏆 Goals\n\t- [ ] Ship the weekly\n", "##### 🏆 Goals\n- 🌓 Quarterly\n\t- [ ] Ship TickAL\n- 🗓️ Monthly\n\t- [ ] Onboard\n")
    got = wheld("the tier bullets without the week's own (he deleted it)", killed, "- [ ] Ship TickAL", "- [ ] Onboard", keep=True)
    own = [l.strip() for l in ps.find(got["new"], pm.SEC_WK_WEEK, pm.SEC_GOALS).body if l.strip()]
    check("weekly.what stood under the tiers above is not filed as the week's own", own == [], own)
    up = [l.strip() for l in ps.find(got["new"], pm.SEC_WK_MONTH, pm.SEC_GOALS).body if l.strip()]
    check("weekly.it is under its own tier", up == ["- [ ] Onboard"], up)
    aside = tiered.replace("\t- [ ] The quarter's own\n", "\t- [ ] The quarter's own\n\t- _(mirrors this quarter's note - set it there)_\n\t\t\t- my own line\n")
    got = wheld("a line under the aside of a tier above", aside, "- my own line", "- [ ] The quarter's own", keep=True)
    up = rc.Tier.family(ps.find(got["new"], pm.SEC_WK_QTR, pm.SEC_GOALS).body, lambda l: not rw.his(l))
    check("weekly.it takes the aside's place, not a place under the goal above", up == [("", "- [ ] The quarter's own"), ("", "- my own line")], up)
    wheld("a line between the tier bullets", tiered.replace("- 🗓️ Monthly\n", "- 🗓️ Monthly\n- A line between the tiers\n\t- and one under it\n"),
          "- A line between the tiers", "- and one under it", keep=False)
    wheld("a heading as the last line of the tier bullets", tiered.replace("\t\t- [ ] Goal B\n", "\t\t- [ ] Goal B\n## Stretch goals\n"), "## Stretch goals", keep=False)

    # ── E. the monthly's and the quarterly's own ────────────────────────────
    for tool, kind, OLD, last in ((rm, "monthly", OLD_MONTHLY, "⏪ Last month"), (rq, "quarterly", OLD_QUARTERLY, "⏪ Last quarter")):
        p = pm.period_for(kind, DAY)

        def mheld(name, body, *needles, keep=None, tool=tool, p=p, kind=kind):
            got = tool.plan(ps.parse_sections(body), p, {})
            st, problems = got.get("status"), got.get("problems") or []
            new = stripped(ps.serialize_sections(got["new"])) if got.get("new") is not None else []
            kept = {n: new.count(n.strip()) >= max(1, stripped(body).count(n.strip())) for n in needles}
            check(f"{kind}.{name}: kept, or refused and named", st in ("ok", "refused")
                  and all(kept[n] or (st == "refused" and named(n, problems)) for n in needles)
                  and (st == "refused" or not problems), (st, kept, problems))
            if keep is True:
                check(f"{kind}.{name}: kept", st == "ok" and all(kept.values()), (st, kept, problems))
            if keep is False:
                check(f"{kind}.{name}: refused and named", st == "refused" and all(named(n, problems) for n in needles), (st, problems))

        mheld("his words in the money header", OLD.replace("##### 💰 Money\n", "##### 💰 Money: saving for the car\n- 200 aside in August\n"),
              "##### 💰 Money: saving for the car", "- 200 aside in August", keep=True)
        mheld("a note in the money roll-up", OLD.replace("\t\t- **Total = 1", "- Owe Ana 50\n\t\t- **Total = 1"), "- Owe Ana 50", keep=False)
        mheld("a total he wrote himself", OLD.replace("\t\t- **Total = 1", "**Total = a lot**\n\t\t- **Total = 1"), "**Total = a lot**", keep=False)
        for line in ("- Tue 15 Sep 2026 • 40", "- 🎂 Mum · in 3d", "- W36 (31-06 Sep) • 100" if kind == "quarterly" else "- 2026-07 July • 5"):
            mheld(f"another filler's line in the money roll-up ({line[:12]})", OLD.replace("\t\t- **Total = 1", line + "\n\t\t- **Total = 1"), line, keep=False)
        mheld("a section named like the template's look back", OLD + f"\n##### {last}\nA hard stretch, moved house\n", "A hard stretch, moved house", keep=True)
        mheld("a journal he started by hand", OLD + f"\n##### {tool.TIER.journal}\nThe month in one line: tired\n", "The month in one line: tired", keep=True)
        mheld("a goals section of his own", OLD + "\n##### 🏆 Goals\n- [ ] Sleep before midnight\n", "- [ ] Sleep before midnight", keep=True)
        above = tool.TIER.mirrors()[0]
        group = OLD + f"\n#### 🏆 Goals\n- {above}\n\t- [ ] from the tier above\n- {tool.TIER.goal} " + '<!-- {"folded":true} -->' + "\n\t- [ ] typed under the folded bullet\n"
        got = tool.plan(ps.parse_sections(group), p, {})
        mine = [l.strip() for l in ps.find(got["new"], tool.TIER.goal, pm.SEC_GOALS).body if l.strip()]
        check(f"{kind}.goals under the tier bullets, the goal bullet folded: each under its own", got.get("status") == "ok"
              and "- [ ] typed under the folded bullet" in mine and "- [ ] from the tier above" not in mine
              and "- [ ] from the tier above" in [l.strip() for l in ps.find(got["new"], above, pm.SEC_GOALS).body]
              and [s.name for s in got["new"].sections].count("🏆 Goals") == 1, (got.get("status"), got.get("problems"), mine))
    mp = pm.period_for("monthly", DAY)
    got = rm.plan(ps.parse_sections(OLD_MONTHLY.replace("- 🎂 Andres · in 9d\n", "- 🎂 Andres · in 9d\n- Ana: ask about the flash sheet\n")), mp, {})
    check("monthly.a line in People the filler could not have written is named", got.get("status") == "refused"
          and named("- Ana: ask about the flash sheet", got.get("problems") or []), (got.get("status"), got.get("problems")))
    got = rm.plan(ps.parse_sections(OLD_MONTHLY.replace("##### 👽 People\n", "##### 👽 People: call mum\n- mum, Sunday\n")), mp, {})
    out = stripped(ps.serialize_sections(got["new"]))
    check("monthly.his words in the People header keep the section", got.get("status") == "ok" and "##### 👽 People: call mum" in out and "- mum, Sunday" in out,
          (got.get("status"), got.get("problems")))

    # ── F. the lists, the way they are now ──────────────────────────────────
    for tool, kind in ((rw, "weekly"), (rm, "monthly"), (rq, "quarterly")):
        homes = tool.homes()
        tpl = template(kind)
        check(f"{kind}.homes are the template's SECTIONS", set(names(tpl)) <= set(homes))
        bullets = {b.name.split(":")[0].strip() for s in tpl.sections for b in ps._blocks(s)} - set(names(tpl)) - set(tool.TIER.generated)
        check(f"{kind}.and never its bullets", not (bullets & set(homes)), bullets & set(homes))
        check(f"{kind}.no section is dropped unread: none without a filler is listed",
              not ({"🧭 Nav", "💬 Quote & weather", "📌 This Week", "📌 This Month", "📌 This Quarter"} & set(tool.TIER.generated)), tool.TIER.generated.keys())
        check(f"{kind}.the header data is only cut where a filler wrote it", set(tool.TIER.headed) <= set(tool.TIER.generated), tool.TIER.headed.keys())
    check("monthly.only what a filler wrote is read as generated", set(rm.TIER.generated) == {"💰 Money", "👽 People"}, rm.TIER.generated.keys())
    check("quarterly.only what a filler wrote is read as generated", set(rq.TIER.generated) == {"💰 Money"}, rq.TIER.generated.keys())
    check("weekly.the six headed sections are the six _set_headed wrote", set(rw.TIER.headed) == {"🔥 Top list", "🚀 Top tasks", "➕ Created", "✅ Completed", "🎯 Focus", "💰 Income"},
          rw.TIER.headed.keys())
    check("monthly and quarterly have none", not rm.TIER.headed and not rq.TIER.headed)
    check("the asides are matched whole, in both spellings the templates shipped",
          not rq.his(f"_(score last quarter's OKRs {EM} keep / kill / change)_") and not rq.his("_(score last quarter's OKRs - keep / kill / change)_")
          and not rm.his(f"_week lines may straddle months {EM} Total counts this month's days only_")
          and not rm.his("\\_\\(pending\\)\\_") and not rw.his("\t_(pending)_") and not rq.his("The one decision:")
          and rq.his("The one decision: raise prices") and rm.his("_(pending review with Ana)_") and rw.his("## Big day") and not rw.his("---")
          and not rw.his("# 📌 This Week") and rw.his("# 📌 This Week, the hard one"))
    S = rc.SHAPES
    check("the week's total is no filler's line: none ever wrote it into 📈 Stats", "bar_total" not in S)
    for shape, yes, no in (
            ("last_income", "- Income: 250", "- Income: the deposit from Ana is still missing"),
            ("last_income", "- Income: 99.50", "- Income: lots"),
            ("last_mood", "- Mood: 3.2 avg", "- Mood: rough, we moved house"),
            ("last_top", "- 🔥 Top list: 📌CTA · 40 done · 12 added", "- 🔥 Top list: the studio list, really"),
            ("last_count", "- Created: 120", "- Completed: the move to the new studio"),
            ("focus_total", "- **Total = 17h 41m**", "- **Total = a long week**"),
            ("head_focus", "17h 41m · 🔴 2h 05m behind last week (" + MINUS + "11%)", "17h 41m of painting, mostly"),
            ("head_focus", "58m", "most of the week"),
            ("head_top", "📌CTA · 13 done · 14 added", "the studio list, really"),
            ("head_count", "79 · ⚪ level with last week", "79 · and I am proud of every one"),
            ("head_count", "214 · 🟢 12 tasks ahead of last week (+6%)", "214 · 🟢 12 tasks ahead of my plan"),
            ("head_amount", "100 · 🟢 40 ahead of last week (+66%)", "100 · 🟢 and rising"),
            ("mood_avg", "- Average: 2.7", "- Average: fine, all things considered"),
            ("money_month", "- 2026-08 August • 0", "- 2026-07 July was slow"),
            ("money_month", "- 2026-07 July • -40.25", "- 2026-07 July • lots"),
            ("money_day", "- Tue 15 Sep 2026 • 0", "- Mon 14 Sep 2026 • 100 from Ana"),
            ("money_week", "- W40 (28-04 Oct) • 12.50", "- W36 (31-06 Sep) • lots"),
            ("entry", "- Finished the note · Thu 11:56", "- Finished the note · Thu evening"),
            ("habit", "- Weekly Review · 0/1 · 0%", "- Weekly Review · most weeks"),
            ("birthday", "- 🎂 Mum · today 🎉", "- 🎂 Mum · in a week or so"),
            ("stale", "- 🕸 Ana · never logged", "- 🕸️ Ana · 41 days, call her"),
            ("day_bar", "- Fri 0", "- Fri ▇▇ a lot"),
            ("breakdown", "- 🗂 📌CTA · 14", "- 🗂 sort the flash sheets"),
            ("day_bar", "- Wed ▇▇▇ 60", "- Wed was the worst"),
            ("day_focus", "- Mon · 7h 43m · Paint it", "- Mon · dentist"),
            ("entry", "- Finished the note · Thu 11:56", "- Finished the note · on Thursday"),
            ("entry_group", "**🟢 Wins**", "**Remember**"),
            ("mood_day", "- Tue 😐 · slept badly", "- Tue bad"),
            ("mood_avg", "- Average: 3.5", "- Average week"),
            ("habit", "- Meditate · 5/7 · 71%", "- Meditate more"),
            ("money_day", "- Mon 14 Sep 2026 • 100", "- Mon • 100 from Ana"),
            ("money_week", "- W36 (31-06 Sep) • 100", "- W36 was slow"),
            ("money_month", "- 2026-07 July • 1110", "- July • a lot"),
            ("money_total", "- **Total = 1110**", "- **Total = a lot**"),
            ("birthday", "- 🎂 Andres · in 9d", "- 🎂 Andres · buy the cake"),
            ("stale", "- 🕸️ Ana · 41d silent", "- 🕸️ Ana · call her"),
            ("last_count", "- Completed: 387", "- Completed the move"),
            ("last_focus", "- Focus: 19h 46m", "- Focus: mornings only"),
            ("head_count", "214 · 🟢 12 tasks ahead of last week (+6%)", "214 and counting"),
            ("head_tasks", "Commute, Paint it, Call mum", "finish the flash sheet for the Saturday walk-ins"),
            ("head_tasks", "Buy milk, eggs, Commute, Paint it", "portfolio · taxes · call the landlord about the leak in the roof"),
            ("last_tasks", "- top: Commute, Paint", "- top: finally moved the whole studio into the new place"),
            ("last_tasks", "- top: Reply to Ana about the flash she, , Book the studio for the Saturday", "- top:    "),
            ("head_tasks", "Reply to Ana about the flash she, , ", "one two three four five six seven eight nine"),
            ("day_focus", "- Tue · 58m", "- Sat · 3h 00m · painting at the studio, the timer app was off all day"),
            ("day_focus", "- Wed · 1h 10m ·", "- Wed · 1h 10m · · and then some more words than forty letters hold"),
            ("crumb_part", "◀ 2026-W37", "◀ Monday: dentist"), ("crumb_part", "2026-10 October ▶", "Studio move ▶"),
            ("crumb_part", "▲ 2026", "▲ Big rocks first"),
            ("head_amount", "100", "100 plus the deposit"),
            ("question", "- *Q1 · What is on your mind?*", "- *Q1 · What is on your mind?* a lot")):
        check(f"the {shape} shape is what the filler wrote and nothing near it", bool(S[shape].match(yes)) and not S[shape].match(no), (yes, no))

    # ── G. the review mirror, REBUILT. In a real run the weekly's filler
    # rewrites the mirror from its source (the list the review id names), so
    # the suite gives it one, in memory, and judges the mirror after the
    # rewrite. The old monthly and quarterly had no mirror: a review section
    # in one is his, source or no source ─────────────────────────────────────
    class Source:
        tasks = []
        columns = [{"id": "c1", "name": "Inboxes"}, {"id": "c2", "name": "Closing"}]
        titles = {T1: "Process inboxes", T2: "Money", T3: "Lock up", "e" * 24: "Book the dentist"}     # what get_task answers
        broken = False
        reads = 0

        def get_project_data(self, pid):
            Source.reads += 1
            if Source.broken:
                raise RuntimeError("the list cannot be read")
            return {"tasks": [dict(t) for t in Source.tasks], "columns": [dict(c) for c in Source.columns]}

        def get_task(self, pid, tid):
            if tid not in Source.titles:
                raise RuntimeError("no such task")
            return {"id": tid, "projectId": pid, "title": Source.titles[tid], "status": 2}

        def __getattr__(self, name):             # every other call: no API in tests
            raise RuntimeError("no API in tests")

    BOTH = [{"id": T1, "title": "Process inboxes", "columnId": "c1", "status": 0, "sortOrder": 1},
            {"id": T2, "title": "Money", "columnId": "c1", "status": 0, "sortOrder": 2}]
    real_target = pe._review_target
    pe._review_target = lambda rid=None: (f"https://ticktick.com/webapp/#p/{LIST}/tasks", "list", {"id": LIST})
    pe._api = lambda: Source()
    p = pm.period_for("weekly", DAY)
    OLD, NAME = OLD_WEEKLY, pm.SEC_REVIEW

    def rheld(name, body, *needles, keep=None, tool=rw, p=p, kind="weekly"):
        got = tool.plan(ps.parse_sections(body), p, {})
        st, problems = got.get("status"), got.get("problems") or []
        new = stripped(ps.serialize_sections(got["new"])) if got.get("new") is not None else []
        kept = {n: new.count(n.strip()) >= max(1, stripped(body).count(n.strip())) for n in needles}
        check(f"{kind}.rebuilt mirror.{name}: kept, or refused and named", st in ("ok", "refused")
              and all(kept[n] or (st == "refused" and named(n, problems)) for n in needles)
              and (st == "refused" or not problems), (st, kept, problems))
        if keep is True:
            check(f"{kind}.rebuilt mirror.{name}: kept", st == "ok" and all(kept.values()), (st, kept, problems))
        if keep is False:
            check(f"{kind}.rebuilt mirror.{name}: refused and named", st == "refused" and all(named(n, problems) for n in needles), (st, problems))
        return got

    Source.tasks, Source.broken, Source.reads = BOTH, False, 0
    check("weekly.the fixture holds the mirror", f"##### {NAME}\n" in OLD and box(T2, "Money") in OLD)
    got = rheld("the untouched note", OLD, box(T1, "Process inboxes", True), box(T2, "Money"), "**Inboxes**", OPEN, keep=True)
    check("weekly.the filler did rebuild the mirror from the source", Source.reads >= 2, Source.reads)
    rb = pm.checkbox_tids(ps.find(got["new"], NAME).body)
    check("weekly.the ticks with their state, through the rebuild", rb == {T1: True, T2: False}, rb)
    OUTSIDE = f"- [ ] [Book the dentist](https://ticktick.com/webapp/#p/{'d' * 24}/tasks/{'e' * 24}) "
    for what, line in (("a bold line of his", "**Before Sunday lunch**"), ("a plain line of his", "Call the accountant first"),
                       ("a box of his own", "- [ ] the shoebox of receipts"),
                       ("a second link of his", "[♻️ Open the review](https://ticktick.com/webapp/#p/OTHER/tasks)"),
                       ("a second copy of the filler's link", OPEN), ("a second copy of a column's name", "**Inboxes**"),
                       ("a column the source does not have", "**Parked**"),
                       ("a box of his to a task of another list", OUTSIDE), ("a second box for the same task", box(T2, "Money"))):
        rheld(what, OLD.replace("**Inboxes**\n", "**Inboxes**\n" + line + "\n"), line, keep=False)
    moved = OLD.replace(OPEN, "[♻️ Open the review](https://ticktick.com/webapp/#p/cccccccccccccccccccccccc/tasks)")
    got = rw.plan(ps.parse_sections(moved), p, {})
    check("weekly.rebuilt mirror.the link the filler wrote first is the filler's, wherever it pointed",
          got.get("status") == "ok" and OPEN in stripped(ps.serialize_sections(got["new"])), (got.get("status"), got.get("problems")))
    got = rw.plan(ps.parse_sections(OLD.replace("[Process inboxes]", "[Process inboxes, the paper one too]")), p, {})
    check("weekly.rebuilt mirror.a label he edited is named", got.get("status") == "refused"
          and any("reworded" in x and "the paper one too" in x for x in got.get("problems") or []), (got.get("status"), got.get("problems")))
    got = rw.plan(ps.parse_sections(OLD.replace(box(T2, "Money"), box(T2, "Money") + "owe Ana 50, pay first")), p, {})
    check("weekly.rebuilt mirror.words typed behind a box are named", got.get("status") == "refused"
          and any("owe Ana 50" in x for x in got.get("problems") or []), (got.get("status"), got.get("problems")))
    Source.tasks = [dict(BOTH[0]), dict(BOTH[1], title="Money and taxes")]
    got = rw.plan(ps.parse_sections(OLD), p, {})
    check("weekly.rebuilt mirror.a task renamed at the source is refused, and the message says which of the two it can be",
          got.get("status") == "refused" and any("reworded" in x and "renamed at the source" in x and "Money and taxes" in x for x in got.get("problems") or []),
          (got.get("status"), got.get("problems")))
    # the ticked task was completed at the source (by him, or by the
    # refresh's sweep): the source drops the box, and that is no loss
    for what, tasks in (("the source no longer lists", BOTH[1:]), ("the source lists as done", [dict(BOTH[0], status=2), BOTH[1]])):
        Source.tasks = tasks
        got = rw.plan(ps.parse_sections(OLD), p, {})
        rb = pm.checkbox_tids(ps.find(got["new"], NAME).body) if got.get("new") is not None else None
        check(f"weekly.rebuilt mirror.a box whose task {what} goes with it, the note is not refused",
              got.get("status") == "ok" and rb == {T2: False} and rw.TIER.review_source()["open"] == {T2}, (got.get("status"), got.get("problems"), rb))
    Source.tasks = BOTH[1:]
    got = rw.plan(ps.parse_sections(OLD.replace("[Process inboxes]", "[Process inboxes, and the paper tray, Ana has the key]")), p, {})
    check("weekly.rebuilt mirror.his words on the box of a task that is done are named", got.get("status") == "refused"
          and any("Ana has the key" in x and "no longer open" in x for x in got.get("problems") or []), (got.get("status"), got.get("problems")))
    got = rw.plan(ps.parse_sections(OLD.replace(box(T1, "Process inboxes", True), box(T1, "Process inboxes", True) + "\n" + box(T1, "Process inboxes", True))), p, {})
    check("weekly.rebuilt mirror.the filler wrote one box per task: a second one of a done task is his", got.get("status") == "refused"
          and any("review task lost" in x and T1 in x for x in got.get("problems") or []), (got.get("status"), got.get("problems")))
    gone_title = dict(Source.titles)
    del Source.titles[T1]
    got = rw.plan(ps.parse_sections(OLD), p, {})
    check("weekly.rebuilt mirror.a done task whose title cannot be read is not guessed at", got.get("status") == "refused"
          and any("could not be read" in x and "Process inboxes" in x for x in got.get("problems") or []), (got.get("status"), got.get("problems")))
    Source.titles = gone_title
    emptied = OLD.replace(box(T2, "Money") + "\n", box(T2, "Money") + "\n\n**Closing**\n" + box(T3, "Lock up", True) + "\n")
    got = rw.plan(ps.parse_sections(emptied), p, {})
    check("weekly.rebuilt mirror.a column whose tasks are all done goes too", got.get("status") == "ok", (got.get("status"), got.get("problems")))
    got = rw.plan(ps.parse_sections(emptied.replace("**Closing**\n", "**Closing**\n**Closing**\n")), p, {})
    check("weekly.rebuilt mirror.but only as often as the source has it", got.get("status") == "refused" and named("**Closing**", got.get("problems") or []),
          (got.get("status"), got.get("problems")))
    # a task that is OPEN at the source has to be in the mirror, ticked as it was
    Source.tasks = BOTH
    got = rw.plan(ps.parse_sections(OLD), p, {})
    out = ps.serialize_sections(got["new"])
    src = rw.TIER.review_source()
    probs = rw.verify(ps.parse_sections(OLD), ps.parse_sections(cut(out, box(T2, "Money"))), src)
    check("weekly.rebuilt mirror.verify names an open task the mirror lost", any("review task lost" in x and T2 in x for x in probs), probs)
    probs = rw.verify(ps.parse_sections(OLD), ps.parse_sections(out.replace(box(T1, "Process inboxes", True), box(T1, "Process inboxes"))), src)
    check("weekly.rebuilt mirror.verify names a tick that changed", any("tick changed" in x for x in probs), probs)
    check("weekly.the source is read the way the filler reads it", src["open"] == {T1, T2} and src["list"] == LIST
          and dict(src["columns"]) == {"**Inboxes**": 1, "**Closing**": 1}, src)
    second = OLD + "##### ♻️ Weekly Review\n[my own list](https://x.example/list)\n" + box(T2, "Money") + "\nA second one, mine\n"
    got = rheld("a second review section is his, kept whole", second, "[my own list](https://x.example/list)", "A second one, mine", keep=True)
    check("weekly.rebuilt mirror.and its box is there beside the mirror's", stripped(ps.serialize_sections(got["new"])).count(box(T2, "Money").strip()) == 2)
    # a source that is a TASK: its open subtasks are the boxes
    KIDS = [{"id": T1, "title": "Process inboxes", "parentId": "f" * 24, "projectId": LIST, "status": 0, "sortOrder": 1},
            {"id": T2, "title": "Money", "parentId": "f" * 24, "projectId": LIST, "status": 0, "sortOrder": 2}]
    real_get = pe.cache_store.get
    pe.cache_store.get = lambda key, *a: list(KIDS) if key == "all_tasks" else real_get(key, *a)
    pe._review_target = lambda rid=None: (f"https://ticktick.com/webapp/#p/{LIST}/tasks/{'f' * 24}", "task", {"id": "f" * 24, "projectId": LIST})
    flat = OLD.replace(OPEN, f"[♻️ Open the review](https://ticktick.com/webapp/#p/{LIST}/tasks/{'f' * 24})").replace("\n**Inboxes**\n", "\n")
    got = rheld("a source that is a task, the untouched note", flat, box(T1, "Process inboxes", True), box(T2, "Money"), keep=True)
    rheld("a source that is a task, a line of his", flat.replace(box(T2, "Money"), box(T2, "Money") + "\nCall the accountant first"), "Call the accountant first", keep=False)
    rheld("a source that is a task, a box of another list", flat.replace(box(T2, "Money"), box(T2, "Money") + "\n" + OUTSIDE), OUTSIDE, keep=False)
    KIDS = KIDS[1:]
    got = rw.plan(ps.parse_sections(flat), p, {})
    check("weekly.rebuilt mirror.a subtask that is done goes with its box", got.get("status") == "ok"
          and pm.checkbox_tids(ps.find(got["new"], NAME).body) == {T2: False}, (got.get("status"), got.get("problems")))
    pe.cache_store.get = real_get
    pe._review_target = lambda rid=None: (f"https://ticktick.com/webapp/#p/{LIST}/tasks", "list", {"id": LIST})
    # a source that cannot be read: the filler leaves the mirror alone, so
    # every line of it has to be there
    Source.tasks, Source.broken = BOTH, True
    check("weekly.a source that cannot be read is no source", rw.TIER.review_source() is None)
    rheld("the source cannot be read, his line stays", OLD.replace("**Inboxes**\n", "**Inboxes**\nCall the accountant first\n"),
          "Call the accountant first", box(T1, "Process inboxes", True), keep=True)
    Source.broken = False
    # the monthly and the quarterly: a review section in an old note is his
    for tool, kind, OLD, NAME in ((rm, "monthly", OLD_MONTHLY, pm.SEC_MREVIEW), (rq, "quarterly", OLD_QUARTERLY, pm.SEC_QREVIEW)):
        mine = OLD + "\n" + "\n".join([f"##### {NAME}", OPEN, "", "**Closing**", box(T3, "Lock the studio, keys to Ana", True),
                                       box(T2, "Money"), "Landlord changes in October, new IBAN", ""])
        got = rheld("a review section he typed is kept whole, the filler's mirror beside it", mine, f"##### {NAME}", "**Closing**",
                    box(T3, "Lock the studio, keys to Ana", True), "Landlord changes in October, new IBAN", keep=True, tool=tool, p=pm.period_for(kind, DAY), kind=kind)
        secs = [s for s in got["new"].sections if s.name == NAME]
        check(f"{kind}.the template's mirror is the filler's, his section is the second of the name", len(secs) == 2
              and pm.checkbox_tids(secs[0].body) == {T1: False, T2: False} and pm.checkbox_tids(secs[1].body) == {T3: True, T2: False},
              [s.body for s in secs])
        check(f"{kind}.no review role, no source", tool.TIER.review is None and tool.TIER.review_source() is None)
    pe._review_target = real_target
    pe._api = _no_api
    check("with no source set there is none", rw.TIER.review_source() is None)

    check("nothing reached the network", NET == [], NET[:3])
    check("the run-state path is the stub, and the engine took its sweep file from it",
          script_base.run_path("x") == os.path.join(_TMP, "x") and pe.SWEPT_FILE == os.path.join(_TMP, "tickal_pn_swept.json"), pe.SWEPT_FILE)
    # the run dir is under the temp home, or it is the gate's own scratch dir
    # (TICKAL_RUN_DIR, Makefile `test` / tests/harness.py): either way never
    # Vex's ~/.ticktick_alfred/run
    _run_ok = (str(script_base.RUN_DIR).startswith(_TMP)
               or script_base.RUN_DIR == (os.environ.get("TICKAL_RUN_DIR") or "").strip())
    check("every path the engine writes to is under the temp home (the run dir: that or the gate's scratch)",
          all(str(v).startswith(_TMP) for v in (pe.LOG_FILE, pe.SWEPT_FILE)) and _run_ok,
          (pe.LOG_FILE, pe.SWEPT_FILE, script_base.RUN_DIR))
    print(f"relayout: {P} passed, {F} failed")
    sys.exit(1 if F else 0)
