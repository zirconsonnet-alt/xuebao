import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_bison_delivery_selects_latest_music_card_video_for_bilibili() -> None:
    import src.services.bison as bison_module

    text_post = SimpleNamespace(timestamp=50, title="图文动态")
    older_post = SimpleNamespace(
        timestamp=100,
        title="旧视频",
        _bison_music_card_meta={
            "url": "https://www.bilibili.com/video/BV1older0000",
            "cover": "https://example.com/older.jpg",
            "title": "旧视频",
            "singer": "测试UP",
        },
    )
    newer_post = SimpleNamespace(
        timestamp=200,
        title="新视频",
        _bison_music_card_meta={
            "url": "https://www.bilibili.com/video/BV1newer0000",
            "cover": "https://example.com/newer.jpg",
            "title": "新视频",
            "singer": "测试UP",
        },
    )
    selected_posts = bison_module._select_bison_posts_for_delivery(
        "bilibili",
        [text_post, older_post, newer_post],
    )

    assert selected_posts == [newer_post]
    assert bison_module._select_bison_posts_for_delivery(
        "weibo",
        [text_post, older_post, newer_post],
    ) == [text_post, older_post, newer_post]


def test_bison_delivery_skips_non_music_card_bilibili_posts() -> None:
    import src.services.bison as bison_module

    text_post = SimpleNamespace(timestamp=100, title="图文动态")
    repost_post = SimpleNamespace(timestamp=200, title="转发动态")

    assert bison_module._select_bison_posts_for_delivery(
        "bilibili",
        [text_post, repost_post],
    ) == []


def test_bison_music_card_audio_url_uses_tts_fallback_when_original_missing(tmp_path: Path, monkeypatch) -> None:
    import src.services.bison as bison_module

    fallback_audio_path = tmp_path / "fallback.mp3"
    fallback_audio_path.write_bytes(b"tts")
    upload_calls = []

    async def fake_ensure_original_audio(video_url: str):
        return None, "bvid_demo_p0"

    async def fake_ensure_fallback_audio(cache_key: str, title: str):
        assert cache_key == "bvid_demo_p0"
        assert title == "测试视频"
        return fallback_audio_path, "tts_bvid_demo_p0"

    async def fake_upload_audio_url(target_group_id: int, audio_path: Path, cache_key: str):
        upload_calls.append((target_group_id, audio_path, cache_key))
        return f"https://example.com/{cache_key}.mp3"

    monkeypatch.setattr(bison_module, "_ensure_bison_music_audio_file", fake_ensure_original_audio)
    monkeypatch.setattr(bison_module, "_ensure_bison_music_fallback_audio_file", fake_ensure_fallback_audio)
    monkeypatch.setattr(bison_module, "_upload_bison_music_card_audio_url", fake_upload_audio_url)

    audio_url = asyncio.run(
        bison_module._resolve_bison_music_card_audio_url(
            123,
            {
                "url": "https://www.bilibili.com/video/BV1demo0000",
                "title": "测试视频",
                "cover": "https://example.com/cover.jpg",
                "singer": "测试UP",
            },
        )
    )

    assert audio_url == "https://example.com/tts_bvid_demo_p0.mp3"
    assert upload_calls == [(123, fallback_audio_path, "tts_bvid_demo_p0")]


def test_bison_music_fallback_audio_file_generates_local_speech(tmp_path: Path, monkeypatch) -> None:
    import src.services.bison as bison_module
    import src.support.ai as ai_module

    calls = {}

    class FakeLocalSpeechGenerator:
        def __init__(self):
            self.voice_path = None

        async def gen_speech(self, text: str, voice_id: str, music_enable: bool = False):
            calls["text"] = text
            calls["voice_id"] = voice_id
            calls["music_enable"] = music_enable
            calls["voice_path"] = self.voice_path
            output_path = Path(self.voice_path) / "generated.mp3"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"tts")
            return str(output_path)

    monkeypatch.setattr(ai_module, "LocalSpeechGenerator", FakeLocalSpeechGenerator)
    monkeypatch.setattr(bison_module, "BISON_MUSIC_CARD_AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(bison_module, "BISON_MUSIC_CARD_TEMP_DIR", tmp_path / "temp")
    bison_module._BISON_AUDIO_FILE_LOCKS.clear()

    audio_path, cache_key = asyncio.run(
        bison_module._ensure_bison_music_fallback_audio_file("bvid_demo_p0", "很长的测试视频标题")
    )

    assert cache_key == "tts_bvid_demo_p0"
    assert audio_path == tmp_path / "audio" / "tts_bvid_demo_p0.mp3"
    assert audio_path.read_bytes() == b"tts"
    assert calls["voice_id"] == bison_module.BISON_MUSIC_CARD_FALLBACK_VOICE_ID
    assert calls["music_enable"] is False
    assert calls["voice_path"] == tmp_path / "temp"
    assert "点开卡片" in calls["text"]


def test_bison_bilibili_video_without_music_meta_skips_default_message() -> None:
    import src.services.bison as bison_module

    class DummyVideoPost:
        platform = SimpleNamespace(platform_name="bilibili")
        url = "https://www.bilibili.com/video/BV1demo0000"

        async def generate_messages(self):
            raise AssertionError("B站视频不应回退普通消息")

    messages = asyncio.run(
        bison_module._build_bison_messages_for_target(
            DummyVideoPost(),
            SimpleNamespace(group_id=123),
        )
    )

    assert messages == []
