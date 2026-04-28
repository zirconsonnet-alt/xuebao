from pprint import pprint

from .enum import Mode, Role
from .player_manager import PlayerManager
from .strategy import ClassicStrategy, HunterStrategy, GuardStrategy, RiderStrategy, SuperHunterStrategy


class GameMode:
    STRATEGIES = {
        Mode.CLASSIC: ClassicStrategy,
        Mode.HUNTER: HunterStrategy,
        Mode.RIDER: RiderStrategy,
        Mode.GUARD: GuardStrategy,
        Mode.SUPER_HUNTER: SuperHunterStrategy,
    }

    def __init__(self, game_mode: Mode, num_players: int):
        self.game_mode = game_mode
        self.num_players = num_players
        self.role_list = []
        self.strategy = self.STRATEGIES[game_mode]()

    def check_victory(self, player_manager: PlayerManager):
        return self.strategy.check_victory(player_manager)

    def generate_role_list(self) -> list[Role]:
        self.role_list = self.strategy.generate_role_list(self.num_players)
        print('1')
        pprint(self.role_list)
        return self.role_list

    def display_role_list(self) -> str:
        print('2')
        pprint(self.role_list)
        if not self.role_list:
            return "角色列表为空"
        role_count = {}
        for role in self.role_list:
            role_name = role.value
            role_count[role_name] = role_count.get(role_name, 0) + 1
        sorted_roles = sorted(role_count.items(), key=lambda x: x[0])
        return "，\n".join([f"{role}*{count}" for role, count in sorted_roles])
