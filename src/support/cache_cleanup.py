"""运行时缓存清理工具。"""

from dataclasses import dataclass
import fnmatch
from pathlib import Path
import time
from typing import Iterable


BYTES_PER_MB = 1024 * 1024
RUNTIME_CACHE_CLEANUP_INTERVAL_HOURS = 6


@dataclass(frozen=True)
class CacheCleanupPolicy:
    max_age_seconds: int
    max_total_bytes: int
    patterns: tuple[str, ...] = ()


@dataclass
class CacheCleanupResult:
    scanned_files: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0
    errors: int = 0

    def merge(self, other: "CacheCleanupResult") -> None:
        self.scanned_files += other.scanned_files
        self.deleted_files += other.deleted_files
        self.deleted_bytes += other.deleted_bytes
        self.errors += other.errors


AI_MEDIA_CACHE_POLICY = CacheCleanupPolicy(
    max_age_seconds=24 * 60 * 60,
    max_total_bytes=512 * BYTES_PER_MB,
    patterns=(
        "*.mp4",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.webp",
        "*.gif",
        "*.wav",
        "*.mp3",
        "*.m4a",
        "*.ogg",
        "*.flac",
    ),
)
SPEECH_CACHE_POLICY = CacheCleanupPolicy(
    max_age_seconds=24 * 60 * 60,
    max_total_bytes=512 * BYTES_PER_MB,
    patterns=("*.mp3", "*.wav", "*.m4a", "*.ogg", "*.flac"),
)
BISON_MUSIC_CARD_AUDIO_POLICY = CacheCleanupPolicy(
    max_age_seconds=7 * 24 * 60 * 60,
    max_total_bytes=300 * BYTES_PER_MB,
    patterns=("*.mp3", "*.wav", "*.m4a", "*.ogg", "*.flac"),
)
GROUP_TEMP_POLICY = CacheCleanupPolicy(
    max_age_seconds=24 * 60 * 60,
    max_total_bytes=300 * BYTES_PER_MB,
)


def _resolve_path(path: Path | str) -> Path:
    return Path(path).resolve(strict=False)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_protected_paths(paths: Iterable[Path | str] | None) -> set[Path]:
    if not paths:
        return set()
    protected_paths: set[Path] = set()
    for path in paths:
        try:
            protected_paths.add(_resolve_path(path))
        except Exception:
            continue
    return protected_paths


def _matches_policy(path: Path, policy: CacheCleanupPolicy) -> bool:
    if not policy.patterns:
        return True
    file_name = path.name.lower()
    return any(fnmatch.fnmatch(file_name, pattern.lower()) for pattern in policy.patterns)


def _delete_file(path: Path, size: int, result: CacheCleanupResult) -> bool:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        result.errors += 1
        return False
    result.deleted_files += 1
    result.deleted_bytes += max(0, size)
    return True


def _cleanup_root(
    root: Path | str,
    policy: CacheCleanupPolicy,
    *,
    protected_paths: Iterable[Path | str] | None = None,
) -> CacheCleanupResult:
    result = CacheCleanupResult()
    root_path = Path(root)
    if not root_path.exists():
        return result

    try:
        resolved_root = _resolve_path(root_path)
    except Exception:
        result.errors += 1
        return result

    protected = _normalize_protected_paths(protected_paths)
    now = time.time()
    files: list[tuple[Path, Path, int, float]] = []

    for file_path in root_path.rglob("*"):
        if not file_path.is_file():
            continue
        if not _matches_policy(file_path, policy):
            continue

        try:
            resolved_file = _resolve_path(file_path)
        except Exception:
            result.errors += 1
            continue
        if not _is_under_root(resolved_file, resolved_root):
            continue

        try:
            stat_result = file_path.stat()
        except Exception:
            result.errors += 1
            continue

        result.scanned_files += 1
        files.append((file_path, resolved_file, int(stat_result.st_size), float(stat_result.st_mtime)))

    remaining: list[tuple[Path, Path, int, float]] = []
    cutoff = now - policy.max_age_seconds if policy.max_age_seconds > 0 else None
    for item in files:
        file_path, resolved_file, size, mtime = item
        if resolved_file in protected:
            remaining.append(item)
            continue
        if cutoff is not None and mtime < cutoff:
            if _delete_file(file_path, size, result):
                continue
        remaining.append(item)

    if policy.max_total_bytes <= 0:
        return result

    total_bytes = sum(size for _, _, size, _ in remaining)
    if total_bytes <= policy.max_total_bytes:
        return result

    for file_path, resolved_file, size, _ in sorted(remaining, key=lambda item: item[3]):
        if total_bytes <= policy.max_total_bytes:
            break
        if resolved_file in protected:
            continue
        if _delete_file(file_path, size, result):
            total_bytes -= size

    return result


def cleanup_ai_media_cache(
    *,
    protected_paths: Iterable[Path | str] | None = None,
) -> CacheCleanupResult:
    return _cleanup_root(
        Path("data") / "ai_assistant" / "media_cache",
        AI_MEDIA_CACHE_POLICY,
        protected_paths=protected_paths,
    )


def cleanup_speech_cache(
    *,
    protected_paths: Iterable[Path | str] | None = None,
) -> CacheCleanupResult:
    return _cleanup_root(
        Path("data") / "speech",
        SPEECH_CACHE_POLICY,
        protected_paths=protected_paths,
    )


def cleanup_bison_music_card_cache(
    *,
    protected_paths: Iterable[Path | str] | None = None,
) -> CacheCleanupResult:
    return _cleanup_root(
        Path("data") / "bison_music_card" / "audio",
        BISON_MUSIC_CARD_AUDIO_POLICY,
        protected_paths=protected_paths,
    )


def _iter_group_temp_roots(group_id: int | None = None) -> Iterable[Path]:
    group_root = Path("data") / "group_management"
    if group_id is not None:
        yield group_root / str(group_id) / "temp"
        return

    if not group_root.exists():
        return
    for child in group_root.iterdir():
        if not child.is_dir():
            continue
        temp_path = child / "temp"
        if temp_path.exists():
            yield temp_path


def cleanup_group_temp_cache(
    group_id: int | None = None,
    *,
    protected_paths: Iterable[Path | str] | None = None,
) -> CacheCleanupResult:
    result = CacheCleanupResult()
    for temp_root in _iter_group_temp_roots(group_id):
        result.merge(
            _cleanup_root(
                temp_root,
                GROUP_TEMP_POLICY,
                protected_paths=protected_paths,
            )
        )
    return result


def cleanup_runtime_caches() -> dict[str, CacheCleanupResult]:
    return {
        "ai_media": cleanup_ai_media_cache(),
        "speech": cleanup_speech_cache(),
        "bison_music_card": cleanup_bison_music_card_cache(),
        "group_temp": cleanup_group_temp_cache(),
    }


def summarize_cleanup_results(results: dict[str, CacheCleanupResult]) -> str:
    deleted_files = sum(result.deleted_files for result in results.values())
    deleted_bytes = sum(result.deleted_bytes for result in results.values())
    errors = sum(result.errors for result in results.values())
    deleted_mb = deleted_bytes / BYTES_PER_MB
    return f"删除 {deleted_files} 个文件，释放 {deleted_mb:.2f} MB，错误 {errors} 个"
