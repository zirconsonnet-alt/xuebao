from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml


LAW_SPEC_RELATIVE_PATH = Path("laws") / "laws.spec.v0.yaml"
LAW_FALLBACK_SOURCE_RELATIVE_PATH = Path("laws") / "laws.md"

IMPLEMENTED_GOVERNANCE_CASE_TYPES = (
    "ordinary_proposal",
    "honor_owner_election",
    "elder_election",
    "honor_owner_impeachment",
    "elder_impeachment",
    "elder_reboot",
    "daily_management",
    "emergency_protection",
    "formal_discipline",
    "formal_discipline_review",
)

CASE_TYPE_LABELS = {
    "ordinary_proposal": "提案/立规",
    "honor_owner_election": "荣誉群主选举",
    "elder_election": "元老选举",
    "honor_owner_impeachment": "荣誉群主弹劾",
    "elder_impeachment": "元老弹劾",
    "elder_reboot": "重组元老会",
    "daily_management": "日常管理",
    "emergency_protection": "紧急防护",
    "formal_discipline": "正式处分",
    "formal_discipline_review": "处分复核",
}

GOVERNANCE_DEFAULT_CONFIG = {
    "governance_law_effective_at": "",
    "governance_nomination_publicity_hours": 24,
    "governance_questioning_hours": 12,
    "governance_impeachment_response_hours": 12,
    "governance_formal_acceptance_hours": 48,
    "governance_formal_notice_dm_hours": 6,
    "governance_formal_notice_offgroup_hours": 12,
    "governance_formal_defense_hours": 12,
    "governance_formal_severe_defense_hours": 24,
    "governance_formal_review_start_hours": 48,
    "governance_formal_default_long_mute_days": 7,
    "governance_formal_default_restrict_days": 30,
    "governance_vote_duration_seconds": 300,
    "governance_elder_impeach_ratio": 0.1,
    "governance_reboot_supporters": 7,
    "governance_reboot_cooldown_hours": 12,
    "governance_reboot_approval_ratio": 2 / 3,
    "governance_emergency_supporters": 5,
    "governance_default_ban_minutes": 60,
    "governance_max_ban_minutes": 1440,
}


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_law_spec_path() -> Path:
    return get_repo_root() / LAW_SPEC_RELATIVE_PATH


@lru_cache(maxsize=1)
def load_law_spec() -> Dict[str, Any]:
    spec_path = get_law_spec_path()
    if not spec_path.exists():
        return {}
    payload = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _iter_source_path_candidates(raw_source_path: Any) -> tuple[Path, ...]:
    repo_root = get_repo_root()
    candidates: list[Path] = []
    if raw_source_path:
        normalized = str(raw_source_path).replace("\\", "/").strip()
        if normalized:
            candidates.append(repo_root / normalized)
            candidates.append(repo_root / "laws" / Path(normalized).name)
    candidates.append(repo_root / LAW_FALLBACK_SOURCE_RELATIVE_PATH)
    return tuple(candidates)


def get_law_source_path() -> Path:
    source_of_truth = load_law_spec().get("meta", {}).get("source_of_truth", {})
    raw_source_path = source_of_truth.get("file") if isinstance(source_of_truth, dict) else None
    for candidate in _iter_source_path_candidates(raw_source_path):
        if candidate.exists():
            return candidate
    return get_repo_root() / LAW_FALLBACK_SOURCE_RELATIVE_PATH


def get_law_template_dir() -> Path:
    return get_law_source_path().parent


def get_supported_workflow_specs() -> Dict[str, Dict[str, Any]]:
    workflow_fsm = load_law_spec().get("workflow_fsm") or {}
    if not isinstance(workflow_fsm, dict):
        return {}
    supported: Dict[str, Dict[str, Any]] = {}
    for case_type in IMPLEMENTED_GOVERNANCE_CASE_TYPES:
        case_spec = workflow_fsm.get(case_type)
        if isinstance(case_spec, dict):
            supported[case_type] = case_spec
    return supported


__all__ = [
    "CASE_TYPE_LABELS",
    "GOVERNANCE_DEFAULT_CONFIG",
    "IMPLEMENTED_GOVERNANCE_CASE_TYPES",
    "LAW_FALLBACK_SOURCE_RELATIVE_PATH",
    "LAW_SPEC_RELATIVE_PATH",
    "get_law_source_path",
    "get_law_spec_path",
    "get_law_template_dir",
    "get_repo_root",
    "get_supported_workflow_specs",
    "load_law_spec",
]
