from typing import Callable, List, Tuple

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.internal.matcher import Matcher

from src.support.core import Services
from src.vendorlibs.command_handler import CommandHandler
from src.vendors.nonebot_plugin_math_game.math_game import (
    LeaderboardType,
    PlayerDatabase,
    PlayerManager,
    TwentyFourGame,
)
from src.vendors.nonebot_plugin_math_game.menu_creator import MenuCreator

from .base import BaseService, check_enabled, config_property, service_action


class _TwentyFourCommandHandler(CommandHandler):
    def __init__(self, matcher: Matcher, event: GroupMessageEvent, arg: Message):
        super().__init__(matcher, event, arg)
        self.player_manager = PlayerManager()

    @property
    def name(self) -> str:
        return "24点"

    @property
    def background(self) -> str:
        return "24.jpg"

    def get_commands(self) -> List[Tuple[str, Callable]]:
        commands = [
            ("启动", self._start_normal_game),
            ("连战", self._start_long_game),
        ]
        for leaderboard_type in LeaderboardType:
            commands.append((leaderboard_type.value, self._show_leaderboard))
        return commands

    async def _check_game_availability(self) -> bool:
        if self.player_manager.is_player_in_game(self.event.user_id) or self.player_manager.is_group_in_game(
            self.event.group_id
        ):
            await self.matcher.send("本群已有游戏正在进行！")
            return False
        return True

    async def _start_normal_game(self) -> None:
        if not await self._check_game_availability():
            return
        self.player_manager.add_group(self.event.group_id)
        self.player_manager.add_player(self.event.group_id, self.event.user_id)
        game = TwentyFourGame(self.event.group_id, self.event.user_id)
        await game.start_game()

    async def _start_long_game(self) -> None:
        if not await self._check_game_availability():
            return
        self.player_manager.add_group(self.event.group_id)
        self.player_manager.add_player(self.event.group_id, self.event.user_id)
        game = TwentyFourGame(self.event.group_id, self.event.user_id)
        await game.start_long_game()

    async def _show_leaderboard(self) -> None:
        if self.msg.isdigit():
            index = int(self.msg) - 1
            if 0 <= index < len(self.commands):
                self.msg = self.commands[index][0]
        leaderboard_type = LeaderboardType(self.msg)
        player_database = PlayerDatabase(self.event.group_id)
        leaderboard_data = player_database.get_leaderboard(leaderboard_type)
        await MenuCreator(self.matcher).show_top_players(leaderboard_data, self.msg)


class MathGameService(BaseService):
    service_type = Services.MathGame
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    @service_action(cmd="24点", need_arg=True, desc="打开 24 点菜单")
    @check_enabled
    async def math_game_menu(self, event: GroupMessageEvent, matcher: Matcher, arg: Message):
        handler = _TwentyFourCommandHandler(matcher, event, arg)
        await handler.execute()


__all__ = ["MathGameService"]
