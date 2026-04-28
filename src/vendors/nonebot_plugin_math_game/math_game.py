import re
import time
import random
import sqlite3
import asyncio
import traceback
import nonebot
from enum import Enum
from typing import List
from pathlib import Path
from datetime import date
from nonebot.internal.rule import Rule
from nonebot import on_fullmatch, on_message
from nonebot.adapters.onebot.v11 import MessageEvent, ActionFailed, GroupMessageEvent, MessageSegment
from .tools import get_name, wait_for


class LeaderboardType(Enum):
    TOTAL = "总榜"
    DAILY = "日榜"
    MONTHLY = "月榜"


class PlayerDatabase:
    _instances = {}

    def __new__(cls, group_id):
        if group_id not in cls._instances:
            cls._instances[group_id] = super(PlayerDatabase, cls).__new__(cls)
        return cls._instances[group_id]

    def __init__(self, group_id):
        if not hasattr(self, 'initialized'):  # 确保只初始化一次
            self.initialized = True
            self.db_name = Path('data') / 'math_game' / 'players.db'
            self.group_id = group_id
            self.conn = sqlite3.connect(self.db_name)
            self.create_leaderboards()

    def __del__(self):
        self.conn.close()

    def create_leaderboards(self):
        self.create_total_leaderboard()
        self.create_daily_leaderboard()
        self.create_monthly_leaderboard()

    def create_total_leaderboard(self):
        with self.conn:
            self.conn.execute(f'''
                CREATE TABLE IF NOT EXISTS total_leaderboard_{self.group_id} (
                    player_id INTEGER PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    total_games INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    avg_time REAL DEFAULT 1e+30,
                    interrupted INTEGER DEFAULT 0,
                    interrupt INTEGER DEFAULT 0
                )
            ''')

    def create_daily_leaderboard(self):
        with self.conn:
            self.conn.execute(f'''
                CREATE TABLE IF NOT EXISTS daily_leaderboard_{self.group_id} (
                    date TEXT,
                    player_id INTEGER,
                    player_name TEXT NOT NULL,
                    total_games INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    avg_time REAL DEFAULT 1e+30,
                    interrupted INTEGER DEFAULT 0,
                    interrupt INTEGER DEFAULT 0,
                    PRIMARY KEY (date, player_id)
                )
            ''')

    def create_monthly_leaderboard(self):
        with self.conn:
            self.conn.execute(f'''
                CREATE TABLE IF NOT EXISTS monthly_leaderboard_{self.group_id} (
                    month TEXT,
                    player_id INTEGER,
                    player_name TEXT NOT NULL,
                    total_games INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    avg_time REAL DEFAULT 1e+30,
                    interrupted INTEGER DEFAULT 0,
                    interrupt INTEGER DEFAULT 0,
                    PRIMARY KEY (month, player_id)
                )
            ''')

    def add_or_update_total_leaderboard(self, player_id, player_name):
        print(f"Inserting into total_leaderboard_{self.group_id}: {player_id}, {player_name}")
        self.conn.execute(f'''
            INSERT INTO total_leaderboard_{self.group_id} (player_id, player_name)
            VALUES (?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                player_name = excluded.player_name
        ''', (player_id, player_name))

    def add_or_update_daily_leaderboard(self, player_id, player_name):
        date_value = date.today().isoformat()
        print(f"Inserting into daily_leaderboard_{self.group_id}: {date_value}, {player_id}, {player_name}")
        self.conn.execute(f'''
            INSERT INTO daily_leaderboard_{self.group_id} (date, player_id, player_name)
            VALUES (?, ?, ?)
            ON CONFLICT(date, player_id) DO UPDATE SET
                player_name = excluded.player_name
        ''', (date_value, player_id, player_name))

    def add_or_update_monthly_leaderboard(self, player_id, player_name):
        date_value = date.today().strftime('%Y-%m')
        print(f"Inserting into monthly_leaderboard_{self.group_id}: {date_value}, {player_id}, {player_name}")
        self.conn.execute(f'''
            INSERT INTO monthly_leaderboard_{self.group_id} (month, player_id, player_name)
            VALUES (?, ?, ?)
            ON CONFLICT(month, player_id) DO UPDATE SET
                player_name = excluded.player_name
        ''', (date_value, player_id, player_name))

    def add_or_update_player(self, player_id, player_name):
        self.add_or_update_total_leaderboard(player_id, player_name)
        self.add_or_update_daily_leaderboard(player_id, player_name)
        self.add_or_update_monthly_leaderboard(player_id, player_name)

    def update_player_stats(self, player_id, win=False, answer_time=None, interrupted=False, interrupt=False):
        for table_type in ['total_leaderboard', 'daily_leaderboard', 'monthly_leaderboard']:
            self.update_leaderboards(table_type, player_id, win, answer_time, interrupted, interrupt)

    def update_leaderboards(self, table_type, player_id, win=False, answer_time=None, rob=False, answer=False):
        table_name = f"{table_type}_{self.group_id}"
        with self.conn:
            self.conn.execute(f'UPDATE {table_name} SET total_games = total_games + 1 WHERE player_id = ?',
                              (player_id,))
            if win:
                self.conn.execute(f'UPDATE {table_name} SET win_count = win_count + 1 WHERE player_id = ?',
                                  (player_id,))
            if answer_time == 1e+30:
                self.conn.execute(f'''
                    UPDATE {table_name}
                    SET avg_time = (avg_time * (win_count - 1) + ?) / win_count
                    WHERE player_id = ?
                ''', (answer_time, player_id))
            else:
                self.conn.execute(f'''
                    UPDATE {table_name}
                    SET avg_time = ?
                    WHERE player_id = ?
                ''', (answer_time, player_id))
            if rob:
                self.conn.execute(f'UPDATE {table_name} SET interrupted = interrupted + 1 WHERE player_id = ?', (player_id,))
            if answer:
                self.conn.execute(f'UPDATE {table_name} SET interrupt = interrupt + 1 WHERE player_id = ?', (player_id,))

    async def store_game_info(self, player_id, winner_id, elapsed_time):
        win = winner_id == player_id
        interrupted = winner_id is not None and winner_id != player_id
        player_name = await get_name(player_id, self.group_id)
        self.add_or_update_player(player_id, player_name)
        self.update_player_stats(player_id, win=win, answer_time=elapsed_time, interrupted=interrupted)
        if winner_id is not None and winner_id != player_id:
            player_name = await get_name(winner_id, self.group_id)
            self.add_or_update_player(winner_id, player_name)
            self.update_player_stats(winner_id, win=True, answer_time=elapsed_time, interrupt=interrupted)

    def daily_leaderboard_exists(self):
        cursor = self.conn.execute(f'''
            SELECT name FROM sqlite_master WHERE type='table' AND name='daily_leaderboard_{self.group_id}'
        ''')
        return cursor.fetchone() is not None

    def monthly_leaderboard_exists(self):
        cursor = self.conn.execute(f'''
            SELECT name FROM sqlite_master WHERE type='table' AND name='monthly_leaderboard_{self.group_id}'
        ''')
        return cursor.fetchone() is not None

    def total_leaderboard_exists(self):
        cursor = self.conn.execute(f'''
            SELECT name FROM sqlite_master WHERE type='table' AND name='total_leaderboard_{self.group_id}'
        ''')
        return cursor.fetchone() is not None

    def get_leaderboard(self, leaderboard_type: LeaderboardType):
        # 定义基本查询结构
        base_query = '''
            SELECT player_id, player_name, win_count, total_games, avg_time,
                   (win_count * 1.0 / total_games) AS win_rate,
                   (CASE 
                       WHEN total_games > 0 THEN ln(total_games) * (win_count * 1.0 / total_games) 
                       ELSE 0 
                   END) AS scientific_rank
            FROM {}
            WHERE {}
            ORDER BY scientific_rank DESC
            LIMIT 20
        '''

        # 初始化变量
        table_name = ""
        where_condition = ""
        params = ()

        # 根据不同类型构建表名和条件
        if leaderboard_type == LeaderboardType.TOTAL:
            table_name = f"total_leaderboard_{self.group_id}"
            where_condition = "total_games > 0"
            params = ()

        elif leaderboard_type == LeaderboardType.DAILY:
            table_name = f"daily_leaderboard_{self.group_id}"
            today = date.today().isoformat()
            where_condition = "date = ?"
            params = (today,)

        elif leaderboard_type == LeaderboardType.MONTHLY:
            table_name = f"monthly_leaderboard_{self.group_id}"
            current_month = date.today().strftime('%Y-%m')
            where_condition = "month = ?"
            params = (current_month,)

        # 格式化查询并执行
        query = base_query.format(table_name, where_condition)
        with self.conn:
            cursor = self.conn.execute(query, params)
            return cursor.fetchall()


# 游戏类
class TwentyFourGame:
    def __init__(self, group_id, player):
        self.player_id = player
        self.numbers = []
        self.winner = None
        self.game_is_running = True
        self.group_id = group_id
        self.times = 3
        self.last_message_time = 0

    def generate_numbers(self):
        self.numbers = self._find_solution_numbers()

    def _find_solution_numbers(self):
        # 尝试生成一组有效的数字，直到找到可以得出 24 的组合
        while True:
            nums = [random.randint(1, 10) for _ in range(4)]
            if self._has_solution(nums):
                return nums

    def _has_solution(self, nums):
        # 检查给定的四个数字是否可以通过加、减、乘、除等运算得到 24
        from itertools import permutations
        from operator import add, sub, mul, truediv
        # 定义所有可用的运算符
        operations = [add, sub, mul, truediv]
        operation_symbols = ['+', '-', '*', '/']
        # 尝试所有数字的排列组合和运算
        for perm in permutations(nums):
            for op1 in operations:
                for op2 in operations:
                    for op3 in operations:
                        # 使用不同的括号组合来尝试计算结果
                        expressions = [
                            f"(({perm[0]}{operation_symbols[operations.index(op1)]}{perm[1]}){operation_symbols[operations.index(op2)]}{perm[2]}){operation_symbols[operations.index(op3)]}{perm[3]}",
                            f"({perm[0]}{operation_symbols[operations.index(op1)]}{perm[1]}){operation_symbols[operations.index(op2)]}({perm[2]}{operation_symbols[operations.index(op3)]}{perm[3]})",
                            f"({perm[0]}{operation_symbols[operations.index(op1)]}{perm[1]}){operation_symbols[operations.index(op2)]}{perm[2]}{operation_symbols[operations.index(op3)]}{perm[3]}",
                            f"{perm[0]}{operation_symbols[operations.index(op1)]}({perm[1]}{operation_symbols[operations.index(op2)]}({perm[2]}{operation_symbols[operations.index(op3)]}{perm[3]}))",
                            f"{perm[0]}{operation_symbols[operations.index(op1)]}{perm[1]}{operation_symbols[operations.index(op2)]}{perm[2]}{operation_symbols[operations.index(op3)]}{perm[3]}",
                        ]
                        for expr in expressions:
                            try:
                                if eval(expr) == 24:
                                    self.resolution = expr  # 存储找到的表达式
                                    print(expr)
                                    return True
                            except ZeroDivisionError:
                                continue
        return False

    @staticmethod
    def replace_chinese_symbols(expression):
        # 中文数字映射
        numbers = {
            '零': '0', '一': '1', '二': '2', '三': '3', '四': '4',
            '五': '5', '六': '6', '七': '7', '八': '8', '九': '9',
            '十': '10'
        }
        # 中文运算符映射
        operators = {
            '加': '+', '减': '-', '乘': '*', '除': '/',
            '（': '(', '）': ')',
            '×': '*', '÷': '/'
        }

        # 替换中文数字
        for chinese_num, digit in numbers.items():
            expression = expression.replace(chinese_num, digit)

        # 替换中文运算符
        for chinese_op, english_op in operators.items():
            expression = expression.replace(chinese_op, english_op)

        return expression

    def is_valid_expression(self, expression):
        try:
            expression = TwentyFourGame.replace_chinese_symbols(expression)
            # 先计算结果
            result = eval(expression)
            # 拆分表达式为单个元素
            numbers_used = [int(num) for num in re.findall(r'\d+', expression)]
            # 确保使用的数字包含所有生成的数字，且每个数字只用一次
            all_numbers = list(self.numbers)
            return result, sorted(numbers_used) == sorted(all_numbers) and len(numbers_used) == len(all_numbers)
        except Exception as e:
            print(e)
            return None, False

    def in_this_game_checker(self):
        def _(event: GroupMessageEvent):
            return event.user_id == self.player_id and event.group_id == self.group_id
        return Rule(_)

    async def start_game(self):
        self.generate_numbers()
        self.game_is_running = True
        matcher = on_message(rule=self.in_this_game_checker(), priority=2, block=True)
        matcher.append_handler(self.player_handler())

        matcher2 = on_message(rule=not_in_game_checker(), priority=2, block=False)
        matcher2.append_handler(self.others_handler())
        close_game = on_fullmatch('退出', rule=self.in_this_game_checker(), priority=1, block=True)
        close_game.append_handler(self.close_game_handler)
        await self.send(
            f"欢迎来到 24 点游戏！请在60秒内，用这四个数字 {self.numbers} 通过加、减、乘、除和括号使结果等于 24，您共有3次机会！")
        start_time = time.time()
        elapsed_time = None
        try:
            is_timeout = await wait_for_condition(
                wait_condition=lambda: not self.winner and self.times > 0,
                wait_time=50,
                game_is_running=lambda: self.game_is_running,
                interruption_exception=GameInterrupted
            )
            if is_timeout:
                await self.send("还剩10秒，请您尽快作答！")
                await wait_for_condition(
                    wait_condition=lambda: not self.winner and self.times > 0,
                    wait_time=10,
                    game_is_running=lambda: self.game_is_running,
                    interruption_exception=GameInterrupted
                )
            if self.winner == self.player_id:
                elapsed_time = time.time() - start_time
                await self.send("恭喜" + MessageSegment.at(user_id=self.winner) + f" 完成游戏！用时 {elapsed_time:.2f} 秒。")
            elif self.winner:
                elapsed_time = time.time() - start_time
                await self.send(
                    "恭喜" + MessageSegment.at(user_id=self.winner) + f" 抢答成功！用时 {elapsed_time:.2f} 秒。")
            else:
                await self.send(f"很遗憾，无人完成本场游戏！\n正确的答案是{self.resolution}。")
        except GameInterrupted:
            await self.send(f"游戏已终止，正确的答案是{self.resolution}。")
        finally:
            player_manager = PlayerManager()
            player_manager.remove_player(self.group_id, self.player_id)
            player_database = PlayerDatabase(self.group_id)
            try:
                await player_database.store_game_info(self.player_id, self.winner, elapsed_time)
            except Exception as e:
                print(e)
                print(traceback.format_exc())
                await self.send("更新数据库时出现问题，请联系训豹师处理！")
            matcher.destroy()
            matcher2.destroy()
            close_game.destroy()

    async def start_long_game(self):
        num = 10
        for i in range(num):
            self.reset_game_state()
            await self.start_game()
            if self.winner is None:
                await self.send(f'很遗憾，您未能完成10轮挑战，不过您坚持到了第{i+1}轮！', user_id=self.player_id)
                return
            if i == num-1:
                await self.send(f'恭喜您完成10轮挑战！您已获得24点之👑称号！')
                await nonebot.get_bot().set_group_special_title(
                    group_id=self.group_id,
                    user_id=self.player_id,
                    special_title='24点之👑'
                )
                return
            await self.send(f'输入1继续游戏，还剩{9-i}轮！')
            resp = await wait_for(10)
            if not resp == '1':
                await self.send("游戏已提前结束。")
                return

    def reset_game_state(self):
        """重置游戏关键状态以开始新的一轮"""
        self.numbers = []
        self.winner = None
        self.game_is_running = True
        self.times = 3
        self.generate_numbers()

    async def send(self, msg, user_id=None):
        current_time = time.time()
        wait_time = max(0.0, 1.0 - (current_time - self.last_message_time))
        if wait_time > 0.0:
            await asyncio.sleep(wait_time)
        bot = nonebot.get_bot()
        try:
            _ = asyncio.create_task(
                bot.send_group_msg(
                    group_id=self.group_id,
                    message=msg if not user_id else (MessageSegment.at(user_id) + ' ' + msg),
                    auto_escape=False
                )
            )
            self.last_message_time = time.time()
        except ActionFailed:
            print("超时异常，请忽视！")

    def player_handler(self):
        async def _(event: GroupMessageEvent):
            user_input = event.get_message().extract_plain_text().strip()
            result, valid = self.is_valid_expression(user_input)
            if not result:
                await self.send("您的表达式不合法，如需退出，请发送消息 退出。", event.user_id)
                return
            if not valid:
                await self.send(f"请确保只使用给出的数字：{'，'.join([str(number) for number in self.numbers])}。", event.user_id)
                return
            if result == 24:
                self.winner = self.player_id
            else:
                self.times -= 1
                if self.times == 0:
                    await self.send(f"答案错误，您的结果是: {result}\n您已用完游戏次数。", event.user_id)
                else:
                    await self.send(f"答案错误，您的结果是: {result}\n还剩 {self.times} 次机会。", event.user_id)
        return _

    def others_handler(self):
        async def _(event: GroupMessageEvent):
            user_input = event.get_message().extract_plain_text().strip()
            result, valid = self.is_valid_expression(user_input)
            if not valid:
                return
            if result == 24:
                self.winner = event.user_id
            else:
                await self.send(f"答案错误，您的结果是: {result}。", event.user_id)
        return _

    def close_game_handler(self):
        self.game_is_running = False


class PlayerManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PlayerManager, cls).__new__(cls)
            cls._instance.games_info = {}
        return cls._instance

    def add_group(self, group_id):
        if group_id not in self.games_info:
            self.games_info[group_id] = []
            return True
        return False

    def add_player(self, group_id: int, player_id: int) -> bool:
        if group_id in self.games_info:
            self.games_info[group_id].append(player_id)
            return True
        return False

    def remove_player(self, group_id: int, player_id: int) -> bool:
        if group_id in self.games_info and player_id in self.games_info[group_id]:
            del self.games_info[group_id]
            return True
        return False

    def get_players(self, group_id: int) -> List[int]:
        return self.games_info.get(group_id, [])

    def is_player_in_game(self, player_id: int) -> bool:
        return any(player_id in player_list for player_list in self.games_info.values())

    def is_group_in_game(self, group: int) -> bool:
        return group in self.games_info.keys()


def in_game_checker():
    def _(event: MessageEvent):
        player_manager = PlayerManager()
        return player_manager.is_player_in_game(event.user_id)
    return Rule(_)


def not_in_game_checker():
    def _(event: MessageEvent):
        player_manager = PlayerManager()
        return not player_manager.is_player_in_game(event.user_id)
    return Rule(_)


# 辅助函数
async def wait_for_condition(wait_condition, wait_time, game_is_running, interruption_exception):
    start_time = time.time()
    while wait_condition():
        if not game_is_running():
            raise interruption_exception
        if time.time() - start_time > wait_time:
            return True
        await asyncio.sleep(0.1)
    return False


class GameInterrupted(Exception):
    """自定义异常类，用于中断游戏"""
    def __str__(self):
        return f"游戏已被终止。"
