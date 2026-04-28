import json
from datetime import datetime, timedelta
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.db import GroupDatabase


def _event_actions(db: GroupDatabase, *, domain_type: str, subject_id: str) -> list[str]:
    with db.conn:
        cursor = db.conn.execute(
            """SELECT action
            FROM engagement_events
            WHERE domain_type = ? AND subject_id = ?
            ORDER BY event_id ASC""",
            (domain_type, subject_id),
        )
        return [row[0] for row in cursor.fetchall()]


def test_activity_creation_and_membership_are_persisted(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=5, data_root=tmp_path)
    try:
        application_id = db.add_application(
            {
                "creator_id": 1001,
                "activity_name": "编曲打卡",
                "requirement": "每日交作业",
                "content": "七天打卡",
                "reward": "积分",
                "duration": 3600,
            }
        )
        activity_id = db.add_activity(
            creator_id=1001,
            activity_name="编曲打卡",
            requirement="每日交作业",
            content="七天打卡",
            reward="积分",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
            status="active",
            source_application_id=application_id,
        )

        assert db.get_participants_by_activity_id(activity_id) == [1001]
        assert db.add_participant(1002, activity_id)[0] is True
        assert sorted(db.get_participants_by_activity_id(activity_id)) == [1001, 1002]
        assert db.remove_participant(1002, activity_id) is True
        assert db.get_participants_by_activity_id(activity_id) == [1001]

        activity_actions = _event_actions(db, domain_type="activity", subject_id=str(activity_id))
        assert activity_actions == ["created", "joined", "joined", "left"]

        with db.conn:
            cursor = db.conn.execute(
                """SELECT metadata_json
                FROM engagement_events
                WHERE domain_type = 'activity' AND subject_id = ? AND action = 'created'""",
                (str(activity_id),),
            )
            metadata = json.loads(cursor.fetchone()[0])
        assert metadata["source_application_id"] == application_id
    finally:
        db.conn.close()


def test_topic_creation_vote_and_supporters_are_persisted(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=6, data_root=tmp_path)
    try:
        assert db.insert_ledger(
            user_id=42,
            currency="points",
            delta=10,
            reason="seed",
            idempotency_key="seed:topic",
        )
        created, topic_id, _ = db.create_topic_and_charge(
            user_id=42,
            content="多做合奏活动",
            sign_date="2026-03-13",
            cost_points=5,
        )
        assert created is True
        assert topic_id is not None

        assert db.reserve_topic_vote(user_id=99, topic_id=topic_id, choice=2) is True
        db.record_topic_supporters(topic_id, [77, 88])

        actions = _event_actions(db, domain_type="topic", subject_id=str(topic_id))
        assert actions == ["created", "voted", "participated", "participated"]
    finally:
        db.conn.close()
