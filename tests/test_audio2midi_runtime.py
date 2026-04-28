import asyncio
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def test_audio2midi_tool_returns_clear_failure_when_dependency_unavailable(monkeypatch) -> None:
    import bot  # noqa: F401

    audio2midi_module = importlib.import_module("src.services.audio2midi")
    service_cls = audio2midi_module.Audio2MidiService

    service = service_cls.__new__(service_cls)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    monkeypatch.setattr(audio2midi_module, "_AUDIO2MIDI_AVAILABLE", False)
    monkeypatch.setattr(audio2midi_module, "_AUDIO2MIDI_IMPORT_ERROR", "No module named 'audio2midi'")

    result = asyncio.run(service.transcribe_tool(user_id=456, group_id=123))

    assert result["success"] is False
    assert "依赖不可用" in result["message"]
    assert "audio2midi" in result["message"]
