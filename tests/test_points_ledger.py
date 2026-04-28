from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.db import GroupDatabase


def test_points_ledger_idempotency_and_balances(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=123, data_root=tmp_path)
    try:
        assert (
            db.get_balance(user_id=42, currency="points") == 0
        ), "No records should return 0 balance"
        assert (
            db.get_balance(user_id=42, currency="honor") == 0
        ), "No records should return 0 balance"

        assert (
            db.insert_ledger(
                user_id=42,
                currency="points",
                delta=1,
                reason="test",
                ref_type="topic",
                ref_id="t1",
                idempotency_key="k1",
            )
            is True
        )
        assert (
            db.insert_ledger(
                user_id=42,
                currency="points",
                delta=1,
                reason="test",
                ref_type="topic",
                ref_id="t1",
                idempotency_key="k1",
            )
            is False
        ), "Same idempotency_key must not double-insert"

        assert (
            db.insert_ledger(
                user_id=42,
                currency="points",
                delta=2,
                reason="test",
                idempotency_key="k2",
            )
            is True
        )
        assert (
            db.insert_ledger(
                user_id=42,
                currency="points",
                delta=-5,
                reason="test",
                idempotency_key="k3",
            )
            is True
        )
        assert (
            db.insert_ledger(
                user_id=42,
                currency="honor",
                delta=1,
                reason="test",
                idempotency_key="k4",
            )
            is True
        )

        assert db.get_balance(user_id=42, currency="points") == (1 + 2 - 5)
        assert db.get_balance(user_id=42, currency="honor") == 1
    finally:
        db.conn.close()
