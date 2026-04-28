import asyncio
from datetime import datetime
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


def _make_event(user_id: int, *, role: str = "member"):
    return SimpleNamespace(
        group_id=9527,
        user_id=int(user_id),
        self_id=114514,
        sender=SimpleNamespace(role=role),
    )


def _seed_formal_case(storage, *, proposer_id: int, target_user_id: int, published_at: str) -> int:
    case_id = storage.create_case(
        case_type="formal_discipline",
        title="旧正式处分案件",
        description="测试旧案适用边界",
        proposer_id=proposer_id,
        target_user_id=target_user_id,
        status="approved",
        phase="closed",
        support_threshold=0,
        vote_duration_seconds=300,
        payload={
            "target_member_id": target_user_id,
            "fact_summary": "测试旧案适用边界",
            "requested_sanction": "long_mute",
            "current_sanction": "long_mute",
            "sanction_type": "long_mute",
            "requested_duration_seconds": 7 * 24 * 3600,
            "published_at": published_at,
            "effective_at": published_at,
            "execution_ref": "formal_case:seed",
            "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
        },
    )
    storage.update_case_fields(case_id, {"resolved_at": published_at})
    return case_id


def test_show_status_reports_current_law_regime() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        service._config["governance_law_effective_at"] = "2030-01-01T00:00:00"
        manager = build_governance_manager(service)

        asyncio.run(manager.show_status(_make_event(100)))

        assert group.sent_messages
        status_text = group.sent_messages[-1]
        assert "现行法版本：群宪法及条例（建议修订稿 v2）" in status_text
        assert "现行法生效：2030-01-01 00:00" in status_text
        assert "生效前已完成程序原则上不溯及既往" in status_text
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_legacy_formal_case_is_not_reviewable_without_appendix_exception() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        service._config["governance_law_effective_at"] = "2030-01-01T00:00:00"
        manager = build_governance_manager(service)
        storage = manager.storage

        published_at = "2029-01-01T00:00:00"
        source_case_id = _seed_formal_case(storage, proposer_id=100, target_user_id=200, published_at=published_at)

        asyncio.run(manager.create_formal_discipline_review_command(_make_event(200), f"{source_case_id} 处分明显失衡"))

        assert storage.find_open_case("formal_discipline_review", 200) is None
        assert group.sent_messages
        assert "原则上不溯及既往" in group.sent_messages[-1]
        summary = manager._format_case_summary(storage.get_case(source_case_id), include_proposer=True)
        assert "适用：旧规则已完结程序（原则上不溯及既往）" in summary
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()


def test_legacy_formal_case_allows_appendix_exception_review() -> None:
    tmp = TemporaryDirectory()
    db = None
    try:
        root = Path(tmp.name)
        db = GroupDatabase(9527, root)
        group = _FakeGroup(db, root)
        service = _FakeService(group)
        service._config["governance_law_effective_at"] = "2030-01-01T00:00:00"
        manager = build_governance_manager(service)
        storage = manager.storage

        published_at = "2029-01-01T00:00:00"
        source_case_id = _seed_formal_case(storage, proposer_id=100, target_user_id=200, published_at=published_at)

        asyncio.run(
            manager.create_formal_discipline_review_command(
                _make_event(200),
                f"{source_case_id} 关键程序错误，存在重大程序违法",
            )
        )

        open_case = storage.find_open_case("formal_discipline_review", 200)
        assert open_case is not None
        review_case = storage.get_case(int(open_case["case_id"]))
        assert review_case is not None
        payload = review_case.get("payload") or {}
        assert payload.get("legacy_case_under_transition") is True
        assert payload.get("legacy_exception_requested") is True
        assert payload.get("legacy_exception_basis") == "major_procedural_illegality"
        evaluation = manager._evaluate_formal_review_request(case=review_case, source_case=storage.get_case(source_case_id))
        assert evaluation["valid"] is True
        assert group.sent_messages
        assert "适用边界：现行法生效前旧程序，按第六十九条例外复核：重大程序违法" in group.sent_messages[-1]
    finally:
        if db is not None:
            db.conn.close()
        tmp.cleanup()
