import random

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.core import Services
from src.support.group import run_flow

from .base import BaseService, config_property, service_action, service_message

class ChatService(BaseService):
    service_type = Services.Chat
    default_config = {
        "enabled": False,
        "auto_emoji_enabled": True,
        "auto_like_enabled": True,
        "emoji_ids": [2, 63, 76, 109, 201],
    }
    enabled = config_property("enabled")
    auto_emoji_enabled = config_property("auto_emoji_enabled")
    auto_like_enabled = config_property("auto_like_enabled")
    emoji_ids = config_property("emoji_ids")

    def __init__(self, group):
        super().__init__(group)
        self._liked_users = []

    @service_message(desc="自动表情回复和点赞", priority=5, block=False)
    async def auto_react(self, event: GroupMessageEvent):
        if not self.enabled:
            return
        await self._auto_emoji_react(event)
        await self._auto_like_user(event)

    async def _auto_emoji_react(self, event: GroupMessageEvent):
        if not self.auto_emoji_enabled:
            return
        if event.user_id in self._liked_users:
            return
        try:
            emoji_id = random.choice(self.emoji_ids)
            await nonebot.get_bot().set_msg_emoji_like(message_id=event.message_id, emoji_id=emoji_id)
        except Exception as exc:
            print(f"自动表情回复失败: {exc}")

    async def _auto_like_user(self, event: GroupMessageEvent):
        if not self.auto_like_enabled:
            return
        if event.user_id in self._liked_users:
            return
        self._liked_users.append(event.user_id)
        try:
            friend_list = await nonebot.get_bot().get_friend_list()
            friend_ids = [friend["user_id"] for friend in friend_list]
            if event.user_id in friend_ids:
                await nonebot.get_bot().send_like(user_id=event.user_id, times=1)
                await nonebot.get_bot().send_like(user_id=event.user_id, times=9)
        except Exception as exc:
            print(f"自动点赞失败: {exc}")

    @service_action(cmd="重置点赞列表", desc="重置今日已点赞用户列表")
    async def reset_liked_users(self):
        self._liked_users.clear()
        await self.group.send_msg("点赞列表已重置")

__all__ = ["ChatService"]
