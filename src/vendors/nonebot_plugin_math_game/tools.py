import asyncio
import nonebot
from pathlib import Path
from nonebot_plugin_alconna import UniMessage
from nonebot.adapters.onebot.v11 import ActionFailed, MessageEvent
from nonebot_plugin_waiter import waiter


# 将字符串包装为指令元组
def command_maker_tuple(command):
    command_start = nonebot.get_driver().config.command_start
    return tuple(f"{prefix}{command.lower()}" for prefix in command_start)


async def wait_for(time):
    @waiter(waits=["message"], keep_session=True, block=True)
    async def _(event: MessageEvent):
        return event.get_message().extract_plain_text().strip()
    result = await _.wait(timeout=time, default=False)
    return result


async def get_name(user_id, group_id):
    user_info = await nonebot.get_bot().get_group_member_info(user_id=user_id, group_id=group_id)
    return user_info.get('card') or user_info.get('nickname', 'Unknown User')


async def send_message(msg, at_sender=False):
    try:
        _ = asyncio.create_task(UniMessage.text(msg).send(at_sender=at_sender))
    except ActionFailed:
        pass


async def send_image(path):
    try:
        _ = asyncio.create_task(UniMessage.image(path=path).send())
    except ActionFailed:
        pass


async def send_audio(path):
    try:
        _ = asyncio.create_task(UniMessage.audio(path=path).send())
    except ActionFailed:
        pass


async def send_file(path):
    try:
        _ = asyncio.create_task(UniMessage.file(path=Path(path).as_uri()).send())
    except ActionFailed:
        pass
