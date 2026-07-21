#!/usr/bin/env python3
"""
move_action.py - Alfred Run Script
Moves a task to a different list, section, or parent task.

$1 format (built by Arg and Vars node: {task_list_id}:{task_id}:{query}):
  old_pid:tid:list:{new_pid}             → move to a different list
  old_pid:tid:section:{list_id}:{col_id} → move to a section (cross-list if needed)
  old_pid:tid:task:{parent_pid}:{p_tid}  → make subtask of another task
"""
import sys
import os
import json

# ── script_base bootstrap ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from script_base import bootstrap, reopen_actions, run_path
bootstrap()

import config as cfg
import cache as cache_store
from api import TickTickAPI


def _list_name(pid):
    projects = cache_store.get("projects") or []
    return next((p["name"] for p in projects if p["id"] == pid), "")


def _output(msg, new_list_id, new_tid=None):
    variables = {"task_list_id": new_list_id}
    if new_tid:
        variables["task_id"] = new_tid
    print(json.dumps({
        "alfredworkflow": {
            "arg": msg,
            "variables": variables,
        }
    }))
    reopen_actions(new_list_id, new_tid or os.environ.get("task_id", ""))


def _update_temp(pid, tid):
    try:
        with open("/tmp/ticktick_reattribute.txt", "w") as _f:
            _f.write(f"{pid}:{tid}")
    except Exception:
        pass


# all_tasks + per-list project_data mirror - dispatch's helper also purges the
# task from the OLD list's cache and injects it into the new one on a move.
from dispatch import _patch_task_cache


def _buffer_lines():
    try:
        with open(run_path("tickal_buffer.txt")) as f:
            return [ln.strip().split(":", 1) for ln in f
                    if ln.strip() and ":" in ln]
    except OSError:
        return []


def _buffer_move(api, rest):
    """🧺 BUFFER sentinel: apply the picked target to every buffered task -
    the move picker runs unchanged for the buffer, only the executor loops
    (delete_action/priority_action pattern; this branch was MISSING and the
    API got literal 'BUFFER' ids → empty-200 → 'Expecting value' JSON error).
    Buffer stays intact afterwards (attr_move parity)."""
    lines = _buffer_lines()
    if not lines:
        print("🅿️ Buffer is empty")
        return
    done = 0
    if rest.startswith("list:"):
        new_pid = rest[5:]
        lname = _list_name(new_pid)
        for bpid, btid in lines:
            try:
                api.move_task(btid, bpid, new_pid)
                _patch_task_cache(btid, projectId=new_pid, _projectId=new_pid,
                                  _projectName=lname, columnId=None,
                                  _columnName="", parentId=None)
                done += 1
            except Exception:
                pass
        print(f"🅿️ {done} moved to {lname or 'list'}")
    elif rest.startswith("section:"):
        _, list_id, col_id = rest.split(":", 2)
        lname = _list_name(list_id)
        for bpid, btid in lines:
            try:
                live = api.get_task(bpid, btid)   # BEFORE any move (race)
                if list_id != bpid:
                    api.move_task(btid, bpid, list_id)
                api.update_task(btid, list_id, current=live, columnId=col_id)
                _patch_task_cache(btid, projectId=list_id, _projectId=list_id,
                                  _projectName=lname, columnId=col_id,
                                  parentId=None)
                done += 1
            except Exception:
                pass
        print(f"🅿️ {done} moved to the section")
    elif rest.startswith("task:"):
        _, parent_pid, parent_tid = rest.split(":", 2)
        import focus_subtasks as fsub
        all_tasks = cache_store.get("all_tasks") or []
        pname = next((t.get("title", "") for t in all_tasks
                      if t["id"] == parent_tid), "the task")
        lname = _list_name(parent_pid)
        skipped = 0
        for bpid, btid in lines:
            # a buffered parent target / ancestor would loop - and the
            # server ACCEPTS parent cycles (live-verified 2026-07-21)
            if btid == parent_tid or fsub.would_cycle(
                    parent_tid, btid, cache_store.find_task):
                skipped += 1
                continue
            try:
                # live BEFORE the move: a GET from the new project right
                # after move_task races replication (empty-200 → JSON error)
                live = api.get_task(bpid, btid)
                fields = {"parentId": parent_tid}
                if parent_pid != bpid:
                    api.move_task(btid, bpid, parent_pid)
                    fields["columnId"] = None
                api.update_task(btid, parent_pid, current=live, **fields)
                _patch_task_cache(btid, projectId=parent_pid,
                                  _projectId=parent_pid, _projectName=lname,
                                  parentId=parent_tid, columnId=None,
                                  _columnName="")
                done += 1
            except Exception:
                pass
        msg = f"🅿️ {done} → subtasks of {pname[:30]}"
        if skipped:
            msg += f" · {skipped} skipped"
        print(msg)
    else:
        print(f"Error: unexpected buffer move target: {rest!r}")


def main():
    arg        = sys.argv[1] if len(sys.argv) > 1 else ""
    task_title = os.environ.get("task_title", "Task")

    try:
        old_pid, tid, rest = arg.split(":", 2)
    except ValueError:
        print(f"Error: unexpected arg format: {arg!r}")
        return

    # Restore from temp file if env vars were empty
    if not old_pid or not tid:
        try:
            with open("/tmp/ticktick_reattribute.txt") as _f:
                parts = _f.read().strip().split(":", 1)
                if len(parts) == 2:
                    old_pid, tid = parts[0], parts[1]
        except Exception:
            pass

    if not old_pid or not tid:
        print("Error: missing task context (no list_id or task_id)")
        return

    api = TickTickAPI(cfg.get_token())

    try:
        # ── 🧺 Buffer: the sentinel loops every buffered task ────────────────
        if tid == "BUFFER":
            _buffer_move(api, rest)
            return

        # ── List move ─────────────────────────────────────────────────────────
        if rest.startswith("list:"):
            new_pid  = rest[5:]
            api.move_task(tid, old_pid, new_pid)
            lname = _list_name(new_pid)
            _patch_task_cache(tid,
                              projectId=new_pid,
                              _projectId=new_pid,
                              _projectName=lname,
                              columnId=None,
                              _columnName="",
                              parentId=None)
            msg = f"{task_title} moved to {lname}" if lname else f"{task_title} moved"
            _update_temp(new_pid, tid)
            _output(msg, new_pid)

        # ── Section move ──────────────────────────────────────────────────────
        elif rest.startswith("section:"):
            _, list_id, col_id = rest.split(":", 2)
            # live BEFORE any move: a GET from the new project right after
            # move_task races replication (empty-200 → 'Expecting value')
            live = api.get_task(old_pid, tid)
            if list_id != old_pid:
                # Cross-list: move first, then set column
                api.move_task(tid, old_pid, list_id)
            api.update_task(tid, list_id, current=live, columnId=col_id)
            # Resolve section name for notification
            section_name = ""
            pdata = cache_store.get(f"project_data_{list_id}")
            if pdata:
                for col in pdata.get("columns", []) or []:
                    if col.get("id") == col_id:
                        section_name = col.get("name", "").strip()
                        break
            lname = _list_name(list_id)
            _patch_task_cache(tid,
                              projectId=list_id,
                              _projectId=list_id,
                              _projectName=lname,
                              columnId=col_id,
                              _columnName=section_name,
                              parentId=None)
            dest = f"{section_name}" if not lname else (f"{lname} › {section_name}" if section_name else lname)
            msg  = f"{task_title} moved to {dest}" if dest else f"{task_title} moved"
            _update_temp(list_id, tid)
            _output(msg, list_id)

        # ── Parent task (make subtask) ─────────────────────────────────────────
        elif rest.startswith("task:"):
            _, parent_pid, parent_tid = rest.split(":", 2)
            import focus_subtasks as fsub
            if parent_tid == tid or fsub.would_cycle(
                    parent_tid, tid, cache_store.find_task):
                print(f"Error: {task_title} can't be its own ancestor")
                return
            # Resolve parent title before any mutation
            all_tasks    = cache_store.get("all_tasks") or []
            parent_title = next((t.get("title", "") for t in all_tasks if t["id"] == parent_tid), "")
            # live BEFORE any move: a GET from the new project right after
            # move_task races replication (empty-200 → 'Expecting value')
            live = api.get_task(old_pid, tid)
            fields = {"parentId": parent_tid}
            if parent_pid != old_pid:
                # Cross-list: move task to parent's list first
                api.move_task(tid, old_pid, parent_pid)
                fields["columnId"] = None
            api.update_task(tid, parent_pid, current=live, **fields)
            lname = _list_name(parent_pid)
            _patch_task_cache(tid,
                              projectId=parent_pid,
                              _projectId=parent_pid,
                              _projectName=lname,
                              parentId=parent_tid,
                              columnId=None,
                              _columnName="")
            msg = (f"{task_title} → subtask of {parent_title}"
                   if parent_title else f"{task_title} added as subtask")
            _update_temp(parent_pid, tid)
            _output(msg, parent_pid)

        # ── Backward compat: bare pid (old list-move format) ─────────────────
        else:
            new_pid = rest
            api.move_task(tid, old_pid, new_pid)
            lname = _list_name(new_pid)
            _patch_task_cache(tid,
                              projectId=new_pid,
                              _projectId=new_pid,
                              _projectName=lname,
                              columnId=None,
                              _columnName="",
                              parentId=None)
            msg = f"{task_title} moved to {lname}" if lname else f"{task_title} moved"
            _update_temp(new_pid, tid)
            _output(msg, new_pid)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
