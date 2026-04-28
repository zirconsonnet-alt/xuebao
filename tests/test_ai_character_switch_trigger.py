import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import Message, MessageSegment

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.services._ai.ai_service_handlers as handler_module
from src.services._ai.ai_service_handlers import AIServiceHandlerMixin


class DummyAssistant:
    def __init__(self, current_name: str, names: list[str]):
        self.black_list = set()
        self.nickname = None
        self.character = SimpleNamespace(name=current_name, on_switch_msg=f"{current_name}已上线")
        self._names = list(names)
        self.switch_calls: list[str] = []
        self.sent_messages: list[str] = []
        self.reply_calls = 0
        self.buffer_calls = 0
        self.buffer_payloads: list[dict] = []

    def get_character_names(self) -> list[str]:
        return list(self._names)

    async def switch_character(self, name: str):
        self.switch_calls.append(name)

    async def send(self, message: str):
        self.sent_messages.append(message)

    async def reply(self, event, service_config):
        self.reply_calls += 1

    def buffer_chat_message(self, *args, **kwargs):
        self.buffer_calls += 1
        self.buffer_payloads.append({"args": args, "kwargs": kwargs})


class DummyService(AIServiceHandlerMixin):
    def __init__(self, assistant: DummyAssistant):
        self.enabled = True
        self.group_mode = True
        self.voice_enable = False
        self.music_enable = False
        self.tools_enable = True
        self.rate_limit_enable = True
        self.rate_limit_per_hour = 10
        self.thinking_enable = False
        self._assistant = assistant

    def get_ai_assistant(self, event):
        return self._assistant


class DummyEvent:
    def __init__(self, message_text: str = "", message=None):
        self.user_id = 123456
        self.group_id = 654321
        self.reply = None
        self._message = message if message is not None else Message(message_text)

    def get_message(self):
        return self._message

    def is_tome(self) -> bool:
        return False


def _patch_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        handler_module.nonebot,
        "get_driver",
        lambda: SimpleNamespace(config=SimpleNamespace(command_start={"/"})),
    )
    monkeypatch.setattr(handler_module.nonebot, "get_bot", lambda: object())
    monkeypatch.setattr(handler_module, "is_player_in_werewolf_game", lambda _user_id: False)


def test_other_character_name_can_switch_before_response_gate(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    assistant = DummyAssistant(current_name="宝宝", names=["雪豹", "宝宝"])
    service = DummyService(assistant)
    event = DummyEvent("雪豹")

    asyncio.run(service.handle_ai_message(event))

    assert assistant.switch_calls == ["雪豹"]
    assert assistant.sent_messages == []
    assert assistant.reply_calls == 0
    assert assistant.buffer_calls == 0


def test_current_character_name_still_sends_switch_message_without_redundant_switch(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    assistant = DummyAssistant(current_name="雪豹", names=["雪豹", "宝宝"])
    service = DummyService(assistant)
    event = DummyEvent("雪豹")

    asyncio.run(service.handle_ai_message(event))

    assert assistant.switch_calls == []
    assert assistant.sent_messages == ["雪豹已上线"]
    assert assistant.reply_calls == 0
    assert assistant.buffer_calls == 0


def test_buffered_group_history_does_not_register_images_from_unaddressed_messages(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    assistant = DummyAssistant(current_name="雪豹", names=["雪豹", "宝宝"])
    service = DummyService(assistant)
    event = DummyEvent(
        message=Message(
            [
                MessageSegment.text("大家看这个"),
                MessageSegment.image("https://example.com/sticker.png"),
            ]
        )
    )

    asyncio.run(service.handle_ai_message(event))

    assert assistant.switch_calls == []
    assert assistant.reply_calls == 0
    assert assistant.buffer_calls == 1
    assert assistant.buffer_payloads[0]["args"][2] == "大家看这个"
    assert assistant.buffer_payloads[0]["args"][3] is None
