from datetime import datetime, timedelta
from typing import Any, Dict
import uuid

from src.services._schedule import (
    ScheduleTaskStore,
    build_schedule_context_snapshot,
    build_task_list_message,
    build_task_summary_message,
    infer_scheduled_tool_metadata,
    validate_schedule,
)
from src.services._schedule.capabilities import prepare_tool_arguments_for_schedule
from src.services.base import BaseService, config_property, service_action
from src.support.core import CreateReminderInput, EmptyInput, Services, ai_tool, tool_registry
from src.support.group import wait_for


class ScheduleService(BaseService):
    """定时服务 - 管理定时消息发送任务"""
    service_type = Services.Schedule
    _TASK_STATE_SCOPE = "scheduler"
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    def __init__(self, group):
        super().__init__(group)
        self._task_store = ScheduleTaskStore(self)

    def _register_message_callback(self, task_id: str, message: str):
        self._task_store.register_message_callback(task_id, message)

    def _extract_task_message(self, task: Dict[str, Any]) -> str:
        return self._task_store.extract_task_message(task)

    def _build_task_state(
        self,
        *,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool,
        description: str,
        message: str,
    ) -> Dict[str, Any]:
        return self._task_store.build_task_state(
            task_id=task_id,
            task_type=task_type,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            description=description,
            message=message,
        )

    def _sync_task_state_from_vendor(self) -> None:
        self._task_store.sync_task_state_from_runtime()

    def _list_scheduler_tasks(self) -> Dict[str, Dict[str, Any]]:
        return self._task_store.list_tasks()

    def _sync_scheduler_task(
        self,
        *,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool,
        description: str,
        message: str,
    ) -> Dict[str, Any]:
        return self._task_store.upsert_task(
            task_id=task_id,
            task_type=task_type,
            schedule=schedule,
            callback_id=callback_id,
            enabled=enabled,
            description=description,
            message=message,
        )

    def _remove_scheduler_task(self, task_id: str) -> bool:
        return self._task_store.remove_task(task_id)

    def _remove_tool_job(self, task_id: str) -> bool:
        return self._task_store.remove_tool_job(task_id)

    def _set_tool_job_enabled(self, task_id: str, enabled: bool) -> Dict[str, Any] | None:
        return self._task_store.set_tool_job_enabled(task_id, enabled)

    def _build_tool_task_name(self, tool_name: str, provided_name: str | None = None) -> str:
        if provided_name and str(provided_name).strip():
            return str(provided_name).strip()
        tool = tool_registry.get_tool(tool_name)
        if tool and str(tool.description or "").strip():
            return str(tool.description).strip()[:20]
        return tool_name[:20]

    def _validate_future_once_schedule(self, task_type: str, schedule: str) -> tuple[bool, str]:
        if task_type != "once":
            return True, ""

        try:
            scheduled_at = datetime.strptime(schedule, "%Y-%m-%d %H:%M")
        except ValueError:
            return False, "一次性提醒时间格式错误，请使用 YYYY-MM-DD HH:MM"

        current_minute = datetime.now().replace(second=0, microsecond=0)
        if scheduled_at <= current_minute:
            return (
                False,
                f"一次性提醒必须设置为未来时间，当前时间为 {current_minute.strftime('%Y-%m-%d %H:%M')}",
            )
        return True, ""

    def _normalize_tool_once_schedule(self, task_type: str, schedule: str) -> str:
        normalized_schedule = str(schedule or "").strip()
        if task_type != "once" or not normalized_schedule:
            return normalized_schedule

        try:
            scheduled_at = datetime.strptime(normalized_schedule, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                scheduled_at = datetime.strptime(normalized_schedule, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return normalized_schedule
            if scheduled_at.second > 0:
                scheduled_at = scheduled_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
            else:
                scheduled_at = scheduled_at.replace(second=0, microsecond=0)
        else:
            scheduled_at = scheduled_at.replace(second=0, microsecond=0)

        return scheduled_at.strftime("%Y-%m-%d %H:%M")

    async def _create_tool_schedule(
        self,
        *,
        user_id: int,
        tool_name: str,
        tool_arguments: Dict[str, Any] | None,
        time: str,
        task_type: str,
        task_name: str | None,
        context: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "success": False,
                "message": "定时服务未开启，请先使用【开启定时服务】命令",
            }

        normalized_time = self._normalize_tool_once_schedule(task_type, time)

        if not self._validate_schedule(task_type, normalized_time):
            return {
                "success": False,
                "message": (
                    "时间格式错误。daily 请用 HH:MM，weekly 请用 `星期 HH:MM`，"
                    "once 请用 YYYY-MM-DD HH:MM，或 YYYY-MM-DD HH:MM:SS"
                ),
            }

        is_valid_future, future_error = self._validate_future_once_schedule(task_type, normalized_time)
        if not is_valid_future:
            return {"success": False, "message": future_error}

        normalized_tool_name = str(tool_name or "").strip()
        if not normalized_tool_name:
            return {"success": False, "message": "未提供目标工具名"}

        tool = tool_registry.get_tool(normalized_tool_name)
        if tool is None:
            return {"success": False, "message": f"未找到工具：{normalized_tool_name}"}

        normalized_tool_args, error_message = await prepare_tool_arguments_for_schedule(
            normalized_tool_name,
            tool_arguments,
            context or {},
            tool=tool,
        )
        if normalized_tool_args is None:
            return {"success": False, "message": error_message}

        normalized_task_name = self._build_tool_task_name(normalized_tool_name, task_name)
        job_id = uuid.uuid4().hex
        metadata = infer_scheduled_tool_metadata(normalized_tool_name)
        context_snapshot = build_schedule_context_snapshot(context or {})
        payload = self._task_store.create_tool_job(
            job_id=job_id,
            creator_user_id=int(user_id),
            task_name=normalized_task_name,
            task_type=task_type,
            schedule=normalized_time,
            tool_name=normalized_tool_name,
            tool_args=normalized_tool_args,
            context_snapshot=context_snapshot,
            delivery_mode=str(metadata.get("delivery_mode") or "render_message"),
            risk_level=str(metadata.get("risk_level") or "normal"),
            enabled=True,
        )
        type_name = {"daily": "每天", "weekly": "每周", "once": "一次性"}
        return {
            "success": True,
            "message": (
                f"已创建{type_name.get(task_type, '')}工具定时任务："
                f"{normalized_time} -> {normalized_tool_name}"
            ),
            "data": {
                "job_id": job_id,
                "task_id": payload.get("task_id"),
                "task_name": normalized_task_name,
                "task_type": task_type,
                "schedule": normalized_time,
                "tool_name": normalized_tool_name,
            },
        }

    # ==================== AI 可调用的核心方法 ====================

    @ai_tool(
        name="create_reminder",
        desc=(
            "创建定时提醒。当用户说「提醒我...」「X分钟后提醒我...」「设置一个提醒」时使用此工具。"
            "如果用户表达的是「X分钟后/几小时后/明天/今晚/某天某时」这类一次性或相对时间，"
            "必须先换算成绝对时间 YYYY-MM-DD HH:MM，再以 task_type=once 调用；"
            "只有每天重复提醒才使用 task_type=daily 并传 HH:MM。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "提醒内容，如「开会」「吃药」等"
                },
                "time": {
                    "type": "string",
                    "description": (
                        "时间参数。task_type=daily 时必须是 HH:MM（如 08:30）；"
                        "task_type=once 时必须是完整绝对时间 YYYY-MM-DD HH:MM"
                        "（如 2026-03-16 00:53），不能只传 HH:MM。"
                    )
                },
                "task_type": {
                    "type": "string",
                    "enum": ["daily", "once"],
                    "description": (
                        "任务类型：daily=每天重复提醒，仅配合 HH:MM；"
                        "once=一次性提醒，凡是相对时间或指定日期时间都应使用 once。"
                    )
                },
                "task_name": {
                    "type": "string",
                    "description": "任务名称，用于识别此提醒"
                }
            },
            "required": ["message", "time", "task_type", "task_name"]
        },
        category="schedule",
        triggers=["提醒我", "设置提醒", "创建提醒", "定时提醒"],
        input_model=CreateReminderInput,
    )
    async def create_reminder(
        self,
        user_id: int,
        group_id: int,
        message: str,
        time: str,
        task_type: str = "once",
        task_name: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        创建定时提醒 - AI 可调用的核心方法

        Args:
            user_id: 创建者 QQ 号
            group_id: 群号
            message: 提醒内容
            time: 时间（HH:MM 或 YYYY-MM-DD HH:MM）
            task_type: 任务类型（daily/once）
            task_name: 任务名称

        Returns:
            {"success": bool, "message": str}
        """
        if not self.enabled:
            return {
                "success": False,
                "message": "定时服务未开启，请先使用【开启定时服务】命令"
            }

        if not self._validate_schedule(task_type, time):
            return {
                "success": False,
                "message": f"时间格式错误。每天定时请用 HH:MM（如 08:30），一次性请用 YYYY-MM-DD HH:MM（如 2025-01-15 08:30）"
            }

        is_valid_future, future_error = self._validate_future_once_schedule(task_type, time)
        if not is_valid_future:
            return {"success": False, "message": future_error}

        # 自动生成任务名
        if not task_name:
            task_name = message[:10] if len(message) > 10 else message

        try:
            # 生成任务ID
            task_id = f"schedule_msg_{group_id}_{task_name}"
            callback_id = f"schedule_msg_callback_{group_id}_{task_name}"
            description = f"{task_name}: {message[:20]}..."

            # 注册回调函数
            self._register_message_callback(callback_id, message)

            self._sync_scheduler_task(
                task_id=task_id,
                task_type=task_type,
                schedule=time,
                callback_id=callback_id,
                enabled=True,
                description=description,
                message=message,
            )

            type_name = {"daily": "每天", "once": "一次性"}
            return {
                "success": True,
                "message": f"已创建{type_name.get(task_type, '')}提醒：{time} - {message}"
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"创建提醒失败: {e}"
            }

    @ai_tool(
        name="list_reminders",
        desc="查看当前群的所有定时任务，包含普通提醒和定时工具调用任务",
        category="schedule",
        triggers=["查看提醒", "提醒列表"],
        input_model=EmptyInput,
    )
    async def list_reminders(
        self,
        user_id: int,
        group_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        查看定时提醒列表 - AI 可调用的核心方法
        """
        if not self.enabled:
            return {
                "success": False,
                "message": "定时服务未开启"
            }

        tasks = self._list_scheduler_tasks()

        if not tasks:
            return {
                "success": True,
                "message": "当前群组没有定时任务"
            }

        return {
            "success": True,
            "message": build_task_summary_message(tasks),
            "data": {"count": len(tasks), "tasks": list(tasks.values())}
        }

    @ai_tool(
        name="schedule_tool_call",
        desc=(
            "创建一个定时工具调用任务。当用户说“1分钟后抽塔罗牌”“今晚8点生成词云”“明天提醒我执行某个工具”时使用。"
            "如果表达的是相对时间，必须先换算成绝对时间 YYYY-MM-DD HH:MM，再以 task_type=once 调用。"
            "once 也可以传 YYYY-MM-DD HH:MM:SS，系统会自动规范到分钟粒度。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "目标工具名，必须是当前已注册的工具名，例如 draw_tarot_card、describe_image、audio2midi_transcribe",
                },
                "tool_arguments": {
                    "type": "object",
                    "description": "传给目标工具的参数对象；如果目标工具无参数，可传空对象",
                    "additionalProperties": True,
                },
                "time": {
                    "type": "string",
                    "description": (
                        "任务时间。daily 用 HH:MM，weekly 用 `星期 HH:MM`，"
                        "once 用 YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS"
                    ),
                },
                "task_type": {
                    "type": "string",
                    "enum": ["daily", "weekly", "once"],
                    "description": "任务类型：daily=每天，weekly=每周，once=一次性",
                },
                "task_name": {
                    "type": "string",
                    "description": "任务名称，可选；用于列表展示和后续管理",
                },
            },
            "required": ["tool_name", "tool_arguments", "time", "task_type"],
        },
        category="schedule",
        triggers=["定时执行", "定时调用", "稍后执行", "延迟执行"],
    )
    async def schedule_tool_call(
        self,
        user_id: int,
        group_id: int,
        tool_name: str,
        tool_arguments: Dict[str, Any],
        time: str,
        task_type: str = "once",
        task_name: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        return await self._create_tool_schedule(
            user_id=user_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            time=time,
            task_type=task_type,
            task_name=task_name,
            context=kwargs,
        )

    @ai_tool(
        name="cancel_scheduled_tool_job",
        desc="取消一个定时工具任务。需要提供 job_id，通常先通过 list_reminders 查看。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "定时工具任务的 job_id",
                }
            },
            "required": ["job_id"],
        },
        category="schedule",
        triggers=["取消定时任务", "删除定时任务"],
    )
    async def cancel_scheduled_tool_job(
        self,
        user_id: int,
        group_id: int,
        job_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        task_id = str(job_id or "").strip()
        if not task_id:
            return {"success": False, "message": "未提供 job_id"}

        runtime_task_id = f"scheduled_tool_{task_id}"
        removed = self._remove_tool_job(runtime_task_id)
        if not removed:
            return {"success": False, "message": f"未找到定时工具任务：{task_id}"}
        return {"success": True, "message": f"已取消定时工具任务：{task_id}"}

    # ==================== 用户命令入口（参数适配器） ====================

    @service_action(cmd="定时服务")
    async def schedule_system(self):
        """定时服务主菜单"""
        if not self.enabled:
            await self.group.send_msg("❌ 定时服务未开启！请先使用【开启定时服务】命令")
            return

        while True:
            msg = (
                "📋【定时服务系统】\n\n"
                "1. 添加定时消息\n"
                "2. 查看定时任务\n"
                "3. 删除定时任务\n"
                "4. 切换任务状态\n\n"
                "输入序号或【退出】返回"
            )
            await self.group.send_msg(msg)

            try:
                response = await wait_for(30)
                if not response:
                    await self.group.send_msg("⏰ 操作超时，已退出")
                    return
                response = response.strip()

                if response == "退出":
                    await self.group.send_msg("✅ 已退出定时服务")
                    return

                if response == "1":
                    await self.add_scheduled_message()
                elif response == "2":
                    await self.list_scheduled_tasks()
                elif response == "3":
                    await self.remove_scheduled_task()
                elif response == "4":
                    await self.toggle_scheduled_task()
                else:
                    await self.group.send_msg("❌ 无效选择，请重新输入")
            except Exception as e:
                print(e)
                await self.group.send_msg("❌ 操作出错，已退出")
                return

    @service_action(cmd="添加定时消息")
    async def add_scheduled_message(self):
        """添加定时消息"""
        if not self.enabled:
            await self.group.send_msg("❌ 定时服务未开启！")
            return

        try:
            # 选择任务类型
            await self.group.send_msg(
                "📝 添加定时消息\n\n"
                "请选择消息类型：\n"
                "1. 每天定时发送\n"
                "2. 每周定时发送\n"
                "3. 一次性发送\n\n"
                "输入序号或【取消】"
            )

            response = await wait_for(30)
            if not response or response.strip() == "取消":
                await self.group.send_msg("❌ 已取消")
                return

            choice = response.strip()
            if choice == "1":
                task_type = "daily"
            elif choice == "2":
                task_type = "weekly"
            elif choice == "3":
                task_type = "once"
            else:
                await self.group.send_msg("❌ 无效选择")
                return

            # 输入时间
            time_prompt = {
                "daily": "请输入发送时间（格式: HH:MM，如 08:30）:",
                "weekly": "请输入星期和时间（格式: 星期 HH:MM，如 1 08:30，星期一为0）:",
                "once": "请输入日期和时间（格式: YYYY-MM-DD HH:MM，如 2025-01-15 08:30）:"
            }
            await self.group.send_msg(time_prompt[task_type])

            time_response = await wait_for(60)
            if not time_response:
                await self.group.send_msg("❌ 输入超时")
                return

            schedule = time_response.strip()
            if not self._validate_schedule(task_type, schedule):
                await self.group.send_msg("❌ 时间格式错误")
                return

            # 输入消息内容
            await self.group.send_msg("请输入要发送的消息内容:")
            message_response = await wait_for(120)
            if not message_response:
                await self.group.send_msg("❌ 输入超时")
                return

            message = message_response.strip()
            if not message:
                await self.group.send_msg("❌ 消息内容不能为空")
                return

            # 输入任务名称
            await self.group.send_msg("请输入任务名称（用于识别此任务）:")
            name_response = await wait_for(60)
            if not name_response:
                await self.group.send_msg("❌ 输入超时")
                return

            task_name = name_response.strip()
            if not task_name:
                await self.group.send_msg("❌ 任务名称不能为空")
                return

            # 生成任务ID
            task_id = f"schedule_msg_{self.group.group_id}_{task_name}"
            callback_id = f"schedule_msg_callback_{self.group.group_id}_{task_name}"
            description = f"{task_name}: {message[:20]}..."

            # 注册回调函数
            self._register_message_callback(callback_id, message)

            self._sync_scheduler_task(
                task_id=task_id,
                task_type=task_type,
                schedule=schedule,
                callback_id=callback_id,
                enabled=True,
                description=description,
                message=message,
            )

            type_name = {"daily": "每天", "weekly": "每周", "once": "一次性"}
            await self.group.send_msg(
                f"✅ 定时消息添加成功！\n\n"
                f"📝 任务名称: {task_name}\n"
                f"📋 类型: {type_name[task_type]}\n"
                f"⏰ 时间: {schedule}\n"
                f"💬 消息: {message[:50]}{'...' if len(message) > 50 else ''}"
            )

        except Exception as e:
            print(e)
            await self.group.send_msg("❌ 添加失败")

    @service_action(cmd="查看定时任务")
    async def list_scheduled_tasks(self):
        """查看当前群组的所有定时任务"""
        if not self.enabled:
            await self.group.send_msg("❌ 定时服务未开启！")
            return

        tasks = self._list_scheduler_tasks()

        if not tasks:
            await self.group.send_msg("📋 当前群组没有定时任务")
            return

        await self.group.send_msg(build_task_list_message(tasks))
        return tasks

    @service_action(cmd="删除定时任务")
    async def remove_scheduled_task(self):
        """删除定时任务"""
        if not self.enabled:
            await self.group.send_msg("❌ 定时服务未开启！")
            return

        tasks = await self.list_scheduled_tasks()
        if not tasks:
            return

        await self.group.send_msg("请输入要删除的任务序号，或输入【取消】:")

        try:
            response = await wait_for(30)
            if not response or response.strip() == "取消":
                await self.group.send_msg("❌ 已取消")
                return

            choice = response.strip()
            if not choice.isdigit():
                await self.group.send_msg("❌ 请输入有效的序号")
                return

            index = int(choice) - 1
            task_list = list(tasks.items())
            if index < 0 or index >= len(task_list):
                await self.group.send_msg("❌ 序号超出范围")
                return

            task_id, task = task_list[index]
            task_kind = str(task.get("task_kind") or "message")
            if task_kind == "tool":
                removed = self._remove_tool_job(task_id)
            else:
                removed = self._remove_scheduler_task(task_id)
            if removed:
                await self.group.send_msg(f"✅ 任务已删除: {task.get('description', task_id)}")
            else:
                await self.group.send_msg("❌ 删除失败")

        except Exception as e:
            print(e)
            await self.group.send_msg("❌ 操作出错")

    @service_action(cmd="切换定时任务")
    async def toggle_scheduled_task(self):
        """切换定时任务状态"""
        if not self.enabled:
            await self.group.send_msg("❌ 定时服务未开启！")
            return

        tasks = await self.list_scheduled_tasks()
        if not tasks:
            return

        await self.group.send_msg("请输入要切换状态的任务序号，或输入【取消】:")

        try:
            response = await wait_for(30)
            if not response or response.strip() == "取消":
                await self.group.send_msg("❌ 已取消")
                return

            choice = response.strip()
            if not choice.isdigit():
                await self.group.send_msg("❌ 请输入有效的序号")
                return

            index = int(choice) - 1
            task_list = list(tasks.items())
            if index < 0 or index >= len(task_list):
                await self.group.send_msg("❌ 序号超出范围")
                return

            task_id, task = task_list[index]
            current_status = task.get("enabled", True)
            new_status = not current_status
            task_kind = str(task.get("task_kind") or "message")
            if task_kind == "tool":
                updated_task = self._set_tool_job_enabled(task_id, new_status)
                if updated_task is None:
                    await self.group.send_msg("❌ 更新失败，未找到该任务")
                    return
            else:
                self._sync_scheduler_task(
                    task_id=task_id,
                    task_type=task.get("task_type", task.get("type", "")),
                    schedule=task.get("schedule", ""),
                    callback_id=task.get("callback_id", ""),
                    enabled=new_status,
                    description=task.get("description", task_id),
                    message=self._extract_task_message(task),
                )
            status_text = "启用" if new_status else "禁用"
            await self.group.send_msg(
                f"✅ 任务状态已切换为【{status_text}】\n"
                f"📝 {task.get('description', task_id)}"
            )
        except Exception as e:
            print(e)
            await self.group.send_msg("❌ 操作出错")

    def _validate_schedule(self, task_type: str, schedule: str) -> bool:
        return validate_schedule(task_type, schedule)
