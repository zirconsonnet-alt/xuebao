import re
import time
import asyncio
import nonebot
from typing import Optional, Tuple
from nonebot.adapters.onebot.v11 import MessageEvent, Message, MessageSegment
from nonebot.compat import type_validate_python
from nonebot_plugin_waiter import waiter


async def wait_for(wait_time) -> str:
    @waiter(waits=["message"], keep_session=True, block=False)
    async def _(event: MessageEvent):
        return event.get_message().extract_plain_text().strip()
    result = await _.wait(timeout=wait_time, default='')
    return result


async def wait_for_condition(wait_condition, wait_time, game_is_running, interruption_exception):
    start_time = time.time()
    while wait_condition():
        if not game_is_running():
            raise interruption_exception
        if time.time() - start_time > wait_time:
            return True
        await asyncio.sleep(0.1)
    return False


def is_valid_name(text):
    # 允许的字符范围：中英文、数字、标点符号和 Emoji，不允许换行符号
    allowed_characters_pattern = re.compile(
        r'^[\u4e00-\u9fff a-zA-Z0-9,.!?，。！？：；“”‘’（）()【】{}《》—\-…'  # 标点符号
        r'\u2600-\u2B55\u1F300-\u1F5FF\u1F600-\u1F64F\u1F680-\u1F6FF'
        r'\u1F700-\u1F77F\u1F780-\u1F7FF\u1F800-\u1F8FF'
        r'\u1F900-\u1F9FF\u1FA70-\u1FAFF\U00010000-\U0010FFFF]+$',
        re.UNICODE
    )
    # 检查长度是否超过 12 个字符
    if len(text) > 12:
        return False
    # 检查是否包含非法字符或换行符号
    if not allowed_characters_pattern.match(text) or '\n' in text or '\r' in text:
        return False
    return True


async def get_resent_file(group_id) -> Tuple[Optional[str], Optional[str]]:
    result = await nonebot.get_bot().get_group_root_files(group_id=group_id)
    file = result['files'][0]
    if not file['file_name'].lower().endswith(('.wav', '.mp3')):
        return None, None
    result = await nonebot.get_bot().get_group_file_url(
        group_id=group_id,
        file_id=file['file_id'],
        busid=file['busid']
    )
    return file['file_name'], result['url']


async def upload_file(group_id, file_path, file_name):
    await nonebot.get_bot().upload_group_file(
        group_id=group_id,
        file=file_path,
        name=file_name
    )


async def get_msg(msg_id) -> Message:
    try:
        resp = await nonebot.get_bot().get_msg(
            message_id=msg_id
        )
        return type_validate_python(Message, resp['message'])
    except Exception as e:
        print(e)
        return Message(MessageSegment.text('💢 该消息记录已被删除'))


async def wait_for_event(time):
    @waiter(waits=["message"], keep_session=True, block=False)
    async def _(event: MessageEvent):
        return event
    result = await _.wait(timeout=time, default=False)
    return result
