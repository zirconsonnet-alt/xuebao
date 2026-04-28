import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import registry
from src.services.base import BaseService, service_action
from src.support.core import Services


class DummyGroup:
    def __init__(self):
        self.sent: list[str] = []

    async def send_msg(self, msg):
        self.sent.append(str(msg))

    async def get_group_member_info(self, user_id: int):
        return {"role": "member"}


class DummyService:
    def __init__(self, group: DummyGroup):
        self.group = group
        self.enabled = True

    def is_feature_enabled(self, handler_name: str, *, default: bool = True) -> bool:
        return default

    @service_action(cmd="管理员动作", require_admin=True)
    async def admin_action(self, event):
        return {"status": True}

    @service_action(cmd="群主动作", require_owner=True)
    async def owner_action(self, event):
        return {"status": True}


class DummyManager:
    def __init__(self, service: DummyService):
        self._service = service

    async def get_service(self, group_id: int, service_type: Services, *, self_id=None):
        return self._service

    def get_group(self, group_id: int):
        return self._service.group


class DummyDb:
    def upsert_service_config(self, service_type: str, config: dict) -> None:
        return None


class AutoToggleService(BaseService):
    service_type = Services.Info
    default_config = {"enabled": False}


def test_member_cannot_call_admin_only_service_action(monkeypatch) -> None:
    group = DummyGroup()
    manager = DummyManager(DummyService(group))
    event = SimpleNamespace(group_id=123, user_id=456, sender=SimpleNamespace(role="member"))
    monkeypatch.setattr(registry, "service_manager", manager)

    result = asyncio.run(
        registry.run_service(
            group_id=123,
            service_enum=Services.Info,
            action="admin_action",
            event=event,
        )
    )

    assert result["error"] == "permission_denied"
    assert group.sent == ["⛔ 此操作需要管理员权限。"]


def test_owner_can_call_owner_only_service_action(monkeypatch) -> None:
    group = DummyGroup()
    manager = DummyManager(DummyService(group))
    event = SimpleNamespace(group_id=123, user_id=456, sender=SimpleNamespace(role="owner"))
    monkeypatch.setattr(registry, "service_manager", manager)

    result = asyncio.run(
        registry.run_service(
            group_id=123,
            service_enum=Services.Info,
            action="owner_action",
            event=event,
        )
    )

    assert result == {"status": True}
    assert group.sent == []


def test_base_service_collects_builtin_toggle_commands() -> None:
    manager = object.__new__(registry.ServiceManager)
    manager.service_commands = {}

    registry.ServiceManager._collect_service_commands(manager, AutoToggleService)

    commands = manager.service_commands[Services.Info]
    command_names = {cmd.cmd for cmd in commands}
    handler_names = {cmd.handler_name for cmd in commands}

    assert AutoToggleService.get_enable_command_name() in command_names
    assert AutoToggleService.get_disable_command_name() in command_names
    assert "enable_service" in handler_names
    assert "disable_service" in handler_names


def test_disabled_service_can_be_enabled_via_base_toggle(monkeypatch) -> None:
    group = DummyGroup()
    group.db = DummyDb()

    service = AutoToggleService.__new__(AutoToggleService)
    service.group = group
    service._config = {"enabled": False}

    manager = DummyManager(service)
    monkeypatch.setattr(registry, "service_manager", manager)

    result = asyncio.run(
        registry.run_service(
            group_id=123,
            service_enum=Services.Info,
            action="enable_service",
        )
    )

    assert result is None
    assert service.enabled is True
    assert group.sent == ["✅ 本群基础信息服务开启成功！"]
