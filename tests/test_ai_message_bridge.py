import asyncio
from io import BytesIO
from pathlib import Path
import sys

from nonebot.adapters.onebot.v11 import Message

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.group_state import GroupStateMixin
from src.services._ai.message_bridge import record_group_media_output, sync_recent_group_bot_outputs
from src.services._vision.describe_api import VisionDescribeApiMixin
from src.support.group import NoneBotGroupGateway


class DummyGroupState(GroupStateMixin):
    CHAT_BUFFER_MAX_MESSAGES = 10
    CHAT_BUFFER_MAX_LENGTH = 1500

    def __init__(self, cache_dir: Path):
        self._config = {"group_mode": True}
        self.msg_list = []
        self._chat_buffer = []
        self._image_registry = {}
        self._image_counter = 0
        self._video_registry = {}
        self._video_counter = 0
        self._media_cache_dir = cache_dir
        self._media_cache_dir.mkdir(parents=True, exist_ok=True)
        self._media_cache_files = []
        self._recorded_assistant_message_ids = set()
        self._recorded_assistant_message_order = []
        self._pending_media_description_tasks = {}
        self._pending_media_description_meta = {}

    def _save_config(self):
        return None

    def add_message(self, record):
        self.msg_list.append(record)


class DummyVisionDescribeApi(VisionDescribeApiMixin):
    pass


def test_record_assistant_output_caches_local_video_and_deduplicates_message_id(tmp_path) -> None:
    assistant = DummyGroupState(tmp_path / "media_cache")
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video data")

    recorded = assistant.record_assistant_output(
        "刚刚给你发了一个视频",
        video_urls=[str(source_video)],
        message_id=101,
    )

    assert recorded is True
    assert assistant.msg_list[-1]["role"] == "assistant"
    assert "[视频:vid_001]" in assistant.msg_list[-1]["content"]
    cached_url = assistant.get_video_url("vid_001")
    assert cached_url is not None
    assert cached_url.startswith("file://")

    cached_path = Path(cached_url[8:] if cached_url.startswith("file:///") else cached_url[7:])
    assert cached_path.exists()
    assert cached_path != source_video

    duplicate = assistant.record_assistant_output(
        "重复记录",
        video_urls=[str(source_video)],
        message_id=101,
    )
    assert duplicate is False
    assert len(assistant.msg_list) == 1


def test_sync_recent_group_bot_outputs_imports_video_history_once(monkeypatch, tmp_path) -> None:
    assistant = DummyGroupState(tmp_path / "media_cache")
    source_video = tmp_path / "history.mp4"
    source_video.write_bytes(b"history video")

    history_payload = {
        "messages": [
            {
                "message_id": 3001,
                "time": 1,
                "sender": {"user_id": 999001},
                "message": [
                    {
                        "type": "video",
                        "data": {"file": str(source_video)},
                    }
                ],
            },
            {
                "message_id": 3002,
                "time": 2,
                "sender": {"user_id": 123456},
                "message": "这条不是机器人发的",
            },
        ]
    }

    class DummyManager:
        def get_group_server(self, group_id: int):
            assert group_id == 766072328
            return assistant

    class DummyGroup:
        async def get_message_history(self, count: int = 20):
            assert count == 12
            return history_payload

    import src.services._ai.assistant as assistant_module
    import src.support.group as group_module

    monkeypatch.setattr(assistant_module, "get_ai_assistant_manager", lambda: DummyManager())
    monkeypatch.setattr(
        group_module.GroupManager,
        "get_group",
        classmethod(lambda cls, group_id: DummyGroup()),
    )

    recorded_count = asyncio.run(sync_recent_group_bot_outputs(766072328, 999001))
    assert recorded_count == 1
    assert len(assistant.msg_list) == 1
    assert "[视频:vid_001]" in assistant.msg_list[0]["content"]

    recorded_again = asyncio.run(sync_recent_group_bot_outputs(766072328, 999001))
    assert recorded_again == 0
    assert len(assistant.msg_list) == 1


def test_record_group_media_output_caches_image_bytes_and_uses_receipt_message_id(tmp_path) -> None:
    assistant = DummyGroupState(tmp_path / "media_cache")

    class DummyReceipt:
        def __init__(self, msg_ids):
            self.msg_ids = list(msg_ids)

    recorded = record_group_media_output(
        123456,
        text="已发送词云图片",
        image_bytes_list=[b"fake-image"],
        message_result=DummyReceipt([8080]),
        assistant=assistant,
    )

    assert recorded is True
    assert len(assistant.msg_list) == 1
    assert assistant.msg_list[0]["role"] == "assistant"
    assert "[图片:img_001]" in assistant.msg_list[0]["content"]
    cached_url = assistant.get_image_url("img_001")
    assert cached_url is not None
    assert cached_url.startswith("file://")

    recorded_again = record_group_media_output(
        123456,
        text="已发送词云图片",
        image_bytes_list=[b"fake-image"],
        message_result=DummyReceipt([8080]),
        assistant=assistant,
    )
    assert recorded_again is False
    assert len(assistant.msg_list) == 1


def test_record_group_media_output_accepts_bytesio_image_payload(tmp_path) -> None:
    assistant = DummyGroupState(tmp_path / "media_cache")

    recorded = record_group_media_output(
        123456,
        text="已发送塔罗牌图片",
        image_bytes_list=[BytesIO(b"fake-tarot-image")],
        message_id=9090,
        assistant=assistant,
    )

    assert recorded is True
    assert len(assistant.msg_list) == 1
    assert "[图片:img_001]" in assistant.msg_list[0]["content"]
    cached_url = assistant.get_image_url("img_001")
    assert cached_url is not None
    cached_path = Path(cached_url[8:] if cached_url.startswith("file:///") else cached_url[7:])
    assert cached_path.read_bytes() == b"fake-tarot-image"


def test_nonebot_group_gateway_send_msg_bridges_ai_output(monkeypatch) -> None:
    captured = {}

    class DummyBot:
        self_id = 346241182

        async def send_group_msg(self, *, group_id: int, message):
            captured["sent_group_id"] = group_id
            captured["sent_message"] = str(message)
            return {"message_id": 4321}

    import nonebot
    import src.services._ai.message_bridge as message_bridge_module

    monkeypatch.setattr(nonebot, "get_bots", lambda: {})
    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())
    monkeypatch.setattr(
        message_bridge_module,
        "record_group_output",
        lambda group_id, message, **kwargs: captured.update(
            {
                "bridge_group_id": group_id,
                "bridge_message": str(message),
                "bridge_message_id": kwargs.get("message_id"),
            }
        ),
    )

    asyncio.run(NoneBotGroupGateway().send_msg(205177952, Message("测试桥接消息")))

    assert captured["sent_group_id"] == 205177952
    assert captured["bridge_group_id"] == 205177952
    assert captured["bridge_message"] == "测试桥接消息"
    assert captured["bridge_message_id"] == 4321


def test_nonebot_group_gateway_prefers_matching_self_id(monkeypatch) -> None:
    sent = {}

    class DummyBot:
        def __init__(self, self_id: int):
            self.self_id = self_id

        async def send_group_msg(self, *, group_id: int, message):
            sent["self_id"] = self.self_id
            sent["group_id"] = group_id
            sent["message"] = str(message)
            return {"message_id": 1}

    import nonebot

    monkeypatch.setattr(
        nonebot,
        "get_bots",
        lambda: {
            "10001": DummyBot(10001),
            "20002": DummyBot(20002),
        },
    )

    asyncio.run(
        NoneBotGroupGateway(preferred_self_id=20002).send_msg(
            205177952,
            Message("多 bot 路由测试"),
        )
    )

    assert sent["self_id"] == 20002
    assert sent["group_id"] == 205177952
    assert sent["message"] == "多 bot 路由测试"


def test_describe_video_api_uses_local_video_fallback_for_local_path(tmp_path) -> None:
    service = DummyVisionDescribeApi()
    source_video = tmp_path / "local.mp4"
    source_video.write_bytes(b"local video")
    captured = {}

    async def _fake_local_video_api(video_path: Path, prompt: str = None) -> str:
        captured["video_path"] = video_path
        captured["prompt"] = prompt
        return "本地视频描述"

    service._describe_local_video_api = _fake_local_video_api

    result = asyncio.run(service._describe_video_api(str(source_video), "请描述视频"))

    assert result == "本地视频描述"
    assert captured["video_path"] == source_video
    assert captured["prompt"] == "请描述视频"
