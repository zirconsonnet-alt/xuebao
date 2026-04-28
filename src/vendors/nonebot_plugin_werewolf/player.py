import re
import math
import time
import sqlite3
import asyncio
import nonebot
from typing import Optional, List, Callable, Tuple, Dict
from nonebot.log import logger
from abc import ABC, abstractmethod
from nonebot.adapters.onebot.v11 import ActionFailed, MessageSegment
from .enum import Role, Phase, Arg, data_dir, Kind, role_emojis
from .transmitter import Transmitter


class PlayerFactory:
    @staticmethod
    def create_player(player_id: int, name: str, group_name: str, role: Role, transmitter: Transmitter):
        print(role)
        print(type(role))
        print(role.value)
        if role == Role.VILLAGER:
            return Villager(player_id, name, group_name, transmitter)
        elif role == Role.WEREWOLF:
            return Werewolf(player_id, name, group_name, transmitter)
        elif role == Role.HUNTER:
            return Hunter(player_id, name, group_name, transmitter)
        elif role == Role.WITCH:
            return Witch(player_id, name, group_name, transmitter)
        elif role == Role.SEER:
            return Seer(player_id, name, group_name, transmitter)
        elif role == Role.NERD:
            return Nerd(player_id, name, group_name, transmitter)
        elif role == Role.EXPLORER:
            return Explorer(player_id, name, group_name, transmitter)
        elif role == Role.WHITE_WOLF:
            return WhiteWolf(player_id, name, group_name, transmitter)
        elif role == Role.CUPID:
            return Cupid(player_id, name, group_name, transmitter)
        elif role == Role.GUARD:
            return Guard(player_id, name, group_name, transmitter)
        elif role == Role.RIDER:
            return Rider(player_id, name, group_name, transmitter)
        else:
            raise ValueError(f"未知角色: {role}")


class PlayerDatabase:
    _instance = None

    def __init__(self, db_path=data_dir):
        if not hasattr(self, 'conn'):
            self.conn = sqlite3.connect(db_path)
            self.create_table()

    @staticmethod
    def get_instance(db_path=None):
        if PlayerDatabase._instance is None:
            if db_path is None:
                raise ValueError("首次初始化时必须提供数据库路径")
            PlayerDatabase._instance = PlayerDatabase(db_path)
        return PlayerDatabase._instance

    def create_table(self):
        with self.conn:
            self.conn.execute(''' 
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    total_games INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    rank INTEGER DEFAULT 0
                )
            ''')

    def upsert_player(self, player_id, name):
        with self.conn:
            cursor = self.conn.execute('SELECT name FROM players WHERE id = ?', (player_id,))
            row = cursor.fetchone()
            if row:
                self.conn.execute('UPDATE players SET name = ? WHERE id = ?', (name, player_id))
            else:
                self.conn.execute('INSERT INTO players (id, name) VALUES (?, ?)', (player_id, name))

    def update_player_stats(self, player_id, wins, losses):
        with self.conn:
            self.conn.execute('''
                UPDATE players
                SET total_games = total_games + 1,
                    wins = wins + ?,
                    losses = losses + ?
                WHERE id = ?
            ''', (wins, losses, player_id))

    def update_win_rate(self, player_id: int):
        with self.conn:
            cursor = self.conn.execute('SELECT wins, total_games FROM players WHERE id = ?', (player_id,))
            row = cursor.fetchone()
            if row:
                wins, total_games = row
                win_rate = wins / total_games if total_games > 0 else 0
                print(win_rate)
                self.conn.execute('UPDATE players SET win_rate = ? WHERE id = ?', (win_rate, player_id))

    def finalize_game(self):
        cursor = self.conn.execute('SELECT id FROM players')
        players = cursor.fetchall()
        for player in players:
            self.update_win_rate(player[0])
        self.update_rank()

    def update_rank(self):
        with self.conn:
            cursor = self.conn.execute('SELECT id, win_rate, total_games FROM players')
            players = cursor.fetchall()
            players_with_scores = []
            for player in players:
                player_id, win_rate, total_games = player
                score = win_rate * math.log(total_games) if total_games > 0 else 0
                players_with_scores.append((player_id, score))
            players_with_scores.sort(key=lambda x: x[1], reverse=True)
            for rank, (player_id, _) in enumerate(players_with_scores, start=1):
                self.conn.execute('UPDATE players SET rank = ? WHERE id = ?', (rank, player_id))

    def get_player(self, player_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM players WHERE id = ?', (player_id,))
        return cursor.fetchone()

    def all_players(self):
        cursor = self.conn.execute('SELECT * FROM players ORDER BY rank')
        players = cursor.fetchall()
        return players

    def get_player_name(self, player_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT name FROM players WHERE id = ?', (player_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    async def update_db(self, player_info_list, group_id):
        for player_id in player_info_list.values():
            player_info = await nonebot.get_bot().get_group_member_info(
                group_id=group_id,
                user_id=player_id
            )
            if player_info["card"]:
                player_name = player_info["card"]
            else:
                player_name = player_info["nickname"]
            self.upsert_player(player_id, player_name)


class Player(ABC):
    """
    玩家基类
    """
    def __init__(self, player_id: int, player_name: str, group_name: str, transmitter: Transmitter):
        self.id = player_id                     # 玩家的id
        self.name = player_name                 # 玩家的游戏昵称
        self.group_name = group_name            # 玩家的群组昵称
        self.transmitter = transmitter          # 广播器
        self.last_message_time = 0              # 上一次给该玩家发消息的时间
        self._is_police = False                 # 是否上警
        self._is_chief = False                  # 是否为警长
        self._role = None                       # 玩家职业
        self._dead = False                      # 玩家是否已死亡
        self._kind = None                       # 玩家阵营
        self._in_room = False                   # 是否在聊天室
        self._handled = True                    # 玩家是否已操作
        self._vote_count = 0                    # 玩家被投票数
        self._command_dict = {                  # 指令字典
            Phase.BEFORE_ELECTION: [
                {
                    'triggers': ('举手', ),
                    'func': self.raise_hand,
                    'args': ()
                },
                {
                    'triggers': ('弃权', 'SKIP'),
                    'func': self.skip_at_before_election,
                    'args': ()
                },
            ],
            Phase.ELECTION: [
                {
                    'triggers': ('投票', '投', '我投'),
                    'func': self.vote_at_election,
                    'args': (Arg.TARGET_PLAYER,)
                },
                {
                    'triggers': ('弃权', '弃票', 'SKIP'),
                    'func': self.skip_at_election,
                    'args': ()
                },
            ],
            Phase.MORNING: [
                {
                    'triggers': ('完毕', '说完了', '讲完了', '发言结束', 'SKIP'),
                    'func': self.skip_at_morning,
                    'args': tuple()
                }
            ],
            Phase.DAY: [
                {
                    'triggers': ('投票', '投', '我投'),
                    'func': self.vote_at_day,
                    'args': (Arg.TARGET_PLAYER,)
                },
                {
                    'triggers': ('弃权', '弃票', 'SKIP'),
                    'func': self.skip_at_day,
                    'args': tuple()
                }
            ],
            Phase.NIGHT: [],
            Phase.DAWN: [
                {
                    'triggers': ('完毕', '说完了', '讲完了', '发言结束', 'SKIP'),
                    'func': self.skip_at_dawn,
                    'args': tuple()
                }
            ],
            Phase.DUSK: []
        }

    def parse_command(self, raw_message: str, phase: Phase, funcs) -> Tuple[Callable, Dict]:
        phase_commands = self._command_dict.get(phase, [])
        for cmd in phase_commands:
            for trigger in cmd['triggers']:
                pattern = re.compile(rf'^{trigger}\s*')
                if pattern.search(raw_message):
                    rest_content = pattern.sub('', raw_message).strip()
                    args = {}
                    for arg in cmd['args']:
                        if arg == Arg.TARGET_PLAYER:
                            target_player = funcs['get_target_player'](rest_content)
                            args['target_player'] = target_player
                        elif arg == Arg.RAW_MESSAGE:
                            args['raw_message'] = rest_content
                        elif arg == Arg.CHAT_ROOM:
                            args['chat_room'] = funcs['get_chat_room']()
                        elif arg == Arg.TARGET_PLAYERS:
                            args['target_players'] = funcs['get_target_players']()(rest_content)
                        elif arg == Arg.PHASE:
                            args['phase'] = phase
                    return cmd['func'], args
        raise ValueError('错误的指令！')

    async def handle_command(self, raw_message, phase, funcs):
        try:
            func, args = self.parse_command(raw_message, phase, funcs)
            if await func(**args):
                self.set_handled(True)
        except Exception as e:
            logger.info(e)
            if phase == Phase.NIGHT:
                await self.send(str(e))
        finally:
            logger.info(f'已处理{raw_message}请求。')

    def reset_states(self):
        self.set_voted(0)
        self.set_handled(True)
        self._reset_states()

    @abstractmethod
    def _reset_states(self):
        pass

    def can_act(self, phase: Phase):
        if phase == Phase.BEFORE_ELECTION:
            return True
        if phase == Phase.ELECTION:
            return not self._is_police
        if phase == Phase.MORNING:
            return True
        return self._can_act(phase)

    @abstractmethod
    def _can_act(self, phase: Phase):
        pass

    def can_chat(self):
        return self._in_room

    @property
    @abstractmethod
    def kind(self):
        pass

    async def notice(self, info: dict):
        phase = info.get('phase', None)
        if phase == Phase.MORNING and self.role not in [Role.WHITE_WOLF, Role.RIDER]:
            await self.transmitter.send('🎙️' + MessageSegment.at(self.id) + f' 轮到您发言了。\n（发送“完毕”可结束发言）')
            await self.transmitter.ban(self.id, 0)
        elif phase == Phase.DAWN:
            await self.transmitter.send(f'🎙️ {self.name}您已被杀害，请发表遗言。\n（发送“完毕”结束发言）')
            await self.transmitter.ban(self.id, 0)
        else:
            await self._notice(info)

    @abstractmethod
    def _notice(self, info: dict):
        pass

    @property
    def role(self):
        return self._role

    @property
    def dead(self):
        return self._dead

    @property
    def handled(self):
        return self._handled

    @property
    def vote_count(self):
        return self._vote_count

    @property
    def command_dict(self):
        return self._command_dict

    def set_dead(self, value: bool):
        self._dead = value

    def set_handled(self, value: bool):
        self._handled = value

    def set_in_room(self, value: bool):
        self._in_room = value

    def set_kind(self, value: Kind):
        self._kind = value

    def set_chief(self, value: bool):
        self._is_chief = value

    def set_voted(self, value: Optional[int] = None, is_chief=False):
        if value is None:
            if is_chief:
                self._vote_count += 1.5
            else:
                self._vote_count += 1
        else:
            self._vote_count = value

    async def skip_at_before_election(self):
        await self.transmitter.send(f"🤷🏻‍♀️ {self.name}不愿成为警长。")
        self.set_handled(True)

    async def skip_at_election(self):
        await self.transmitter.send(f"🤔 {self.name}犹豫不决，并放弃了投票。")
        self.set_handled(True)

    async def skip_at_morning(self):
        await self.transmitter.send(f"👌🏻 {self.name}发言完毕！")
        await self.transmitter.ban(self.id, 300)
        self.set_handled(True)

    async def skip_at_dawn(self):
        self.set_handled(True)

    async def skip_at_day(self):
        await self.transmitter.send(f"🤔 {self.name}犹豫不决，并放弃了投票。")
        self.set_handled(True)

    async def raise_hand(self):
        self._is_police = True
        await self.transmitter.send(f"🙋🏻‍♀️ {self.name}想成为警长！")
        return True

    async def vote_at_election(self, target_player: 'Player'):
        target_player.set_voted()
        await self.transmitter.send(f"🧐 {self.name}认为{target_player.name}应该成为警长。")
        return True

    async def vote_at_day(self, target_player: 'Player'):
        if not target_player.dead:
            target_player.set_voted(is_chief=self._is_chief)
            await self.transmitter.send(f"🧐 {self.name}认为{target_player.name}是{Role.WEREWOLF.value}？")
            return True
        else:
            await self.transmitter.send(f"😹 {self.name}试图投票给已淘汰的玩家...")
            return False

    async def send(self, message):
        current_time = time.time()
        wait_time = max(0.0, 1.0 - (current_time - self.last_message_time))
        if wait_time > 0.0:
            await asyncio.sleep(wait_time)
        try:
            await nonebot.get_bot().send_msg(
                user_id=self.id,
                message=message,
                message_type='private'
            )
            self.last_message_time = time.time()
        except ActionFailed:
            logger.debug("超时异常，请忽视！")

    async def send_prompt(self, content: str, commands: List[Tuple[str, str]]):
        prompt = f"{role_emojis[self.role]} {self.role.value}\n\n"
        prompt += f"🎯 {content} 行动\n\n"
        if commands:
            prompt += "⚡ 可用指令:"
            for trigger, description in commands:
                prompt += f"\n- {trigger}: {description}"
        await self.send(prompt)

    async def send_prompt_with_transmitter(self, content: str, commands: List[Tuple[str, str]]):
        prompt = f"{role_emojis[self.role]} {self.role.value}\n\n"
        prompt += f"🎯 {content} 行动\n\n"
        if commands:
            prompt += "⚡ 可用指令:"
            for trigger, description in commands:
                prompt += f"\n- {trigger}: {description}"
        await self.transmitter.send(prompt)


class Villager(Player):
    """村民"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.VILLAGER

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return False
        elif phase == Phase.DAWN:
            return self.dead

    async def _notice(self, info):
        pass


class Explorer(Player):
    """探险家"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.EXPLORER
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('收买',),
                'func': self.buy,
                'args': tuple()
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]
        self._have_bought = False
        self._killed_by_wolf = False

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        self.set_killed_by_wolf(False)

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return not self.have_bought and self.killed_by_wolf
        elif phase == Phase.DAWN:
            return self.dead

    @property
    def killed_by_wolf(self):
        return self._killed_by_wolf

    @property
    def have_bought(self):
        return self._have_bought

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    async def buy(self):
        if not self.have_bought:
            self.set_dead(False)
            self.set_have_bought(True)
            await self.send(f"💰 钱袋子打狼，一去不回...")
            return True
        else:
            await self.send(f"⭕ 您已经收买过狼人...")
            return False

    def set_have_bought(self, value: bool):
        self._have_bought = value

    def set_killed_by_wolf(self, value: bool):
        self._killed_by_wolf = value

    async def _notice(self, info):
        phase = info.get('phase')
        if phase == Phase.NIGHT and self.killed_by_wolf:
            content = "狼人试图杀害您！您可以用金币收买狼人，让它放弃对您的迫害"
            commands = [
                ("收买", "收买狼人自救"),
                ("跳过", "跳过本次操作")
            ]
            await self.send_prompt(content, commands)


class Werewolf(Player):
    """狼人"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.WEREWOLF
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('杀害', '杀死', '杀'),
                'func': self.kill,
                'args': (Arg.TARGET_PLAYER, Arg.CHAT_ROOM)
            },
            {
                'triggers': ('chat',),
                'func': self.chat,
                'args': (Arg.CHAT_ROOM, Arg.RAW_MESSAGE)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': (Arg.CHAT_ROOM,)
            }
        ]

    @property
    def kind(self):
        return Kind.WEREWOLF

    def _reset_states(self):
        pass

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return True
        elif phase == Phase.DAWN:
            return self.dead

    async def skip_at_night(self, chat_room):
        for member in chat_room:
            if member != self:
                await member.send(f"⏭️ 您的队友{self.name}跳过了本回合。")
                member.set_in_room(False)
                member.set_handled(True)
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    async def kill(self, chat_room, target_player: Player):
        if not target_player.dead:
            for member in chat_room:
                if member != self:
                    await member.send(f"🔪 您的队友{self.name}采取了对{target_player.name}的行动！狼人回合结束。")
                    member.set_in_room(False)
                    member.set_handled(True)
            await self.send(f"🔪 您杀害了 {target_player.name}。")
            target_player.set_dead(True)
            if isinstance(target_player, Explorer):
                target_player.set_killed_by_wolf(True)
            return True
        await self.send(f"⭕ {target_player.name}早已死亡😿😿😿。")
        return False

    async def chat(self, chat_room, raw_message):
        if not chat_room:
            await self.send("⭕ 今晚只有您一个狼人，无法聊天")
            return False
        for member in chat_room:
            if member.id != self.id:
                await member.send(f'{self.name}：{raw_message}')
        return False

    async def _notice(self, info):
        phase: Phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        other_werewolves = info.get('other_werewolves')
        if phase == Phase.NIGHT:
            content = "请选择要杀害的玩家，或与队友交流" if other_werewolves else "请选择要杀害的玩家"
            commands = [
                ("杀害『』", "杀害序号为『』的玩家"),
                ("chat 『』", "向队友发送消息：『』"),
                ("跳过", "跳过本次操作")
            ] if other_werewolves else [
                ("杀害『』", "杀害序号为『』的玩家"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)


class WhiteWolf(Player):
    """狼人"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.WHITE_WOLF
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('杀害', '杀死', '杀'),
                'func': self.kill,
                'args': (Arg.TARGET_PLAYER, Arg.CHAT_ROOM)
            },
            {
                'triggers': ('chat',),
                'func': self.chat,
                'args': (Arg.CHAT_ROOM, Arg.RAW_MESSAGE)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': (Arg.CHAT_ROOM,)
            }
        ]
        self._command_dict[Phase.MORNING] += [
            {
                'triggers': ('自爆', ),
                'func': self.explode,
                'args': (Arg.TARGET_PLAYER, )
            },
        ]
        self._have_exploded = False

    @property
    def kind(self):
        return Kind.WEREWOLF

    @property
    def have_exploded(self):
        return self._have_exploded

    def set_have_exploded(self, value: bool):
        self._have_exploded = value

    def _reset_states(self):
        self._have_exploded = False

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return True
        elif phase == Phase.DAWN:
            return self.dead

    async def skip_at_night(self, chat_room):
        for member in chat_room:
            if member != self:
                await member.send(f"⏭️ 您的队友{self.name}跳过了本回合。")
                member.set_in_room(False)
                member.set_handled(True)
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    async def kill(self, chat_room, target_player: Player):
        if not target_player.dead:
            for member in chat_room:
                if member != self:
                    await member.send(f"🔪 您的队友{self.name}采取了对{target_player.name}的行动！狼人回合结束。")
                    member.set_in_room(False)
                    member.set_handled(True)
            await self.send(f"🔪 您杀害了 {target_player.name}。")
            target_player.set_dead(True)
            if isinstance(target_player, Explorer):
                target_player.set_killed_by_wolf(True)
            return True
        await self.send(f"⭕ {target_player.name}早已死亡😿😿😿。")
        return False

    async def explode(self, target_player: Player):
        if not target_player.dead:
            await self.transmitter.send(f"🙀 {self.name} 自爆并带走了 {target_player.name}。")
            target_player.set_dead(True)
            self.set_dead(True)
            self.set_have_exploded(True)
            return True
        await self.transmitter.send(f"⭕ {target_player.name}早已死亡😿😿😿。")
        return False

    async def chat(self, chat_room, raw_message):
        if len(chat_room) == 1:
            await self.send("⭕ 今晚只有您一个狼人，无法聊天")
            return False
        for member in chat_room:
            if member.id != self.id:
                await member.send(f'{self.name}：{raw_message}')
        return False

    async def _notice(self, info):
        phase: Phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.NIGHT:
            other_werewolves = info.get('other_werewolves')
            content = "请选择要杀害的玩家，或与队友交流" if other_werewolves else "请选择要杀害的玩家"
            commands = [
                ("杀害『』", "杀害序号为『』的玩家"),
                ("chat 『』", "向队友发送消息：『』"),
                ("跳过", "跳过本次操作")
            ] if other_werewolves else [
                ("杀害『』", "杀害序号为『』的玩家"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)
        elif phase == Phase.MORNING:
            content = "您可以选择自爆带走一名玩家"
            commands = [
                ("自爆『』", "自爆带走序号为『』的玩家"),
                ("完毕", "正常结束发言")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)
            await self.transmitter.send('🎙️' + MessageSegment.at(self.id) + f' 轮到您发言了。\n（发送“完毕”可结束发言）')
            await self.transmitter.ban(self.id, 0)


class Seer(Player):
    """预言家"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.SEER
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('预言', '验'),
                'func': self.predict,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return True
        elif phase == Phase.DAWN:
            return self.dead

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    async def predict(self, target_player: Player):
        if target_player.role.value == Role.CUPID:
            await self.send(f"🔮 {target_player.name} 是 {Kind.VILLAGER.value} ？？！")
            return True
        await self.send(f"🔮 {target_player.name} 是 {target_player.kind.value} ？？！")
        return True

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.NIGHT:
            content = "请选择要查验身份的玩家"
            commands = [
                ("预言『』", "查验序号为『』的玩家的身份"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)


class Witch(Player):
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.WITCH
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('毒害', '毒'),
                'func': self.poison,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('治疗', '救'),
                'func': self.save,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]
        self._have_saved = False
        self._have_poisoned = False

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return not self.have_saved or not self.have_poisoned
        elif phase == Phase.DAWN:
            return self.dead

    @property
    def have_saved(self):
        return self._have_saved

    @property
    def have_poisoned(self):
        return self._have_poisoned

    def set_have_saved(self, value: bool):
        self._have_saved = value

    def set_have_poisoned(self, value: bool):
        self._have_poisoned = value

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    async def poison(self, target_player: Player):
        if not self.have_poisoned:
            if not target_player.dead:
                await self.send(f"🧪 您毒害了 {target_player.name}。")
            else:
                await self.send(f"⭕ 您毒害了 {target_player.name}，但是他早已死亡😿😿😿。")
            target_player.set_dead(True)
            self.set_have_poisoned(True)
            return True
        else:
            await self.send("⭕ 您已使用过毒药。")
            return False

    async def save(self, target_player: Player):
        if not self.have_saved:
            if target_player.dead:
                target_player.set_dead(False)
                self.set_have_saved(True)
                await self.send(f"🔯 您治疗了 {target_player.name}。")
                return True
            else:
                await self.send("⭕ 这名玩家并未死亡。")
                return False
        else:
            await self.send("⭕ 您已使用过解药。")
            return False

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        victims: list = info.get('victims')()
        if phase == Phase.NIGHT:
            commands = []
            content = ''
            if victims and not self.have_saved:
                content += f"玩家 {', '.join(v.name for v in victims)} 遇害，您可以使用解药\n"
                commands.append(("治疗『』", "治疗序号为『』的玩家"))
            if not self.have_poisoned:
                content += "您可以使用毒药，毒害一名玩家"
                commands.append(("毒害『』", "毒害序号为『』的玩家"))
            commands.append(("跳过", "放弃操作"))
            await self.send(alive_players)
            await self.send_prompt(content, commands)


class Hunter(Player):
    """猎人"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.HUNTER
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('肘击', '肘'),
                'func': self.shoot_at_night,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]
        self._command_dict[Phase.DUSK] += [
            {
                'triggers': ('肘击', '肘'),
                'func': self.shoot_at_day,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.shoot_at_day,
                'args': (Arg.TARGET_PLAYER,)
            }
        ]
        self.have_shot = False

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        self.have_shot = False

    def set_shot(self, value: bool):
        self.have_shot = value

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return self.dead and not self.have_shot
        elif phase == Phase.NIGHT:
            return self.dead and not self.have_shot
        elif phase == Phase.DAWN:
            return self.dead

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)
        self.set_shot(True)

    async def skip_at_dusk(self):
        await self.transmitter.send(f"⏭️ 牢大放弃了肘击...")
        self.set_handled(True)
        self.set_shot(True)

    async def shoot_at_night(self, target_player: Player):
        if not target_player.dead:
            await self.send(f"💪 您肘击了{target_player.name}。")
        else:
            await self.send(f"⭕ 您肘击了{target_player.name}，但是他早已死亡😿😿😿。")
        target_player.set_dead(True)
        self.set_shot(True)
        return True

    async def shoot_at_day(self, target_player: Player):
        await self.transmitter.send(f"💪 {self.name}肘击了{target_player.name}！")
        target_player.set_dead(True)
        self.set_shot(True)
        return True

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.NIGHT:
            content = "您已死亡，可以肘击带走一名玩家"
            commands = [
                ("肘击『』", "肘击带走序号为『』的玩家"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)
        if phase == Phase.DUSK:
            content = "您已被放逐，可以肘击带走一名玩家"
            commands = [
                ("肘击X", "肘击带走序号为『』的玩家"),
                ("跳过", "跳过本次操作")
            ]
            await self.transmitter.send(alive_players)
            await self.send_prompt_with_transmitter(content, commands)


class Guard(Player):
    """守卫"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.GUARD
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('守护', '守'),
                'func': self.protect,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]
        self._last_protected = None

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return True
        elif phase == Phase.DAWN:
            return self.dead

    async def protect(self, target_player: Player):
        if target_player == self._last_protected:
            await self.send("⭕ 您不能连续两晚守护同一玩家！")
            return False
        if target_player != self:
            self._last_protected = target_player
            target_player.set_dead(False)
            await self.send(f"🛡️ 您守护了 {target_player.name}。")
            return True
        else:
            await self.send("⭕ 您无法保护自己！")
            return False

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.NIGHT:
            content = "您可以守护一名玩家"
            commands = [
                ("守护『』", "守护序号为『』的玩家"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)


class Rider(Player):
    """其实"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.RIDER
        self._command_dict[Phase.MORNING] += [
            {
                'triggers': ('决斗', '戳'),
                'func': self.battle,
                'args': (Arg.TARGET_PLAYER,)
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_morning,
                'args': tuple()
            }
        ]
        self._have_found_wolf = False

    @property
    def kind(self):
        return Kind.VILLAGER

    @property
    def have_found_wolf(self):
        return self._have_found_wolf

    def _reset_states(self):
        self._have_found_wolf = False

    def set_found_wolf(self, value: bool):
        self._have_found_wolf = value

    async def skip_at_morning(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return False
        elif phase == Phase.DAWN:
            return self.dead

    async def battle(self, target_player: Player):
        if target_player.kind == Kind.WEREWOLF:
            self.set_found_wolf(True)
            await self.transmitter.send(f"😻 {self.name}是真正的骑士！")
            target_player.set_dead(True)
            return True
        await self.transmitter.send(f"😹 {self.name}不是一个称职的骑士...")
        self.set_dead(True)
        return True

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.MORNING:
            content = "您可以选择一名玩家决斗"
            commands = [
                ("决斗『』", "与序号为『』的玩家决斗"),
                ("完毕", "正常结束发言")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)
            await self.transmitter.send('🎙️' + MessageSegment.at(self.id) + f' 轮到您发言了。\n（发送“完毕”可结束发言）')
            await self.transmitter.ban(self.id, 0)


class Nerd(Player):
    """白痴"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.NERD
        self._command_dict[Phase.DUSK] += [
            {
                'triggers': ('自爆', '爆'),
                'func': self.reveal,
                'args': tuple()
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_dusk,
                'args': tuple()
            }
        ]
        self.have_revealed = False

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    async def skip_at_dusk(self):
        self.set_handled(True)

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return not self.have_revealed
        elif phase == Phase.DUSK:
            return not self.have_revealed
        elif phase == Phase.NIGHT:
            return False
        elif phase == Phase.DAWN:
            return self.dead

    def set_revealed(self, value: bool):
        self.have_revealed = value

    async def reveal(self):
        if not self.have_revealed:
            self.set_dead(False)
            await self.transmitter.send(f"😹 {self.name} 自爆了身份，原来他是 {Role.NERD.value}！！！")
            await self.transmitter.send(f"😼 {self.name} 重新回到了游戏中。")
            self.set_revealed(True)
            return True
        else:
            await self.transmitter.send(f"⭕ 您已自爆过一次了...")
            return False

    async def _notice(self, info):
        phase = info.get('phase')
        if phase == Phase.DUSK and self.dead:
            content = f"{self.name}原来是{Role.NERD.value}！他可以选择留在游戏中"
            commands = [
                ("自爆", "揭示身份留在游戏"),
                ("跳过", "跳过本次操作")
            ]
            await self.send_prompt_with_transmitter(content, commands)


class Cupid(Player):
    """白痴"""
    def __init__(self, player_id, name, group_name, transmitter):
        super().__init__(player_id, name, group_name, transmitter)
        self._role = Role.CUPID
        self._command_dict[Phase.NIGHT] += [
            {
                'triggers': ('连接', '连接'),
                'func': self.shoot,
                'args': (Arg.TARGET_PLAYERS, )
            },
            {
                'triggers': ('跳过', 'SKIP'),
                'func': self.skip_at_night,
                'args': tuple()
            }
        ]
        self.have_shot = False

    @property
    def kind(self):
        return Kind.VILLAGER

    def _reset_states(self):
        pass

    def _can_act(self, phase: Phase) -> bool:
        if phase == Phase.DAY:
            return True
        elif phase == Phase.DUSK:
            return False
        elif phase == Phase.NIGHT:
            return not self.have_shot
        elif phase == Phase.DAWN:
            return self.dead

    def set_shot(self, value: bool):
        self.have_shot = value

    async def skip_at_night(self):
        await self.send(f"⏭️ 您选择了跳过本次操作。")
        self.set_handled(True)
        self.set_shot(True)

    async def shoot(self, target_players: List[Player]):
        if not self.have_shot:
            if all(p.kind == Kind.VILLAGER for p in target_players):
                self.set_kind(Kind.VILLAGER)
            elif all(p.kind == Kind.WEREWOLF for p in target_players):
                self.set_kind(Kind.WEREWOLF)
            else:
                self.set_kind(Kind.CUPID)
                for p in target_players:
                    p.set_kind(Kind.CUPID)
            await self.send(f'💞 您成功连接了{'，'.join([p.name for p in target_players])}')
            await target_players[0].send(f'💞 您与{target_players[1]}成为了情侣！')
            await target_players[1].send(f'💞 您与{target_players[0]}成为了情侣！')
            return True
        else:
            await self.send(f"⭕ 您已连接过一次了..")
            return False

    async def _notice(self, info):
        phase = info.get('phase')
        alive_players: str = info.get('alive_players')()
        if phase == Phase.NIGHT:
            content = "请连接两名玩家成为情侣"
            commands = [
                ("连接X Y", "连接玩家X和Y"),
                ("跳过", "跳过本次操作")
            ]
            await self.send(alive_players)
            await self.send_prompt(content, commands)
