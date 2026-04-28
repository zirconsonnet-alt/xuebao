import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.db import GroupDatabase  # noqa: E402
from src.vendors.nonebot_plugin_law.service import build_governance_manager  # noqa: E402
from src.vendors.nonebot_plugin_law.spec import GOVERNANCE_DEFAULT_CONFIG  # noqa: E402


class _FakeGroup:
    def __init__(self, db, root: Path):
        self.group_id = 9527
        self.db = db
        self._self_id = 114514
        self.laws_path = root / "laws"
        self.laws_path.mkdir(parents=True, exist_ok=True)
        self.sent_messages: list[str] = []
        self._is_voting = False

    @property
    def self_id(self) -> int:
        return self._self_id

    @property
    def is_voting(self) -> bool:
        return self._is_voting

    def set_voting(self, value: bool) -> None:
        self._is_voting = bool(value)

    async def send_msg(self, message):
        self.sent_messages.append(str(message))

    async def ban(self, user_id, duration_seconds):
        return None

    async def kick(self, user_id):
        return None

    async def set_group_admin(self, user_id, enable):
        return None

    async def get_group_member_info(self, user_id):
        return {
            "user_id": int(user_id),
            "nickname": f"U{user_id}",
            "card": "",
            "role": "member",
            "title": "",
        }

    async def get_group_member_list(self):
        return []


class _FakeService:
    def __init__(self, group):
        self.group = group
        self._config = dict(GOVERNANCE_DEFAULT_CONFIG)

    def get_config_value(self, key, default=None):
        return self._config.get(key, default)


class _FakeMessage:
    def __init__(self, raw_text: str, plain_text: str):
        self._raw_text = raw_text
        self._plain_text = plain_text

    def extract_plain_text(self):
        return self._plain_text

    def __str__(self) -> str:
        return self._raw_text


def _add_member(storage, user_id: int, *, role: str = "member", join_time: int | None = None) -> None:
    storage.upsert_member_profile(
        {
            "user_id": int(user_id),
            "nickname": f"U{user_id}",
            "card": "",
            "role": role,
            "title": "",
            "join_time": join_time,
        }
    )


def _make_event(user_id: int, *, role: str = "member"):
    return SimpleNamespace(
        group_id=9527,
        user_id=int(user_id),
        self_id=114514,
        sender=SimpleNamespace(role=role),
    )


def test_manual_set_honor_owner_revokes_elder_role() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=30)).timestamp())
        _add_member(storage, 100, role="admin", join_time=joined_at)
        _add_member(storage, 200, join_time=joined_at)
        storage.set_role_status(
            user_id=200,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        asyncio.run(manager.set_honor_owner_command(_make_event(100, role="admin"), "[CQ:at,qq=200]"))

        assert storage.get_active_role_user("honor_owner") == 200
        assert not storage.has_role(200, "elder")
        assert group.sent_messages
        assert "同步解除其元老身份" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_add_elder_rejects_current_honor_owner() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=30)).timestamp())
        _add_member(storage, 100, role="admin", join_time=joined_at)
        _add_member(storage, 200, join_time=joined_at)
        storage.set_role_status(
            user_id=200,
            role_code="honor_owner",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        asyncio.run(manager.add_elder_command(_make_event(100, role="admin"), "[CQ:at,qq=200]"))

        assert not storage.has_role(200, "elder")
        assert group.sent_messages
        assert "不得兼任元老" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_locked_elder_cannot_start_honor_owner_impeachment() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=30)).timestamp())
        _add_member(storage, 100, join_time=joined_at)
        _add_member(storage, 200, join_time=joined_at)
        storage.set_role_status(
            user_id=100,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )
        storage.set_role_status(
            user_id=200,
            role_code="honor_owner",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )
        source_case_id = storage.create_case(
            case_type="elder_impeachment",
            title="冻结测试",
            description="冻结测试",
            proposer_id=100,
            target_user_id=100,
            status="supporting",
            phase="support",
            support_threshold=1,
            vote_duration_seconds=0,
            payload={},
        )
        storage.upsert_lock(
            lock_key="test:elder_lock",
            lock_type="elder_powers",
            target_user_id=100,
            source_case_id=source_case_id,
            reason="测试冻结",
            payload={},
        )

        asyncio.run(manager.create_honor_owner_impeachment_command(_make_event(100), "测试"))

        assert storage.find_open_case("honor_owner_impeachment", 200) is None
        assert group.sent_messages
        assert "元老职权已被冻结" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_frozen_honor_owner_loses_direct_formal_discipline_authority() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=30)).timestamp())
        _add_member(storage, 100, join_time=joined_at)
        _add_member(storage, 200, join_time=joined_at)
        storage.set_role_status(
            user_id=100,
            role_code="honor_owner",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )
        source_case_id = storage.create_case(
            case_type="honor_owner_impeachment",
            title="冻结测试",
            description="冻结测试",
            proposer_id=100,
            target_user_id=100,
            status="supporting",
            phase="support",
            support_threshold=1,
            vote_duration_seconds=0,
            payload={},
        )
        storage.upsert_lock(
            lock_key="test:honor_owner_lock",
            lock_type="honor_owner_powers",
            target_user_id=100,
            source_case_id=source_case_id,
            reason="测试冻结",
            payload={},
        )

        asyncio.run(
            manager.create_formal_discipline_command(
                _make_event(100),
                _FakeMessage("[CQ:at,qq=200] 长期禁言 7d 测试处分", "长期禁言 7d 测试处分"),
            )
        )

        open_case = storage.find_open_case("formal_discipline", 200)
        assert open_case is not None
        case = storage.get_case(int(open_case["case_id"]))
        assert case is not None
        assert case["status"] == "supporting"
        assert case["phase"] == "support"
        assert group.sent_messages
        assert "已创建正式处分申请案件" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
