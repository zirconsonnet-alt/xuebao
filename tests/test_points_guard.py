import asyncio
from pathlib import Path
import sys

from nonebot.adapters.onebot.v11 import GroupMessageEvent

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import registry
from src.services.base import BaseService, service_action
from src.support.core import Services, ToolDefinition, ToolRegistry


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


class DummyPointsDB:
    def __init__(self, *, allowed: bool, balance: int):
        self.allowed = allowed
        self.balance = balance
        self.calls = []

    def apply_points_cost(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.allowed, self.balance, False


class DummyGroup:
    group_id = 123456
    self_id = 654321

    def __init__(self, db: DummyPointsDB):
        self.db = db
        self.sent = []

    async def send_msg(self, message):
        self.sent.append(str(message))
        return {"message_id": 1}

    async def get_group_member_info(self, user_id: int):
        return {"role": "member", "user_id": user_id}


class DummyPaidService(BaseService):
    service_type = Services.Vision
    default_config = {"enabled": True}

    @service_action(
        cmd="付费画图",
        desc="根据提示词生成图片",
        points_cost=5,
        points_reason="vision_generate_image",
    )
    async def paid_action(self, event: GroupMessageEvent):
        self.called = True
        return {"success": True}


def test_run_service_blocks_paid_action_when_points_insufficient(monkeypatch) -> None:
    db = DummyPointsDB(allowed=False, balance=3)
    service = DummyPaidService.__new__(DummyPaidService)
    service.group = DummyGroup(db)
    service._config = {"enabled": True}
    service.called = False

    monkeypatch.setattr(
        registry.service_manager,
        "get_service",
        lambda group_id, service_type: asyncio.sleep(0, result=service),
    )

    event = _make_group_event("/付费画图")
    result = asyncio.run(
        registry.run_service(
            group_id=event.group_id,
            service_enum=Services.Vision,
            action="paid_action",
            event=event,
        )
    )

    assert result["status"] is False
    assert result["error"] == "points_insufficient"
    assert service.called is False
    assert db.calls and db.calls[0]["cost_points"] == 5
    assert "积分不足" in service.group.sent[0]


def test_run_service_executes_paid_action_when_points_sufficient(monkeypatch) -> None:
    db = DummyPointsDB(allowed=True, balance=25)
    service = DummyPaidService.__new__(DummyPaidService)
    service.group = DummyGroup(db)
    service._config = {"enabled": True}
    service.called = False

    monkeypatch.setattr(
        registry.service_manager,
        "get_service",
        lambda group_id, service_type: asyncio.sleep(0, result=service),
    )

    event = _make_group_event("/付费画图")
    result = asyncio.run(
        registry.run_service(
            group_id=event.group_id,
            service_enum=Services.Vision,
            action="paid_action",
            event=event,
        )
    )

    assert result == {"success": True}
    assert service.called is True
    assert db.calls and db.calls[0]["reason"] == "vision_generate_image"


def test_tool_registry_blocks_paid_tool_when_points_insufficient() -> None:
    called = {"value": False}

    async def _handler(arguments, context):
        called["value"] = True
        return {"success": True, "message": "ok"}

    registry_obj = ToolRegistry()
    registry_obj.register(
        ToolDefinition(
            name="generate_image",
            description="根据文字描述生成图片",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_handler,
            points_cost=5,
            points_reason="vision_generate_image",
        )
    )

    result = asyncio.run(
        registry_obj.execute_tool(
            "generate_image",
            {},
            {
                "group_id": 123456,
                "user_id": 456,
                "message_id": 1001,
                "group_db": DummyPointsDB(allowed=False, balance=2),
            },
        )
    )

    assert result["success"] is False
    assert "积分不足" in result["message"]
    assert called["value"] is False
