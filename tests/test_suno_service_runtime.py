import asyncio
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_suno_generate_music_tool_uploads_group_file_result(tmp_path) -> None:
    import bot  # noqa: F401

    suno_module = importlib.import_module("src.services.suno")
    service_cls = suno_module.SunoService

    captured = {"messages": [], "uploads": [], "steps": []}

    async def _send_msg(message):
        captured["messages"].append(message)

    service = service_cls.__new__(service_cls)
    service.group = SimpleNamespace(send_msg=_send_msg)
    service._config = {
        "enabled": True,
        "base_url": "http://127.0.0.1:3000",
        "request_timeout_seconds": 30,
        "poll_interval_seconds": 1,
        "max_wait_seconds": 10,
    }

    async def _fake_download_ready_audio_file(item):
        file_path = tmp_path / "night_piano.mp3"
        file_path.write_bytes(b"fake-mp3")
        return file_path, "夜色钢琴曲.mp3"

    def _fake_write_mp3_artist_metadata(file_path, item):
        captured["steps"].append(("metadata", str(file_path), item["title"]))

    async def _fake_upload_generated_audio_file(file_path, file_name):
        captured["steps"].append(("upload", str(file_path), file_name))
        captured["uploads"].append((str(file_path), file_name))

    service._download_ready_audio_file = _fake_download_ready_audio_file
    service._write_mp3_artist_metadata = _fake_write_mp3_artist_metadata
    service._upload_generated_audio_file = _fake_upload_generated_audio_file

    async def _fake_generate_music_request(**kwargs):
        items = [
            {
                "id": "clip-1",
                "title": "夜色钢琴曲",
                "audio_url": "https://example.com/clip-1.mp3",
                "video_url": "https://example.com/clip-1.mp4",
                "image_url": "https://example.com/cover.jpg",
                "status": "complete",
                "model_name": "chirp-v3-5",
                "tags": "piano",
                "duration": 180,
            },
            {
                "id": "clip-2",
                "title": "夜色钢琴曲（备选）",
                "audio_url": "https://example.com/clip-2.mp3",
                "status": "complete",
                "model_name": "chirp-v3-5",
                "duration": 180,
            },
        ]
        upload_result = await service._send_generation_result(items)
        return {
            "success": True,
            "message": "已生成音乐并上传到群文件",
            "data": {"items": items, "ready": True, **upload_result},
        }

    service._generate_music_request = _fake_generate_music_request

    result = asyncio.run(
        service.generate_music_tool(
            user_id=456,
            group_id=123,
            prompt="一首带有夜色感的钢琴纯音乐",
            make_instrumental=True,
        )
    )

    assert result["success"] is True
    assert result["data"]["uploaded"] is True
    assert result["data"]["file_name"] == "夜色钢琴曲.mp3"
    assert captured["messages"], "应当向群里发送生成结果"
    assert "已上传到群文件：夜色钢琴曲.mp3" in str(captured["messages"][0])
    assert captured["uploads"] == [(str(tmp_path / "night_piano.mp3"), "夜色钢琴曲.mp3")]
    assert captured["steps"] == [
        ("metadata", str(tmp_path / "night_piano.mp3"), "夜色钢琴曲"),
        ("upload", str(tmp_path / "night_piano.mp3"), "夜色钢琴曲.mp3"),
    ]


def test_suno_write_mp3_artist_metadata_sets_xuebao(tmp_path) -> None:
    import bot  # noqa: F401
    from mutagen.id3 import ID3

    suno_module = importlib.import_module("src.services.suno")
    service_cls = suno_module.SunoService

    service = service_cls.__new__(service_cls)
    file_path = tmp_path / "night_piano.mp3"
    file_path.write_bytes(b"fake-mp3")

    service._write_mp3_artist_metadata(
        file_path,
        {
            "id": "clip-1",
            "title": "夜色钢琴曲",
            "audio_url": "https://example.com/clip-1.mp3",
            "status": "complete",
        },
    )

    tags = ID3(file_path)
    assert tags.getall("TPE1")[0].text == ["雪豹"]
    assert tags.getall("TPE2")[0].text == ["雪豹"]
    assert tags.getall("TIT2")[0].text == ["夜色钢琴曲"]


def test_suno_send_generation_result_keeps_streaming_items_as_text_only() -> None:
    import bot  # noqa: F401

    suno_module = importlib.import_module("src.services.suno")
    service_cls = suno_module.SunoService

    captured = {"messages": []}

    async def _send_msg(message):
        captured["messages"].append(message)

    service = service_cls.__new__(service_cls)
    service.group = SimpleNamespace(send_msg=_send_msg)
    service._config = {
        "enabled": True,
        "base_url": "http://127.0.0.1:3000",
        "request_timeout_seconds": 30,
        "poll_interval_seconds": 1,
        "max_wait_seconds": 10,
    }

    upload_result = asyncio.run(
        service._send_generation_result(
            [
                {
                    "id": "clip-1",
                    "title": "夜色钢琴曲",
                    "audio_url": "https://example.com/preview.mp3",
                    "status": "streaming",
                    "model_name": "chirp-v3-5",
                }
            ]
        )
    )

    assert upload_result["uploaded"] is False
    assert captured["messages"]
    text = str(captured["messages"][0])
    assert "仍在生成中" in text
    assert "已上传到群文件" not in text


def test_suno_generate_music_request_polls_until_finished() -> None:
    import bot  # noqa: F401

    suno_module = importlib.import_module("src.services.suno")
    service_cls = suno_module.SunoService

    service = service_cls.__new__(service_cls)
    service.group = SimpleNamespace(send_msg=None)
    service._config = {
        "enabled": True,
        "base_url": "http://127.0.0.1:3000",
        "request_timeout_seconds": 30,
        "poll_interval_seconds": 1,
        "max_wait_seconds": 10,
    }

    responses = [
        [
            {"id": "clip-1", "status": "streaming", "title": "测试歌曲"},
            {"id": "clip-2", "status": "submitted", "title": "测试歌曲 2"},
        ],
        [
            {
                "id": "clip-1",
                "status": "complete",
                "title": "测试歌曲",
                "audio_url": "https://example.com/clip-1.mp3",
                "duration": 180,
            },
            {
                "id": "clip-2",
                "status": "streaming",
                "title": "测试歌曲 2",
                "audio_url": "https://example.com/clip-2-preview.mp3",
            },
        ],
    ]

    async def _fake_request_json(method, path, *, payload=None, params=None):
        if method == "POST" and path == "/api/generate":
            return [
                {"id": "clip-1", "status": "submitted", "title": "测试歌曲"},
                {"id": "clip-2", "status": "submitted", "title": "测试歌曲 2"},
            ]
        if method == "GET" and path == "/api/get":
            return responses.pop(0)
        raise AssertionError(f"unexpected request: {method} {path}")

    service._request_json = _fake_request_json
    original_sleep = suno_module.asyncio.sleep
    suno_module.asyncio.sleep = lambda *_args, **_kwargs: original_sleep(0)
    try:
        result = asyncio.run(
            service._generate_music_request(
                prompt="来一首测试歌曲",
                make_instrumental=False,
                send_output=False,
            )
        )
    finally:
        suno_module.asyncio.sleep = original_sleep

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["clip_ids"] == ["clip-1", "clip-2"]
    assert result["data"]["items"][0]["audio_url"] == "https://example.com/clip-1.mp3"


def test_suno_get_limit_request_formats_payload() -> None:
    import bot  # noqa: F401

    suno_module = importlib.import_module("src.services.suno")
    service_cls = suno_module.SunoService

    captured = {"messages": []}

    async def _send_msg(message):
        captured["messages"].append(message)

    service = service_cls.__new__(service_cls)
    service.group = SimpleNamespace(send_msg=_send_msg)
    service._config = {
        "enabled": True,
        "base_url": "http://127.0.0.1:3000",
        "request_timeout_seconds": 30,
        "poll_interval_seconds": 1,
        "max_wait_seconds": 10,
    }

    async def _fake_request_json(method, path, *, payload=None, params=None):
        assert method == "GET"
        assert path == "/api/get_limit"
        return {
            "credits_left": 42,
            "period": "day",
            "monthly_limit": 50,
            "monthly_usage": 8,
        }

    service._request_json = _fake_request_json

    result = asyncio.run(service._get_limit_request(send_output=True))

    assert result["success"] is True
    assert result["data"]["credits_left"] == 42
    assert captured["messages"]
    assert "Suno 额度信息" in str(captured["messages"][0])
    assert "剩余额度：42" in str(captured["messages"][0])
