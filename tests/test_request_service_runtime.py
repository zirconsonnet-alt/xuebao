import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.services.request as request_module
from src.services.request import RequestService, _normalize_answer_patterns, _normalize_welcome_nodes


class FakeDB:
    def __init__(self):
        self.data = None

    def get_service_config(self, service_name: str):
        return self.data

    def upsert_service_config(self, service_name: str, config):
        self.data = config


class FakeGroup:
    def __init__(self, tmp_path: Path):
        self.group_id = 123
        self.self_id = 999
        self.group_path = tmp_path
        self.db = FakeDB()
        self.sent: list[str] = []
        self.forwarded = []
        self.approvals = []

    async def send_msg(self, msg):
        self.sent.append(str(msg))

    async def send_forward_msg(self, nodes):
        self.forwarded.append(nodes)

    async def set_group_add(self, event, value, reason=None):
        self.approvals.append((value, reason))


class FakeBot:
    async def get_stranger_info(self, user_id: int):
        return {"nickname": f"用户{user_id}"}


def test_normalize_request_config_helpers() -> None:
    assert _normalize_answer_patterns(" 北京,上海\n广州，深圳 ") == ["北京", "上海", "广州", "深圳"]
    assert _normalize_answer_patterns(["a", " b "]) == ["A", "B"]

    welcome_nodes = _normalize_welcome_nodes(
        {
            123: [
                {"user_id": 1, "nickname": "欢迎助手", "content": " 你好 "},
                {"user_id": 2, "nickname": "", "content": "   "},
            ],
            "bad": "invalid",
        }
    )
    assert welcome_nodes == {
        "123": [{"user_id": 1, "nickname": "欢迎助手", "content": "你好"}],
    }


def test_request_service_enable_answer_requires_configured_answers(tmp_path: Path) -> None:
    group = FakeGroup(tmp_path)
    service = RequestService(group)

    asyncio.run(service.enable_answer())

    assert service.answer_enabled is False
    assert group.sent[-1] == "⚠️ 请先设置入群答案，再开启入群问答审核"


def test_request_service_manual_review_when_answer_audit_disabled(tmp_path: Path, monkeypatch) -> None:
    group = FakeGroup(tmp_path)
    service = RequestService(group)
    service.enabled = True
    service.answer_enabled = False
    monkeypatch.setattr(request_module.nonebot, "get_bot", lambda: FakeBot())

    event = SimpleNamespace(
        user_id=1001,
        self_id=999,
        group_id=123,
        sub_type="add",
        comment="答案：北京",
    )
    asyncio.run(service.check(event))

    assert group.approvals == []
    assert any("手动处理" in msg for msg in group.sent)


def test_request_service_welcome_only_for_current_group_nodes(tmp_path: Path) -> None:
    group = FakeGroup(tmp_path)
    service = RequestService(group)
    service.enabled = True
    service.welcome_enabled = True
    service.welcome_nodes = {
        "123": [{"user_id": 999, "nickname": "欢迎助手", "content": "欢迎来到 123"}],
        "456": [{"user_id": 999, "nickname": "欢迎助手", "content": "欢迎来到 456"}],
    }

    event = SimpleNamespace(user_id=1001, self_id=999, group_id=123)
    asyncio.run(service.welcome(event))

    assert len(group.forwarded) == 1
    assert isinstance(group.forwarded[0], list)
    assert len(group.forwarded[0]) == 1
