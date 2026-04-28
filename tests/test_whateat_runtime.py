import asyncio
import importlib
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_ensure_recommendation_files_syncs_when_resource_dir_is_empty(monkeypatch) -> None:
    import bot  # noqa: F401

    whateat_module = importlib.import_module("src.services.whateat")

    state = {"list_calls": 0, "sync_calls": 0}

    def _fake_list_image_names(path: Path) -> list[str]:
        state["list_calls"] += 1
        if state["list_calls"] == 1:
            return []
        return ["咖喱饭.jpg"]

    async def _fake_sync_whateat_resources() -> dict[str, int]:
        state["sync_calls"] += 1
        return {"downloaded": 1, "existing": 0, "failed": 0}

    monkeypatch.setattr(whateat_module, "_list_image_names", _fake_list_image_names)
    monkeypatch.setattr(whateat_module, "_sync_whateat_resources", _fake_sync_whateat_resources)
    monkeypatch.setattr(whateat_module, "_eat_path", lambda: Path("dummy_eat_path"))

    result = asyncio.run(whateat_module._ensure_recommendation_files("eat"))

    assert result == ["咖喱饭.jpg"]
    assert state["sync_calls"] == 1
