import asyncio
import json
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


def _seed_honor_owner_term(storage, *, operator_id: int, honor_owner_id: int, term_expires_at: datetime) -> int:
    term_started_at = term_expires_at - timedelta(days=90)
    storage.set_role_status(
        user_id=honor_owner_id,
        role_code="honor_owner",
        status="active",
        source="test_seed",
        operator_id=operator_id,
        notes="test_seed",
    )
    return storage.create_case(
        case_type="honor_owner_election",
        title="荣誉群主任期记录",
        description="测试任期",
        proposer_id=operator_id,
        target_user_id=honor_owner_id,
        status="approved",
        phase="closed",
        support_threshold=0,
        vote_duration_seconds=300,
        payload={
            "winner_member_id": honor_owner_id,
            "tally": {"approve": 8, "reject": 1, "turnout": 9},
            "term_started_at": term_started_at.isoformat(),
            "term_expires_at": term_expires_at.isoformat(),
        },
    )


def _latest_audit_event(db: GroupDatabase, action: str):
    return db.conn.execute(
        "SELECT action, subject_id, context_json FROM audit_events WHERE action = ? ORDER BY event_id DESC LIMIT 1",
        (action,),
    ).fetchone()


def test_term_expiry_enters_caretaker_and_blocks_high_risk_kick() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=60)).timestamp())
        for user_id in (100, 200, 300):
            _add_member(storage, user_id, join_time=joined_at)
        term_case_id = _seed_honor_owner_term(
            storage,
            operator_id=100,
            honor_owner_id=200,
            term_expires_at=datetime.now() - timedelta(hours=2),
        )

        asyncio.run(manager.show_status(_make_event(200)))

        term_case = storage.get_case(term_case_id)
        assert term_case is not None
        term_payload = term_case.get("payload") or {}
        by_election_case = storage.find_open_case_by_type("honor_owner_election")
        assert by_election_case is not None
        assert int(term_payload.get("caretaker_by_election_case_id") or 0) == int(by_election_case["case_id"])
        assert term_payload.get("caretaker_started_at")
        assert term_payload.get("caretaker_deadline_at")
        assert term_payload.get("last_governance_summary_at")
        assert group.sent_messages
        assert "荣誉群主看守期" in group.sent_messages[-1]
        assert "看守补选" in group.sent_messages[-1]

        asyncio.run(manager.govern_kick_command(_make_event(200), "[CQ:at,qq=300] 看守期不得放逐"))
        assert "看守期" in group.sent_messages[-1]

        asyncio.run(manager.daily_management_command(_make_event(200), "[CQ:at,qq=300] 警告 看守期仍可处理日常事务"))
        assert "已记录日常管理" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_vacancy_status_shows_pending_proxy_and_collective_dispute_channel() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=45)).timestamp())
        for user_id in (100, 101, 102):
            _add_member(storage, user_id, join_time=joined_at)
        storage.set_role_status(
            user_id=100,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        manager._ensure_honor_owner_by_election_case(
            operator_id=100,
            source_case_id=1,
            reopen_reason="荣誉群主空缺",
            failure_count=0,
        )
        asyncio.run(manager.show_status(_make_event(101)))
        assert "临时程序代理：待元老会指定 1 名元老处理必要事务" in group.sent_messages[-1]

        manager._ensure_honor_owner_by_election_case(
            operator_id=100,
            source_case_id=1,
            reopen_reason="补选连续流产",
            failure_count=2,
        )
        asyncio.run(manager.show_status(_make_event(101)))
        assert "争议处理：涉及荣誉群主职权的争议，直接提交全体表决权成员表决" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_direct_governance_kick_requires_reason_and_records_high_risk_action() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=45)).timestamp())
        for user_id in (100, 200, 300):
            _add_member(storage, user_id, join_time=joined_at)
        _seed_honor_owner_term(
            storage,
            operator_id=100,
            honor_owner_id=200,
            term_expires_at=datetime.now() + timedelta(days=30),
        )

        asyncio.run(manager.govern_kick_command(_make_event(200), "[CQ:at,qq=300]"))
        assert "高风险操作" in group.sent_messages[-1]

        asyncio.run(manager.govern_kick_command(_make_event(200), "[CQ:at,qq=300] 持续人身攻击并拒绝停止"))
        assert "理由已留痕" in group.sent_messages[-1]
        audit_row = _latest_audit_event(db, "honor_owner_high_risk_action_recorded")
        assert audit_row is not None
        context = json.loads(audit_row[2])
        assert context["action_type"] == "kick_member"
        assert "持续人身攻击" in context["reason"]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_formal_discipline_scope_and_timeout_fallback_are_recorded() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=45)).timestamp())
        for user_id in (100, 200, 300):
            _add_member(storage, user_id, join_time=joined_at)
        _seed_honor_owner_term(
            storage,
            operator_id=100,
            honor_owner_id=200,
            term_expires_at=datetime.now() + timedelta(days=20),
        )

        asyncio.run(manager.create_formal_discipline_command(_make_event(200), "[CQ:at,qq=300] 长期禁言 7d 持续刷屏并辱骂"))
        case_row = storage.find_open_case("formal_discipline", 300)
        assert case_row is not None
        case_id = int(case_row["case_id"])
        case = storage.get_case(case_id)
        assert case is not None
        payload = case.get("payload") or {}
        assert payload.get("formal_scope_summary") == "长期禁言、限制表决资格、限制被选举资格、移出群聊"

        storage.update_case_fields(
            case_id,
            {
                "payload_json": manager._merge_case_payload(
                    case,
                    {
                        "acceptance_due_at": (datetime.now() - timedelta(minutes=1)).isoformat(),
                    },
                )
            },
        )
        asyncio.run(
            manager._advance_formal_discipline_case(
                case=storage.get_case(case_id),
                event=_make_event(114514, role="admin"),
            )
        )
        refreshed = storage.get_case(case_id)
        assert refreshed is not None
        refreshed_payload = refreshed.get("payload") or {}
        assert refreshed_payload.get("timeout_fallback_actor_stage") == "bot"
        assert refreshed_payload.get("timeout_request_kind") == "formal_discipline_acceptance_review"
        assert "机器人自动转接" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_formal_review_timeout_fallback_is_recorded() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        joined_at = int((datetime.now() - timedelta(days=45)).timestamp())
        for user_id in (100, 300):
            _add_member(storage, user_id, join_time=joined_at)
        source_case_id = storage.create_case(
            case_type="formal_discipline",
            title="测试处分",
            description="测试正式处分",
            proposer_id=100,
            target_user_id=300,
            status="approved",
            phase="closed",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={
                "filer_id": 100,
                "target_member_id": 300,
                "fact_summary": "测试正式处分",
                "evidence_refs": ["test"],
                "requested_sanction": "long_mute",
                "current_sanction": "long_mute",
                "requested_duration_seconds": 7 * 24 * 3600,
                "sanction_type": "long_mute",
                "execution_ref": "formal_ban:604800s",
                "effective_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
                "published_at": datetime.now().isoformat(),
                "closed_at": datetime.now().isoformat(),
            },
        )

        asyncio.run(manager.create_formal_discipline_review_command(_make_event(300), f"{source_case_id} 关键程序错误"))
        review_case_row = storage.find_open_case("formal_discipline_review", 300)
        assert review_case_row is not None
        review_case_id = int(review_case_row["case_id"])
        review_case = storage.get_case(review_case_id)
        assert review_case is not None
        storage.update_case_fields(
            review_case_id,
            {
                "payload_json": manager._merge_case_payload(
                    review_case,
                    {
                        "start_check_due_at": (datetime.now() - timedelta(minutes=1)).isoformat(),
                    },
                )
            },
        )
        asyncio.run(
            manager._advance_formal_discipline_review_case(
                case=storage.get_case(review_case_id),
                event=_make_event(114514, role="admin"),
            )
        )
        refreshed = storage.get_case(review_case_id)
        assert refreshed is not None
        refreshed_payload = refreshed.get("payload") or {}
        assert refreshed_payload.get("timeout_fallback_actor_stage") == "bot"
        assert refreshed_payload.get("timeout_request_kind") == "formal_discipline_review_start_check"
        assert "机器人自动转接" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
