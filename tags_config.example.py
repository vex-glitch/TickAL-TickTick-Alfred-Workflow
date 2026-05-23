# ──────────────────────────────────────────────────────────────────────────────
# TickTick Alfred Workflow — Tag Definitions
# ──────────────────────────────────────────────────────────────────────────────
#
# Problem: The TickTick API has no endpoint to list all your tags. The workflow
#          can only discover tags that are currently assigned to at least one
#          active task — meaning new tags or tags used only on completed tasks
#          will never appear in the picker automatically.
#
# Solution: Adding your tags here ensures they are always available in the tag
#           picker, regardless of whether any task currently uses them. This
#           list is merged with tags discovered from your tasks during sync, so
#           you never lose automatically discovered tags either.
#
# Open this file via Update → Set Tags in Alfred.
#
# Add your tags below. These are merged with tags discovered from your tasks
# during sync, so you can include tags that aren't yet assigned to any task.
#
# Format: just a list of tag name strings.
#
# Notes:
#   - Tags are case-sensitive (match exactly how they appear in TickTick)
#   - Tags discovered from your tasks during sync are always included too
#   - Duplicates between this list and synced tags are handled automatically
#   - The order here is the order tags appear in the picker — organise them
#     however makes sense to you. Any tags discovered from tasks that are not
#     in this list will be appended alphabetically at the bottom.
#
# ──────────────────────────────────────────────────────────────────────────────

TAGS = [
    # This is an example list — feel free to delete it and add yours,
    # or just keep adding yours beneath (without #).

    # "🔥CRM",
    # 	"🔥Prepare",
    # 	"🔥Consultation",
    # 	"🔥Ongoing",
    # 	"🔥Lead",
    # "🏁Status",
    # 	"🔥Active",
    # 	"⏭️NextSteps",
    # 	"❓Consider",
    # 	"🚦Waiting",
    # 	"🔮Someday",
    # 	"‼️Attention",
    # "👽People",
    # 	"👽Alice",
    # 	"👽Bob",
    # "📍Places",
    # 	"📍Anywhere",
    # 	"📍Home",
    # 	"📍Office",
    # "🎩Area",
    # 	"1️⃣Work",
    # 	"2️⃣Personal",
    # 	"3️⃣Learning",
]
