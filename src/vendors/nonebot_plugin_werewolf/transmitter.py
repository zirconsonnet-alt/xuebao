import time
import asyncio
import nonebot
from nonebot import get_bot
from nonebot.log import logger
from nonebot_plugin_alconna import UniMessage
from nonebot.adapters.onebot.v11 import ActionFailed, MessageSegment


class Transmitter:
    GROUP = 627629957

    def __init__(self, group_id):
        self.group_id = group_id
        self.last_message_time = 0

    async def send(self, msg):
        current_time = time.time()
        wait_time = max(0.0, 1.0 - (current_time - self.last_message_time))
        if wait_time > 0.0:
            await asyncio.sleep(wait_time)
        bot = get_bot()
        try:
            _ = asyncio.create_task(
                bot.send_group_msg(
                    group_id=self.group_id,
                    message=msg,
                    auto_escape=False
                )
            )
            self.last_message_time = time.time()
        except ActionFailed:
            logger.debug("超时异常，请忽视！")

    async def send_forward_msg(self, msg):
        current_time = time.time()
        wait_time = max(0.0, 1.0 - (current_time - self.last_message_time))
        if wait_time > 0.0:
            await asyncio.sleep(wait_time)
        bot = get_bot()
        try:
            _ = asyncio.create_task(
                bot.send_forward_msg(
                    message_type='group',
                    group_id=self.group_id,
                    messages=msg
                )
            )
            self.last_message_time = time.time()
        except ActionFailed:
            logger.debug("超时异常，请忽视！")

    @staticmethod
    async def send_message(msg, at_sender=False):
        try:
            _ = asyncio.create_task(UniMessage.text(msg).send(at_sender=at_sender))
        except ActionFailed:
            logger.debug("超时异常，请忽视！")

    @staticmethod
    async def broadcast(player_list, msg):
        for player in player_list:
            await player.send(msg)

    async def ban(self, player_id: int, duration: int):
        bot = get_bot()
        try:
            _ = asyncio.create_task(
                bot.set_group_ban(
                    group_id=self.group_id,
                    user_id=player_id,
                    duration=duration
                )
            )
        except ActionFailed:
            logger.debug("超时异常，请忽视！")

    async def set_name(self, user_id, name):
        await nonebot.get_bot().set_group_card(
            group_id=self.group_id,
            user_id=user_id,
            card=name
        )

    async def transform_in(self):
        try:
            await self.set_name(nonebot.get_bot().self_id, '🙀雪豹杀🙀')
            # await nonebot.get_bot().set_qq_avatar(file=r'C:\BOT\mybot\data\nonebot_plugins_werewolf\background.png')
        except Exception as e:
            print(e)

    async def transform_out(self):
        try:
            await self.set_name(nonebot.get_bot().self_id, '牢雪豹')
            # await nonebot.get_bot().set_qq_avatar(file=r'C:\BOT\mybot\data\nonebot_plugins_werewolf\leopard.jpg')
        except Exception as e:
            print(e)

    async def send_card(self, title, music, picture):
        audio_url = await nonebot.get_bot().get_group_file_url(
            group_id=Transmitter.GROUP,
            file_id=music,
            busid=0
        )
        img_url = await nonebot.get_bot().get_group_file_url(
            group_id=627629957,
            file_id=picture,
            busid=0
        )
        await self.send(
            MessageSegment(
                "music",
                {
                    "type": "custom",
                    "url": 'www.baidu.com',
                    'audio': audio_url['url'],
                    "title": title,
                    "image": img_url['url']
                }
            )
        )

    @staticmethod
    async def get_file_by_name(name: str) -> str:
        file_data = await nonebot.get_bot().get_group_root_files(
            group_id=Transmitter.GROUP
        )
        files = file_data["files"]
        for file_info in files:
            if file_info["file_name"] == name:
                return file_info["file_id"]
        raise FileNotFoundError(f"文件 '{name}' 不存在于群文件中")
