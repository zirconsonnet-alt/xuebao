from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.core import Services
from src.support.scheduled_tasks import (
    build_scheduler_state_record,
)


def test_build_scheduler_state_record_for_schedule_task_extracts_full_message() -> None:
    record = build_scheduler_state_record(
        "schedule_msg_123_开会",
        {
            "type": "once",
            "schedule": "2026-03-15 09:00",
            "callback_id": "schedule_msg_callback_123_开会",
            "enabled": True,
            "group_id": 123,
            "description": "开会提醒: 参加例会...",
        },
    )

    assert record is not None
    group_id, service_name, entry_key, payload = record
    assert group_id == 123
    assert service_name == Services.Schedule.value
    assert entry_key == "schedule_msg_123_开会"
    assert payload["message"] == "参加例会"
