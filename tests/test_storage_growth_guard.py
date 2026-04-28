import os
from pathlib import Path
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support import storage_guard


def _write(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _make_old(path: Path, *, days: int = 8) -> None:
    old_time = time.time() - days * 24 * 60 * 60
    os.utime(path, (old_time, old_time))


def test_storage_review_reports_required_growth_categories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / ".venv" / "lib" / "site.py", b"venv")
    _write(tmp_path / "logs" / "bot.log", b"log")
    _write(tmp_path / "docker" / "layer.bin", b"docker")
    _write(tmp_path / "cache" / "nonebot_plugin_chatrecorder" / "record.bin", b"chat")
    _write(tmp_path / "data" / "bot.sqlite", b"db")
    _write(tmp_path / "cache" / "unknown_plugin" / "blob.bin", b"unknown")

    review = storage_guard.review_storage_growth("test")
    reports = review.by_key()

    assert set(reports) >= {
        "venv",
        "host_logs",
        "docker_artifacts",
        "chatrecorder_cache",
        "database_files",
        "other_plugin_caches",
    }
    assert reports["venv"].safety_class == storage_guard.StorageSafetyClass.PROTECTED
    assert reports["host_logs"].safety_class == storage_guard.StorageSafetyClass.MANUAL_ACTION
    assert reports["docker_artifacts"].safety_class == storage_guard.StorageSafetyClass.MANUAL_ACTION
    assert reports["chatrecorder_cache"].safety_class == storage_guard.StorageSafetyClass.PROTECTED
    assert reports["database_files"].safety_class == storage_guard.StorageSafetyClass.PROTECTED
    assert reports["other_plugin_caches"].safety_class == storage_guard.StorageSafetyClass.UNCLASSIFIED
    assert reports["other_plugin_caches"].total_bytes == len(b"unknown")
    assert any("其他插件缓存" in warning and "未分类" in warning for warning in review.warnings)


def test_storage_review_keeps_unknown_plugin_cache_report_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    unknown_file = _write(tmp_path / "cache" / "another_plugin" / "cache.bin", b"cache")

    review = storage_guard.run_storage_guard("test")

    assert unknown_file.exists()
    report = review.by_key()["other_plugin_caches"]
    assert report.safety_class == storage_guard.StorageSafetyClass.UNCLASSIFIED
    assert report.total_bytes == len(b"cache")


def test_run_storage_guard_cleans_only_explicit_safe_plugin_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    safe_root = tmp_path / "cache" / "safe_plugin"
    old_file = _write(safe_root / "old.bin", b"old")
    fresh_file = _write(safe_root / "fresh.bin", b"fresh")
    _make_old(old_file)
    monkeypatch.setenv(storage_guard.SAFE_PLUGIN_CACHE_ROOTS_ENV, str(safe_root))

    review = storage_guard.run_storage_guard("test")
    safe_report = review.by_key()["safe_plugin_cache:safe_plugin"]

    assert not old_file.exists()
    assert fresh_file.exists()
    assert safe_report.cleanup_result is not None
    assert safe_report.cleanup_result.deleted_files == 1
    assert safe_report.safety_class == storage_guard.StorageSafetyClass.AUTO_CLEANUP


def test_run_storage_guard_never_deletes_protected_categories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    protected_files = [
        _write(tmp_path / ".venv" / "lib" / "site.py", b"venv"),
        _write(tmp_path / "cache" / "nonebot_plugin_chatrecorder" / "record.bin", b"chat"),
        _write(tmp_path / "data" / "bot.db", b"db"),
    ]
    for path in protected_files:
        _make_old(path)

    review = storage_guard.run_storage_guard("test")

    assert all(path.exists() for path in protected_files)
    assert review.by_key()["venv"].safety_class == storage_guard.StorageSafetyClass.PROTECTED
    assert review.by_key()["database_files"].safety_class == storage_guard.StorageSafetyClass.PROTECTED
    assert review.by_key()["chatrecorder_cache"].safety_class == storage_guard.StorageSafetyClass.PROTECTED


def test_optional_write_decision_blocks_low_free_disk(monkeypatch) -> None:
    monkeypatch.setenv(storage_guard.MIN_FREE_BYTES_ENV, "100")
    monkeypatch.setenv(storage_guard.MIN_FREE_RATIO_ENV, "0")
    monkeypatch.setattr(storage_guard, "_disk_usage", lambda target_path=None: (90, 1000))

    decision = storage_guard.ensure_optional_write_allowed("测试写入", expected_bytes=1)

    assert decision.allowed is False
    assert decision.reason == "free_below_threshold"
    assert "测试写入" in decision.message


def test_optional_write_decision_blocks_expected_write_over_reserve(monkeypatch) -> None:
    monkeypatch.setenv(storage_guard.MIN_FREE_BYTES_ENV, "100")
    monkeypatch.setenv(storage_guard.MIN_FREE_RATIO_ENV, "0")
    monkeypatch.setattr(storage_guard, "_disk_usage", lambda target_path=None: (150, 1000))

    allowed = storage_guard.ensure_optional_write_allowed("测试写入", expected_bytes=20)
    blocked = storage_guard.ensure_optional_write_allowed("测试写入", expected_bytes=60)

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.reason == "expected_write_exceeds_safe_reserve"
