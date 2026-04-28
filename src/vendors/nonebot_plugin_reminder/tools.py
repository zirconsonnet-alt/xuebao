import time
import asyncio
from typing import Callable, Optional

from nonebot import on_message
from nonebot_plugin_waiter import waiter
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent


async def wait_for(wait_time):
    @waiter(waits=["message"], keep_session=True, block=True)
    async def _(event: MessageEvent):
        return event.get_message().extract_plain_text().strip()
    result = await _.wait(timeout=wait_time, default='')
    return result


async def wait_for_plus(user_id: int, group_id: int, wait_time: float) -> Optional[GroupMessageEvent]:
    user_input: Optional[GroupMessageEvent] = None

    handled = False
    async def _checker(event: GroupMessageEvent) -> bool:
        return event.user_id == user_id and event.group_id == group_id
    matcher = on_message(rule=_checker)

    async def _handler(e: GroupMessageEvent):
        nonlocal user_input, handled
        if not handled:
            user_input = e
            handled = True
    matcher.append_handler(_handler)
    timed_out = await wait_for_condition(lambda: handled, wait_time)
    matcher.destroy()
    return None if timed_out else user_input


async def wait_for_condition(
    condition_checker: Callable[[], bool],
    max_wait: float
) -> bool:
    start_time = time.time()
    while not condition_checker():
        if time.time() - start_time > max_wait:
            return True
        await asyncio.sleep(0.1)
    return False
