import asyncio
import importlib
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid
import types

from nonebot.adapters.onebot.v11 import Message, MessageSegment

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.base import BaseService
from src.services.base import service_action
from src.services.ai import AIAssistantManager
from src.services.base import check_enabled
from src.support.core import GetUserInfoInput, Services, ServiceBridge, ai_tool, tool_registry


def test_service_bridge_rescans_lazily_loaded_service_classes() -> None:
    bridge = ServiceBridge()
    bridge.init_service_tools()

    tool_name = f"dynamic_test_tool_{uuid.uuid4().hex}"

    class DummyDynamicService(BaseService):
        service_type = Services.Info

        @ai_tool(name=tool_name, desc="dynamic test tool")
        async def run_dynamic_tool(self, **kwargs):
            return {"success": True}

    try:
        bridge.init_service_tools()
        assert tool_name in {item["name"] for item in bridge.get_service_tools_info()}
        assert tool_registry.get_tool(tool_name) is not None
    finally:
        DummyDynamicService.service_type = None
        tool_registry.unregister(tool_name)
        bridge._service_tools.pop(tool_name, None)


def test_service_bridge_builds_mock_event_arg_and_reply_for_service_tools() -> None:
    bridge = ServiceBridge()
    bridge.init_service_tools()

    method_name = f"bridge_echo_{uuid.uuid4().hex}"
    tool_name = f"{Services.Info.value}_{method_name}"

    async def _bridge_echo(self, event, arg):
        return {
            "group_id": event.group_id,
            "user_id": event.user_id,
            "message_text": event.get_message().extract_plain_text(),
            "arg_text": arg.extract_plain_text(),
            "reply_text": event.reply.message.extract_plain_text() if event.reply else "",
            "reply_message_id": event.reply.message_id if event.reply else 0,
        }

    _bridge_echo.__name__ = method_name
    decorated = service_action(cmd="桥接回显", tool_callable=True, need_arg=True)(_bridge_echo)
    DummyBridgeService = type(
        f"DummyBridgeService_{uuid.uuid4().hex}",
        (BaseService,),
        {
            "service_type": Services.Info,
            method_name: decorated,
        },
    )

    service = DummyBridgeService.__new__(DummyBridgeService)

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            return service

    bridge.set_service_manager(DummyManager())

    try:
        bridge.init_service_tools()
        tool = tool_registry.get_tool(tool_name)
        assert tool is not None
        assert "arg_text" in tool.parameters["properties"]
        assert "reply_text" in tool.parameters["properties"]

        result = asyncio.run(
            tool_registry.execute_tool(
                tool_name,
                {
                    "arg_text": "桥接参数",
                    "reply_text": "被回复内容",
                    "reply_message_id": 321,
                },
                {
                    "group_id": 123,
                    "user_id": 456,
                    "message": "原始消息",
                    "member_role": "admin",
                },
            )
        )
        assert result["success"] is True
        assert result["data"] == {
            "group_id": 123,
            "user_id": 456,
            "message_text": "原始消息",
            "arg_text": "桥接参数",
            "reply_text": "被回复内容",
            "reply_message_id": 321,
        }
    finally:
        DummyBridgeService.service_type = None
        tool_registry.unregister(tool_name)
        bridge._service_tools.pop(tool_name, None)


def test_service_bridge_unwraps_check_enabled_service_tool_signature() -> None:
    bridge = ServiceBridge()
    bridge.init_service_tools()

    method_name = f"bridge_wrapped_{uuid.uuid4().hex}"
    tool_name = f"{Services.Info.value}_{method_name}"
    captured = {}

    @check_enabled
    async def _wrapped_tool(self, event, arg):
        captured["message_text"] = event.get_message().extract_plain_text()
        captured["arg_text"] = arg.extract_plain_text()
        return {"success": True, "message": "ok"}

    _wrapped_tool.__name__ = method_name
    decorated = service_action(cmd="包装桥接", tool_callable=True, need_arg=True)(_wrapped_tool)
    DummyWrappedService = type(
        f"DummyWrappedService_{uuid.uuid4().hex}",
        (BaseService,),
        {
            "service_type": Services.Info,
            method_name: decorated,
        },
    )

    service = DummyWrappedService.__new__(DummyWrappedService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            return service

    bridge.set_service_manager(DummyManager())

    try:
        bridge.init_service_tools()
        tool = tool_registry.get_tool(tool_name)
        assert tool is not None
        assert "arg_text" in tool.parameters["properties"]
        assert "args" not in tool.parameters["properties"]
        assert "kwargs" not in tool.parameters["properties"]

        result = asyncio.run(
            tool_registry.execute_tool(
                tool_name,
                {
                    "arg_text": "今天",
                },
                {
                    "group_id": 123,
                    "user_id": 456,
                    "message": "今日词云",
                    "member_role": "admin",
                },
            )
        )

        assert result["success"] is True
        assert captured == {"message_text": "今日词云", "arg_text": "今天"}
    finally:
        DummyWrappedService.service_type = None
        tool_registry.unregister(tool_name)
        bridge._service_tools.pop(tool_name, None)


def test_service_bridge_preserves_explicit_empty_arg_text() -> None:
    bridge = ServiceBridge()
    arg = bridge._create_mock_arg({"arg_text": ""}, {"message": "原始消息"})

    assert arg.extract_plain_text() == ""


def test_ai_assistant_manager_accepts_duck_typed_events() -> None:
    manager = object.__new__(AIAssistantManager)
    manager.get_group_server = lambda group_id: ("group", group_id)
    manager.get_private_server = lambda user_id: ("private", user_id)

    assert AIAssistantManager.get_client(manager, SimpleNamespace(group_id=321, user_id=123)) == ("group", 321)
    assert AIAssistantManager.get_client(manager, SimpleNamespace(group_id=None, user_id=123)) == ("private", 123)


def test_service_bridge_blocks_disabled_ai_tool_service() -> None:
    bridge = ServiceBridge()
    bridge.init_service_tools()

    tool_name = f"disabled_tool_{uuid.uuid4().hex}"

    class DummyDisabledService(BaseService):
        service_type = Services.Info
        default_config = {"enabled": False}

        @ai_tool(name=tool_name, desc="disabled test tool")
        async def run_disabled_tool(self, **kwargs):
            return {"success": True, "message": "should not run"}

    service = DummyDisabledService.__new__(DummyDisabledService)
    service.group = SimpleNamespace()
    service._config = {"enabled": False}

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            return service

    bridge.set_service_manager(DummyManager())

    try:
        bridge.init_service_tools()
        result = asyncio.run(
            tool_registry.execute_tool(
                tool_name,
                {},
                {
                    "group_id": 123,
                    "user_id": 456,
                    "service_manager": bridge._service_manager,
                },
            )
        )
        assert result["success"] is False
        assert result["message"] == "基础信息服务未开启，请使用【开启基础信息服务】命令"
    finally:
        DummyDisabledService.service_type = None
        tool_registry.unregister(tool_name)
        bridge._service_tools.pop(tool_name, None)


def test_service_bridge_preserves_context_user_id_when_input_model_default_is_none() -> None:
    bridge = ServiceBridge()
    bridge.init_service_tools()

    tool_name = f"context_user_tool_{uuid.uuid4().hex}"
    captured = {}

    class DummyContextAwareService(BaseService):
        service_type = Services.Info

        @ai_tool(name=tool_name, desc="context user test tool", input_model=GetUserInfoInput)
        async def run_context_user_tool(self, user_id: int, group_id: int, **kwargs):
            captured["user_id"] = user_id
            captured["group_id"] = group_id
            return {"success": True, "data": {"user_id": user_id, "group_id": group_id}}

    service = DummyContextAwareService.__new__(DummyContextAwareService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            return service

    bridge.set_service_manager(DummyManager())

    try:
        bridge.init_service_tools()
        result = asyncio.run(
            tool_registry.execute_tool(
                tool_name,
                {},
                {
                    "group_id": 123,
                    "user_id": 456,
                    "service_manager": bridge._service_manager,
                },
            )
        )

        assert result["success"] is True
        assert captured == {"user_id": 456, "group_id": 123}
        assert result["data"] == {"user_id": 456, "group_id": 123}
    finally:
        DummyContextAwareService.service_type = None
        tool_registry.unregister(tool_name)
        bridge._service_tools.pop(tool_name, None)


def test_info_service_get_user_info_merges_group_member_fields(monkeypatch) -> None:
    import bot  # noqa: F401
    import nonebot

    InfoService = importlib.import_module("src.services.info").InfoService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = InfoService.__new__(InfoService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    join_time = 1704161040
    last_sent_time = 1704248700

    class DummyBot:
        async def get_group_member_info(self, group_id: int, user_id: int):
            assert group_id == 123
            assert user_id == 456
            return {
                "user_id": user_id,
                "nickname": "群昵称",
                "card": "测试群名片",
                "role": "admin",
                "title": "活跃成员",
                "join_time": join_time,
                "last_sent_time": last_sent_time,
                "level": "5",
            }

        async def get_stranger_info(self, user_id: int):
            assert user_id == 456
            return {
                "user_id": user_id,
                "nickname": "测试用户",
                "sex": "male",
                "age": 18,
            }

    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Info
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "get_user_info",
            {},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert result["message"] == "执行成功"
    assert result["data"] == {
        "QQ号": 456,
        "昵称": "测试用户",
        "群名片": "测试群名片",
        "角色": "管理员",
        "头衔": "活跃成员",
        "入群时间": datetime.fromtimestamp(join_time).strftime("%Y-%m-%d %H:%M"),
        "最后发言": datetime.fromtimestamp(last_sent_time).strftime("%Y-%m-%d %H:%M"),
        "等级": "5",
        "性别": "男",
        "年龄": 18,
    }
    assert tool_registry.get_tool("get_group_member_info") is None


def test_service_bridge_multincm_ai_tool_tolerates_extra_context(monkeypatch) -> None:
    import bot  # noqa: F401

    MultiNCMService = importlib.import_module("src.services.multincm").MultiNCMService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = MultiNCMService.__new__(MultiNCMService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)

    class DummySongSearcher:
        def __init__(self, keyword: str):
            self.keyword = keyword

        async def get_page(self, page_no: int):
            return SimpleNamespace(
                content=[SimpleNamespace(id=987654321)],
                transform_to_list_cards=lambda: asyncio.sleep(
                    0,
                    result=[
                        SimpleNamespace(
                            title=f"{self.keyword}-结果",
                            alias="别名",
                            extras=["歌手"],
                            small_extras=["03:15"],
                        )
                    ],
                ),
            )

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_multincm.data_source.song",
        types.SimpleNamespace(
            SongSearcher=DummySongSearcher,
            Song=type("DummySong", (), {}),
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Multincm
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "multincm_search_song",
            {"keyword": "lemon", "limit": 5},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
                "image_registry": {"img_001": "https://example.com/1.png"},
                "video_registry": {"vid_001": "https://example.com/1.mp4"},
            },
        )
    )

    assert result["success"] is True
    assert result["data"]["results"][0]["id"] == 987654321
    assert result["data"]["results"][0]["title"] == "lemon-结果"


def test_service_bridge_multincm_get_song_url_returns_clear_error_for_invalid_id(monkeypatch) -> None:
    import bot  # noqa: F401

    MultiNCMService = importlib.import_module("src.services.multincm").MultiNCMService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = MultiNCMService.__new__(MultiNCMService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_multincm.data_source.song",
        types.SimpleNamespace(
            Song=type(
                "DummySong",
                (),
                {
                    "from_id": classmethod(lambda cls, song_id: asyncio.sleep(0, result=(_ for _ in ()).throw(IndexError()))),
                },
            )
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Multincm
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "multincm_get_song_url",
            {"song_id": 1},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is False
    assert result["message"] == "未找到歌曲 ID：1"


def test_service_bridge_multincm_get_song_url_sends_music_card(monkeypatch) -> None:
    import bot  # noqa: F401

    MultiNCMService = importlib.import_module("src.services.multincm").MultiNCMService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    sent_messages = []

    async def _fake_send_msg(message):
        sent_messages.append(message)

    service = MultiNCMService.__new__(MultiNCMService)
    service.group = SimpleNamespace(send_msg=_fake_send_msg)
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_multincm.data_source.song",
        types.SimpleNamespace(
            Song=type(
                "DummySong",
                (),
                {
                    "from_id": classmethod(
                        lambda cls, song_id: asyncio.sleep(
                            0,
                            result=SimpleNamespace(
                                id=song_id,
                                get_info=lambda: asyncio.sleep(
                                    0,
                                    result=SimpleNamespace(
                                        url="https://music.163.com/song?id=31421442",
                                        playable_url="https://example.com/audio.mp3",
                                        display_name="アイロニ",
                                        cover_url="https://example.com/cover.jpg",
                                        display_artists="majiko",
                                        display_duration="04:04",
                                    ),
                                ),
                            ),
                        )
                    ),
                },
            )
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Multincm
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "multincm_get_song_url",
            {"song_id": 31421442},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert result["message"] == "已发送音乐卡片"
    assert result["data"]["card_sent"] is True
    assert result["data"]["page_url"] == "https://music.163.com/song?id=31421442"
    assert len(sent_messages) == 1
    segment = sent_messages[0][0]
    assert segment.type == "music"
    assert segment.data == {
        "type": "custom",
        "url": "https://music.163.com/song?id=31421442",
        "audio": "https://example.com/audio.mp3",
        "title": "アイロニ",
        "image": "https://example.com/cover.jpg",
        "singer": "majiko",
    }


def test_service_bridge_multincm_get_song_url_falls_back_to_text_when_card_send_fails(monkeypatch) -> None:
    import bot  # noqa: F401

    MultiNCMService = importlib.import_module("src.services.multincm").MultiNCMService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    sent_messages = []

    async def _fake_send_msg(message):
        sent_messages.append(message)

    service = MultiNCMService.__new__(MultiNCMService)
    service.group = SimpleNamespace(send_msg=_fake_send_msg)
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    async def _raise_card_send(info):
        raise RuntimeError("send failed")

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(service, "_send_song_card_message", _raise_card_send)
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_multincm.data_source.song",
        types.SimpleNamespace(
            Song=type(
                "DummySong",
                (),
                {
                    "from_id": classmethod(
                        lambda cls, song_id: asyncio.sleep(
                            0,
                            result=SimpleNamespace(
                                id=song_id,
                                get_info=lambda: asyncio.sleep(
                                    0,
                                    result=SimpleNamespace(
                                        url="https://music.163.com/song?id=42",
                                        playable_url="https://example.com/fallback.mp3",
                                        display_name="反语",
                                        cover_url="https://example.com/fallback.jpg",
                                        display_artists="鹿乃",
                                        display_duration="04:11",
                                    ),
                                ),
                            ),
                        )
                    ),
                },
            )
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Multincm
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "multincm_get_song_url",
            {"song_id": 42},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert result["message"] == "音乐卡片发送失败，已改为发送文本链接"
    assert result["data"]["card_sent"] is False
    assert sent_messages == [
        "已为你找到歌曲：反语\n歌手：鹿乃\n页面：https://music.163.com/song?id=42\n直链：https://example.com/fallback.mp3"
    ]


def test_service_bridge_emojimix_ai_tool_tolerates_extra_context(monkeypatch) -> None:
    import bot  # noqa: F401

    EmojimixService = importlib.import_module("src.services.emojimix").EmojimixService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = EmojimixService.__new__(EmojimixService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    called = {}

    async def _fake_send_mix_result(*, code1: str, code2: str, silent: bool):
        called.update({"code1": code1, "code2": code2, "silent": silent})

    monkeypatch.setattr(service, "_send_mix_result", _fake_send_mix_result)

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Emojimix
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "emojimix",
            {"emoji1": "😀", "emoji2": "😁", "silent": True},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
                "image_registry": {"img_001": "https://example.com/1.png"},
                "video_registry": {"vid_001": "https://example.com/1.mp4"},
            },
        )
    )

    assert result["success"] is True
    assert called == {"code1": "😀", "code2": "😁", "silent": True}


def test_service_bridge_bison_ai_tool_tolerates_extra_context(monkeypatch) -> None:
    import bot  # noqa: F401
    import nonebot_plugin_saa

    BisonService = importlib.import_module("src.services.bison").BisonService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(service, "_ensure_scheduler_ready", lambda platform: asyncio.sleep(0))
    monkeypatch.setattr(
        nonebot_plugin_saa,
        "TargetQQGroup",
        lambda group_id: SimpleNamespace(group_id=group_id, user_type="group"),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.apis",
        types.SimpleNamespace(check_sub_target=lambda platform, target: asyncio.sleep(0, result="测试UP")),
    )

    class DummyBisonConfig:
        def __init__(self):
            self.called = None

        async def add_subscribe(self, **kwargs):
            self.called = kwargs

    bison_config = DummyBisonConfig()

    class DummySubscribeDupException(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config",
        types.SimpleNamespace(config=bison_config),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config.db_config",
        types.SimpleNamespace(SubscribeDupException=DummySubscribeDupException),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.types",
        types.SimpleNamespace(
            Target=lambda target: SimpleNamespace(target=target),
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Bison
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "bison_subscribe",
            {"platform": "bilibili", "target": "12345"},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
                "image_registry": {"img_001": "https://example.com/1.png"},
                "video_registry": {"vid_001": "https://example.com/1.mp4"},
            },
        )
    )

    assert result["success"] is True
    assert bison_config.called is not None
    assert bison_config.called["user"].group_id == 123
    assert bison_config.called["user"].user_type == "group"


def test_service_bridge_bison_ai_tool_initializes_scheduler_when_missing(monkeypatch) -> None:
    import bot  # noqa: F401
    import nonebot_plugin_saa

    BisonService = importlib.import_module("src.services.bison").BisonService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(
        nonebot_plugin_saa,
        "TargetQQGroup",
        lambda group_id: SimpleNamespace(group_id=group_id, user_type="group"),
    )

    scheduler_state = {"inited": 0}
    fake_site = type("FakeBilibiliSite", (), {})

    async def _fake_init_scheduler():
        scheduler_state["inited"] += 1
        fake_scheduler_module.scheduler_dict[fake_site] = object()

    fake_scheduler_module = types.SimpleNamespace(
        scheduler_dict={},
        init_scheduler=_fake_init_scheduler,
    )

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.platform",
        types.SimpleNamespace(
            platform_manager={"bilibili": SimpleNamespace(site=fake_site)},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.scheduler",
        fake_scheduler_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.apis",
        types.SimpleNamespace(check_sub_target=lambda platform, target: asyncio.sleep(0, result="测试UP")),
    )

    class DummyBisonConfig:
        def __init__(self):
            self.called = None

        async def add_subscribe(self, **kwargs):
            self.called = kwargs

    bison_config = DummyBisonConfig()

    class DummySubscribeDupException(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config",
        types.SimpleNamespace(config=bison_config),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config.db_config",
        types.SimpleNamespace(SubscribeDupException=DummySubscribeDupException),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.types",
        types.SimpleNamespace(
            Target=lambda target: SimpleNamespace(target=target),
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Bison
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "bison_subscribe",
            {"platform": "bilibili", "target": "1084470248"},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert scheduler_state["inited"] == 1
    assert fake_site in fake_scheduler_module.scheduler_dict
    assert bison_config.called is not None
    assert bison_config.called["user"].group_id == 123


def test_service_bridge_bison_ai_tool_unsubscribes_existing_target(monkeypatch) -> None:
    import bot  # noqa: F401
    import nonebot_plugin_saa

    BisonService = importlib.import_module("src.services.bison").BisonService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(
        nonebot_plugin_saa,
        "TargetQQGroup",
        lambda group_id: SimpleNamespace(group_id=group_id, user_type="group"),
    )

    class DummyNoSuchUserException(Exception):
        pass

    class DummyNoSuchSubscribeException(Exception):
        pass

    class DummyBisonConfig:
        def __init__(self):
            self.listed_user = None
            self.deleted = None

        async def list_subscribe(self, user):
            self.listed_user = user
            return [
                SimpleNamespace(
                    target=SimpleNamespace(
                        platform_name="bilibili",
                        target="12345",
                        target_name="测试UP",
                    )
                )
            ]

        async def del_subscribe(self, user, target, platform_name):
            self.deleted = {
                "user": user,
                "target": target,
                "platform_name": platform_name,
            }

    bison_config = DummyBisonConfig()

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config",
        types.SimpleNamespace(
            config=bison_config,
            NoSuchSubscribeException=DummyNoSuchSubscribeException,
            NoSuchUserException=DummyNoSuchUserException,
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Bison
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "bison_unsubscribe",
            {"platform": "bilibili", "target": "12345"},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert result["message"] == "已取消订阅 测试UP (bilibili 12345)"
    assert bison_config.listed_user is not None
    assert bison_config.listed_user.group_id == 123
    assert bison_config.deleted == {
        "user": bison_config.listed_user,
        "target": "12345",
        "platform_name": "bilibili",
    }


def test_service_bridge_bison_ai_tool_unsubscribe_returns_not_found(monkeypatch) -> None:
    import bot  # noqa: F401
    import nonebot_plugin_saa

    BisonService = importlib.import_module("src.services.bison").BisonService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(
        nonebot_plugin_saa,
        "TargetQQGroup",
        lambda group_id: SimpleNamespace(group_id=group_id, user_type="group"),
    )

    class DummyNoSuchUserException(Exception):
        pass

    class DummyNoSuchSubscribeException(Exception):
        pass

    class DummyBisonConfig:
        def __init__(self):
            self.deleted = False

        async def list_subscribe(self, user):
            return [
                SimpleNamespace(
                    target=SimpleNamespace(
                        platform_name="bilibili",
                        target="99999",
                        target_name="别的UP",
                    )
                )
            ]

        async def del_subscribe(self, user, target, platform_name):
            self.deleted = True

    bison_config = DummyBisonConfig()

    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_bison.config",
        types.SimpleNamespace(
            config=bison_config,
            NoSuchSubscribeException=DummyNoSuchSubscribeException,
            NoSuchUserException=DummyNoSuchUserException,
        ),
    )

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Bison
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "bison_unsubscribe",
            {"platform": "bilibili", "target": "12345"},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is False
    assert result["message"] == "未找到该订阅"
    assert bison_config.deleted is False


def test_bison_service_proxy_commands_persist_and_sync_runtime(tmp_path, monkeypatch) -> None:
    import bot  # noqa: F401

    bison_module = importlib.import_module("src.services.bison")
    BisonService = bison_module.BisonService

    runtime_path = tmp_path / "bison_runtime.json"
    fake_plugin_module = types.SimpleNamespace(plugin_config=SimpleNamespace(bison_proxy="http://default-proxy:8080"))
    fake_http_module = types.SimpleNamespace(http_args={"proxy": "http://default-proxy:8080"})

    monkeypatch.setattr(bison_module, "BISON_RUNTIME_CONFIG_PATH", runtime_path)
    monkeypatch.setitem(sys.modules, "src.vendors.nonebot_bison.plugin_config", fake_plugin_module)
    monkeypatch.setitem(sys.modules, "nonebot_bison.plugin_config", fake_plugin_module)
    monkeypatch.setitem(sys.modules, "src.vendors.nonebot_bison.utils.http", fake_http_module)
    monkeypatch.setitem(sys.modules, "nonebot_bison.utils.http", fake_http_module)

    sent_messages = []

    async def _fake_send_msg(message):
        sent_messages.append(str(message))
        return True

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace(send_msg=_fake_send_msg)
    service._config = {"enabled": True}

    from nonebot.adapters.onebot.v11 import Message

    asyncio.run(service.set_bison_proxy(Message("http://127.0.0.1:7890")))

    assert runtime_path.exists()
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {"proxy": "http://127.0.0.1:7890"}
    assert fake_plugin_module.plugin_config.bison_proxy == "http://127.0.0.1:7890"
    assert fake_http_module.http_args["proxy"] == "http://127.0.0.1:7890"
    assert sent_messages[-1] == "已设置 Bison 代理：http://127.0.0.1:7890"

    asyncio.run(service.show_bison_proxy())
    assert sent_messages[-1] == "当前 Bison 代理：http://127.0.0.1:7890"

    asyncio.run(service.clear_bison_proxy())
    assert runtime_path.exists() is False
    assert fake_plugin_module.plugin_config.bison_proxy == "http://default-proxy:8080"
    assert fake_http_module.http_args["proxy"] == "http://default-proxy:8080"
    assert sent_messages[-1] == "已清除 Bison 代理"


def test_bison_service_set_proxy_rejects_invalid_input(monkeypatch, tmp_path) -> None:
    import bot  # noqa: F401

    bison_module = importlib.import_module("src.services.bison")
    BisonService = bison_module.BisonService

    runtime_path = tmp_path / "bison_runtime.json"
    monkeypatch.setattr(bison_module, "BISON_RUNTIME_CONFIG_PATH", runtime_path)

    sent_messages = []

    async def _fake_send_msg(message):
        sent_messages.append(str(message))
        return True

    service = BisonService.__new__(BisonService)
    service.group = SimpleNamespace(send_msg=_fake_send_msg)
    service._config = {"enabled": True}

    from nonebot.adapters.onebot.v11 import Message

    asyncio.run(service.set_bison_proxy(Message("not-a-proxy")))

    assert runtime_path.exists() is False
    assert sent_messages == ["代理地址格式无效，请使用如 http://127.0.0.1:7890 的完整地址"]


def test_resolver_service_toggle_syncs_runtime_shutdown_list(monkeypatch) -> None:
    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService

    shutdown_list: list[int] = []
    sent_messages: list[str] = []

    monkeypatch.setattr(resolver_module, "_load_resolver_shutdown_list", lambda: list(shutdown_list))
    monkeypatch.setattr(
        resolver_module,
        "_save_resolver_shutdown_list",
        lambda group_ids: shutdown_list.__setitem__(slice(None), list(group_ids)),
    )

    async def _fake_send_msg(message):
        sent_messages.append(str(message))
        return True

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456, send_msg=_fake_send_msg)
    service._config = {"enabled": True}
    service._save_config = lambda: None

    async def _noop_runtime():
        return None

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)

    asyncio.run(service.disable_service())

    assert shutdown_list == [123456]
    assert service.enabled is False
    assert service._config["enabled"] is False
    assert sent_messages[-1] == "✅ 本群链接解析服务关闭成功！"

    asyncio.run(service.enable_service())

    assert shutdown_list == []
    assert service.enabled is True
    assert service._config["enabled"] is True
    assert sent_messages[-1] == "✅ 本群链接解析服务开启成功！"


def test_resolver_service_auto_message_skips_when_disabled(monkeypatch) -> None:
    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService

    called = {"value": False}

    async def _fake_dispatch_auto_resolve(event):
        called["value"] = True
        return True

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456)
    service._config = {"enabled": False}

    monkeypatch.setattr(service, "_sync_runtime_enabled", lambda: False)
    monkeypatch.setattr(service, "_dispatch_auto_resolve", _fake_dispatch_auto_resolve)

    event = SimpleNamespace(message=Message("https://www.bilibili.com/video/BV1xx411c7mD"))
    event.get_message = lambda: event.message
    event.reply = None

    asyncio.run(service.handle_auto_resolve(event))

    assert called["value"] is False


def test_resolver_service_auto_message_ignores_non_matching_message_without_loading_runtime(monkeypatch) -> None:
    import nonebot

    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService

    called = {"ensure_runtime": False}

    async def _fake_ensure_runtime():
        called["ensure_runtime"] = True

    class DummyBot:
        async def get_forward_msg(self, *, id: str):
            return {"messages": []}

    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456)
    service._config = {"enabled": True}

    monkeypatch.setattr(service, "_ensure_runtime", _fake_ensure_runtime)
    monkeypatch.setattr(service, "_sync_runtime_enabled", lambda: True)

    event = SimpleNamespace(message=Message("这是一条普通聊天消息"))
    event.get_message = lambda: event.message
    event.reply = None

    asyncio.run(service.handle_auto_resolve(event))

    assert called["ensure_runtime"] is False


def test_resolver_service_auto_message_ignores_non_bilibili_link_without_loading_runtime(monkeypatch) -> None:
    import nonebot

    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService

    called = {"ensure_runtime": False}

    async def _fake_ensure_runtime():
        called["ensure_runtime"] = True

    class DummyBot:
        async def get_forward_msg(self, *, id: str):
            return {"messages": []}

    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456)
    service._config = {"enabled": True}

    monkeypatch.setattr(service, "_ensure_runtime", _fake_ensure_runtime)
    monkeypatch.setattr(service, "_sync_runtime_enabled", lambda: True)

    event = SimpleNamespace(message=Message("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    event.get_message = lambda: event.message
    event.reply = None

    asyncio.run(service.handle_auto_resolve(event))

    assert called["ensure_runtime"] is False


def test_resolver_service_auto_message_dispatches_matching_candidate(monkeypatch) -> None:
    import nonebot

    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService
    resolver_package = importlib.import_module("src.vendors.nonebot_plugin_resolver")

    captured: list[str] = []

    async def _fake_dispatch(bot, event, message_text=None):
        captured.append(str(message_text or ""))
        return "bilibili.com" in str(message_text or "")

    fake_bootstrap = types.SimpleNamespace(dispatch_resolver_message=_fake_dispatch)
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_resolver.bootstrap",
        fake_bootstrap,
    )
    monkeypatch.setattr(resolver_package, "bootstrap", fake_bootstrap, raising=False)

    class DummyBot:
        async def get_forward_msg(self, *, id: str):
            return {"messages": []}

    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())

    async def _noop_runtime():
        return None

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456)
    service._config = {"enabled": True}

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(service, "_sync_runtime_enabled", lambda: True)

    event = SimpleNamespace(message=Message("https://www.bilibili.com/video/BV1xx411c7mD"))
    event.get_message = lambda: event.message
    event.reply = None

    asyncio.run(service.handle_auto_resolve(event))

    assert captured
    assert captured[0] == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_resolver_service_auto_message_uses_forward_payload_candidates(monkeypatch) -> None:
    import nonebot

    resolver_module = importlib.import_module("src.services.resolver")
    ResolverService = resolver_module.ResolverService
    resolver_package = importlib.import_module("src.vendors.nonebot_plugin_resolver")

    captured: list[str] = []

    async def _fake_dispatch(bot, event, message_text=None):
        captured.append(str(message_text or ""))
        return "bilibili.com" in str(message_text or "")

    fake_bootstrap = types.SimpleNamespace(dispatch_resolver_message=_fake_dispatch)
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_resolver.bootstrap",
        fake_bootstrap,
    )
    monkeypatch.setattr(resolver_package, "bootstrap", fake_bootstrap, raising=False)

    class DummyBot:
        async def get_forward_msg(self, *, id: str):
            assert id == "forward-1"
            return {
                "messages": [
                    {
                        "content": "https://www.bilibili.com/video/BV1xx411c7mD",
                    }
                ]
            }

    monkeypatch.setattr(nonebot, "get_bot", lambda: DummyBot())

    async def _noop_runtime():
        return None

    service = ResolverService.__new__(ResolverService)
    service.group = SimpleNamespace(group_id=123456)
    service._config = {"enabled": True}

    monkeypatch.setattr(service, "_ensure_runtime", _noop_runtime)
    monkeypatch.setattr(service, "_sync_runtime_enabled", lambda: True)

    event = SimpleNamespace(message=Message([MessageSegment("forward", {"id": "forward-1"})]))
    event.get_message = lambda: event.message
    event.reply = None

    asyncio.run(service.handle_auto_resolve(event))

    assert any("bilibili.com/video" in item for item in captured)


def test_service_bridge_whateat_ai_tool_tolerates_extra_context(monkeypatch) -> None:
    import bot  # noqa: F401

    WhateatService = importlib.import_module("src.services.whateat").WhateatService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = WhateatService.__new__(WhateatService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    captured = {}

    async def _fake_recommend_food(event):
        captured["event"] = event

    monkeypatch.setattr(service, "recommend_food", _fake_recommend_food)

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Whateat
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "recommend_food",
            {},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
                "image_registry": {"img_001": "https://example.com/1.png"},
                "video_registry": {"vid_001": "https://example.com/1.mp4"},
            },
        )
    )

    assert result["success"] is True
    assert captured["event"].user_id == 456
    assert captured["event"].group_id == 123


def test_service_bridge_whateat_ai_tool_propagates_real_failure(monkeypatch) -> None:
    import bot  # noqa: F401

    WhateatService = importlib.import_module("src.services.whateat").WhateatService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    service = WhateatService.__new__(WhateatService)
    service.group = SimpleNamespace()
    service._config = {"enabled": True}

    async def _fake_recommend_food(event):
        return {"success": False, "message": "出错啦！没有找到好吃的~"}

    monkeypatch.setattr(service, "recommend_food", _fake_recommend_food)

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Whateat
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "recommend_food",
            {},
            {
                "group_id": 123,
                "user_id": 456,
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is False
    assert "没有找到好吃的" in result["message"]


def test_service_bridge_wordcloud_history_defaults_to_full_history_when_arg_is_empty(monkeypatch) -> None:
    import bot  # noqa: F401

    WordcloudService = importlib.import_module("src.services.wordcloud").WordcloudService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    class DummyGroup:
        group_id = 123

        async def send_msg(self, message):
            return None

    service = WordcloudService.__new__(WordcloudService)
    service.group = DummyGroup()
    service._config = {"enabled": True}

    captured = {}

    async def _fake_send_wordcloud(*, event, start, stop, scope, user_id=None):
        captured["start"] = start
        captured["stop"] = stop
        captured["scope"] = scope

    monkeypatch.setattr(service, "_send_wordcloud", _fake_send_wordcloud)
    monkeypatch.setattr(service, "_resolve_scope", lambda event: "group")

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Wordcloud
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "wordcloud_wordcloud_history",
            {"arg_text": ""},
            {
                "group_id": 123,
                "user_id": 456,
                "message": "历史词云",
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is True
    assert captured["start"].year == 1970
    assert captured["scope"] == "group"


def test_service_bridge_wordcloud_history_returns_failure_for_invalid_range(monkeypatch) -> None:
    import bot  # noqa: F401

    WordcloudService = importlib.import_module("src.services.wordcloud").WordcloudService

    bridge = ServiceBridge()
    bridge.init_service_tools()

    sent_messages = []

    class DummyGroup:
        group_id = 123

        async def send_msg(self, message):
            sent_messages.append(str(message))

    service = WordcloudService.__new__(WordcloudService)
    service.group = DummyGroup()
    service._config = {"enabled": True}

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            assert service_type is Services.Wordcloud
            return service

    bridge.set_service_manager(DummyManager())

    result = asyncio.run(
        tool_registry.execute_tool(
            "wordcloud_wordcloud_history",
            {"arg_text": "not-a-date"},
            {
                "group_id": 123,
                "user_id": 456,
                "message": "历史词云",
                "service_manager": bridge._service_manager,
            },
        )
    )

    assert result["success"] is False
    assert "示例：/历史词云" in result["message"]
    assert sent_messages
