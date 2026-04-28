import asyncio
import base64
import io
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Iterator

import nonebot
import httpx
from httpx import AsyncClient
from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)
from nonebot.adapters.onebot.v11.helpers import extract_image_urls
from nonebot_plugin_localstore import get_cache_dir
from PIL import Image, ImageDraw, ImageFont

from src.support.core import Services, ai_tool
from src.support.group import wait_for, wait_for_event

from .base import BaseService, config_property, service_message

WHAT_EAT_PATTERN = re.compile(
    r"^(/)?[今|明|后]?[天|日]?(早|中|晚)?(上|午|餐|饭|夜宵|宵夜)吃(什么|啥|点啥)$"
)
WHAT_DRINK_PATTERN = re.compile(
    r"^(/)?[今|明|后]?[天|日]?(早|中|晚)?(上|午|餐|饭|夜宵|宵夜)喝(什么|啥|点啥)$"
)
VIEW_ALL_PATTERN = re.compile(r"^(/)?查[看|寻]?全部(菜[单|品]|饮[料|品])$")
VIEW_PATTERN = re.compile(r"^(/)?查[看|寻]?(菜[单|品]|饮[料|品])[\s]?(.*)?$")
ADD_PATTERN = re.compile(r"^(/)?添[加]?(菜[品|单]|饮[品|料])[\s]?(.*)?$")
DELETE_PATTERN = re.compile(r"^(/)?删[除]?(菜[品|单]|饮[品|料])[\s]?(.*)?$")

_last_recommend_time = 0
_user_count: dict[str, int] = {}
_WHATEAT_CD = 10
_WHATEAT_MAX = 0
_RESOURCE_DOWNLOAD_BASE_URLS = [
    "https://raw.githubusercontent.com/Cvandia/nonebot-plugin-whateat-pic/",
    "https://fastly.jsdelivr.net/gh/Cvandia/nonebot-plugin-whateat-pic@",
    "https://raw.gitmirror.com/Cvandia/nonebot-plugin-whateat-pic/",
    "https://ghproxy.cfd/https:/raw.githubusercontent.com/Cvandia/nonebot-plugin-whateat-pic/",
    "https://ghfast.top/https:/raw.githubusercontent.com/Cvandia/nonebot-plugin-whateat-pic/",
]
_resource_sync_lock: asyncio.Lock | None = None


def _asset_root() -> Path:
    return Path(__file__).resolve().parent.parent / "vendors" / "nonebot_plugin_whateat_pic"


def _resource_root() -> Path:
    return Path(get_cache_dir("nonebot_plugin_whateat_pic"))


def _eat_path() -> Path:
    return _resource_root() / "eat_pic"


def _drink_path() -> Path:
    return _resource_root() / "drink_pic"


def _ensure_resource_dirs() -> None:
    _eat_path().mkdir(parents=True, exist_ok=True)
    _drink_path().mkdir(parents=True, exist_ok=True)


def _get_resource_sync_lock() -> asyncio.Lock:
    global _resource_sync_lock
    if _resource_sync_lock is None:
        _resource_sync_lock = asyncio.Lock()
    return _resource_sync_lock


async def _download_resource_bytes(client: AsyncClient, resource_name: str) -> bytes | None:
    last_url = ""
    for base_url in _RESOURCE_DOWNLOAD_BASE_URLS:
        last_url = f"{base_url}refs/heads/main/res/{resource_name}"
        try:
            response = await client.get(last_url, timeout=20, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            continue
    if last_url:
        logger.warning(f"吃喝推荐资源下载失败: {last_url}")
    return None


async def _sync_whateat_resources() -> dict[str, int]:
    _ensure_resource_dirs()

    async with _get_resource_sync_lock():
        async with AsyncClient() as client:
            content = await _download_resource_bytes(client, "download_list.json")
            if not content:
                return {"downloaded": 0, "existing": 0, "failed": 1}
            try:
                resource_list = json.loads(content.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("吃喝推荐资源清单解析失败")
                return {"downloaded": 0, "existing": 0, "failed": 1}

            download_list: list[tuple[Path, str]] = []
            for resource_type, base_path in (("drink_pic", _drink_path()), ("eat_pic", _eat_path())):
                for item in resource_list.get(resource_type, []):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    download_list.append((base_path / name, f"{resource_type}/{name}"))

            if not download_list:
                return {"downloaded": 0, "existing": 0, "failed": 0}

            stats = {"downloaded": 0, "existing": 0, "failed": 0}
            semaphore = asyncio.Semaphore(10)

            async def _download_single(file_path: Path, resource_name: str) -> None:
                if file_path.exists():
                    stats["existing"] += 1
                    return
                async with semaphore:
                    file_content = await _download_resource_bytes(client, resource_name)
                if file_content is None:
                    stats["failed"] += 1
                    return
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with file_path.open("wb") as handle:
                    handle.write(file_content)
                stats["downloaded"] += 1

            await asyncio.gather(*(_download_single(file_path, resource_name) for file_path, resource_name in download_list))
            return stats


async def _ensure_recommendation_files(menu_type: str) -> list[str]:
    base_path = _eat_path() if menu_type == "eat" else _drink_path()
    files = _list_image_names(base_path)
    if files:
        return files

    stats = await _sync_whateat_resources()
    files = _list_image_names(base_path)
    if files:
        return files

    logger.warning(f"吃喝推荐资源仍为空: type={menu_type}, stats={stats}")
    return []


@nonebot.get_driver().on_startup
async def _prepare_whateat_resources() -> None:
    _ensure_resource_dirs()
    try:
        await _sync_whateat_resources()
    except Exception as exc:
        logger.warning(f"初始化吃喝推荐资源失败: {exc}")


def _bot_nickname() -> str:
    raw_nicknames = getattr(nonebot.get_driver().config, "nickname", ())
    if isinstance(raw_nicknames, str):
        nicknames = [raw_nicknames.strip()] if raw_nicknames.strip() else []
    else:
        nicknames = [str(item).strip() for item in raw_nicknames or [] if str(item).strip()]
    return nicknames[0] if nicknames else "雪豹"


def _list_image_names(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(item.name for item in path.iterdir() if item.is_file())


def _check_cd(last_time: float) -> tuple[bool, float, float]:
    now_time = time.time()
    if now_time - last_time < _WHATEAT_CD:
        return True, _WHATEAT_CD - (now_time - last_time), last_time
    return False, 0, now_time


def _check_max(event: GroupMessageEvent, user_count: dict[str, int]) -> tuple[bool, dict[str, int]]:
    if _WHATEAT_MAX == 0:
        return False, user_count

    user_id = str(event.user_id)
    if user_id not in user_count:
        user_count[user_id] = 0
    if user_count[user_id] < _WHATEAT_MAX:
        user_count[user_id] += 1
        return False, user_count
    return True, user_count


class _MenuRenderer:
    def __init__(self, menu_type: str) -> None:
        self.dish_path = _eat_path() if menu_type == "eat" else _drink_path()
        self.all_dish_name = sorted(item.stem for item in self.dish_path.iterdir() if item.is_file())
        menu_res_root = _asset_root() / "menu_res"
        self.menu_background = Image.open(menu_res_root / "menu_bg.jpg")
        self.font_size = 30
        self.menu_font = ImageFont.truetype(
            str(menu_res_root / "FZSJ-QINGCRJ.TTF"),
            self.font_size,
        )

    @property
    def menu_bg_size(self) -> tuple[int, int]:
        return self.menu_background.size

    def draw_menu(self) -> Iterator[Image.Image]:
        line_num = (self.menu_bg_size[1] - 150) // (self.font_size + 10)
        img_num = len(self.all_dish_name) // line_num + 1
        for index in range(img_num):
            menu_img = self.menu_background.copy()
            draw = ImageDraw.Draw(menu_img)
            for line_index in range(line_num):
                offset = index * line_num + line_index
                if offset >= len(self.all_dish_name):
                    break
                draw.text(
                    ((self.menu_bg_size[0] - 300) // 2, 75 + line_index * (self.font_size + 10)),
                    f"{offset + 1}.{self.all_dish_name[offset]}",
                    font=self.menu_font,
                    fill="black",
                )
            yield menu_img


def _is_admin_or_superuser(event: GroupMessageEvent) -> bool:
    role = getattr(getattr(event, "sender", None), "role", None)
    if role in {"admin", "owner"}:
        return True
    superusers = {str(item) for item in getattr(nonebot.get_driver().config, "superusers", set())}
    return str(event.user_id) in superusers


def _extract_text(event: GroupMessageEvent) -> str:
    return event.get_message().extract_plain_text().strip()


def what_eat_rule(event: GroupMessageEvent) -> bool:
    return WHAT_EAT_PATTERN.fullmatch(_extract_text(event)) is not None


def what_drink_rule(event: GroupMessageEvent) -> bool:
    return WHAT_DRINK_PATTERN.fullmatch(_extract_text(event)) is not None


def view_all_rule(event: GroupMessageEvent) -> bool:
    return VIEW_ALL_PATTERN.fullmatch(_extract_text(event)) is not None


def view_rule(event: GroupMessageEvent) -> bool:
    return VIEW_PATTERN.fullmatch(_extract_text(event)) is not None


def add_rule(event: GroupMessageEvent) -> bool:
    return ADD_PATTERN.fullmatch(_extract_text(event)) is not None


def delete_rule(event: GroupMessageEvent) -> bool:
    return DELETE_PATTERN.fullmatch(_extract_text(event)) is not None


async def send_forward_msg(bot: Bot, event: GroupMessageEvent, name: str, uin: str, msgs: list[Message]):
    def to_json(msg: Message):
        return {"type": "node", "data": {"name": name, "uin": uin, "content": msg}}

    messages = [to_json(msg) for msg in msgs]
    return await bot.call_api("send_group_forward_msg", group_id=event.group_id, messages=messages)


class WhateatService(BaseService):
    service_type = Services.Whateat
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    async def _recommend_random_item(self, event: GroupMessageEvent, *, menu_type: str) -> dict:
        global _last_recommend_time, _user_count

        check_result, remain_time, new_last_time = _check_cd(_last_recommend_time)
        if check_result:
            _last_recommend_time = new_last_time
            message = f"cd冷却中,还有{remain_time}秒"
            await self.group.send_msg(message)
            return {"success": False, "message": message}

        is_max, _user_count = _check_max(event, _user_count)
        if is_max:
            message = random.choice(_MAX_MESSAGES)
            await self.group.send_msg(message)
            return {"success": False, "message": message}

        _last_recommend_time = new_last_time
        files = await _ensure_recommendation_files(menu_type)
        failure_message = "出错啦！没有找到好吃的~" if menu_type == "eat" else "出错啦！没有找到好喝的~"
        success_message = "已发送吃什么推荐" if menu_type == "eat" else "已发送喝什么推荐"
        verb = "吃" if menu_type == "eat" else "喝"
        base_path = _eat_path() if menu_type == "eat" else _drink_path()
        if not files:
            await self.group.send_msg(failure_message)
            return {"success": False, "message": failure_message}

        img_name = random.choice(files)
        img = base_path / img_name
        with open(img, "rb") as handle:
            base64_str = "base64://" + base64.b64encode(handle.read()).decode()
        send_msg = MessageSegment.text(f"{_bot_nickname()}建议你{verb}: \n⭐{img.stem}⭐\n") + MessageSegment.image(base64_str)
        history_summary = f"已发送{verb}什么推荐：{img.stem}"
        try:
            message_result = await nonebot.get_bot().send_group_msg(
                group_id=event.group_id,
                message=send_msg,
            )
            try:
                from src.services._ai.message_bridge import record_group_output

                record_group_output(
                    event.group_id,
                    history_summary,
                    message_result=message_result,
                )
            except Exception:
                pass
        except ActionFailed:
            await self.group.send_msg(failure_message)
            return {"success": False, "message": failure_message}
        return {"success": True, "message": success_message, "data": {"name": img.stem}}

    @staticmethod
    def _build_ai_tool_event(*, user_id: int, group_id: int, message_text: str) -> GroupMessageEvent:
        class _MockEvent:
            def __init__(self):
                self.user_id = user_id
                self.group_id = group_id
                self.self_id = 0
                self.sender = type("Sender", (), {"role": "member"})()
                self._message = Message(message_text)

            def get_message(self):
                return self._message

        return _MockEvent()

    @ai_tool(
        name="recommend_food",
        desc="推荐今天吃什么",
        parameters={"type": "object", "properties": {}, "required": []},
        category="whateat",
        triggers=["今天吃什么", "吃什么"],
    )
    async def recommend_food_tool(self, user_id: int, group_id: int, **kwargs) -> dict:
        if not self.enabled:
            return {"success": False, "message": "吃喝推荐服务未开启"}
        result = await self.recommend_food(
            self._build_ai_tool_event(
                user_id=user_id,
                group_id=group_id,
                message_text="今天吃什么",
            )
        )
        if isinstance(result, dict) and "success" in result:
            return result
        return {"success": True, "message": "已发送吃什么推荐"}

    @ai_tool(
        name="recommend_drink",
        desc="推荐今天喝什么",
        parameters={"type": "object", "properties": {}, "required": []},
        category="whateat",
        triggers=["今天喝什么", "喝什么"],
    )
    async def recommend_drink_tool(self, user_id: int, group_id: int, **kwargs) -> dict:
        if not self.enabled:
            return {"success": False, "message": "吃喝推荐服务未开启"}
        result = await self.recommend_drink(
            self._build_ai_tool_event(
                user_id=user_id,
                group_id=group_id,
                message_text="今天喝什么",
            )
        )
        if isinstance(result, dict) and "success" in result:
            return result
        return {"success": True, "message": "已发送喝什么推荐"}

    @service_message(desc="今天吃什么", rule=what_eat_rule, priority=20, block=True)
    async def recommend_food(self, event: GroupMessageEvent):
        return await self._recommend_random_item(event, menu_type="eat")

    @service_message(desc="今天喝什么", rule=what_drink_rule, priority=20, block=True)
    async def recommend_drink(self, event: GroupMessageEvent):
        return await self._recommend_random_item(event, menu_type="drink")

    @service_message(desc="查看全部菜单", rule=view_all_rule, priority=5, block=True)
    async def view_all_dishes(self, event: GroupMessageEvent):
        matched = VIEW_ALL_PATTERN.fullmatch(_extract_text(event))
        if not matched:
            return

        menu_type = "eat" if matched.group(2) in {"菜单", "菜品"} else "drink"
        try:
            menu = _MenuRenderer(menu_type)
            send_msg_list = [Message(MessageSegment.text("菜单如下："))]
            for img in menu.draw_menu():
                image_io = io.BytesIO()
                img.save(image_io, format="JPEG")
                send_msg_list.append(Message(MessageSegment.image(image_io.getvalue())))
        except OSError:
            await self.group.send_msg("没有找到菜单，请稍后重试")
            return

        await send_forward_msg(
            nonebot.get_bot(),
            event,
            _bot_nickname(),
            str(nonebot.get_bot().self_id),
            send_msg_list,
        )

    @service_message(desc="查看菜品或饮料", rule=view_rule, priority=6, block=True)
    async def view_dish(self, event: GroupMessageEvent):
        matched = VIEW_PATTERN.fullmatch(_extract_text(event))
        if not matched:
            return

        dish_type = "吃的" if matched.group(2) in {"菜单", "菜品"} else "喝的"
        name = (matched.group(3) or "").strip()
        if not name:
            await self.group.send_msg(f"请告诉{_bot_nickname()}具体菜名或者饮品名吧")
            response = await wait_for(30)
            if not response:
                await self.group.send_msg("已取消")
                return
            name = response.strip()

        base_path = _eat_path() if dish_type == "吃的" else _drink_path()
        img = base_path / f"{name}.jpg"
        if not img.exists():
            img = base_path / f"{name}.png"
        if not img.exists():
            await self.group.send_msg("没有找到你所说的，请检查一下菜单吧")
            return

        try:
            await self.group.send_msg(MessageSegment.image(img))
        except ActionFailed:
            await self.group.send_msg("没有找到你所说的，请检查一下菜单吧")

    @service_message(desc="添加菜品或饮料", rule=add_rule, priority=20, block=True)
    async def add_dish(self, event: GroupMessageEvent):
        if not _is_admin_or_superuser(event):
            await self.group.send_msg("⛔ 该操作需要管理员或超级用户权限。")
            return

        matched = ADD_PATTERN.fullmatch(_extract_text(event))
        if not matched:
            return

        raw_type = matched.group(2)
        name = (matched.group(3) or "").strip()
        if not name:
            await self.group.send_msg("⭐请发送名字\n发送“取消”可取消添加")
            response = await wait_for(30)
            if not response or response == "取消":
                await self.group.send_msg("已取消")
                return
            name = response.strip()

        await self.group.send_msg("⭐图片也发给我吧\n发送“取消”可取消添加")
        image_event = await wait_for_event(30)
        if not image_event:
            await self.group.send_msg("已取消")
            return

        image_text = image_event.get_message().extract_plain_text().strip()
        if image_text == "取消":
            await self.group.send_msg("已取消")
            return

        image_urls = extract_image_urls(image_event.get_message())
        if not image_urls:
            await self.group.send_msg("没有找到图片(╯▔皿▔)╯，请稍后重试")
            return

        path = _eat_path() if raw_type in {"菜品", "菜单"} else _drink_path()
        path.mkdir(parents=True, exist_ok=True)
        save_path = path / f"{name}.jpg"
        try:
            async with AsyncClient() as client:
                dish_image = await client.get(url=image_urls[0])
                with open(save_path, "wb") as handle:
                    handle.write(dish_image.content)
        except (OSError, ActionFailed, IndexError, httpx.ConnectError, httpx.ConnectTimeout):
            await self.group.send_msg("添加失败，请稍后重试")
            return

        await self.group.send_msg(
            MessageSegment.text(f"成功添加{raw_type}:{name}\n") + MessageSegment.image(image_urls[0])
        )

    @service_message(desc="删除菜品或饮料", rule=delete_rule, priority=20, block=True)
    async def delete_dish(self, event: GroupMessageEvent):
        if not _is_admin_or_superuser(event):
            await self.group.send_msg("⛔ 该操作需要管理员或超级用户权限。")
            return

        matched = DELETE_PATTERN.fullmatch(_extract_text(event))
        if not matched:
            return

        raw_type = matched.group(2)
        name = (matched.group(3) or "").strip()
        if not name:
            await self.group.send_msg("请告诉我你要删除哪个菜品或饮料,发送“取消”可取消操作")
            response = await wait_for(30)
            if not response or response == "取消":
                await self.group.send_msg("已取消")
                return
            name = response.strip()

        path = _eat_path() if raw_type in {"菜单", "菜品"} else _drink_path()
        candidates = [path / f"{name}.jpg", path / f"{name}.png"]
        target = next((item for item in candidates if item.exists()), None)
        if target is None:
            await self.group.send_msg(f"不存在该{raw_type}，请检查下菜单再重试吧")
            return

        try:
            os.remove(target)
        except OSError:
            await self.group.send_msg(f"不存在该{raw_type}，请检查下菜单再重试吧")
            return

        await self.group.send_msg(f"已成功删除{raw_type}:{name}")


_MAX_MESSAGES = (
    "你今天吃的够多了！不许再吃了(´-ωก`)",
    "吃吃吃，就知道吃，你都吃饱了！明天再来(▼皿▼#)",
    "(*｀へ´*)你猜我会不会再给你发好吃的图片",
    f"没得吃的了，{_bot_nickname()}的食物都被你这坏蛋吃光了！",
    "你在等我给你发好吃的？做梦哦！你都吃那么多了，不许再吃了！ヽ(≧Д≦)ノ",
)

__all__ = ["WhateatService"]
