import asyncio
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.tarot import TarotService


def _install_saa_stub(monkeypatch, captured: dict) -> None:
    class DummyText:
        def __init__(self, text):
            self.text = text

    class DummyImage:
        def __init__(self, payload):
            captured["image_payload"] = payload

    class DummyMessageFactory:
        def __init__(self, items):
            self.items = list(items)

        def append(self, item):
            self.items.append(item)

        async def send(self):
            captured["message_items"] = list(self.items)
            return {"message_id": 4321}

    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_saa",
        SimpleNamespace(
            Image=DummyImage,
            MessageFactory=DummyMessageFactory,
            Text=DummyText,
        ),
    )


def test_draw_tarot_core_normalizes_bytesio_before_bridge(monkeypatch) -> None:
    captured = {}
    service = object.__new__(TarotService)
    _install_saa_stub(monkeypatch, captured)

    import src.services.tarot as tarot_module
    import src.services._ai.message_bridge as bridge_module

    monkeypatch.setattr(
        tarot_module,
        "load_tarot_data",
        lambda: (
            {
                "fool": {
                    "name_cn": "愚者",
                    "meaning": {"up": "开始", "down": "犹豫"},
                    "description": ["牌义"],
                }
            },
            {"tarot_fool": "fool.jpg"},
        ),
    )
    monkeypatch.setattr(
        tarot_module,
        "random_tarot_card",
        lambda cards_dict, tarot_urls: ("愚者", "开始", "犹豫", "fool.jpg"),
    )
    monkeypatch.setattr(tarot_module, "send_image_as_bytes", lambda _path: BytesIO(b"tarot-image"))
    monkeypatch.setattr(
        bridge_module,
        "record_group_media_output",
        lambda group_id, **kwargs: captured.update({"group_id": group_id, **kwargs}) or True,
    )

    result = asyncio.run(service.draw_tarot_core(user_id=123, group_id=456))

    assert result["success"] is True
    assert captured["group_id"] == 456
    assert captured["image_payload"] == b"tarot-image"
    assert captured["image_bytes_list"] == [b"tarot-image"]
    assert captured["message_result"] == {"message_id": 4321}


def test_tarot_fortune_normalizes_bytesio_before_bridge(monkeypatch) -> None:
    captured = {}
    service = object.__new__(TarotService)
    _install_saa_stub(monkeypatch, captured)

    import src.services.tarot as tarot_module
    import src.services._ai.message_bridge as bridge_module

    monkeypatch.setattr(
        tarot_module,
        "load_tarot_data",
        lambda: (
            {
                "magician": {
                    "name_cn": "魔术师",
                    "meaning": {"up": "行动", "down": "混乱"},
                    "description": ["牌义"],
                }
            },
            {"tarot_magician": "magician.jpg"},
        ),
    )
    monkeypatch.setattr(
        tarot_module,
        "load_fortune_descriptions",
        lambda: {"81-90": ["好运连连"]},
    )
    monkeypatch.setattr(tarot_module.random, "choice", lambda items: items[0])
    monkeypatch.setattr(tarot_module.random, "randint", lambda start, end: 88)
    monkeypatch.setattr(tarot_module, "send_image_as_bytes", lambda _path: BytesIO(b"fortune-image"))
    monkeypatch.setattr(
        bridge_module,
        "record_group_media_output",
        lambda group_id, **kwargs: captured.update({"group_id": group_id, **kwargs}) or True,
    )

    result = asyncio.run(service.fortune_core(user_id=123, group_id=789))

    assert result["success"] is True
    assert captured["group_id"] == 789
    assert captured["image_payload"] == b"fortune-image"
    assert captured["image_bytes_list"] == [b"fortune-image"]
    assert captured["message_result"] == {"message_id": 4321}
