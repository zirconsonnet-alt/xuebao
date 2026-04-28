from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg

from src.support.core import Services

from .base import (
    BaseService,
    check_enabled,
    config_property,
    service_action,
    service_message,
)

class TitleService(BaseService):
    service_type = Services.Title
    enable_requires_bot_admin = True
    default_config = {
        "enabled": False,
        "auto_title_enabled": True,
        "auto_title_level": 20,
        "default_title": "默认头衔",
    }
    enabled = config_property("enabled")
    auto_title_enabled = config_property("auto_title_enabled")
    auto_title_level = config_property("auto_title_level")
    default_title = config_property("default_title")

    @check_enabled
    @service_action(cmd="设置头衔", need_arg=True)
    async def set_title(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        member_info = await self.group.get_group_member_info(self.group.self_id)
        if member_info["role"] == "member":
            await self.group.send_msg("❌ 机器人不是管理员，无法使用此功能！")
            return
        title = arg.extract_plain_text().strip()
        if not title:
            await self.group.send_msg("❌ 头衔不能为空")
            return
        user_id = event.user_id
        await self.group.set_special_title(user_id, title)
        await self.group.send_msg(MessageSegment.at(user_id) + f" ✅ 头衔已设置为「{title}」")

    @check_enabled
    @service_action(cmd="设置头衔等级门槛", need_arg=True)
    async def set_auto_title_level(self, arg: Message = CommandArg()):
        try:
            level = int(arg.extract_plain_text().strip())
            self.auto_title_level = level
            await self.group.send_msg(f"✅ 自动授予头衔等级门槛已设置为 {level} 级")
        except ValueError:
            await self.group.send_msg("❌ 等级必须是整数！")

    @service_message(desc="自动等级检测授予头衔", priority=5, block=False)
    async def check_title(self, event: GroupMessageEvent):
        if not self.enabled or not self.auto_title_enabled:
            return
        await self._auto_grant_title(event)

    async def _auto_grant_title(self, event: GroupMessageEvent):
        member_info = await self.group.get_group_member_info(event.user_id)
        if member_info.get("title"):
            return
        if int(member_info.get("level", 0)) < self.auto_title_level:
            return
        await self.group.set_special_title(event.user_id, self.default_title)
        await self.group.send_msg(
            MessageSegment.at(event.user_id)
            + f" 🎉 等级达到 {self.auto_title_level} 级，已授予专属头衔！\n使用“/设置头衔 新头衔”可修改"
        )

__all__ = ["TitleService"]
