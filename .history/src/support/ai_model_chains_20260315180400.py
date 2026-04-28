"""AI 模型链条配置。"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from .ai_config import AI_CONFIG_DIR, load_ai_runtime_config

AI_MODEL_CHAINS_CONFIG_PATH = AI_CONFIG_DIR / "ai_model_chains.json"

_MODEL_CHAIN_DEFAULTS: Dict[str, List[str]] = {
    "llm_models": [
        "deepseek-ai/DeepSeek-V3.2",
        "ZhipuAI/GLM-5",
        "MiniMax/MiniMax-M2.5",
        "deepseek-chat",
    ],
    "vision_models": [
        "moonshotai/Kimi-K2.5",
    ],
    "image_generation_models": [
        "Tongyi-MAI/Z-Image-Turbo",
        "Qwen/Qwen-Image-2512",
        "MusePublic/489_ckpt_FLUX_1"
    ],
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


def _load_legacy_model_chains() -> Dict[str, Any]:
    runtime_config = load_ai_runtime_config()
    llm_models = _dedupe_models(
        [
            str(runtime_config.get("model") or "").strip(),
            *_MODEL_CHAIN_DEFAULTS["llm_models"][1:],
        ]
    )
    vision_models = _dedupe_models(
        [
            str(runtime_config.get("vision_model") or "").strip(),
            *_MODEL_CHAIN_DEFAULTS["vision_models"][1:],
        ]
    )
    image_generation_models = _dedupe_models(
        [
            str(runtime_config.get("image_gen_model") or "").strip(),
            *_MODEL_CHAIN_DEFAULTS["image_generation_models"][1:],
        ]
    )
    return {
        "llm_models": llm_models or copy.deepcopy(_MODEL_CHAIN_DEFAULTS["llm_models"]),
        "vision_models": vision_models or copy.deepcopy(_MODEL_CHAIN_DEFAULTS["vision_models"]),
        "image_generation_models": image_generation_models or copy.deepcopy(_MODEL_CHAIN_DEFAULTS["image_generation_models"]),
    }


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
        raw = _load_legacy_model_chains()
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
    "get_image_generation_model_chain",
    "get_llm_model_chain",
    "get_vision_model_chain",
    "load_ai_model_chains",
]
