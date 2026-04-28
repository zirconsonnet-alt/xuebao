import re
from typing import Dict, Optional, List, Union
from nonebot import logger
from .player import PlayerFactory, PlayerDatabase, Player
from .enum import Role, Phase
from .player_registry import PlayerRegistry
from .transmitter import Transmitter


class PlayerManager:
    """
    游戏状态类，管理玩家状态，并负责与玩家行动的交互。
    Attributes:
        victims (List[Any]): 临时受害人列表，用于存储当前游戏中的受害者。
        player_list (List[Any]): 全部玩家列表，包含所有参与游戏的玩家。
        player_registry (PlayerManager): 游戏玩家管理实例，负责管理玩家的增删改查。
        player_dict (Dict[str, List[Any]]): 根据职业划分的玩家字典，角色名称为键，玩家列表为值。
        last_words (Dict[Any, str]): 遗言字典，用于存储已死亡玩家的遗言。
    """
    def __init__(self, group_id: int, player_registry: PlayerRegistry, transmitter: Transmitter):
        self.group_id = group_id
        self.player_registry = player_registry
        self.transmitter = transmitter
        self.victims: List[Player] = []
        self.player_list: List[Player] = []
        self.all_players: List[Player] = []
        self.player_dict: Dict[Role, List[Player]] = {}
        self.last_words = {}

    @property
    def players_able_to_act(self):
        return [player for player in self.player_list if not player.handled]

    @property
    def chat_room(self):
        return [player for player in self.player_list if not player.handled]

    def set_player_list(self, player_info_list: Dict[str, int], role_list: List[Role]):
        """
        根据玩家信息字典初始化玩家对象，并将其添加到管理器和角色字典中。
        Args:
            player_info_list (Dict[str, int]): 包含玩家名称和id的字典，键为玩家名称（str），值为玩家ID（int）。
            role_list: List (List[Role]): 玩家职业列表。
        """
        if len(role_list) < len(player_info_list):
            raise ValueError("角色数量不足")
        for name, player_id in player_info_list.items():
            role = role_list.pop(0)
            self._add_player_to_list(player_id, name, role)
        self.player_registry.add_players(self.group_id, [player.id for player in self.player_list])
        for player in self.player_list:
            role = player.role
            if role not in self.player_dict:
                self.player_dict[role] = []
            self.player_dict[role].append(player)
        self.player_registry.add_players(self.group_id, list(player_info_list.values()))
        self.all_players = self.player_list.copy()

    def _add_player_to_list(self, player_id: int, name: str, role: Role):
        """
        增加玩家实例并将其添加到玩家列表中。
        Args:
            player_id (int): 要添加的玩家的id
            name (str): 要添加的玩家的昵称
            role (str): 要添加的玩家的职业
        """
        player_group_name = PlayerDatabase().get_player_name(player_id)
        self.player_list.append(
            PlayerFactory.create_player(
                player_id=player_id,
                name=name,
                group_name=player_group_name,
                role=role,
                transmitter=self.transmitter
            )
        )

    def _get_player_by_name(self, name: str) -> Optional[Player]:
        try:
            logger.info(f"正在寻找名为{name}的玩家")
            return next((player for player in self.player_list if player.name == name), None)
        except Exception as e:
            print(e)
            return None

    def _get_player_by_id(self, player_id: str) -> Optional[Player]:
        try:
            logger.info(f"正在寻找id为{player_id}的玩家")
            return next((player for player in self.player_list if player.id == int(player_id)), None)
        except Exception as e:
            print(e)
            return None

    def _get_player_by_index(self, index: str) -> Optional[Player]:
        try:
            logger.info(f"正在寻找索引为{index}的玩家")
            target_player = self.all_players[int(index)-1]
            return target_player if target_player in self.player_list else None
        except Exception as e:
            print(e)
            return None

    def _get_player_by_at(self, msg: str) -> Optional[Player]:
        try:
            cq_code_match = re.match(r'\[CQ:at,qq=(\d+)]', str(msg))
            target_player = self._get_player_by_id(cq_code_match.group(1))
            return target_player
        except Exception as e:
            print(e)
            return None

    def get_target_player(self, info: Union[int, str]) -> Player:
        info = str(info)
        target_player = self._get_player_by_name(info)
        if target_player:
            return target_player
        target_player = self._get_player_by_index(info)
        if target_player:
            return target_player
        target_player = self._get_player_by_id(info)
        if target_player:
            return target_player
        target_player = self._get_player_by_at(info)
        if target_player:
            return target_player
        raise ValueError(
            '❌ 您未成功指定玩家。请使用如下方式指定目标玩家：\n序号：『您要使用的指令』1\n（如“杀害1”：杀害序号为1的玩家）\n'
            '玩家名：『您要使用的指令』雪豹\n（如“预言雪豹”:预言“雪豹”的身份）\n@（群内使用）：『您要使用的指令』@目标玩家\n（如“我投@牢雪豹”：投“牢雪豹”一票）'
        )

    def get_target_players(self, combined_info: str) -> List[Player]:
        parts = combined_info.split('+')
        if len(parts) != 2:
            raise ValueError("参数必须由两个部分通过 '+' 连接")
        part1, part2 = parts
        player1 = self.get_target_player(part1)
        player2 = self.get_target_player(part2)
        return [player1, player2]

    async def _remove_player(self, player: Player):
        """
        从游戏和玩家管理器中移除玩家。
        Args:
            player (Player): 要移除的玩家对象。
        """
        logger.info(f"{player.name}已被移除。")
        self.player_list.remove(player)
        self.player_dict[player.role].remove(player)
        self.player_registry.remove_player(self.group_id, player.id)
        await self.transmitter.ban(player.id, 300)

    def alive_players(self) -> str:
        return '🐆-------玩家列表-------🥷\n' + '；\n'.join([
            f"{i + 1}. {p.name}{' ✅' if p in self.player_list else ' ❌'}"
            for i, p in enumerate(self.all_players)
        ]) + '。'

    async def end_vote_at_day(self):
        """
        根据投票结果，令得票最高的玩家死亡。
        """
        vote_results = []
        max_votes = max([player.vote_count for player in self.player_list])
        top_players = [player for player in self.player_list if player.vote_count == max_votes]
        if len(top_players) == 1:
            target_player = top_players[0]
            if target_player:
                target_player.set_dead(True)
                for player in self.player_list:
                    vote_results.append(f"{player.name}: {player.vote_count}票")
                await self.transmitter.send(f'⚖️ 投票结果如下：\n{"；\n".join(vote_results)}。')
                await self.transmitter.send(f'⚔️ {target_player.name}已被放逐')
                return
        await self.transmitter.send("⚖️ 平票，无人被放逐")
        return

    async def end_vote_at_election(self):
        """
        根据投票结果，令得票最高的玩家死亡。
        """
        vote_results = []
        max_votes = max([player.vote_count for player in self.player_list])
        top_players = [player for player in self.player_list if player.vote_count == max_votes]
        if len(top_players) == 1:
            target_player = top_players[0]
            if target_player:
                target_player.set_chief(True)
                for player in self.player_list:
                    vote_results.append(f"{player.name}: {player.vote_count}票")
                await self.transmitter.send(f'⚖️ 投票结果如下：\n{"；\n".join(vote_results)}。')
                await self.transmitter.send(f'🔱 {target_player.name}成为了警长！')
                return
        await self.transmitter.send("⚖️ 平票，无人成为警长。")
        return

    async def set_players_able_to_act(
            self,
            players: List[Player],
            phase: Phase
    ):
        print(f'{','.join([p.name for p in players])}')
        print(f'{','.join([str(p.handled) for p in players])}')
        players_able_to_act = [player for player in players if player.can_act(phase)]
        for player in set(players_able_to_act):
            player.set_in_room(True)
            player.set_handled(False)
            await player.notice(info={
                'phase': phase,
                'alive_players': self.alive_players,
                'other_werewolves': len(players_able_to_act) > 1,
                'victims': lambda: [victim for victim in self.player_list if victim.dead]
            })

    async def refresh(self):
        for player in list(self.player_list):
            if player.dead:
                await self._remove_player(player)
                continue
            player.reset_states()
