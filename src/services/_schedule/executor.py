from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import nonebot

from src.support.core import tool_registry
from src.support.db import GroupDatabase
from src.support.group import group_context_factory
from src.support.scheduled_tasks import (
    get_runtime_task,
    is_expired_once_schedule,
    register_runtime_callback,
    remove_runtime_task,
    unregister_runtime_callback,
    upsert_runtime_task,
)

from .capabilities import get_tool_schedule_capability
from .models import SCHEDULE_TOOL_CALLBACK_PREFIX, SCHEDULE_TOOL_TASK_PREFIX


def build_scheduled_tool_runtime_ids(job_id: str) -> Tuple[str, str]:
    normalized_job_id = str(job_id).strip()
    return (
        f"{SCHEDULE_TOOL_TASK_PREFIX}{normalized_job_id}",
        f"{SCHEDULE_TOOL_CALLBACK_PREFIX}{normalized_job_id}",
    )


def build_scheduled_tool_description(task_name: str, tool_name: str) -> str:
    normalized_name = str(task_name or tool_name or "未命名任务").strip()
    normalized_tool = str(tool_name or "unknown_tool").strip()
    return f"{normalized_name}: 调用 {normalized_tool}"


def build_schedule_context_snapshot(
    context: Dict[str, Any] | None,
) -> Dict[str, Any]:
    context = context or {}
    return {
        "message": str(context.get("message") or ""),
        "message_id": int(context.get("message_id") or 0),
        "self_id": int(context.get("self_id") or 0),
        "reply_text": str(context.get("reply_text") or ""),
        "reply_message_id": int(context.get("reply_message_id") or 0),
        "image_registry": dict(context.get("image_registry") or {}),
        "video_registry": dict(context.get("video_registry") or {}),
    }


def _iter_persisted_group_ids() -> list[int]:
    root = Path("data") / "group_management"
    if not root.exists():
        return []

    group_ids = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not (child / "group_data.db").exists():
            continue
        try:
            group_ids.append(int(child.name))
        except ValueError:
            continue
    return sorted(group_ids)


def _get_service_manager():
    from src.services.registry import service_manager

    return service_manager


async def _resolve_member_role(group_id: int, user_id: int) -> str:
    try:
        bot = nonebot.get_bot()
        member_info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
        return str(member_info.get("role") or "member").strip().lower() or "member"
    except Exception:
        return "member"


async def _build_execution_context(job: Dict[str, Any]) -> Dict[str, Any]:
    context_snapshot = dict(job.get("context_snapshot") or {})
    group_id = int(job.get("group_id") or 0)
    user_id = int(job.get("creator_user_id") or 0)
    group = group_context_factory.get_group(group_id) if group_id > 0 else None
    context_snapshot["group_id"] = group_id
    context_snapshot["user_id"] = user_id
    context_snapshot["service_manager"] = _get_service_manager()
    context_snapshot["group_db"] = getattr(group, "db", None)
    context_snapshot["_scheduled_job_id"] = str(job.get("job_id") or "")
    context_snapshot["_scheduled_run_key"] = datetime.now().strftime("%Y%m%d%H%M")
    context_snapshot["member_role"] = await _resolve_member_role(group_id, user_id)
    return context_snapshot


async def _deliver_job_result(job: Dict[str, Any], result: Dict[str, Any]) -> None:
    group_id = int(job.get("group_id") or 0)
    if group_id <= 0:
        return

    task_name = str(job.get("task_name") or job.get("tool_name") or "未命名任务").strip()
    delivery_mode = str(job.get("delivery_mode") or "render_message").strip()
    success = bool(result.get("success", False))
    message = str(result.get("message") or "").strip()
    group = group_context_factory.get_group(group_id)
    at_user_id = int(job.get("creator_user_id") or 0) or None

    if success and delivery_mode == "self_output":
        return

    if success:
        if delivery_mode == "silent":
            return
        text = message or f"工具 {job.get('tool_name')} 执行完成"
        await group.send_msg(
            f"⏰ 定时任务「{task_name}」执行结果：\n{text}",
            at_user_id=at_user_id,
        )
        return

    error_text = message or "未知错误"
    await group.send_msg(
        f"⏰ 定时任务「{task_name}」执行失败：\n{error_text}",
        at_user_id=at_user_id,
    )


async def execute_scheduled_tool_job(job_id: str) -> None:
    normalized_job_id = str(job_id).strip()
    if not normalized_job_id:
        return

    db = None
    job = None
    result: Dict[str, Any] = {"success": False, "message": "任务不存在"}
    try:
        for group_id in _iter_persisted_group_ids():
            db = GroupDatabase(group_id)
            maybe_job = db.get_scheduled_tool_job(normalized_job_id)
            if maybe_job:
                job = maybe_job
                break
            db.conn.close()
            db = None

        if not job or db is None:
            return

        context = await _build_execution_context(job)
        result = await tool_registry.execute_tool(
            str(job.get("tool_name") or ""),
            dict(job.get("tool_args") or {}),
            context,
        )
        db.record_scheduled_tool_run(
            job_id=normalized_job_id,
            status="succeeded" if result.get("success", False) else "failed",
            result=result,
            error_text="" if result.get("success", False) else str(result.get("message") or ""),
        )
        if str(job.get("task_type") or "").strip() == "once":
            db.set_scheduled_tool_job_enabled(normalized_job_id, False)
        await _deliver_job_result(job, result)
    except Exception as exc:
        if db is not None:
            db.record_scheduled_tool_run(
                job_id=normalized_job_id,
                status="failed",
                result=result,
                error_text=str(exc),
            )
        if job:
            await _deliver_job_result(
                job,
                {"success": False, "message": f"执行异常: {exc}"},
            )
    finally:
        if db is not None:
            db.conn.close()


def register_scheduled_tool_runtime_callback(job_id: str) -> str:
    task_id, callback_id = build_scheduled_tool_runtime_ids(job_id)

    async def _callback() -> None:
        await execute_scheduled_tool_job(job_id)

    register_runtime_callback(callback_id, _callback)
    return callback_id


def remove_scheduled_tool_runtime_callback(job_id: str) -> None:
    _, callback_id = build_scheduled_tool_runtime_ids(job_id)
    unregister_runtime_callback(callback_id)


def restore_scheduled_tool_jobs_to_runtime() -> Tuple[int, int]:
    restored = 0
    pruned = 0

    for group_id in _iter_persisted_group_ids():
        db = GroupDatabase(group_id)
        try:
            jobs = db.list_scheduled_tool_jobs(group_id=group_id, include_disabled=True)
            for job in jobs:
                job_id = str(job.get("job_id") or "").strip()
                task_id = str(job.get("task_id") or "").strip()
                callback_id = str(job.get("callback_id") or "").strip()
                task_type = str(job.get("task_type") or "").strip()
                schedule = str(job.get("schedule") or "").strip()
                if not job_id or not task_id or not callback_id or not task_type or not schedule:
                    continue

                if bool(job.get("enabled", True)) and is_expired_once_schedule(task_type, schedule):
                    remove_runtime_task(task_id)
                    db.set_scheduled_tool_job_enabled(job_id, False)
                    pruned += 1
                    continue

                register_scheduled_tool_runtime_callback(job_id)
                existing_task = get_runtime_task(task_id)
                upsert_runtime_task(
                    task_id=task_id,
                    task_type=task_type,
                    schedule=schedule,
                    callback_id=callback_id,
                    enabled=bool(job.get("enabled", True)),
                    group_id=group_id,
                    description=str(job.get("description") or ""),
                )
                if not existing_task:
                    restored += 1
        finally:
            db.conn.close()

    return restored, pruned


def infer_scheduled_tool_metadata(tool_name: str) -> Dict[str, Any]:
    tool = tool_registry.get_tool(tool_name)
    capability = get_tool_schedule_capability(tool_name, tool=tool)
    return {
        "delivery_mode": capability.get("delivery_mode", "render_message"),
        "risk_level": capability.get("risk_level", "normal"),
    }
