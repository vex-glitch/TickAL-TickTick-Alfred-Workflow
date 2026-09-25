"""The three ♻️ review trees as agreed on 2026-09-25 (the Review Trees page, v2;
tools/stoic_library/review_proposal.md holds Vex's rulings verbatim).

Pure data. A node is (title, children): `title` is the exact TickTick title to
write, markdown links included; `children` a list of nodes. Lines that keep an
existing subtask are matched by their flattened title (rebuild.norm), so a
kept line must read exactly like the live one once its links are flattened;
a reworded line names the live title it replaces in ALIASES.

Doors: kmtrigger:// by UID (never by name: two macros are called YNAB),
TickTick app links on the webapp router the inbox link already proved
(ticktick:///webapp/#p|#t|#f), the v1/show smart lists probed 2026-09-10,
and TickAL Link verbs minted through routine_link.url so an unparsable verb
can never be written.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.abspath(os.path.join(HERE, "..", ".."))
if os.path.join(WF, "src") not in sys.path:
    sys.path.insert(0, os.path.join(WF, "src"))
import routine_link as rl                       # noqa: E402

LIST = "6a268ea18f081f1de80eaeb5"               # 🌅 Routines
PARENT = {"weekly":    "6aa4eaad7c035e06a3686a2f",
          "monthly":   "6aa517f607a3ba2e0339b7bd",
          "quarterly": "6aa520b28f084b1907ea08e2",
          "startup":   "6a9faa51635ed1022425af34",   # the two daily routines,
          "shutdown":  "6a268ea28f081f1de80eb10b"}   # reviewed 2026-09-25 late
# the parents' own kanban column: new subtasks are born beside their parent
COLUMN = {"weekly":    "6aa4f1337c035e06a3687ff7",
          "monthly":   "6aa517bd07a3ba2e0339b7b5",
          "quarterly": "6aa51eac07a3ba2e0339cdce",
          "startup":   "6a268ea18f081f1de80eadd5",
          "shutdown":  "6a268ea18f081f1de80eadd4"}

# last day of the month: probe-verified 2026-09-25 on a throwaway task
# (30 Sep completed -> 31 Oct -> 30 Nov), so February gets its 28th or 29th
REPEAT = {"monthly":   "RRULE:FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=-1",
          "quarterly": "RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=-1"}

KM = {"inboxes":  "9476B133-2F11-4405-BADA-4E58E314C1D0",   # Process Inboxes
      "spark":    "4E7D2C37-C0C3-4B4B-9CCE-952D68E16BE3",
      "eagle":    "97F027F1-84D8-4F4B-A48C-118DE70D4EA3",
      "anybox":   "BD28D179-1B91-4F26-9E26-98B388E42335",
      "money":    "2DC599C6-CDDC-4AE7-8989-731118A89254",   # Money (YNAB and Numbers)
      "numbers":  "6B50A0AB-A585-4A97-BF48-0A55530890AF",
      "ynab":     "5C82A18F-47A0-4768-8D10-78AC43514CB6",
      "crm":      "62AC623E-751E-41B9-ACC9-A684139AA2D2",   # Update CRM
      "content":  "FE82B637-9B78-42F0-B217-FB2AC87E0909",   # Update Content PL
      "drawing":  "C7EE88C3-4027-4524-8878-B5A7D8FB44EA",   # Update Drawing PL
      "downloads": "DDC34222-4219-46A5-8F21-025AF1982292",  # made 2026-09-25
      "obsidian": "C53EBB10-1D6B-4520-A8BA-0EC6BEC9897D",   # made 2026-09-25
      "photos":   "1CD816FB-D18E-405F-B83A-0FA4BBFFB8BC"}   # S - App Invokes-, was linked by name

FILTER = {"status":   "69fed6b260ac110a6914f83f",           # 🚦Status
          "projects": "69fedd25018d510d8510c4c2",           # 💼Projects
          "overdue":  "6a3418f9ba90110c0d077b12",           # ‼Overdue
          "nodate":   "6a5fbd9063dd110397594304"}           # 🕧No date
TAG = {"waiting": "🚦waiting", "someday": "🔮someday"}      # children of 🏁status

INBOX = "ticktick:///webapp/#p/inbox/tasks"
TODAY = "ticktick://v1/show?smartlist=today"
NEXT7 = "ticktick://v1/show?smartlist=next_7_days"
HABITS = "ticktick://habit"


def km(key):
    return f"kmtrigger://macro={KM[key]}"


def tag_url(name):
    b = base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ticktick:///webapp/#t/{b}/tasks"


def filter_url(key):
    return f"ticktick:///webapp/#f/{FILTER[key]}/tasks"


def L(text, url):
    return f"[{text}]({url})"


def A(text, verb, tid="", pid=""):
    """A TickAL Link, round-tripped through the grammar."""
    return L(text, rl.url(verb, tid, pid))


def N(title, *children):
    return (title, list(children))


# ── shared blocks ────────────────────────────────────────────────────────────
def _inboxes(monthly=False):
    email = N(L("Email", km("spark")),
              *([N("Unsubscribe from newly discovered low-value email")] if monthly else []))
    eagle = N(L("Eagle", km("eagle")),
              *([N("Uncategorized and Untagged views")] if monthly else []))
    return N(L("Process my digital inboxes", km("inboxes")),
             email, eagle,
             N(L("TickTick", INBOX)),
             N(L("Anybox", km("anybox"))),
             N(L("Downloads", km("downloads"))),
             N("Collect loose papers"),
             N(L("Obsidian vault inbox", km("obsidian"))))


def _work_weekly():
    return N("Work",
             N(L("Update CRM", km("crm")),
               N("Add any new entries"),
               N("Adjust any old entries")),
             N(L("Update Content PL", km("content")),
               N("Pick material to edit"),
               N("Adjust any edited, posted entries")),
             N(L("Update Drawing PL", km("drawing")),
               N("Pick one idea to draw"),
               N("Adjust any drawn ideas")))


def _work_monthly():
    return N("Work",
             N(L("Update CRM", km("crm")),
               N("Add any new entries"),
               N("Adjust any old entries"),
               N("Cross compare with Eagle"),
               N("Follow up clients from six months ago")),
             N(L("Update Content PL", km("content")),
               N("Pick material to edit"),
               N("Adjust any edited, posted entries"),
               N("Look for candidates for editing in raw"),
               N("Cross compare with Eagle")),
             N(L("Update Drawing PL", km("drawing")),
               N("Pick one idea to draw"),
               N("Adjust any drawn ideas"),
               N("Cross compare with Eagle")),
             N("Check the website and the contact form"),
             N(A("Check how many weeks you are booked out", "view", "crmcal")))


def _hygiene(span):
    """The TickTick pass shared by the weekly and the monthly; `span` is
    "week" or "month" and shapes the calendar and scheduling lines. The
    monthly adds Today's Suggested Tasks (Long Overdue, Postponed) right
    after the Overdue line, the order Vex approved on the page."""
    cal_door = rl.url("view", "calendar")
    sched_door = NEXT7 if span == "week" else cal_door
    return [
        N(L("Overdue: reschedule or drop, all in one go", filter_url("overdue"))),
        *([N(L("Long Overdue and Postponed views: do, split or drop", TODAY))] if span == "month" else []),
        N(L("No date: give it a date or send it to someday", filter_url("nodate"))),
        N(L("Waiting for: chase what others owe you", tag_url(TAG["waiting"]))),
        N(L("Review status filter, clear stale statuses", filter_url("status"))),
        N("Skim through lists",
          N("Assign proper statuses")),
        N(L("Check active projects", filter_url("projects")),
          *([N("Archive completed or inactive projects")] if span == "month" else [])),
        *([N(L("Review Someday", tag_url(TAG["someday"])))] if span == "month" else []),
        N(L(f"Check last {span} and next {span}", cal_door)),
        N(L(f"Schedule next {span} using OKRs and status filter", sched_door)),
    ]


# ── the three trees ──────────────────────────────────────────────────────────
def weekly():
    tid, pid = PARENT["weekly"], LIST
    return [
        N(A("Weekly Review • Start", "routine", "weekly")),
        _inboxes(),
        N(L("Money", km("money")),
          N(A("Check how much money you made this week", "moneysticky")),
          N(L("YNAB", km("ynab")),
            N("Clear and approve transactions"),
            N("Reconcile all accounts"))),
        _work_weekly(),
        N("TickTick",
          N(A("Check OKRs", "view", "okrweekly")),
          *_hygiene("week")),
        N(A("📔 Weekly journal", "journal", "weekly")),
        N(A("Finish Weekly Review", "done", tid, pid)),
    ]


def monthly():
    tid, pid = PARENT["monthly"], LIST
    return [
        N(A("Monthly Review • Start", "routine", "monthly")),
        _inboxes(monthly=True),
        N(L("Money", km("money")),
          N(A("Check how much money you made this month", "moneysticky")),
          N(L("YNAB", km("ynab")),
            N("Clear and approve all transactions"),
            N("Reconcile all accounts"),
            N("Cover overspending before the rollover"),
            N("Move available money to Ready to assign"),
            N("Spend time in insights view"),
            N("Adjust next month targets"),
            N("Assign money to next month"),
            N("Work toward a month ahead")),
          N(L("Numbers", km("numbers")),
            N("Add Income"),
            N("Add Expenses"),
            N("Check Progress"),
            N("Compare forecast to reality, then adjust the forecast"),
            N("Compare to YNAB")),
          N("File the month's receipts")),
        _work_monthly(),
        N("TickTick",
          N("MindSweep"),
          N(f"Check {L('inbox', INBOX)} for mindsweep triggers and act on them"),
          N(A("Check OKRs", "view", "okrmonthly")),
          *_hygiene("month")),
        N(A("📔 Monthly journal", "journal", "monthly")),
        N(A("Finish Monthly Review", "done", tid, pid)),
    ]


def quarterly():
    """The monthly runs FIRST, as its own routine, before the quarterly
    session exists: the monthly's Start quits and relaunches TickTick and
    puts the focus timer on the monthly, which would tear down a running
    quarterly workspace and clash with its timer (review 2026-09-25). So
    line one is the monthly's routine link and line two the quarterly's own
    Start; on a quarter end Vex finishes the monthly, then starts this."""
    tid, pid = PARENT["quarterly"], LIST
    return [
        N(A("Run the Monthly Review first", "routine", "monthly")),
        N(A("Quarterly Review • Start", "routine", "quarterly")),
        N(L("Money", km("money")),
          N(A("Check how much money you made this quarter", "moneysticky")),
          N(L("YNAB: Review Categories", km("ynab"))),
          N("Review recurring charges and subscriptions"),
          N("Sweep bank statements and bills for non-monthly expenses"),
          N(L("Numbers: compare with the same quarter last year", km("numbers")))),
        N("Work",
          N("Pricing review"),
          # no door: 04 Portfolio is a subfolder of every tattoo folder in
          # Eagle, not one place a link can open (Eagle MCP, 2026-09-25)
          N("Portfolio refresh: swap in the best recent pieces"),
          N("Effective hourly rate over the last ten pieces"),
          N("Where new clients came from this quarter")),
        N("TickTick",
          N(A("Check OKRs", "view", "okrquarterly"),
            N(A("Adjust OKRs if needed", "view", "okrcarry"))),
          N(A("Check last quarter and next quarter", "view", "calendar")),
          N("System pass",
            N("Audit recurring tasks"),
            N("Delete dead tags"),
            N(L("Archive dropped habits", HABITS)),
            N("Back up TickTick data"))),
        N(A("📔 Quarterly journal", "journal", "quarterly")),
        N(A("Finish Quarterly Review", "done", tid, pid)),
    ]


def startup():
    """Vex 2026-09-25 (🟢 on the review): the YNAB link by UID (two macros
    are called YNAB), "alligns" spelled right. Everything else as it was."""
    tid, pid = PARENT["startup"], LIST
    return [
        N(A("Startup • Start", "routine", "startup")),
        N(A("Calendar", "view", "calendar"),
          N("Check todays schedule"),
          N("Check next two days tasks"),
          N("Adjust if necessary")),
        N(A("Daily Note", "notesticky", "daily"),
          N("Check yesterdays completed tasks"),
          N(A("Make sure your daily plan aligns with your goals", "view", "okrdaily")),
          N(A("Journal", "journal", "morning"))),
        N(L("YNAB", km("ynab")),
          N("Quick glance to remember where you are at")),
        N(A("Finish Startup", "done", tid, pid)),
    ]


def shutdown():
    """Vex 2026-09-25 (🟢): "Set Tomorrow's MIT" goes (the evening journal's
    🎯 question hands off to the goal picker); the Journal moves to the end
    of the TickTick block, after Plan tomorrow, so the goal is picked after
    tomorrow's calendar and the status filter were looked at; the photos
    macro by UID; the overdue and status-filter lines get their doors."""
    tid, pid = PARENT["shutdown"], LIST
    return [
        N(A("Shutdown • Start", "routine", "shutdown")),
        N(A("CRM", "view", "crmcal"),
          N("Mark session as done",
            N(f"Add {L('photos', km('photos'))} to Content PL")),
          N("Add any new entries"),
          N("Check next week worth of appointments")),
        N(A("Money", "moneysticky"),
          N("Money note",
            N("Make sure all income is entered and all sums are updated")),
          N("YNAB",
            N("Add/approve/review transactions"),
            N("Reconcile all accounts"))),
        N("TickTick",
          N(A("D Note", "notesticky", "daily")),
          N(A("Wrap the day", "view", "calendar"),
            N("Cross off completed tasks"),
            N(L("Reschedule or delete overdue tasks", filter_url("overdue"))),
            N(L("Check in habits", HABITS)),
            N(L("Inbox 0", INBOX)),
            N("Daily notes 0"),
            N("Check completed tasks")),
          N(A("Plan tomorrow", "view", "calendar"),
            N("Open Calendar on Week View"),
            N("Check tomorrows schedule and next 7 days schedule and adjust if necessary"),
            N(L("Check status filter and schedule something if necessary", filter_url("status"))),
            N(A("Check the OKR plan", "view", "okrweekly"))),
          N(A("Journal", "journal", "evening"))),
        N(A("Finish Shutdown", "done", tid, pid)),
    ]


TREES = {"weekly": weekly, "monthly": monthly, "quarterly": quarterly,
         "startup": startup, "shutdown": shutdown}

# a reworded line -> the live title(s) it replaces (flattened, casefolded)
ALIASES = {
    "review status filter, clear stale statuses": ("review status filter",),
    "compare forecast to reality, then adjust the forecast": ("compare forecast to reality",),
    "check last month and next month": ("check last week and next week",),
    "schedule next month using okrs and status filter":
        ("schedule next week using okrs and status filter",),
    "check last quarter and next quarter": ("check last week and next week",),
    # the quarterly's Money block keeps the live YNAB and Numbers subtasks
    # (their ids and completion history) as the single lines the page shows
    "ynab: review categories": ("ynab",),
    "numbers: compare with the same quarter last year": ("numbers",),
    # the startup's typo, kept id
    "make sure your daily plan aligns with your goals": ("make sure your daily plan alligns with your goals",),
}
