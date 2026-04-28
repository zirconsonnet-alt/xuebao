from typing import Union
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from .enum import Phase
from .player import Player
from .player_manager import PlayerManager


class FormalHandler:
    @staticmethod
    def handler(player_manager: PlayerManager, phase: Phase):
        async def _(event: Union[GroupMessageEvent, PrivateMessageEvent]):
            raw_message = str(event.get_message()).strip()
            this_player: Player = player_manager.get_target_player(event.user_id)
            funcs = {
                'get_target_player': player_manager.get_target_player,
                'get_target_players': player_manager.get_target_players,
                'get_chat_room': lambda: player_manager.chat_room
            }
            await this_player.handle_command(raw_message, phase, funcs)

        return _


class TestHandler:
    @staticmethod
    def handler(player_manager: PlayerManager, phase: Phase):
        async def _(event: Union[GroupMessageEvent, PrivateMessageEvent]):
            try:
                user_input = str(event.get_message()).strip()
                raw_message = user_input[1:]
                if not user_input[0].isdigit() and int(user_input[0]) < len(player_manager.player_list):
                    return
                this_player: Player = player_manager.get_target_player(int(user_input[0]))
                funcs = {
                    'get_target_player': player_manager.get_target_player,
                    'get_target_players': player_manager.get_target_players,
                    'get_chat_room': lambda: player_manager.chat_room
                }
                await this_player.handle_command(raw_message, phase, funcs)
            except Exception as e:
                print(e)
        return _
