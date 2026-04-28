import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.support.ai as ai_module


class _DummySpeechGenerator(ai_module.SpeechGenerator):
    async def text_to_speech(self, text, voice_id):
        return ""


def test_local_speech_generator_uses_unique_output_paths(tmp_path: Path, monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str):
            self.text = text
            self.voice = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(f"{self.voice}:{self.text}".encode("utf-8"))

    monkeypatch.setattr(ai_module.edge_tts, "Communicate", FakeCommunicate)

    generator = ai_module.LocalSpeechGenerator()
    generator.voice_path = tmp_path / "speech"

    first_path = Path(asyncio.run(generator.text_to_speech("你好", "voice-a")))
    second_path = Path(asyncio.run(generator.text_to_speech("你好", "voice-a")))

    assert first_path != second_path
    assert first_path.exists()
    assert second_path.exists()


def test_mix_music_uses_exec_with_unique_output(tmp_path: Path, monkeypatch) -> None:
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        Path(args[-1]).write_bytes(b"merged")
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    generator = _DummySpeechGenerator()
    generator.voice_path = tmp_path / "speech"
    generator.music_path = tmp_path / "bgm"
    generator.music_path.mkdir(parents=True, exist_ok=True)

    speech_path = generator._new_voice_file_path("speech")
    speech_path.write_bytes(b"speech")
    music_path = generator.music_path / "bgm.mp3"
    music_path.write_bytes(b"music")

    output_path = Path(asyncio.run(generator.mix_music(str(speech_path))))

    assert calls
    assert calls[0][0][0] == "ffmpeg"
    assert output_path.exists()
    assert output_path.name != "merged_output.mp3"


def test_api_speech_generator_returns_empty_when_segments_fail(tmp_path: Path, monkeypatch) -> None:
    generator = ai_module.ApiSpeechGenerator()
    generator.voice_path = tmp_path / "speech"

    async def fake_call_api(text: str, model_name: str, index: int, *, request_id: str) -> str:
        return ""

    monkeypatch.setattr(generator, "call_api", fake_call_api)

    result = asyncio.run(generator.text_to_speech("你好，世界", "voice-a"))
    assert result == ""


def test_api_speech_generator_preserves_absolute_audio_url_and_query() -> None:
    generator = ai_module.ApiSpeechGenerator()
    generator.url = "http://127.0.0.1:8000"

    resolved = generator._resolve_audio_download_url(
        "https://cdn.example.com/audio/file.wav?token=abc123"
    )

    assert resolved == "https://cdn.example.com/audio/file.wav?token=abc123"


def test_local_speech_generator_refuses_before_creating_output_dir(tmp_path: Path, monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str):
            raise AssertionError("低磁盘时不应创建语音任务")

    monkeypatch.setattr(ai_module.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(
        ai_module,
        "ensure_optional_write_allowed",
        lambda *args, **kwargs: SimpleNamespace(allowed=False, message="磁盘不足"),
    )

    generator = ai_module.LocalSpeechGenerator()
    generator.voice_path = tmp_path / "speech"

    result = asyncio.run(generator.gen_speech("你好", "voice-a"))

    assert result is None
    assert not generator.voice_path.exists()
