"""AI 助手配置运行时。"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.support.ai import ApiSpeechGenerator, LocalSpeechGenerator, config, get_llm_models_to_try, get_upstream_context
from src.support.core import TTSType
from src.support.db import AIAssistantStateDatabase

from .common import Character, DEFAULT_CHARACTERS, _get_assistant_config_db


def _get_legacy_ai_config_backup_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.legacy_backup{path.suffix}")


def _archive_legacy_ai_config_file(path: Path) -> None:
    if not path.exists():
        return

    backup_path = _get_legacy_ai_config_backup_path(path)
    try:
        if backup_path.exists():
            backup_path.unlink()
        path.replace(backup_path)
    except Exception:
        return


def _load_legacy_ai_config_dict(path: Path) -> Dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        print(f"加载配置失败: {exc}")
        return None
    return data if isinstance(data, dict) else None


def migrate_legacy_ai_assistant_config_file(
    *,
    db: AIAssistantStateDatabase,
    scope_type: str,
    scope_id: int,
    config_path: Path | str,
) -> bool:
    legacy_path = Path(config_path)
    if not legacy_path.exists():
        return False

    existing_config = db.get_config(scope_type, int(scope_id))
    if existing_config is None:
        legacy_config = _load_legacy_ai_config_dict(legacy_path)
        if legacy_config is None:
            return False
        db.upsert_config(scope_type, int(scope_id), legacy_config)

    _archive_legacy_ai_config_file(legacy_path)
    return True


def migrate_all_legacy_ai_assistant_configs(data_dir: Path | str = Path("data") / "ai_assistant") -> int:
    root_path = Path(data_dir)
    if not root_path.exists():
        return 0

    migrated_count = 0
    db = AIAssistantStateDatabase(db_path=root_path / "assistant_state.db")
    try:
        for config_path in sorted(root_path.glob("*.json")):
            stem = config_path.stem
            if stem.endswith(".legacy_backup"):
                continue

            scope_type, separator, raw_scope_id = stem.partition("_")
            if separator != "_" or scope_type not in {"group", "private"}:
                continue
            try:
                scope_id = int(raw_scope_id)
            except ValueError:
                continue

            if migrate_legacy_ai_assistant_config_file(
                db=db,
                scope_type=scope_type,
                scope_id=scope_id,
                config_path=config_path,
            ):
                migrated_count += 1
    finally:
        db.close()
    return migrated_count


class AIAssistantConfigRuntimeMixin:
    def _migrate_legacy_config_file_to_db(self) -> bool:
        return migrate_legacy_ai_assistant_config_file(
            db=_get_assistant_config_db(),
            scope_type=self.server_type,
            scope_id=self.server_id,
            config_path=self.config_path,
        )

    def _load_config(self) -> Dict[str, Any]:
        default_config = {
            "voice_enable": True,
            "music_enable": True,
            "tools_enable": True,
            "tarot_enable": True,
            "memes_enable": False,
            "rate_limit_enable": True,
            "thinking_enable": False,
            "model": config.model,
            "temperature": config.default_temperature,
            "black_list": [],
            "current_character": "雪豹",
            "custom_characters": [],
            "nickname": None,
        }
        self._migrate_legacy_config_file_to_db()
        data = _get_assistant_config_db().get_config(self.server_type, self.server_id)
        if data is None:
            data = {}
        if data:
            default_config.update(data)
        allowed_models = set(get_llm_models_to_try())
        current_model = default_config.get("model")
        if current_model not in allowed_models:
            default_config["model"] = config.model
        self._save_config(default_config)
        return default_config

    def _save_config(self, cfg: Dict[str, Any] = None):
        if cfg is None:
            cfg = self._config
        _get_assistant_config_db().upsert_config(self.server_type, self.server_id, cfg)

    def _init_characters(self):
        for character in DEFAULT_CHARACTERS:
            self.character_dict[character.name] = character
        for char_data in self._config.get("custom_characters", []):
            try:
                character = Character.from_dict(char_data)
                self.character_dict[character.name] = character
            except Exception as exc:
                print(f"加载自定义角色失败: {exc}")

    def _init_client(self) -> OpenAI:
        return get_upstream_context(config.model).client

    def _get_client_for_model(self, model: str) -> OpenAI:
        return get_upstream_context(model).client

    def _update_speech_generator(self):
        if self.character and self.character.tts_type:
            if self.character.tts_type == TTSType.API:
                self.speech_generator = ApiSpeechGenerator()
            elif self.character.tts_type == TTSType.LOCAL:
                self.speech_generator = LocalSpeechGenerator()
            else:
                self.speech_generator = None
        else:
            self.speech_generator = None

    @property
    def voice_enable(self) -> bool:
        return self._config.get("voice_enable", True)

    @voice_enable.setter
    def voice_enable(self, value: bool):
        self._config["voice_enable"] = value
        self._save_config()

    @property
    def music_enable(self) -> bool:
        return self._config.get("music_enable", True)

    @music_enable.setter
    def music_enable(self, value: bool):
        self._config["music_enable"] = value
        self._save_config()

    @property
    def model(self) -> str:
        return self._config.get("model", config.model)

    @model.setter
    def model(self, value: str):
        self._config["model"] = value
        self._save_config()

    @property
    def temperature(self) -> float:
        return self._config.get("temperature", 1)

    @temperature.setter
    def temperature(self, value: float):
        self._config["temperature"] = value
        self._save_config()

    @property
    def black_list(self) -> List[int]:
        return self._config.get("black_list", [])

    @black_list.setter
    def black_list(self, value: List[int]):
        self._config["black_list"] = value
        self._save_config()

    @property
    def tools_enable(self) -> bool:
        return self._config.get("tools_enable", True)

    @tools_enable.setter
    def tools_enable(self, value: bool):
        self._config["tools_enable"] = value
        self._save_config()

    @property
    def tarot_enable(self) -> bool:
        return self._config.get("tarot_enable", True)

    @tarot_enable.setter
    def tarot_enable(self, value: bool):
        self._config["tarot_enable"] = value
        self._save_config()

    @property
    def memes_enable(self) -> bool:
        return self._config.get("memes_enable", False)

    @memes_enable.setter
    def memes_enable(self, value: bool):
        self._config["memes_enable"] = value
        self._save_config()

    @property
    def rate_limit_enable(self) -> bool:
        return self._config.get("rate_limit_enable", True)

    @rate_limit_enable.setter
    def rate_limit_enable(self, value: bool):
        self._config["rate_limit_enable"] = value
        self._save_config()

    @property
    def thinking_enable(self) -> bool:
        return self._config.get("thinking_enable", False)

    @thinking_enable.setter
    def thinking_enable(self, value: bool):
        self._config["thinking_enable"] = value
        self._save_config()

    @property
    def nickname(self) -> Optional[str]:
        return self._config.get("nickname")

    @nickname.setter
    def nickname(self, value: Optional[str]):
        self._config["nickname"] = value
        self._save_config()

    def add_to_blacklist(self, user_id: int) -> tuple[bool, str]:
        blacklist = self.black_list
        if user_id in blacklist:
            return False, "用户已在黑名单中"
        blacklist.append(user_id)
        self.black_list = blacklist
        return True, "已加入黑名单"

    def remove_from_blacklist(self, user_id: int) -> tuple[bool, str]:
        blacklist = self.black_list
        if user_id not in blacklist:
            return False, "用户不在黑名单中"
        blacklist.remove(user_id)
        self.black_list = blacklist
        return True, "已移出黑名单"

    def _get_service_manager(self):
        try:
            from src.services.registry import service_manager

            return service_manager
        except ImportError:
            return None

    def get_character_names(self) -> List[str]:
        return list(self.character_dict.keys())

    def add_custom_character(self, character: Character) -> bool:
        if character.name in self.character_dict:
            return False
        self.character_dict[character.name] = character
        custom_chars = self._config.get("custom_characters", [])
        custom_chars.append(character.to_dict())
        self._config["custom_characters"] = custom_chars
        self._save_config()
        return True

    def remove_custom_character(self, name: str) -> bool:
        if name not in self.character_dict:
            return False
        character = self.character_dict[name]
        if not character.is_custom:
            return False
        del self.character_dict[name]
        custom_chars = self._config.get("custom_characters", [])
        self._config["custom_characters"] = [item for item in custom_chars if item["name"] != name]
        self._save_config()
        return True

    def get_custom_characters(self) -> List[Character]:
        return [character for character in self.character_dict.values() if character.is_custom]


