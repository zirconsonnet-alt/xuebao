"""AI 服务消息与通知处理。"""

import random
from typing import Any

import nonebot
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PokeNotifyEvent

from src.services.base import service_message, service_notice
from src.support.group import get_group_member_identity

from .assistant import extract_video_urls, is_player_in_werewolf_game


def _is_essence_reaction_message(event: GroupMessageEvent) -> bool:
    if not getattr(event, "reply", None):
        return False

    message = event.get_message()
    if len(message) != 1:
        return False

    segment: Any = message[0]
    if getattr(segment, "type", None) != "face":
        return False

    try:
        return int((getattr(segment, "data", None) or {}).get("id", -1)) == 63
    except (TypeError, ValueError):
        return False


def _build_member_identity_fallback(event: GroupMessageEvent) -> dict[str, Any]:
    sender = getattr(event, "sender", None)
    user_id = int(getattr(event, "user_id", 0) or 0)
    display_name = (
        getattr(sender, "card", None)
        or getattr(sender, "nickname", None)
        or f"QQ:{user_id}"
    )
    role_code = str(getattr(sender, "role", None) or "member").strip().lower() or "member"
    role_name_map = {
        "owner": "群主",
        "admin": "管理员",
        "member": "成员",
    }
    return {
        "user_id": user_id,
        "display_name": str(display_name),
        "nickname": str(getattr(sender, "nickname", None) or display_name),
        "card": str(getattr(sender, "card", None) or ""),
        "role_code": role_code,
        "role_name": role_name_map.get(role_code, role_code or "成员"),
        "title": str(getattr(sender, "title", None) or ""),
    }


class AIServiceHandlerMixin:
    def _get_trigger_character_name(self, msg_text: str, ai_assistant) -> str | None:
        for name in ai_assistant.get_character_names():
            if msg_text.startswith(name):
                return name
        return None

    @service_message(desc="处理AI聊天消息", priority=2, block=True)
    async def handle_ai_message(self, event: GroupMessageEvent, bot: Bot | None = None):
        if not self.enabled:
            return

        ai_assistant = self.get_ai_assistant(event)
        if hasattr(ai_assistant, "_bind_runtime_bot"):
            ai_assistant._bind_runtime_bot(bot)
        if event.user_id in ai_assistant.black_list:
            return
        if is_player_in_werewolf_game(event.user_id):
            return

        command_start = nonebot.get_driver().config.command_start
        msg_text = event.get_message().extract_plain_text()
        if any(msg_text.startswith(cmd) for cmd in command_start):
            return
        if _is_essence_reaction_message(event):
            return

        trigger_character_name = self._get_trigger_character_name(msg_text, ai_assistant)
        if trigger_character_name and trigger_character_name != ai_assistant.character.name:
            await ai_assistant.switch_character(trigger_character_name)
            return

        runtime_bot = bot
        if runtime_bot is None and hasattr(ai_assistant, "_get_runtime_bot"):
            runtime_bot = ai_assistant._get_runtime_bot()
        should_respond = await self._check_should_respond(runtime_bot, event, ai_assistant)
        if not should_respond:
            if hasattr(ai_assistant, "buffer_chat_message") and self.group_mode:
                try:
                    identity = await get_group_member_identity(runtime_bot, event)
                except Exception:
                    identity = _build_member_identity_fallback(event)
                video_urls = extract_video_urls(event.get_message())
                ai_assistant.buffer_chat_message(
                    identity.get("display_name") or f"QQ:{event.user_id}",
                    event.user_id,
                    msg_text,
                    None,
                    video_urls,
                    member_identity=identity,
                )
            return

        if (msg_text == ai_assistant.character.name or not msg_text) and not event.reply:
            await ai_assistant.send(ai_assistant.character.on_switch_msg)
            return
        if msg_text == f"{ai_assistant.character.name}闭嘴":
            return

        service_config = {
            "voice_enable": self.voice_enable,
            "music_enable": self.music_enable,
            "tools_enable": self.tools_enable,
            "rate_limit_enable": self.rate_limit_enable,
            "rate_limit_per_hour": self.rate_limit_per_hour,
            "thinking_enable": self.thinking_enable,
            "group_mode": self.group_mode,
        }
        if not msg_text.strip().endswith(("??", "？？")):
            await ai_assistant.reply(event, service_config)
            return
        await ai_assistant.reply_with_zhihu(event, service_config)

    async def _check_should_respond(self, _bot: Bot | None, event: MessageEvent, ai_assistant) -> bool:
        msg_text = event.get_message().extract_plain_text()
        starts_with_name = msg_text.startswith(ai_assistant.character.name)
        starts_with_nickname = ai_assistant.nickname and msg_text.startswith(ai_assistant.nickname)
        return starts_with_name or starts_with_nickname or event.is_tome()

    @service_message(desc="随机回复", priority=3, block=True)
    async def handle_random_reply(self, event: GroupMessageEvent, bot: Bot | None = None):
        if not self.enabled or not self.random_reply_enabled:
            return
        if random.random() >= 0.01:
            return

        ai_assistant = self.get_ai_assistant(event)
        if hasattr(ai_assistant, "_bind_runtime_bot"):
            ai_assistant._bind_runtime_bot(bot)
        runtime_bot = bot
        if runtime_bot is None and hasattr(ai_assistant, "_get_runtime_bot"):
            runtime_bot = ai_assistant._get_runtime_bot()
        if random.random() < 0.5:
            if runtime_bot is None:
                return
            try:
                await runtime_bot.call_api("group_poke", group_id=event.group_id, user_id=event.user_id)
            except Exception:
                return
            return
        emoji = random.choice(["😸", "😺", "😹", "😻", "😼", "😽", "🙀", "😿", "😾"])
        await ai_assistant.send_text(emoji)

    @service_message(desc="关键词回复", priority=4, block=True)
    async def handle_keyword_reply(self, event: GroupMessageEvent, bot: Bot | None = None):
        if not self.enabled or not self.keyword_reply_enabled:
            return

        msg = event.get_message().extract_plain_text()
        if "哈哈哈" not in msg and "笑死" not in msg:
            return
        if random.random() < 0.2:
            ai_assistant = self.get_ai_assistant(event)
            if hasattr(ai_assistant, "_bind_runtime_bot"):
                ai_assistant._bind_runtime_bot(bot)
            await ai_assistant.send_text("😸")

    @service_notice(desc="戳一戳显示菜单", event_type="PokeNotifyEvent", priority=5, block=True)
    async def handle_poke(self, event: PokeNotifyEvent, matcher=None, bot: Bot | None = None):
        if not self.enabled:
            return
        if event.target_id != event.self_id:
            return
        ai_assistant = self.get_ai_assistant(event)
        if hasattr(ai_assistant, "_bind_runtime_bot"):
            ai_assistant._bind_runtime_bot(bot)
        await ai_assistant.text_menu()


__all__ = ["AIServiceHandlerMixin"]
