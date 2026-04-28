from typing import Any, Dict

from .executor import (
    build_scheduled_tool_description,
    build_scheduled_tool_runtime_ids,
    register_scheduled_tool_runtime_callback,
    remove_scheduled_tool_runtime_callback,
)
from src.support.scheduled_tasks import (
    list_runtime_tasks_by_group,
    register_runtime_callback,
    remove_runtime_task,
    upsert_runtime_task,
)

from .models import (
    SCHEDULE_STATE_SCOPE,
    SCHEDULE_TASK_PREFIX,
    ScheduleTaskState,
    ScheduledToolJobState,
)


class ScheduleTaskStore:
    def __init__(self, service: Any):
        self.service = service
        self.group = service.group

    def register_message_callback(self, callback_id: str, message: str) -> None:
        group = self.group

        async def send_message_callback():
            await group.send_msg(f"⏰ 定时提醒：\n{message}")

        register_runtime_callback(callback_id, send_message_callback)

    def extract_task_message(self, task: Dict[str, Any]) -> str:
        message = str(task.get("message", "")).strip()
        if message:
            return message
        description = str(task.get("description", "")).strip()
        if ": " in description:
            return description.split(": ", 1)[1].rstrip("...")
        return description

    def build_task_state(
        self,
        *,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool,
        description: str,
        message: str,
    ) -> ScheduleTaskState:
        return {
            "task_id": task_id,
            "task_type": task_type,
            "schedule": schedule,
            "callback_id": callback_id,
            "enabled": enabled,
            "group_id": self.group.group_id,
            "description": description,
            "message": message,
        }

    def sync_task_state_from_runtime(self) -> None:
        tasks = list_runtime_tasks_by_group(self.group.group_id)
        for task_id, task in tasks.items():
            if not str(task_id).startswith(SCHEDULE_TASK_PREFIX):
                continue
            if self.service.get_state_entry(SCHEDULE_STATE_SCOPE, task_id) is not None:
                continue
            payload = self.build_task_state(
                task_id=task_id,
                task_type=task.get("type", ""),
                schedule=task.get("schedule", ""),
                callback_id=task.get("callback_id", ""),
                enabled=bool(task.get("enabled", True)),
                description=task.get("description", ""),
                message=self.extract_task_message(task),
            )
            self.service.put_state_entry(SCHEDULE_STATE_SCOPE, task_id, payload)

    def list_tasks(self) -> Dict[str, Dict[str, Any]]:
        self.sync_task_state_from_runtime()
        entries = self.service.list_state_entries(SCHEDULE_STATE_SCOPE)
        tasks: Dict[str, Dict[str, Any]] = {}
        for entry_key, value in entries.items():
            if not isinstance(value, dict):
                continue
            task_id = str(value.get("task_id") or entry_key)
            payload = dict(value)
            payload.setdefault("task_kind", "message")
            tasks[task_id] = payload
        tasks.update(self.list_tool_jobs())
        return tasks

    def upsert_task(
        self,
        *,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool,
        description: str,
        message: str,
    ) -> ScheduleTaskState:
        payload = self.build_task_state(
            task_id=task_id,
            task_type=task_type,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            description=description,
            message=message,
        )
        self.service.put_state_entry(SCHEDULE_STATE_SCOPE, task_id, payload)
        upsert_runtime_task(
            task_id=task_id,
            task_type=task_type,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            group_id=self.group.group_id,
            description=description,
            message=message,
        )
        return payload

    def remove_task(self, task_id: str) -> bool:
        removed = remove_runtime_task(task_id)
        self.service.delete_state_entry(SCHEDULE_STATE_SCOPE, task_id)
        return removed

    def build_tool_job_state(
        self,
        *,
        job_id: str,
        task_name: str,
        task_type: str,
        schedule: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_snapshot: Dict[str, Any],
        delivery_mode: str,
        risk_level: str,
        enabled: bool = True,
    ) -> ScheduledToolJobState:
        task_id, callback_id = build_scheduled_tool_runtime_ids(job_id)
        return {
            "job_id": job_id,
            "task_id": task_id,
            "callback_id": callback_id,
            "task_name": task_name,
            "task_kind": "tool",
            "task_type": task_type,
            "schedule": schedule,
            "enabled": enabled,
            "group_id": self.group.group_id,
            "creator_user_id": 0,
            "tool_name": tool_name,
            "tool_args": dict(tool_args or {}),
            "context_snapshot": dict(context_snapshot or {}),
            "description": build_scheduled_tool_description(task_name, tool_name),
            "delivery_mode": delivery_mode,
            "risk_level": risk_level,
        }

    def create_tool_job(
        self,
        *,
        job_id: str,
        creator_user_id: int,
        task_name: str,
        task_type: str,
        schedule: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_snapshot: Dict[str, Any],
        delivery_mode: str,
        risk_level: str,
        enabled: bool = True,
    ) -> ScheduledToolJobState:
        payload = self.build_tool_job_state(
            job_id=job_id,
            task_name=task_name,
            task_type=task_type,
            schedule=schedule,
            tool_name=tool_name,
            tool_args=tool_args,
            context_snapshot=context_snapshot,
            delivery_mode=delivery_mode,
            risk_level=risk_level,
            enabled=enabled,
        )
        payload["creator_user_id"] = int(creator_user_id)
        self.group.db.upsert_scheduled_tool_job(
            job_id=job_id,
            creator_user_id=int(creator_user_id),
            task_name=task_name,
            task_id=payload["task_id"],
            callback_id=payload["callback_id"],
            task_type=task_type,
            schedule=schedule,
            tool_name=tool_name,
            tool_args=tool_args,
            context_snapshot=context_snapshot,
            description=payload["description"],
            delivery_mode=delivery_mode,
            risk_level=risk_level,
            enabled=enabled,
        )
        register_scheduled_tool_runtime_callback(job_id)
        upsert_runtime_task(
            task_id=payload["task_id"],
            task_type=task_type,
            schedule=schedule,
            callback_id=payload["callback_id"],
            enabled=enabled,
            group_id=self.group.group_id,
            description=payload["description"],
        )
        return payload

    def list_tool_jobs(self) -> Dict[str, Dict[str, Any]]:
        jobs = self.group.db.list_scheduled_tool_jobs(
            group_id=self.group.group_id,
            include_disabled=True,
        )
        tasks: Dict[str, Dict[str, Any]] = {}
        for job in jobs:
            task_id = str(job.get("task_id") or job.get("job_id") or "")
            if not task_id:
                continue
            payload = dict(job)
            payload.setdefault("task_kind", "tool")
            tasks[task_id] = payload
        return tasks

    def get_tool_job_by_task_id(self, task_id: str) -> Dict[str, Any] | None:
        job = self.group.db.get_scheduled_tool_job_by_task_id(task_id)
        return dict(job) if job else None

    def set_tool_job_enabled(self, task_id: str, enabled: bool) -> Dict[str, Any] | None:
        job = self.group.db.get_scheduled_tool_job_by_task_id(task_id)
        if not job:
            return None
        self.group.db.set_scheduled_tool_job_enabled(str(job["job_id"]), enabled)
        upsert_runtime_task(
            task_id=str(job["task_id"]),
            task_type=str(job["task_type"]),
            schedule=str(job["schedule"]),
            callback_id=str(job["callback_id"]),
            enabled=enabled,
            group_id=self.group.group_id,
            description=str(job.get("description") or ""),
        )
        job["enabled"] = enabled
        return job

    def remove_tool_job(self, task_id: str) -> bool:
        job = self.group.db.get_scheduled_tool_job_by_task_id(task_id)
        if not job:
            return False
        remove_runtime_task(str(job["task_id"]))
        remove_scheduled_tool_runtime_callback(str(job["job_id"]))
        return self.group.db.delete_scheduled_tool_job(str(job["job_id"]))
