from typing import Any, Dict, TypedDict


SCHEDULE_STATE_SCOPE = "scheduler"
SCHEDULE_TASK_PREFIX = "schedule_msg_"
SCHEDULE_CALLBACK_PREFIX = "schedule_msg_callback_"
SCHEDULE_TOOL_TASK_PREFIX = "scheduled_tool_"
SCHEDULE_TOOL_CALLBACK_PREFIX = "scheduled_tool_callback_"
TASK_TYPE_NAMES = {
    "daily": "每天",
    "weekly": "每周",
    "once": "一次性",
}


class ScheduleTaskState(TypedDict):
    task_id: str
    task_type: str
    schedule: str
    callback_id: str
    enabled: bool
    group_id: int
    description: str
    message: str


class ScheduledToolJobState(TypedDict, total=False):
    job_id: str
    task_id: str
    callback_id: str
    task_name: str
    task_kind: str
    task_type: str
    schedule: str
    enabled: bool
    group_id: int
    creator_user_id: int
    tool_name: str
    tool_args: Dict[str, Any]
    context_snapshot: Dict[str, Any]
    description: str
    delivery_mode: str
    risk_level: str
    last_run_at: str
    last_status: str
