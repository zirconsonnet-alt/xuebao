"""AI 支撑层配置加载。

注意：
- 运行配置文件：`config/ai_support.json`
- 密钥配置文件：`config/ai_support_secrets.json`
- 模型列表文件：`config/ai_model_chains.json`

其中“模型列表”不在本文件里定义，统一入口见 `src/support/ai/model_chains.py`。
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict

AI_CONFIG_DIR = Path("config")
AI_RUNTIME_CONFIG_PATH = AI_CONFIG_DIR / "ai_support.json"
AI_SECRETS_CONFIG_PATH = AI_CONFIG_DIR / "ai_support_secrets.json"

_RUNTIME_DEFAULTS: Dict[str, Any] = {
    "default_temperature": 1.0,
    "tool_max_rounds": 3,
    "tool_orchestrator": "langgraph",
    "mcp_servers": [],
    "max_msg_count": 40,
    "max_total_length": 32000,
    "max_single_msg_length": 4000,
    "default_rate_limit_per_hour": 3,
    "default_rate_limit_enabled": True,
    "default_rate_limit_warning": (
        "检测到聊天功能使用频率过高，\n"
        "请注意本群以编曲作曲交流为主，\n"
        "聊天功能虽有趣，也应适当使用哦！\n"
        "如果想无限制使用功能，\n"
        "请加入雪豹小窝群：{redirect_group}"
    ),
    "default_redirect_group": 1034063784,
    "tts_api_url": "http://117.50.252.57:8000",
    "tts_local_service_url": "http://127.0.0.1:3005",
    "vision_default_prompt": "请简洁描述这张图片的内容，不超过100字。",
    "image_gen_poll_interval": 2.0,
    "image_gen_max_wait": 120.0,
    "search_spider_dir": "",
    "search_keywords_csv_path": "",
    "search_result_csv_path": "",
    "data_path": "data/ai_assistant",
    "voice_path": "data/speech",
    "music_path": "data/bgm",
}

_SECRETS_DEFAULTS: Dict[str, Any] = {
    "api_key": "",
    "base_url": "https://api-inference.modelscope.cn/v1",
    "modelscope_api_key": "",
    "modelscope_base_url": "https://api-inference.modelscope.cn/v1",
    "anthropic_api_key": "",
    "anthropic_base_url": "",
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "fetch_answers_cookie": "",
}


def _normalize_base_url(url: str) -> str:
    if not url:
        return url
    lowered = url.lower()
    if "/v1" in lowered:
        return url.rstrip("/")
    return url.rstrip("/") + "/v1"


def _coerce_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def _coerce_float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
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


def _read_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception as exc:
        print(f"[AI CONFIG] 读取配置失败 {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _normalize_runtime_config(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(_RUNTIME_DEFAULTS)

    normalized["default_temperature"] = _coerce_float(data.get("default_temperature"), normalized["default_temperature"])
    normalized["tool_max_rounds"] = _coerce_int(data.get("tool_max_rounds"), normalized["tool_max_rounds"], minimum=1, maximum=8)

    tool_orchestrator = _coerce_str(data.get("tool_orchestrator"), normalized["tool_orchestrator"]).strip().lower()
    normalized["tool_orchestrator"] = tool_orchestrator if tool_orchestrator in {"internal", "langgraph"} else normalized["tool_orchestrator"]

    mcp_servers = data.get("mcp_servers")
    normalized["mcp_servers"] = mcp_servers if isinstance(mcp_servers, list) else copy.deepcopy(normalized["mcp_servers"])

    normalized["max_msg_count"] = _coerce_int(data.get("max_msg_count"), normalized["max_msg_count"], minimum=2)
    normalized["max_total_length"] = _coerce_int(data.get("max_total_length"), normalized["max_total_length"], minimum=1000)
    normalized["max_single_msg_length"] = _coerce_int(data.get("max_single_msg_length"), normalized["max_single_msg_length"], minimum=100)
    normalized["default_rate_limit_per_hour"] = _coerce_int(
        data.get("default_rate_limit_per_hour"),
        normalized["default_rate_limit_per_hour"],
        minimum=1,
    )
    normalized["default_rate_limit_enabled"] = _coerce_bool(
        data.get("default_rate_limit_enabled"),
        normalized["default_rate_limit_enabled"],
    )
    normalized["default_rate_limit_warning"] = _coerce_str(
        data.get("default_rate_limit_warning"),
        normalized["default_rate_limit_warning"],
    )
    normalized["default_redirect_group"] = _coerce_int(
        data.get("default_redirect_group"),
        normalized["default_redirect_group"],
        minimum=1,
    )
    normalized["tts_api_url"] = _coerce_str(data.get("tts_api_url"), normalized["tts_api_url"])
    normalized["tts_local_service_url"] = _coerce_str(data.get("tts_local_service_url"), normalized["tts_local_service_url"])
    normalized["vision_default_prompt"] = _coerce_str(
        data.get("vision_default_prompt"),
        normalized["vision_default_prompt"],
    )
    normalized["image_gen_poll_interval"] = _coerce_float(
        data.get("image_gen_poll_interval"),
        normalized["image_gen_poll_interval"],
        minimum=0.1,
    )
    normalized["image_gen_max_wait"] = _coerce_float(
        data.get("image_gen_max_wait"),
        normalized["image_gen_max_wait"],
        minimum=1.0,
    )
    normalized["search_spider_dir"] = _coerce_str(data.get("search_spider_dir"), normalized["search_spider_dir"])
    normalized["search_keywords_csv_path"] = _coerce_str(
        data.get("search_keywords_csv_path"),
        normalized["search_keywords_csv_path"],
    )
    normalized["search_result_csv_path"] = _coerce_str(
        data.get("search_result_csv_path"),
        normalized["search_result_csv_path"],
    )
    normalized["data_path"] = _coerce_str(data.get("data_path"), normalized["data_path"])
    normalized["voice_path"] = _coerce_str(data.get("voice_path"), normalized["voice_path"])
    normalized["music_path"] = _coerce_str(data.get("music_path"), normalized["music_path"])
    return normalized


def _normalize_secrets_config(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(_SECRETS_DEFAULTS)
    for key, default in _SECRETS_DEFAULTS.items():
        normalized[key] = _coerce_str(data.get(key), default)
    for key in ("base_url", "modelscope_base_url", "anthropic_base_url", "deepseek_base_url"):
        normalized[key] = _normalize_base_url(normalized[key])
    return normalized


def load_ai_runtime_config() -> Dict[str, Any]:
    raw = _read_json_dict(AI_RUNTIME_CONFIG_PATH)
    if not raw:
        raw = copy.deepcopy(_RUNTIME_DEFAULTS)
    normalized = _normalize_runtime_config(raw)
    if normalized != raw or not AI_RUNTIME_CONFIG_PATH.exists():
        _write_json_dict(AI_RUNTIME_CONFIG_PATH, normalized)
    return normalized


def load_ai_secrets_config() -> Dict[str, Any]:
    raw = _read_json_dict(AI_SECRETS_CONFIG_PATH)
    if not raw:
        raw = copy.deepcopy(_SECRETS_DEFAULTS)
    normalized = _normalize_secrets_config(raw)
    if normalized != raw or not AI_SECRETS_CONFIG_PATH.exists():
        _write_json_dict(AI_SECRETS_CONFIG_PATH, normalized)
    return normalized


__all__ = [
    "AI_RUNTIME_CONFIG_PATH",
    "AI_SECRETS_CONFIG_PATH",
    "load_ai_runtime_config",
    "load_ai_secrets_config",
]
