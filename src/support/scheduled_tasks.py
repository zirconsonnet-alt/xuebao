from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

from .core import Services
from .db import GroupDatabase


SCHEDULER_STATE_SCOPE = "scheduler"
_RUNTIME_SCHEDULER_JOB_REGISTERED = False


def _get_scheduler():
    from nonebot_plugin_apscheduler import scheduler

    return scheduler


def is_expired_once_schedule(
    task_type: str,
    schedule: str,
    *,
    now: Optional[datetime] = None,
) -> bool:
    if str(task_type).strip() != "once":
        return False

    try:
        scheduled_at = datetime.strptime(str(schedule).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return False

    current_minute = (now or datetime.now()).replace(second=0, microsecond=0)
    return scheduled_at < current_minute


def extract_schedule_message(task: Dict[str, Any]) -> str:
    message = str(task.get("message", "")).strip()
    if message:
        return message
    description = str(task.get("description", "")).strip()
    if ": " in description:
        return description.split(": ", 1)[1].rstrip("...")
    return description


def resolve_scheduler_state_target(
    task_id: str,
    task: Dict[str, Any],
) -> Optional[Tuple[str, str]]:
    callback_id = str(task.get("callback_id", ""))
    task_id = str(task_id)

    if callback_id.startswith("file_organize_") or task_id.startswith("auto_organize_"):
        return Services.File.value, "auto_organize"
    if callback_id.startswith("file_arrange_") or task_id.startswith("auto_arrange_"):
        return Services.File.value, "auto_arrange"
    if callback_id.startswith("wordcloud_daily_") or task_id.startswith("wordcloud_daily_task_"):
        return Services.Wordcloud.value, "daily_wordcloud"
    if callback_id.startswith("schedule_msg_callback_") or task_id.startswith("schedule_msg_"):
        return Services.Schedule.value, task_id
    return None


def build_scheduler_state_record(
    task_id: str,
    task: Dict[str, Any],
    *,
    group_id: Optional[int] = None,
) -> Optional[Tuple[int, str, str, Dict[str, Any]]]:
    target = resolve_scheduler_state_target(task_id, task)
    if target is None:
        return None

    resolved_group_id = group_id if group_id is not None else task.get("group_id")
    if resolved_group_id is None:
        return None

    service_name, entry_key = target
    payload = {
        "task_id": str(task_id),
        "task_type": str(task.get("task_type") or task.get("type") or ""),
        "schedule": str(task.get("schedule", "")),
        "callback_id": str(task.get("callback_id", "")),
        "enabled": bool(task.get("enabled", True)),
        "group_id": int(resolved_group_id),
        "description": str(task.get("description", "")),
    }
    if not payload["task_type"] or not payload["schedule"] or not payload["callback_id"]:
        return None

    if service_name == Services.Schedule.value:
        payload["message"] = extract_schedule_message(task)

    return int(resolved_group_id), service_name, entry_key, payload


def upsert_scheduler_state_entry(
    task_id: str,
    task: Dict[str, Any],
    *,
    group_id: Optional[int] = None,
) -> bool:
    record = build_scheduler_state_record(task_id, task, group_id=group_id)
    if record is None:
        return False

    resolved_group_id, service_name, entry_key, payload = record
    db = GroupDatabase(resolved_group_id)
    try:
        db.upsert_service_state_entry(service_name, SCHEDULER_STATE_SCOPE, entry_key, payload)
    finally:
        db.conn.close()
    return True


def register_runtime_callback(
    task_id: str,
    callback: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    from src.services.reminder import register_reminder_scheduled_callback

    register_reminder_scheduled_callback(task_id, callback)


def unregister_runtime_callback(task_id: str) -> None:
    from src.vendors.nonebot_plugin_reminder.reminder import unregister_scheduled_callback

    unregister_scheduled_callback(task_id)


def get_runtime_task(task_id: str) -> Optional[Dict[str, Any]]:
    from src.services.reminder import get_reminder_scheduled_task_manager

    task = get_reminder_scheduled_task_manager().get_task(task_id)
    return dict(task) if task else None


def list_runtime_tasks_by_group(group_id: int) -> Dict[str, Dict[str, Any]]:
    from src.services.reminder import get_reminder_scheduled_task_manager

    scheduled_task_manager = get_reminder_scheduled_task_manager()

    return {
        task_id: dict(task)
        for task_id, task in scheduled_task_manager.get_tasks_by_group(group_id).items()
    }


def iter_runtime_tasks() -> Dict[str, Dict[str, Any]]:
    from src.services.reminder import get_reminder_scheduled_task_manager

    scheduled_task_manager = get_reminder_scheduled_task_manager()
    return {task_id: dict(task) for task_id, task in scheduled_task_manager.tasks.items()}


def upsert_runtime_task(
    *,
    task_id: str,
    task_type: str,
    schedule: str,
    callback_id: str,
    enabled: bool,
    group_id: Optional[int],
    description: str,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    from src.services.reminder import get_reminder_scheduled_task_manager

    scheduled_task_manager = get_reminder_scheduled_task_manager()
    existing_task = scheduled_task_manager.get_task(task_id)
    if existing_task:
        scheduled_task_manager.update_task(
            task_id,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            group_id=group_id,
            description=description,
            message=message,
        )
    else:
        scheduled_task_manager.add_task(
            task_id=task_id,
            task_type=task_type,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            group_id=group_id,
            description=description,
        )
        if message is not None:
            scheduled_task_manager.update_task(task_id, message=message)

    task = scheduled_task_manager.get_task(task_id) or {}
    return dict(task)


def remove_runtime_task(task_id: str) -> bool:
    from src.services.reminder import get_reminder_scheduled_task_manager

    return get_reminder_scheduled_task_manager().remove_task(task_id)


def register_runtime_scheduler_job() -> None:
    global _RUNTIME_SCHEDULER_JOB_REGISTERED
    if _RUNTIME_SCHEDULER_JOB_REGISTERED:
        return

    async def check_scheduled_tasks():
        from src.services.reminder import check_reminder_scheduled_tasks

        await check_reminder_scheduled_tasks()

    _get_scheduler().add_job(
        check_scheduled_tasks,
        "cron",
        second=30,
        id="scheduled_task_check",
        replace_existing=True,
    )
    _RUNTIME_SCHEDULER_JOB_REGISTERED = True

__all__ = [
    "SCHEDULER_STATE_SCOPE",
    "build_scheduler_state_record",
    "extract_schedule_message",
    "get_runtime_task",
    "is_expired_once_schedule",
    "iter_runtime_tasks",
    "list_runtime_tasks_by_group",
    "register_runtime_callback",
    "register_runtime_scheduler_job",
    "remove_runtime_task",
    "unregister_runtime_callback",
    "resolve_scheduler_state_target",
    "upsert_runtime_task",
    "upsert_scheduler_state_entry",
]
