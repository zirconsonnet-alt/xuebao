import re
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, Tuple

import aiohttp
import nonebot
from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.permission import SUPERUSER

from src.support.core import Services
from src.support.group import GroupContext, wait_for_event
from src.support.scheduled_tasks import (
    get_runtime_task,
    register_runtime_callback,
    upsert_runtime_task,
)

from .base import BaseService, check_enabled, config_property, service_action

try:
    from PIL import Image
    from src.vendors.nonebot_plugin_wordcloud.config import global_config, plugin_config
    from src.vendors.nonebot_plugin_wordcloud.data_source import get_wordcloud
    from src.vendors.nonebot_plugin_wordcloud.utils import (
        admin_permission,
        get_datetime_fromisoformat_with_timezone,
        get_datetime_now_with_timezone,
        get_mask_key,
    )

    _WORDCLOUD_AVAILABLE = True
except Exception:
    _WORDCLOUD_AVAILABLE = False

if not _WORDCLOUD_AVAILABLE:
    raise ImportError("wordcloud 依赖不可用")

def _strip_command_start(text: str) -> str:
    for prefix in global_config.command_start:
        if prefix and text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _parse_scope_from_command_text(text: str) -> Optional[str]:
    raw = _strip_command_start(text).strip()
    if raw.startswith("本群"):
        return "group"
    if raw.startswith("我的"):
        return "personal"
    return None


def _get_time_range_by_keyword(now: datetime, keyword: str) -> Tuple[datetime, datetime]:
    keyword = keyword.strip()
    if keyword == "今日":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if keyword == "昨日":
        stop = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return stop - timedelta(days=1), stop
    if keyword == "本周":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if keyword == "上周":
        stop = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return stop - timedelta(days=7), stop
    if keyword == "本月":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if keyword == "上月":
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_last_day = this_month_start - timedelta(days=1)
        start = last_month_last_day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, this_month_start
    if keyword == "年度":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    raise ValueError(f"未知时间段关键词：{keyword}")


def _parse_wordcloud_history_range(now: datetime, raw: str) -> Tuple[datetime, datetime]:
    raw = raw.strip()
    if not raw:
        raise ValueError("缺少日期或时间段参数")
    if "~" in raw:
        left, right = (item.strip() for item in raw.split("~", 1))
        if not left or not right:
            raise ValueError("时间段格式应为：开始~结束")
        start = get_datetime_fromisoformat_with_timezone(left)
        stop = get_datetime_fromisoformat_with_timezone(right)
    else:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            start = get_datetime_fromisoformat_with_timezone(f"{raw}T00:00:00")
            stop = start + timedelta(days=1)
        else:
            start = get_datetime_fromisoformat_with_timezone(raw)
            stop = now
    if stop <= start:
        raise ValueError("结束时间必须晚于开始时间")
    return start, stop


async def _download_onebot_image_bytes(event: GroupMessageEvent) -> Optional[bytes]:
    images = [seg for seg in event.get_message() if getattr(seg, "type", "") == "image"]
    if not images:
        return None
    file_id = images[0].data.get("file")
    url = images[0].data.get("url")
    if not url and file_id:
        try:
            info = await nonebot.get_bot().get_image(file=file_id)
            url = info.get("url")
        except Exception:
            url = None
    if not url:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


class WordcloudService(BaseService):
    service_type = Services.Wordcloud
    _TASK_STATE_SCOPE = "scheduler"
    default_config = {"enabled": False, "daily_schedule_enabled": False, "daily_schedule_time": "22:00"}
    enabled = config_property("enabled")
    daily_schedule_enabled = config_property("daily_schedule_enabled")
    daily_schedule_time = config_property("daily_schedule_time")

    def __init__(self, group: "GroupContext"):
        super().__init__(group)

    async def _send_wordcloud(self, *, event: Optional[GroupMessageEvent], start: datetime, stop: datetime, scope: str, user_id: Optional[int] = None):
        require("nonebot_plugin_saa")
        require("nonebot_plugin_cesaa")
        import nonebot_plugin_saa as saa
        from nonebot_plugin_cesaa import get_messages_plain_text

        saa.enable_auto_select_bot()
        target = saa.TargetQQGroup(group_id=self.group.group_id)
        mask_key = get_mask_key(target=target)
        kwargs = {
            "target": target,
            "types": ["message"],
            "time_start": start,
            "time_stop": stop,
            "exclude_user_ids": plugin_config.wordcloud_exclude_user_ids,
        }
        if scope == "personal":
            if user_id is None and event is not None:
                user_id = event.user_id
            if user_id is None:
                await self.group.send_msg("❌ 缺少 user_id，无法生成个人词云")
                return
            kwargs["user_ids"] = [str(user_id)]
        messages = await get_messages_plain_text(**kwargs)
        image = await get_wordcloud(list(messages), mask_key)
        if image:
            await saa.Image(image).send_to(target)
            return
        await self.group.send_msg("今天没有足够的数据生成词云")

    def _resolve_scope(self, event: GroupMessageEvent) -> str:
        override = _parse_scope_from_command_text(event.get_message().extract_plain_text())
        if override == "group":
            return "group"
        if override == "personal":
            return "personal"
        return "personal" if plugin_config.wordcloud_default_personal else "group"

    @service_action(cmd="今日词云", aliases={"本群今日词云", "我的今日词云"}, desc="生成今日词云", tool_callable=True)
    @check_enabled
    async def wordcloud_today(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "今日")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="昨日词云", aliases={"本群昨日词云", "我的昨日词云"}, desc="生成昨日词云", tool_callable=True)
    @check_enabled
    async def wordcloud_yesterday(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "昨日")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="本周词云", aliases={"本群本周词云", "我的本周词云"}, desc="生成本周词云")
    @check_enabled
    async def wordcloud_this_week(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "本周")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="上周词云", aliases={"本群上周词云", "我的上周词云"}, desc="生成上周词云")
    @check_enabled
    async def wordcloud_last_week(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "上周")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="本月词云", aliases={"本群本月词云", "我的本月词云"}, desc="生成本月词云")
    @check_enabled
    async def wordcloud_this_month(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "本月")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="上月词云", aliases={"本群上月词云", "我的上月词云"}, desc="生成上月词云")
    @check_enabled
    async def wordcloud_last_month(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "上月")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="年度词云", aliases={"本群年度词云", "我的年度词云"}, desc="生成年度词云")
    @check_enabled
    async def wordcloud_year(self, event: GroupMessageEvent):
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "年度")
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="历史词云", aliases={"本群历史词云", "我的历史词云"}, need_arg=True, desc="生成指定时间段词云（支持 ISO8601 或 开始~结束）")
    @check_enabled
    async def wordcloud_history(self, event: GroupMessageEvent, arg: Message):
        now = get_datetime_now_with_timezone()
        try:
            start, stop = _parse_wordcloud_history_range(now, arg.extract_plain_text().strip())
        except ValueError as exc:
            await self.group.send_msg(f"❌ {exc}\n示例：/历史词云 2026-02-01~2026-02-05")
            return
        await self._send_wordcloud(event=event, start=start, stop=stop, scope=self._resolve_scope(event))

    @service_action(cmd="设置词云形状", permission=admin_permission(), desc="设置本群词云形状（发送一张图片）")
    @check_enabled
    async def set_mask(self, event: GroupMessageEvent):
        image_bytes = await _download_onebot_image_bytes(event)
        if not image_bytes:
            await self.group.send_msg("请发送一张图片作为词云形状（30 秒内）")
            evt = await wait_for_event(30)
            if not evt or not isinstance(evt, GroupMessageEvent):
                await self.group.send_msg("❌ 超时，已取消")
                return
            image_bytes = await _download_onebot_image_bytes(evt)
        if not image_bytes:
            await self.group.send_msg("❌ 未检测到图片")
            return

        require("nonebot_plugin_saa")
        import nonebot_plugin_saa as saa

        target = saa.TargetQQGroup(group_id=self.group.group_id)
        mask_key = get_mask_key(target=target)
        mask = Image.open(BytesIO(image_bytes))
        path = plugin_config.get_mask_path(mask_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(path, format="PNG")
        await self.group.send_msg("✅ 词云形状设置成功")

    @service_action(cmd="删除词云形状", permission=admin_permission(), desc="删除本群自定义词云形状")
    @check_enabled
    async def remove_mask(self):
        require("nonebot_plugin_saa")
        import nonebot_plugin_saa as saa

        target = saa.TargetQQGroup(group_id=self.group.group_id)
        mask_key = get_mask_key(target=target)
        plugin_config.get_mask_path(mask_key).unlink(missing_ok=True)
        await self.group.send_msg("✅ 词云形状已删除")

    @service_action(cmd="设置词云默认形状", permission=SUPERUSER, desc="设置默认词云形状（仅超级用户）")
    @check_enabled
    async def set_default_mask(self, event: GroupMessageEvent):
        image_bytes = await _download_onebot_image_bytes(event)
        if not image_bytes:
            await self.group.send_msg("请发送一张图片作为默认词云形状（30 秒内）")
            evt = await wait_for_event(30)
            if not evt or not isinstance(evt, GroupMessageEvent):
                await self.group.send_msg("❌ 超时，已取消")
                return
            image_bytes = await _download_onebot_image_bytes(evt)
        if not image_bytes:
            await self.group.send_msg("❌ 未检测到图片")
            return
        mask = Image.open(BytesIO(image_bytes))
        path = plugin_config.get_mask_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(path, format="PNG")
        await self.group.send_msg("✅ 默认词云形状设置成功")

    @service_action(cmd="删除词云默认形状", permission=SUPERUSER, desc="删除默认词云形状（仅超级用户）")
    @check_enabled
    async def remove_default_mask(self):
        plugin_config.get_mask_path().unlink(missing_ok=True)
        await self.group.send_msg("✅ 默认词云形状已删除")

    def _wordcloud_daily_task_id(self) -> str:
        return f"wordcloud_daily_task_{self.group.group_id}"

    def _wordcloud_daily_callback_id(self) -> str:
        return f"wordcloud_daily_{self.group.group_id}"

    def _daily_schedule_state(self) -> Optional[dict]:
        task = self.get_state_entry(self._TASK_STATE_SCOPE, "daily_wordcloud")
        if isinstance(task, dict):
            return task

        task = get_runtime_task(self._wordcloud_daily_task_id())
        if not task:
            return None

        payload = {
            "task_id": self._wordcloud_daily_task_id(),
            "task_type": task.get("type", "daily"),
            "schedule": task.get("schedule", self.daily_schedule_time),
            "callback_id": task.get("callback_id", self._wordcloud_daily_callback_id()),
            "enabled": bool(task.get("enabled", True)),
            "group_id": self.group.group_id,
            "description": task.get("description", "每日词云定时发送"),
        }
        self.put_state_entry(self._TASK_STATE_SCOPE, "daily_wordcloud", payload)
        return payload

    def _sync_daily_schedule_state(
        self,
        *,
        time_str: str,
        callback_id: str,
        enabled: bool,
    ) -> None:
        payload = {
            "task_id": self._wordcloud_daily_task_id(),
            "task_type": "daily",
            "schedule": time_str,
            "callback_id": callback_id,
            "enabled": enabled,
            "group_id": self.group.group_id,
            "description": "每日词云定时发送",
        }
        self.put_state_entry(self._TASK_STATE_SCOPE, "daily_wordcloud", payload)

        upsert_runtime_task(
            task_id=payload["task_id"],
            task_type="daily",
            schedule=time_str,
            callback_id=callback_id,
            enabled=enabled,
            group_id=self.group.group_id,
            description=payload["description"],
        )

    async def send_daily_wordcloud(self):
        if not self.enabled or not self.daily_schedule_enabled:
            return
        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_keyword(now, "今日")
        await self._send_wordcloud(event=None, start=start, stop=stop, scope="group")

    @service_action(cmd="词云每日定时发送状态", permission=admin_permission(), desc="查看本群每日词云定时发送状态")
    @check_enabled
    async def daily_schedule_status(self):
        task = self._daily_schedule_state()
        if not task or not task.get("enabled", True):
            await self.group.send_msg("词云每日定时发送未开启")
            return
        await self.group.send_msg(f"词云每日定时发送已开启，发送时间为：{task.get('schedule')}")

    @service_action(cmd="开启词云每日定时发送", permission=admin_permission(), need_arg=True, desc="开启每日定时发送词云（可选：HH:MM）")
    @check_enabled
    async def daily_schedule_enable(self, arg: Message):
        time_str = arg.extract_plain_text().strip() or self.daily_schedule_time or "22:00"
        if not re.fullmatch(r"\d{2}:\d{2}", time_str):
            await self.group.send_msg("❌ 请输入正确的时间，例如：/开启词云每日定时发送 23:59")
            return

        callback_id = self._wordcloud_daily_callback_id()

        async def cb():
            from src.services.registry import service_manager

            service = await service_manager.get_service(self.group.group_id, Services.Wordcloud)
            await service.send_daily_wordcloud()

        register_runtime_callback(callback_id, cb)
        self._sync_daily_schedule_state(
            time_str=time_str,
            callback_id=callback_id,
            enabled=True,
        )
        self.daily_schedule_enabled = True
        self.daily_schedule_time = time_str
        await self.group.send_msg(f"✅ 已开启词云每日定时发送，发送时间为：{time_str}")

    @service_action(cmd="关闭词云每日定时发送", permission=admin_permission(), desc="关闭本群每日词云定时发送")
    @check_enabled
    async def daily_schedule_disable(self):
        task = self._daily_schedule_state()
        if not task:
            await self.group.send_msg("词云每日定时发送未开启")
            return
        self._sync_daily_schedule_state(
            time_str=task.get("schedule", self.daily_schedule_time),
            callback_id=task.get("callback_id", self._wordcloud_daily_callback_id()),
            enabled=False,
        )
        self.daily_schedule_enabled = False
        await self.group.send_msg("✅ 已关闭词云每日定时发送")

__all__ = ["WordcloudService"]
