import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_python(code: str):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return SimpleNamespace(
        returncode=result.returncode,
        stdout=_decode_output(result.stdout),
        stderr=_decode_output(result.stderr),
    )


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    preferred_encodings = ["utf-8", "gbk", sys.getdefaultencoding()]
    for encoding in preferred_encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def test_multincm_song_card_uses_onebot_music_segment():
    result = _run_python(
        """
        import asyncio
        import importlib
        import json
        from types import SimpleNamespace
        from nonebot.matcher import current_bot, current_event

        import bot

        song_card = importlib.import_module('src.vendors.nonebot_plugin_multincm.interaction.message.song_card')

        captured = {}

        class DummyBot:
            adapter = SimpleNamespace(get_name=lambda: 'OneBot V11')

            async def send(self, event, message):
                captured['message'] = message
                return {'message_id': 1}

        class DummySong:
            async def get_info(self):
                return SimpleNamespace(
                    url='https://music.163.com/song?id=123',
                    playable_url='https://example.com/audio.mp3',
                    display_name='Lemon',
                    cover_url='https://example.com/cover.jpg',
                    display_artists='米津玄師',
                )

        bot_token = current_bot.set(DummyBot())
        event_token = current_event.set(SimpleNamespace(group_id=123, user_id=456))
        try:
            asyncio.run(song_card.send_song_card_msg(DummySong()))
        finally:
            current_bot.reset(bot_token)
            current_event.reset(event_token)

        segment = captured['message'][0]
        print(json.dumps({'type': segment.type, 'data': segment.data}, ensure_ascii=False))
        """
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "type": "music",
        "data": {
            "type": "custom",
            "url": "https://music.163.com/song?id=123",
            "audio": "https://example.com/audio.mp3",
            "title": "Lemon",
            "image": "https://example.com/cover.jpg",
            "singer": "米津玄師",
        },
    }


def test_multincm_song_card_failure_falls_back_to_visible_message():
    result = _run_python(
        """
        import asyncio
        import importlib

        import bot

        common = importlib.import_module('src.vendors.nonebot_plugin_multincm.interaction.message.common')

        common.config.send_as_card = True
        common.config.send_media = False

        state = {'sent': False}

        async def broken_send_song_card_msg(song):
            raise RuntimeError('card failed')

        class DummyVisibleMessage:
            async def send(self):
                state['sent'] = True
                return True

        async def fake_construct_info_msg(song, tip_command=True):
            return DummyVisibleMessage()

        common.send_song_card_msg = broken_send_song_card_msg
        common.construct_info_msg = fake_construct_info_msg

        class DummySong:
            pass

        asyncio.run(common._send_song_without_cache(DummySong()))
        print(state['sent'])
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "True"
