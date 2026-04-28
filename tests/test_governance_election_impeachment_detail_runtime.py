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

    def get_all_laws(self):
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


def test_honor_owner_nomination_requires_join_days_and_joint_recommendation_confirmation() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        now = datetime.now()
        for user_id in range(100, 110):
            _add_member(storage, user_id, join_time=int((now - timedelta(days=30)).timestamp()))
        _add_member(storage, 200, join_time=int((now - timedelta(days=20)).timestamp()))
        _add_member(storage, 300, join_time=int((now - timedelta(days=7)).timestamp()))

        asyncio.run(manager.create_honor_owner_election_command(_make_event(300), "[CQ:at,qq=300] 自荐"))
        assert group.sent_messages
        assert "入群未满 14 日" in group.sent_messages[-1]

        asyncio.run(manager.create_honor_owner_election_command(_make_event(100), "[CQ:at,qq=200] 联名推荐"))
        open_case = storage.find_open_case_by_type("honor_owner_election")
        assert open_case is not None
        case_id = int(open_case["case_id"])

        for supporter_id in (101, 102, 103, 104):
            asyncio.run(
                manager.create_honor_owner_election_command(
                    _make_event(supporter_id),
                    "[CQ:at,qq=200] 联名推荐",
                )
            )

        case = storage.get_case(case_id)
        assert case is not None
        payload = case.get("payload") or {}
        entry = (payload.get("candidate_nominations") or {}).get("200") or {}
        assert payload.get("candidate_member_ids") == []
        assert int(entry.get("supporter_count") or 0) == 5
        assert entry.get("nomination_status") == "pending_self_confirmation"

        asyncio.run(manager.create_honor_owner_election_command(_make_event(200), "[CQ:at,qq=200] 愿意履职并接受监督"))

        refreshed_case = storage.get_case(case_id)
        assert refreshed_case is not None
        refreshed_payload = refreshed_case.get("payload") or {}
        refreshed_entry = (refreshed_payload.get("candidate_nominations") or {}).get("200") or {}
        assert refreshed_payload.get("candidate_member_ids") == [200]
        assert refreshed_payload.get("nomination_method") == "joint_recommendation"
        assert refreshed_entry.get("willing_to_serve_confirmed") is True
        assert group.sent_messages
        assert "录入荣誉群主选举案件" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_honor_owner_election_approval_records_term_and_status_display() -> None:
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

        case_id = storage.create_case(
            case_type="honor_owner_election",
            title="荣誉群主选举提名公示",
            description="测试",
            proposer_id=100,
            target_user_id=200,
            status="voting",
            phase="vote",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={
                "candidate_member_ids": [200],
                "candidate_nominations": {
                    "200": {
                        "candidate_id": 200,
                        "nomination_method": "self_nomination",
                        "supporter_ids": [200],
                        "supporter_threshold": 5,
                        "supporter_count": 1,
                        "willing_to_serve_confirmed": True,
                        "nomination_status": "qualified",
                    }
                },
                "nomination_method": "self_nomination",
                "nomination_support_threshold": 5,
            },
        )
        case = storage.get_case(case_id)
        assert case is not None

        lines = asyncio.run(manager._approve_honor_owner_election_case(case_id=case_id, case=case, winner_member_id=200))
        refreshed_case = storage.get_case(case_id)
        assert refreshed_case is not None
        refreshed_payload = refreshed_case.get("payload") or {}

        assert storage.get_active_role_user("honor_owner") == 200
        assert int(refreshed_payload.get("winner_member_id") or 0) == 200
        assert refreshed_payload.get("term_started_at")
        assert refreshed_payload.get("term_expires_at")
        assert any("任期记录" in line for line in lines)

        asyncio.run(manager.show_status(_make_event(100)))
        assert group.sent_messages
        assert "荣誉群主任期：" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_impeachment_reason_catalogs_are_recorded() -> None:
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
        for user_id in (100, 101, 102, 103, 200, 201):
            _add_member(storage, user_id, join_time=joined_at)
        for elder_id in (100, 101, 201):
            storage.set_role_status(
                user_id=elder_id,
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

        asyncio.run(manager.create_honor_owner_impeachment_command(_make_event(100), "我不喜欢他"))
        assert group.sent_messages
        assert "法定范围" in group.sent_messages[-1]
        assert storage.find_open_case("honor_owner_impeachment", 200) is None

        asyncio.run(manager.create_honor_owner_impeachment_command(_make_event(100), "越权并阻碍投票"))
        honor_case = storage.find_open_case("honor_owner_impeachment", 200)
        assert honor_case is not None
        honor_payload = (storage.get_case(int(honor_case["case_id"])) or {}).get("payload") or {}
        assert honor_payload.get("reason_codes") == ["abuse_high_risk_power", "obstruct_lawful_process"]

        asyncio.run(manager.create_elder_impeachment_command(_make_event(102), "[CQ:at,qq=201] 泄露隐私并滥用复核权"))
        elder_case = storage.find_open_case("elder_impeachment", 201)
        assert elder_case is not None
        elder_payload = (storage.get_case(int(elder_case["case_id"])) or {}).get("payload") or {}
        assert elder_payload.get("reason_codes") == ["abuse_proxy_or_review_power", "privacy_or_record_misconduct"]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_failed_honor_owner_by_elections_trigger_temporary_autonomy_window() -> None:
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

        first_case_id = storage.create_case(
            case_type="honor_owner_election",
            title="荣誉群主选举提名公示",
            description="测试",
            proposer_id=100,
            target_user_id=200,
            status="voting",
            phase="vote",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={"candidate_member_ids": [200]},
        )
        first_case = storage.get_case(first_case_id)
        assert first_case is not None
        asyncio.run(manager._reject_honor_owner_election_case(case_id=first_case_id, case=first_case, reason="首次补选失败"))

        by_election_case = storage.find_open_case_by_type("honor_owner_election")
        assert by_election_case is not None
        second_case_id = int(by_election_case["case_id"])
        second_case = storage.get_case(second_case_id)
        assert second_case is not None

        lines = asyncio.run(manager._reject_honor_owner_election_case(case_id=second_case_id, case=second_case, reason="第二次补选失败"))

        reopened_case = storage.find_open_case_by_type("honor_owner_election")
        assert reopened_case is not None
        reopened_payload = (storage.get_case(int(reopened_case["case_id"])) or {}).get("payload") or {}
        assert int(reopened_payload.get("consecutive_failed_by_election_rounds") or 0) == 2
        assert reopened_payload.get("temporary_autonomy_restart_deadline_at")
        assert any("临时自治" in line for line in lines)

        asyncio.run(manager.show_status(_make_event(100)))
        assert group.sent_messages
        assert "机器人临时自治" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
