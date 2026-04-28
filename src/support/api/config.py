"""内部 API 与 Codex 桥接配置加载。

注意：
- 运行配置文件：`config/api_support.json`
- 密钥配置文件：`config/api_support_secrets.json`
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

API_CONFIG_DIR = Path("config")
API_RUNTIME_CONFIG_PATH = API_CONFIG_DIR / "api_support.json"
API_SECRETS_CONFIG_PATH = API_CONFIG_DIR / "api_support_secrets.json"

_RUNTIME_DEFAULTS: Dict[str, Any] = {
    "bot_api": {
        "sign_tolerance_seconds": 60,
        "nonce_ttl_seconds": 300,
        "session_ttl_seconds": 604800,
        "cookie_secure": True,
        "cookie_name": "session",
    },
    "codex_bridge": {
        "command": [
            "codex",
            "-a",
            "never",
            "-s",
            "workspace-write",
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
        ],
        "workdir": r"I:\Projects",
        "timeout_seconds": 1800,
        "max_concurrent_jobs": 1,
        "result_max_chars": 4000,
        "history_limit": 5,
        "allowed_user_ids": [],
        "allowed_group_ids": [],
        "at_sender_in_group": True,
    },
}

_SECRETS_DEFAULTS: Dict[str, Any] = {
    "bot_secrets": {},
}


def _coerce_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None and result < minimum:
        result = minimum
    return result


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _coerce_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _coerce_str_list(value: Any, default: List[str]) -> List[str]:
    if not isinstance(value, list):
        value = default
    result: List[str] = []
    for item in value:
        text = _coerce_str(item, "").strip()
        if text:
            result.append(text)
    return result or copy.deepcopy(default)


def _coerce_int_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    result: List[int] = []
    seen = set()
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number in seen:
            continue
        seen.add(number)
        result.append(number)
    return result


def _coerce_str_dict(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, str] = {}
    for key, item in value.items():
        key_text = _coerce_str(key, "").strip()
        value_text = _coerce_str(item, "").strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def _read_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception as exc:
        print(f"[API CONFIG] 读取配置失败 {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _normalize_runtime_config(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(_RUNTIME_DEFAULTS)

    bot_api = data.get("bot_api")
    if not isinstance(bot_api, dict):
        bot_api = {}
    bot_api_defaults = _RUNTIME_DEFAULTS["bot_api"]
    normalized["bot_api"] = {
        "sign_tolerance_seconds": _coerce_int(
            bot_api.get("sign_tolerance_seconds"),
            bot_api_defaults["sign_tolerance_seconds"],
            minimum=1,
        ),
        "nonce_ttl_seconds": _coerce_int(
            bot_api.get("nonce_ttl_seconds"),
            bot_api_defaults["nonce_ttl_seconds"],
            minimum=1,
        ),
        "session_ttl_seconds": _coerce_int(
            bot_api.get("session_ttl_seconds"),
            bot_api_defaults["session_ttl_seconds"],
            minimum=1,
        ),
        "cookie_secure": _coerce_bool(
            bot_api.get("cookie_secure"),
            bot_api_defaults["cookie_secure"],
        ),
        "cookie_name": _coerce_str(
            bot_api.get("cookie_name"),
            bot_api_defaults["cookie_name"],
        ),
    }

    codex_bridge = data.get("codex_bridge")
    if not isinstance(codex_bridge, dict):
        codex_bridge = {}
    codex_defaults = _RUNTIME_DEFAULTS["codex_bridge"]
    normalized["codex_bridge"] = {
        "command": _coerce_str_list(codex_bridge.get("command"), codex_defaults["command"]),
        "workdir": _coerce_str(codex_bridge.get("workdir"), codex_defaults["workdir"]),
        "timeout_seconds": _coerce_int(
            codex_bridge.get("timeout_seconds"),
            codex_defaults["timeout_seconds"],
            minimum=1,
        ),
        "max_concurrent_jobs": _coerce_int(
            codex_bridge.get("max_concurrent_jobs"),
            codex_defaults["max_concurrent_jobs"],
            minimum=1,
        ),
        "result_max_chars": _coerce_int(
            codex_bridge.get("result_max_chars"),
            codex_defaults["result_max_chars"],
            minimum=100,
        ),
        "history_limit": _coerce_int(
            codex_bridge.get("history_limit"),
            codex_defaults["history_limit"],
            minimum=1,
        ),
        "allowed_user_ids": _coerce_int_list(codex_bridge.get("allowed_user_ids")),
        "allowed_group_ids": _coerce_int_list(codex_bridge.get("allowed_group_ids")),
        "at_sender_in_group": _coerce_bool(
            codex_bridge.get("at_sender_in_group"),
            codex_defaults["at_sender_in_group"],
        ),
    }
    return normalized


def _normalize_secrets_config(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(_SECRETS_DEFAULTS)
    normalized["bot_secrets"] = _coerce_str_dict(data.get("bot_secrets"))
    return normalized


def load_api_runtime_config() -> Dict[str, Any]:
    raw = _read_json_dict(API_RUNTIME_CONFIG_PATH)
    if not raw:
        raw = copy.deepcopy(_RUNTIME_DEFAULTS)
    normalized = _normalize_runtime_config(raw)
    if normalized != raw or not API_RUNTIME_CONFIG_PATH.exists():
        _write_json_dict(API_RUNTIME_CONFIG_PATH, normalized)
    return normalized


def load_api_secrets_config() -> Dict[str, Any]:
    raw = _read_json_dict(API_SECRETS_CONFIG_PATH)
    if not raw:
        raw = copy.deepcopy(_SECRETS_DEFAULTS)
    normalized = _normalize_secrets_config(raw)
    if normalized != raw or not API_SECRETS_CONFIG_PATH.exists():
        _write_json_dict(API_SECRETS_CONFIG_PATH, normalized)
    return normalized


__all__ = [
    "API_RUNTIME_CONFIG_PATH",
    "API_SECRETS_CONFIG_PATH",
    "load_api_runtime_config",
    "load_api_secrets_config",
]
