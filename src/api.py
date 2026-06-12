"""TickTick Open API v1 client."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from urllib3.util.retry import Retry  # noqa: E402

BASE_URL = "https://api.ticktick.com/open/v1"

# TickTick's Open API throws intermittent 500s (especially GET /project).
# Retry transient server errors with a short backoff before surfacing them.
# Only idempotent methods — retrying POST could create duplicates if the
# first request succeeded server-side before erroring.
_RETRY = Retry(
    total=3,
    backoff_factor=0.5,  # 0.5s, 1s, 2s
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET", "DELETE"],
    raise_on_status=False,
)


def _is_all_day(date_str):
    """True when a date string represents an all-day entry (no specific time).
    Handles:
      - Date-only strings like '2026-05-21'
      - UTC midnight: '2026-05-21T00:00:00+0000'
      - Local midnight stored as UTC (TickTick returns e.g. 'T22:00:00' for UTC+2)
    """
    if not date_str:
        return False
    if len(date_str) < 12:
        return True  # date-only format
    if date_str[11:19] == "00:00:00":
        return True  # UTC midnight
    # Check if the UTC timestamp equals local midnight
    try:
        from datetime import datetime, timezone
        dt_utc = datetime(
            int(date_str[0:4]), int(date_str[5:7]), int(date_str[8:10]),
            int(date_str[11:13]), int(date_str[14:16]), int(date_str[17:19]),
            tzinfo=timezone.utc,
        )
        local = dt_utc.astimezone()
        return local.hour == 0 and local.minute == 0 and local.second == 0
    except Exception:
        return False


class TickTickAPI:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        adapter = HTTPAdapter(max_retries=_RETRY)
        self.session.mount("https://", adapter)

    def create_project(self, name, group_id=None):
        payload = {"name": name, "kind": "TASK"}
        if group_id:
            payload["groupId"] = group_id
        r = self.session.post(f"{BASE_URL}/project", json=payload)
        r.raise_for_status()
        return r.json() if r.text.strip() else {}


    def get_projects(self):
        r = self.session.get(f"{BASE_URL}/project")
        r.raise_for_status()
        return r.json()

    def get_project_data(self, project_id):
        """Returns dict with keys: project, tasks, groups (sections)."""
        r = self.session.get(f"{BASE_URL}/project/{project_id}/data")
        r.raise_for_status()
        return r.json()

    def get_task(self, project_id, task_id):
        r = self.session.get(f"{BASE_URL}/project/{project_id}/task/{task_id}")
        r.raise_for_status()
        return r.json()

    def create_task(self, title, project_id=None, due_date=None, content=None,
                    priority=0, tags=None, column_id=None, parent_id=None, kind=None,
                    start_date=None, repeat_flag=None):
        payload = {"title": title}
        if project_id:
            payload["projectId"] = project_id
        if start_date:
            # startDate + dueDate together define a time span (duration)
            payload["startDate"] = start_date
        if due_date:
            payload["dueDate"]   = due_date
            payload["isAllDay"]  = _is_all_day(due_date) and not start_date
        if content:
            payload["content"] = content
        if priority:
            payload["priority"] = priority
        if tags:
            payload["tags"] = tags
        if column_id:
            payload["columnId"] = column_id
        if parent_id:
            payload["parentId"] = parent_id
        if kind:
            payload["kind"] = kind
        if repeat_flag:
            payload["repeatFlag"] = repeat_flag
        r = self.session.post(f"{BASE_URL}/task", json=payload)
        r.raise_for_status()
        return r.json()

    def complete_task(self, project_id, task_id, task_data=None):
        r = self.session.post(
            f"{BASE_URL}/project/{project_id}/task/{task_id}/complete"
        )
        r.raise_for_status()
        return True

    def update_task(self, task_id, project_id, **fields):
        """Fetch current task, merge changes, post full object.
        TickTick ignores partial updates — full object required to persist.
        Pass field=None to send explicit null (clears the field in TickTick).
        """
        current = self.get_task(project_id, task_id)
        payload = {**current}
        for key, value in fields.items():
            payload[key] = value  # None serialises as JSON null — clears the field
        # Auto-set isAllDay based on date fields
        date_val = fields.get("startDate") or fields.get("dueDate")
        if "startDate" in fields or "dueDate" in fields:
            if date_val is None:
                payload["isAllDay"] = False
            else:
                payload["isAllDay"] = _is_all_day(date_val)
        payload["id"] = task_id
        # Preserve explicit projectId override (for move operations)
        if "projectId" not in fields:
            payload["projectId"] = project_id
        # Moving to a new project: clear columnId — it belongs to the old project
        if "projectId" in fields and fields["projectId"] != project_id:
            payload["columnId"] = None
        r = self.session.post(f"{BASE_URL}/task/{task_id}", json=payload)
        r.raise_for_status()
        return r.json()

    def move_task(self, task_id, from_project_id, to_project_id):
        payload = [{"fromProjectId": from_project_id, "toProjectId": to_project_id, "taskId": task_id}]
        r = self.session.post(f"{BASE_URL}/task/move", json=payload)
        r.raise_for_status()
        return r.json()

    def delete_task(self, project_id, task_id):
        r = self.session.delete(f"{BASE_URL}/project/{project_id}/task/{task_id}")
        r.raise_for_status()
        return True
