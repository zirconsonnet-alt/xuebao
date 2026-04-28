from typing import Callable, List, Tuple, Union

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.internal.matcher import Matcher

from src.support.core import Services
from src.vendorlibs.command_handler import CommandHandler
from src.vendors.nonebot_plugin_sp.game import TurtleSoupGameManager
from src.vendors.nonebot_plugin_sp.tools import wait_for, wait_for_event

from .base import BaseService, check_enabled, config_property, service_action


class _TurtleSoupCommandHandler(CommandHandler):
    def __init__(self, matcher: Matcher, event: GroupMessageEvent, arg: Union[Message, str]):
        super().__init__(matcher, event, arg)
        self.manager = TurtleSoupGameManager()

    @property
    def name(self) -> str:
        return "海龟汤"

    @property
    def background(self) -> str:
        return "sp.jpg"

    def get_commands(self) -> List[Tuple[str, Callable]]:
        return [("启动", self.start_game)]

    async def start_game(self) -> None:
        group_id = self.event.group_id
        host_id = self.event.user_id
        manager = TurtleSoupGameManager()
        if manager.is_game_active(group_id):
            await self.matcher.finish("⚠️ 本群已有一个进行中的海龟汤游戏")
        if not self.event.reply:
            await self.matcher.send("🐢 请发送汤面")
            response = await wait_for_event(30)
            if not response:
                await self.matcher.send("⏱️ 汤面超时未发送")
                return
            self.msg = response.message_id
        await self.matcher.send("🍲 请设置提问次数上限(0-50)，9999代表次数不限")
        max_questions = await wait_for(30)
        if not max_questions.isdigit() or (int(max_questions) > 50 and int(max_questions) != 9999):
            await self.matcher.finish("⚠️ 最大提问次数不合法")
        await self.matcher.send("🍲 海龟汤游戏创建中...")
        host_info = await nonebot.get_bot().get_group_member_info(group_id=group_id, user_id=host_id)
        host_name = host_info["card"] if host_info["card"] else host_info["nickname"]
        manager.start_game(group_id, host_id, host_name, int(self.msg), int(max_questions))


class TurtleSoupService(BaseService):
    service_type = Services.TurtleSoup
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    @service_action(cmd="海龟汤", need_arg=True, desc="打开海龟汤菜单")
    @check_enabled
    async def turtle_soup_menu(self, event: GroupMessageEvent, matcher: Matcher, arg: Message):
        if getattr(event, "reply", None):
            handler = _TurtleSoupCommandHandler(matcher, event, str(event.reply.message_id))
            await handler.start_game()
            return
        handler = _TurtleSoupCommandHandler(matcher, event, arg)
        await handler.execute()


__all__ = ["TurtleSoupService"]
