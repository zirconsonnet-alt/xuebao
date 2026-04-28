import ast
import asyncio
import importlib
import inspect
from pathlib import Path
import sys
from types import MethodType
from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import SERVICE_CLASS_IMPORTS
from src.services import registry
from src.support.core import ServiceBridge, Services, tool_registry


@pytest.fixture(scope="module")
def boot_runtime():
    import bot  # noqa: F401

    yield

    import src.services.bison as bison_module
    import src.services.multincm as multincm_module
    import src.services.resolver as resolver_module

    bison_module._RUNTIME_ACTIVATED = False
    multincm_module._RUNTIME_ACTIVATED = False
    resolver_module._RUNTIME_ACTIVATED = False


def _iter_service_classes():
    for service_type, (module_path, class_name) in SERVICE_CLASS_IMPORTS.items():
        module = importlib.import_module(module_path)
        yield service_type, getattr(module, class_name)


def _collect_runtime_decorated_methods():
    inventory = {
        "actions": [],
        "messages": [],
        "notices": [],
        "requests": [],
        "ai_tools": [],
    }

    for service_type, service_cls in _iter_service_classes():
        for attr_name in dir(service_cls):
            method = getattr(service_cls, attr_name, None)
            if method is None:
                continue

            if meta := getattr(method, "__service_action__", None):
                inventory["actions"].append((service_type, service_cls, attr_name, meta))
            if meta := getattr(method, "__service_message__", None):
                inventory["messages"].append((service_type, service_cls, attr_name, meta))
            if meta := getattr(method, "__service_notice__", None):
                inventory["notices"].append((service_type, service_cls, attr_name, meta))
            if meta := getattr(method, "__service_request__", None):
                inventory["requests"].append((service_type, service_cls, attr_name, meta))
            if meta := getattr(method, "__ai_tool__", None):
                inventory["ai_tools"].append((service_type, service_cls, attr_name, meta))

    return inventory


def _collect_check_enabled_methods():
    records = []
    services_root = REPO_ROOT / "src" / "services"

    for path in services_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_path = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorator_names = []
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name):
                        decorator_names.append(decorator.id)
                    elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                        decorator_names.append(decorator.func.id)
                if "check_enabled" in decorator_names:
                    records.append((module_path, node.name, item.name))

    return records


def _sample_value(schema: dict):
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        return schema["default"]
    value_type = schema.get("type", "string")
    if value_type == "integer":
        return 1
    if value_type == "number":
        return 1.0
    if value_type == "boolean":
        return False
    if value_type == "array":
        return []
    if value_type == "object":
        return {}
    return "测试值"


def _get_model_schema(model_cls) -> dict:
    if model_cls is None:
        return {}
    if hasattr(model_cls, "model_json_schema"):
        return model_cls.model_json_schema()
    if hasattr(model_cls, "schema"):
        return model_cls.schema()
    return {}


def _build_required_tool_args(parameters: dict, *, model_cls=None) -> dict:
    properties = dict(parameters.get("properties", {}))
    required = set(parameters.get("required", []))

    model_schema = _get_model_schema(model_cls)
    model_properties = model_schema.get("properties", {})
    properties.update({name: spec for name, spec in model_properties.items() if name not in properties})
    required.update(model_schema.get("required", []))

    args = {name: _sample_value(properties.get(name, {})) for name in required}

    if "message" in properties:
        args.setdefault("message", "测试消息")
    if "arg_text" in properties:
        args.setdefault("arg_text", "测试参数")
    if "reply_text" in properties:
        args.setdefault("reply_text", "测试回复")
    if "reply_message_id" in properties:
        args.setdefault("reply_message_id", 1)

    return args


class DummyDB:
    def __init__(self):
        self.service_configs = {}
        self.service_states = {}
        self.sign_ins = set()
        self.ledger = []

    def get_service_config(self, service_name):
        return self.service_configs.get(service_name)

    def upsert_service_config(self, service_name, payload):
        self.service_configs[service_name] = dict(payload)

    def get_service_state_entry(self, service_name, scope, key):
        return self.service_states.get((service_name, scope, key))

    def upsert_service_state_entry(self, service_name, scope, key, value):
        self.service_states[(service_name, scope, key)] = value

    def delete_service_state_entry(self, service_name, scope, key):
        self.service_states.pop((service_name, scope, key), None)

    def list_service_state_entries(self, service_name, scope):
        rows = []
        for (service, row_scope, key), value in self.service_states.items():
            if service == service_name and row_scope == scope:
                rows.append({"entry_key": key, "value": value})
        return rows

    def reserve_sign_in(self, user_id: int, sign_date: str):
        key = (user_id, sign_date)
        if key in self.sign_ins:
            return False
        self.sign_ins.add(key)
        return True

    def insert_ledger(self, **kwargs):
        self.ledger.append(kwargs)

    def get_balance(self, user_id: int, currency: str):
        return sum(item.get("delta", 0) for item in self.ledger if item.get("user_id") == user_id and item.get("currency") == currency)

    def apply_points_cost(
        self,
        *,
        user_id: int,
        cost_points: int,
        reason: str,
        idempotency_key: str,
        ref_type=None,
        ref_id=None,
    ):
        self.ledger.append(
            {
                "user_id": user_id,
                "currency": "points",
                "delta": -int(cost_points or 0),
                "reason": reason,
                "idempotency_key": idempotency_key,
                "ref_type": ref_type,
                "ref_id": ref_id,
            }
        )
        return True, 999, False

    def __getattr__(self, name):
        if name.startswith("get_all_"):
            return lambda *args, **kwargs: []
        if name.startswith("get_"):
            return lambda *args, **kwargs: None
        if name.startswith(("add_", "update_", "upsert_", "delete_", "remove_", "insert_")):
            return lambda *args, **kwargs: True
        if name.startswith("list_"):
            return lambda *args, **kwargs: []
        return lambda *args, **kwargs: None


class DummyGroup:
    def __init__(self, root: Path):
        self.group_id = 123456
        self.self_id = 654321
        self.group_path = root / "group"
        self.custom_path = root / "custom"
        self.group_path.mkdir(parents=True, exist_ok=True)
        self.custom_path.mkdir(parents=True, exist_ok=True)
        self.db = DummyDB()
        self.sent = []
        self.notices = []
        self.forward_messages = []
        self.actions = []

    async def send_msg(self, msg):
        self.sent.append(str(msg))
        return {"message_id": len(self.sent)}

    async def send_notice(self, msg):
        self.notices.append(str(msg))
        return True

    async def send_forward_msg(self, nodes):
        self.forward_messages.append(nodes)
        return True

    async def set_group_add(self, event, approve: bool, reason: str | None = None):
        self.actions.append(("set_group_add", approve, reason))
        return True

    async def set_special_title(self, *args, **kwargs):
        self.actions.append(("set_special_title", args, kwargs))
        return True

    async def get_group_member_info(self, user_id):
        return {"role": "admin", "user_id": user_id, "nickname": "测试成员"}

    async def get_files(self):
        return []

    async def get_folder(self, name):
        return {"folder": name, "folder_name": name}

    async def get_works(self, folder=None):
        return []

    async def delete_file(self, file):
        self.actions.append(("delete_file", file))
        return True

    async def move_file(self, file_id, source, target):
        self.actions.append(("move_file", file_id, source, target))
        return True

    async def get_resent_file_url(self):
        return "测试作品", "https://example.com/audio.mp3"

    async def get_user_img(self, user_id):
        return f"https://example.com/avatar/{user_id}.jpg"

    async def get_resent_file(self, user_id):
        return None

    async def download_file(self, file):
        return str(self.custom_path / "dummy.bin")

    async def upload_file(self, *args, **kwargs):
        self.actions.append(("upload_file", args, kwargs))
        return True

    async def set_msg(self, *args, **kwargs):
        self.actions.append(("set_msg", args, kwargs))
        return True

    def __getattr__(self, name):
        async def _stub(*args, **kwargs):
            self.actions.append((name, args, kwargs))
            if name.startswith("get_"):
                return {}
            return True

        return _stub


class DummyBot:
    def __init__(self):
        self.self_id = 654321
        self.sent = []

    async def get_group_info(self, **kwargs):
        return {"group_id": kwargs.get("group_id", 123456), "group_name": "测试群", "member_count": 12}

    async def get_group_member_list(self, **kwargs):
        return [{"user_id": 456, "nickname": "测试用户", "card": "", "role": "admin"}]

    async def get_group_member_info(self, **kwargs):
        return {"user_id": kwargs.get("user_id", 456), "nickname": "测试用户", "card": "", "role": "admin"}

    async def get_stranger_info(self, **kwargs):
        return {"user_id": kwargs.get("user_id", 456), "nickname": "测试路人"}

    async def get_group_honor_info(self, **kwargs):
        return {"current_talkative": {}, "talkative_list": []}

    async def get_friend_list(self):
        return [{"user_id": 456}]

    async def get_image(self, **kwargs):
        return {"url": "https://example.com/image.jpg"}

    async def send_like(self, **kwargs):
        return True

    async def set_msg_emoji_like(self, **kwargs):
        return True

    async def call_api(self, api_name, **kwargs):
        self.sent.append((api_name, kwargs))
        return {"ok": True}

    async def delete_msg(self, **kwargs):
        return True

    async def send_group_msg(self, **kwargs):
        return {"message_id": 1}

    async def send_group_forward_msg(self, **kwargs):
        return {"message_id": 1}

    async def get_forward_msg(self, **kwargs):
        return {"messages": []}

    async def send(self, event, message):
        self.sent.append(("send", str(message)))
        return True

    def __getattr__(self, name):
        async def _stub(*args, **kwargs):
            self.sent.append((name, args, kwargs))
            return True

        return _stub


class DummyMatcher:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(str(message))
        return True

    async def finish(self, message=""):
        if message:
            self.sent.append(str(message))
        raise RuntimeError("dummy matcher finish")


class DummyReply:
    def __init__(self):
        self.message_id = 1
        self.message = Message("测试回复")


class DummyEvent:
    def __init__(
        self,
        *,
        message_text: str = "测试消息",
        user_id: int = 456,
        group_id: int = 123456,
        self_id: int = 654321,
        sub_type: str = "add",
        reply=None,
        file_name: str = "测试作品.mp3",
        comment: str = "答案：测试",
    ):
        self.user_id = user_id
        self.group_id = group_id
        self.self_id = self_id
        self.message_id = 1001
        self.post_type = "message"
        self.notice_type = "notify"
        self.request_type = "group"
        self.sub_type = sub_type
        self.comment = comment
        self.message = Message(message_text)
        self.reply = reply
        self.sender = SimpleNamespace(role="admin", nickname="测试用户")
        self.target_id = self_id
        self.file = SimpleNamespace(name=file_name)

    def get_message(self):
        return self.message

    def is_tome(self):
        return True


class DummySpeechGenerator:
    async def gen_speech(self, **kwargs):
        return "dummy.wav"


class DummyAIAssistant:
    def __init__(self):
        self.black_list = set()
        self.nickname = "测试AI"
        self.msg_list = [{"role": "user", "content": "hi"}]
        self.character = SimpleNamespace(
            name="测试AI",
            on_switch_msg="切换成功",
            voice_enable_msg="语音已开启",
            voice_disable_msg="语音已关闭",
            voice_id="voice-1",
        )
        self.speech_generator = DummySpeechGenerator()
        self._custom_characters = [SimpleNamespace(name="角色A")]

    def get_character_names(self):
        return ["测试AI", "角色A"]

    async def switch_character(self, name):
        self.character.name = name

    async def switch_character_menu(self):
        return None

    async def clear_conversation(self):
        return None

    async def send(self, *args, **kwargs):
        return None

    async def send_text(self, *args, **kwargs):
        return None

    async def send_audio(self, *args, **kwargs):
        return None

    async def reply(self, *args, **kwargs):
        return None

    async def reply_with_zhihu(self, *args, **kwargs):
        return None

    async def text_menu(self):
        return None

    def buffer_chat_message(self, *args, **kwargs):
        return None

    def add_to_blacklist(self, user_id: int):
        self.black_list.add(user_id)
        return True, f"已拉黑 {user_id}"

    def remove_from_blacklist(self, user_id: int):
        self.black_list.discard(user_id)
        return True, f"已解除 {user_id}"

    def get_custom_characters(self):
        return list(self._custom_characters)

    def add_custom_character(self, character):
        self._custom_characters.append(character)
        return True

    def remove_custom_character(self, char_name: str):
        self._custom_characters = [item for item in self._custom_characters if item.name != char_name]
        return True


class DummyAIManager:
    def __init__(self):
        self.assistant = DummyAIAssistant()

    def get_client(self, event):
        return self.assistant


class DummyReminderRuntime:
    async def run(self):
        return None

    async def edit_mode(self):
        return None

    async def collect_question_and_screenshots(self, index):
        return None

    async def handler_task(self, index):
        return None

    async def check_and_trigger(self):
        return None

    async def send(self, message):
        return None

    def save_goal(self, **kwargs):
        return None


class DummyTaskStore:
    def __init__(self):
        self.tasks = {}

    def register_message_callback(self, task_id: str, message: str):
        self.tasks.setdefault(task_id, {"description": message, "message": message, "enabled": True})

    def extract_task_message(self, task):
        return task.get("message", "")

    def build_task_state(self, **kwargs):
        return kwargs

    def sync_task_state_from_runtime(self):
        return None

    def list_tasks(self):
        return dict(self.tasks)

    def upsert_task(self, **kwargs):
        self.tasks[kwargs["task_id"]] = dict(kwargs)
        return dict(kwargs)

    def remove_task(self, task_id: str):
        return self.tasks.pop(task_id, None) is not None


class DummyDriver:
    def __init__(self):
        self.config = SimpleNamespace(
            nickname={"测试豹"},
            superusers={"456"},
            command_start={"/"},
        )

    def on_startup(self, func=None):
        if func is None:
            return lambda inner: inner
        return func

    def on_shutdown(self, func=None):
        if func is None:
            return lambda inner: inner
        return func


class DummySendable:
    def __init__(self, payload=None):
        self.payload = [] if payload is None else [payload]

    def append(self, item):
        self.payload.append(item)
        return self

    def __add__(self, other):
        merged = DummySendable()
        merged.payload = list(self.payload)
        if isinstance(other, DummySendable):
            merged.payload.extend(other.payload)
        else:
            merged.payload.append(other)
        return merged

    async def send(self, *args, **kwargs):
        return True

    async def finish(self, *args, **kwargs):
        return True


class DummyUniMessage(DummySendable):
    @classmethod
    def text(cls, text=""):
        return cls(text)

    @classmethod
    def image(cls, raw=None):
        return cls(raw if raw is not None else "image")


class DummySaaText(DummySendable):
    pass


class DummySaaImage(DummySendable):
    pass


class DummyMessageFactory(DummySendable):
    def __init__(self, payload=None):
        super().__init__(payload or [])


class DummyTargetQQGroup(SimpleNamespace):
    def __init__(self, group_id: int):
        super().__init__(group_id=group_id, platform_type=SimpleNamespace(name="qq"))

    def dict(self, **kwargs):
        return {"group_id": self.group_id, "platform_type": {"name": self.platform_type.name}}


def _method_signature(method):
    signature = inspect.signature(method)
    params = list(signature.parameters.values())
    if params and all(param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) for param in params[1:]):
        closure = getattr(method, "__closure__", None) or ()
        for cell in closure:
            inner = getattr(cell, "cell_contents", None)
            if inspect.isfunction(inner):
                return inspect.signature(inner)
    return signature


def _message_text_for(attr_name: str, trigger_type: str) -> str:
    mapping = {
        "recommend_food": "今天吃什么",
        "recommend_drink": "今天喝什么",
        "view_all_dishes": "查看全部菜单",
        "view_dish": "查看菜品 测试",
        "add_dish": "添加菜品 测试",
        "delete_dish": "删除菜品 测试",
        "handle_emojimix": "😀+😁",
        "handle_auto_emojimix": "试试😀",
        "describe_image_cmd": "识别图片",
        "generate_image_cmd": "生成图片",
        "wordcloud_today": "今日词云",
        "wordcloud_history": "历史词云",
    }
    if attr_name in mapping:
        return mapping[attr_name]
    if trigger_type == "notice":
        return "通知事件"
    if trigger_type == "request":
        return "入群请求"
    return "测试消息"


def _arg_message_for(attr_name: str) -> Message:
    mapping = {
        "daily_schedule_enable": "22:00",
        "wordcloud_history": "2026-03-01~2026-03-02",
        "collect_task": "1",
        "view_task": "1",
        "save_goal": "math 2025-07-03 1 2025-07-10 5 完成目标",
        "set_target_user": "123456",
        "handle_approval": "1",
        "join_activity": "1",
        "approve_activity": "1",
        "enroll_activity": "1",
        "add_blacklist": "123456",
        "remove_blacklist": "123456",
        "generate_image_cmd": "测试提示词",
        "speak": "你好",
        "set_answer_cmd": "北京,上海",
        "search_memes": "摸",
        "meme_info": "摸",
        "generate_meme": "摸 你好",
        "set_bison_proxy": "http://127.0.0.1:7890",
        "rank": "今日 -k 测试",
        "kkb": "123456 -k 测试",
        "今日B话榜": "测试",
        "昨日B话榜": "测试",
        "本周B话榜": "测试",
        "上周B话榜": "测试",
        "本月B话榜": "测试",
        "上月B话榜": "测试",
        "年度B话榜": "测试",
        "历史B话榜": "2026-03-01~2026-03-02",
    }
    return Message(mapping.get(attr_name, "测试参数"))


def _build_event(attr_name: str, trigger_type: str):
    return DummyEvent(
        message_text=_message_text_for(attr_name, trigger_type),
        reply=DummyReply() if attr_name in {"speak"} else None,
        file_name="测试作品.mp3" if attr_name == "on_file_upload" else "文件.txt",
        sub_type="add" if trigger_type == "request" else "normal",
    )


def _build_call_kwargs(method, *, attr_name: str, trigger_type: str, bot: DummyBot):
    signature = _method_signature(method)
    kwargs = {}
    for name, param in signature.parameters.items():
        if name == "self":
            continue
        if name == "event":
            kwargs[name] = _build_event(attr_name, trigger_type)
            continue
        if name == "arg":
            kwargs[name] = _arg_message_for(attr_name)
            continue
        if name == "matcher":
            kwargs[name] = DummyMatcher()
            continue
        if name == "bot":
            kwargs[name] = bot
            continue
        if name == "user_id":
            kwargs[name] = 456
            continue
        if name == "group_id":
            kwargs[name] = 123456
            continue
        if param.default is not inspect._empty:
            continue
        kwargs[name] = "测试值"
    return kwargs


def _make_service_instance(service_cls, root: Path):
    service = object.__new__(service_cls)
    service.group = DummyGroup(root)
    service.config_file = root / f"{service_cls.__name__}.json"
    service._config = dict(getattr(service_cls, "default_config", {}))
    if "enabled" in service._config:
        service._config["enabled"] = True
    if service_cls.__name__ == "AIService":
        service._ai_manager = DummyAIManager()
    if service_cls.__name__ == "ActivityService":
        service.applications = {}
        service.activities = {}
    if service_cls.__name__ == "ChatService":
        service._liked_users = []
    if service_cls.__name__ == "ScheduleService":
        service._task_store = DummyTaskStore()
    if service_cls.__name__ == "CompositionService":
        service._config["auto_essence_enabled"] = False
    return service


def _install_runtime_stubs(monkeypatch, bot: DummyBot):
    driver = DummyDriver()

    async def _fake_wait_for(_timeout: int):
        return None

    async def _fake_wait_for_event(_timeout: int):
        return None

    async def _fake_run_flow(*args, **kwargs):
        return None

    async def _fake_get_name(*args, **kwargs):
        return "测试用户"

    monkeypatch.setattr("nonebot.get_bot", lambda: bot)
    monkeypatch.setattr("nonebot.get_driver", lambda: driver)
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_saa",
        SimpleNamespace(
            Text=DummySaaText,
            Image=DummySaaImage,
            MessageFactory=DummyMessageFactory,
            AggregatedMessageFactory=DummyMessageFactory,
            TargetQQGroup=DummyTargetQQGroup,
            enable_auto_select_bot=lambda: None,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_alconna",
        SimpleNamespace(UniMessage=DummyUniMessage, AlconnaMatcher=object),
    )
    monkeypatch.setitem(sys.modules, "nonebot_plugin_userinfo", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_dialectlist.time",
        SimpleNamespace(
            get_datetime_fromisoformat_with_timezone=lambda raw: __import__("datetime").datetime.fromisoformat(raw),
            get_datetime_now_with_timezone=lambda: __import__("datetime").datetime(2026, 3, 15, 12, 0, 0),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_dialectlist.config",
        SimpleNamespace(
            plugin_config=SimpleNamespace(
                excluded_people=[],
                show_text_rank=True,
                visualization=False,
                suffix=False,
                aggregate_transmission=False,
                string_format="{index}. {nickname}: {chatdatanum}\n",
                string_suffix="{timecost}",
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.vendors.nonebot_plugin_dialectlist.utils",
        SimpleNamespace(
            get_rank_image=lambda *args, **kwargs: b"",
            get_user_infos=lambda *args, **kwargs: asyncio.sleep(
                0,
                result=[SimpleNamespace(user_index=1, user_nickname="测试用户", user_bnum=3)],
            ),
            get_user_message_counts=lambda *args, **kwargs: asyncio.sleep(0, result=[["123456", 3]]),
            got_rank=lambda raw: [[str(item[0]), item[1]] for item in raw],
            persist_id2user_id=lambda ids: asyncio.sleep(0, result=ids),
        ),
    )

    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith(("src.services", "src.support")):
            continue
        if hasattr(module, "wait_for"):
            monkeypatch.setattr(module, "wait_for", _fake_wait_for, raising=False)
        if hasattr(module, "wait_for_event"):
            monkeypatch.setattr(module, "wait_for_event", _fake_wait_for_event, raising=False)
        if hasattr(module, "run_flow"):
            monkeypatch.setattr(module, "run_flow", _fake_run_flow, raising=False)
        if hasattr(module, "get_name_simple"):
            monkeypatch.setattr(module, "get_name_simple", _fake_get_name, raising=False)
        if hasattr(module, "get_name_by_id"):
            monkeypatch.setattr(module, "get_name_by_id", _fake_get_name, raising=False)

    monkeypatch.setattr("src.services._ai.ai_character_actions.get_voice_list_text", lambda: "1. 测试音色")
    monkeypatch.setattr("src.services._ai.ai_character_actions.get_voice_id_by_index", lambda _index: ("voice-1", "edge"))
    monkeypatch.setattr("src.services._ai.ai_control_actions.get_id", lambda _text: 123456)
    monkeypatch.setattr("src.services.vote.VoteController.vote", lambda self, event: asyncio.sleep(0))
    monkeypatch.setattr("src.services.wordcloud.register_runtime_callback", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.services.wordcloud.upsert_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.services.wordcloud.get_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.services.reminder.get_problem_solver_system", lambda *args, **kwargs: DummyReminderRuntime())
    monkeypatch.setattr("src.services.reminder.get_reminder_system", lambda *args, **kwargs: DummyReminderRuntime())
    monkeypatch.setattr("src.services.reminder.get_viewer", lambda *args, **kwargs: DummyReminderRuntime())
    monkeypatch.setattr("src.services.reminder.get_scoring_system", lambda *args, **kwargs: DummyReminderRuntime())


def _patch_service_specific_methods(monkeypatch, service, attr_name: str):
    service_name = service.__class__.__name__
    if service_name == "AIService":
        monkeypatch.setattr(service, "_check_should_respond", MethodType(lambda self, bot, event, ai: asyncio.sleep(0, result=False), service))
    if service_name == "BisonService":
        bison_module = sys.modules.get(service.__class__.__module__)
        if bison_module is not None:
            monkeypatch.setattr(
                bison_module,
                "BISON_RUNTIME_CONFIG_PATH",
                service.group.group_path / "bison_runtime.json",
                raising=False,
            )
    if service_name == "MultiNCMService":
        monkeypatch.setattr(service, "_ensure_runtime", MethodType(lambda self: asyncio.sleep(0), service))
    if service_name == "ResolverService":
        monkeypatch.setattr(service, "_ensure_runtime", MethodType(lambda self: asyncio.sleep(0), service))
        monkeypatch.setattr(service, "_dispatch_auto_resolve", MethodType(lambda self, event: asyncio.sleep(0, result=False), service))
        monkeypatch.setattr(service, "_sync_runtime_enabled", MethodType(lambda self: True, service))
    if service_name == "WordcloudService":
        monkeypatch.setattr(service, "_send_wordcloud", MethodType(lambda self, **kwargs: asyncio.sleep(0), service))
    if service_name == "DialectlistService":
        monkeypatch.setattr(service, "_ensure_deps", MethodType(lambda self: asyncio.sleep(0), service))
        monkeypatch.setattr(service, "_send_rank", MethodType(lambda self, **kwargs: asyncio.sleep(0), service))
    if service_name == "EmojimixService":
        monkeypatch.setattr(service, "_send_mix_result", MethodType(lambda self, **kwargs: asyncio.sleep(0), service))
    if service_name == "TarotService":
        monkeypatch.setattr(service, "draw_tarot_core", MethodType(lambda self, **kwargs: asyncio.sleep(0, result={"success": True}), service))
        monkeypatch.setattr(service, "fortune_core", MethodType(lambda self, **kwargs: asyncio.sleep(0, result={"success": True}), service))
        monkeypatch.setattr(service, "reading_core", MethodType(lambda self, **kwargs: asyncio.sleep(0, result={"success": True}), service))
    if service_name == "VisionService":
        monkeypatch.setattr(service, "_describe_image_api", MethodType(lambda self, *args, **kwargs: asyncio.sleep(0, result="图片描述"), service))
        monkeypatch.setattr(service, "_generate_image_api", MethodType(lambda self, *args, **kwargs: asyncio.sleep(0, result=(True, "https://example.com/generated.png")), service))


def _iter_non_tool_decorated_methods():
    inventory = _collect_runtime_decorated_methods()
    for key, trigger_type in (
        ("actions", "action"),
        ("messages", "message"),
        ("notices", "notice"),
        ("requests", "request"),
    ):
        for service_type, service_cls, attr_name, meta in inventory[key]:
            yield service_type, service_cls, attr_name, trigger_type, meta


def test_all_decorated_handlers_are_registered(boot_runtime, monkeypatch):
    inventory = _collect_runtime_decorated_methods()
    captured = {
        "actions": set(),
        "messages": set(),
        "notices": set(),
        "requests": set(),
    }

    monkeypatch.setattr(registry, "_handlers_registered", False)
    monkeypatch.setattr(
        registry,
        "_register_command",
        lambda service_enum, action, meta: captured["actions"].add((service_enum, action)),
    )
    monkeypatch.setattr(
        registry,
        "_register_message",
        lambda service_enum, action, meta: captured["messages"].add((service_enum, action)),
    )
    monkeypatch.setattr(
        registry,
        "_register_notice",
        lambda service_enum, action, meta: captured["notices"].add((service_enum, action)),
    )
    monkeypatch.setattr(
        registry,
        "_register_request",
        lambda service_enum, action, meta: captured["requests"].add((service_enum, action)),
    )

    registry.register_all_service_handlers()

    expected_actions = {(service_type, attr_name) for service_type, _, attr_name, _ in inventory["actions"]}
    expected_messages = {(service_type, attr_name) for service_type, _, attr_name, _ in inventory["messages"]}
    expected_notices = {(service_type, attr_name) for service_type, _, attr_name, _ in inventory["notices"]}
    expected_requests = {(service_type, attr_name) for service_type, _, attr_name, _ in inventory["requests"]}

    assert expected_actions <= captured["actions"]
    assert expected_messages <= captured["messages"]
    assert expected_notices <= captured["notices"]
    assert expected_requests <= captured["requests"]


def test_all_decorated_tools_are_registered_in_service_bridge(boot_runtime):
    inventory = _collect_runtime_decorated_methods()
    bridge = ServiceBridge()
    bridge.init_service_tools()

    registered_tools = {item["name"] for item in bridge.get_service_tools_info()}
    expected_ai_tools = {meta["name"] for _, _, _, meta in inventory["ai_tools"]}

    expected_service_tools = set()
    for service_type, _, attr_name, meta in inventory["actions"]:
        if meta.get("tool_callable", False) and not bridge._should_skip_service_tool(attr_name=attr_name, meta=meta):
            expected_service_tools.add(f"{service_type.value}_{attr_name}")

    assert expected_ai_tools <= registered_tools
    assert expected_service_tools <= registered_tools


def test_all_registered_tools_can_execute_through_bridge(boot_runtime):
    bridge = ServiceBridge()
    bridge.init_service_tools()

    expected_tool_names = set(bridge._service_tools.keys())

    service_objects = {}

    def make_stub(tool_name: str):
        async def _stub(self, **kwargs):
            return {"success": True, "message": f"{tool_name} ok", "data": {"kwargs": kwargs}}

        return _stub

    for tool_name, meta in bridge._service_tools.items():
        service_type = Services(meta.service_type)
        if service_type not in service_objects:
            service_objects[service_type] = type(
                f"DummyService_{service_type.value}",
                (),
                {
                    "enabled": True,
                    "group": SimpleNamespace(db=DummyDB()),
                    "get_disabled_tool_message": lambda self: "disabled",
                },
            )()
        service_obj = service_objects[service_type]
        if not hasattr(service_obj.__class__, meta.method_name):
            setattr(service_obj.__class__, meta.method_name, make_stub(tool_name))

    class DummyManager:
        async def get_service(self, group_id: int, service_type: Services):
            return service_objects[service_type]

    bridge.set_service_manager(DummyManager())

    failures = []
    context = {
        "group_id": 123,
        "user_id": 456,
        "member_role": "admin",
        "message": "测试消息",
        "message_id": 1001,
        "service_manager": bridge._service_manager,
    }

    for tool_name in sorted(expected_tool_names):
        tool = tool_registry.get_tool(tool_name)
        meta = bridge._service_tools[tool_name]
        args = _build_required_tool_args(tool.parameters, model_cls=meta.input_model)
        result = asyncio.run(tool_registry.execute_tool(tool_name, args, context))
        if result.get("success") is not True:
            failures.append((tool_name, result))

    assert failures == []


def test_all_check_enabled_wrapped_methods_short_circuit_when_disabled(boot_runtime, monkeypatch):
    async def _fake_wait_for(_timeout: int):
        return None

    monkeypatch.setattr("src.support.group.wait_for", _fake_wait_for)

    class DummyGroup:
        def __init__(self):
            self.sent = []
            self.self_id = 1

        async def send_msg(self, msg):
            self.sent.append(str(msg))

    failures = []
    for module_path, class_name, method_name in _collect_check_enabled_methods():
        module = importlib.import_module(module_path)
        service_cls = getattr(module, class_name)
        service = object.__new__(service_cls)
        service.group = DummyGroup()
        service._config = {"enabled": False}

        method = getattr(service_cls, method_name)
        try:
            asyncio.run(method(service))
        except Exception as exc:
            failures.append((module_path, class_name, method_name, f"raised: {exc}"))
            continue

        if not service.group.sent or "未开启" not in service.group.sent[0]:
            failures.append((module_path, class_name, method_name, service.group.sent))

    assert failures == []


def test_all_decorated_service_entrypoints_can_execute_directly(boot_runtime, monkeypatch, tmp_path):
    bot = DummyBot()
    _install_runtime_stubs(monkeypatch, bot)

    failures = []

    for service_type, service_cls, attr_name, trigger_type, _meta in _iter_non_tool_decorated_methods():
        service = _make_service_instance(service_cls, tmp_path / service_type.value / attr_name)
        _patch_service_specific_methods(monkeypatch, service, attr_name)
        method = getattr(service, attr_name)
        kwargs = _build_call_kwargs(method, attr_name=attr_name, trigger_type=trigger_type, bot=bot)

        try:
            asyncio.run(method(**kwargs))
        except RuntimeError as exc:
            if "dummy matcher finish" not in str(exc):
                failures.append((service_type.value, service_cls.__name__, attr_name, repr(exc)))
        except Exception as exc:
            failures.append((service_type.value, service_cls.__name__, attr_name, repr(exc)))

    assert failures == []
