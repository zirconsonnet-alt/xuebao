import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import nonebot

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.ai_service_actions import AIServiceActionMixin


class DummyAssistant:
    def __init__(self):
        self.server_type = "group"
        self.server_id = 123456
        self.character = SimpleNamespace(name="雪豹")
        self.msg_list = [
            {"role": "user", "content": "请帮我下载 B 站视频"},
            {"role": "assistant", "content": "已经给你发了视频文件 [视频:vid_001]"},
            {"role": "user", "content": "这个视频内容是什么"},
        ]
        self._image_registry = {"img_001": "file:///tmp/demo.png"}
        self._video_registry = {"vid_001": "file:///tmp/demo.mp4"}
        self._pending_media_description_meta = {
            ("video", "file:///tmp/demo.mp4", "请描述视频"): {
                "media_type": "video",
                "media_id": "vid_001",
                "prompt": "请描述视频",
            }
        }
        self.black_list = {222, 111}
        self.recorded_message_ids = []

    def _remember_recorded_assistant_message_id(self, message_id):
        self.recorded_message_ids.append(int(message_id))


class DummyGroup:
    def __init__(self):
        self.sent = []

    async def send_msg(self, message):
        self.sent.append(str(message))
        return {"message_id": len(self.sent)}


class DummyService(AIServiceActionMixin):
    def __init__(self, assistant):
        self._assistant = assistant
        self.group = DummyGroup()
        self.enabled = True
        self.random_reply_enabled = True
        self.keyword_reply_enabled = True
        self.voice_enable = True
        self.music_enable = False
        self.tools_enable = True
        self.rate_limit_enable = True
        self.rate_limit_per_hour = 3
        self.thinking_enable = False
        self.group_mode = True

    def get_ai_assistant(self, event):
        return self._assistant


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_group_msg(self, *, group_id: int, message):
        self.sent.append({"group_id": group_id, "message": str(message)})
        return {"message_id": 9001}


def test_ai_context_action_prints_snapshot_and_sends_non_bridged_summary(monkeypatch, capsys) -> None:
    bot = DummyBot()
    assistant = DummyAssistant()
    service = DummyService(assistant)
    event = SimpleNamespace(group_id=123456)

    monkeypatch.setattr(nonebot, "get_bot", lambda: bot)

    asyncio.run(service.print_message_log(event))

    captured = capsys.readouterr().out
    assert "[AIService] context_snapshot group_id=123456" in captured
    assert '"msg_count": 3' in captured
    assert '"image_count": 1' in captured
    assert '"video_count": 1' in captured
    assert '"pending_media_task_count": 1' in captured

    assert len(bot.sent) == 1
    assert bot.sent[0]["group_id"] == 123456
    assert "AI上下文已打印到后台。" in bot.sent[0]["message"]
    assert "历史消息：3 条" in bot.sent[0]["message"]
    assert "图片登记：1 个" in bot.sent[0]["message"]
    assert "视频登记：1 个" in bot.sent[0]["message"]
    assert "待描述任务：1 个" in bot.sent[0]["message"]
    assert "- assistant: 已经给你发了视频文件 [视频:vid_001]" in bot.sent[0]["message"]

    assert service.group.sent == []
    assert assistant.recorded_message_ids == [9001]
