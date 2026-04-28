"""AI 模型链条配置。

重要：
- LLM 模型列表
- 视觉多模态模型列表
- 画图模型列表

统一都在 `config/ai_model_chains.json` 里维护。
如果你在代码里要找“模型列表在哪里定义”，先看这个文件。
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from .config import AI_CONFIG_DIR

AI_MODEL_CHAINS_CONFIG_PATH = AI_CONFIG_DIR / "ai_model_chains.json"
AI_MODEL_LISTS_CONFIG_PATH = AI_MODEL_CHAINS_CONFIG_PATH

_MODEL_CHAIN_DEFAULTS: Dict[str, List[str]] = {
    "llm_models": [],
    "vision_models": [],
    "image_generation_models": [],
}


def _dedupe_models(models: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for model in models:
        if not isinstance(model, str):
            continue
        value = model.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _read_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception as exc:
        print(f"[AI MODEL CHAINS] 读取配置失败 {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _normalize_model_chains(data: Dict[str, Any]) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}
    for key, default_models in _MODEL_CHAIN_DEFAULTS.items():
        raw_models = data.get(key, default_models)
        if not isinstance(raw_models, list):
            raw_models = default_models
        models = _dedupe_models(raw_models)
        normalized[key] = models or copy.deepcopy(default_models)
    return normalized


def load_ai_model_chains() -> Dict[str, List[str]]:
    raw = _read_json_dict(AI_MODEL_CHAINS_CONFIG_PATH)
    if not raw:
        raw = copy.deepcopy(_MODEL_CHAIN_DEFAULTS)
    normalized = _normalize_model_chains(raw)
    if normalized != raw or not AI_MODEL_CHAINS_CONFIG_PATH.exists():
        _write_json_dict(AI_MODEL_CHAINS_CONFIG_PATH, normalized)
    return normalized


def get_llm_model_chain(primary_model: str | None = None) -> List[str]:
    chains = load_ai_model_chains()
    models = list(chains.get("llm_models") or [])
    if primary_model and primary_model.strip():
        models = [primary_model.strip(), *models]
    return _dedupe_models(models)


def get_vision_model_chain() -> List[str]:
    chains = load_ai_model_chains()
    return _dedupe_models(list(chains.get("vision_models") or []))


def get_image_generation_model_chain() -> List[str]:
    chains = load_ai_model_chains()
    return _dedupe_models(list(chains.get("image_generation_models") or []))


__all__ = [
    "AI_MODEL_CHAINS_CONFIG_PATH",
    "AI_MODEL_LISTS_CONFIG_PATH",
    "get_image_generation_model_chain",
    "get_llm_model_chain",
    "get_vision_model_chain",
    "load_ai_model_chains",
]
