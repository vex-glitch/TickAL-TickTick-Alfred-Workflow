#!/usr/bin/env python3
"""
Action dispatcher — called by Alfred after item selection.

Arg format (from Script Filter items):
  open:<url>              → open TickTick deep link
  copy:<url>              → copy to clipboard, print confirmation
  complete:<pid>:<tid>:<title>  → complete task via API, print confirmation
  create:<base64json>     → create task via API, print confirmation
"""
import sys
import os
import json
import base64
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

import config as cfg
from api import TickTickAPI
import cache as cache_store
from dateutil import utc_to_local_display, utc_to_long_display


def _patch_task_cache(tid, **fields):
    """Update specific fields on a task in the all_tasks cache without a full wipe."""
    try:
        cached = cache_store.get("all_tasks")
        if cached is None:
            return
        updated = []
        for t in cached:
            if t.get("id") == tid:
                t = dict(t)
                t.update(fields)
            updated.append(t)
        cache_store.set("all_tasks", updated)
    except Exception:
        cache_store.invalidate("all_tasks")


def main():
    if len(sys.argv) < 2:
        return

    arg = sys.argv[1]

    try:
        if arg.startswith("open:"):
            url = arg[5:]
            subprocess.run(["open", url], check=False)
            # no output → notification node shows nothing

        elif arg.startswith("copy:"):
            url = arg[5:]
            subprocess.run(["pbcopy"], input=url.encode(), check=False)
            task_title = os.environ.get("task_title", "")
            title = f"{task_title} · URL Copied" if task_title else "URL Copied"
            print(f"{title}\n{url}")

        elif arg.startswith("complete:"):
            # complete:projectId:taskId:title
            parts = arg[9:].split(":", 2)
            if len(parts) < 2:
                print("Error: malformed complete arg")
                return
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"

            # Snapshot the task before completing so we can add it to the
            # local completed-tasks log (the Open API doesn't expose completed tasks)
            try:
                all_tasks = cache_store.get("all_tasks") or []
                snap = next((t for t in all_tasks if t["id"] == tid), None)
                if snap:
                    from datetime import datetime, timezone
                    snap = dict(snap)
                    snap["status"] = 2
                    snap["completedTime"] = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S+0000"
                    )
                    completed = cache_store.get("completed_tasks") or []
                    completed = [t for t in completed if t.get("id") != tid]
                    completed.insert(0, snap)
                    cache_store.set("completed_tasks", completed[:200])
            except Exception:
                pass

            api = TickTickAPI(cfg.get_token())
            api.complete_task(pid, tid)
            # Remove task from all_tasks in-place (no full cache wipe)
            try:
                cached = cache_store.get("all_tasks")
                if cached is not None:
                    cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} completed")

        elif arg.startswith("attr_date:"):
            # attr_date:projectId:taskId:isoDate
            raw = arg[10:]
            parts = raw.split(":", 2)
            pid, tid, due = parts[0], parts[1], parts[2]

            # Snapshot old date before overwriting (for "rescheduled" notification)
            had_date = os.environ.get("has_date", "0") == "1"
            old_due = None
            if had_date:
                try:
                    all_tasks = cache_store.get("all_tasks") or []
                    snap = next((t for t in all_tasks if t["id"] == tid), None)
                    if snap:
                        old_due = snap.get("dueDate") or snap.get("startDate")
                except Exception:
                    pass

            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, startDate=due, dueDate=due)
            _patch_task_cache(tid, startDate=due, dueDate=due)

            task_title = os.environ.get("task_title", "Task")
            verb = "Rescheduled" if had_date else "Scheduled"
            new_display = utc_to_long_display(due)
            if had_date and old_due:
                old_display = utc_to_long_display(old_due)
                print(f"{verb} · {task_title}\n🟢 {new_display}\n🔴 {old_display}")
            else:
                print(f"{verb} · {task_title}\n{new_display}")

        elif arg.startswith("attr_cleardate:"):
            # attr_cleardate:projectId:taskId
            raw = arg[15:]
            pid, tid = raw.split(":", 1)
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, startDate=None, dueDate=None)
            _patch_task_cache(tid, startDate=None, dueDate=None)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} · Unscheduled")

        elif arg.startswith("attr_priority:"):
            # attr_priority:projectId:taskId:priorityInt
            raw = arg[14:]
            parts = raw.split(":", 2)
            pid, tid, pval = parts[0], parts[1], int(parts[2])
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, priority=pval)
            _patch_task_cache(tid, priority=pval)
            labels = {0: "None", 1: "Low", 3: "Medium", 5: "High"}
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} → {labels.get(pval, pval)}")

        elif arg.startswith("attr_tag:"):
            # attr_tag:projectId:taskId:tagName
            raw = arg[9:]
            parts = raw.split(":", 2)
            pid, tid, tag = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            # Fetch current task to preserve existing tags
            try:
                task = api.get_task(pid, tid)
                existing = task.get("tags") or []
            except Exception:
                existing = []
            merged = list(dict.fromkeys(existing + [tag]))  # deduplicated, order preserved
            api.update_task(tid, pid, tags=merged)
            _patch_task_cache(tid, tags=merged)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} tagged #{tag}")

        elif arg.startswith("attr_tags_multi:"):
            # attr_tags_multi:projectId:taskId:tag1,tag2,tag3
            raw = arg[16:]
            parts = raw.split(":", 2)
            pid, tid, tags_csv = parts[0], parts[1], parts[2]
            new_tags = [t.strip() for t in tags_csv.split(",") if t.strip()]
            api = TickTickAPI(cfg.get_token())
            current = api.get_task(pid, tid)
            existing = current.get("tags") or []
            merged = list(dict.fromkeys(existing + new_tags))
            api.update_task(tid, pid, tags=merged)
            _patch_task_cache(tid, tags=merged)
            task_title = os.environ.get("task_title", "Task")
            tags_display = "  ".join(f"#{t}" for t in new_tags)
            print(f"{task_title} tagged {tags_display}")

        elif arg.startswith("attr_tag_remove:"):
            # attr_tag_remove:projectId:taskId:tagName
            raw = arg[16:]
            parts = raw.split(":", 2)
            pid, tid, tag = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            current = api.get_task(pid, tid)
            updated = [t for t in (current.get("tags") or []) if t != tag]
            api.update_task(tid, pid, tags=updated)
            _patch_task_cache(tid, tags=updated)
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} tag #{tag} removed")

        elif arg.startswith("attr_tag_clear:"):
            # attr_tag_clear:projectId:taskId
            raw = arg[15:]
            pid, tid = raw.split(":", 1)
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, tags=[])
            _patch_task_cache(tid, tags=[])
            task_title = os.environ.get("task_title", "Task")
            print(f"{task_title} — all tags removed")

        elif arg.startswith("attr_move:"):
            # attr_move:oldProjectId:taskId:newProjectId
            raw = arg[10:]
            parts = raw.split(":", 2)
            old_pid, tid, new_pid = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            api.move_task(tid, old_pid, new_pid)
            task_title = os.environ.get("task_title", "Task")
            projects = cache_store.get("projects") or []
            new_list = next((p["name"] for p in projects if p["id"] == new_pid), "")
            _patch_task_cache(tid,
                              projectId=new_pid,
                              _projectId=new_pid,
                              _projectName=new_list,
                              columnId=None,
                              _columnName="",
                              parentId=None)
            print(f"{task_title} moved to {new_list}" if new_list else f"{task_title} moved")

        elif arg.startswith("attr_rename:"):
            # attr_rename:projectId:taskId:newTitle
            raw = arg[12:]
            parts = raw.split(":", 2)
            pid, tid, new_title = parts[0], parts[1], parts[2]
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, title=new_title)
            _patch_task_cache(tid, title=new_title)
            print(f"{new_title} renamed")

        elif arg.startswith("uncomplete:"):
            # uncomplete:projectId:taskId:title
            parts = arg[11:].split(":", 2)
            if len(parts) < 2:
                print("Error: malformed uncomplete arg")
                return
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"
            api = TickTickAPI(cfg.get_token())
            api.update_task(tid, pid, status=0)
            # Remove from local completed log and restore to all_tasks in-place
            try:
                completed = cache_store.get("completed_tasks") or []
                snap = next((t for t in completed if t.get("id") == tid), None)
                completed = [t for t in completed if t.get("id") != tid]
                cache_store.set("completed_tasks", completed)
                cached = cache_store.get("all_tasks")
                if cached is not None and snap is not None:
                    restored = dict(snap)
                    restored["status"] = 0
                    restored.pop("completedTime", None)
                    cached = [t for t in cached if t.get("id") != tid]
                    cached.append(restored)
                    cache_store.set("all_tasks", cached)
                elif cached is None:
                    cache_store.invalidate("all_tasks")
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} uncompleted")

        elif arg.startswith("attr_delete:"):
            # attr_delete:projectId:taskId:title
            raw = arg[12:]
            parts = raw.split(":", 2)
            pid, tid = parts[0], parts[1]
            title = parts[2] if len(parts) > 2 else "Task"
            api = TickTickAPI(cfg.get_token())
            api.delete_task(pid, tid)
            try:
                cached = cache_store.get("all_tasks")
                if cached is not None:
                    cache_store.set("all_tasks", [t for t in cached if t.get("id") != tid])
            except Exception:
                cache_store.invalidate("all_tasks")
            print(f"{title} deleted")

        elif arg.startswith("create_project_meta:"):
            # create_project_meta:<base64 {name, tag, emoji}>
            # Creates a project list in the Projects folder + a linked meta
            # task in the Project Meta Tasks list, tagged with the area tag.
            raw = arg[20:]
            payload = json.loads(base64.b64decode(raw))
            name  = payload.get("name", "").strip()
            tag   = payload.get("tag", "")
            emoji = payload.get("emoji", "")
            if not name:
                print("Error: project has no name")
                return

            folder_id = os.environ.get("projects_folder_id") or "69fcaeb9bac7d10a6914dfca"
            meta_list = os.environ.get("project_meta_list_id") or "6a2ac922f6161196c5d02531"

            api = TickTickAPI(cfg.get_token())
            list_name = f"💼P • {name} {emoji}".rstrip()
            proj = api.create_project(list_name, group_id=folder_id)
            pid = proj.get("id") if isinstance(proj, dict) else None
            if not pid:
                cache_store.invalidate("projects")
                print("Error: list created but no id returned — meta task skipped")
                return

            url = f"ticktick:///webapp/#p/{pid}/tasks"
            task = api.create_task(
                title=f"PM • [{name}]({url}) 🗺️",
                project_id=meta_list,
                tags=[tag] if tag else None,
            )

            # Update caches in-place
            try:
                projects_cache = cache_store.get("projects")
                if projects_cache is not None:
                    projects_cache.append(proj)
                    cache_store.set("projects", projects_cache)
                if task and task.get("id"):
                    meta_name = ""
                    if projects_cache:
                        meta_name = next((p.get("name", "") for p in projects_cache
                                          if p.get("id") == meta_list), "")
                    entry = dict(task)
                    entry["_projectId"]   = meta_list
                    entry["_projectName"] = meta_name
                    entry["_columnName"]  = ""
                    cached_tasks = cache_store.get("all_tasks") or []
                    cached_tasks.append(entry)
                    cache_store.set("all_tasks", cached_tasks)
            except Exception:
                cache_store.invalidate("projects")
                cache_store.invalidate("all_tasks")

            print(f"💼 {name} created · {tag}")

        elif arg.startswith("create_list:"):
            raw = arg[12:]
            payload = json.loads(base64.b64decode(raw))
            name = payload.get("name", "").strip()
            if not name:
                print("Error: list has no name")
                return
            api = TickTickAPI(cfg.get_token())
            api.create_project(name, group_id=payload.get("groupId"))
            cache_store.invalidate("projects")
            cache_store.invalidate("all_tasks")
            print(f"{name} created")

        elif arg.startswith("create:"):
            raw = arg[7:]
            payload = json.loads(base64.b64decode(raw))
            title = payload.get("title", "").strip()
            if not title:
                print("Error: task has no title")
                return
            api = TickTickAPI(cfg.get_token())
            result = api.create_task(
                title=title,
                project_id=payload.get("projectId"),
                due_date=payload.get("dueDate"),
                start_date=payload.get("startDate"),
                content=payload.get("content"),
                priority=payload.get("priority", 0),
                tags=payload.get("tags"),
                column_id=payload.get("columnId", None),
                parent_id=payload.get("parentId"),
                kind=payload.get("kind"),
                repeat_flag=payload.get("repeatFlag"),
            )
            # Update all_tasks in-place so searches work immediately after create
            proj_id = payload.get("projectId", "")
            if result and result.get("id"):
                try:
                    projects_cache = cache_store.get("projects") or []
                    proj = next((p for p in projects_cache if p["id"] == proj_id), None)
                    new_entry = dict(result)
                    new_entry["_projectId"]   = proj_id or "inbox"
                    new_entry["_projectName"] = proj.get("name", "") if proj else ""
                    new_entry["_columnName"]  = ""
                    cached_tasks = cache_store.get("all_tasks") or []
                    cached_tasks = [t for t in cached_tasks if t.get("id") != result["id"]]
                    cached_tasks.append(new_entry)
                    cache_store.set("all_tasks", cached_tasks)

                    # Inject into all_notes for any kind=NOTE item (any project)
                    if result.get("kind") == "NOTE":
                        all_notes = cache_store.get("all_notes") or []
                        all_notes = [n for n in all_notes if n.get("id") != result["id"]]
                        all_notes.insert(0, new_entry)
                        cache_store.set("all_notes", all_notes)
                except Exception:
                    cache_store.invalidate("all_tasks")  # fallback

            notif = payload.get("_notif_text") or f"Task added to {payload.get('listName') or 'Inbox'}"
            print(notif)

        else:
            # Fallback: treat as raw URL
            subprocess.run(["open", arg], check=False)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
