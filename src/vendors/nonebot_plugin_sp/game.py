import time
import asyncio
import nonebot
from typing import Dict, Tuple, Optional, Union, List
from nonebot.internal.rule import Rule
from nonebot import on_message, on_command
from .tools import get_msg, wait_for_event
from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    GroupMessageEvent,
    Message,
    MessageSegment
)


class TurtleSoupGame:
    def __init__(self, group_id: int, host_id: int, host_name: str, message_id: int, max_questions):
        self.group_id = group_id
        self.host_id = host_id
        self.host_name = host_name
        self.soup = message_id
        self.max_questions = max_questions
        self.remaining_questions = max_questions
        self.game_is_running = True
        self.winner = None
        self.answer = None
        self.start_time = time.time()
        self.qa_records: Dict[int, Tuple[int, int, Optional[int]]] = {}
        self.hints: List[int] = []
        self.last_question = None
        self.next_question_id = 1
        self.last_message_time = 0
        self.last_activity_time = time.time()

    async def start_game(self):
        await nonebot.get_bot().set_group_card(
            group_id=self.group_id,
            user_id=int(nonebot.get_bot().self_id),
            card='😼 雪豹大侦探'
        )
        await nonebot.get_bot().set_group_card(
            group_id=self.group_id,
            user_id=self.host_id,
            card='🐢 主持人 🍲'
        )
        await self.send(Message([
            MessageSegment.text(
                f"🍲 海龟汤游戏开始！主持人: \n"
            ),
            MessageSegment.at(self.host_id),
            MessageSegment.text(
                f"\n📜 汤面: 见回复消息\n"
                f"❓ 大家可以用是/否/无关的问题提问，主持人会回答\n"
                f"🔢 剩余问题次数: {self.max_questions}\n"
                f"⏱️ 猜出汤底或问题用尽游戏结束\n"
                f"操作方法：\n"
                f"提问：句尾添加双问号（？？）；\n"
                f"回答：回复触发提问的消息；\n"
                f"定位汤面：/汤面；\n"
                f"补充提示：/提示。\n"
                f"结束游戏：/结束；\n"
                f"查询提问记录：/线索；\n"
            ),
            MessageSegment.reply(self.soup)
        ])
        )
        question_matcher = on_message(rule=self.question_rule(), priority=0, block=False)
        question_matcher.append_handler(self.handle_question)
        answer_matcher = on_message(rule=self.answer_rule(), priority=0, block=False)
        answer_matcher.append_handler(self.handle_host_answer)
        close_matcher = on_command("结束", priority=0, block=True)
        close_matcher.append_handler(self.close_game_handler)
        recorder_matcher = on_command("线索", priority=0, block=True)
        recorder_matcher.append_handler(self.recorder_handler)
        soup_matcher = on_command("汤面", priority=0, block=True)
        soup_matcher.append_handler(self.soup_handler)
        hint_matcher = on_command("提示", priority=0, block=True)
        hint_matcher.append_handler(self.hint_handler)
        try:
            warning_sent = False
            while self.game_is_running and self.remaining_questions >= 0 and not self.winner:
                current_time = time.time()
                inactive_time = current_time - self.last_activity_time
                if inactive_time > 540 and not warning_sent:
                    await self.send("⏳ 游戏长时间无活动，将在1分钟后自动结束")
                    warning_sent = True
                if inactive_time > 600:
                    await self.send("⏳ 游戏长时间无活动，自动结束")
                    break
                if warning_sent and current_time - self.last_activity_time < 540:
                    await self.send("✅ 恢复活动，游戏继续")
                    warning_sent = False
                await asyncio.sleep(1)
            mvp_players = await self.calculate_mvp()
            mvp_text = self.format_mvp_text(mvp_players)
            if self.winner:
                elapsed = time.time() - self.start_time
                min_sec = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"
                await self.send(Message([
                    MessageSegment.text(
                        f"🎉 恭喜 "),
                    MessageSegment.at(self.winner),
                    MessageSegment.text(
                        "\n猜中了汤底！\n"
                        f"💡 汤底: 见回复消息\n"
                        f"⏱️ 用时: {min_sec}\n"
                        f"❓ 使用问题数: {self.max_questions - self.remaining_questions}/{self.max_questions}\n"
                        f"{mvp_text}"
                    ),
                    MessageSegment.reply(self.answer)
                ])
                )
            else:
                await self.send(
                    f"🔚 游戏结束！无人猜中汤底\n"
                    f"💡 请主持人公布答案"
                    f"{mvp_text}"
                )
        except Exception as e:
            print(e)
        finally:
            question_matcher.destroy()
            answer_matcher.destroy()
            close_matcher.destroy()
            recorder_matcher.destroy()
            soup_matcher.destroy()
            hint_matcher.destroy()
            game_manager = TurtleSoupGameManager()
            game_manager.end_game(self.group_id)
            await nonebot.get_bot().set_group_card(
                group_id=self.group_id,
                user_id=self.host_id,
                card=self.host_name
            )
            await nonebot.get_bot().set_group_card(
                group_id=self.group_id,
                user_id=int(nonebot.get_bot().self_id),
                card='牢雪豹'
            )

    async def calculate_mvp(self) -> List[Tuple[int, int]]:
        yes_count = {}
        for qid, record in self.qa_records.items():
            user_id, question_id, answer_id = record
            if answer_id is None:
                continue
            answer_msg = await get_msg(answer_id)
            answer_text = answer_msg.extract_plain_text().strip()
            if answer_text == "是":
                yes_count[user_id] = yes_count.get(user_id, 0) + 1
        sorted_players = sorted(yes_count.items(), key=lambda x: x[1], reverse=True)
        return sorted_players[:3]

    @staticmethod
    def format_mvp_text(mvp_players: List[Tuple[int, int]]) -> str:
        if not mvp_players:
            return ""
        text_lines = ["🏆 MVP榜单（获得'是'回答最多）："]
        for idx, (player_id, count) in enumerate(mvp_players):
            rank = ["🥇 MVP", "🥈 第二名", "🥉 第三名"][idx] if idx < 3 else f"第{idx + 1}名"
            text_lines.append(f"{rank}: {MessageSegment.at(player_id)} - {count}次")
        return "\n".join(text_lines)

    def question_rule(self):
        def _(event: GroupMessageEvent):
            question = event.message.extract_plain_text().strip()
            return (
                event.group_id == self.group_id and
                event.user_id != self.host_id and
                self.game_is_running and
                len(question) >= 3 and
                question.endswith(('??', '？？'))
            )
        return Rule(_)

    def answer_rule(self):
        def _(event: GroupMessageEvent):
            return (
                event.group_id == self.group_id and
                event.user_id == self.host_id and
                self.game_is_running and
                event.reply is not None and
                event.message.extract_plain_text().strip().startswith(('是', '不是', '不重要', '是也不是', '恭喜'))
            )
        return Rule(_)

    async def handle_question(self, event: GroupMessageEvent):
        question_id = event.message_id
        question = event.get_plaintext().strip()
        if not question:
            return
        if self.remaining_questions == 0:
            await self.send("🛑 提问次数已用光")
            return
        qid = self.next_question_id
        self.last_question = event.message_id
        self.qa_records[qid] = (event.user_id, question_id, None)
        self.next_question_id += 1
        self.remaining_questions -= 1
        await self.send(
            f"❓ 问题[{qid}]: {MessageSegment.at(event.user_id)} 提问: {question}\n"
            f"👤 请主持人 {MessageSegment.at(self.host_id)} 回复 (是/不是/不重要/是也不是/恭喜)\n"
            f"🔢 剩余问题数: {self.remaining_questions}"
        )

    async def handle_host_answer(self, event: GroupMessageEvent):
        response_id = event.message_id
        response = event.message.extract_plain_text().strip()
        replied_msg_id = event.reply.message_id
        target_qid = None
        is_modification = False
        for qid, (asker_id, question_id, answer_id) in self.qa_records.items():
            if answer_id == replied_msg_id:
                target_qid = qid
                is_modification = True
                break
            elif question_id == replied_msg_id:
                target_qid = qid
                break
        if target_qid is None:
            return
        asker_id, question_id, old_answer_id = self.qa_records[target_qid]
        if is_modification:
            await self.send(f"🔄 主持人修改了问题[{target_qid}]的回答")
        if response.startswith('恭喜'):
            self.winner = asker_id
            self.answer = response_id
            self.game_is_running = False
            self.qa_records[target_qid] = (asker_id, question_id, response_id)
            question_msg = await get_msg(question_id)
            question_text = question_msg.extract_plain_text().strip()
            await self.send(Message([
                MessageSegment.text(f"🎉 恭喜 "),
                MessageSegment.at(asker_id),
                MessageSegment.text(
                    "猜中了汤底！\n"
                    f"👤 主持人确认: {response}\n"
                    f"💬 问题[{target_qid}]: {question_text}"
                )
            ]))
            return
        elif self.remaining_questions == 0 and not is_modification:
            self.game_is_running = False
        self.qa_records[target_qid] = (asker_id, question_id, response_id)
        question_msg = await get_msg(question_id)
        question_text = question_msg.extract_plain_text().strip()
        if is_modification:
            await self.send(
                f"🔄 主持人修改了回答: {response}\n"
                f"💬 问题[{target_qid}]: {question_text}\n"
                f"🙋 提问者: {MessageSegment.at(asker_id)}"
            )
        else:
            await self.send(
                f"👤 主持人回答: {response}\n"
                f"💬 问题[{target_qid}]: {question_text}\n"
                f"🙋 提问者: {MessageSegment.at(asker_id)}"
            )

    async def close_game_handler(self):
        self.game_is_running = False
        await self.send("🛑 已结束游戏")

    async def soup_handler(self):
        await self.send(MessageSegment.reply(self.soup) + MessageSegment.text('🐢 汤面如上'))

    async def hint_handler(self, event: GroupMessageEvent):
        if event.user_id != self.host_id:
            await self.send("❌ 只有主持人可以发送提示")
            return
        if event.reply:
            mid = event.reply.message_id
        else:
            await self.send("💡 请发送您的提示内容(将记录并显示在线索中)")
            hint_msg = await wait_for_event(30)
            if not hint_msg:
                await self.send("⏱️ 提示超时未发送")
                return
            mid = hint_msg.message_id
        self.hints.append(mid)
        await self.send("✅ 提示已记录")

    async def recorder_handler(self):
        msg = [
            MessageSegment.node_custom(
                user_id=int(nonebot.get_bot().self_id),
                nickname="😼 雪豹大侦探",
                content=Message(
                    "📝 雪豹为您整理线索如下："
                )
            ),
            MessageSegment.node_custom(
                user_id=int(nonebot.get_bot().self_id),
                nickname="🐢 汤面",
                content=await get_msg(self.soup)
            )
        ]
        for record in self.qa_records.values():
            if record[1] and record[2]:
                if question := await get_msg(record[1]):
                    msg.append(MessageSegment.node_custom(
                        user_id=record[0],
                        nickname="❓ 提问",
                        content=question
                    ))
                if answer := await get_msg(record[2]):
                    if answer.extract_plain_text().strip() == '是':
                        emoji = '✅'
                    elif answer.extract_plain_text().strip() == '不是':
                        emoji = '❌'
                    elif answer.extract_plain_text().strip() == '❓':
                        emoji = '❓'
                    else:
                        emoji = '🚫'
                    msg.append(MessageSegment.node_custom(
                        user_id=self.host_id,
                        nickname=f"{emoji} 回答",
                        content=answer.extract_plain_text().strip()
                    ))
        if self.hints:
            msg.append(MessageSegment.node_custom(
                user_id=int(nonebot.get_bot().self_id),
                nickname="💡 主持人提示",
                content=Message("以下是主持人提供的提示：")
            ))

            for hint_id in self.hints:
                if hint_msg := await get_msg(hint_id):
                    msg.append(MessageSegment.node_custom(
                        user_id=self.host_id,
                        nickname="💡 提示",
                        content=hint_msg
                    ))
        await nonebot.get_bot().send_group_forward_msg(
            group_id=self.group_id,
            messages=msg
        )

    async def send(self, message: Union[MessageSegment, Message, str]):
        current_time = time.time()
        self.last_activity_time = time.time()
        wait_time = max(0.0, 1.0 - (current_time - self.last_message_time))
        if wait_time > 0.0:
            await asyncio.sleep(wait_time)
        try:
            bot = nonebot.get_bot()
            await bot.send_group_msg(group_id=self.group_id, message=message)
            self.last_message_time = time.time()
        except ActionFailed:
            pass


class TurtleSoupGameManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TurtleSoupGameManager, cls).__new__(cls)
            cls._instance.active_games = {}
        return cls._instance

    def start_game(self, group_id: int, host_id: int, host_name: str, message_id: int, max_questions: int) -> bool:
        if group_id in self.active_games:
            return False
        game = TurtleSoupGame(group_id, host_id, host_name, message_id, max_questions)
        self.active_games[group_id] = game
        asyncio.create_task(game.start_game())
        return True

    def end_game(self, group_id: int):
        if group_id in self.active_games:
            del self.active_games[group_id]

    def is_game_active(self, group_id: int) -> bool:
        return group_id in self.active_games
