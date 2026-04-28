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


def test_elder_reboot_rejects_daily_conflict_only_reason() -> None:
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
        for user_id in (100, 101, 102):
            _add_member(storage, user_id, join_time=joined_at)

        asyncio.run(manager.create_elder_reboot_command(_make_event(100), "我只是看他们不顺眼，有个人恩怨"))

        assert storage.find_open_case("elder_reboot", None) is None
        assert group.sent_messages
        assert "不得仅以具体裁决不满、政治立场差异或个人恩怨作为理由" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_elder_reboot_records_institutional_reason_catalog() -> None:
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
        for user_id in range(100, 112):
            _add_member(storage, user_id, join_time=joined_at)

        asyncio.run(manager.create_elder_reboot_command(_make_event(100), "元老会长期无法形成法定人数，并阻碍弹劾和选举"))

        open_case = storage.find_open_case("elder_reboot", None)
        assert open_case is not None
        case = storage.get_case(int(open_case["case_id"]))
        assert case is not None
        payload = case.get("payload") or {}
        assert payload.get("institutional_reason_codes") == ["long_no_quorum_or_timeout", "collective_obstruction"]
        assert "长期无法形成法定人数" in str(payload.get("institutional_reason_summary") or "")
        assert payload.get("constitutional_remedy") is True
        assert group.sent_messages
        assert "制度性理由" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_elder_reboot_approval_records_interim_supervision_and_status_notice() -> None:
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
        for user_id in range(100, 112):
            _add_member(storage, user_id, join_time=joined_at)
        storage.set_role_status(
            user_id=200,
            role_code="honor_owner",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )
        for elder_id in (101, 102, 103):
            storage.set_role_status(
                user_id=elder_id,
                role_code="elder",
                status="active",
                source="test_seed",
                operator_id=100,
                notes="test_seed",
            )

        case_id = storage.create_case(
            case_type="elder_reboot",
            title="是否启动重组元老会程序",
            description="监督机制整体失灵",
            proposer_id=100,
            target_user_id=None,
            status="voting",
            phase="vote",
            support_threshold=7,
            vote_duration_seconds=300,
            payload={
                "fact_summary": "监督机制整体失灵",
                "institutional_reason": "监督机制整体失灵",
                "institutional_reason_codes": ["other_institutional_breakdown"],
                "institutional_reason_summary": "其他足以证明监督机制整体失灵的制度性理由",
            },
        )
        case = storage.get_case(case_id)
        assert case is not None

        summary = asyncio.run(
            manager._finalize_case_vote(
                case_id=case_id,
                case=case,
                tallies={1: 8, 2: 1},
                voter_count=9,
            )
        )

        refreshed_case = storage.get_case(case_id)
        assert refreshed_case is not None
        payload = refreshed_case.get("payload") or {}
        assert payload.get("interim_supervision_active") is True
        assert payload.get("interim_supervision_mode") == "honor_owner_daily_only"
        assert payload.get("honor_owner_self_review_channel")
        assert int(payload.get("new_council_election_started_case_id") or 0) > 0
        assert storage.get_active_role_users("elder") == []
        assert "临时监督" in summary

        asyncio.run(manager.show_status(_make_event(100)))
        assert group.sent_messages
        assert "重组监督" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_reboot_sourced_elder_election_failures_escalate_and_success_clears_collective_supervision() -> None:
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
        for user_id in range(100, 120):
            _add_member(storage, user_id, join_time=joined_at)
        for winner_id in (300, 301, 302):
            _add_member(storage, winner_id, join_time=joined_at)

        reboot_case_id = storage.create_case(
            case_type="elder_reboot",
            title="是否启动重组元老会程序",
            description="监督机制整体失灵",
            proposer_id=100,
            target_user_id=None,
            status="approved",
            phase="closed",
            support_threshold=7,
            vote_duration_seconds=300,
            payload={
                "institutional_reason_codes": ["other_institutional_breakdown"],
                "institutional_reason_summary": "其他足以证明监督机制整体失灵的制度性理由",
                "interim_supervision_active": True,
                "interim_supervision_mode": "honor_owner_daily_only",
                "new_council_failed_election_rounds": 0,
                "new_council_election_started_case_id": 0,
            },
        )

        first_election_case_id = manager._ensure_elder_by_election_case(
            operator_id=100,
            source_case_id=reboot_case_id,
            reopen_reason="重组后换届补选",
            seat_count=3,
        )
        first_election_case = storage.get_case(first_election_case_id)
        assert first_election_case is not None
        asyncio.run(
            manager._reject_elder_election_case(
                case_id=first_election_case_id,
                case=first_election_case,
                remaining_seats=3,
                reason="第一次换届流产",
            )
        )

        reboot_case = storage.get_case(reboot_case_id)
        assert reboot_case is not None
        reboot_payload = reboot_case.get("payload") or {}
        assert int(reboot_payload.get("new_council_failed_election_rounds") or 0) == 1
        assert reboot_payload.get("temporary_collective_supervision_active") in {None, False}

        second_open_case = storage.find_open_case_by_type("elder_election")
        assert second_open_case is not None
        second_case_id = int(second_open_case["case_id"])
        second_election_case = storage.get_case(second_case_id)
        assert second_election_case is not None
        asyncio.run(
            manager._reject_elder_election_case(
                case_id=second_case_id,
                case=second_election_case,
                remaining_seats=3,
                reason="第二次换届流产",
            )
        )

        reboot_case = storage.get_case(reboot_case_id)
        assert reboot_case is not None
        reboot_payload = reboot_case.get("payload") or {}
        assert int(reboot_payload.get("new_council_failed_election_rounds") or 0) == 2
        assert reboot_payload.get("temporary_collective_supervision_active") is True

        third_open_case = storage.find_open_case_by_type("elder_election")
        assert third_open_case is not None
        third_case_id = int(third_open_case["case_id"])
        third_case = storage.get_case(third_case_id)
        assert third_case is not None
        lines = asyncio.run(
            manager._approve_elder_election_case(
                case_id=third_case_id,
                case=third_case,
                winner_member_ids=[300, 301, 302],
                remaining_seats=0,
            )
        )

        reboot_case = storage.get_case(reboot_case_id)
        assert reboot_case is not None
        reboot_payload = reboot_case.get("payload") or {}
        assert reboot_payload.get("temporary_collective_supervision_active") is False
        assert reboot_payload.get("interim_supervision_active") is False
        assert reboot_payload.get("new_council_restored_at")
        assert any("已当选元老" in line for line in lines)
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
