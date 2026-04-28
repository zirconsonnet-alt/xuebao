from pathlib import Path
import sys
import os

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.support.api as support_module


def test_resolve_workdir_rejects_missing_dir(tmp_path: Path):
    missing_dir = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="工作目录不存在"):
        support_module._resolve_workdir(str(missing_dir))


def test_resolve_command_keeps_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    monkeypatch.setattr(
        support_module,
        "_resolve_executable",
        lambda raw_executable: str(workdir / f"{raw_executable}.exe"),
    )
    cfg = support_module.CodexBridgeConfig(
        command=["codex", "--color", "never", "exec"],
        workdir=str(workdir),
    )

    command = cfg.resolve_command()

    assert command == [
        str(workdir / "codex.exe"),
        "--color",
        "never",
        "exec",
    ]


def test_resolve_executable_prefers_exe_on_windows(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    if os.name == "nt":
        resolved_exe = r"C:\Tools\codex.exe"
        mapping = {
            "codex.exe": resolved_exe,
            "codex": None,
            "codex.cmd": r"C:\Tools\codex.cmd",
            "codex.bat": None,
        }
    else:
        resolved_exe = "/usr/local/bin/codex"
        mapping = {"codex": resolved_exe}

    def fake_which(name: str):
        calls.append(name)
        return mapping.get(name)

    monkeypatch.setattr(support_module.shutil, "which", fake_which)

    resolved = support_module._resolve_executable("codex")

    assert resolved == str(Path(resolved_exe).resolve())
    if os.name == "nt":
        assert calls[0].lower() == "codex.exe"
        assert "codex.cmd" not in calls
    else:
        assert calls == ["codex"]
