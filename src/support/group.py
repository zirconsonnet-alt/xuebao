"""群上下文与交互支撑能力。"""

import os
from pathlib import Path
from pprint import pprint
import re
import time
import traceback
from typing import Any, Dict, Iterable, Optional, Set, Union
import uuid

import aiohttp
import nonebot
from nonebot.adapters.onebot.v11 import GroupRequestEvent, Message, MessageEvent, MessageSegment

from .cache_cleanup import cleanup_group_temp_cache
from .db import GroupDatabase, SqliteMemberStatsRepository, SqliteTopicRepository

_GROUP_MEMBER_INFO_CACHE_TTL_SECONDS = 60.0
_GROUP_MEMBER_INFO_CACHE: Dict[tuple[int, int], tuple[float, Dict[str, Any]]] = {}
_GROUP_ROLE_NAME_MAP = {
    "owner": "群主",
    "admin": "管理员",
    "member": "成员",
}

class GroupStorage:
    def __init__(self, base_dir: Path | str = "data/group_management"):
        self.base_dir = Path(base_dir)

    def ensure_group_dirs(self, group_id: int) -> Dict[str, Path]:
        group_path = self.base_dir / str(group_id)
        temp_path = group_path / "temp"
        laws_path = group_path / "laws"
        custom_path = group_path / "custom"
        temp_path.mkdir(parents=True, exist_ok=True)
        laws_path.mkdir(parents=True, exist_ok=True)
        custom_path.mkdir(parents=True, exist_ok=True)
        return {
            "group_path": group_path,
            "temp_path": temp_path,
            "laws_path": laws_path,
            "custom_path": custom_path,
        }

    def get_law_content(self, group_id: int, law_name: str) -> Dict[str, str | bool]:
        paths = self.ensure_group_dirs(group_id)
        law_file = paths["laws_path"] / f"{law_name}.txt"
        if not law_file.exists():
            return {"ok": False, "text": "", "error": "law_not_found"}
        try:
            content = law_file.read_text(encoding="utf-8")
            return {"ok": True, "text": content}
        except Exception as exc:
            return {"ok": False, "text": "", "error": str(exc)}

    def list_laws(self, group_id: int) -> Set[str]:
        paths = self.ensure_group_dirs(group_id)
        return {file_path.stem for file_path in paths["laws_path"].glob("*.txt")}


async def wait_for(time, block: bool = True):
    from nonebot_plugin_waiter import waiter

    @waiter(waits=["message"], keep_session=True, block=block)
    async def _(event: MessageEvent):
        return event.get_message().extract_plain_text().strip()

    return await _.wait(timeout=time, default=False)


async def wait_for_event(time):
    from nonebot_plugin_waiter import waiter

    @waiter(waits=["message"], keep_session=True, block=False)
    async def _(event: MessageEvent):
        return event

    return await _.wait(timeout=time, default=False)


def get_id(target: str) -> Optional[int]:
    cq_code_match = re.match(r"\[CQ:at,qq=(\d+)]", target)
    if cq_code_match:
        return int(cq_code_match.group(1))
    return None


def build_group_message(msg: Any, *, at_user_id: int | None = None) -> Message:
    message = Message(msg)
    if at_user_id is None:
        return message

    try:
        normalized_user_id = int(at_user_id)
    except (TypeError, ValueError):
        return message
    if normalized_user_id <= 0:
        return message

    rendered_message = Message(MessageSegment.at(normalized_user_id))
    if len(message) > 0:
        rendered_message += MessageSegment.text(" ")
    rendered_message += message
    return rendered_message


def _resolve_any_bot() -> Any | None:
    bots = nonebot.get_bots()
    if bots:
        return next(iter(bots.values()))
    try:
        return nonebot.get_bot()
    except Exception:
        return None


def _resolve_bot_by_self_id(self_id: Any) -> Any | None:
    if self_id is None:
        return None

    bots = nonebot.get_bots()
    target_bot = bots.get(str(self_id))
    if target_bot is not None:
        return target_bot

    fallback_bot = _resolve_any_bot()
    if fallback_bot is not None and str(getattr(fallback_bot, "self_id", "")) == str(self_id):
        return fallback_bot
    return None


def _resolve_event_bot(event: Any) -> Any | None:
    event_bot = getattr(event, "bot", None)
    if event_bot is not None:
        return event_bot

    self_id = getattr(event, "self_id", None)
    if self_id is not None and (target_bot := _resolve_bot_by_self_id(self_id)) is not None:
        return target_bot

    return _resolve_any_bot()


def _resolve_group_member_lookup_args(*args: Any):
    if len(args) == 1:
        event = args[0]
        bot = _resolve_event_bot(event)
    elif len(args) == 2:
        bot, event = args
    else:
        raise TypeError("group member lookup expects (event) or (bot, event)")
    return bot, event


def _build_sender_member_info(event: Any) -> Dict[str, Any]:
    sender = getattr(event, "sender", None)
    return {
        "user_id": getattr(sender, "user_id", None) or getattr(event, "user_id", None),
        "nickname": getattr(sender, "nickname", None) or "",
        "card": getattr(sender, "card", None) or "",
        "role": getattr(sender, "role", None) or "",
        "title": getattr(sender, "title", None) or "",
    }


def _merge_member_info(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _has_sufficient_sender_member_info(info: Dict[str, Any]) -> bool:
    has_name = bool(str(info.get("card") or info.get("nickname") or "").strip())
    has_role = bool(str(info.get("role") or "").strip())
    return has_name and has_role


async def get_group_member_info_cached(
    bot: Any,
    *,
    group_id: int,
    user_id: int,
    fallback: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cache_key = (int(group_id), int(user_id))
    now = time.monotonic()
    cached = _GROUP_MEMBER_INFO_CACHE.get(cache_key)
    stale_info = cached[1] if cached else {}
    if cached and cached[0] > now:
        return _merge_member_info(cached[1], fallback or {})

    try:
        member_info = await bot.get_group_member_info(
            user_id=user_id,
            group_id=group_id,
        )
    except Exception:
        fallback_info = _merge_member_info(stale_info, fallback or {})
        if fallback_info:
            return fallback_info
        raise

    normalized_info = _merge_member_info(member_info if isinstance(member_info, dict) else {}, fallback or {})
    _GROUP_MEMBER_INFO_CACHE[cache_key] = (
        now + _GROUP_MEMBER_INFO_CACHE_TTL_SECONDS,
        dict(normalized_info),
    )
    return normalized_info


async def get_group_member_identity(*args: Any) -> Dict[str, Any]:
    bot, event = _resolve_group_member_lookup_args(*args)
    fallback_info = _build_sender_member_info(event)
    group_id = int(getattr(event, "group_id", 0) or 0)
    user_id = int(getattr(event, "user_id", 0) or 0)

    if _has_sufficient_sender_member_info(fallback_info):
        member_info = fallback_info
    elif bot is None:
        member_info = fallback_info
    else:
        member_info = await get_group_member_info_cached(
            bot,
            group_id=group_id,
            user_id=user_id,
            fallback=fallback_info,
        )

    normalized_user_id = int(member_info.get("user_id") or user_id or 0)
    display_name = str(member_info.get("card") or member_info.get("nickname") or f"QQ:{normalized_user_id}")
    nickname = str(member_info.get("nickname") or display_name)
    role_code = str(member_info.get("role") or "member").strip().lower() or "member"
    return {
        "user_id": normalized_user_id,
        "display_name": display_name,
        "nickname": nickname,
        "card": str(member_info.get("card") or ""),
        "role_code": role_code,
        "role_name": _GROUP_ROLE_NAME_MAP.get(role_code, role_code or "成员"),
        "title": str(member_info.get("title") or ""),
    }


async def get_name_simple(*args: Any):
    identity = await get_group_member_identity(*args)
    return identity.get("display_name") or "Unknown User"


async def get_name_by_id(group_id: int, user_id: int):
    bot = _resolve_any_bot()
    if bot is None:
        return f"QQ:{user_id}"
    user_info = await get_group_member_info_cached(
        bot,
        group_id=group_id,
        user_id=user_id,
    )
    return user_info.get("card") or user_info.get("nickname", "Unknown User")


def _get_card_field(card_data: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in card_data and card_data.get(key) not in (None, ""):
            return card_data.get(key)
    return default


def _normalize_card_sections(card_data: Dict[str, Any]) -> list[Dict[str, Any]]:
    sections = _get_card_field(card_data, "sections", "分组", default=[])
    if isinstance(sections, dict):
        sections = [sections]
    if not isinstance(sections, list):
        sections = []

    normalized: list[Dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        items = section.get("items") or section.get("项目") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            items = []
        normalized.append(
            {
                "title": section.get("title") or section.get("标题") or "",
                "description": section.get("description") or section.get("描述") or "",
                "items": [item for item in items if isinstance(item, dict)],
            }
        )

    if normalized:
        return normalized

    items = _get_card_field(card_data, "items", "项目", default=[])
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, list) and items:
        return [{"title": "", "description": "", "items": [item for item in items if isinstance(item, dict)]}]
    return []


def format_card_fallback_text(card_data: Dict[str, Any]) -> str:
    if not isinstance(card_data, dict):
        return str(card_data or "")

    title = str(_get_card_field(card_data, "title", "标题", default="")).strip()
    subtitle = str(_get_card_field(card_data, "subtitle", "副标题", default="")).strip()
    text = str(_get_card_field(card_data, "text", "文字", default="")).strip()
    hint = str(_get_card_field(card_data, "hint", "提示", "footer", "底部", default="")).strip()
    sections = _normalize_card_sections(card_data)

    if text:
        lines = [text]
    else:
        lines: list[str] = []
        for section in sections:
            section_title = str(section.get("title") or "").strip()
            section_description = str(section.get("description") or "").strip()
            if section_title:
                lines.append(f"【{section_title}】")
            if section_description:
                lines.append(section_description)
            for item in section.get("items") or []:
                index = str(item.get("index") or item.get("序号") or "").strip()
                item_title = str(item.get("title") or item.get("标题") or "").strip()
                item_description = str(item.get("description") or item.get("描述") or "").strip()
                item_status = str(item.get("status") or item.get("状态") or "").strip()

                prefix = f"{index}. " if index else "- "
                line = prefix + (item_title or "未命名项")
                if item_status:
                    line += f" [{item_status}]"
                if item_description:
                    line += f"：{item_description}"
                lines.append(line)

    output_lines = []
    if title:
        output_lines.append(title)
    if subtitle:
        output_lines.append(subtitle)
    if lines:
        output_lines.append("\n".join(lines))
    if hint:
        output_lines.append(hint)
    return "\n\n".join(line for line in output_lines if line).strip()


async def render_card_message(card_data: Dict[str, Any]) -> Any:
    from src.vendorlibs.cardmaker.html_card import HtmlCardMaker

    return await HtmlCardMaker(card_data).create_card()


async def run_flow(group: Any, flow: dict) -> None:
    try:
        routes = flow.get("routes", {})
        card_data = dict(flow or {})
        try:
            result = await render_card_message(card_data)
        except Exception as exc:
            print(exc)
            fallback_text = format_card_fallback_text(card_data)
            await group.send_msg(fallback_text or "❌ 卡片渲染失败")
        else:
            await group.send_msg(result)

        if not routes:
            return

        timeout = flow.get("timeout", 60)
        response = await wait_for(timeout)
        if not response or response.strip().lower() == "退出":
            await group.send_msg("❌ 已取消")
            return

        cmd = response.strip()
        if cmd not in routes:
            await group.send_msg("❌ 无效序号，请重新使用该指令")
            return

        target = routes[cmd]
        if isinstance(target, dict):
            await run_flow(group, target)
            return

        await target()
    except Exception as exc:
        print(exc)
        await group.send_msg("❌ 操作超时或出错")


class NoneBotGroupGateway:
    def __init__(self, preferred_self_id: Any | None = None):
        self._preferred_self_id = str(preferred_self_id) if preferred_self_id not in (None, "") else None

    def set_preferred_self_id(self, self_id: Any | None) -> None:
        if self_id in (None, ""):
            return
        self._preferred_self_id = str(self_id)

    def _bot(self):
        bot = _resolve_bot_by_self_id(self._preferred_self_id)
        if bot is None:
            bot = _resolve_any_bot()
        if bot is None:
            raise ValueError("There are no bots to get.")
        return bot

    @staticmethod
    def _extract_message_id(message_result: Any) -> Optional[int]:
        if isinstance(message_result, dict):
            raw_message_id = message_result.get("message_id") or message_result.get("messageId")
        else:
            raw_message_id = getattr(message_result, "message_id", None)

        if raw_message_id is None:
            return None

        try:
            return int(raw_message_id)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _bridge_ai_output(cls, group_id: int, message: Any, message_result: Any = None) -> None:
        try:
            from src.services._ai.message_bridge import record_group_output

            record_group_output(
                group_id,
                message,
                message_id=cls._extract_message_id(message_result),
            )
        except Exception:
            return

    def get_self_id(self) -> int:
        try:
            return int(self._bot().self_id)
        except Exception:
            return int(str(self._bot().self_id))

    async def send_msg(
        self,
        group_id: int,
        msg: Any,
        *,
        at_user_id: int | None = None,
    ) -> None:
        rendered_message = build_group_message(msg, at_user_id=at_user_id)
        message_result = await self._bot().send_group_msg(group_id=group_id, message=rendered_message)
        self._bridge_ai_output(group_id, rendered_message, message_result)

    async def delete_msg(self, message_id: int) -> None:
        await self._bot().delete_msg(message_id)

    async def set_msg(self, message_id: int) -> None:
        await self._bot().set_essence_msg(message_id=message_id)

    async def ban(self, group_id: int, user_id: int, duration: int) -> None:
        await self._bot().set_group_ban(group_id=group_id, user_id=user_id, duration=duration)

    async def whole_ban(self, group_id: int, enable: bool) -> None:
        await self._bot().set_group_whole_ban(group_id=group_id, enable=enable)

    async def get_group_member_info(self, group_id: int, user_id: int) -> Any:
        return await self._bot().get_group_member_info(group_id=group_id, user_id=user_id)

    async def get_group_member_list(self, group_id: int) -> Any:
        return await self._bot().get_group_member_list(group_id=group_id)

    async def send_forward_msg(self, group_id: int, nodes: Any) -> None:
        message_result = await self._bot().send_forward_msg(
            message_type="group",
            group_id=group_id,
            messages=nodes,
        )
        self._bridge_ai_output(group_id, nodes, message_result)

    async def set_group_add(
        self,
        flag: str,
        sub_type: str,
        approve: bool,
        reason: str | None,
    ) -> None:
        await self._bot().set_group_add_request(
            flag=flag,
            sub_type=sub_type,
            approve=approve,
            reason=reason,
        )

    async def send_notice(self, group_id: int, msg: Any) -> None:
        await self._bot()._send_group_notice(group_id=group_id, content=msg)

    async def del_notice(self, group_id: int, notice_id: int) -> None:
        await self._bot()._del_group_notice(group_id=group_id, notice_id=notice_id)

    async def get_notice(self, group_id: int) -> Any:
        return await self._bot()._get_group_notice(group_id=group_id)

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> None:
        await self._bot().set_group_admin(group_id=group_id, user_id=user_id, enable=enable)

    async def delete_file(self, group_id: int, file_id: str, busid: int) -> None:
        await self._bot().delete_group_file(group_id=group_id, file_id=file_id, busid=busid)

    async def upload_file(self, group_id: int, path: str, name: str, folder_id: str) -> None:
        await self._bot().upload_group_file(group_id=group_id, file=path, name=name, folder=folder_id)

    async def move_file(
        self,
        group_id: int,
        file_id: str,
        current_parent_directory: str,
        target_parent_directory: str,
    ) -> None:
        await self._bot().move_group_file(
            group_id=group_id,
            file_id=file_id,
            current_parent_directory=current_parent_directory,
            target_parent_directory=target_parent_directory,
        )

    async def get_group_file_url(self, group_id: int, file_id: str, busid: int) -> Dict[str, Any]:
        return await self._bot().get_group_file_url(group_id=group_id, file_id=file_id, busid=busid)

    async def get_group_root_files(self, group_id: int) -> Dict[str, Any]:
        return await self._bot().get_group_root_files(group_id=group_id)

    async def get_group_files_by_folder(
        self,
        group_id: int,
        folder_id: str,
        file_count: int,
    ) -> Dict[str, Any]:
        return await self._bot().get_group_files_by_folder(
            group_id=group_id,
            folder_id=folder_id,
            file_count=file_count,
        )

    async def create_group_file_folder(
        self,
        group_id: int,
        folder_name: str,
        parent_id: str,
    ) -> Dict[str, Any]:
        return await self._bot().create_group_file_folder(
            group_id=group_id,
            folder_name=folder_name,
            parent_id=parent_id,
        )

    async def get_group_msg_history(
        self,
        group_id: int,
        count: int,
        message_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        payloads = []
        if message_seq is not None:
            payloads.append({"group_id": group_id, "message_seq": message_seq, "count": count})
        payloads.extend(
            [
                {"group_id": group_id, "count": count},
                {"group_id": group_id, "message_seq": 0, "count": count},
                {"group_id": group_id, "message_seq": -1, "count": count},
            ]
        )
        last_error = None
        for payload in payloads:
            try:
                return await self._bot().call_api("get_group_msg_history", **payload)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return {}

    async def kick(self, group_id: int, user_id: int) -> None:
        await self._bot().set_group_kick(group_id=group_id, user_id=user_id)

    async def set_group_special_title(
        self,
        group_id: int,
        user_id: int,
        special_title: str,
    ) -> None:
        await self._bot().set_group_special_title(
            group_id=group_id,
            user_id=user_id,
            special_title=special_title,
        )


class Group:
    def __init__(
        self,
        group_id: int,
        gateway: Any | None = None,
        storage: GroupStorage | None = None,
    ):
        self._is_voting = False
        self.group_id = group_id
        self.gateway = gateway or NoneBotGroupGateway()
        self.storage = storage or GroupStorage()
        self.db: GroupDatabase = GroupDatabase(group_id)
        paths = self.storage.ensure_group_dirs(group_id)
        self.group_path = paths["group_path"]
        self.temp_path = paths["temp_path"]
        self.laws_path = paths["laws_path"]
        self.custom_path = paths["custom_path"]

    def __eq__(self, other):
        return self.group_id == other.group_id

    def __hash__(self):
        return self.group_id

    @property
    def is_voting(self) -> bool:
        return self._is_voting

    def set_voting(self, value: bool):
        self._is_voting = value

    @property
    def self_id(self) -> int:
        return self.gateway.get_self_id()

    async def send_msg(self, msg: Union[Message, str], *, at_user_id: int | None = None):
        await self.gateway.send_msg(self.group_id, msg, at_user_id=at_user_id)

    async def delete_msg(self, mid: int):
        await self.gateway.delete_msg(mid)

    async def set_msg(self, mid: int):
        await self.gateway.set_msg(mid)

    async def set_special_title(self, user_id: int, special_title: str):
        await self.gateway.set_group_special_title(self.group_id, user_id, special_title)

    async def ban(self, user_id: int, duration: int):
        await self.gateway.ban(self.group_id, user_id, duration)

    async def whole_ban(self):
        await self.gateway.whole_ban(self.group_id, True)

    async def release_ban(self):
        await self.gateway.whole_ban(self.group_id, False)

    async def get_group_member_info(self, user_id: int):
        return await self.gateway.get_group_member_info(self.group_id, user_id)

    async def get_group_member_list(self):
        return await self.gateway.get_group_member_list(self.group_id)

    async def send_forward_msg(self, nodes):
        await self.gateway.send_forward_msg(self.group_id, nodes)

    async def set_group_add(self, event: GroupRequestEvent, value, reason=None):
        await self.gateway.set_group_add(event.flag, event.sub_type, value, reason)

    async def send_notice(self, msg: Union[Message, str]):
        await self.gateway.send_notice(self.group_id, msg)

    async def del_notice(self, notice_id: int):
        await self.gateway.del_notice(self.group_id, notice_id)

    async def get_notice(self):
        return await self.gateway.get_notice(self.group_id)

    async def set_group_admin(self, user_id: int, enable: bool):
        await self.gateway.set_group_admin(self.group_id, user_id, enable)

    async def delete_file(self, file):
        await self.gateway.delete_file(self.group_id, file["file_id"], file["busid"])

    @staticmethod
    def _normalize_folder(folder: Any) -> Dict[str, Any]:
        if isinstance(folder, dict):
            normalized = dict(folder)
            folder_id = normalized.get("folder")
            if not folder_id:
                folder_id = normalized.get("folder_id") or normalized.get("id")
            folder_info = normalized.get("folder_info")
            if not folder_id and isinstance(folder_info, dict):
                folder_id = folder_info.get("folder") or folder_info.get("folder_id") or folder_info.get("id")
                for key, value in folder_info.items():
                    normalized.setdefault(key, value)
            if folder_id:
                normalized["folder"] = folder_id
            return normalized
        return {"folder": str(folder)}

    def _resolve_folder_id(self, folder: Any) -> str:
        normalized = self._normalize_folder(folder)
        folder_id = normalized.get("folder")
        if not folder_id:
            raise KeyError("folder")
        return str(folder_id)

    async def upload_file(self, path, name, folder):
        await self.gateway.upload_file(
            self.group_id,
            str(os.path.abspath(path)),
            name,
            self._resolve_folder_id(folder),
        )

    async def search_file(self, file_id: str):
        files = await self.get_files()
        for file in files:
            if file["file_id"] == file_id:
                return file
        return None

    async def move_file(self, file_id, current, target):
        await self.gateway.move_file(self.group_id, file_id, current, target)

    async def download_file(self, file):
        try:
            url_info = await self.gateway.get_group_file_url(
                self.group_id,
                file["file_id"],
                file["busid"],
            )
            download_url = url_info["url"]
            unique_name = f"{uuid.uuid4()}{Path(file['file_name']).suffix}"
            save_path = self.group_path / "temp" / unique_name
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(download_url) as response:
                    response.raise_for_status()
                    with save_path.open("wb") as f:
                        f.write(await response.read())
            cleanup_group_temp_cache(self.group_id, protected_paths=[save_path])
            return save_path
        except Exception as e:
            print(e)
            print(traceback.print_exc())
            return None

    @staticmethod
    async def get_user_img(user_id: int) -> str:
        return f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=0"

    async def get_resent_file_url(self):
        result = await self.gateway.get_group_root_files(self.group_id)
        file = result["files"][0]
        if not file["file_name"].lower().endswith((".wav", ".mp3")):
            return None, None
        result = await self.gateway.get_group_file_url(
            self.group_id,
            file["file_id"],
            file["busid"],
        )
        return file["file_name"], result["url"]

    async def get_resent_file(self, user_id: int = None):
        result = await self.gateway.get_group_root_files(self.group_id)
        if not user_id:
            return result["files"][0]

        file = None
        for item in result["files"]:
            pprint(item)
            if item["uploader"] == user_id and item["file_name"].lower().endswith((".wav", ".mp3")):
                file = item
        return file

    async def get_files(self):
        result = await self.gateway.get_group_root_files(self.group_id)
        return result.get("files", [])

    async def get_message_history(self, count: int = 20, message_seq: Optional[int] = None):
        return await self.gateway.get_group_msg_history(
            self.group_id,
            count=count,
            message_seq=message_seq,
        )

    async def get_works(self, folder):
        result = await self.gateway.get_group_files_by_folder(
            self.group_id,
            self._resolve_folder_id(folder),
            file_count=1000,
        )
        return result.get("files", [])

    async def get_folders(self):
        result = await self.gateway.get_group_root_files(self.group_id)
        return result.get("folders", [])

    async def get_folder(self, name: str):
        folders = await self.gateway.get_group_root_files(self.group_id)
        for folder in folders.get("folders", []):
            if folder["folder_name"] == name:
                return self._normalize_folder(folder)
        created = await self.gateway.create_group_file_folder(self.group_id, name, parent_id="/")
        return self._normalize_folder(created)

    async def kick(self, user_id: int):
        await self.gateway.kick(self.group_id, user_id)

    def get_law_content(self, law_name: str) -> Dict:
        return self.storage.get_law_content(self.group_id, law_name)

    def get_all_laws(self) -> Set[str]:
        return self.storage.list_laws(self.group_id)


class GroupManager:
    _instance = None
    from threading import Lock as _Lock

    _lock = _Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_group(cls, group_id: int, self_id: Any | None = None):
        return group_context_factory.get_group(group_id, self_id=self_id)

    @property
    def groups(self):
        return group_context_factory.contexts


class GroupContext:
    def __init__(
        self,
        group_id: int,
        *,
        gateway: Optional[Any] = None,
        storage: Optional[GroupStorage] = None,
    ):
        from src.services.vote import ApproveTopicAndRefreshNoticeUseCase

        self.group = Group(group_id, gateway=gateway, storage=storage)
        self.group_id = self.group.group_id
        self.gateway = self.group.gateway
        self.storage = self.group.storage
        self.db = self.group.db

        self.topic_repo = SqliteTopicRepository(self.db)
        self.member_stats_repo = SqliteMemberStatsRepository(self.db)
        self._approve_topic_use_case = ApproveTopicAndRefreshNoticeUseCase(
            topic_repo=self.topic_repo,
            member_stats_repo=self.member_stats_repo,
            group_gateway=self.gateway,
        )

    async def process_group_notice(
        self,
        new_content_str: str,
        proposer_id: int,
        joiners: list[int],
    ):
        await self._approve_topic_use_case.execute(
            group_id=self.group_id,
            proposer_id=proposer_id,
            content=new_content_str,
            joiners=joiners,
        )

    def __getattr__(self, name: str):
        return getattr(self.group, name)


class GroupContextFactory:
    def __init__(self):
        from threading import Lock

        self._lock = Lock()
        self._contexts: Dict[int, GroupContext] = {}

    def get_group(self, group_id: int, self_id: Any | None = None) -> GroupContext:
        with self._lock:
            if group_id not in self._contexts:
                self._contexts[group_id] = GroupContext(
                    group_id,
                    gateway=NoneBotGroupGateway(preferred_self_id=self_id),
                )
            context = self._contexts[group_id]
            gateway = getattr(context, "gateway", None)
            if self_id not in (None, "") and hasattr(gateway, "set_preferred_self_id"):
                gateway.set_preferred_self_id(self_id)
            return context

    def all_groups(self) -> Iterable[GroupContext]:
        return list(self._contexts.values())

    @property
    def contexts(self) -> Dict[int, GroupContext]:
        return self._contexts


group_context_factory = GroupContextFactory()


