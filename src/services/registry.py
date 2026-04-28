import importlib
import inspect
import traceback
import uuid
from typing import Dict, List, Tuple, Type

import nonebot
from nonebot import on_command, on_message, on_notice, on_request
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.exception import FinishedException, PausedException, RejectedException
from nonebot.internal.matcher import Matcher
from nonebot.params import CommandArg

from src.support.core import Services, service_bridge
from src.support.points import format_points_insufficient_message, normalize_points_cost
from src.support.group import GroupContext, group_context_factory

from . import SERVICE_CLASS_IMPORTS
from .base import BaseService, ServiceCommand

_SERVICE_CLASS_IMPORTS: Dict[Services, tuple[str, str]] = SERVICE_CLASS_IMPORTS

_handlers_registered = False


def _load_service_class(service_type: Services) -> Type[BaseService]:
    module_path, class_name = _SERVICE_CLASS_IMPORTS[service_type]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _build_toggle_action_meta(service_cls: Type[BaseService], action: str) -> dict | None:
    if action not in ("enable_service", "disable_service"):
        return None

    is_enable = action == "enable_service"
    switch_name = service_cls.get_service_switch_name()
    command_name = (
        service_cls.get_enable_command_name()
        if is_enable
        else service_cls.get_disable_command_name()
    )
    verb = "开启" if is_enable else "关闭"
    return {
        "cmd": command_name,
        "aliases": set(),
        "desc": f"{verb}{switch_name}",
        "need_arg": False,
        "permission": None,
        "rule": None,
        "priority": 2,
        "block": True,
        "visible": True,
        "trigger_type": "command",
        "tool_callable": False,
        "require_admin": False,
        "require_owner": False,
        "allow_when_disabled": True,
    }


def _build_service_entry_action_meta(service_cls: Type[BaseService], action: str) -> dict | None:
    if action != "service_entry":
        return None
    if service_cls.get_default_action_name() != "service_entry":
        return None

    command_name = service_cls.get_service_entry_command_name()
    return {
        "cmd": command_name,
        "aliases": set(),
        "desc": f"打开{command_name}主页",
        "need_arg": False,
        "permission": None,
        "rule": None,
        "priority": 2,
        "block": True,
        "visible": True,
        "trigger_type": "command",
        "tool_callable": False,
        "require_admin": False,
        "require_owner": False,
        "allow_when_disabled": False,
    }


def _resolve_service_action_meta(service_cls: Type[BaseService], action: str, method) -> dict | None:
    meta = getattr(method, "__service_action__", None)
    if meta:
        return meta
    if entry_meta := _build_service_entry_action_meta(service_cls, action):
        return entry_meta
    return _build_toggle_action_meta(service_cls, action)


def _is_explicit_command_invocation(event, action_meta: dict | None) -> bool:
    if not action_meta or not isinstance(event, GroupMessageEvent):
        return False

    try:
        message_text = event.get_message().extract_plain_text().strip()
    except Exception:
        return False

    if not message_text:
        return False

    try:
        command_start = tuple(str(item) for item in nonebot.get_driver().config.command_start)
    except Exception:
        command_start = ("/",)

    normalized_text = message_text
    matched_prefix = ""
    for prefix in sorted(command_start, key=len, reverse=True):
        if prefix and normalized_text.startswith(prefix):
            matched_prefix = prefix
            normalized_text = normalized_text[len(prefix) :].lstrip()
            break

    if not matched_prefix:
        return False

    command_candidates = {str(action_meta.get("cmd", "")).strip()}
    command_candidates.update(
        str(item).strip()
        for item in action_meta.get("aliases", set()) or set()
        if str(item).strip()
    )
    command_candidates.discard("")
    if not command_candidates:
        return False

    for candidate in command_candidates:
        if normalized_text == candidate:
            return True
        if normalized_text.startswith(f"{candidate} "):
            return True
    return False


def _extract_command_arg_text(kwargs) -> str:
    arg = kwargs.get("arg")
    if arg is None:
        return ""
    try:
        return str(arg.extract_plain_text() or "").strip()
    except Exception:
        return str(arg or "").strip()


def _build_ai_command_context_text(
    service: BaseService,
    action_meta: dict,
    event: GroupMessageEvent,
    kwargs,
) -> str:
    sender = getattr(event, "sender", None)
    nickname = (
        getattr(sender, "card", None)
        or getattr(sender, "nickname", None)
        or f"QQ:{event.user_id}"
    )
    label = (
        str(action_meta.get("ai_context_label") or "").strip()
        or str(action_meta.get("desc") or "").strip()
        or str(action_meta.get("cmd") or "").strip()
        or "执行服务操作"
    )

    content = (
        f"[服务指令] {nickname} (QQ:{event.user_id}) "
        f"通过指令触发了{service.get_service_switch_name()}：{label}"
    )

    if action_meta.get("ai_context_include_arg", False):
        arg_text = _extract_command_arg_text(kwargs)
        if arg_text:
            content += f"。参数：{arg_text}"

    return content


def _record_service_command_ai_context(
    service: BaseService,
    *,
    action_meta: dict | None,
    event=None,
    kwargs=None,
) -> None:
    if not action_meta or not action_meta.get("record_ai_context", False):
        return
    if not _is_explicit_command_invocation(event, action_meta):
        return

    from src.services._ai.message_bridge import record_group_user_command

    context_text = _build_ai_command_context_text(service, action_meta, event, kwargs or {})
    record_group_user_command(event.group_id, context_text)


async def _check_action_permissions(
    service: BaseService,
    *,
    action_meta: dict | None,
    event=None,
) -> tuple[bool, str]:
    if not action_meta:
        return True, ""

    require_admin = bool(action_meta.get("require_admin", False))
    require_owner = bool(action_meta.get("require_owner", False))
    if not require_admin and not require_owner:
        return True, ""

    if event is None:
        return False, "无法获取操作者身份"

    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None)
    if not role:
        user_id = getattr(event, "user_id", None)
        if not user_id:
            return False, "无法获取操作者身份"
        try:
            member_info = await service.group.get_group_member_info(user_id)
            role = member_info.get("role")
        except Exception:
            role = None

    normalized_role = str(role or "member").lower()
    if require_owner and normalized_role != "owner":
        return False, "此操作需要群主权限。"
    if require_admin and normalized_role == "member":
        return False, "此操作需要管理员权限。"
    return True, ""


async def _check_action_points_cost(
    service: BaseService,
    *,
    action: str,
    action_meta: dict | None,
    event=None,
) -> tuple[bool, str]:
    if bool((action_meta or {}).get("defer_points_charge", False)):
        return True, ""

    required_points = normalize_points_cost((action_meta or {}).get("points_cost"))
    if required_points <= 0:
        return True, ""

    user_id = int(getattr(event, "user_id", 0) or 0)
    if user_id <= 0:
        return False, "无法获取触发用户，暂时不能校验积分。"

    message_id = int(getattr(event, "message_id", 0) or 0)
    source_key = f"message:{message_id}" if message_id > 0 else f"action:{action}"
    idempotency_key = (
        f"service_points:{service.group.group_id}:{user_id}:"
        f"{service.service_type.value}:{action}:{source_key}"
    )
    reason = (
        str((action_meta or {}).get("points_reason") or "").strip()
        or f"service_action:{service.service_type.value}:{action}"
    )
    allowed, balance, _already_applied = service.group.db.apply_points_cost(
        user_id=user_id,
        cost_points=required_points,
        reason=reason,
        ref_type="service_action",
        ref_id=f"{service.service_type.value}:{action}",
        idempotency_key=idempotency_key,
    )
    if allowed:
        return True, ""

    action_label = (
        str((action_meta or {}).get("desc") or "").strip()
        or str((action_meta or {}).get("cmd") or "").strip()
        or action
    )
    return (
        False,
        format_points_insufficient_message(
            required_points=required_points,
            current_balance=balance,
            action_label=action_label,
            custom_message=str((action_meta or {}).get("points_insufficient_message") or ""),
        ),
    )


class ServiceManager:
    def __init__(self):
        self.groups: Dict[int, GroupContext] = {}
        self.services: Dict[Services, Dict[int, BaseService]] = {}
        self.service_commands: Dict[Services, List[ServiceCommand]] = {}
        self._service_classes: Dict[Services, Type[BaseService]] = {}

        for stype in list(_SERVICE_CLASS_IMPORTS.keys()):
            try:
                service_cls = _load_service_class(stype)
            except Exception as e:
                print(f"[ServiceManager] 跳过服务 {stype.value}：{e}")
                continue
            self._service_classes[stype] = service_cls
            self._collect_service_commands(service_cls)

        service_bridge.set_service_manager(self)
        service_bridge.init_service_tools()

    def _collect_service_commands(self, service_cls: Type[BaseService]):
        service_type = service_cls.service_type
        if service_type in self.service_commands:
            return
        commands: List[ServiceCommand] = []
        for attr_name in dir(service_cls):
            func = getattr(service_cls, attr_name)
            meta = _resolve_service_action_meta(service_cls, attr_name, func)
            if not meta or not meta.get("visible", True):
                continue
            commands.append(
                ServiceCommand(
                    cmd=meta["cmd"],
                    handler_name=attr_name,
                    need_arg=meta["need_arg"],
                    permission=meta["permission"],
                    rule=meta["rule"],
                    priority=meta["priority"],
                    block=meta["block"],
                    desc=meta.get("desc", ""),
                    allow_when_disabled=bool(meta.get("allow_when_disabled", False)),
                )
            )

        commands.sort(key=lambda c: c.priority)
        self.service_commands[service_type] = commands

    def get_group(self, group_id: int, *, self_id=None) -> GroupContext:
        group = group_context_factory.get_group(group_id, self_id=self_id)
        self.groups[group_id] = group
        return group

    async def get_service(self, group_id: int, service_type: Services, *, self_id=None) -> BaseService:
        self.services.setdefault(service_type, {})
        group = self.get_group(group_id, self_id=self_id)

        if group_id not in self.services[service_type]:
            service_cls = self._service_classes.get(service_type)
            if not service_cls:
                service_cls = _load_service_class(service_type)
                self._service_classes[service_type] = service_cls
                self._collect_service_commands(service_cls)
                service_bridge.init_service_tools()
            self.services[service_type][group_id] = service_cls(group)

        return self.services[service_type][group_id]

    def get_all_service_types(self) -> List[Services]:
        return list(self.service_commands.keys())

    def get_service_commands(self, service_type: Services) -> List[ServiceCommand]:
        return self.service_commands.get(service_type, [])

    def get_default_action_name(self, service_type: Services) -> str:
        service_cls = self._service_classes.get(service_type)
        if not service_cls:
            service_cls = _load_service_class(service_type)
            self._service_classes[service_type] = service_cls
            self._collect_service_commands(service_cls)
        return service_cls.get_default_action_name()

    async def get_bound_commands(
        self, group_id: int, service_type: Services
    ) -> List[Tuple[ServiceCommand, callable]]:
        service = await self.get_service(group_id, service_type)
        result = []
        for cmd in self.get_service_commands(service_type):
            handler = getattr(service, cmd.handler_name)
            result.append((cmd, handler))
        return result

    async def group_service_help(self, group: GroupContext):
        lines = []
        for stype in self.get_all_service_types():
            lines.append(f"【{stype.chinese_name}】")
            for cmd in self.get_service_commands(stype):
                lines.append(f"- {cmd.cmd}：{cmd.desc}")
        return "\n".join(lines)

    async def group_service_panel(self, group: GroupContext):
        lines = ["群服务面板："]
        for stype in self.get_all_service_types():
            try:
                service = await self.get_service(group.group_id, stype)
                enabled = bool(getattr(service, "enabled", False))
            except Exception:
                enabled = False
            lines.append(f"- {stype.chinese_name}：{'✅ 已开启' if enabled else '⛔ 已关闭'}")
        await group.send_msg("\n".join(lines))


def iter_service_classes():
    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    yield from walk(BaseService)


def _register_command(service_enum, action, meta):
    matcher = on_command(
        meta["cmd"],
        aliases=meta.get("aliases") or set(),
        rule=meta["rule"],
        permission=meta["permission"],
        priority=meta["priority"],
        block=meta["block"],
    )

    @matcher.handle()
    async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher = Matcher(), arg: Message = CommandArg()):
        kwargs = {"event": event, "matcher": matcher, "bot": bot}
        if meta.get("need_arg", False):
            kwargs["arg"] = arg
        await run_service(
            group_id=event.group_id,
            service_enum=service_enum,
            action=action,
            **kwargs,
        )


def _register_message(service_enum, action, meta):
    matcher = on_message(
        rule=meta.get("rule"),
        priority=meta["priority"],
        block=meta["block"],
    )

    @matcher.handle()
    async def _(bot: Bot, event: GroupMessageEvent):
        await run_service(
            group_id=event.group_id,
            service_enum=service_enum,
            action=action,
            event=event,
            bot=bot,
        )


def _register_notice(service_enum, action, meta):
    matcher = on_notice(priority=meta["priority"], block=meta["block"])

    @matcher.handle()
    async def _(bot: Bot, event, matcher: Matcher = Matcher()):
        event_type = meta.get("event_type")
        if event_type and event.__class__.__name__ != event_type:
            return
        group_id = getattr(event, "group_id", None)
        if not group_id:
            return
        await run_service(
            group_id=group_id,
            service_enum=service_enum,
            action=action,
            event=event,
            matcher=matcher,
            bot=bot,
        )


def _register_request(service_enum, action, meta):
    matcher = on_request(priority=meta["priority"], block=meta["block"])

    @matcher.handle()
    async def _(bot: Bot, event):
        event_type = meta.get("event_type")
        if event_type and event.__class__.__name__ != event_type:
            return
        group_id = getattr(event, "group_id", None)
        if not group_id:
            return
        await run_service(
            group_id=group_id,
            service_enum=service_enum,
            action=action,
            event=event,
            bot=bot,
        )


def register_all_service_handlers():
    global _handlers_registered
    if _handlers_registered:
        return

    for service_cls in iter_service_classes():
        print(f"正在注册 {str(service_cls)}")
        service_enum = getattr(service_cls, "service_type", None)
        if not service_enum:
            print("注册失败：没有 service_type")
            continue
        for attr in dir(service_cls):
            method = getattr(service_cls, attr)
            if meta := _resolve_service_action_meta(service_cls, attr, method):
                _register_command(service_enum, attr, meta)
            if meta := getattr(method, "__service_message__", None):
                _register_message(service_enum, attr, meta)
            if meta := getattr(method, "__service_notice__", None):
                _register_notice(service_enum, attr, meta)
            if meta := getattr(method, "__service_request__", None):
                _register_request(service_enum, attr, meta)

    _handlers_registered = True


async def run_service(
    *,
    group_id: int,
    service_enum,
    action: str,
    event=None,
    **kwargs,
):
    try:
        service = await service_manager.get_service(
            group_id,
            service_enum,
            self_id=getattr(event, "self_id", None),
        )
        method = getattr(service, action, None)
        if method is None:
            raise AttributeError(f"{service.__class__.__name__} 没有方法 {action}")

        action_meta = _resolve_service_action_meta(service.__class__, action, method)
        allow_when_disabled = bool(action_meta.get("allow_when_disabled", False)) if action_meta else False

        availability_checker = getattr(service, "check_service_availability", None)
        if callable(availability_checker):
            service_available, unavailable_reason = await availability_checker(
                action=action,
                action_meta=action_meta,
                event=event,
            )
            if not service_available:
                await service.group.send_msg(unavailable_reason or "⛔ 当前环境不可使用该服务。")
                return {"status": False, "error": "service_unavailable"}

        if hasattr(service, "enabled") and not getattr(service, "enabled", False):
            if not allow_when_disabled:
                if action_meta:
                    await service.group.send_msg(service.get_disabled_notice())
                return {"status": False, "error": "service_disabled"}

        if action_meta and not service.is_feature_enabled(action, default=True):
            await service.group.send_msg(
                f"⛔ 功能『{action_meta.get('cmd', action)}』已在本群设置为关闭。\n"
                f"管理员请使用『/设置』开启后再试。"
            )
            return {"status": False, "error": "feature_disabled"}

        has_permission, permission_error = await _check_action_permissions(
            service,
            action_meta=action_meta,
            event=event,
        )
        if not has_permission:
            await service.group.send_msg(f"⛔ {permission_error}")
            return {"status": False, "error": "permission_denied"}

        has_points, points_error = await _check_action_points_cost(
            service,
            action=action,
            action_meta=action_meta,
            event=event,
        )
        if not has_points:
            await service.group.send_msg(points_error)
            return {"status": False, "error": "points_insufficient"}

        if event is not None:
            kwargs["event"] = event

        sig = inspect.signature(method)
        params = sig.parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            filtered_kwargs = kwargs
        else:
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in params}

        _record_service_command_ai_context(
            service,
            action_meta=action_meta,
            event=event,
            kwargs=filtered_kwargs,
        )
        return await method(**filtered_kwargs)
    except (FinishedException, RejectedException, PausedException):
        return {"status": True, "message": "matcher_flow_finished"}
    except Exception as e:
        error_id = uuid.uuid4().hex[:8]
        traceback.print_exc()
        try:
            group = service_manager.get_group(group_id)
            await group.send_msg(f"❌ 操作失败（错误ID：{error_id}）")
        except Exception:
            pass
        return {
            "status": False,
            "error": e,
            "error_id": error_id,
        }


service_manager = ServiceManager()

__all__ = [
    "ServiceManager",
    "iter_service_classes",
    "register_all_service_handlers",
    "run_service",
    "service_manager",
]
