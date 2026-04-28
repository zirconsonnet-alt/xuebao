import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import registry
from src.services.base import BaseService, service_action
from src.support.core import Services


def _make_group_event(message_text: str, *, user_id: int = 456, group_id: int = 123456) -> GroupMessageEvent:
    payload = {
        "time": 1710000000,
        "self_id": 654321,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "user_id": user_id,
        "message_id": 1001,
        "group_id": group_id,
        "raw_message": message_text,
        "font": 0,
        "message": [{"type": "text", "data": {"text": message_text}}],
        "sender": {
            "user_id": user_id,
            "nickname": "测试用户",
            "card": "测试群名片",
            "role": "member",
        },
    }
    if hasattr(GroupMessageEvent, "model_validate"):
        return GroupMessageEvent.model_validate(payload)
    return GroupMessageEvent.parse_obj(payload)


class DummyAssistant:
    def __init__(self):
        self.msg_list = []

    def add_message(self, record):
        self.msg_list.append(record)


class DummyManager:
    def __init__(self, assistant):
        self.assistant = assistant

    def get_group_server(self, group_id: int):
        return self.assistant


class DummyGroup:
    group_id = 123456
    self_id = 654321

    async def send_msg(self, message):
        return {"message_id": 1}

    async def get_group_member_info(self, user_id: int):
        return {"role": "member", "user_id": user_id}


class DummyTarotCommandService(BaseService):
    service_type = Services.Tarot
    default_config = {"enabled": True}

    @service_action(
        cmd="塔罗牌",
        record_ai_context=True,
        ai_context_label="抽一张塔罗牌",
    )
    async def draw_tarot(self, event: GroupMessageEvent):
        return {"success": True}

    @service_action(
        cmd="塔罗牌解读",
        need_arg=True,
        record_ai_context=True,
        ai_context_label="解读指定塔罗牌",
        ai_context_include_arg=True,
    )
    async def tarot_reading(self, event: GroupMessageEvent, arg: Message):
        return {"success": True, "arg": arg.extract_plain_text()}


def test_run_service_records_explicit_command_into_ai_context(monkeypatch) -> None:
    assistant = DummyAssistant()
    service = DummyTarotCommandService.__new__(DummyTarotCommandService)
    service.group = DummyGroup()
    service._config = {"enabled": True}

    import src.services._ai.assistant as assistant_module

    monkeypatch.setattr(assistant_module, "get_ai_assistant_manager", lambda: DummyManager(assistant))
    monkeypatch.setattr(registry.service_manager, "get_service", lambda group_id, service_type: asyncio.sleep(0, result=service))

    event = _make_group_event("/塔罗牌")
    asyncio.run(
        registry.run_service(
            group_id=event.group_id,
            service_enum=Services.Tarot,
            action="draw_tarot",
            event=event,
        )
    )

    assert len(assistant.msg_list) == 1
    assert assistant.msg_list[0]["role"] == "user"
    assert "通过指令触发了塔罗牌服务：抽一张塔罗牌" in assistant.msg_list[0]["content"]
    assert "测试群名片" in assistant.msg_list[0]["content"]


def test_run_service_skips_ai_context_record_for_service_menu_navigation(monkeypatch) -> None:
    assistant = DummyAssistant()
    service = DummyTarotCommandService.__new__(DummyTarotCommandService)
    service.group = DummyGroup()
    service._config = {"enabled": True}

    import src.services._ai.assistant as assistant_module

    monkeypatch.setattr(assistant_module, "get_ai_assistant_manager", lambda: DummyManager(assistant))
    monkeypatch.setattr(registry.service_manager, "get_service", lambda group_id, service_type: asyncio.sleep(0, result=service))

    event = _make_group_event("/服务")
    asyncio.run(
        registry.run_service(
            group_id=event.group_id,
            service_enum=Services.Tarot,
            action="draw_tarot",
            event=event,
        )
    )

    assert assistant.msg_list == []


def test_run_service_records_command_arg_when_enabled(monkeypatch) -> None:
    assistant = DummyAssistant()
    service = DummyTarotCommandService.__new__(DummyTarotCommandService)
    service.group = DummyGroup()
    service._config = {"enabled": True}

    import src.services._ai.assistant as assistant_module

    monkeypatch.setattr(assistant_module, "get_ai_assistant_manager", lambda: DummyManager(assistant))
    monkeypatch.setattr(registry.service_manager, "get_service", lambda group_id, service_type: asyncio.sleep(0, result=service))

    event = _make_group_event("/塔罗牌解读 愚者")
    asyncio.run(
        registry.run_service(
            group_id=event.group_id,
            service_enum=Services.Tarot,
            action="tarot_reading",
            event=event,
            arg=Message("愚者"),
        )
    )

    assert len(assistant.msg_list) == 1
    assert "通过指令触发了塔罗牌服务：解读指定塔罗牌" in assistant.msg_list[0]["content"]
    assert "参数：愚者" in assistant.msg_list[0]["content"]
