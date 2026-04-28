#!/usr/bin/env python3
import argparse
import ast
import fnmatch
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    rule_id: str
    imported: str
    message: str


def _is_python_file(path: Path) -> bool:
    return path.is_file() and path.suffix == ".py"


def _iter_python_files(root: Path) -> Iterator[Path]:
    src_dir = root / "src"
    if not src_dir.exists():
        return

    excluded_dirs = {
        "__pycache__",
        ".venv",
        ".idea",
        ".git",
    }

    for path in src_dir.rglob("*.py"):
        if any(part in excluded_dirs for part in path.parts):
            continue
        if "src" in path.parts:
            try:
                idx = path.parts.index("src")
            except ValueError:
                idx = -1
            if idx != -1 and len(path.parts) > idx + 1 and path.parts[idx + 1] == "vendors":
                continue
        yield path


def _module_from_import(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        # Return first; caller will handle multiple aliases separately.
        return None
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


def _iter_imported_modules(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            yield node.lineno, node.module


def _path_to_layer(rel_path: Path) -> str | None:
    # rel_path is expected under src/
    parts = rel_path.parts
    if not parts:
        return None
    top = parts[0]
    if top in {"interfaces", "application", "domain", "infrastructure"}:
        return top
    return None


def _match_any(patterns: Sequence[str], value: str) -> bool:
    return any(fnmatch.fnmatch(value, pat) for pat in patterns)


def check_layer_imports(
    *,
    root: Path,
    allowlist: Sequence[str] = (),
) -> list[Violation]:
    violations: list[Violation] = []

    denied_framework_roots = {"nonebot", "aiohttp", "httpx", "openai"}
    denied_framework_prefixes = tuple(f"{x}." for x in denied_framework_roots)

    for file_path in _iter_python_files(root):
        rel = file_path.relative_to(root / "src")
        layer = _path_to_layer(rel)
        if layer is None:
            continue

        try:
            content = file_path.read_text(encoding="utf-8-sig")
            tree = ast.parse(content, filename=str(file_path))
        except (OSError, SyntaxError) as exc:
            violations.append(
                Violation(
                    file=file_path,
                    line=1,
                    rule_id="E000",
                    imported="",
                    message=f"无法解析文件（{exc.__class__.__name__}）: {exc}",
                )
            )
            continue

        for lineno, imported in _iter_imported_modules(tree):
            if allowlist and _match_any(allowlist, str(file_path).replace("\\", "/")):
                continue

            if layer == "interfaces" and imported.startswith("src.infrastructure"):
                violations.append(
                    Violation(
                        file=file_path,
                        line=lineno,
                        rule_id="E101",
                        imported=imported,
                        message="interfaces 层禁止直接依赖 infrastructure 层（应通过 application.ports 间接使用）",
                    )
                )

            if layer == "application" and (
                imported.startswith("src.interfaces") or imported.startswith("src.infrastructure")
            ):
                violations.append(
                    Violation(
                        file=file_path,
                        line=lineno,
                        rule_id="E201",
                        imported=imported,
                        message="application 层禁止依赖 interfaces/infrastructure 层（应仅依赖 domain 与 ports 契约）",
                    )
                )

            if layer == "domain":
                if imported in denied_framework_roots or imported.startswith(denied_framework_prefixes):
                    violations.append(
                        Violation(
                            file=file_path,
                            line=lineno,
                            rule_id="E301",
                            imported=imported,
                            message="domain 层禁止依赖外部框架/网络库（应通过 ports 抽象）",
                        )
                    )

    return violations


def _format_violation(v: Violation) -> str:
    file_display = str(v.file).replace("\\", "/")
    imported = v.imported or "-"
    return f"{file_display}:{v.line} 违反规则: {v.rule_id} -> {imported} | {v.message}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 src/ 下分层依赖的非法 import（CI-ready）")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="仓库根目录（默认：脚本上两级目录）",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="允许的文件路径 glob（可重复；匹配到则跳过该文件的检查）",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = check_layer_imports(root=root, allowlist=tuple(args.allow))

    if violations:
        for v in violations:
            print(_format_violation(v), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
