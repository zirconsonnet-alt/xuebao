from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


FORBIDDEN_PATTERNS = (
    "from src.vendors.nonebot_plugin_reminder import",
    "from src.vendors.nonebot_plugin_reminder.reminder import",
    "from nonebot_plugin_reminder import",
    "scheduled_task_manager",
    "register_scheduled_callback",
    "unregister_scheduled_callback",
    "get_scheduled_callback",
)


def test_src_only_scheduler_adapter_and_vendor_may_touch_scheduler_runtime() -> None:
    src_root = REPO_ROOT / "src"
    allowlisted = {
        REPO_ROOT / "src" / "support" / "scheduled_tasks.py",
    }
    vendor_root = REPO_ROOT / "src" / "vendors" / "nonebot_plugin_reminder"
    targets = [
        path
        for path in src_root.rglob("*.py")
        if path not in allowlisted and vendor_root not in path.parents and path != vendor_root
    ]

    offenders = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} -> {pattern}")

    assert offenders == []
