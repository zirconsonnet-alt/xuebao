from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vote import AwardHonorForTopicVoteUseCase
from src.support.db import GroupDatabase


def _count_honor_awards(db, *, topic_id: int) -> int:
    cursor = db.conn.execute(
        """SELECT COUNT(*)
        FROM points_ledger
        WHERE currency = 'honor'
          AND reason = 'topic_vote_participation'
          AND ref_type = 'topic'
          AND ref_id = ?""",
        (str(topic_id),),
    )
    return int(cursor.fetchone()[0])


def test_award_honor_is_idempotent_per_topic_user(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=2, data_root=tmp_path)
    try:
        uc = AwardHonorForTopicVoteUseCase(honor_per_vote=1)
        now = datetime(2026, 2, 6, 10, 0, 0)

        r1 = uc.execute(
            db=db,
            group_id=2,
            user_id=42,
            topic_id=123,
            choice=1,
            now=now,
        )
        assert r1.awarded is True
        assert r1.honor_balance == 1
        assert _count_honor_awards(db, topic_id=123) == 1

        r2 = uc.execute(
            db=db,
            group_id=2,
            user_id=42,
            topic_id=123,
            choice=2,
            now=now,
        )
        assert r2.awarded is False
        assert r2.honor_balance == 1
        assert _count_honor_awards(db, topic_id=123) == 1

        r3 = uc.execute(
            db=db,
            group_id=2,
            user_id=99,
            topic_id=123,
            choice=1,
            now=now,
        )
        assert r3.awarded is True
        assert r3.honor_balance == 1
        assert _count_honor_awards(db, topic_id=123) == 2
    finally:
        db.conn.close()
