"""存储增长巡检与可选大文件写入保护。"""

from dataclasses import dataclass
from enum import Enum
import fnmatch
import os
from pathlib import Path
import shutil
import time
from typing import Iterable

from src.support.cache_cleanup import (
    BYTES_PER_MB,
    CacheCleanupPolicy,
    CacheCleanupResult,
    cleanup_cache_root,
    cleanup_runtime_caches,
    summarize_cleanup_results,
)


MIN_FREE_BYTES_ENV = "STORAGE_GUARD_MIN_FREE_BYTES"
MIN_FREE_RATIO_ENV = "STORAGE_GUARD_MIN_FREE_RATIO"
HOST_LOG_ROOTS_ENV = "STORAGE_GUARD_HOST_LOG_ROOTS"
DOCKER_ROOTS_ENV = "STORAGE_GUARD_DOCKER_ROOTS"
SAFE_PLUGIN_CACHE_ROOTS_ENV = "STORAGE_GUARD_SAFE_PLUGIN_CACHE_ROOTS"

DEFAULT_MIN_FREE_BYTES = 128 * BYTES_PER_MB
DEFAULT_MIN_FREE_RATIO = 0.0
SAFE_PLUGIN_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
SAFE_PLUGIN_CACHE_MAX_TOTAL_BYTES = 300 * BYTES_PER_MB

DATABASE_PATTERNS = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.db-shm",
    "*.db-wal",
    "*.sqlite-shm",
    "*.sqlite-wal",
    "*.sqlite3-shm",
    "*.sqlite3-wal",
)


class StorageSafetyClass(str, Enum):
    AUTO_CLEANUP = "auto_cleanup"
    EXPLICIT_POLICY = "explicit_policy"
    MANUAL_ACTION = "manual_action"
    PROTECTED = "protected"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class StorageAction:
    category_key: str
    action: str
    path: str
    files_affected: int = 0
    bytes_affected: int = 0


@dataclass(frozen=True)
class StorageCategoryDefinition:
    key: str
    label: str
    roots: tuple[Path, ...]
    safety_class: StorageSafetyClass
    owner: str
    recommended_action: str
    retention_seconds: int | None = None
    max_total_bytes: int | None = None
    patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "roots", tuple(Path(root) for root in self.roots))
        object.__setattr__(self, "patterns", tuple(self.patterns or ()))
        if self.safety_class != StorageSafetyClass.AUTO_CLEANUP:
            return
        if self.retention_seconds is None or self.max_total_bytes is None:
            raise ValueError(f"{self.key} 自动清理类别缺少保留期或容量上限")
        if self.retention_seconds < 0 or self.max_total_bytes < 0:
            raise ValueError(f"{self.key} 自动清理策略不能为负数")


@dataclass(frozen=True)
class StorageCategoryReport:
    definition: StorageCategoryDefinition
    root_paths: tuple[str, ...]
    exists: bool
    total_bytes: int
    file_count: int
    errors: int = 0
    risk_level: str = "ok"
    cleanup_result: CacheCleanupResult | None = None

    @property
    def key(self) -> str:
        return self.definition.key

    @property
    def safety_class(self) -> StorageSafetyClass:
        return self.definition.safety_class


@dataclass(frozen=True)
class StorageReview:
    reason: str
    categories: tuple[StorageCategoryReport, ...]
    warnings: tuple[str, ...]
    free_bytes: int
    total_bytes: int
    min_free_bytes: int
    min_free_ratio: float
    created_at: float

    @property
    def low_disk(self) -> bool:
        return _is_low_disk(
            free_bytes=self.free_bytes,
            total_bytes=self.total_bytes,
            min_free_bytes=self.min_free_bytes,
            min_free_ratio=self.min_free_ratio,
        )

    def by_key(self) -> dict[str, StorageCategoryReport]:
        return {report.key: report for report in self.categories}


@dataclass(frozen=True)
class DiskGuardDecision:
    allowed: bool
    operation: str
    target_path: str | None
    free_bytes: int
    total_bytes: int
    min_free_bytes: int
    min_free_ratio: float
    expected_bytes: int | None = None
    reason: str = "ok"
    message: str = ""
    degraded: bool = False


def _format_bytes(size: int | float) -> str:
    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return max(0, int(str(raw_value).strip()))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return max(0.0, float(str(raw_value).strip()))
    except ValueError:
        return default


def _thresholds() -> tuple[int, float]:
    return (
        _env_int(MIN_FREE_BYTES_ENV, DEFAULT_MIN_FREE_BYTES),
        _env_float(MIN_FREE_RATIO_ENV, DEFAULT_MIN_FREE_RATIO),
    )


def _is_low_disk(
    *,
    free_bytes: int,
    total_bytes: int,
    min_free_bytes: int,
    min_free_ratio: float,
) -> bool:
    ratio_threshold = int(total_bytes * min_free_ratio)
    return free_bytes < max(min_free_bytes, ratio_threshold)


def _safe_reserve(total_bytes: int, min_free_bytes: int, min_free_ratio: float) -> int:
    return max(min_free_bytes, int(total_bytes * min_free_ratio))


def _split_env_paths(name: str, base_path: Path) -> tuple[Path, ...]:
    raw_value = os.getenv(name, "")
    roots: list[Path] = []
    for item in raw_value.replace(",", ";").split(";"):
        item = item.strip()
        if not item:
            continue
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = base_path / path
        roots.append(path)
    return tuple(roots)


def _resolve_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _matches_patterns(path: Path, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def _scan_file(path: Path, patterns: tuple[str, ...]) -> tuple[int, int, int]:
    if not _matches_patterns(path, patterns):
        return 0, 0, 0
    try:
        stat = path.stat()
    except OSError:
        return 0, 0, 1
    return int(stat.st_size), 1, 0


def _scan_root(root: Path, patterns: tuple[str, ...]) -> tuple[bool, int, int, int]:
    resolved_root = _resolve_path(root)
    if not resolved_root.exists():
        return False, 0, 0, 0
    if resolved_root.is_file():
        total_bytes, file_count, errors = _scan_file(resolved_root, patterns)
        return True, total_bytes, file_count, errors
    if not resolved_root.is_dir():
        return True, 0, 0, 0

    total_bytes = 0
    file_count = 0
    errors = 0
    try:
        iterator = resolved_root.rglob("*")
        for file_path in iterator:
            try:
                if not file_path.is_file():
                    continue
                resolved_file = file_path.resolve(strict=False)
                if not _is_under_root(resolved_file, resolved_root):
                    continue
                current_bytes, current_count, current_errors = _scan_file(
                    resolved_file,
                    patterns,
                )
                total_bytes += current_bytes
                file_count += current_count
                errors += current_errors
            except OSError:
                errors += 1
    except OSError:
        errors += 1
    return True, total_bytes, file_count, errors


def _scan_definition(
    definition: StorageCategoryDefinition,
    cleanup_result: CacheCleanupResult | None = None,
) -> StorageCategoryReport:
    root_paths: list[str] = []
    exists = False
    total_bytes = 0
    file_count = 0
    errors = 0

    for root in definition.roots:
        resolved_root = _resolve_path(root)
        root_paths.append(str(resolved_root))
        root_exists, root_bytes, root_files, root_errors = _scan_root(
            resolved_root,
            definition.patterns,
        )
        exists = exists or root_exists
        total_bytes += root_bytes
        file_count += root_files
        errors += root_errors

    risk_level = "ok"
    if errors:
        risk_level = "high"
    elif definition.safety_class == StorageSafetyClass.UNCLASSIFIED and exists:
        risk_level = "high"
    elif definition.safety_class in {
        StorageSafetyClass.MANUAL_ACTION,
        StorageSafetyClass.PROTECTED,
    } and total_bytes:
        risk_level = "watch"
    elif definition.safety_class == StorageSafetyClass.AUTO_CLEANUP and cleanup_result:
        if cleanup_result.errors:
            risk_level = "high"
        elif cleanup_result.deleted_files:
            risk_level = "watch"

    return StorageCategoryReport(
        definition=definition,
        root_paths=tuple(root_paths),
        exists=exists,
        total_bytes=total_bytes,
        file_count=file_count,
        errors=errors,
        risk_level=risk_level,
        cleanup_result=cleanup_result,
    )


def _discover_database_roots(base_path: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = _resolve_path(path)
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(path)

    data_root = base_path / "data"
    if data_root.exists():
        for pattern in DATABASE_PATTERNS:
            for path in data_root.rglob(pattern):
                if path.is_file():
                    add(path)
    for pattern in DATABASE_PATTERNS:
        for path in base_path.glob(pattern):
            if path.is_file():
                add(path)
    return tuple(roots)


def _same_path(left: Path, right: Path) -> bool:
    return _resolve_path(left) == _resolve_path(right)


def _discover_other_plugin_cache_roots(
    base_path: Path,
    safe_plugin_roots: Iterable[Path],
) -> tuple[Path, ...]:
    cache_root = base_path / "cache"
    if not cache_root.exists() or not cache_root.is_dir():
        return ()

    chatrecorder_root = cache_root / "nonebot_plugin_chatrecorder"
    safe_roots = tuple(_resolve_path(root) for root in safe_plugin_roots)
    roots: list[Path] = []
    try:
        for child in cache_root.iterdir():
            if not child.is_dir():
                continue
            if _same_path(child, chatrecorder_root):
                continue
            if any(_same_path(child, safe_root) for safe_root in safe_roots):
                continue
            roots.append(child)
    except OSError:
        return (cache_root,)
    return tuple(roots)


def _storage_categories(base_path: Path) -> tuple[StorageCategoryDefinition, ...]:
    safe_plugin_roots = _split_env_paths(SAFE_PLUGIN_CACHE_ROOTS_ENV, base_path)
    other_plugin_roots = _discover_other_plugin_cache_roots(base_path, safe_plugin_roots)

    definitions: list[StorageCategoryDefinition] = [
        StorageCategoryDefinition(
            key="venv",
            label="Python 虚拟环境",
            roots=(base_path / ".venv", base_path / "venv"),
            safety_class=StorageSafetyClass.PROTECTED,
            owner="python_runtime",
            recommended_action="受保护，不自动删除；如需压缩体积，请手动重建虚拟环境。",
        ),
        StorageCategoryDefinition(
            key="host_logs",
            label="主机或服务日志",
            roots=_split_env_paths(HOST_LOG_ROOTS_ENV, base_path) or (base_path / "logs",),
            safety_class=StorageSafetyClass.MANUAL_ACTION,
            owner="host",
            recommended_action="不自动删除；请在宿主机或日志服务中配置轮转。",
        ),
        StorageCategoryDefinition(
            key="docker_artifacts",
            label="Docker 镜像、卷与构建缓存",
            roots=_split_env_paths(DOCKER_ROOTS_ENV, base_path) or (base_path / ".docker", base_path / "docker"),
            safety_class=StorageSafetyClass.MANUAL_ACTION,
            owner="container_runtime",
            recommended_action="不自动删除；请使用 Docker 自带清理与卷保留策略。",
        ),
        StorageCategoryDefinition(
            key="chatrecorder_cache",
            label="nonebot_plugin_chatrecorder 缓存",
            roots=(base_path / "cache" / "nonebot_plugin_chatrecorder",),
            safety_class=StorageSafetyClass.PROTECTED,
            owner="plugin",
            recommended_action="包含消息记录缓存，不自动删除；需要单独确认插件保留策略。",
        ),
        StorageCategoryDefinition(
            key="database_files",
            label="持久化数据库文件",
            roots=_discover_database_roots(base_path),
            safety_class=StorageSafetyClass.PROTECTED,
            owner="database",
            recommended_action="数据库与 sidecar 文件受保护，不自动删除；请使用迁移、归档或数据库维护工具处理。",
        ),
        StorageCategoryDefinition(
            key="other_plugin_caches",
            label="其他插件缓存",
            roots=other_plugin_roots,
            safety_class=StorageSafetyClass.UNCLASSIFIED,
            owner="plugin",
            recommended_action="未分类，不自动删除；请登记为安全缓存或制定插件专属保留策略。",
        ),
    ]

    for root in safe_plugin_roots:
        definitions.append(
            StorageCategoryDefinition(
                key=f"safe_plugin_cache:{_resolve_path(root).name}",
                label=f"显式安全插件缓存：{_resolve_path(root).name}",
                roots=(root,),
                safety_class=StorageSafetyClass.AUTO_CLEANUP,
                owner="plugin",
                recommended_action="已按显式策略自动清理。",
                retention_seconds=SAFE_PLUGIN_CACHE_MAX_AGE_SECONDS,
                max_total_bytes=SAFE_PLUGIN_CACHE_MAX_TOTAL_BYTES,
            )
        )

    return tuple(definitions)


def _disk_usage_path(target_path: Path | str | None = None) -> Path:
    path = Path(target_path).expanduser() if target_path is not None else Path.cwd()
    if path.exists() and path.is_file():
        path = path.parent
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def _disk_usage(target_path: Path | str | None = None) -> tuple[int, int]:
    usage = shutil.disk_usage(_disk_usage_path(target_path))
    return int(usage.free), int(usage.total)


def _build_warnings(
    *,
    reports: tuple[StorageCategoryReport, ...],
    free_bytes: int,
    total_bytes: int,
    min_free_bytes: int,
    min_free_ratio: float,
    extra_warnings: Iterable[str] = (),
) -> tuple[str, ...]:
    warnings: list[str] = list(extra_warnings)
    reserve = _safe_reserve(total_bytes, min_free_bytes, min_free_ratio)
    if free_bytes < reserve:
        warnings.append(
            f"磁盘剩余空间偏低：可用 {_format_bytes(free_bytes)}，"
            f"低于安全阈值 {_format_bytes(reserve)}；可选大文件写入将被拒绝。"
        )

    for report in reports:
        definition = report.definition
        if report.errors:
            warnings.append(f"{definition.label} 扫描出现 {report.errors} 个错误，请人工确认。")

        if not report.exists and not report.total_bytes:
            continue

        size_text = _format_bytes(report.total_bytes)
        if definition.safety_class == StorageSafetyClass.PROTECTED:
            warnings.append(f"{definition.label} 当前 {size_text}，受保护，不自动删除；{definition.recommended_action}")
        elif definition.safety_class == StorageSafetyClass.MANUAL_ACTION:
            warnings.append(f"{definition.label} 当前 {size_text}，需要人工或外部工具处理；{definition.recommended_action}")
        elif definition.safety_class == StorageSafetyClass.UNCLASSIFIED:
            warnings.append(f"{definition.label} 当前 {size_text}，未分类且不会自动清理；{definition.recommended_action}")
        elif definition.safety_class == StorageSafetyClass.AUTO_CLEANUP and report.cleanup_result:
            cleanup_result = report.cleanup_result
            if cleanup_result.deleted_files or cleanup_result.errors:
                warnings.append(
                    f"{definition.label} 自动清理完成：删除 {cleanup_result.deleted_files} 个文件、"
                    f"{_format_bytes(cleanup_result.deleted_bytes)}，错误 {cleanup_result.errors} 个。"
                )

    return tuple(warnings)


def review_storage_growth(reason: str = "manual") -> StorageReview:
    base_path = Path.cwd()
    min_free_bytes, min_free_ratio = _thresholds()
    free_bytes, total_bytes = _disk_usage(base_path)
    reports = tuple(_scan_definition(definition) for definition in _storage_categories(base_path))
    warnings = _build_warnings(
        reports=reports,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        min_free_bytes=min_free_bytes,
        min_free_ratio=min_free_ratio,
    )
    return StorageReview(
        reason=reason,
        categories=reports,
        warnings=warnings,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        min_free_bytes=min_free_bytes,
        min_free_ratio=min_free_ratio,
        created_at=time.time(),
    )


def _cleanup_auto_category(definition: StorageCategoryDefinition) -> CacheCleanupResult:
    result = CacheCleanupResult()
    if definition.safety_class != StorageSafetyClass.AUTO_CLEANUP:
        return result

    policy = CacheCleanupPolicy(
        max_age_seconds=int(definition.retention_seconds or 0),
        max_total_bytes=int(definition.max_total_bytes or 0),
        patterns=definition.patterns,
    )
    for root in definition.roots:
        result.merge(cleanup_cache_root(root, policy))
    return result


def run_storage_guard(reason: str = "scheduled") -> StorageReview:
    base_path = Path.cwd()
    min_free_bytes, min_free_ratio = _thresholds()

    runtime_cleanup_warnings: list[str] = []
    runtime_results = cleanup_runtime_caches()
    if any(result.deleted_files or result.errors for result in runtime_results.values()):
        runtime_cleanup_warnings.append(f"运行时缓存清理：{summarize_cleanup_results(runtime_results)}")

    cleanup_results: dict[str, CacheCleanupResult] = {}
    definitions = _storage_categories(base_path)
    for definition in definitions:
        if definition.safety_class != StorageSafetyClass.AUTO_CLEANUP:
            continue
        cleanup_results[definition.key] = _cleanup_auto_category(definition)

    free_bytes, total_bytes = _disk_usage(base_path)
    reports = tuple(
        _scan_definition(definition, cleanup_results.get(definition.key))
        for definition in definitions
    )
    warnings = _build_warnings(
        reports=reports,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        min_free_bytes=min_free_bytes,
        min_free_ratio=min_free_ratio,
        extra_warnings=runtime_cleanup_warnings,
    )
    return StorageReview(
        reason=reason,
        categories=reports,
        warnings=warnings,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        min_free_bytes=min_free_bytes,
        min_free_ratio=min_free_ratio,
        created_at=time.time(),
    )


def format_storage_warnings(review: StorageReview) -> str:
    return "\n".join(review.warnings)


def summarize_storage_review(review: StorageReview) -> str:
    if review.warnings:
        return "；".join(review.warnings)
    return (
        f"存储巡检完成：可用 {_format_bytes(review.free_bytes)}，"
        f"分类 {len(review.categories)} 项，未发现需提示风险。"
    )


def ensure_optional_write_allowed(
    operation: str,
    target_path: Path | str | None = None,
    expected_bytes: int | None = None,
) -> DiskGuardDecision:
    min_free_bytes, min_free_ratio = _thresholds()
    free_bytes, total_bytes = _disk_usage(target_path)
    reserve = _safe_reserve(total_bytes, min_free_bytes, min_free_ratio)
    normalized_expected = None if expected_bytes is None else max(0, int(expected_bytes))
    target_text = str(target_path) if target_path is not None else None

    if free_bytes < reserve:
        return DiskGuardDecision(
            allowed=False,
            operation=operation,
            target_path=target_text,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            min_free_bytes=min_free_bytes,
            min_free_ratio=min_free_ratio,
            expected_bytes=normalized_expected,
            reason="free_below_threshold",
            message=(
                f"{operation} 已跳过：磁盘可用 {_format_bytes(free_bytes)}，"
                f"低于安全阈值 {_format_bytes(reserve)}。"
            ),
            degraded=True,
        )

    if normalized_expected is not None and free_bytes - normalized_expected < reserve:
        return DiskGuardDecision(
            allowed=False,
            operation=operation,
            target_path=target_text,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            min_free_bytes=min_free_bytes,
            min_free_ratio=min_free_ratio,
            expected_bytes=normalized_expected,
            reason="expected_write_exceeds_safe_reserve",
            message=(
                f"{operation} 已跳过：预计写入 {_format_bytes(normalized_expected)} 后，"
                f"磁盘剩余将低于安全阈值 {_format_bytes(reserve)}。"
            ),
            degraded=True,
        )

    return DiskGuardDecision(
        allowed=True,
        operation=operation,
        target_path=target_text,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        min_free_bytes=min_free_bytes,
        min_free_ratio=min_free_ratio,
        expected_bytes=normalized_expected,
        reason="ok",
        message="",
        degraded=False,
    )
