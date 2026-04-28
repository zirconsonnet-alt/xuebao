from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vote import CreateTopicAndChargeUseCase
from src.support.db import GroupDatabase


def _count_rows(db, table: str) -> int:
    cursor = db.conn.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cursor.fetchone()[0])


def test_create_topic_and_charge_insufficient_points(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=1, data_root=tmp_path)
    try:
        uc = CreateTopicAndChargeUseCase(cost_points=5)
        now = datetime(2026, 2, 6, 10, 0, 0)

        r = uc.execute(db=db, group_id=1, user_id=42, content="hello", now=now)
        assert r.created is False
        assert r.topic_id is None
        assert r.points_balance == 0
        assert _count_rows(db, "topics") == 0
        assert _count_rows(db, "points_ledger") == 0
    finally:
        db.conn.close()


def test_create_topic_and_charge_success_and_idempotent(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=1, data_root=tmp_path)
    try:
        assert db.insert_ledger(
            user_id=42,
            currency="points",
            delta=10,
            reason="seed",
            idempotency_key="seed:1",
        )

        uc = CreateTopicAndChargeUseCase(cost_points=5)
        now = datetime(2026, 2, 6, 10, 0, 0)

        r1 = uc.execute(db=db, group_id=1, user_id=42, content="topic a", now=now)
        assert r1.created is True
        assert isinstance(r1.topic_id, int)
        assert r1.points_balance == 5
        assert _count_rows(db, "topics") == 1

        r2 = uc.execute(db=db, group_id=1, user_id=42, content="topic a", now=now)
        assert r2.created is False
        assert r2.topic_id == r1.topic_id
        assert r2.points_balance == 5
        assert _count_rows(db, "topics") == 1

        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM points_ledger WHERE reason = 'topic_create_cost'"
        )
        assert int(cursor.fetchone()[0]) == 1
    finally:
        db.conn.close()
