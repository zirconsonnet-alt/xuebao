from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.db import GroupDatabase


def test_nested_connection_context_rolls_back_atomically(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=456, data_root=tmp_path)
    try:
        try:
            with db.conn:
                db.conn.execute("INSERT INTO members (member_id) VALUES (?)", (101,))
                with db.conn:
                    db.conn.execute("INSERT INTO members (member_id) VALUES (?)", (202,))
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        with db.conn:
            cursor = db.conn.execute(
                "SELECT COUNT(*) FROM members WHERE member_id IN (?, ?)",
                (101, 202),
            )
            assert cursor.fetchone()[0] == 0
    finally:
        db.conn.close()


def test_group_database_connection_sets_busy_timeout_and_wal(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=789, data_root=tmp_path)
    try:
        with db.conn:
            busy_timeout = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert busy_timeout == 10000
        assert str(journal_mode).lower() == "wal"
    finally:
        db.conn.close()


def test_group_database_rejects_illegal_mutable_fields(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=999, data_root=tmp_path)
    try:
        try:
            db.update_activity_field(1, "status = 'ended'", "active")
            raise AssertionError("expected ValueError for illegal activity field")
        except ValueError:
            pass

        try:
            db.update_application_field(1, "status = 1", 0)
            raise AssertionError("expected ValueError for illegal application field")
        except ValueError:
            pass
    finally:
        db.conn.close()
