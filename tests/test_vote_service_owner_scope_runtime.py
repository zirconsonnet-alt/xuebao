import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import registry  # noqa: E402
from src.services.vote import VoteService  # noqa: E402
from src.support.core import Services  # noqa: E402
from nonebot.adapters.onebot.v11 import Message  # noqa: E402


class _FakeDb:
    def upsert_service_config(self, service_type: str, config: dict) -> None:
        return None


class _FakeGroup:
    def __init__(self, *, group_id: int, bot_role: str = "owner"):
        self.group_id = group_id
        self.db = _FakeDb()
        self.sent: list[str] = []
        self._bot_role = bot_role

    @property
    def self_id(self) -> int:
        return 114514

    async def send_msg(self, message):
        self.sent.append(str(message))

    async def get_group_member_info(self, user_id: int):
        return {"user_id": int(user_id), "role": self._bot_role}


class _FakeServiceManager:
    def __init__(self, service: VoteService):
        self._service = service

    async def get_service(self, group_id: int, service_type: Services, *, self_id=None):
        return self._service

    def get_group(self, group_id: int):
        return self._service.group


def _make_vote_service(*, group_id: int, bot_role: str = "owner", enabled: bool = True) -> VoteService:
    group = _FakeGroup(group_id=group_id, bot_role=bot_role)
    service = VoteService.__new__(VoteService)
    service.group = group
    service._config = {"enabled": enabled}
    return service


def _make_event(*, group_id: int, self_id: int = 114514):
    return SimpleNamespace(
        group_id=group_id,
        user_id=10001,
        self_id=self_id,
        sender=SimpleNamespace(role="owner"),
    )


def test_vote_service_rejects_use_outside_authorized_group(monkeypatch) -> None:
    service = _make_vote_service(group_id=9527, enabled=True)
    monkeypatch.setattr(registry, "service_manager", _FakeServiceManager(service))

    result = asyncio.run(
        registry.run_service(
            group_id=9527,
            service_enum=Services.Vote,
            action="list_governance_cases",
            event=_make_event(group_id=9527),
        )
    )

    assert result["error"] == "service_unavailable"
    assert service.group.sent == [
        "⛔ 群法律治理插件仅允许在授权群使用。当前授权群：1034063784。"
    ]


def test_vote_service_rejects_enable_when_bot_is_not_group_owner(monkeypatch) -> None:
    service = _make_vote_service(group_id=1034063784, bot_role="admin", enabled=False)
    monkeypatch.setattr(registry, "service_manager", _FakeServiceManager(service))

    result = asyncio.run(
        registry.run_service(
            group_id=1034063784,
            service_enum=Services.Vote,
            action="enable_service",
            event=_make_event(group_id=1034063784),
        )
    )

    assert result["error"] == "service_unavailable"
    assert service.enabled is False
    assert service.group.sent == ["⛔ 群法律治理插件只能在机器人为群主的群开启或使用。"]


def test_vote_service_allows_disable_outside_authorized_group(monkeypatch) -> None:
    service = _make_vote_service(group_id=9527, enabled=True)
    monkeypatch.setattr(registry, "service_manager", _FakeServiceManager(service))

    result = asyncio.run(
        registry.run_service(
            group_id=9527,
            service_enum=Services.Vote,
            action="disable_service",
            event=_make_event(group_id=9527),
        )
    )

    assert result is None
    assert service.enabled is False
    assert service.group.sent == ["✅ 本群投票服务关闭成功！"]


def test_vote_service_command_usage_accepts_full_command_query() -> None:
    service = _make_vote_service(group_id=1034063784, enabled=True)

    asyncio.run(
        service.show_command_usage(
            _make_event(group_id=1034063784),
            Message("/设置荣誉群主 测试参数"),
        )
    )

    output = service.group.sent[-1]
    assert "【设置荣誉群主】" in output
    assert "示例聊天记录" in output
    assert "群友：/设置荣誉群主 @成员" in output
    assert "机器人：开始处理【设置唯一荣誉群主并同步平台管理员】" in output
