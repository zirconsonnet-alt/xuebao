from pathlib import Path

import pytest

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_layer_imports import check_layer_imports  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_layer_violations(tmp_path: Path) -> None:
    root = tmp_path

    _write(
        root / "src" / "interfaces" / "a.py",
        "import src.infrastructure.foo\n",
    )
    _write(
        root / "src" / "application" / "a.py",
        "from src.domain.model import X\n",
    )
    _write(
        root / "src" / "domain" / "a.py",
        "import httpx\n",
    )

    violations = check_layer_imports(root=root)
    rule_ids = sorted(v.rule_id for v in violations)
    assert rule_ids == ["E101", "E301"]


def test_allowlist_skips_file(tmp_path: Path) -> None:
    root = tmp_path
    bad = root / "src" / "interfaces" / "a.py"
    _write(bad, "import src.infrastructure.foo\n")

    violations = check_layer_imports(root=root, allowlist=(str(bad).replace("\\", "/"),))
    assert violations == []


def test_parse_error_is_reported(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "src" / "application" / "broken.py", "def x(:\n")

    violations = check_layer_imports(root=root)
    assert len(violations) == 1
    assert violations[0].rule_id == "E000"
