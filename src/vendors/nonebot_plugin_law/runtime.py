import asyncio
import time
from typing import TYPE_CHECKING, Callable, Dict, Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from .manager import VoteManager
from .strategies import BanStrategy, GeneralStrategy, KickStrategy, SetStrategy, Strategy, TopicStrategy

if TYPE_CHECKING:
    from src.support.group import GroupContext


async def _get_name(event: GroupMessageEvent) -> str:
    from src.support.group import get_name_simple

    return await get_name_simple(event)


def _extract_target_id(message: str) -> Optional[int]:
    from src.support.group import get_id

    return get_id(message)


async def _wait_for_text(timeout: int):
    from src.support.group import wait_for

    return await wait_for(timeout)


async def _wait_for_message_event(timeout: int):
    from src.support.group import wait_for_event

    return await wait_for_event(timeout)


def build_vote_handler(
    vote_manager: VoteManager,
    group: "GroupContext",
    *,
    on_vote_success: Optional[Callable[[int, int], bool]] = None,
) -> Callable:
    async def handle_vote(event: GroupMessageEvent):
        user_input = event.get_message().extract_plain_text().strip()
        if int(user_input) in vote_manager.options.keys():
            if vote_manager.vote(event.user_id, int(user_input)):
                honor_awarded = False
                if on_vote_success:
                    try:
                        honor_awarded = bool(on_vote_success(event.user_id, int(user_input)))
                    except Exception:
                        honor_awarded = False
                suffix = "（荣誉+1）" if honor_awarded else ""
                await group.send_msg(f"{await _get_name(event)}已表态！{suffix}")
            else:
                await group.send_msg("您已投过票了！")

    return handle_vote


async def _collect_topic(
    strategy: Strategy,
    group: "GroupContext",
    event: GroupMessageEvent,
    vote_manager: VoteManager,
) -> Optional[Dict]:
    if isinstance(strategy, TopicStrategy):
        if not event.reply:
            await group.send_msg("请设置您的议题：\n(请使用肯定句)")
            content = await _wait_for_text(60)
            if not content:
                await group.send_msg("您未设置议题，系统已自动退出。")
                return None
            if content == "退出":
                await group.send_msg("系统已退出。")
            topic = {"content": content}
        else:
            topic = {"content": event.reply.message.extract_plain_text().strip()}
        strategy.setup_options(vote_manager)
        return topic

    if isinstance(strategy, SetStrategy):
        if not event.reply:
            await group.send_msg("请回复您要设为精华的消息：")
            input_event = await _wait_for_message_event(60)
            if not input_event or not input_event.reply:
                return None
            msg = str(input_event.get_message()).strip()
            if msg == "退出":
                await group.send_msg("系统已退出。")
            mid = input_event.reply.message_id
        else:
            mid = event.reply.message_id
        if not mid:
            return None
        topic = {"content": mid}
        strategy.setup_options(vote_manager)
        return topic

    if isinstance(strategy, BanStrategy):
        if not event.reply:
            await group.send_msg("请@您要禁言的成员：")
            input_event = await _wait_for_message_event(60)
            if not input_event:
                return None
            msg = str(input_event.get_message()).strip()
            if msg == "退出":
                await group.send_msg("系统已退出。")
            target_id = _extract_target_id(msg)
        else:
            target_id = _extract_target_id(event.reply.message.extract_plain_text().strip())
        if not target_id:
            return None
        topic = {"content": target_id}
        strategy.setup_options(vote_manager)
        return topic

    if isinstance(strategy, KickStrategy):
        if not event.reply:
            await group.send_msg("请@您要放逐的成员：")
            input_event = await _wait_for_message_event(60)
            if not input_event:
                return None
            msg = str(input_event.get_message()).strip()
            if msg == "退出":
                await group.send_msg("系统已退出。")
            target_id = _extract_target_id(msg)
        else:
            target_id = _extract_target_id(event.reply.message.extract_plain_text().strip())
        if not target_id:
            return None
        topic = {"content": target_id}
        strategy.setup_options(vote_manager)
        return topic

    if isinstance(strategy, GeneralStrategy):
        await group.send_msg("请设置投票主题：")
        topic_text = await _wait_for_text(60)
        if not topic_text:
            await group.send_msg("您未设置投票主题，系统已自动退出。")
            return None
        if topic_text == "退出":
            await group.send_msg("系统已退出。")
        await group.send_msg("请设置投票选项，用换行符分开。\n例如：\n1. 苹果\n2. 香蕉")
        options = await _wait_for_text(60)
        if not options:
            await group.send_msg("未设置选项，系统已自动退出。")
            return None
        for idx, option in enumerate(options.split("\n"), 1):
            vote_manager.set_option(idx, option.strip())
        return {"content": topic_text}

    return None


async def _get_vote_duration(group: "GroupContext") -> Optional[int]:
    await group.send_msg("请选择投票结束时间：\n1. 一分钟\n2. 五分钟\n3. 十分钟")
    wait_time = await _wait_for_text(60)
    if not wait_time or wait_time not in Strategy.TIME_DICT:
        await group.send_msg("结束时间未设置或不合法，系统已自动退出。")
        return None
    return Strategy.TIME_DICT[wait_time][1]


async def wait_for_condition(wait_condition, wait_time):
    start_time = time.time()
    while wait_condition():
        if time.time() - start_time > wait_time:
            return True
        await asyncio.sleep(0.1)
    return False
