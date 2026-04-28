import asyncio
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.dialog_runtime import AIAssistantDialogRuntimeMixin
from src.support.core import ServerType


class DummyDialogRuntime(AIAssistantDialogRuntimeMixin):
    def __init__(self):
        self.server_id = 123456
        self.server_type = ServerType.GROUP.value
        self.voice_enable = False
        self.music_enable = False
        self.character = None
        self.speech_generator = None


def test_send_text_records_group_output(monkeypatch) -> None:
    runtime = DummyDialogRuntime()
    captured = {}

    class DummyTextMessage:
        async def send(self, **kwargs):
            captured["send_kwargs"] = kwargs
            return {"message_id": 10086}

    class DummyUniMessage:
        @staticmethod
        def text(message: str):
            captured["text"] = message
            return DummyTextMessage()

    import src.services._ai.dialog_runtime as dialog_runtime_module
    import src.services._ai.message_bridge as message_bridge_module

    monkeypatch.setattr(dialog_runtime_module, "UniMessage", DummyUniMessage)
    monkeypatch.setattr(
        message_bridge_module,
        "record_group_output",
        lambda group_id, message, **kwargs: captured.update(
            {
                "group_id": group_id,
                "bridge_message": message,
                "bridge_result": kwargs.get("message_result"),
            }
        ),
    )

    asyncio.run(runtime.send_text("测试即时文本"))

    assert captured["text"] == "测试即时文本"
    assert captured["group_id"] == 123456
    assert captured["bridge_message"] == "测试即时文本"
    assert captured["bridge_result"] == {"message_id": 10086}


def test_send_audio_records_group_audio_output_with_transcript(monkeypatch) -> None:
    runtime = DummyDialogRuntime()
    captured = {}

    class DummyAudioMessage:
        async def send(self, **kwargs):
            captured["send_kwargs"] = kwargs
            return {"message_id": 20001}

    class DummyUniMessage:
        @staticmethod
        def audio(path: str):
            captured["audio_path"] = path
            return DummyAudioMessage()

    import src.services._ai.dialog_runtime as dialog_runtime_module
    import src.services._ai.message_bridge as message_bridge_module

    monkeypatch.setattr(dialog_runtime_module, "UniMessage", DummyUniMessage)
    monkeypatch.setattr(
        message_bridge_module,
        "record_group_media_output",
        lambda group_id, **kwargs: captured.update(
            {
                "group_id": group_id,
                "bridge_text": kwargs.get("text"),
                "bridge_markers": kwargs.get("markers"),
                "bridge_result": kwargs.get("message_result"),
            }
        ),
    )

    asyncio.run(runtime.send_audio("demo.wav", transcript="这是语音内容"))

    assert captured["audio_path"] == "demo.wav"
    assert captured["group_id"] == 123456
    assert captured["bridge_text"] == "这是语音内容"
    assert captured["bridge_markers"] == ["[语音]"]
    assert captured["bridge_result"] == {"message_id": 20001}
