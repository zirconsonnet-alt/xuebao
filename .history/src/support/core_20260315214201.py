"""共享支撑核心。"""

import inspect
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Dict, List, Literal, Optional, Protocol, Sequence

import nonebot
from pydantic import BaseModel


_SPEECH_URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
_SPEECH_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\u2300-\u23FF"
    "\u2600-\u27BF"
    "\u2B00-\u2BFF"
    "]+",
    flags=re.UNICODE,
)
_SPEECH_TRANSLATION_TABLE = str.maketrans(
    {
        "/": " ",
        "\\": " ",
        "*": " ",
        "_": " ",
        "#": " ",
        "~": " ",
        "`": " ",
        "|": " ",
        "【": " ",
        "】": " ",
        "「": " ",
        "」": " ",
        "『": " ",
        "』": " ",
        "（": " ",
        "）": " ",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
        "<": " ",
        ">": " ",
        "《": " ",
        "》": " ",
        "·": " ",
        "•": " ",
        "●": " ",
        "○": " ",
        "◆": " ",
        "◇": " ",
    }
)


def make_dict(role: str, content: Any) -> Dict[str, Any]:
    return {"role": role, "content": content}


def clean_markdown(text: str) -> str:
    if not text:
        return text

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"「\1」", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[图片]", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"【\1】", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*]\s+", "· ", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s*(.+)$", r"「\1」", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*]{3,}$", "——", text, flags=re.MULTILINE)
    return text


def clean_latex(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\$(.*?)\$", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\\[(.*?)\\\]", r"\1", text, flags=re.DOTALL)
    return text


def clean_for_speech(text: str) -> str:
    if not text:
        return text
    text = _SPEECH_URL_RE.sub(" ", text)
    text = text.replace("[图片]", "图片")
    text = text.replace("[语音]", "语音")
    text = text.replace("\u200d", "")
    text = text.replace("\ufe0f", "")
    text = _SPEECH_EMOJI_RE.sub(" ", text)
    text = text.translate(_SPEECH_TRANSLATION_TABLE)
    text = re.sub(r"([，。！？；：,.!?;:])\1+", r"\1", text)
    text = re.sub(r"\s*([，。！？；：,.!?;:])\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def process_text(text: str, for_speech: bool = False) -> str:
    text = clean_markdown(text)
    text = clean_latex(text)
    if for_speech:
        return clean_for_speech(text)
    return text


class TTSType(str, Enum):
    LOCAL = "local"
    TENCENT = "tencent"
    API = "api"


class ServerType(str, Enum):
    GROUP = "group"
    PRIVATE = "private"

class Activities(Enum):
    CREATED_TOPICS = "created_topics"
    CREATED_ACTIVITIES = "created_activities"
    VOTED_TOPICS = "voted_topics"
    JOINED_ACTIVITIES = "joined_activities"
    PUBLISHED_WORKS = "published_works"


class Services(Enum):
    Speech = "speech"
    Activity = "activity"
    Request = "request"
    File = "file"
    Title = "title"
    Vote = "vote"
    Chat = "chat"
    Info = "info"
    Composition = "composition"
    Schedule = "schedule"
    Wordcloud = "wordcloud"
    Dialectlist = "dialectlist"
    Emojimix = "emojimix"
    AI = "ai"
    Tarot = "tarot"
    Meme = "meme"
    Vision = "vision"
    SignIn = "sign_in"
    Werewolf = "werewolf"
    MathGame = "math_game"
    TurtleSoup = "turtle_soup"
    Whateat = "whateat"
    Reminder = "reminder"
    Bison = "bison"
    Multincm = "multincm"

    @property
    def chinese_name(self) -> str:
        chinese_names = {
            Services.Speech: "语音服务",
            Services.Activity: "活动服务",
            Services.Request: "入群管理服务",
            Services.File: "文件服务",
            Services.Title: "头衔服务",
            Services.Vote: "投票服务",
            Services.Chat: "聊天互动服务",
            Services.Info: "基础信息服务",
            Services.Composition: "作品发布服务",
            Services.Schedule: "定时服务",
            Services.Wordcloud: "词云服务",
            Services.Dialectlist: "B话榜服务",
            Services.Emojimix: "Emoji合成服务",
            Services.AI: "AI助手服务",
            Services.Tarot: "塔罗牌服务",
            Services.Meme: "表情包服务",
            Services.Vision: "视觉服务",
            Services.SignIn: "签到服务",
            Services.Werewolf: "雪豹杀服务",
            Services.MathGame: "24点服务",
            Services.TurtleSoup: "海龟汤服务",
            Services.Whateat: "吃喝推荐服务",
            Services.Reminder: "提醒服务",
            Services.Bison: "Bison订阅服务",
            Services.Multincm: "点歌服务",
        }
        return chinese_names.get(self, self.value)


@dataclass(frozen=True)
class SessionSnapshot:
    session_key: str
    flow: str
    step: int
    data: Dict[str, Any]
    version: int
    status: str
    expires_at: Optional[str] = None

    def is_active(self, *, now: Optional[datetime] = None) -> bool:
        if self.status != "active":
            return False
        if not self.expires_at:
            return True
        now_dt = now or datetime.now()
        try:
            return datetime.fromisoformat(self.expires_at) > now_dt
        except ValueError:
            return False


@dataclass(frozen=True)
class AuditEvent:
    group_id: int
    actor_id: Optional[int]
    action: str
    subject_type: Optional[str]
    subject_id: Optional[str]
    session_key: Optional[str]
    result: str
    context: Optional[Dict[str, Any]] = None

    def validate(self) -> None:
        if not self.action:
            raise ValueError("audit action must not be empty")
        if not self.result:
            raise ValueError("audit result must not be empty")


class Clock(Protocol):
    def now(self) -> datetime:
        ...


class MessagingGateway(Protocol):
    async def send_group(self, *, group_id: int, message: Any) -> None:
        ...

    async def send_private(self, *, user_id: int, message: Any) -> None:
        ...


class LlmGateway(Protocol):
    async def chat(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        extra: Dict[str, Any] | None = None,
    ) -> str:
        ...


LlmMessages = List[Dict[str, Any]]


class ToolGateway(Protocol):
    async def call(
        self,
        *,
        name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        ...


class VisionGateway(Protocol):
    async def describe_image(self, *, image_url: str, prompt: str | None = None) -> str:
        ...

    async def describe_video(self, *, video_url: str, prompt: str | None = None) -> str:
        ...

    async def generate_image(self, *, prompt: str) -> str:
        ...


class AuditRepository(Protocol):
    def record_log(
        self,
        *,
        group_id: int,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
        result: str,
    ) -> None:
        ...

    def record_event(
        self,
        *,
        group_id: int,
        actor_id: Optional[int],
        action: str,
        subject_type: Optional[str],
        subject_id: Optional[str],
        session_key: Optional[str],
        result: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...


class GroupGateway(Protocol):
    def get_self_id(self) -> int:
        ...

    async def send_msg(self, group_id: int, msg: Any) -> None:
        ...

    async def delete_msg(self, message_id: int) -> None:
        ...

    async def set_msg(self, message_id: int) -> None:
        ...

    async def ban(self, group_id: int, user_id: int, duration: int) -> None:
        ...

    async def whole_ban(self, group_id: int, enable: bool) -> None:
        ...

    async def get_group_member_info(self, group_id: int, user_id: int) -> Any:
        ...

    async def send_forward_msg(self, group_id: int, nodes: Any) -> None:
        ...

    async def set_group_add(
        self,
        flag: str,
        sub_type: str,
        approve: bool,
        reason: str | None,
    ) -> None:
        ...

    async def send_notice(self, group_id: int, msg: Any) -> None:
        ...

    async def del_notice(self, group_id: int, notice_id: int) -> None:
        ...

    async def get_notice(self, group_id: int) -> Any:
        ...

    async def delete_file(self, group_id: int, file_id: str, busid: int) -> None:
        ...

    async def upload_file(self, group_id: int, path: str, name: str, folder_id: str) -> None:
        ...

    async def move_file(
        self,
        group_id: int,
        file_id: str,
        current_parent_directory: str,
        target_parent_directory: str,
    ) -> None:
        ...

    async def get_group_file_url(self, group_id: int, file_id: str, busid: int) -> Dict[str, Any]:
        ...

    async def get_group_root_files(self, group_id: int) -> Dict[str, Any]:
        ...

    async def get_group_files_by_folder(
        self,
        group_id: int,
        folder_id: str,
        file_count: int,
    ) -> Dict[str, Any]:
        ...

    async def create_group_file_folder(
        self,
        group_id: int,
        folder_name: str,
        parent_id: str,
    ) -> Dict[str, Any]:
        ...

    async def kick(self, group_id: int, user_id: int) -> None:
        ...

    async def set_group_special_title(
        self,
        group_id: int,
        user_id: int,
        special_title: str,
    ) -> None:
        ...


class IdempotencyRepository(Protocol):
    def reserve(
        self,
        *,
        idem_key: str,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
    ) -> bool:
        ...


class MemberStatsRepository(Protocol):
    def update_member_stats(self, member_id: int, action: Activities) -> None:
        ...


class SessionRepository(Protocol):
    def get_session(self, session_key: str) -> Optional[SessionSnapshot]:
        ...

    def create_session(
        self,
        *,
        session_key: str,
        flow: str,
        owner_id: Optional[int],
        ttl_seconds: int,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        ...

    def update_session_step(
        self,
        *,
        session_key: str,
        step: int,
        patch_data: Optional[Dict[str, Any]],
        expected_version: int,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        ...

    def update_session_status(self, session_key: str, status: str) -> bool:
        ...

    def cleanup_expired_sessions(self) -> int:
        ...


class TopicRepository(Protocol):
    def add_topic(self, proposer_id: int, content: str) -> int:
        ...

    def record_supporters(self, topic_id: int, supporter_ids: List[int]) -> None:
        ...

    def get_all_topics(self) -> List[Dict[str, Any]]:
        ...


class VoteRepository(Protocol):
    def reserve_vote_record(
        self,
        *,
        session_key: str,
        user_id: int,
        option_idx: int,
    ) -> bool:
        ...


CATEGORY_FEATURE_CONFIG: Dict[str, Dict[str, Any]] = {
    "tarot": {
        "service_type": Services.Tarot,
        "disabled_msg": "塔罗牌服务未开启，请使用【开启塔罗牌服务】命令",
    },
    "memes": {
        "service_type": Services.Meme,
        "disabled_msg": "表情包服务未开启，请使用【开启表情包服务】命令",
    },
    "schedule": {
        "service_type": Services.Schedule,
        "disabled_msg": "定时服务未开启，请使用【开启定时服务】命令",
    },
    "vision": {
        "service_type": Services.Vision,
        "disabled_msg": "视觉服务未开启，请使用【开启视觉服务】命令",
    },
}


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Any
    require_admin: bool = False
    require_owner: bool = False
    category: str = "general"
    triggers: List[str] = field(default_factory=list)
    gate: Optional[Dict[str, Any]] = None


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self._initialized = False

    def register(self, tool: ToolDefinition):
        self.tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        if name in self.tools:
            del self.tools[name]
            return True
        return False

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self.tools.get(name)

    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        return [tool for tool in self.tools.values() if tool.category == category]

    def get_openai_tools_schema(
        self,
        exclude_categories: List[str] = None,
        exclude_tool_names: List[str] = None,
    ) -> List[Dict[str, Any]]:
        exclude_categories = exclude_categories or []
        exclude_tool_names = set(exclude_tool_names or [])
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools.values()
            if tool.category not in exclude_categories and tool.name not in exclude_tool_names
        ]

    async def check_permission(self, tool: ToolDefinition, context: Dict[str, Any]) -> tuple[bool, str]:
        if not tool.require_admin and not tool.require_owner:
            return True, ""

        group_id = context.get("group_id")
        user_id = context.get("user_id")
        member_role = context.get("member_role") or context.get("role")
        if member_role:
            role = str(member_role).lower()
            if tool.require_owner and role != "owner":
                return False, "此操作需要群主权限"
            if tool.require_admin and role == "member":
                return False, "此操作需要管理员权限"
            return True, ""

        if not group_id or not user_id:
            return False, "无法获取用户信息"

        try:
            bot = nonebot.get_bot()
            member_info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
            role = member_info.get("role", "member")
            if tool.require_owner and role != "owner":
                return False, "此操作需要群主权限"
            if tool.require_admin and role == "member":
                return False, "此操作需要管理员权限"
            return True, ""
        except Exception as exc:
            return False, f"权限检查失败: {exc}"

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        tool = self.get_tool(name)
        context = context or {}
        if not tool:
            return {"success": False, "message": f"未找到工具: {name}"}

        has_permission, error_msg = await self.check_permission(tool, context)
        if not has_permission:
            return {"success": False, "message": f"权限不足: {error_msg}"}

        if tool.category in CATEGORY_FEATURE_CONFIG:
            cfg = CATEGORY_FEATURE_CONFIG[tool.category]
            service_manager = context.get("service_manager")
            group_id = context.get("group_id")
            if service_manager and group_id:
                try:
                    service = await service_manager.get_service(group_id, cfg["service_type"])
                    if not getattr(service, "enabled", False):
                        return {"success": False, "message": cfg["disabled_msg"]}
                except Exception:
                    pass

        try:
            result = await tool.handler(arguments, context)
            if isinstance(result, dict):
                if "success" in result:
                    if "data" not in result:
                        result["data"] = {"tool": name, "args": arguments}
                    return result
                if "error" in result:
                    return {
                        "success": False,
                        "message": result["error"],
                        "data": {"tool": name, "error": result["error"]},
                    }
                return {"success": True, "message": "执行成功", "data": {"tool": name, "result": result}}
            return {
                "success": True,
                "message": str(result) if result else "执行成功",
                "data": {"tool": name, "result": result},
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"执行失败: {exc}",
                "data": {"tool": name, "exception": str(exc)},
            }

    def get_tools_prompt(
        self,
        exclude_categories: List[str] = None,
        exclude_tool_names: List[str] = None,
    ) -> str:
        exclude_categories = exclude_categories or []
        exclude_tool_names = set(exclude_tool_names or [])
        lines: List[str] = []
        for tool in self.tools.values():
            if tool.category in exclude_categories:
                continue
            if tool.name in exclude_tool_names:
                continue
            if tool.triggers:
                lines.append(f"- {'/'.join(tool.triggers)}：使用 {tool.name} 工具")
            else:
                lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)


tool_registry = ToolRegistry()


def ai_tool(
    name: str,
    desc: str,
    parameters: Dict[str, Any] = None,
    input_model: Optional[type] = None,
    gate: Optional[Dict[str, Any]] = None,
    require_admin: bool = False,
    require_owner: bool = False,
    category: str = "service",
    triggers: List[str] = None,
):
    def decorator(func):
        func.__ai_tool__ = {
            "name": name,
            "desc": desc,
            "parameters": parameters or {"type": "object", "properties": {}, "required": []},
            "input_model": input_model,
            "gate": gate,
            "require_admin": require_admin,
            "require_owner": require_owner,
            "category": category,
            "triggers": triggers or [],
        }

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)

        wrapper.__ai_tool__ = func.__ai_tool__
        return wrapper

    return decorator


def build_tool_parameters(
    custom_params: Dict[str, Any] = None,
    include_user_id: bool = False,
    include_group_id: bool = False,
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []

    if include_user_id:
        properties["user_id"] = {
            "type": "integer",
            "description": "目标用户的 QQ 号，不填则使用当前说话的用户",
        }
    if include_group_id:
        properties["group_id"] = {
            "type": "integer",
            "description": "目标群号，不填则使用当前群",
        }
    if custom_params:
        if "properties" in custom_params:
            properties.update(custom_params["properties"])
        if "required" in custom_params:
            required.extend(custom_params["required"])

    return {"type": "object", "properties": properties, "required": required}


@dataclass
class ServiceToolMeta:
    service_type: str
    method_name: str
    cmd: str
    desc: str
    require_admin: bool
    require_owner: bool
    parameters: Dict[str, Any]
    category: str = "service"
    triggers: List[str] = None
    input_model: Optional[type] = None
    gate: Optional[Dict[str, Any]] = None


class ServiceBridge:
    def __init__(self):
        self._service_tools: Dict[str, ServiceToolMeta] = {}
        self._service_manager = None
        self._initialized = False

    def set_service_manager(self, manager):
        self._service_manager = manager

    def init_service_tools(self):
        try:
            from src.services.base import BaseService
        except ImportError:
            print("[ServiceBridge] 无法导入服务模块，跳过服务工具初始化")
            return

        before_count = len(self._service_tools)

        def walk_subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from walk_subclasses(sub)

        for service_cls in walk_subclasses(BaseService):
            service_type = getattr(service_cls, "service_type", None)
            if not service_type:
                continue
            self._scan_ai_tool_methods(service_cls, service_type)
            self._scan_service_class(service_cls, service_type)

        current_count = len(self._service_tools)
        if not self._initialized or current_count != before_count:
            print(f"[ServiceBridge] 已注册 {current_count} 个服务工具")
        self._initialized = True

    def _scan_ai_tool_methods(self, service_cls: type, service_type):
        for attr_name in dir(service_cls):
            method = getattr(service_cls, attr_name, None)
            if not method:
                continue
            ai_tool_meta = getattr(method, "__ai_tool__", None)
            if not ai_tool_meta:
                continue

            tool_name = ai_tool_meta["name"]
            if tool_name in self._service_tools:
                continue

            tool_meta = ServiceToolMeta(
                service_type=service_type.value,
                method_name=attr_name,
                cmd=tool_name,
                desc=ai_tool_meta["desc"],
                require_admin=ai_tool_meta.get("require_admin", False),
                require_owner=ai_tool_meta.get("require_owner", False),
                parameters=ai_tool_meta.get("parameters", {"type": "object", "properties": {}, "required": []}),
                category=ai_tool_meta.get("category", "service"),
                triggers=ai_tool_meta.get("triggers", []),
                input_model=ai_tool_meta.get("input_model"),
                gate=ai_tool_meta.get("gate"),
            )
            self._service_tools[tool_name] = tool_meta
            self._register_ai_tool(tool_name, tool_meta)
            print(f"[ServiceBridge] 注册 @ai_tool: {tool_name} ({service_cls.__name__}.{attr_name})")

    def _register_ai_tool(self, tool_name: str, meta: ServiceToolMeta):
        async def handler(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return await self._execute_ai_tool_method(tool_name, args, context)

        tool_registry.register(
            ToolDefinition(
                name=tool_name,
                description=meta.desc,
                parameters=meta.parameters,
                handler=handler,
                require_admin=meta.require_admin,
                require_owner=meta.require_owner,
                category=meta.category,
                triggers=meta.triggers or [],
                gate=meta.gate,
            )
        )

    def _validate_tool_args(self, model_cls, args: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            if hasattr(model_cls, "model_validate"):
                model = model_cls.model_validate(args or {})
            else:
                model = model_cls.parse_obj(args or {})
        except Exception as exc:
            return None, str(exc)
        if hasattr(model, "model_dump"):
            return model.model_dump(), None
        return model.dict(), None

    def _build_service_disabled_result(self, service: Any) -> Dict[str, Any]:
        if hasattr(service, "get_disabled_tool_message"):
            message = service.get_disabled_tool_message()
        else:
            service_type = getattr(service, "service_type", None)
            service_name = getattr(service_type, "chinese_name", "服务")
            message = f"{service_name}未开启"
        return {"success": False, "message": message}

    async def _execute_ai_tool_method(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        meta = self._service_tools.get(tool_name)
        if not meta:
            return {"success": False, "message": f"未找到服务工具: {tool_name}"}

        group_id = context.get("group_id")
        if not group_id:
            return {"success": False, "message": "无法获取群ID"}
        if not self._service_manager:
            return {"success": False, "message": "服务管理器未初始化"}

        try:
            service_type = next((service for service in Services if service.value == meta.service_type), None)
            if not service_type:
                return {"success": False, "message": f"未找到服务类型: {meta.service_type}"}
            service = await self._service_manager.get_service(group_id, service_type)
            if hasattr(service, "enabled") and not bool(getattr(service, "enabled", False)):
                return self._build_service_disabled_result(service)
            method = getattr(service, meta.method_name, None)
            if not method:
                return {"success": False, "message": f"服务方法不存在: {meta.method_name}"}

            validated_args = args or {}
            if meta.input_model:
                validated_args, err = self._validate_tool_args(meta.input_model, args or {})
                if err:
                    return {"success": False, "message": f"参数校验失败: {err}"}

            call_kwargs = {
                "user_id": context.get("user_id"),
                "group_id": group_id,
                "image_registry": context.get("image_registry", {}),
                "video_registry": context.get("video_registry", {}),
            }
            if validated_args:
                call_kwargs.update(validated_args)

            result = await method(**call_kwargs)
            if isinstance(result, dict) and "success" in result:
                return result
            return {
                "success": True,
                "message": str(result) if result else "执行成功",
                "data": result,
            }
        except Exception as exc:
            traceback.print_exc()
            return {"success": False, "message": f"执行失败: {exc}"}

    def _scan_service_class(self, service_cls: type, service_type):
        for attr_name in dir(service_cls):
            method = getattr(service_cls, attr_name, None)
            if not method:
                continue
            meta = getattr(method, "__service_action__", None)
            if not meta or not meta.get("tool_callable", False):
                continue
            if self._should_skip_service_tool(attr_name=attr_name, meta=meta):
                continue

            tool_name = f"{service_type.value}_{attr_name}"
            parameters = self._build_parameters(method, meta)
            tool_meta = ServiceToolMeta(
                service_type=service_type.value,
                method_name=attr_name,
                cmd=meta.get("cmd", attr_name),
                desc=meta.get("desc", ""),
                require_admin=meta.get("require_admin", False),
                require_owner=meta.get("require_owner", False),
                parameters=parameters,
            )
            self._service_tools[tool_name] = tool_meta
            self._register_tool(tool_name, tool_meta)

    def _should_skip_service_tool(self, *, attr_name: str, meta: Dict[str, Any]) -> bool:
        cmd = str(meta.get("cmd", "") or "").strip()
        if attr_name.startswith("toggle_"):
            return True
        if "开关" in cmd:
            return True
        return False

    def _build_parameters(self, method: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sig = inspect.signature(method)
        properties: Dict[str, Any] = {}
        required: List[str] = []
        if "arg" in sig.parameters:
            properties["arg_text"] = {
                "type": "string",
                "description": "命令参数文本",
            }
            if meta and meta.get("need_arg", False):
                required.append("arg_text")
        if "event" in sig.parameters:
            properties["message"] = {
                "type": "string",
                "description": "原始消息文本，可选",
            }
            properties["reply_text"] = {
                "type": "string",
                "description": "被回复消息的文本，可选",
            }
            properties["reply_message_id"] = {
                "type": "integer",
                "description": "被回复消息的消息 ID，可选",
            }
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "event", "arg", "matcher"):
                continue

            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == float:
                    param_type = "number"
            properties[param_name] = {"type": param_type, "description": f"参数 {param_name}"}
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        return {"type": "object", "properties": properties, "required": required}

    def _register_tool(self, tool_name: str, meta: ServiceToolMeta):
        async def handler(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            return await self._execute_service_method(tool_name, args, context)

        tool_registry.register(
            ToolDefinition(
                name=tool_name,
                description=meta.desc or f"执行 {meta.cmd}",
                parameters=meta.parameters,
                handler=handler,
                require_admin=meta.require_admin,
                require_owner=meta.require_owner,
                category="service",
            )
        )

    async def _execute_service_method(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        meta = self._service_tools.get(tool_name)
        if not meta:
            return {"success": False, "message": f"未找到服务工具: {tool_name}"}
        group_id = context.get("group_id")
        if not group_id:
            return {"success": False, "message": "无法获取群ID"}
        if not self._service_manager:
            return {"success": False, "message": "服务管理器未初始化"}

        try:
            service_type = next((service for service in Services if service.value == meta.service_type), None)
            if not service_type:
                return {"success": False, "message": f"未找到服务类型: {meta.service_type}"}

            service = await self._service_manager.get_service(group_id, service_type)
            if (
                hasattr(service, "enabled")
                and not bool(getattr(service, "enabled", False))
                and meta.method_name not in ("enable_service", "disable_service")
            ):
                return self._build_service_disabled_result(service)
            method = getattr(service, meta.method_name, None)
            if not method:
                return {"success": False, "message": f"服务方法不存在: {meta.method_name}"}

            call_kwargs: Dict[str, Any] = {}
            method_signature = inspect.signature(method)
            if "event" in method_signature.parameters:
                call_kwargs["event"] = self._create_mock_event(context, args)
            if "arg" in method_signature.parameters:
                call_kwargs["arg"] = self._create_mock_arg(args, context)

            for param_name in method_signature.parameters:
                if param_name == "self":
                    continue
                if param_name in ("event", "arg", "matcher"):
                    continue
                elif param_name in args:
                    call_kwargs[param_name] = args[param_name]

            result = await method(**call_kwargs)
            if isinstance(result, dict) and "success" in result:
                return result
            return {"success": True, "message": f"已执行: {meta.cmd}", "data": result}
        except Exception as exc:
            traceback.print_exc()
            return {"success": False, "message": f"执行失败: {exc}"}

    def _create_mock_arg(self, args: Dict[str, Any], context: Dict[str, Any]):
        @dataclass
        class MockArg:
            text: str = ""

            def extract_plain_text(self):
                return self.text

            def __str__(self):
                return self.text

            def __iter__(self):
                return iter(())

        text = str(
            args.get("arg_text")
            or args.get("message")
            or context.get("message")
            or ""
        )
        return MockArg(text=text)

    def _create_mock_event(self, context: Dict[str, Any], args: Optional[Dict[str, Any]] = None):
        args = args or {}

        @dataclass
        class MockMessage:
            text: str = ""

            def extract_plain_text(self):
                return self.text

            def __str__(self):
                return self.text

            def __iter__(self):
                return iter(())

        @dataclass
        class MockReply:
            message_text: str = ""
            message_id: int = 0

            @property
            def message(self):
                return MockMessage(text=self.message_text)

        @dataclass
        class MockEvent:
            group_id: int
            user_id: int
            message_text: str = ""
            reply: Optional[MockReply] = None
            sender: Any = None
            message_id: int = 0
            self_id: int = 0

            def get_message(self):
                return MockMessage(text=self.message_text)

        @dataclass
        class MockSender:
            role: str = "member"

        reply_text = str(args.get("reply_text") or "")
        reply_message_id = args.get("reply_message_id")
        reply = None
        if reply_text or reply_message_id is not None:
            reply = MockReply(
                message_text=reply_text,
                message_id=int(reply_message_id or 0),
            )

        message_text = str(args.get("message") or context.get("message") or "")
        role = str(context.get("member_role") or context.get("role") or "member")
        return MockEvent(
            group_id=context.get("group_id", 0),
            user_id=context.get("user_id", 0),
            message_text=message_text,
            reply=reply,
            sender=MockSender(role=role),
            message_id=int(context.get("message_id", 0) or 0),
            self_id=int(context.get("self_id", 0) or 0),
        )

    def get_service_tools_info(self) -> List[Dict[str, str]]:
        return [
            {
                "name": name,
                "cmd": meta.cmd,
                "desc": meta.desc,
                "require_admin": meta.require_admin,
            }
            for name, meta in self._service_tools.items()
        ]


service_bridge = ServiceBridge()


def match_any_pattern(patterns: List[str], text: str) -> bool:
    if not patterns or not text:
        return False
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def match_any_keyword(keywords: List[str], text: str) -> bool:
    if not keywords or not text:
        return False
    haystack = str(text).casefold()
    for keyword in keywords:
        if not keyword:
            continue
        needle = str(keyword).casefold()
        if needle and needle in haystack:
            return True
    return False


def gate_hit(gate: Dict[str, Any], user_text: str, assistant_text: str) -> bool:
    if not gate or not user_text or not assistant_text:
        return False

    user_patterns = gate.get("user_patterns") or []
    assistant_patterns = gate.get("assistant_patterns") or []
    regex_ok = (
        bool(user_patterns)
        and bool(assistant_patterns)
        and match_any_pattern(user_patterns, user_text)
        and match_any_pattern(assistant_patterns, assistant_text)
    )
    if regex_ok:
        return True

    user_keywords = gate.get("user_keywords") or gate.get("keywords") or []
    assistant_keywords = gate.get("assistant_keywords") or gate.get("keywords") or []
    return (
        bool(user_keywords)
        and bool(assistant_keywords)
        and match_any_keyword(user_keywords, user_text)
        and match_any_keyword(assistant_keywords, assistant_text)
    )


try:
    from mcp.client.session import ClientSession
    from mcp.types import Implementation
    from mcp.client.sse import sse_client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.websocket import websocket_client

    _MCP_IMPORT_ERROR = None
except ImportError as exc:
    ClientSession = Any
    Implementation = None
    StdioServerParameters = None
    sse_client = None
    stdio_client = None
    streamable_http_client = None
    websocket_client = None
    _MCP_IMPORT_ERROR = exc


_IDENT_RE = re.compile(r"[^a-zA-Z0-9_]+")


class BaseDTO(BaseModel):
    """共享 DTO 基类。"""


class EmptyInput(BaseDTO):
    pass


class GetGroupMemberListInput(BaseDTO):
    limit: Optional[int] = 10


class GetUserInfoInput(BaseDTO):
    user_id: Optional[int] = None


class GetGroupMemberInfoInput(BaseDTO):
    user_id: Optional[int] = None


class GetGroupHonorInput(BaseDTO):
    type: Literal[
        "talkative",
        "performer",
        "legend",
        "strong_newbie",
        "emotion",
        "all",
    ] = "all"


class GenerateMemeInput(BaseDTO):
    keyword: str
    texts: Optional[List[str]] = None
    user_ids: Optional[List[int]] = None


class ListMemesInput(BaseDTO):
    search: Optional[str] = None
    limit: Optional[int] = 20


class DescribeUserAvatarInput(BaseDTO):
    user_id: Optional[int] = None
    prompt: Optional[str] = None


class DescribeImageInput(BaseDTO):
    image_id: str
    prompt: Optional[str] = None


class DescribeVideoInput(BaseDTO):
    video_id: str
    prompt: Optional[str] = None


class GenerateImageInput(BaseDTO):
    prompt: str


class CreateReminderInput(BaseDTO):
    message: str
    time: str
    task_type: Literal["daily", "once"] = "once"
    task_name: Optional[str] = None


class TarotReadingInput(BaseDTO):
    card_name: Optional[str] = None


class ProvisionRequest(BaseDTO):
    qq_uin: str
    display_name: Optional[str] = None


class ConfirmRequest(BaseDTO):
    qq_uin: str


class LoginRequest(BaseDTO):
    qq_uin: str
    secret: str


