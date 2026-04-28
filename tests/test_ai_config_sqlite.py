import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.services.ai as ai_module
from src.services._ai.config_runtime import migrate_all_legacy_ai_assistant_configs
from src.support.db import AIAssistantStateDatabase


class _DummyAssistant(ai_module.AIAssistantConfigRuntimeMixin):
    def __init__(self, *, server_type: str, server_id: int, config_path: Path):
        self.server_type = server_type
        self.server_id = server_id
        self.config_path = config_path


def test_ai_assistant_config_migrates_to_sqlite(tmp_path: Path, monkeypatch) -> None:
    db = AIAssistantStateDatabase(db_path=tmp_path / "assistant_state.db")
    monkeypatch.setattr(ai_module, "_assistant_config_db", db)

    legacy_path = tmp_path / "group_456.json"
    legacy_path.write_text(
        json.dumps(
            {
                "voice_enable": False,
                "nickname": "旧昵称",
                "model": ai_module.config.model,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        assistant = _DummyAssistant(server_type="group", server_id=456, config_path=legacy_path)
        cfg = assistant._load_config()
        assistant._config = cfg
        assert cfg["voice_enable"] is False
        assert cfg["nickname"] == "旧昵称"

        assistant.voice_enable = True
        assistant.nickname = "新昵称"

        legacy_path.write_text(
            json.dumps({"voice_enable": False, "nickname": "过时值"}, ensure_ascii=False),
            encoding="utf-8",
        )
        reloaded = _DummyAssistant(server_type="group", server_id=456, config_path=legacy_path)
        reloaded_cfg = reloaded._load_config()
        assert reloaded_cfg["voice_enable"] is True
        assert reloaded_cfg["nickname"] == "新昵称"
    finally:
        db.close()


def test_migrate_all_legacy_ai_assistant_configs_moves_files_and_archives_json(tmp_path: Path) -> None:
    data_dir = tmp_path / "ai_assistant"
    data_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = data_dir / "group_456.json"
    legacy_path.write_text(
        json.dumps(
            {
                "voice_enable": False,
                "nickname": "旧昵称",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    migrated = migrate_all_legacy_ai_assistant_configs(data_dir)
    db = AIAssistantStateDatabase(db_path=data_dir / "assistant_state.db")
    backup_path = data_dir / "group_456.legacy_backup.json"
    try:
        assert migrated == 1
        assert not legacy_path.exists()
        assert backup_path.exists()
        assert db.get_config("group", 456) == {"voice_enable": False, "nickname": "旧昵称"}
    finally:
        db.close()
