from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.base import BaseService, config_property
import src.services.file as file_module
from src.services.file import FileService
import src.services._schedule.store as schedule_store_module
from src.services.schedule import ScheduleService
from src.support.core import Services
from src.support.db import GroupDatabase


class _DummyService(BaseService):
    service_type = Services.Chat
    default_config = {
        "enabled": False,
        "feature_x": True,
    }
    enabled = config_property("enabled")


class FakeTaskManager:
    def __init__(self):
        self.tasks = {}

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    def add_task(
        self,
        *,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool = True,
        group_id: int | None = None,
        description: str = "",
        message: str | None = None,
    ) -> bool:
        self.tasks[task_id] = {
            "type": task_type,
            "schedule": schedule,
            "callback_id": callback_id,
            "enabled": enabled,
            "group_id": group_id,
            "description": description,
        }
        if message is not None:
            self.tasks[task_id]["message"] = message
        return True

    def update_task(self, task_id: str, **kwargs) -> bool:
        if task_id not in self.tasks:
            return False
        for key, value in kwargs.items():
            if value is not None:
                self.tasks[task_id][key] = value
        return True

    def remove_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def get_tasks_by_group(self, group_id: int):
        return {
            task_id: task
            for task_id, task in self.tasks.items()
            if task.get("group_id") == group_id
        }


def _build_group(tmp_path: Path, group_id: int = 123):
    group_path = tmp_path / "group_management" / str(group_id)
    group_path.mkdir(parents=True, exist_ok=True)
    db = GroupDatabase(group_id=group_id, data_root=tmp_path)
    group = SimpleNamespace(group_id=group_id, group_path=group_path, db=db)
    return group, db


def test_base_service_state_entry_helpers(tmp_path: Path) -> None:
    group, db = _build_group(tmp_path)
    try:
        service = _DummyService(group)

        service.set_config_value("feature_x", False)
        service.update_config({"welcome_text": "你好"})
        snapshot = service.get_config_snapshot()
        snapshot["welcome_text"] = "已修改"

        service.put_state_entry("scheduler", "task_a", {"enabled": True, "schedule": "08:00"})
        service.put_state_entry("scheduler", "task_b", {"enabled": False, "schedule": "09:00"})

        assert service.get_config_value("feature_x") is False
        assert service.get_config_value("welcome_text") == "你好"
        assert service.get_config_snapshot()["welcome_text"] == "你好"
        assert service.get_state_entry("scheduler", "task_a") == {
            "enabled": True,
            "schedule": "08:00",
        }
        assert service.list_state_entries("scheduler") == {
            "task_a": {"enabled": True, "schedule": "08:00"},
            "task_b": {"enabled": False, "schedule": "09:00"},
        }

        service.delete_state_entry("scheduler", "task_b")
        assert service.get_state_entry("scheduler", "task_b") is None
    finally:
        db.conn.close()


def test_file_service_syncs_scheduler_state_to_sqlite(tmp_path: Path, monkeypatch) -> None:
    group, db = _build_group(tmp_path)
    task_manager = FakeTaskManager()
    try:
        service = FileService(group)
        monkeypatch.setattr(file_module, "get_runtime_task", task_manager.get_task)
        monkeypatch.setattr(
            file_module,
            "upsert_runtime_task",
            lambda **kwargs: task_manager.add_task(**kwargs),
        )

        service._sync_scheduler_task(
            task_name="auto_organize",
            schedule="04:30",
            callback_id="file_organize_123",
            description="自动整理群文件",
            enabled=True,
            create_if_missing=True,
        )

        assert task_manager.get_task("auto_organize_123") == {
            "type": "daily",
            "schedule": "04:30",
            "callback_id": "file_organize_123",
            "enabled": True,
            "group_id": 123,
            "description": "自动整理群文件",
        }
        assert service.get_state_entry("scheduler", "auto_organize") == {
            "task_id": "auto_organize_123",
            "task_type": "daily",
            "schedule": "04:30",
            "callback_id": "file_organize_123",
            "enabled": True,
            "group_id": 123,
            "description": "自动整理群文件",
        }
    finally:
        db.conn.close()


def test_schedule_service_syncs_task_state_and_message(tmp_path: Path, monkeypatch) -> None:
    group, db = _build_group(tmp_path)
    task_manager = FakeTaskManager()
    try:
        service = ScheduleService(group)

        def _upsert_runtime_task(**kwargs):
            task_id = kwargs["task_id"]
            payload = dict(kwargs)
            payload.pop("task_id", None)
            if task_manager.get_task(task_id):
                task_manager.update_task(task_id, **payload)
            else:
                task_manager.add_task(task_id=task_id, **payload)
            return task_manager.get_task(task_id)

        monkeypatch.setattr(
            schedule_store_module,
            "upsert_runtime_task",
            _upsert_runtime_task,
        )

        service._sync_scheduler_task(
            task_id="schedule_msg_123_喝水",
            task_type="daily",
            schedule="08:30",
            callback_id="schedule_msg_callback_123_喝水",
            enabled=True,
            description="喝水提醒: 记得喝水...",
            message="记得每隔一小时喝水",
        )

        assert task_manager.get_task("schedule_msg_123_喝水") == {
            "type": "daily",
            "schedule": "08:30",
            "callback_id": "schedule_msg_callback_123_喝水",
            "enabled": True,
            "group_id": 123,
            "description": "喝水提醒: 记得喝水...",
            "message": "记得每隔一小时喝水",
        }
        assert service.get_state_entry("scheduler", "schedule_msg_123_喝水") == {
            "task_id": "schedule_msg_123_喝水",
            "task_type": "daily",
            "schedule": "08:30",
            "callback_id": "schedule_msg_callback_123_喝水",
            "enabled": True,
            "group_id": 123,
            "description": "喝水提醒: 记得喝水...",
            "message": "记得每隔一小时喝水",
        }
    finally:
        db.conn.close()


def test_schedule_service_backfills_state_from_vendor_tasks(tmp_path: Path, monkeypatch) -> None:
    group, db = _build_group(tmp_path)
    task_manager = FakeTaskManager()
    task_manager.add_task(
        task_id="schedule_msg_123_开会",
        task_type="once",
        schedule="2026-03-15 09:00",
        callback_id="schedule_msg_callback_123_开会",
        enabled=True,
        group_id=123,
        description="开会提醒: 参加例会...",
    )
    try:
        service = ScheduleService(group)
        monkeypatch.setattr(
            schedule_store_module,
            "list_runtime_tasks_by_group",
            task_manager.get_tasks_by_group,
        )

        tasks = service._list_scheduler_tasks()

        assert "schedule_msg_123_开会" in tasks
        assert tasks["schedule_msg_123_开会"]["message"] == "参加例会"
        assert service.get_state_entry("scheduler", "schedule_msg_123_开会")["task_type"] == "once"
    finally:
        db.conn.close()
