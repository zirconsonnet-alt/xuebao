import json
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.base import BaseService, config_property, migrate_all_legacy_service_configs
from src.support.core import Services
from src.support.db import GroupDatabase


class _DummyService(BaseService):
    service_type = Services.AI
    default_config = {
        "enabled": False,
        "feature_x": True,
    }
    enabled = config_property("enabled")


def _build_group(tmp_path: Path):
    group_path = tmp_path / "group_management" / "123"
    group_path.mkdir(parents=True, exist_ok=True)
    db = GroupDatabase(group_id=123, data_root=tmp_path)
    group = SimpleNamespace(group_path=group_path, db=db)
    return group, db


def test_base_service_migrates_legacy_json_to_sqlite(tmp_path: Path) -> None:
    group, db = _build_group(tmp_path)
    legacy_path = group.group_path / "AI_service.json"
    legacy_path.write_text(
        json.dumps({"enabled": True, "feature_x": False}, ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        service = _DummyService(group)
        assert service.enabled is True
        assert service._config["feature_x"] is False

        stored = db.get_service_config("ai")
        assert stored is not None
        assert stored["enabled"] is True
        assert stored["feature_x"] is False

        legacy_path.write_text(
            json.dumps({"enabled": False, "feature_x": True}, ensure_ascii=False),
            encoding="utf-8",
        )
        service.enabled = False

        reloaded = _DummyService(group)
        assert reloaded.enabled is False
        assert reloaded._config["feature_x"] is False
    finally:
        db.conn.close()


def test_migrate_all_legacy_service_configs_moves_known_files_and_archives_legacy_json(tmp_path: Path) -> None:
    group_path = tmp_path / "group_management" / "123"
    group_path.mkdir(parents=True, exist_ok=True)
    legacy_path = group_path / "AI_service.json"
    legacy_path.write_text(
        json.dumps({"enabled": True, "feature_x": False}, ensure_ascii=False),
        encoding="utf-8",
    )

    migrated = migrate_all_legacy_service_configs(tmp_path)
    db = GroupDatabase(group_id=123, data_root=tmp_path)
    backup_path = group_path / "AI_service.legacy_backup.json"
    try:
        assert migrated == 1
        assert not legacy_path.exists()
        assert backup_path.exists()
        assert db.get_service_config("ai") == {"enabled": True, "feature_x": False}
    finally:
        db.conn.close()
