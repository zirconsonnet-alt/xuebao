import re
import time as t
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import nonebot
from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.support.core import Services
from src.support.group import run_flow

from .base import BaseService, check_enabled, config_property, service_action

TIME_TYPES = {"今日", "昨日", "本周", "上周", "本月", "上月", "年度", "历史"}


@dataclass
class DialectlistArgs:
    group_id: Optional[str] = None
    keyword: Optional[str] = None
    time_type: Optional[str] = None
    time_range: Optional[str] = None


def _parse_flags(raw: str) -> DialectlistArgs:
    tokens = [item for item in raw.strip().split() if item]
    result = DialectlistArgs()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"-g", "--group_id"} and index + 1 < len(tokens):
            result.group_id = tokens[index + 1]
            index += 2
            continue
        if token in {"-k", "--keyword"} and index + 1 < len(tokens):
            result.keyword = tokens[index + 1]
            index += 2
            continue
        if result.time_type is None and token in TIME_TYPES:
            result.time_type = token
            index += 1
            continue
        if result.time_range is None:
            result.time_range = token
            index += 1
            continue
        index += 1
    return result


def _extract_at_user_id(event: GroupMessageEvent) -> Optional[str]:
    for seg in event.get_message():
        if getattr(seg, "type", "") == "at":
            qq = seg.data.get("qq")
            if qq and qq != "all":
                return str(qq)
    return None


def _extract_first_number(raw: str) -> Optional[str]:
    matched = re.search(r"\b(\d{5,})\b", raw)
    return matched.group(1) if matched else None


def _get_time_range_by_type(now: datetime, time_type: str) -> tuple[Optional[datetime], Optional[datetime]]:
    if time_type == "今日":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if time_type == "昨日":
        stop = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = stop - timedelta(days=1)
        return start, stop
    if time_type == "本周":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        return start, now
    if time_type == "上周":
        stop = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        start = stop - timedelta(days=7)
        return start, stop
    if time_type == "本月":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if time_type == "上月":
        stop = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (stop - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, stop
    if time_type == "年度":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if time_type == "历史":
        return None, None
    raise ValueError(f"未知时间类型：{time_type}")


def _parse_history_range(now: datetime, raw: str, get_dt) -> tuple[Optional[datetime], Optional[datetime]]:
    raw = raw.strip()
    if not raw:
        return None, None
    if "~" in raw:
        left, right = (item.strip() for item in raw.split("~", 1))
        if not left or not right:
            raise ValueError("时间段格式应为：开始~结束")
        start = get_dt(left)
        stop = get_dt(right)
        if stop <= start:
            raise ValueError("结束时间必须晚于开始时间")
        return start, stop
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        start = get_dt(f"{raw}T00:00:00")
        stop = start + timedelta(days=1)
        return start, stop
    start = get_dt(raw)
    return start, now


def _make_rank_action(time_type: str):
    @service_action(
        cmd=f"{time_type}B话榜",
        aliases={f"{time_type}废话榜"},
        need_arg=True,
        desc=f"查看{time_type}B话榜（支持：-g 群号 -k 关键词）",
        tool_callable=True,
    )
    @check_enabled
    async def _action(self, event: GroupMessageEvent, arg: Message):
        raw = arg.extract_plain_text().strip()
        parsed = _parse_flags(raw)
        from src.vendors.nonebot_plugin_dialectlist.time import (
            get_datetime_fromisoformat_with_timezone,
            get_datetime_now_with_timezone,
        )

        now = get_datetime_now_with_timezone()
        start, stop = _get_time_range_by_type(now, time_type)
        if time_type == "历史":
            try:
                start, stop = _parse_history_range(
                    now,
                    parsed.time_range or "",
                    get_datetime_fromisoformat_with_timezone,
                )
            except ValueError as exc:
                await self.group.send_msg(f"❌ {exc}\n示例：/{time_type}B话榜 2026-02-01~2026-02-05 -k 关键词")
                return

        group_id = parsed.group_id or str(event.group_id)
        await self._send_rank(
            event=event,
            group_id=str(group_id),
            keyword=parsed.keyword,
            start=start,
            stop=stop,
        )

    return _action


class DialectlistService(BaseService):
    service_type = Services.Dialectlist
    default_config = {"enabled": True}
    enabled = config_property("enabled")

    async def _ensure_deps(self):
        require("nonebot_plugin_chatrecorder")
        require("nonebot_plugin_apscheduler")
        require("nonebot_plugin_htmlrender")
        require("nonebot_plugin_userinfo")
        require("nonebot_plugin_alconna")
        require("nonebot_plugin_uninfo")
        require("nonebot_plugin_cesaa")
        require("nonebot_plugin_saa")

        import nonebot_plugin_saa as saa

        saa.enable_auto_select_bot()

    async def _send_rank(
        self,
        *,
        event: GroupMessageEvent,
        group_id: str,
        keyword: Optional[str],
        start: Optional[datetime],
        stop: Optional[datetime],
    ):
        await self._ensure_deps()

        import nonebot_plugin_saa as saa
        from src.vendors.nonebot_plugin_dialectlist.config import plugin_config
        from src.vendors.nonebot_plugin_dialectlist.time import get_datetime_now_with_timezone
        from src.vendors.nonebot_plugin_dialectlist.utils import (
            get_rank_image,
            get_user_infos,
            get_user_message_counts,
            got_rank,
            persist_id2user_id,
        )

        dt_now = get_datetime_now_with_timezone()
        start = start or dt_now.replace(year=1970, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        stop = stop or dt_now

        start_time = t.time()
        raw_rank = await get_user_message_counts(
            keyword=keyword,
            scene_ids=[group_id],
            types=["message"],
            time_start=start,
            time_stop=stop,
            exclude_user_ids=plugin_config.excluded_people,
        )
        if not raw_rank:
            await saa.Text("没有获取到排行榜数据哦，请确认时间范围和群号是否正确或者关键词是否存在~").finish(reply=True)
            return

        rank = got_rank(raw_rank)
        ids = await persist_id2user_id([int(item[0]) for item in rank])
        for index in range(len(rank)):
            rank[index][0] = str(ids[index])

        rank2 = await get_user_infos(nonebot.get_bot(), event, rank)
        string = ""
        if plugin_config.show_text_rank:
            string += f"关于{keyword}的话痨榜结果：\n" if keyword else "话痨榜：\n"
            for item in rank2:
                string += plugin_config.string_format.format(
                    index=item.user_index,
                    nickname=item.user_nickname,
                    chatdatanum=item.user_bnum,
                )

        msg = saa.Text(string) if string else None
        if plugin_config.visualization:
            image = await get_rank_image(rank2)
            msg = (msg or saa.Text("")) + saa.Image(image)

        if plugin_config.suffix:
            timecost = t.time() - start_time
            msg = (msg or saa.Text("")) + saa.Text(plugin_config.string_suffix.format(timecost=timecost))

        if not msg:
            await saa.Text("你把可视化都关了哪来的排行榜？").finish(reply=True)
            return

        if plugin_config.aggregate_transmission:
            await saa.AggregatedMessageFactory([msg]).finish()
            return
        await msg.finish(reply=True)

    @service_action(
        cmd="B话榜",
        aliases={"废话榜"},
        need_arg=True,
        desc="查看 B话榜（支持：今日/昨日/本周/上周/本月/上月/年度/历史 + -g 群号 + -k 关键词）",
        tool_callable=True,
    )
    @check_enabled
    async def rank(self, event: GroupMessageEvent, arg: Message):
        raw = arg.extract_plain_text().strip()
        parsed = _parse_flags(raw)

        from src.vendors.nonebot_plugin_dialectlist.time import (
            get_datetime_fromisoformat_with_timezone,
            get_datetime_now_with_timezone,
        )

        now = get_datetime_now_with_timezone()
        time_type = parsed.time_type or "历史"
        start, stop = _get_time_range_by_type(now, time_type)
        if time_type == "历史":
            try:
                start, stop = _parse_history_range(
                    now,
                    parsed.time_range or "",
                    get_datetime_fromisoformat_with_timezone,
                )
            except ValueError as exc:
                await self.group.send_msg(f"❌ {exc}\n示例：/B话榜 历史 2026-02-01~2026-02-05 -k 关键词")
                return

        group_id = parsed.group_id or str(event.group_id)
        await self._send_rank(
            event=event,
            group_id=str(group_id),
            keyword=parsed.keyword,
            start=start,
            stop=stop,
        )

    今日B话榜 = _make_rank_action("今日")
    昨日B话榜 = _make_rank_action("昨日")
    本周B话榜 = _make_rank_action("本周")
    上周B话榜 = _make_rank_action("上周")
    本月B话榜 = _make_rank_action("本月")
    上月B话榜 = _make_rank_action("上月")
    年度B话榜 = _make_rank_action("年度")
    历史B话榜 = _make_rank_action("历史")

    @service_action(
        cmd="看看B话",
        aliases={"kkb"},
        need_arg=True,
        desc="查看某人在某群的 B话数量（支持：@某人/QQ号 + -g 群号 + -k 关键词）",
        tool_callable=True,
    )
    @check_enabled
    async def kkb(self, event: GroupMessageEvent, arg: Message):
        await self._ensure_deps()

        import nonebot_plugin_saa as saa
        from src.vendors.nonebot_plugin_dialectlist.config import plugin_config
        from src.vendors.nonebot_plugin_dialectlist.utils import get_user_message_counts, got_rank

        raw = arg.extract_plain_text().strip()
        parsed = _parse_flags(raw)
        user_id = _extract_at_user_id(event) or _extract_first_number(raw)
        if not user_id:
            await self.group.send_msg("❌ 请 @ 某人或提供 QQ 号，例如：/看看B话 @某人 -k 关键词")
            return

        group_id = parsed.group_id or str(event.group_id)
        data = await get_user_message_counts(
            keyword=parsed.keyword,
            scene_ids=[str(group_id)],
            user_ids=[str(user_id)],
            types=["message"],
            exclude_user_ids=plugin_config.excluded_people,
        )
        rank = got_rank(data)
        count = rank[0][1] if rank else 0
        keyword = parsed.keyword or ""
        await saa.Text(f"该用户在群“{group_id}”关于“{keyword}”的B话数量为{count}。").send(reply=True)

__all__ = ["DialectlistService"]
