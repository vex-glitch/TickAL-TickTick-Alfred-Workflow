# ──────────────────────────────────────────────────────────────────────────────
# TickTick Alfred Workflow — Filter Definitions
# ──────────────────────────────────────────────────────────────────────────────
#
# Problem: TickTick's built-in filters are locked inside their app and cannot
#          be read or extended via the API. There is no way to fetch your
#          existing TickTick filters or create new ones through the workflow
#          automatically.
#
# Solution: Define your filters here using the criteria below. Each filter
#           becomes a fully searchable entry in Alfred, applying your chosen
#           conditions across all tasks in real time when selected.
#
# Open this file via Update → Set Filters in Alfred.
#
# Add your filters below. Each filter is a dict with a "name" and criteria.
#
# Available criteria (all optional, combine freely):
#
#   include     — title must contain this string (case-insensitive)
#                 omit field — no title filtering
#                 e.g. "include": "PRJ -"  (matches "PRJ - Website", "PRJ - App", etc.)
#
#   tags        — list: task must have ALL listed tags (AND logic)
#                 omit field — no tag filtering (tagged or untagged both pass)
#                 "untagged" — tasks with no tags at all
#                 "any"      — tasks with at least one tag
#                 e.g. "tags": ["active", "work"]   (must have both)
#                 e.g. "tags": "untagged"
#
#   any_tags    — list: task must have AT LEAST ONE listed tag (OR logic)
#                 omit field — no tag filtering
#                 e.g. "any_tags": ["CRM", "Prepare", "Consultation"]  (any one suffices)
#
#   priority    — 0 = none, 1 = low, 2 = medium, 3 = high
#                 omit field — no priority filtering
#                 e.g. "priority": [2, 3]  (medium or high)
#
#   projects    — list of project/list names (exact match)
#                 omit field — no list filtering (all lists pass)
#                 e.g. "projects": ["Content PL", "Digital Drawing"]
#
#   due         — shorthand date filter, one of:
#                 omit field    — no date filtering
#                 "no_date"     — tasks with no due date
#                 "overdue"     — past due
#                 "today"       — due today
#                 "tomorrow"    — due tomorrow
#                 "next7days"   — due within the next 7 days
#                 "this_week"   — due this week (Mon–Sun)
#                 "next_week"   — due next week (Mon–Sun)
#                 "this_month"  — due this month
#                 "next_month"  — due next month
#                 e.g. "due": "this_week"
#
#   due_before  — custom range end: "today", "tomorrow", "next7days", "next14days"
#   due_after   — custom range start: "today", "tomorrow", "next7days", "next14days"
#                 e.g. "due_after": "today", "due_before": "next7days"
#
#   no_date     — True to show only tasks with no due date (standalone boolean)
#                 e.g. "no_date": True
#
# Example filters:
#
#   {"name": "Active",            "tags": ["active"]},
#   {"name": "High Priority",     "priority": [3]},
#   {"name": "Overdue",           "due": "overdue"},
#   {"name": "No date",           "no_date": True},
#
#   {
#       "name": "Complicated Example",
#       "include": "KM -",
#       "tags": ["active", "review", "waiting"],
#       "priority": [2, 3],
#       "projects": ["Tools", "Standards"],
#       "due_after": "next7days",
#       "due_before": "next14days",
#   },
#
# ──────────────────────────────────────────────────────────────────────────────

FILTERS = [
    {"name": "Active",        "tags": ["active"]},
    {"name": "High Priority", "priority": [3]},
    {"name": "Overdue",       "due": "overdue"},
    {"name": "This Week",     "due": "this_week"},
    {"name": "No Date",       "no_date": True},
    {
        "name": "Work — Urgent",
        "projects": ["Work"],
        "priority": [3],
        "due": "this_week",
    },
]
