import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

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


class _FakeService:
    def __init__(self, group):
        self.group = group
        self._config = dict(GOVERNANCE_DEFAULT_CONFIG)

    def get_config_value(self, key, default=None):
        return self._config.get(key, default)


def _add_member(storage, user_id: int, role: str = "member") -> None:
    storage.upsert_member_profile(
        {
            "user_id": int(user_id),
            "nickname": f"U{user_id}",
            "card": "",
            "role": role,
            "title": "",
        }
    )


def _load_auto_scan_events(db) -> list[dict]:
    rows = db.conn.execute(
        """
        SELECT action, subject_id, result, context_json
        FROM audit_events
        WHERE action = 'governance_case_auto_advanced'
        ORDER BY event_id
        """
    ).fetchall()
    events = []
    for row in rows:
        context_json = row[3] if not isinstance(row, dict) else row["context_json"]
        events.append(
            {
                "action": row[0] if not isinstance(row, dict) else row["action"],
                "subject_id": row[1] if not isinstance(row, dict) else row["subject_id"],
                "result": row[2] if not isinstance(row, dict) else row["result"],
                "context": json.loads(context_json or "{}"),
            }
        )
    return events


def test_auto_scan_advances_due_formal_discipline_notice_chain() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage
        _add_member(storage, 100)
        _add_member(storage, 200)

        past_due = datetime.now() - timedelta(hours=1)
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
                "acceptance_due_at": past_due.isoformat(),
                "off_group_statement_channel": "平台私聊",
            },
        )

        asyncio.run(manager.auto_advance_due_cases(trigger="test:formal_notice", actor_id=100))

        latest_case = storage.get_case(case_id)
        assert latest_case is not None
        assert latest_case["phase"] == "notice_in_progress"
        assert latest_case["status"] == "active"
        payload = latest_case.get("payload") or {}
        assert payload.get("accepted_at")
        assert payload.get("deemed_service_deadline")

        events = _load_auto_scan_events(db)
        assert events
        assert events[-1]["subject_id"] == str(case_id)
        assert events[-1]["result"] == "success"
        assert events[-1]["context"]["after_phase"] == "notice_in_progress"
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_auto_scan_advances_due_formal_review_and_reopens_formal_case() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage
        _add_member(storage, 100)
        _add_member(storage, 200)

        published_at = datetime.now() - timedelta(hours=1)
        source_case_id = storage.create_case(
            case_type="formal_discipline",
            title="正式处分源案件",
            description="测试",
            proposer_id=100,
            target_user_id=200,
            status="approved",
            phase="closed",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={
                "target_member_id": 200,
                "fact_summary": "测试事实",
                "requested_sanction": "long_mute",
                "current_sanction": "long_mute",
                "sanction_type": "long_mute",
                "requested_duration_seconds": 7 * 24 * 3600,
                "published_at": published_at.isoformat(),
                "effective_at": published_at.isoformat(),
                "execution_ref": "formal_case:seed",
                "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
            },
        )
        storage.update_case_fields(source_case_id, {"resolved_at": published_at.isoformat()})
        review_case_id = storage.create_case(
            case_type="formal_discipline_review",
            title="处分复核",
            description="程序错误",
            proposer_id=200,
            target_user_id=200,
            status="active",
            phase="review_start_check",
            support_threshold=0,
            vote_duration_seconds=0,
            payload={
                "source_case_id": source_case_id,
                "requester_id": 200,
                "review_reasons": "程序错误",
                "review_reason_codes": ["procedural_error"],
                "submitted_at": published_at.isoformat(),
                "start_check_due_at": (datetime.now() - timedelta(minutes=10)).isoformat(),
                "pause_execution_requested": False,
            },
        )
        storage.update_case_fields(
            source_case_id,
            {
                "payload_json": manager._merge_case_payload(
                    storage.get_case(source_case_id),
                    {"review_started_case_id": review_case_id},
                )
            },
        )

        asyncio.run(manager.auto_advance_due_cases(trigger="test:review", actor_id=200))

        latest_review_case = storage.get_case(review_case_id)
        assert latest_review_case is not None
        assert latest_review_case["status"] == "approved"
        assert latest_review_case["phase"] == "closed"
        reopened_case_id = int((latest_review_case.get("payload") or {}).get("new_case_ref") or 0)
        reopened_case = storage.get_case(reopened_case_id)
        assert reopened_case is not None
        assert reopened_case["case_type"] == "formal_discipline"
        assert reopened_case["phase"] == "accepted"

        events = _load_auto_scan_events(db)
        assert len(events) >= 2
        assert any(event["context"]["reason"] == "review_start_due" for event in events)
        assert any(event["context"]["reason"] == "reopened_followup" for event in events)
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_auto_scan_queues_due_vote_in_background() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage
        _add_member(storage, 100)
        _add_member(storage, 200)

        case_id = storage.create_case(
            case_type="honor_owner_election",
            title="荣誉群主选举",
            description="测试",
            proposer_id=100,
            target_user_id=200,
            status="statement_and_questioning",
            phase="statement_and_questioning",
            support_threshold=0,
            vote_duration_seconds=300,
            payload={
                "candidate_id": 200,
                "candidate_member_ids": [200],
                "questioning_closes_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
            },
        )

        started_case_ids: list[int] = []

        async def _fake_start_case_vote(*, case_id: int, event, preclaimed: bool = False):
            started_case_ids.append(case_id)
            storage.update_case_fields(
                case_id,
                {
                    "status": "voting",
                    "phase": "vote",
                    "vote_started_at": datetime.now().isoformat(),
                },
            )
            group.set_voting(False)

        manager._start_case_vote = _fake_start_case_vote

        async def _run():
            await manager.auto_advance_due_cases(trigger="test:vote", actor_id=100)
            await asyncio.sleep(0.05)

        asyncio.run(_run())

        latest_case = storage.get_case(case_id)
        assert started_case_ids == [case_id]
        assert latest_case is not None
        assert latest_case["status"] == "voting"
        assert latest_case["phase"] == "vote"

        events = _load_auto_scan_events(db)
        assert events
        assert events[-1]["context"]["result"] == "queued_vote"
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
