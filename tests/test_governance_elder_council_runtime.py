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


def _load_audit_events(db, action: str) -> list[dict]:
    rows = db.conn.execute(
        """
        SELECT subject_id, result, context_json
        FROM audit_events
        WHERE action = ?
        ORDER BY event_id
        """,
        (action,),
    ).fetchall()
    events: list[dict] = []
    for row in rows:
        events.append(
            {
                "subject_id": row[0] if not isinstance(row, dict) else row["subject_id"],
                "result": row[1] if not isinstance(row, dict) else row["result"],
                "context": json.loads((row[2] if not isinstance(row, dict) else row["context_json"]) or "{}"),
            }
        )
    return events


def _make_event(user_id: int, *, role: str = "member"):
    return SimpleNamespace(
        group_id=9527,
        user_id=int(user_id),
        self_id=114514,
        sender=SimpleNamespace(role=role),
    )


def test_elder_election_enforces_join_days_and_defaults_to_three_seats() -> None:
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
        for user_id in range(100, 135):
            _add_member(storage, user_id, join_time=int((now - timedelta(days=30)).timestamp()))
        _add_member(storage, 200, join_time=int((now - timedelta(days=7)).timestamp()))

        event = _make_event(100)
        asyncio.run(manager.create_elder_election_command(event, "[CQ:at,qq=200] 候选测试"))
        assert group.sent_messages
        assert "入群未满 14 日" in group.sent_messages[-1]

        _add_member(storage, 200, join_time=int((now - timedelta(days=20)).timestamp()))
        asyncio.run(manager.create_elder_election_command(event, "[CQ:at,qq=200] 候选测试"))

        open_case = storage.find_open_case_by_type("elder_election")
        assert open_case is not None
        case = storage.get_case(int(open_case["case_id"]))
        assert case is not None
        payload = case.get("payload") or {}
        assert int(payload.get("seat_count") or 0) == 3
        assert int(payload.get("desired_council_seat_count") or 0) == 3
        assert int(payload.get("term_days") or 0) == 90
        assert "元老会目标席位：3 席" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_honor_owner_impeachment_uses_two_thirds_elder_resolution_and_records_audit() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        now = datetime.now() - timedelta(days=30)
        for user_id in range(100, 106):
            _add_member(storage, user_id, join_time=int(now.timestamp()))
        _add_member(storage, 200, join_time=int(now.timestamp()))
        for elder_id in range(100, 105):
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

        event = _make_event(100)
        asyncio.run(manager.create_honor_owner_impeachment_command(event, "程序失职"))

        open_case = storage.find_open_case("honor_owner_impeachment", 200)
        assert open_case is not None
        case_id = int(open_case["case_id"])
        case = storage.get_case(case_id)
        assert case is not None
        assert int(case.get("support_threshold") or 0) == 4
        for supporter_id in (101, 102, 103):
            assert storage.add_case_support(case_id, supporter_id)

        asyncio.run(manager._advance_case_after_support(case_id=case_id, event=event))

        latest_case = storage.get_case(case_id)
        assert latest_case is not None
        assert latest_case["status"] == "response_window"

        events = _load_audit_events(db, "elder_council_resolution_recorded")
        assert events
        assert events[-1]["subject_id"] == str(case_id)
        assert events[-1]["result"] == "passed"
        assert events[-1]["context"]["decision_kind"] == "start_honor_owner_impeachment"
        assert events[-1]["context"]["required_support"] == 4
        assert events[-1]["context"]["actual_support"] == 4
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_formal_discipline_acceptance_timeout_records_elder_council_audit() -> None:
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
        _add_member(storage, 100, join_time=int((now - timedelta(days=30)).timestamp()))
        _add_member(storage, 200, join_time=int((now - timedelta(days=30)).timestamp()))
        case_id = storage.create_case(
            case_type="formal_discipline",
            title="正式处分测试",
            description="测试",
            proposer_id=100,
            target_user_id=200,
            status="active",
            phase="acceptance_review",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={
                "target_member_id": 200,
                "requested_sanction": "long_mute",
                "current_sanction": "long_mute",
                "requested_duration_seconds": 7 * 24 * 3600,
                "acceptance_due_at": (now - timedelta(minutes=10)).isoformat(),
                "off_group_statement_channel": "平台私聊",
            },
        )

        asyncio.run(manager.auto_advance_due_cases(trigger="test:elder_timeout", actor_id=100))

        events = _load_audit_events(db, "elder_council_review_timeout")
        assert events
        assert events[-1]["subject_id"] == str(case_id)
        assert events[-1]["context"]["request_kind"] == "formal_discipline_acceptance_review"
        assert events[-1]["context"]["fallback_stage"] == "accepted"
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
