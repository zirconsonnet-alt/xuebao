import random
from abc import ABC, abstractmethod
from .enum import Role, Kind
from .player_manager import PlayerManager


class Strategy(ABC):
    ROLE_CONFIG = None
    NON_KILLING_ROLES = [
        Role.VILLAGER,
        Role.SEER,
        Role.GUARD,
        Role.EXPLORER,
        Role.NERD
    ]

    @abstractmethod
    def check_victory(self, player_manager: PlayerManager):
        pass

    def generate_role_list(self, num_players: int) -> list[Role]:
        config = None
        for (min_p, max_p) in self.ROLE_CONFIG:
            if min_p <= num_players <= max_p:
                config = self.ROLE_CONFIG[(min_p, max_p)]
                break
        if not config:
            raise ValueError("玩家数量不符合该模式的配置。")
        roles = []
        for role, count_spec in config.items():
            count = count_spec(num_players) if callable(count_spec) else count_spec
            roles.extend([role] * count)
        random.shuffle(roles)
        print(type(roles[0]))
        return roles

    @staticmethod
    def check_victory_1(player_manager):
        if all(p.dead for p in player_manager.player_list):
            return True, 'None'
        players_alive = [player for player in player_manager.player_list if not player.dead]
        villagers_alive = [
            player for player in players_alive if player.kind == Kind.VILLAGER]
        werewolves_alive = [
            player for player in players_alive if player.kind == Kind.WEREWOLF]
        cupids_alive = [
            player for player in players_alive if player.kind == Kind.CUPID]
        if cupids_alive:
            if not werewolves_alive and not villagers_alive:
                return True, Kind.CUPID
            return False, None
        if werewolves_alive and villagers_alive:
            if (not [p for p in villagers_alive if p.role == Role.VILLAGER] or
                    all(p.role == Role.VILLAGER for p in villagers_alive)):
                return True, Kind.WEREWOLF
            return False, None
        elif werewolves_alive:
            return True, Kind.WEREWOLF
        elif villagers_alive:
            return True, Kind.VILLAGER

    @staticmethod
    def check_victory_2(player_manager):
        if all(p.dead for p in player_manager.player_list):
            return True, 'None'
        players_alive = [player for player in player_manager.player_list if not player.dead]
        villagers_alive = [
            player for player in players_alive if player.kind == Kind.VILLAGER]
        werewolves_alive = [
            player for player in players_alive if player.kind == Kind.WEREWOLF]
        cupids_alive = [
            player for player in players_alive if player.kind == Kind.CUPID]
        if cupids_alive:
            if not werewolves_alive and not villagers_alive:
                return True, Kind.CUPID
            return False, None
        if werewolves_alive and villagers_alive:
            return False, None
        elif werewolves_alive:
            return True, Kind.WEREWOLF
        elif villagers_alive:
            return True, Kind.VILLAGER


class ClassicStrategy(Strategy):
    ROLE_CONFIG = {
        (3, 3): {
            Role.VILLAGER: lambda num: num - 2,
            Role.WEREWOLF: 1,
            Role.WITCH: 1
        },
        (4, 5): {
            Role.VILLAGER: lambda num: num - 3,
            Role.WEREWOLF: 1,
            Role.HUNTER: 1,
            Role.WITCH: 1
        },
        (6, 8): {
            Role.VILLAGER: lambda num: num - 4,
            Role.WEREWOLF: 1,
            Role.WHITE_WOLF: 1,
            Role.WITCH: 1,
            Role.SEER: 1
        },
        (9, 9): {
            Role.VILLAGER: lambda num: num - 5,
            Role.WEREWOLF: 2,
            Role.WHITE_WOLF: 1,
            Role.WITCH: 1,
            Role.SEER: 1,
            random.choice((Role.HUNTER, Role.GUARD, Role.NERD, Role.EXPLORER, Role.RIDER)): 1
        }
    }

    def check_victory(self, player_manager: PlayerManager):
        if len(player_manager.all_players) >= 6:
            return self.check_victory_1(player_manager)
        else:
            return self.check_victory_2(player_manager)


class HunterStrategy(Strategy):
    ROLE_CONFIG = {
        (3, 3): {
            Role.VILLAGER: lambda num: num - 2,
            Role.WEREWOLF: 1,
            Role.HUNTER: 1
        },
        (4, 5): {
            Role.VILLAGER: lambda num: num - 3,
            Role.WEREWOLF: 1,
            Role.HUNTER: 2
        },
        (6, 8): {
            Role.VILLAGER: lambda num: num - 4,
            Role.WEREWOLF: 1,
            Role.WHITE_WOLF: 1,
            Role.HUNTER: 1,
            Role.SEER: 1
        },
        (9, 9): {
            Role.VILLAGER: lambda num: num - 5,
            Role.WEREWOLF: 2,
            Role.WHITE_WOLF: 1,
            Role.HUNTER: 1,
            Role.SEER: 1,
            random.choice((Role.WITCH, Role.GUARD, Role.NERD, Role.EXPLORER, Role.RIDER)): 1
        }
    }

    def check_victory(self, player_manager: PlayerManager):
        if len(player_manager.all_players) >= 6:
            return self.check_victory_1(player_manager)
        else:
            return self.check_victory_2(player_manager)


class SuperHunterStrategy(Strategy):
    ROLE_CONFIG = {
        (3, 5): {
            Role.WEREWOLF: lambda num: num // 2,
            Role.HUNTER: lambda num: num // 2 + 1
        }
    }

    def check_victory(self, player_manager):
        return self.check_victory_2(player_manager)


class GuardStrategy(Strategy):
    ROLE_CONFIG = {
        (3, 3): {
            Role.VILLAGER: lambda num: num - 2,
            Role.WEREWOLF: 1,
            Role.GUARD: 1
        },
        (4, 5): {
            Role.VILLAGER: lambda num: num - 3,
            Role.WEREWOLF: 1,
            Role.HUNTER: 1,
            Role.GUARD: 1
        },
        (6, 8): {
            Role.VILLAGER: lambda num: num - 4,
            Role.WEREWOLF: 1,
            Role.WHITE_WOLF: 1,
            Role.GUARD: 1,
            Role.SEER: 1
        },
        (9, 9): {
            Role.VILLAGER: lambda num: num - 5,
            Role.WEREWOLF: 2,
            Role.WHITE_WOLF: 1,
            Role.GUARD: 1,
            Role.SEER: 1,
            random.choice((Role.HUNTER, Role.RIDER, Role.NERD, Role.EXPLORER, Role.WITCH)): 1
        }
    }

    def check_victory(self, player_manager: PlayerManager):
        if len(player_manager.all_players) >= 6:
            return self.check_victory_1(player_manager)
        else:
            return self.check_victory_2(player_manager)


class RiderStrategy(Strategy):
    ROLE_CONFIG = {
        (3, 3): {
            Role.VILLAGER: lambda num: num - 2,
            Role.WEREWOLF: 1,
            Role.RIDER: 1
        },
        (4, 5): {
            Role.VILLAGER: lambda num: num - 3,
            Role.WEREWOLF: 1,
            Role.HUNTER: 1,
            Role.RIDER: 1
        },
        (6, 8): {
            Role.VILLAGER: lambda num: num - 4,
            Role.WEREWOLF: 1,
            Role.WHITE_WOLF: 1,
            Role.RIDER: 1,
            Role.SEER: 1
        },
        (9, 9): {
            Role.VILLAGER: lambda num: num - 5,
            Role.WEREWOLF: 2,
            Role.WHITE_WOLF: 1,
            Role.RIDER: 1,
            Role.SEER: 1,
            random.choice((Role.HUNTER, Role.GUARD, Role.NERD, Role.EXPLORER, Role.WITCH)): 1
        }
    }

    def check_victory(self, player_manager: PlayerManager):
        if len(player_manager.all_players) >= 6:
            return self.check_victory_1(player_manager)
        else:
            return self.check_victory_2(player_manager)
