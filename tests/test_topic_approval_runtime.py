import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vote import ApproveTopicAndRefreshNoticeUseCase
from src.support.db import GroupDatabase, SqliteMemberStatsRepository, SqliteTopicRepository


class _FailingGateway:
    async def get_notice(self, group_id: int):
        return []

    async def del_notice(self, group_id: int, notice_id: int):
        return None

    async def send_notice(self, group_id: int, msg):
        raise RuntimeError("gateway unavailable")


def _topic_actions(db: GroupDatabase, topic_id: int) -> list[str]:
    with db.conn:
        cursor = db.conn.execute(
            """SELECT action
            FROM engagement_events
            WHERE domain_type = 'topic' AND subject_id = ?
            ORDER BY event_id ASC""",
            (str(topic_id),),
        )
        return [row[0] for row in cursor.fetchall()]


def test_topic_supporters_are_recorded_before_notice_side_effects(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=77, data_root=tmp_path)
    use_case = ApproveTopicAndRefreshNoticeUseCase(
        topic_repo=SqliteTopicRepository(db),
        member_stats_repo=SqliteMemberStatsRepository(db),
        group_gateway=_FailingGateway(),
    )

    try:
        try:
            asyncio.run(
                use_case.execute(
                    group_id=77,
                    proposer_id=1001,
                    content="多办试听会",
                    joiners=[2001, 2002],
                )
            )
            raise AssertionError("expected notice gateway failure")
        except RuntimeError:
            pass

        with db.conn:
            cursor = db.conn.execute(
                "SELECT topic_id FROM topics WHERE proposer_id = ? ORDER BY topic_id DESC LIMIT 1",
                (1001,),
            )
            row = cursor.fetchone()
        assert row is not None
        topic_id = int(row[0])

        assert _topic_actions(db, topic_id) == ["created", "participated", "participated"]
        stats_2001 = db.get_member_stats(2001)
        stats_2002 = db.get_member_stats(2002)
        assert stats_2001["voted_topics"] == 1
        assert stats_2002["voted_topics"] == 1
    finally:
        db.conn.close()
