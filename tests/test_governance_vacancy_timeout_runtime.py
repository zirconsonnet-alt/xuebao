import asyncio
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


def _add_member(storage, user_id: int, *, role: str = "member", join_days: int = 45) -> None:
    storage.upsert_member_profile(
        {
            "user_id": int(user_id),
            "nickname": f"U{user_id}",
            "card": "",
            "role": role,
            "title": "",
            "join_time": int((datetime.now() - timedelta(days=join_days)).timestamp()),
        }
    )


def _make_event(user_id: int, *, role: str = "member"):
    return SimpleNamespace(
        group_id=9527,
        user_id=int(user_id),
        self_id=114514,
        sender=SimpleNamespace(role=role),
    )


def _seed_honor_owner(storage, *, operator_id: int, user_id: int) -> None:
    storage.set_role_status(
        user_id=user_id,
        role_code="honor_owner",
        status="active",
        source="test_seed",
        operator_id=operator_id,
        notes="test_seed",
    )


def _seed_formal_case(storage, *, proposer_id: int, target_user_id: int, published_at: str) -> int:
    case_id = storage.create_case(
        case_type="formal_discipline",
        title="正式处分案件",
        description="测试正式处分复核",
        proposer_id=proposer_id,
        target_user_id=target_user_id,
        status="approved",
        phase="closed",
        support_threshold=0,
        vote_duration_seconds=300,
        payload={
            "target_member_id": target_user_id,
            "fact_summary": "测试正式处分复核",
            "requested_sanction": "long_mute",
            "current_sanction": "long_mute",
            "sanction_type": "long_mute",
            "requested_duration_seconds": 7 * 24 * 3600,
            "published_at": published_at,
            "effective_at": published_at,
            "execution_ref": "formal_case:test",
            "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
        },
    )
    storage.update_case_fields(case_id, {"resolved_at": published_at})
    return case_id


def test_designate_temporary_proxy_records_designation_and_status() -> None:
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
        for elder_id in (100, 101):
            storage.set_role_status(
                user_id=elder_id,
                role_code="elder",
                status="active",
                source="test_seed",
                operator_id=100,
                notes="test_seed",
            )

        vacancy_case_id = manager._ensure_honor_owner_by_election_case(
            operator_id=100,
            source_case_id=1,
            reopen_reason="荣誉群主空缺",
            failure_count=0,
        )

        asyncio.run(manager.designate_temporary_proxy_command(_make_event(100), "[CQ:at,qq=101] 空缺期程序代理"))

        vacancy_case = storage.get_case(vacancy_case_id)
        assert vacancy_case is not None
        payload = vacancy_case.get("payload") or {}
        assert payload.get("temporary_proxy_status") == "elder_designated_proxy"
        assert int(payload.get("temporary_proxy_user_id") or 0) == 101
        assert payload.get("temporary_proxy_expires_at")

        asyncio.run(manager.show_status(_make_event(102)))
        assert "临时程序代理：U101(QQ:101)" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_vacancy_dispute_vote_bypasses_review_and_starts_vote() -> None:
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

        vacancy_case_id = manager._ensure_honor_owner_by_election_case(
            operator_id=100,
            source_case_id=2,
            reopen_reason="两次补选流产，进入机器人临时自治",
            failure_count=2,
        )

        asyncio.run(
            manager.create_vacancy_dispute_vote_command(
                _make_event(101),
                "代理权限范围 | 当前需要明确机器人临时自治的权限边界 | 仅保留日常秩序与紧急安全处理 | 即时生效 | 否",
            )
        )

        proposal_case = storage.find_open_case_by_type("ordinary_proposal")
        assert proposal_case is not None
        proposal = storage.get_case(int(proposal_case["case_id"]))
        assert proposal is not None
        payload = proposal.get("payload") or {}
        assert payload.get("direct_collective_dispute_vote") is True
        assert int(payload.get("vacancy_case_id") or 0) == vacancy_case_id
        assert proposal["status"] == "voting"
        assert any(message.startswith("FAKE_VOTE:") for message in group.sent_messages)
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_timeout_fallback_requires_two_voting_members_when_no_elder_or_honor_owner() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in (201, 202, 203):
            _add_member(storage, user_id)

        asyncio.run(
            manager.create_proposal_command(
                _make_event(201),
                "普通议题案 超时承接测试 | 测试第三十一条两人联署触发 | 通过后进入讨论期 | 即时生效 | 否",
            )
        )
        case_id = int(storage.find_open_case_by_type("ordinary_proposal")["case_id"])
        proposal_case = storage.get_case(case_id)
        assert proposal_case is not None
        storage.update_case_fields(
            case_id,
            {
                "payload_json": manager._merge_case_payload(
                    proposal_case,
                    {
                        "review_due_at": (datetime.now() - timedelta(hours=1)).isoformat(),
                    },
                )
            },
        )

        asyncio.run(manager.advance_case_command(_make_event(201), f"{case_id}"))
        proposal_case = storage.get_case(case_id)
        assert proposal_case is not None
        payload = proposal_case.get("payload") or {}
        assert proposal_case["phase"] == "procedural_review"
        assert payload.get("timeout_pending_supporter_ids") == [201]
        assert "1/2" in group.sent_messages[-1]

        asyncio.run(manager.advance_case_command(_make_event(202), f"{case_id}"))
        proposal_case = storage.get_case(case_id)
        assert proposal_case is not None
        payload = proposal_case.get("payload") or {}
        assert proposal_case["phase"] == "discussion"
        assert payload.get("timeout_fallback_actor_stage") == "any_two_voting_members"
        assert payload.get("timeout_fallback_supporter_ids") == [201, 202]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_review_timeout_can_fall_back_to_honor_owner() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        manager = build_governance_manager(service)
        storage = manager.storage

        for user_id in (100, 200, 300):
            _add_member(storage, user_id)
        _seed_honor_owner(storage, operator_id=100, user_id=300)
        published_at = (datetime.now() - timedelta(hours=1)).isoformat()
        source_case_id = _seed_formal_case(storage, proposer_id=100, target_user_id=200, published_at=published_at)

        asyncio.run(manager.create_formal_discipline_review_command(_make_event(200), f"{source_case_id} 关键程序错误"))

        open_case = storage.find_open_case("formal_discipline_review", 200)
        assert open_case is not None
        review_case_id = int(open_case["case_id"])
        review_case = storage.get_case(review_case_id)
        assert review_case is not None
        storage.update_case_fields(
            review_case_id,
            {
                "payload_json": manager._merge_case_payload(
                    review_case,
                    {
                        "start_check_due_at": (datetime.now() - timedelta(hours=2)).isoformat(),
                    },
                )
            },
        )

        asyncio.run(manager.advance_case_command(_make_event(300), f"{review_case_id}"))

        review_case = storage.get_case(review_case_id)
        assert review_case is not None
        payload = review_case.get("payload") or {}
        assert review_case["phase"] == "reopened"
        assert payload.get("timeout_fallback_actor_stage") == "honor_owner"
        assert "荣誉群主" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
