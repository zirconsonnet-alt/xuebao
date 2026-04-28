import asyncio
from datetime import datetime
from pathlib import Path
import random
import re
import shutil
from typing import Any, Callable, Coroutine, Iterable, Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot_plugin_apscheduler import scheduler

from src.support.core import Services

from .base import BaseService, check_enabled, config_property, service_action

try:
    from src.vendors.nonebot_plugin_reminder.problem_solver import ProblemSolverSystem
    from src.vendors.nonebot_plugin_reminder.reminder import ReminderSystem
    from src.vendors.nonebot_plugin_reminder.reviewer import Viewer
    from src.vendors.nonebot_plugin_reminder.scoring_system import ScoringSystem

    _REMINDER_AVAILABLE = True
except Exception:
    _REMINDER_AVAILABLE = False

if not _REMINDER_AVAILABLE:
    raise ImportError("reminder 依赖不可用")

_problem_solver_systems: dict[tuple[int, int], ProblemSolverSystem] = {}
_reminder_systems: dict[tuple[int, int], ReminderSystem] = {}
_scoring_systems: dict[tuple[int, int], ScoringSystem] = {}
_viewers: dict[tuple[int, int], Viewer] = {}
_scheduler_jobs_registered = False

_SCORE_TIME_POINTS = (
    (9, 25),
    (11, 25),
    (15, 25),
    (17, 25),
    (19, 25),
    (21, 25),
)
_VIEW_TIME_POINTS = (
    (9, 30),
    (11, 30),
    (15, 30),
    (17, 30),
    (19, 30),
    (21, 30),
)
_BREAK_NOTICE_BASE_POINTS = (
    (8, 10),
    (10, 10),
    (14, 10),
    (16, 10),
    (18, 10),
    (20, 10),
)


def _iter_persisted_group_ids() -> tuple[int, ...]:
    root = Path("data") / "group_management"
    if not root.exists():
        return ()

    group_ids: list[int] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        if not (child / "group_data.db").exists():
            continue
        group_ids.append(int(child.name))
    return tuple(sorted(group_ids))


def _get_group_root(group_id: int) -> Path:
    group_root = Path("data") / "group_management" / str(group_id) / "reminder"
    group_root.mkdir(parents=True, exist_ok=True)
    return group_root


def _ensure_problem_tree_config(group_id: int) -> Path:
    target = _get_group_root(group_id) / "problem_tree.json"
    if target.exists():
        return target

    default_config = Path("data") / "problem_tree.json"
    if default_config.exists():
        shutil.copyfile(default_config, target)
        return target

    target.write_text(
        '{"title": "您是否遇到以下问题：", "is_leaf": false, "children": {}}',
        encoding="utf-8",
    )
    return target


def _get_context_key(group_id: int, user_id: int) -> tuple[int, int]:
    return int(group_id), int(user_id)


def get_problem_solver_system(group_id: int, user_id: int) -> ProblemSolverSystem:
    key = _get_context_key(group_id, user_id)
    if key not in _problem_solver_systems:
        _problem_solver_systems[key] = ProblemSolverSystem(
            user_id=user_id,
            group_id=group_id,
            config_file=_ensure_problem_tree_config(group_id),
        )
    return _problem_solver_systems[key]


def get_reminder_system(group_id: int, user_id: int) -> ReminderSystem:
    key = _get_context_key(group_id, user_id)
    if key not in _reminder_systems:
        _reminder_systems[key] = ReminderSystem(
            user_id=user_id,
            group_id=group_id,
            json_path=_get_group_root(group_id) / "reminders.json",
        )
    return _reminder_systems[key]


def get_viewer(group_id: int, user_id: int) -> Viewer:
    key = _get_context_key(group_id, user_id)
    if key not in _viewers:
        viewer_root = _get_group_root(group_id) / "viewer"
        _viewers[key] = Viewer(
            user_id=user_id,
            group_id=group_id,
            root_dir=viewer_root,
        )
    return _viewers[key]


def get_scoring_system(group_id: int, user_id: int) -> ScoringSystem:
    key = _get_context_key(group_id, user_id)
    if key not in _scoring_systems:
        _scoring_systems[key] = ScoringSystem(
            user_id=user_id,
            group_id=group_id,
            db_path=_get_group_root(group_id) / "user_scores.db",
        )
    return _scoring_systems[key]


def register_reminder_scheduled_callback(
    task_id: str,
    callback: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    from src.vendors.nonebot_plugin_reminder.reminder import register_scheduled_callback

    register_scheduled_callback(task_id, callback)


def get_reminder_scheduled_task_manager():
    from src.vendors.nonebot_plugin_reminder.reminder import scheduled_task_manager

    return scheduled_task_manager


async def check_reminder_scheduled_tasks() -> None:
    await get_reminder_scheduled_task_manager().check_and_trigger()


async def _iter_enabled_reminder_contexts() -> list[tuple[int, int]]:
    from .registry import service_manager

    contexts: list[tuple[int, int]] = []
    for group_id in _iter_persisted_group_ids():
        service = await service_manager.get_service(group_id, Services.Reminder)
        if not bool(getattr(service, "enabled", False)):
            continue
        target_user_id = getattr(service, "target_user_id", None)
        if target_user_id is None:
            continue
        try:
            contexts.append((int(group_id), int(target_user_id)))
        except (TypeError, ValueError):
            continue
    return contexts


async def _run_for_enabled_reminder_contexts(callback):
    for group_id, user_id in await _iter_enabled_reminder_contexts():
        await callback(group_id, user_id)


def _add_minutes(time_point: tuple[int, int], minutes_to_add: int) -> tuple[int, int]:
    hour, minute = time_point
    total_minutes = minute + minutes_to_add
    new_hour = hour + total_minutes // 60
    new_minute = total_minutes % 60
    return new_hour, new_minute


def _generate_break_notice_points() -> tuple[tuple[int, int], ...]:
    all_times: list[tuple[int, int]] = []
    for time_point in _BREAK_NOTICE_BASE_POINTS:
        all_times.append(time_point)
        all_times.append(_add_minutes(time_point, 30))
        all_times.append(_add_minutes(time_point, 60))
    return tuple(all_times)


async def send_break_reminder(group_id: int, user_id: int) -> None:
    try:
        await asyncio.sleep(random.randint(0, 5) * 60)
        reminder = get_reminder_system(group_id, user_id)
        await reminder.send("请停止思考10秒钟")
        await asyncio.sleep(10)
        await reminder.send("10秒钟思考结束，请继续学习")
    except Exception as exc:
        print(f"发送提醒时出错: {exc}")


class ReminderService(BaseService):
    service_type = Services.Reminder
    default_config = {"enabled": False, "target_user_id": None}
    enabled = config_property("enabled")
    target_user_id = config_property("target_user_id")

    def bind_target_user(self, user_id: int) -> None:
        self.target_user_id = int(user_id)

    @staticmethod
    def _extract_target_user_id(arg: Message) -> Optional[int]:
        for segment in arg:
            if getattr(segment, "type", None) != "at":
                continue
            qq = segment.data.get("qq")
            if qq and str(qq).isdigit():
                return int(qq)

        text = arg.extract_plain_text().strip()
        if not text:
            return None

        match = re.search(r"\d{5,}", text)
        if not match:
            return None
        return int(match.group(0))

    async def ensure_bound_target_user(self, event: GroupMessageEvent) -> bool:
        current = getattr(self, "target_user_id", None)
        current_user_id = int(event.user_id)

        if current is None:
            self.bind_target_user(current_user_id)
            await self.group.send_msg(
                "✅ 已自动绑定本群 Reminder 用户。\n"
                f"当前绑定 QQ：{current_user_id}\n"
                "管理员如需切换，可使用『绑定提醒用户 @成员』。"
            )
            return True

        try:
            bound_user_id = int(current)
        except (TypeError, ValueError):
            self.bind_target_user(current_user_id)
            await self.group.send_msg(
                "⚠️ 检测到 Reminder 绑定配置异常，已重新绑定到当前用户。\n"
                f"当前绑定 QQ：{current_user_id}"
            )
            return True

        if bound_user_id == current_user_id:
            return True

        await self.group.send_msg(
            "🚫 当前 Reminder 已绑定到其他用户，为避免学习记录串档，暂不允许直接接管。\n"
            f"当前绑定 QQ：{bound_user_id}\n"
            "管理员可使用『绑定提醒用户 @成员』切换绑定对象。"
        )
        return False

    @service_action(
        cmd="绑定提醒用户",
        aliases={"提醒绑定", "设置提醒用户"},
        need_arg=True,
        desc="绑定本群 Reminder 服务的目标用户",
        require_admin=True,
        allow_when_disabled=True,
        tool_callable=True,
    )
    async def set_target_user(self, event: GroupMessageEvent, arg: Message):
        target_user_id = self._extract_target_user_id(arg)
        if target_user_id is None:
            await self.group.send_msg("❌ 请提供目标 QQ 号或 @ 一位成员。")
            return

        self.bind_target_user(target_user_id)
        get_problem_solver_system(event.group_id, target_user_id)
        get_reminder_system(event.group_id, target_user_id)
        get_viewer(event.group_id, target_user_id)
        get_scoring_system(event.group_id, target_user_id)
        await self.group.send_msg(
            "✅ Reminder 绑定用户已更新。\n"
            f"当前绑定 QQ：{target_user_id}"
        )

    @service_action(
        cmd="提醒状态",
        aliases={"Reminder状态", "查看提醒绑定"},
        desc="查看本群 Reminder 服务当前绑定状态",
        require_admin=True,
        allow_when_disabled=True,
        tool_callable=True,
    )
    async def show_reminder_status(self, event: GroupMessageEvent):
        current = getattr(self, "target_user_id", None)
        enabled = "✅ 开启" if bool(getattr(self, "enabled", False)) else "⛔ 关闭"
        if current is None:
            await self.group.send_msg(
                "Reminder 状态：\n"
                f"总开关：{enabled}\n"
                "当前绑定：未设置\n"
                "管理员可使用『绑定提醒用户 @成员』设置目标用户。"
            )
            return

        await self.group.send_msg(
            "Reminder 状态：\n"
            f"总开关：{enabled}\n"
            f"当前绑定 QQ：{current}\n"
            f"数据目录：{_get_group_root(event.group_id)}"
        )

    @service_action(cmd="问题解决", desc="启动问题解决系统", tool_callable=True)
    @check_enabled
    async def solve_problem(self, event: GroupMessageEvent):
        if not await self.ensure_bound_target_user(event):
            return
        await get_problem_solver_system(event.group_id, event.user_id).run()

    @service_action(cmd="日志", desc="打开提醒任务编辑模式", tool_callable=True)
    @check_enabled
    async def edit_reminder_tasks(self, event: GroupMessageEvent):
        if not await self.ensure_bound_target_user(event):
            return
        await get_reminder_system(event.group_id, event.user_id).edit_mode()

    @service_action(cmd="任务收集", aliases={"收集任务"}, need_arg=True, desc="收集指定学习周期的任务")
    @check_enabled
    async def collect_task(self, event: GroupMessageEvent, arg: Message):
        if not await self.ensure_bound_target_user(event):
            return
        raw = arg.extract_plain_text().strip()
        if not raw or not raw.isdigit():
            await self.group.send_msg("❌ 请指定学习周期序号 (1-6)，例如：任务收集 1")
            return
        index = int(raw)
        if not 1 <= index <= 6:
            await self.group.send_msg("❌ 序号必须在 1-6 范围内")
            return
        await get_viewer(event.group_id, event.user_id).collect_question_and_screenshots(index)
        await self.group.send_msg(f"✅ 已完成第 {index} 个学习周期的任务收集")

    @service_action(cmd="任务查看", aliases={"查看任务"}, need_arg=True, desc="查看指定学习周期的任务")
    @check_enabled
    async def view_task(self, event: GroupMessageEvent, arg: Message):
        if not await self.ensure_bound_target_user(event):
            return
        raw = arg.extract_plain_text().strip()
        if not raw or not raw.isdigit():
            await self.group.send_msg("❌ 请指定学习周期序号 (1-6)，例如：任务查看 1")
            return
        index = int(raw)
        if not 1 <= index <= 6:
            await self.group.send_msg("❌ 序号必须在 1-6 范围内")
            return
        await get_viewer(event.group_id, event.user_id).handler_task(index)
        await self.group.send_msg(f"✅ 已完成第 {index} 个学习周期的任务查看")

    @service_action(cmd="目标", need_arg=True, desc="保存学习目标")
    @check_enabled
    async def save_goal(self, event: GroupMessageEvent, arg: Message):
        if not await self.ensure_bound_target_user(event):
            return
        raw = arg.extract_plain_text().strip()
        if not raw:
            await self.group.send_msg(
                "❌ 请使用以下格式：目标 类型 开始日期 开始序号 结束日期 结束序号 描述\n"
                "例如：目标 math 2025-07-03 1 2025-07-10 5 完成高等数学第一章"
            )
            return

        parts = raw.split(" ")
        if len(parts) < 6:
            await self.group.send_msg("❌ 格式错误，请使用：类型 开始日期 开始序号 结束日期 结束序号 描述")
            return

        goal_type, start_date, start_idx, end_date, end_idx = parts[:5]
        description = " ".join(parts[5:]).strip()
        if goal_type not in {"math", "cs"}:
            await self.group.send_msg("❌ 目标类型必须是 'math' 或 'cs'")
            return

        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            await self.group.send_msg("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
            return

        try:
            start_index = int(start_idx)
            end_index = int(end_idx)
            if not (1 <= start_index <= 6 and 1 <= end_index <= 6):
                raise ValueError
        except ValueError:
            await self.group.send_msg("❌ 序号必须是 1-6 之间的整数")
            return

        get_viewer(event.group_id, event.user_id).save_goal(
            goal_type=goal_type,
            start_date=start_date,
            start_idx=start_index,
            end_date=end_date,
            end_idx=end_index,
            description=description,
        )
        await self.group.send_msg(f"✅ 目标已保存: {description}")


def register_reminder_scheduler_jobs() -> None:
    global _scheduler_jobs_registered
    if _scheduler_jobs_registered:
        return

    for index, (hour, minute) in enumerate(_SCORE_TIME_POINTS, start=1):
        job_id = f"reminder_score_{index}"

        async def score_job():
            async def _run(group_id: int, user_id: int):
                await get_scoring_system(group_id, user_id).score()

            await _run_for_enabled_reminder_contexts(_run)

        scheduler.add_job(
            score_job,
            "cron",
            hour=hour,
            minute=minute,
            id=job_id,
            replace_existing=True,
        )

    for index, (hour, minute) in enumerate(_VIEW_TIME_POINTS, start=1):
        job_id = f"reminder_view_cycle_{index}"

        async def view_job(cycle_index=index):
            async def _run(group_id: int, user_id: int):
                viewer = get_viewer(group_id, user_id)
                await viewer.collect_question_and_screenshots(cycle_index)
                await viewer.handler_task(cycle_index)

            await _run_for_enabled_reminder_contexts(_run)

        scheduler.add_job(
            view_job,
            "cron",
            hour=hour,
            minute=minute,
            id=job_id,
            replace_existing=True,
        )

    for index, (hour, minute) in enumerate(_generate_break_notice_points(), start=1):
        job_id = f"reminder_break_notice_{index}"

        async def break_notice_job():
            async def _run(group_id: int, user_id: int):
                await send_break_reminder(group_id, user_id)

            await _run_for_enabled_reminder_contexts(_run)

        scheduler.add_job(
            break_notice_job,
            "cron",
            hour=hour,
            minute=minute,
            id=job_id,
            replace_existing=True,
        )

    async def check_reminders_job():
        async def _run(group_id: int, user_id: int):
            await get_reminder_system(group_id, user_id).check_and_trigger()

        await _run_for_enabled_reminder_contexts(_run)

    scheduler.add_job(
        check_reminders_job,
        "cron",
        second=30,
        id="reminder_check",
        replace_existing=True,
    )

    _scheduler_jobs_registered = True


__all__ = [
    "check_reminder_scheduled_tasks",
    "get_reminder_scheduled_task_manager",
    "ReminderService",
    "get_problem_solver_system",
    "get_reminder_system",
    "register_reminder_scheduled_callback",
    "get_scoring_system",
    "get_viewer",
    "register_reminder_scheduler_jobs",
]
