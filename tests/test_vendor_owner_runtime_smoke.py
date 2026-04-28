import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vendor_registry import iter_vendor_owner_modules


def test_import_bot_does_not_skip_vendor_owner_modules() -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.run(
        [sys.executable, "-c", "import bot; print('BOT_IMPORT_OK')"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=env,
    )

    output = f"{process.stdout}\n{process.stderr}"

    assert process.returncode == 0, output
    assert "BOT_IMPORT_OK" in output

    skipped_owner_modules = [
        module_name
        for module_name in iter_vendor_owner_modules()
        if f"[src.services] 跳过模块 {module_name}:" in output
    ]

    assert skipped_owner_modules == [], output
