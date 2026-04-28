import traceback
from typing import Callable, List, Tuple

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.internal.matcher import Matcher

from src.support.core import Services
from src.vendorlibs.command_handler import CommandHandler
from src.vendors.nonebot_plugin_werewolf.enum import Mode, data_dir
from src.vendors.nonebot_plugin_werewolf.game import Game
from src.vendors.nonebot_plugin_werewolf.menu_creator import WerewolfMenuCreator
from src.vendors.nonebot_plugin_werewolf.player import PlayerDatabase
from src.vendors.nonebot_plugin_werewolf.player_registry import PlayerRegistry
from src.vendors.nonebot_plugin_werewolf.tool import wait_for
from src.vendors.nonebot_plugin_werewolf.transmitter import Transmitter

from .base import BaseService, check_enabled, config_property, service_action


class _WerewolfCommandHandler(CommandHandler):
    def __init__(self, matcher: Matcher, event: GroupMessageEvent, arg: Message):
        super().__init__(matcher, event, arg)
        self.player_registry = PlayerRegistry()

    @property
    def name(self) -> str:
        return "雪豹杀"

    @property
    def background(self) -> str:
        return "werewolf.jpg"

    def get_commands(self) -> List[Tuple[str, Callable]]:
        return [
            ("启动", self._start_game),
            ("总榜", self._show_leaderboard),
        ]

    async def _check_game_availability(self) -> bool:
        if self.event.group_id in self.player_registry.games_info.keys():
            await self.matcher.send("❌ 本群已有游戏正在进行！")
            return False
        return True

    async def _start_game(self) -> None:
        if not await self._check_game_availability():
            return
        self.player_registry.add_group(self.event.group_id)
        transmitter = Transmitter(self.event.group_id)
        await transmitter.send(
            "请选择游戏模式：\n"
            f"1.{Mode.CLASSIC.value}（3-9人）\n"
            f"2.{Mode.HUNTER.value}（3-9人）\n"
            f"3.{Mode.RIDER.value}（3-9人）\n"
            f"4.{Mode.GUARD.value}（3-9人）\n"
            f"5.{Mode.SUPER_HUNTER.value}（3-5人）\n"
            "如10秒内未选择，将自动使用经典模式"
        )
        choice = await wait_for(10)
        mode_mapping = {
            "1": Mode.CLASSIC,
            "2": Mode.HUNTER,
            "3": Mode.RIDER,
            "4": Mode.GUARD,
            "5": Mode.SUPER_HUNTER,
        }
        game_mode = mode_mapping.get(choice, Mode.CLASSIC)
        await transmitter.send(
            f"{game_mode.value}已准备就绪！\n✅发送【我要参加】可加入游戏，等待时间为120秒，发送【参与结束】可提前开始，"
            "如果您不清楚游戏规则，请发送“help”进行查看！"
        )
        game = Game(transmitter)
        try:
            await transmitter.transform_in()
            await game.join_game(game_mode, self.event.group_id)
            await game.state_machine.start_game()
            game.clean_up()
        except Exception as exc:
            logger.error(f"游戏运行出错: {str(exc)}")
            traceback.print_exc()
            await transmitter.send(f"游戏异常终止: {str(exc)}")
        finally:
            await transmitter.transform_out()
            self.player_registry.clear_game(self.event.group_id)

    async def _show_leaderboard(self) -> None:
        player_db = PlayerDatabase(data_dir)
        player_db.create_table()
        await WerewolfMenuCreator(self.matcher).show_top_players(player_db.all_players())


class WerewolfService(BaseService):
    service_type = Services.Werewolf
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    @service_action(cmd="雪豹杀", aliases={"狼人杀"}, need_arg=True, desc="打开雪豹杀菜单")
    @check_enabled
    async def werewolf_menu(self, event: GroupMessageEvent, matcher: Matcher, arg: Message):
        handler = _WerewolfCommandHandler(matcher, event, arg)
        await handler.execute()


__all__ = ["WerewolfService"]
