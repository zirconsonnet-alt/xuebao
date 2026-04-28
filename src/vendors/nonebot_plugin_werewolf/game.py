import asyncio
import nonebot
from typing import Optional
from functools import partial
from arclet.alconna import Arparma, Alconna
from nonebot.internal.matcher import Matcher
from nonebot.internal.rule import Rule
from nonebot import logger, on_message
from nonebot_plugin_alconna import on_alconna
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent
from transitions.extensions.asyncio import AsyncMachine, AsyncState
from .game_mode import GameMode
from .handler import FormalHandler
from .player_manager import PlayerManager
from .player_registry import PlayerRegistry
from .player import PlayerDatabase, WhiteWolf, Rider
from .tool import wait_for, is_valid_name, wait_for_condition
from .transmitter import Transmitter
from .enum import Role, Phase, data_dir, MessageType, Kind, role_emojis
from .presets import werewolf_guide, player_guide


class StateMachine:
    ROLE_IN_ORDER_AT_NIGHT = [Role.CUPID, Role.WEREWOLF, Role.EXPLORER, Role.SEER, Role.WITCH, Role.GUARD, Role.HUNTER]
    ROLE_IN_ORDER_AT_DUSK = [Role.WHITE_WOLF, Role.HUNTER, Role.NERD]
    states = [
        AsyncState(
            name='Init'
        ),
        AsyncState(
            name='BeforeElection'
        ),
        AsyncState(
            name='Election'
        ),
        AsyncState(
            name='Night'
        ),
        AsyncState(
            name='Dawn',
        ),
        AsyncState(
            name='Morning',
        ),
        AsyncState(
            name='Day',
        ),
        AsyncState(
            name='Dusk'
        ),
        AsyncState(
            name='End'
        )
    ]

    def __init__(self, game_mode: GameMode, transmitter: Transmitter, player_manager: PlayerManager):
        self.player_manager = player_manager
        self.game_mode = game_mode
        self.day_account = 0
        self.is_running = True
        self.transmitter = transmitter
        self.winner = None
        self.special_state = False
        self.machine = AsyncMachine(
            model=self,
            states=StateMachine.states,
            initial='Init'
        )
        self.machine.add_transition(
            trigger='to_before_election',
            source='Init',
            dest='BeforeElection',
            after='begin_before_election',
        )
        self.machine.add_transition(
            trigger='to_election',
            source='BeforeElection',
            dest='Election',
            after='begin_election',
        )
        self.machine.add_transition(
            trigger='to_night',
            source=['Dusk', 'Election', 'Morning', 'Init'],
            dest='Night',
            after='begin_night',
        )
        self.machine.add_transition(
            trigger='to_dawn',
            source='Night',
            dest='Dawn',
            after='begin_dawn'
        )
        self.machine.add_transition(
            trigger='to_morning',
            source='Dawn',
            dest='Morning',
            after='begin_morning'
        )
        self.machine.add_transition(
            trigger='to_day',
            source='Morning',
            dest='Day',
            after='begin_day'
        )
        self.machine.add_transition(
            trigger='to_dusk',
            source=['Day'],
            dest='Dusk',
            after='begin_dusk'
        )
        self.machine.add_transition(
            trigger='to_end',
            source='*',
            dest='End',
            after='begin_end'
        )

    async def start_game(self):
        if len(self.player_manager.all_players) >= 6:
            await self.to_before_election()
            await self.to_election()
        while self.is_running:
            await self.refresh_alive_player_list()
            await self.to_night()
            if self.check_game_end():
                break
            await self.to_dawn()
            await self.refresh_alive_player_list()
            if self.check_game_end():
                break
            await self.to_morning()
            await self.refresh_alive_player_list()
            if self.check_game_end():
                break
            if not self.special_state:
                await self.to_day()
                await self.to_dusk()
                if self.check_game_end():
                    break
            else:
                self.special_state = False
        await self.to_end()

    async def refresh_alive_player_list(self):
        await self.player_manager.refresh()

    async def begin_before_election(self):
        await self.transmitter.send(f"🙋🏻‍♀️ 游戏开始，请需要竞选警长的玩家发送消息“举手”！不竞选的玩家可以发送“弃权”。")
        await self.player_manager.set_players_able_to_act(
            players=self.player_manager.player_list,
            phase=Phase.BEFORE_ELECTION
        )
        logger.info("等待玩家竞选")
        act = on_message(rule=command_checker(self.player_manager), block=True)
        act.append_handler(FormalHandler.handler(self.player_manager, Phase.BEFORE_ELECTION))
        await self.wait_and_notify(
            wait_time1=30,
            wait_time2=0,
            timeout_callback=partial(self.skip_rest_players, Phase.BEFORE_ELECTION),
            message_type=MessageType.GROUP_MESSAGE
        )
        act.destroy()

    async def begin_election(self):
        if not [player for player in self.player_manager.player_list if not player.can_act(Phase.ELECTION)]:
            return
        await self.transmitter.send(
            f"📮 请未举手的玩家发送“我投xxx”选举警长！"
        )
        await self.player_manager.set_players_able_to_act(
            players=self.player_manager.player_list,
            phase=Phase.ELECTION
        )
        logger.info("等待玩家投票")
        act = on_message(rule=command_checker(self.player_manager), block=True)
        act.append_handler(FormalHandler.handler(self.player_manager, Phase.ELECTION))
        await self.wait_and_notify(
            wait_time1=25,
            wait_time2=5,
            message="❗ 投票时间仅剩5秒，请尽快完成投票！",
            timeout_callback=partial(self.skip_rest_players, Phase.ELECTION),
            message_type=MessageType.GROUP_MESSAGE
        )
        act.destroy()
        await self.player_manager.end_vote_at_election()

    async def begin_morning(self):
        self.day_account += 1
        await self.transmitter.send(
            f"------🙀🙀🙀第{self.day_account}天🙀🙀🙀------\n"
            f"{self.player_manager.alive_players()}\n"
            f"🎙️ 每位玩家有60秒时间进行发言。"
        )
        music = await self.transmitter.get_file_by_name('morning.wav')
        picture = await self.transmitter.get_file_by_name('background.webp')
        await self.transmitter.send_card(f'第{self.day_account}天', music, picture)
        for player in self.player_manager.player_list:
            await self.player_manager.set_players_able_to_act(
                players=[player],
                phase=Phase.MORNING
            )
            act = on_message(rule=command_checker(self.player_manager), block=True)
            act.append_handler(FormalHandler.handler(self.player_manager, Phase.MORNING))
            await self.wait_and_notify(
                wait_time1=90,
                wait_time2=30,
                message="❗ 您的发言时间仅剩10秒！",
                timeout_callback=partial(self.skip_rest_players, Phase.MORNING),
                message_type=MessageType.GROUP_MESSAGE
            )
            act.destroy()
            white_wolves = self.player_manager.player_dict.get(Role.WHITE_WOLF, [])
            if white_wolves:
                white_wolf = white_wolves[0]
                if isinstance(white_wolf, WhiteWolf) and white_wolf.have_exploded:
                    self.special_state = True
                    return
            riders = self.player_manager.player_dict.get(Role.RIDER, [])
            if riders:
                rider = riders[0]
                if isinstance(rider, Rider) and rider.have_found_wolf:
                    self.special_state = True
                    return

    async def begin_day(self):
        await asyncio.sleep(1)
        self.day_account += 1
        for p in self.player_manager.player_list:
            await self.transmitter.ban(p.id, 0)
        await self.transmitter.send(
            f"{self.player_manager.alive_players()}\n"
            f"📮 请在60秒内完成投票。发送“我投”并指定目标玩家即可投票，您也可以发送“弃权”。"
        )
        await self.player_manager.set_players_able_to_act(
            players=self.player_manager.player_list,
            phase=Phase.DAY
        )
        logger.info("等待玩家投票")
        act = on_message(rule=command_checker(self.player_manager), block=True)
        act.append_handler(FormalHandler.handler(self.player_manager, Phase.DAY))
        await self.wait_and_notify(
            wait_time1=50,
            wait_time2=10,
            message="投票时间仅剩10秒，请尽快完成投票！",
            timeout_callback=partial(self.skip_rest_players, Phase.DAY),
            message_type=MessageType.GROUP_MESSAGE
        )
        act.destroy()
        await self.player_manager.end_vote_at_day()

    async def begin_dusk(self):
        await self.transmitter.send("🌅 黄昏时刻")
        roles = []
        for role in StateMachine.ROLE_IN_ORDER_AT_DUSK:
            if role in self.player_manager.player_dict.keys():
                if role == Role.HUNTER:
                    roles += [Role.HUNTER] * len(self.player_manager.player_dict[Role.HUNTER])
                else:
                    roles.append(role)
        for role in roles:
            await self.player_manager.set_players_able_to_act(
                players=self.player_manager.player_dict[role],
                phase=Phase.DUSK
            )
            if not self.player_manager.players_able_to_act:
                continue
            logger.info(f"等待{role.value}操作")
            act = on_message(rule=command_checker(self.player_manager), block=True)
            act.append_handler(FormalHandler.handler(self.player_manager, Phase.DUSK))
            await self.wait_and_notify(
                wait_time1=50,
                wait_time2=10,
                timeout_callback=partial(self.skip_rest_players, Phase.DUSK),
                message_type=MessageType.GROUP_MESSAGE
            )
            act.destroy()

    async def begin_night(self):
        await self.transmitter.send("🌙 夜幕降临")
        music = await self.transmitter.get_file_by_name('mellohi.wav')
        picture = await self.transmitter.get_file_by_name('background.webp')
        await self.transmitter.send_card('夜幕降临', music, picture)
        for p in self.player_manager.player_list:
            await self.transmitter.ban(p.id, 300)
        roles = []
        for role in StateMachine.ROLE_IN_ORDER_AT_NIGHT:
            if role in self.player_manager.player_dict.keys():
                if role == Role.HUNTER:
                    roles += [Role.HUNTER] * len(self.player_manager.player_dict[Role.HUNTER])
                else:
                    roles.append(role)
        for role in roles:
            players = self.player_manager.player_dict[role]
            if role == Role.WEREWOLF:
                players += self.player_manager.player_dict.get(Role.WHITE_WOLF, [])
            await self.player_manager.set_players_able_to_act(
                players=players,
                phase=Phase.NIGHT
            )
            if not self.player_manager.players_able_to_act:
                continue
            await self.transmitter.send(f"{role_emojis[role]} 请职业为{role.value}的玩家及时操作！")
            act = on_message(rule=command_checker(self.player_manager), block=False)
            act.append_handler(FormalHandler.handler(self.player_manager, Phase.NIGHT))
            await self.wait_and_notify(
                wait_time1=100 if role == Role.WEREWOLF else 50,
                wait_time2=20 if role == Role.WEREWOLF else 10,
                message="❗ 时间仅剩10秒，请尽快完成操作！",
                timeout_callback=partial(self.skip_rest_players, Phase.NIGHT)
            )
            act.destroy()

    async def begin_dawn(self):
        if victims := [p for p in self.player_manager.player_list if p.dead]:
            await self.transmitter.send(
                f"😿 昨晚{'，'.join(victim.name for victim in victims)}遇害了。"
            )
            if self.day_account == 0:
                for player in victims:
                    await self.player_manager.set_players_able_to_act(
                        players=[player],
                        phase=Phase.DAWN
                    )
                    act = on_message(rule=command_checker(self.player_manager), block=True)
                    act.append_handler(FormalHandler.handler(self.player_manager, Phase.DAWN))
                    await self.wait_and_notify(
                        wait_time1=25,
                        wait_time2=5,
                        message="❗ 您的发言时间仅剩5秒！",
                        timeout_callback=partial(self.skip_rest_players, Phase.DAWN),
                        message_type=MessageType.GROUP_MESSAGE
                    )
        else:
            await self.transmitter.send(f"🙏🏻 昨晚是一个平安夜！")

    async def begin_end(self):
        if self.winner == "None":
            await self.transmitter.send('😿 无人取得胜利...')
            return
        werewolves = [player for player in self.player_manager.all_players if player.kind == Kind.WEREWOLF]
        villagers = [player for player in self.player_manager.all_players if player.kind == Kind.VILLAGER]
        cupids = [player for player in self.player_manager.all_players if player.kind == Kind.CUPID]
        if self.winner == Kind.WEREWOLF:
            await self.transmitter.send(f'🥷 {self.winner.value}取得了胜利😈')
            await self.game_result(werewolves, villagers + cupids)
            music = await self.transmitter.get_file_by_name('mw3.wav')
            picture = await self.transmitter.get_file_by_name('background.webp')
            await self.transmitter.send_card(f'{Role.WEREWOLF.value}胜利', music, picture)
        elif self.winner == Kind.VILLAGER:
            await self.transmitter.send(f'🐆 {self.winner.value}取得了胜利😸')
            await self.game_result(villagers, werewolves + cupids)
            music = await self.transmitter.get_file_by_name('promise.wav')
            picture = await self.transmitter.get_file_by_name('background.webp')
            await self.transmitter.send_card(f'{Role.VILLAGER.value}胜利', music, picture)
        elif self.winner == Kind.CUPID:
            await self.transmitter.send(f'{'，'.join(player.name for player in villagers)}取得了胜利😸')
            await self.game_result(cupids, werewolves + villagers)
        logger.info("游戏已结束")
        for p in self.player_manager.all_players:
            await self.transmitter.ban(p.id, 0)
            await self.transmitter.set_name(p.id, p.group_name)
            print(p.group_name)
        await self.transmitter.send("🕹️ 游戏已结束！再来一局？")

    async def game_result(self, winners, losers):
        player_db = PlayerDatabase(data_dir)
        winner_message = "📈游戏结算：\n\n😼 胜利者：\n"
        winner_message += '\n'.join(f"{player.name}（{player.role.value}）" for player in winners) + "\n"
        loser_message = "\n😿 失败者：\n"
        loser_message += '\n'.join(f"{player.name}（{player.role.value}）" for player in losers)
        await self.transmitter.send(winner_message + loser_message)
        for player in winners:
            player_db.update_player_stats(player.id, wins=1, losses=0)
        for player in losers:
            player_db.update_player_stats(player.id, wins=0, losses=1)
        player_db.finalize_game()

    def check_game_end(self):
        print('正在检查游戏是否结束')
        game_over, winner = self.game_mode.check_victory(self.player_manager)
        if game_over:
            self.winner = winner
            if winner == 'None':
                logger.info("无人幸免")
            else:
                logger.info(f"{winner.value}胜利")
        return game_over

    # 等待并提醒玩家进行操作
    async def wait_for_player_action(self, wait_time: int):
        return await wait_for_condition(
            wait_condition=lambda: self.player_manager.players_able_to_act,
            wait_time=wait_time,
            game_is_running=lambda: self.is_running,
            interruption_exception=GameInterrupted
        )

    # 等待并提醒玩家进行操作
    async def wait_and_notify(
            self,
            wait_time1,
            wait_time2,
            message=None,
            timeout_callback=None,
            message_type=MessageType.PRIVATE_MESSAGE
    ):
        print('开始等待')
        is_timeout = await self.wait_for_player_action(wait_time1)
        if is_timeout:
            print('第一次等待超时')
            if message_type == MessageType.PRIVATE_MESSAGE:
                for player in self.player_manager.players_able_to_act:
                    await player.send(message)
            elif message_type == MessageType.GROUP_MESSAGE:
                await self.transmitter.send(message)
            is_timeout = await self.wait_for_player_action(wait_time2)
            if is_timeout and timeout_callback:
                print('第二次等待超时')
                await timeout_callback()

    async def skip_rest_players(self, phase):
        for player in list(self.player_manager.players_able_to_act):
            funcs = {
                'get_target_player': self.player_manager.get_target_player,
                'get_target_players': self.player_manager.get_target_players,
                'get_chat_room': lambda: self.player_manager.chat_room
            }
            await player.handle_command('SKIP', phase, funcs)


# 游戏整体类
class Game:
    """游戏主体"""
    def __init__(self, transmitter: Transmitter):
        self.game_mode: Optional[GameMode] = None
        self.state_machine: Optional[StateMachine] = None
        self.game_interrupt_matcher = None
        self.transmitter: Optional[Transmitter] = transmitter
        self.player_manager: Optional[PlayerManager] = None
        self.player_registry: Optional[PlayerRegistry] = PlayerRegistry()
        self.player_help_matcher: Optional[Matcher] = None

    # 玩家开始参与游戏
    async def join_game(self, game_mode, group_id):
        """启动玩家参与阶段"""
        logger.info("初始化玩家信息")
        player_info_list = {}
        is_joining = {'is_joining': True}
        join, join_close = await self.setup_join_handlers(group_id, player_info_list, is_joining, game_mode)
        game_help_matcher = on_alconna('help')
        game_help_matcher.append_handler(self.game_help_handler())
        await self.wait_and_notify(player_info_list, is_joining)
        join.destroy()
        join_close.destroy()
        game_help_matcher.destroy()
        await self.initialize_game(game_mode, group_id, player_info_list)
        await self.broadcast_player_roles()
        await self.transmitter.set_name(nonebot.get_bot().self_id, '🙀雪豹杀🙀')
        await self.transmitter.send(f'🎉 游戏开始！\n本局的职业配置是：\n{self.game_mode.display_role_list()}')
        await self.transmitter.send(self.player_manager.alive_players())

    async def setup_join_handlers(self, group_id, player_info_list, is_joining, game_mode):
        join = on_alconna(Alconna(r're:我要参加\s*(?:[\u3001、，;:]*\s*我是\s*(?P<name>[^\s]+))?'))
        join.append_handler(self.join_handler(player_info_list, group_id, is_joining, game_mode))
        join_close = on_alconna(Alconna(r're:参与结束'))
        join_close.append_handler(lambda: is_joining.update({'is_joining': False}))
        return join, join_close

    async def wait_and_notify(self, player_info_list, is_joining):
        is_timeout = await Game.wait_for_player_action(player_info_list, is_joining, 110)
        if is_timeout:
            await self.transmitter.send('❗ 10秒后将停止游戏的参与...')
            await Game.wait_for_player_action(player_info_list, is_joining, 10)

    async def initialize_game(self, game_mode, group_id, player_info_list):
        await PlayerDatabase(data_dir).update_db(player_info_list, group_id)
        self.game_mode = GameMode(
            game_mode=game_mode,
            num_players=len(player_info_list)
        )
        self.player_manager = PlayerManager(
            group_id=group_id,
            player_registry=self.player_registry,
            transmitter=self.transmitter
        )
        self.state_machine = StateMachine(
            self.game_mode,
            self.transmitter,
            self.player_manager
        )
        self.player_manager.set_player_list(player_info_list, self.game_mode.generate_role_list().copy())
        logger.info(f"玩家信息如下：{self.player_manager.alive_players()}")
        self.game_interrupt_matcher = on_alconna('游戏结束', priority=0)
        self.game_interrupt_matcher.append_handler(self.game_interrupt_handler())
        self.player_help_matcher = on_alconna('help', aliases={'帮助'}, priority=0, block=True)
        self.player_help_matcher.append_handler(self.player_help_handler())

    async def broadcast_player_roles(self):
        """广播玩家角色信息"""
        werewolves = [player for player in self.player_manager.player_list if player.kind == Kind.WEREWOLF]
        for player in self.player_manager.player_list:
            msg = Game.create_role_message(player, werewolves)
            await player.send(msg)
            await self.transmitter.set_name(player.id, player.name)

    @staticmethod
    def create_role_message(player, werewolves):
        if player.role == Role.VILLAGER:
            base_message = (f'🎖️ {player.name}，您是{role_emojis[player.role]} {player.role.value}，'
                            f'您无法在夜间行动。请运用您的智慧，找出真正的{Role.WEREWOLF.value}😼!')
        elif player.role in [Role.WEREWOLF, Role.WHITE_WOLF]:
            base_message = (f'🎖️ {player.name}，您是{role_emojis[player.role]} {player.role.value}！'
                            f'您的任务是骗过所有人，成为最后的赢家😈。')
            if len(werewolves) > 1:
                base_message += f'\n本局的您的队友是\n{'；\n'.join([
                    f"{i + 1}. {p.name}\n(职业：{p.role.value})" for i, p in enumerate(werewolves)
                ]) + '。'}。'
        else:
            base_message = f'🎖️ {player.name}，您的职业是：{role_emojis[player.role]} {player.role.value}😺！'
        base_message += "\n发送help可查看角色指引。"
        return base_message

    @staticmethod
    async def wait_for_player_action(player_info_list, is_joining, wait_time):
        return await wait_for_condition(
            wait_condition=lambda: len(player_info_list) <= 9 and is_joining['is_joining'],
            wait_time=wait_time,
            game_is_running=lambda: True,
            interruption_exception=GameInterrupted
        )

    def join_handler(self, player_info_list, group_id, is_joining, game_mode):
        async def _(event: MessageEvent, result: Arparma):
            if event.user_id in [2017823739]:
                await self.transmitter.send(f"❌ 您已被永久禁赛！")
                return
            friend_desc = {}
            friend_list = await nonebot.get_bot().get_friend_list()
            for i in friend_list:
                friend_desc[i['user_id']] = f"{i['remark']}/{i['nickname']}"
            if event.user_id not in friend_desc:
                await self.transmitter.send(f"❌ 您需要先加机器人为好友才能加入游戏！")
                return
            if event.user_id in player_info_list.values():
                await self.transmitter.send(f"❌ 您已在游戏中！")
                return
            name = result.header["name"]
            if not name:
                player_id = event.user_id
                player_info = await nonebot.get_bot().get_group_member_info(group_id=group_id, user_id=player_id)
                if player_info["card"]:
                    name = player_info["card"]
                else:
                    name = player_info["nickname"]
            name = name.strip()
            if name in player_info_list:
                await self.transmitter.send(f'❌ {name} 该名称已有玩家采用。')
            else:
                if is_valid_name(name) and not (name.isdigit() and int(name) < 12):
                    player_id = event.user_id
                    player_info_list[name] = player_id
                    await self.transmitter.send(f'✅ {name} 您已进入游戏。')
                    strategy = GameMode.STRATEGIES[game_mode]
                    max_players = max(
                        max_players
                        for (min_players, max_players) in strategy.ROLE_CONFIG.keys()
                    )
                    if len(player_info_list) >= max_players:
                        await self.transmitter.set_name(
                            nonebot.get_bot().self_id,
                            f'✅ 人数已满({max_players}人)，游戏开始...'
                        )
                        is_joining['is_joining'] = False
                    else:
                        await self.transmitter.set_name(
                            nonebot.get_bot().self_id,
                            f'🐆{len(player_info_list)}人已参与...🥷'
                        )
                else:
                    await self.transmitter.send(f'❌ 您的名称不合法！')
        return _

    def game_interrupt_handler(self):
        async def _():
            await self.transmitter.send('您确定要终止游戏的运行吗？回复1确定，回复其他内容取消。')
            resp = await wait_for(10)
            if resp == '1':
                self.state_machine.is_running = False
        return _

    def player_help_handler(self):
        async def _(event: PrivateMessageEvent):
            _ = asyncio.create_task(
                nonebot.get_bot().send_forward_msg(
                    message_type='private',
                    user_id=event.user_id,
                    messages=[
                        player_guide[next(p for p in self.player_manager.player_list if p.id == event.user_id).role]
                      ]
                )
            )
        return _

    def game_help_handler(self):
        async def _():
            await self.transmitter.send_forward_msg(werewolf_guide)
        return _

    def clean_up(self):
        if self.game_interrupt_matcher:
            self.game_interrupt_matcher.destroy()
            self.game_interrupt_matcher = None
        if self.player_help_matcher:
            self.player_help_matcher.destroy()
            self.player_help_matcher = None


class GameInterrupted(Exception):
    def __str__(self):
        return f"游戏已被终止。"


def command_checker(player_manager: PlayerManager):
    async def _checker(event: MessageEvent) -> bool:
        player_id = event.user_id
        if player_id in [player.id for player in player_manager.players_able_to_act]:
            return True
        elif player_id in [player.id for player in player_manager.chat_room]:
            return True
        return False
    return Rule(_checker)


def to_player(pid: int):
    async def _checker(event: MessageEvent) -> bool:
        print(f'正在判断是否是{pid}发送')
        print(pid == event.user_id)
        return pid == event.user_id
    return Rule(_checker)
