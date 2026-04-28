"""群聊 AI 助手回复流程。"""

import re
import time
import traceback
from typing import Any, Dict

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.ai import fetch_answers, run_search_spider_and_get_first_result
from src.support.core import make_dict
from src.support.group import get_group_member_identity

from .group_state import GroupStateMixin
from .message_bridge import sync_recent_group_bot_outputs
from .message_utils import build_message_record


_GROUP_ROLE_NAME_MAP = {
    "owner": "群主",
    "admin": "管理员",
    "member": "成员",
}


def _build_member_identity_fallback(event: GroupMessageEvent) -> Dict[str, Any]:
    sender = getattr(event, "sender", None)
    user_id = int(getattr(event, "user_id", 0) or 0)
    display_name = (
        getattr(sender, "card", None)
        or getattr(sender, "nickname", None)
        or f"QQ:{user_id}"
    )
    role_code = str(getattr(sender, "role", None) or "member").strip().lower() or "member"
    return {
        "user_id": user_id,
        "display_name": str(display_name),
        "nickname": str(getattr(sender, "nickname", None) or display_name),
        "card": str(getattr(sender, "card", None) or ""),
        "role_code": role_code,
        "role_name": _GROUP_ROLE_NAME_MAP.get(role_code, role_code or "成员"),
        "title": str(getattr(sender, "title", None) or ""),
    }


class GroupReplyMixin(GroupStateMixin):
    @staticmethod
    def _merge_text_and_media_refs(text: str, media_refs: str) -> str:
        normalized_text = str(text or "").strip()
        normalized_refs = str(media_refs or "").strip()
        if normalized_text and normalized_refs:
            return f"{normalized_text} {normalized_refs}"
        return normalized_text or normalized_refs

    def _build_media_refs_from_message(self, message: Any) -> str:
        if not message:
            return ""

        message_record = build_message_record(message)
        parts: list[str] = []
        for url in message_record.get("image_urls", []):
            image_id = self.register_image(url)
            parts.append(f"[图片:{image_id}]")
        for url in message_record.get("video_urls", []):
            video_id = self.register_video(url)
            parts.append(f"[视频:{video_id}]")
        return " ".join(parts).strip()

    def _build_tool_context(
        self,
        event: GroupMessageEvent,
        service_config: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        service_config = service_config or {}
        service_manager = self._get_service_manager()
        group_db = None
        if service_manager is not None:
            get_group = getattr(service_manager, "get_group", None)
            if callable(get_group):
                try:
                    group_db = getattr(get_group(event.group_id), "db", None)
                except Exception:
                    group_db = None
        context = {
            "group_id": event.group_id,
            "user_id": event.user_id,
            "member_role": getattr(getattr(event, "sender", None), "role", None),
            "bot": self._get_runtime_bot(),
            "image_registry": self._image_registry,
            "video_registry": self._video_registry,
            "ai_assistant": self,
            "service_config": service_config,
            "service_manager": service_manager,
            "group_db": group_db,
            "message": event.get_message().extract_plain_text(),
            "message_id": getattr(event, "message_id", 0),
            "self_id": getattr(event, "self_id", 0),
        }
        if event.reply:
            context["reply_text"] = event.reply.message.extract_plain_text()
            context["reply_message_id"] = getattr(event.reply, "message_id", 0)
            context["reply_message_obj"] = event.reply.message
        return context

    def _resolve_rate_limit_settings(self, service_config: Dict[str, Any] | None = None) -> tuple[bool, int]:
        service_config = service_config or {}
        enabled = service_config.get(
            "rate_limit_enable",
            service_config.get("rate_limit_enabled", self.rate_limit_enabled),
        )
        limit_per_hour = service_config.get("rate_limit_per_hour", self.rate_limit_per_hour)
        try:
            normalized_limit = max(1, int(limit_per_hour))
        except (TypeError, ValueError):
            normalized_limit = self.rate_limit_per_hour
        return bool(enabled), normalized_limit

    async def _build_user_message(
        self,
        event: GroupMessageEvent,
        service_config: Dict[str, Any] = None,
    ) -> str:
        service_config = service_config or {}
        group_mode = service_config.get("group_mode", self.group_mode)

        user_input = self._merge_text_and_media_refs(
            event.get_message().extract_plain_text(),
            self._build_media_refs_from_message(event.get_message()),
        )
        reply_text = ""
        if event.reply:
            reply_text = self._merge_text_and_media_refs(
                event.reply.message.extract_plain_text(),
                self._build_media_refs_from_message(event.reply.message),
            )
        if group_mode:
            try:
                identity = await get_group_member_identity(self._get_runtime_bot(), event)
            except Exception:
                identity = _build_member_identity_fallback(event)
            return self._build_group_user_message(identity, user_input, reply_text=reply_text)
        if reply_text:
            return f"对于你所说的：{reply_text}，我的回复是：{user_input}"
        return user_input

    def _check_rate_limit(self, user_id: int, *, enabled: bool, limit_per_hour: int) -> bool:
        if not enabled:
            return False

        current_time = time.time()
        self.user_reply_history[user_id] = [
            ts for ts in self.user_reply_history[user_id]
            if current_time - ts <= 3600
        ]
        return len(self.user_reply_history[user_id]) >= limit_per_hour

    def _record_reply(self, user_id: int):
        self.user_reply_history[user_id].append(time.time())

    async def _get_response(self, context: Dict[str, Any]) -> str:
        return await self.call_api(context)

    async def _sync_recent_assistant_outputs(self, event: GroupMessageEvent):
        try:
            self_id = int(getattr(event, "self_id", 0) or 0)
        except (TypeError, ValueError):
            self_id = 0
        if not self_id:
            return
        await sync_recent_group_bot_outputs(event.group_id, self_id)

    async def _send_rate_limit_warning(self, event: GroupMessageEvent):
        from src.vendorlibs.cardmaker import CardMaker

        warning_text = self.rate_limit_warning.format(redirect_group=self.redirect_group)
        data = {
            "标题": f"聊天功能使用频率过高：{len(self.user_reply_history[event.user_id])}次/小时",
            "文字": warning_text,
            "图片": "background.png",
        }
        runtime_bot = self._get_runtime_bot()
        if runtime_bot is None:
            await self.send_text(warning_text, record_history=False)
            return
        try:
            await runtime_bot.send_group_msg(
                group_id=event.group_id,
                message=CardMaker(data).create_card(),
            )
        except Exception:
            await self.send_text(warning_text, record_history=False)

    async def reply(self, event: GroupMessageEvent, service_config: Dict[str, Any] = None):
        service_config = service_config or {}
        rate_limit_enable, rate_limit_per_hour = self._resolve_rate_limit_settings(service_config)

        if self._check_rate_limit(
            event.user_id,
            enabled=rate_limit_enable,
            limit_per_hour=rate_limit_per_hour,
        ):
            await self._send_rate_limit_warning(event)
            return

        self._record_reply(event.user_id)
        self.flush_chat_buffer()
        await self._sync_recent_assistant_outputs(event)

        user_message = await self._build_user_message(event, service_config)
        self.add_message(make_dict("user", user_message))

        context = self._build_tool_context(event, service_config)
        response = await self._get_response(context)
        await self.send(response, service_config, record_history=False)

    async def reply_with_zhihu(
        self,
        event: GroupMessageEvent,
        service_config: Dict[str, Any] = None,
    ):
        service_config = service_config or {}
        rate_limit_enable, rate_limit_per_hour = self._resolve_rate_limit_settings(service_config)

        if self.is_searching:
            await self.send("当前有一个问题正在被分析，请等待该问题得到回答后再试。", service_config)
            return

        if self._check_rate_limit(
            event.user_id,
            enabled=rate_limit_enable,
            limit_per_hour=rate_limit_per_hour,
        ):
            await self._send_rate_limit_warning(event)
            return

        user_input = event.get_message().extract_plain_text()
        user_input = re.sub(r"^雪豹[，。！？、；]*", "", user_input)
        self.is_searching = True

        try:
            self._record_reply(event.user_id)
            self.flush_chat_buffer()
            await self._sync_recent_assistant_outputs(event)

            url = await run_search_spider_and_get_first_result(user_input)
            prompt = await fetch_answers(url)

            group_mode = service_config.get("group_mode", self.group_mode)
            if group_mode:
                self.add_message(
                    make_dict(
                        "user",
                        f"[互联网搜索结果]\n{prompt}\n\n请根据以上内容，认真阅读并回答用户问题。",
                    )
                )
                self.add_message(make_dict("user", user_input))
            else:
                self.add_message(make_dict("user", user_input))

            context = self._build_tool_context(event, service_config)
            response = await self._get_response(context)
            await self.send(response, service_config, record_history=False)
        except Exception as exc:
            print(exc)
            traceback.print_exc()
        finally:
            self.is_searching = False


__all__ = ["GroupReplyMixin"]
