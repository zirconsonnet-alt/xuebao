import ast
import importlib
from pathlib import Path
import sys
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vendor_registry import (
    VENDOR_PLUGIN_OWNERS,
    iter_vendor_plugin_dirs,
    validate_vendor_plugin_ownership,
)


FORBIDDEN_ROOT_CALLS = {
    "get_driver().on_startup",
    "load_plugin",
    "on_command",
    "on_message",
    "on_notice",
    "on_regex",
    "on_request",
    "require",
    "scheduler.add_job",
}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        prefix = _call_name(node.func)
        return f"{prefix}()" if prefix else ""
    return ""


def test_vendor_registry_matches_importable_vendor_dirs() -> None:
    validate_vendor_plugin_ownership()
    assert tuple(sorted(VENDOR_PLUGIN_OWNERS)) == iter_vendor_plugin_dirs(REPO_ROOT / "src" / "vendors")


def test_each_vendor_has_unique_service_owner_file() -> None:
    owner_modules = [owner.owner_module for owner in VENDOR_PLUGIN_OWNERS.values()]
    owner_files = [owner.owner_file for owner in VENDOR_PLUGIN_OWNERS.values()]

    assert len(owner_modules) == len(set(owner_modules))
    assert len(owner_files) == len(set(owner_files))

    for owner in VENDOR_PLUGIN_OWNERS.values():
        assert owner.owner_module.startswith("src.services.")
        assert (REPO_ROOT / owner.owner_file).exists()


def test_vendor_root_init_files_are_metadata_only() -> None:
    violations: list[str] = []

    for path in sorted((REPO_ROOT / "src" / "vendors").glob("*/__init__.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(REPO_ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.append(f"{relative}: 不允许普通 import")
                continue

            if isinstance(node, ast.ImportFrom):
                imported = tuple(alias.name for alias in node.names)
                if node.level != 0 or node.module != "nonebot.plugin" or imported != ("PluginMetadata",):
                    violations.append(f"{relative}: 不允许 from {'.' * node.level}{node.module or ''} import {imported}")
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                violations.append(f"{relative}: 不允许定义 {node.__class__.__name__}")
                continue

            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if call_name == "PluginMetadata":
                    continue
                if call_name in FORBIDDEN_ROOT_CALLS:
                    violations.append(f"{relative}: 不允许调用 {call_name}")

        top_level_types = {
            ast.Expr,
            ast.ImportFrom,
            ast.Assign,
            ast.AnnAssign,
        }
        for node in tree.body:
            if type(node) not in top_level_types:
                violations.append(f"{relative}: 顶层仅允许文档字符串、PluginMetadata 导入和变量赋值")

    assert violations == []


def test_bison_owner_module_is_import_safe() -> None:
    module = importlib.import_module("src.services.bison")
    assert callable(module.activate_owned_vendor)
    assert module._RUNTIME_ACTIVATED is False


def test_resolver_owner_module_is_import_safe() -> None:
    module = importlib.import_module("src.services.resolver")
    assert callable(module.activate_owned_vendor)
    assert module._RUNTIME_ACTIVATED is False


def test_resolver_hard_dependency_is_declared_in_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["tool"]["poetry"]["dependencies"]

    assert dependencies["bilibili-api-python"] == "^17.4.1"
    assert dependencies["PyExecJS"] == "^1.5.1"
    assert dependencies["aiofiles"] == "^24.1.0"
    assert dependencies["yt-dlp"] == "^2026.3.13"


def test_resolver_prerequisite_check_aggregates_missing_dependencies(monkeypatch) -> None:
    resolver_module = importlib.import_module("src.services.resolver")
    real_import_module = importlib.import_module

    def _fake_import_module(name: str, package=None):
        if name in {"execjs", "yt_dlp"}:
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    monkeypatch.setattr(resolver_module.importlib, "import_module", _fake_import_module)
    monkeypatch.setattr(resolver_module.shutil, "which", lambda command: None)
    monkeypatch.setattr(resolver_module, "_PREREQUISITES_VALIDATED", False)

    with pytest.raises(RuntimeError) as exc_info:
        resolver_module.validate_resolver_runtime_prerequisites()

    error_message = str(exc_info.value)
    assert "PyExecJS" in error_message
    assert "yt-dlp" in error_message
    assert "ffmpeg" in error_message
