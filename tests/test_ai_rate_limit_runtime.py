import asyncio
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from nonebot.adapters.onebot.v11 import Message

from src.services._ai.ai_control_actions import AIControlActionMixin
from src.services._ai.group_reply import GroupReplyMixin


class _DummyReplyAssistant(GroupReplyMixin):
    def __init__(self):
        self.user_reply_history = {}
        self._config = {
            "rate_limit_enabled": True,
            "rate_limit_per_hour": 3,
        }


class _DummyGroup:
    def __init__(self):
        self.messages = []

    async def send_msg(self, message):
        self.messages.append(str(message))


class _DummyAIAssistant:
    def __init__(self):
        self.rate_limit_enabled = True
        self.rate_limit_per_hour = 3


class _DummyService(AIControlActionMixin):
    def __init__(self):
        self.group = _DummyGroup()
        self.rate_limit_enable = True
        self.rate_limit_per_hour = 3
        self._assistant = _DummyAIAssistant()

    def get_ai_assistant(self, event):
        return self._assistant


class _DummyEvent:
    group_id = 123
    user_id = 456


def test_group_reply_rate_limit_can_be_disabled_by_service_config() -> None:
    assistant = _DummyReplyAssistant()
    assistant.user_reply_history[123] = [1.0, 2.0, 3.0, 4.0]

    blocked = assistant._check_rate_limit(
        123,
        enabled=False,
        limit_per_hour=1,
    )

    assert blocked is False


def test_group_reply_rate_limit_uses_overridden_hourly_limit() -> None:
    assistant = _DummyReplyAssistant()
    now = time.time()
    assistant.user_reply_history[123] = [now - 30, now - 10]

    blocked = assistant._check_rate_limit(
        123,
        enabled=True,
        limit_per_hour=2,
    )

    assert blocked is True


def test_set_rate_limit_updates_value_even_when_switch_is_off() -> None:
    service = _DummyService()
    service.rate_limit_enable = False

    asyncio.run(service.set_rate_limit(_DummyEvent(), Message("5")))

    assert service.rate_limit_per_hour == 5
    assert service._assistant.rate_limit_per_hour == 5
    assert service._assistant.rate_limit_enabled is False
    assert "重新开启后才会生效" in service.group.messages[-1]


def test_toggle_rate_limit_off_disables_all_rate_limiting() -> None:
    service = _DummyService()

    asyncio.run(service.toggle_rate_limit(_DummyEvent()))

    assert service.rate_limit_enable is False
    assert service._assistant.rate_limit_enabled is False
    assert "当前不限制聊天频率" in service.group.messages[-1]
