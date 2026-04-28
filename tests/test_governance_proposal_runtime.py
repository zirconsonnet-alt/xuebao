import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace

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


def _add_member(storage, user_id: int, *, role: str = "member") -> None:
    storage.upsert_member_profile(
        {
            "user_id": int(user_id),
            "nickname": f"U{user_id}",
            "card": "",
            "role": role,
            "title": "",
            "join_time": int((datetime.now() - timedelta(days=45)).timestamp()),
        }
    )


def _make_event(user_id: int, *, role: str = "member"):
    return SimpleNamespace(
        group_id=9527,
        user_id=int(user_id),
        self_id=114514,
        sender=SimpleNamespace(role=role),
    )


def _latest_audit_event(db: GroupDatabase, action: str):
    return db.conn.execute(
        "SELECT action, subject_id, context_json FROM audit_events WHERE action = ? ORDER BY event_id DESC LIMIT 1",
        (action,),
    ).fetchone()


def test_proposal_creation_supports_rulemaking_types_and_temporary_measure_limit() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in (100, 101, 102):
            _add_member(storage, user_id)
        storage.set_role_status(
            user_id=100,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        asyncio.run(
            manager.create_proposal_command(
                _make_event(101),
                "宪制修订案 群规修订 | 调整基础治理结构 | 将元老会换届程序写入正文 | 通过后即生效 | 是",
            )
        )
        proposal_case = storage.find_open_case_by_type("ordinary_proposal")
        assert proposal_case is not None
        proposal = storage.get_case(int(proposal_case["case_id"]))
        assert proposal is not None
        payload = proposal.get("payload") or {}
        assert payload["proposal_type"] == "constitutional_amendment"
        assert payload["high_risk_power_requested"] is True
        assert proposal["vote_duration_seconds"] == 24 * 3600
        assert "宪制修订案" in group.sent_messages[-1]

        asyncio.run(
            manager.create_proposal_command(
                _make_event(102),
                "临时管理措施 临时值日 | 临时安排卫生轮值 | 一周内安排轮值 | 8天后失效 | 否",
            )
        )
        assert "不得超过 7 日" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_proposal_correction_cycle_returns_case_to_procedural_review() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in (100, 101):
            _add_member(storage, user_id)
        storage.set_role_status(
            user_id=100,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        asyncio.run(
            manager.create_proposal_command(
                _make_event(101),
                "基础治理条例案 值日条例 | 规范值日制度 | 初版文本待补充 | 通过后次日生效 | 否",
            )
        )
        case_id = int(storage.find_open_case_by_type("ordinary_proposal")["case_id"])

        asyncio.run(manager.review_proposal_command(_make_event(100), f"{case_id} 补正 请补充请假和替班规则"))
        proposal = storage.get_case(case_id)
        assert proposal is not None
        assert proposal["phase"] == "correction_requested"
        assert (proposal.get("payload") or {}).get("correction_items") == "请补充请假和替班规则"

        asyncio.run(
            manager.correct_proposal_command(
                _make_event(101),
                f"{case_id} 值日条例修订 | 规范值日制度并补充请假替班 | 明确轮值、请假和替班规则 | 通过后次日生效 | 否",
            )
        )
        proposal = storage.get_case(case_id)
        assert proposal is not None
        assert proposal["phase"] == "procedural_review"
        assert proposal["title"] == "值日条例修订"
        payload = proposal.get("payload") or {}
        assert payload["purpose_and_reason"] == "规范值日制度并补充请假替班"
        assert payload["proposed_text_or_measure"] == "明确轮值、请假和替班规则"
        assert payload["correction_items"] == ""
        assert payload.get("review_due_at")
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_procedural_reject_escalation_starts_vote_after_signatures() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in range(100, 108):
            _add_member(storage, user_id)
        storage.set_role_status(
            user_id=100,
            role_code="elder",
            status="active",
            source="test_seed",
            operator_id=100,
            notes="test_seed",
        )

        async def _fake_start_case_vote(self, *, case_id: int, event, preclaimed: bool = False):
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "voting",
                    "phase": "vote",
                    "vote_started_at": datetime.now().isoformat(),
                    "vote_ends_at": (datetime.now() + timedelta(seconds=30)).isoformat(),
                },
            )
            await self.group.send_msg(f"FAKE_VOTE:{case_id}")

        manager._start_case_vote = MethodType(_fake_start_case_vote, manager)

        asyncio.run(
            manager.create_proposal_command(
                _make_event(101),
                "基础治理条例案 值日条例 | 固化值日制度 | 制定正式轮值条例 | 通过后即生效 | 否",
            )
        )
        case_id = int(storage.find_open_case_by_type("ordinary_proposal")["case_id"])

        asyncio.run(manager.review_proposal_command(_make_event(100), f"{case_id} 驳回 当前文本范围过宽，请先缩窄到值日制度本身"))
        proposal = storage.get_case(case_id)
        assert proposal is not None
        assert proposal["status"] == "supporting"
        assert proposal["phase"] == "procedurally_rejected"
        assert int(proposal["support_threshold"]) == 5

        for user_id in range(101, 106):
            asyncio.run(manager.support_case_command(_make_event(user_id), str(case_id)))

        proposal = storage.get_case(case_id)
        assert proposal is not None
        assert proposal["status"] == "voting"
        assert proposal["phase"] == "vote"
        assert group.sent_messages[-1] == f"FAKE_VOTE:{case_id}"
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_proposal_result_publication_and_review_request_are_recorded() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in range(100, 110):
            _add_member(storage, user_id)

        case_id = storage.create_case(
            case_type="ordinary_proposal",
            title="值日规则",
            description="规范值日制度",
            proposer_id=100,
            target_user_id=None,
            status="voting",
            phase="vote",
            support_threshold=0,
            vote_duration_seconds=12 * 3600,
            payload={
                "proposal_type": "ordinary_proposal",
                "proposal_type_label": "普通议题案",
                "purpose_and_reason": "规范值日制度",
                "proposed_text_or_measure": "每周轮值并公开补位规则",
                "effective_time_or_expiry": "通过后次日生效",
                "high_risk_power_requested": False,
                "submitted_at": datetime.now().isoformat(),
                "discussion_opened_at": (datetime.now() - timedelta(hours=13)).isoformat(),
                "discussion_closes_at": (datetime.now() - timedelta(hours=1)).isoformat(),
                "threshold_set": "ordinary_proposal",
                "review_requests": [],
            },
        )

        result_text = asyncio.run(
            manager._finalize_proposal_vote(
                case_id=case_id,
                case=storage.get_case(case_id),
                tallies={1: 4, 2: 2, 3: 1},
                voter_count=7,
            )
        )
        assert "赞成：4 票" in result_text
        assert "弃权：1 票" in result_text
        assert "表决结果已在群内公示" in result_text

        proposal = storage.get_case(case_id)
        assert proposal is not None
        assert proposal["status"] == "approved"
        assert proposal["phase"] == "closed"
        payload = proposal.get("payload") or {}
        assert payload["public_summary_ref"] == f"proposal_case:{case_id}:public_summary"
        assert payload["law_version_snapshot"]
        assert payload["non_retroactivity_boundary_notice"]
        assert payload["tally"]["abstain"] == 1

        asyncio.run(manager.request_proposal_review_command(_make_event(108), f"{case_id} 结果公告里应补充程序说明"))
        proposal = storage.get_case(case_id)
        assert proposal is not None
        review_requests = (proposal.get("payload") or {}).get("review_requests") or []
        assert len(review_requests) == 1
        assert review_requests[0]["requester_id"] == 108
        audit_row = _latest_audit_event(db, "proposal_review_requested")
        assert audit_row is not None
        context = json.loads(audit_row[2] or "{}")
        assert context["case_type"] == "ordinary_proposal"
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
