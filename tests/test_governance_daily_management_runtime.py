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
        self.ban_actions: list[tuple[int, int]] = []
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
        self.ban_actions.append((int(user_id), int(duration_seconds)))
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


def _seed_honor_owner(storage, user_id: int) -> None:
    storage.set_role_status(
        user_id=user_id,
        role_code="honor_owner",
        status="active",
        source="test_seed",
        operator_id=user_id,
        notes="test_seed",
    )


def test_daily_management_short_mute_creates_record_and_executes_ban() -> None:
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
        _seed_honor_owner(storage, 100)

        asyncio.run(manager.daily_management_command(_make_event(100), "[CQ:at,qq=200] 短期禁言 30m 连续刷屏"))

        cases = storage.fetchall(
            """
            SELECT case_id, payload_json, status, phase
            FROM governance_cases
            WHERE case_type = 'daily_management'
            ORDER BY case_id DESC
            LIMIT 1
            """
        )
        assert cases
        case = cases[0]
        payload = case.get("payload") or {}
        assert case["status"] == "approved"
        assert case["phase"] == "closed"
        assert payload["action_type"] == "short_mute"
        assert str(payload["execution_ref"]).startswith("daily_short_mute:")
        assert group.ban_actions == [(200, 1800)]
        assert group.sent_messages
        assert "短期禁言" in group.sent_messages[-1]
        assert "后续衔接" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_daily_management_motion_restriction_blocks_governance_motion() -> None:
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
        _add_member(storage, 300, join_time=joined_at)
        _seed_honor_owner(storage, 100)

        asyncio.run(manager.daily_management_command(_make_event(100), "[CQ:at,qq=200] 限制提案 12h 连续恶意发起动议"))
        asyncio.run(manager.create_honor_owner_election_command(_make_event(200), "[CQ:at,qq=300] 提名测试"))

        assert storage.find_open_case_by_type("honor_owner_election") is None
        assert group.sent_messages
        assert "提案/动议限制期间" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_daily_management_rejects_formal_only_sanctions() -> None:
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
        _seed_honor_owner(storage, 100)

        asyncio.run(manager.daily_management_command(_make_event(100), "[CQ:at,qq=200] 长期禁言 7d 反复违规"))

        row = storage.fetchone("SELECT COUNT(*) AS total FROM governance_cases WHERE case_type = 'daily_management'")
        assert int((row or {}).get("total") or 0) == 0
        assert group.sent_messages
        assert "不得由日常管理直接作出" in group.sent_messages[-1]
        assert "发起正式处分" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_daily_management_warning_carries_prior_action_labels() -> None:
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
        _seed_honor_owner(storage, 100)

        asyncio.run(manager.daily_management_command(_make_event(100), "[CQ:at,qq=200] 提醒 首次偏离话题"))
        asyncio.run(manager.daily_management_command(_make_event(100), "[CQ:at,qq=200] 警告 再次偏离话题"))

        cases = storage.fetchall(
            """
            SELECT case_id, payload_json
            FROM governance_cases
            WHERE case_type = 'daily_management'
            ORDER BY case_id DESC
            LIMIT 1
            """
        )
        assert cases
        payload = cases[0].get("payload") or {}
        assert payload["action_type"] == "warning"
        assert payload["prior_action_labels"] == ["提醒"]
        assert group.sent_messages
        assert "前序记录：提醒" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
