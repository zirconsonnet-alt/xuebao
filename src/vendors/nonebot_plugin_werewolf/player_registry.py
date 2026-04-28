import threading
from typing import List


class PlayerRegistry:
    """
        玩家管理类，负责管理各个游戏群组中的玩家信息。
        Attributes:
            _instance (Optional[PlayerManager]): 单例实例，确保该类只有一个实例。
            games_info (Dict[int, List[int]]): 存储群组id与对应玩家id列表。
        """
    _lock = threading.Lock()
    _instance = None

    def __new__(cls):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance.games_info = {}
        return cls._instance

    def add_group(self, group_id):
        if group_id not in self.games_info:
            self.games_info[group_id] = []
            return True
        return False

    def add_players(self, group_id: int, player_id_list: List[int]) -> bool:
        if group_id in self.games_info:
            self.games_info[group_id].extend(player_id_list)
            return True
        return False

    def remove_player(self, group_id: int, player_id: int) -> bool:
        if group_id in self.games_info and player_id in self.games_info[group_id]:
            self.games_info[group_id].remove(player_id)
            return True
        return False

    def get_players(self, group_id: int) -> List[int]:
        return self.games_info.get(group_id, [])

    def clear_game(self, group_id: int) -> bool:
        return self.games_info.pop(group_id, None) is not None

    def is_player_in_game(self, player_id: int) -> bool:
        return any(player_id in player_list for player_list in self.games_info.values())

    def is_any_game_active(self) -> bool:
        return any(len(player_list) > 0 for player_list in self.games_info.values())
