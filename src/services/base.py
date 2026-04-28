import copy
import inspect
import json
import re
from pathlib import Path
from abc import ABC
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Dict, Optional

from nonebot.adapters.onebot.v11 import Message

from src.support.core import Services

if TYPE_CHECKING:
    from src.support.group import GroupContext


@dataclass
class ServiceCommand:
    cmd: str
    handler_name: str
    need_arg: bool
    permission: Optional[str]
    rule: Optional[str]
    priority: int
    block: bool
    desc: str
    allow_when_disabled: bool = False


@dataclass
class ServiceHandler:
    """通用的服务处理器元数据"""

    handler_name: str
    trigger_type: str
    priority: int
    block: bool
    event_type: Optional[str]
    desc: str


@dataclass
class ServiceConfigOption:
    """服务配置项声明，用于统一驱动 /设置 中的配置项管理。"""

    key: str
    title: str
    description: str = ""
    type: str = "bool"
    group: str = "基础设置"
    default: Any = None
    placeholder: str = ""
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    choices: Optional[list[dict[str, Any]]] = None

    @classmethod
    def from_data(cls, raw: Any) -> "ServiceConfigOption":
        if isinstance(raw, cls):
            return copy.deepcopy(raw)
        if isinstance(raw, dict):
            data = dict(raw)
            choices = data.get("choices")
            if isinstance(choices, list):
                data["choices"] = [dict(item) for item in choices if isinstance(item, dict)]
            return cls(**data)
        raise TypeError(f"无法解析服务配置项声明：{raw!r}")


class _ServiceMenuMatcher:
    """为服务内菜单提供最小 matcher 能力，兼容 CommandHandler 类流程。"""

    def __init__(self, service: "BaseService"):
        self._service = service

    async def send(self, message: Any):
        await self._service.group.send_msg(message)

    async def finish(self, message: Any = ""):
        if message:
            await self.send(message)
        from nonebot.exception import FinishedException

        raise FinishedException


def service_action(
    *,
    cmd: str,
    aliases: Optional[set[str]] = None,
    desc: str = "",
    need_arg: bool = False,
    permission=None,
    rule=None,
    priority: int = 2,
    block: bool = True,
    visible: bool = True,
    tool_callable: bool = False,
    require_admin: bool = False,
    require_owner: bool = False,
    allow_when_disabled: bool = False,
    record_ai_context: bool = False,
    ai_context_label: str = "",
    ai_context_include_arg: bool = False,
    points_cost: int = 0,
    points_reason: str = "",
    points_insufficient_message: str = "",
    defer_points_charge: bool = False,
):
    def decorator(func):
        setattr(
            func,
            "__service_action__",
            {
                "cmd": cmd,
                "aliases": aliases or set(),
                "desc": desc,
                "need_arg": need_arg,
                "permission": permission,
                "rule": rule,
                "priority": priority,
                "block": block,
                "visible": visible,
                "trigger_type": "command",
                "tool_callable": tool_callable,
                "require_admin": require_admin,
                "require_owner": require_owner,
                "allow_when_disabled": allow_when_disabled,
                "record_ai_context": record_ai_context,
                "ai_context_label": ai_context_label,
                "ai_context_include_arg": ai_context_include_arg,
                "points_cost": points_cost,
                "points_reason": points_reason,
                "points_insufficient_message": points_insufficient_message,
                "defer_points_charge": defer_points_charge,
            },
        )
        return func

    return decorator


def service_message(
    *,
    desc: str = "",
    rule=None,
    priority: int = 0,
    block: bool = False,
):
    def decorator(func):
        setattr(
            func,
            "__service_message__",
            {
                "desc": desc,
                "rule": rule,
                "priority": priority,
                "block": block,
                "trigger_type": "message",
            },
        )
        return func

    return decorator


def service_notice(
    *,
    desc: str = "",
    event_type: str = None,
    priority: int = 5,
    block: bool = True,
):
    def decorator(func):
        setattr(
            func,
            "__service_notice__",
            {
                "desc": desc,
                "event_type": event_type,
                "priority": priority,
                "block": block,
                "trigger_type": "notice",
            },
        )
        return func

    return decorator


def service_request(
    *,
    desc: str = "",
    event_type: str = None,
    priority: int = 5,
    block: bool = False,
):
    def decorator(func):
        setattr(
            func,
            "__service_request__",
            {
                "desc": desc,
                "event_type": event_type,
                "priority": priority,
                "block": block,
                "trigger_type": "request",
            },
        )
        return func

    return decorator


def config_property(key: str):
    def getter(self):
        return self.get_config_value(key)

    def setter(self, value):
        self.set_config_value(key, value)

    return property(getter, setter)


class BaseService(ABC):
    service_type: Services
    default_config: Dict[str, Any] = {}
    settings_schema: list[Any] = []
    service_toggle_name: Optional[str] = None
    enable_requires_bot_admin: bool = False
    disable_requires_bot_admin: bool = False
    enabled = config_property("enabled")

    def __init__(self, group: "GroupContext"):
        self.group = group
        self.config_file = group.group_path / f"{self.service_type.name}_service.json"
        self._migrate_legacy_config_file_to_db()
        self._config = self._load_config()

    def _migrate_legacy_config_file_to_db(self) -> bool:
        return migrate_legacy_service_config_file(
            group_db=self.group.db,
            service_type=self.service_type,
            config_file=self.config_file,
        )

    @classmethod
    def get_service_switch_name(cls) -> str:
        if cls.service_toggle_name:
            return str(cls.service_toggle_name)
        service_type = getattr(cls, "service_type", None)
        if service_type:
            return service_type.chinese_name
        return "服务"

    @classmethod
    def get_enable_command_name(cls) -> str:
        return f"开启{cls.get_service_switch_name()}"

    @classmethod
    def get_disable_command_name(cls) -> str:
        return f"关闭{cls.get_service_switch_name()}"

    @classmethod
    def get_service_entry_command_name(cls) -> str:
        return cls.get_service_switch_name()

    @classmethod
    def get_explicit_service_entry_action_name(cls) -> Optional[str]:
        entry_command = cls.get_service_entry_command_name()
        for attr_name in dir(cls):
            if attr_name == "service_entry":
                continue
            func = getattr(cls, attr_name, None)
            meta = getattr(func, "__service_action__", None)
            if meta and meta.get("cmd") == entry_command:
                return attr_name
        return None

    @classmethod
    def get_default_action_name(cls) -> str:
        return cls.get_explicit_service_entry_action_name() or "service_entry"

    def get_disabled_notice(self) -> str:
        return (
            f"🚫 本群{self.get_service_switch_name()}未开启。\n"
            f"管理员请使用『{self.get_enable_command_name()}』或『/设置』开启后再试。"
        )

    def get_disabled_tool_message(self) -> str:
        return f"{self.get_service_switch_name()}未开启，请使用【{self.get_enable_command_name()}】命令"

    def _action_supported_in_service_menu(self, handler_name: str, *, event=None) -> bool:
        method = getattr(self, handler_name, None)
        if method is None:
            return False

        signature = inspect.signature(method)
        supported_params = {"event", "arg", "matcher", "bot"}
        for param_name, param in signature.parameters.items():
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            if param_name not in supported_params and param.default is inspect._empty:
                return False
            if param_name == "event" and event is None and param.default is inspect._empty:
                return False
        return True

    def _should_prompt_for_arg(self, command: ServiceCommand) -> bool:
        if not command.need_arg:
            return False

        method = getattr(self, command.handler_name, None)
        if method is None:
            return False

        arg_param = inspect.signature(method).parameters.get("arg")
        if arg_param is None:
            return False
        if arg_param.default is not inspect._empty:
            return False

        desc = f"{command.cmd} {command.desc}".strip()
        if "菜单" in desc or "打开" in desc:
            return False
        return True

    def _get_visible_service_menu_commands(self, *, event=None) -> list[ServiceCommand]:
        from src.services.registry import service_manager

        default_action = self.get_default_action_name()
        commands: list[ServiceCommand] = []
        for command in service_manager.get_service_commands(self.service_type):
            if command.handler_name in {"enable_service", "disable_service"}:
                continue
            if command.handler_name == default_action:
                continue
            if not self.is_feature_enabled(command.handler_name, default=True):
                continue
            if not self._action_supported_in_service_menu(command.handler_name, event=event):
                continue
            commands.append(command)
        return commands

    async def _build_menu_command_kwargs(self, command: ServiceCommand, *, event=None) -> Optional[Dict[str, Any]]:
        from nonebot import get_bot
        from src.support.group import wait_for

        method = getattr(self, command.handler_name)
        signature = inspect.signature(method)
        params = signature.parameters
        kwargs: Dict[str, Any] = {}

        if "event" in params and event is not None:
            kwargs["event"] = event
        if "matcher" in params:
            kwargs["matcher"] = _ServiceMenuMatcher(self)
        if "bot" in params:
            kwargs["bot"] = get_bot()
        if "arg" in params:
            arg_text = ""
            if self._should_prompt_for_arg(command):
                await self.group.send_msg("请输入参数内容（60 秒内），或输入“退出”取消。")
                response = await wait_for(60)
                if not response or response.strip().lower() == "退出":
                    await self.group.send_msg("❌ 已取消。")
                    return None
                arg_text = response.strip()
            kwargs["arg"] = Message(arg_text)

        return kwargs

    async def _run_service_menu_command(self, command: ServiceCommand, *, event=None):
        from src.services.registry import run_service

        kwargs = await self._build_menu_command_kwargs(command, event=event)
        if kwargs is None:
            return

        await run_service(
            group_id=self.group.group_id,
            service_enum=self.service_type,
            action=command.handler_name,
            **kwargs,
        )

    async def service_entry(self, event=None):
        from src.support.group import run_flow

        commands = self._get_visible_service_menu_commands(event=event)
        if not commands:
            await self.group.send_msg(f"{self.get_service_switch_name()}当前没有可用操作。")
            return

        lines = ["请选择以下操作："]
        routes = {}
        items = []
        for index, command in enumerate(commands, start=1):
            suffix = f"：{command.desc}" if command.desc else ""
            need_arg = "（需参数）" if self._should_prompt_for_arg(command) else ""
            lines.append(f"{index}. {command.cmd}{need_arg}{suffix}")
            items.append(
                {
                    "index": str(index),
                    "title": command.cmd,
                    "description": command.desc or "执行该操作",
                    "meta": "回复序号或命令均可",
                    "status": "需参数" if need_arg else "直达",
                    "status_tone": "warning" if need_arg else "accent",
                }
            )

            async def runner(selected_command: ServiceCommand = command):
                await self._run_service_menu_command(selected_command, event=event)

            routes[str(index)] = runner
            routes[command.cmd] = runner

        lines.append("")
        lines.append("输入【序号】或【指令】")
        flow = {
            "title": f"{self.get_service_switch_name()}",
            "subtitle": "选择一个操作继续执行。",
            "text": "\n".join(lines),
            "template": "service_menu",
            "badges": [
                {"text": "回复序号或命令", "tone": "accent"},
                {"text": "带参数操作会继续追问", "tone": "warning"},
            ],
            "sections": [
                {
                    "title": "可用操作",
                    "description": "这里展示的是当前群内已启用且可用的服务命令。",
                    "columns": 1,
                    "items": items,
                }
            ],
            "hint": "输入【序号】或【指令】",
            "routes": routes,
        }
        await run_flow(self.group, flow)

    def _get_feature_flags(self) -> Dict[str, bool]:
        raw = self._config.get("feature_flags", {})
        if isinstance(raw, dict):
            return {str(k): bool(v) for k, v in raw.items()}
        return {}

    def is_feature_enabled(self, handler_name: str, *, default: bool = True) -> bool:
        flags = self._get_feature_flags()
        if handler_name not in flags:
            return default
        return bool(flags[handler_name])

    def set_feature_enabled(self, handler_name: str, enabled: bool) -> None:
        flags = self._get_feature_flags()
        flags[str(handler_name)] = bool(enabled)
        self._config["feature_flags"] = flags
        self._save_config()

    @classmethod
    def get_config_options(cls) -> list[ServiceConfigOption]:
        options: list[ServiceConfigOption] = []
        for raw in getattr(cls, "settings_schema", []) or []:
            option = ServiceConfigOption.from_data(raw)
            if option.default is None and option.key in cls.default_config:
                option.default = copy.deepcopy(cls.default_config[option.key])
            options.append(option)
        return options

    def get_config_option(self, key: str) -> Optional[ServiceConfigOption]:
        for option in self.get_config_options():
            if option.key == key:
                return option
        return None

    def get_config_option_value(self, option: ServiceConfigOption) -> Any:
        return self.get_config_value(option.key, option.default)

    def format_config_option_value(self, option: ServiceConfigOption) -> str:
        value = self.get_config_option_value(option)
        if option.type == "bool":
            return "开启" if bool(value) else "关闭"
        if option.type == "select":
            for choice in option.choices or []:
                if choice.get("value") == value:
                    return str(choice.get("label") or value)
        if option.type == "text":
            text = str(value or "").strip()
            return text or "未设置"
        if value is None or value == "":
            return "未设置"
        return str(value)

    def parse_config_option_input(
        self,
        option: ServiceConfigOption,
        raw_value: Any,
    ) -> tuple[bool, Any, str]:
        text = str(raw_value or "").strip()
        option_type = str(option.type or "text").strip().lower()

        if option_type == "bool":
            lowered = text.lower()
            if lowered in {"1", "true", "on", "yes", "y", "开", "开启"}:
                return True, True, ""
            if lowered in {"0", "false", "off", "no", "n", "关", "关闭"}:
                return True, False, ""
            return False, None, "请输入开启/关闭、开/关、true/false 或 1/0。"

        if option_type == "int":
            try:
                value = int(text)
            except ValueError:
                return False, None, "请输入整数。"
            if option.min_value is not None and value < option.min_value:
                return False, None, f"数值不能小于 {option.min_value}。"
            if option.max_value is not None and value > option.max_value:
                return False, None, f"数值不能大于 {option.max_value}。"
            return True, value, ""

        if option_type == "time":
            if not re.fullmatch(r"^([0-1]\d|2[0-3]):[0-5]\d$", text):
                return False, None, "请输入 HH:MM 格式，例如 22:00。"
            return True, text, ""

        if option_type == "select":
            choices = option.choices or []
            if not choices:
                return False, None, "当前配置项未提供可选项。"
            if text.isdigit():
                index = int(text) - 1
                if 0 <= index < len(choices):
                    return True, choices[index].get("value"), ""
            for choice in choices:
                label = str(choice.get("label") or "").strip()
                value = choice.get("value")
                if text == label or text == str(value):
                    return True, value, ""
            return False, None, "请输入有效序号或选项值。"

        return True, text, ""

    def apply_config_option_value(self, key: str, value: Any) -> None:
        option = self.get_config_option(key)
        if option is None:
            raise KeyError(f"未找到配置项：{key}")
        previous_value = copy.deepcopy(self.get_config_value(option.key, option.default))
        self.set_config_value(option.key, value)
        try:
            self.on_config_option_changed(option, previous_value, value)
        except Exception:
            self.set_config_value(option.key, previous_value)
            raise

    def on_config_option_changed(
        self,
        option: ServiceConfigOption,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """子类可重写，用于在配置项变更后同步运行时状态。"""

    async def check_service_availability(
        self,
        *,
        action: str,
        action_meta: Optional[Dict[str, Any]] = None,
        event=None,
    ) -> tuple[bool, str]:
        """子类可重写，用于限制服务在特定运行环境下开启或使用。"""
        return True, ""

    def _load_config(self) -> Dict[str, Any]:
        data = self.group.db.get_service_config(self.service_type.value)
        if data is None:
            data = {}
        merged = copy.deepcopy(self.default_config)
        merged.update(data)
        self._config = merged
        self._save_config()
        return merged

    def _save_config(self):
        self.group.db.upsert_service_config(self.service_type.value, self._config)

    def get_config_value(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config_value(self, key: str, value: Any) -> None:
        self._config[key] = value
        self._save_config()

    def update_config(self, patch: Dict[str, Any]) -> None:
        if not patch:
            return
        self._config.update(patch)
        self._save_config()

    def delete_config_value(self, key: str) -> None:
        if key in self._config:
            del self._config[key]
            self._save_config()

    def get_config_snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self._config)

    def get_state_entry(self, scope: str, key: str, default: Any = None) -> Any:
        value = self.group.db.get_service_state_entry(self.service_type.value, scope, key)
        if value is None:
            return default
        return value

    def put_state_entry(self, scope: str, key: str, value: Any) -> None:
        self.group.db.upsert_service_state_entry(self.service_type.value, scope, key, value)

    def delete_state_entry(self, scope: str, key: str) -> None:
        self.group.db.delete_service_state_entry(self.service_type.value, scope, key)

    def list_state_entries(self, scope: str) -> Dict[str, Any]:
        entries = self.group.db.list_service_state_entries(self.service_type.value, scope)
        return {entry["entry_key"]: entry["value"] for entry in entries}

    async def toggle_service(
        self,
        enable: bool,
        service_name: Optional[str] = None,
        check_admin: bool = True,
    ):
        service_name = service_name or self.get_service_switch_name()
        current_enabled = getattr(self, "enabled", False)
        if enable and current_enabled:
            await self.group.send_msg(f"🚫 本群{service_name}已开启！")
            return False
        if not enable and not current_enabled:
            await self.group.send_msg(f"🚫 本群{service_name}已关闭！")
            return False
        if check_admin:
            mi = await self.group.get_group_member_info(self.group.self_id)
            if mi["role"] == "member":
                await self.group.send_msg(f"❌ 机器人不是管理员，无法操作 {service_name}！")
                return False
        setattr(self, "enabled", enable)
        state = "开启" if enable else "关闭"
        await self.group.send_msg(f"✅ 本群{service_name}{state}成功！")
        return True

    async def enable_service(self):
        await self.toggle_service(True, check_admin=self.enable_requires_bot_admin)

    async def disable_service(self):
        await self.toggle_service(False, check_admin=self.disable_requires_bot_admin)


def check_enabled(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not getattr(self, "enabled", False):
            service_name = self.get_service_switch_name()
            await self.group.send_msg(
                f"🚫 本群{service_name}未开启！\n"
                f"🕹️ 回复『1』即可开启该服务\n"
                f"📝 或使用指令『{self.get_enable_command_name()}』\n"
                f"⚙️ 管理开关：『/设置』\n"
                f"📋 功能菜单：『/服务』"
            )
            try:
                from src.support.group import wait_for

                response = await wait_for(10)
                if response and response.strip() == "1":
                    await self.enable_service()
                else:
                    await self.group.send_msg("✅ 系统已自动退出")
            except Exception as e:
                print(e)
                await self.group.send_msg("✅ 系统已自动退出")
            return

        return await func(self, *args, **kwargs)

    return wrapper


def _get_legacy_backup_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.legacy_backup{path.suffix}")


def _archive_legacy_json_file(path: Path) -> None:
    if not path.exists():
        return

    backup_path = _get_legacy_backup_path(path)
    try:
        if backup_path.exists():
            backup_path.unlink()
        path.replace(backup_path)
    except Exception:
        return


def _load_legacy_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def migrate_legacy_service_config_file(
    *,
    group_db: Any,
    service_type: Services,
    config_file: Path,
) -> bool:
    config_path = Path(config_file)
    if not config_path.exists():
        return False

    existing_config = group_db.get_service_config(service_type.value)
    if existing_config is None:
        legacy_config = _load_legacy_json_dict(config_path)
        if legacy_config is None:
            return False
        group_db.upsert_service_config(service_type.value, legacy_config)

    _archive_legacy_json_file(config_path)
    return True


def migrate_all_legacy_service_configs(data_root: Path | str = "data") -> int:
    root_path = Path(data_root)
    group_root = root_path / "group_management"
    if not group_root.exists():
        return 0

    service_lookup = {service.name.lower(): service for service in Services}
    migrated_count = 0

    for group_dir in sorted((item for item in group_root.iterdir() if item.is_dir()), key=lambda item: item.name):
        try:
            group_id = int(group_dir.name)
        except ValueError:
            continue

        db = None
        try:
            from src.support.db import GroupDatabase

            db = GroupDatabase(group_id=group_id, data_root=root_path)
            for config_path in sorted(group_dir.glob("*_service.json")):
                service_key = config_path.stem.removesuffix("_service").lower()
                service_type = service_lookup.get(service_key)
                if service_type is None:
                    continue
                if migrate_legacy_service_config_file(
                    group_db=db,
                    service_type=service_type,
                    config_file=config_path,
                ):
                    migrated_count += 1
        finally:
            if db is not None:
                db.conn.close()

    return migrated_count


__all__ = [
    "BaseService",
    "ServiceCommand",
    "ServiceConfigOption",
    "ServiceHandler",
    "Services",
    "check_enabled",
    "config_property",
    "migrate_all_legacy_service_configs",
    "migrate_legacy_service_config_file",
    "service_action",
    "service_message",
    "service_notice",
    "service_request",
]
