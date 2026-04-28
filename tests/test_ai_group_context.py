import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageSegment

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.group_reply import GroupReplyMixin


class DummyReplyAssistant(GroupReplyMixin):
    CHAT_BUFFER_MAX_MESSAGES = 10
    CHAT_BUFFER_MAX_LENGTH = 1500

    def __init__(self):
        self._config = {"group_mode": True}
        self.user_reply_history = {}
        self.msg_list = []
        self._chat_buffer = []
        self._image_registry = {}
        self._image_counter = 0
        self._video_registry = {}
        self._video_counter = 0

    def add_message(self, record):
        self.msg_list.append(record)

    def _get_runtime_bot(self):
        return nonebot.get_bot()


class DummyEvent:
    def __init__(
        self,
        *,
        message_text: str = "",
        message=None,
        group_id: int = 123456,
        user_id: int = 654321,
        sender=None,
        reply=None,
    ):
        self.group_id = group_id
        self.user_id = user_id
        self.sender = sender
        self.reply = reply

        self._message = message if message is not None else Message(message_text)

    def get_message(self):
        return self._message


class DummyBot:
    def __init__(self, member_info: dict):
        self.member_info = dict(member_info)
        self.calls = 0

    async def get_group_member_info(self, *, user_id: int, group_id: int):
        self.calls += 1
        return dict(self.member_info)


def test_group_user_message_uses_sender_inline_identity_without_member_lookup(monkeypatch) -> None:
    import src.support.group as group_module

    monkeypatch.setattr(group_module, "_GROUP_MEMBER_INFO_CACHE", {})

    assistant = DummyReplyAssistant()
    bot = DummyBot(
        {
            "user_id": 654321,
            "nickname": "寻宝士",
            "card": "训豹师",
            "role": "owner",
        }
    )
    event = DummyEvent(
        message_text="雪豹我是群主或管理员吗？",
        sender=SimpleNamespace(
            user_id=654321,
            nickname="寻宝士",
            card="训豹师",
            role="owner",
        ),
    )

    monkeypatch.setattr(nonebot, "get_bot", lambda: bot)

    message_text = asyncio.run(assistant._build_user_message(event, {"group_mode": True}))

    assert bot.calls == 0
    assert "[群消息]" in message_text
    assert "发送者：训豹师" in message_text
    assert "昵称：寻宝士" in message_text
    assert "QQ：654321" in message_text
    assert "群角色：群主" in message_text
    assert "内容：雪豹我是群主或管理员吗？" in message_text


def test_group_user_message_falls_back_to_cached_member_lookup(monkeypatch) -> None:
    import src.support.group as group_module

    monkeypatch.setattr(group_module, "_GROUP_MEMBER_INFO_CACHE", {})

    assistant = DummyReplyAssistant()
    bot = DummyBot(
        {
            "user_id": 654321,
            "nickname": "寻宝士",
            "card": "训豹师",
            "role": "admin",
        }
    )
    event = DummyEvent(
        message_text="第一条消息",
        sender=SimpleNamespace(
            user_id=654321,
            nickname="",
            card="",
            role="",
        ),
        reply=SimpleNamespace(message=Message("上一条塔罗牌"), message_id=1001),
    )

    monkeypatch.setattr(nonebot, "get_bot", lambda: bot)

    first_message = asyncio.run(assistant._build_user_message(event, {"group_mode": True}))
    second_event = DummyEvent(
        message_text="第二条消息",
        sender=SimpleNamespace(
            user_id=654321,
            nickname="",
            card="",
            role="",
        ),
    )
    second_message = asyncio.run(assistant._build_user_message(second_event, {"group_mode": True}))

    assert bot.calls == 1
    assert "发送者：训豹师" in first_message
    assert "群角色：管理员" in first_message
    assert "回复内容：上一条塔罗牌" in first_message
    assert "内容：第一条消息" in first_message
    assert "发送者：训豹师" in second_message
    assert "内容：第二条消息" in second_message


def test_flush_chat_buffer_uses_structured_group_message_format() -> None:
    assistant = DummyReplyAssistant()

    assistant.buffer_chat_message(
        "训豹师",
        654321,
        "今天不艾特机器人",
        member_identity={
            "display_name": "训豹师",
            "nickname": "寻宝士",
            "user_id": 654321,
            "role_name": "管理员",
        },
    )
    assistant.flush_chat_buffer()

    assert len(assistant.msg_list) == 1
    content = assistant.msg_list[0]["content"]
    assert content.startswith("[群聊记录]")
    assert "[群消息]" in content
    assert "发送者：训豹师" in content
    assert "昵称：寻宝士" in content
    assert "QQ：654321" in content
    assert "群角色：管理员" in content
    assert "内容：今天不艾特机器人" in content


def test_group_user_message_registers_only_current_and_reply_images(monkeypatch) -> None:
    import src.support.group as group_module

    monkeypatch.setattr(group_module, "_GROUP_MEMBER_INFO_CACHE", {})

    assistant = DummyReplyAssistant()
    assigned_ids = iter(["img_001", "img_002"])
    assistant.register_image = lambda _url: next(assigned_ids)

    bot = DummyBot(
        {
            "user_id": 654321,
            "nickname": "寻宝士",
            "card": "训豹师",
            "role": "admin",
        }
    )
    event = DummyEvent(
        message=Message(
            [
                MessageSegment.text("雪豹看这个"),
                MessageSegment.image("https://example.com/current.png"),
            ]
        ),
        sender=SimpleNamespace(
            user_id=654321,
            nickname="寻宝士",
            card="训豹师",
            role="admin",
        ),
        reply=SimpleNamespace(
            message=Message([MessageSegment.image("https://example.com/reply.png")]),
            message_id=1001,
        ),
    )

    monkeypatch.setattr(nonebot, "get_bot", lambda: bot)

    message_text = asyncio.run(assistant._build_user_message(event, {"group_mode": True}))

    assert "内容：雪豹看这个 [图片:img_001]" in message_text
    assert "回复内容：[图片:img_002]" in message_text
