from typing import TYPE_CHECKING

from cookit.loguru import warning_suppress
from httpx import AsyncClient
from nonebot.matcher import current_bot, current_event
from nonebot_plugin_alconna.builtins.uniseg.music_share import (
    MusicShare,
    MusicShareKind,
)
from nonebot_plugin_alconna.uniseg import UniMessage

from ...config import config

if TYPE_CHECKING:
    from ...data_source import BaseSong, SongInfo


async def _send_onebot_music_card(info: "SongInfo"):
    bot = current_bot.get()
    event = current_event.get()
    adapter = getattr(bot, "adapter", None)
    adapter_name = adapter.get_name() if adapter and hasattr(adapter, "get_name") else ""
    if adapter_name != "OneBot V11":
        return None

    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    message = Message(
        MessageSegment(
            "music",
            {
                "type": "custom",
                "url": info.url,
                "audio": info.playable_url,
                "title": info.display_name,
                "image": info.cover_url,
                "singer": info.display_artists,
            },
        )
    )
    return await bot.send(event, message)


async def sign_music_card(info: "SongInfo") -> str:
    assert config.card_sign_url
    async with AsyncClient(
        follow_redirects=True,
        timeout=config.card_sign_timeout,
    ) as cli:
        body = {
            "type": "custom",
            "url": info.url,
            "audio": info.playable_url,
            "title": info.display_name,
            "image": info.cover_url,
            "singer": info.display_artists,
        }
        return (await cli.post(config.card_sign_url, json=body)).raise_for_status().text


async def send_song_card_msg(song: "BaseSong"):
    info = await song.get_info()
    with warning_suppress(f"Failed to send OneBot V11 music card for song {song}"):
        receipt = await _send_onebot_music_card(info)
        if receipt is not None:
            return receipt
    if config.card_sign_url:
        with warning_suppress(
            f"Failed to send signed card for song {song}, fallback to MusicShare seg",
        ):
            return await UniMessage.hyper("json", await sign_music_card(info)).send(
                fallback=False,
            )
    return await UniMessage(
        MusicShare(
            kind=MusicShareKind.NeteaseCloudMusic,
            title=info.display_name,
            content=info.display_artists,
            url=info.url,
            thumbnail=info.cover_url,
            audio=info.playable_url,
            summary=info.display_artists,
        ),
    ).send(fallback=False)
