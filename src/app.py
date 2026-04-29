"""
内部业务统一入口。

运行时不再依赖 `src/plugins` 自动发现本仓库自研插件，
而是由 `bot.py` 显式 import 本模块完成注册。
"""

import asyncio
import os
import traceback
from pathlib import Path
from typing import List, Optional

from nonebot import get_app, get_driver, on_command, on_message, on_notice
from nonebot.adapters.onebot.v11 import (
    ActionFailed,
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    PokeNotifyEvent,
    PrivateMessageEvent,
)
from nonebot.internal.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule
from nonebot_plugin_alconna import UniMessage
from nonebot_plugin_apscheduler import scheduler

from src.services import load_internal_services
from src.services._schedule import restore_scheduled_tool_jobs_to_runtime
from src.services._ai.config_runtime import migrate_all_legacy_ai_assistant_configs
from src.services.ai import AIAssistantManager
from src.services.base import ServiceConfigOption, migrate_all_legacy_service_configs
from src.services.reminder import register_reminder_scheduler_jobs
from src.services.registry import register_all_service_handlers, run_service, service_manager
from src.support.api import codex_bridge, internal_api_router
from src.support.cache_cleanup import (
    RUNTIME_CACHE_CLEANUP_INTERVAL_HOURS,
)
from src.support.core import Services, process_text
from src.support.db import GroupDatabase
from src.support.group import format_card_fallback_text, group_context_factory, render_card_message, run_flow, wait_for
from src.support.law_docs import (
    build_law_document_forward_nodes,
    chunk_law_forward_nodes,
    chunk_law_original_plain_text,
    format_law_search_response,
    register_law_doc_tools,
)
from src.support.scheduled_tasks import (
    SCHEDULER_STATE_SCOPE,
    get_runtime_task,
    is_expired_once_schedule,
    iter_runtime_tasks,
    register_runtime_callback,
    register_runtime_scheduler_job,
    remove_runtime_task,
    upsert_runtime_task,
)
from src.support.storage_guard import run_storage_guard, summarize_storage_review

load_internal_services()
register_all_service_handlers()
register_law_doc_tools()
get_app().include_router(internal_api_router)

_private_ai_manager = None


def _get_menu_service_types() -> List[Services]:
    return service_manager.get_all_service_types()


def _iter_persisted_group_ids() -> List[int]:
    root = Path("data") / "group_management"
    if not root.exists():
        return []

    group_ids: List[int] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not (child / "group_data.db").exists():
            continue
        try:
            group_ids.append(int(child.name))
        except ValueError:
            continue
    return sorted(group_ids)


def _iter_daily_release_group_ids() -> List[int]:
    raw_value = str(os.getenv("DAILY_RELEASE_GROUP_IDS") or "").strip()
    if not raw_value:
        return []

    group_ids: list[int] = []
    seen: set[int] = set()
    for chunk in raw_value.replace(";", ",").split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            group_id = int(text)
        except ValueError:
            continue
        if group_id in seen:
            continue
        seen.add(group_id)
        group_ids.append(group_id)
    return group_ids


def _should_run_auto_organize_fallback(service, runtime_task: dict | None) -> bool:
    if not bool(getattr(service, "enabled", False)):
        return False
    if not bool(getattr(service, "auto_organize_enabled", False)):
        return False
    if runtime_task and bool(runtime_task.get("enabled", True)):
        return False
    return True


def _restore_service_state_tasks_to_scheduler() -> tuple[int, int]:
    restored = 0
    pruned = 0
    service_names = (
        Services.File.value,
        Services.Wordcloud.value,
        Services.Schedule.value,
    )

    for group_id in _iter_persisted_group_ids():
        db = GroupDatabase(group_id)
        try:
            for service_name in service_names:
                entries = db.list_service_state_entries(service_name, SCHEDULER_STATE_SCOPE)
                for entry in entries:
                    payload = entry.get("value")
                    if not isinstance(payload, dict):
                        continue

                    task_id = payload.get("task_id")
                    task_type = payload.get("task_type") or payload.get("type")
                    schedule = payload.get("schedule")
                    callback_id = payload.get("callback_id")
                    if not task_id or not task_type or not schedule or not callback_id:
                        continue
                    entry_key = str(entry.get("entry_key") or task_id)

                    if is_expired_once_schedule(task_type, schedule):
                        remove_runtime_task(str(task_id))
                        db.delete_service_state_entry(service_name, SCHEDULER_STATE_SCOPE, entry_key)
                        pruned += 1
                        continue

                    task_kwargs = {
                        "schedule": schedule,
                        "callback_id": callback_id,
                        "enabled": bool(payload.get("enabled", True)),
                        "group_id": group_id,
                        "description": payload.get("description", ""),
                    }
                    message = payload.get("message")
                    existing_task = get_runtime_task(task_id)
                    if existing_task:
                        upsert_runtime_task(
                            task_id=task_id,
                            task_type=task_type,
                            schedule=schedule,
                            callback_id=callback_id,
                            enabled=task_kwargs["enabled"],
                            group_id=group_id,
                            description=task_kwargs["description"],
                            message=message,
                        )
                        continue

                    upsert_runtime_task(
                        task_id=task_id,
                        task_type=task_type,
                        schedule=schedule,
                        callback_id=callback_id,
                        enabled=task_kwargs["enabled"],
                        group_id=group_id,
                        description=task_kwargs["description"],
                        message=message,
                    )
                    restored += 1
        finally:
            db.conn.close()

    return restored, pruned


def _is_admin(event: GroupMessageEvent) -> bool:
    role = getattr(getattr(event, "sender", None), "role", None)
    return role in ("admin", "owner")


def _get_service_snapshot(group_id: int, stype: Services, *, self_id=None):
    group = service_manager.get_group(group_id, self_id=self_id)
    service_cls = service_manager._service_classes.get(stype)  # noqa: SLF001
    if not service_cls:
        return None
    return service_cls(group)


def _extract_text(event: MessageEvent, arg: Message) -> str:
    text = arg.extract_plain_text().strip()
    if text:
        return text
    if getattr(event, "reply", None):
        return event.reply.message.extract_plain_text().strip()
    return ""


def _is_private_message_event(event: MessageEvent) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    msg_text = event.get_message().extract_plain_text().strip()
    if not msg_text:
        return True

    try:
        command_start = get_driver().config.command_start
    except Exception:
        command_start = {"/"}
    return not any(str(prefix) and msg_text.startswith(str(prefix)) for prefix in command_start)


def _format_service_menu(group_id: int) -> str:
    menu_service_types = _get_menu_service_types()
    lines = ["请选择服务："]
    for index, stype in enumerate(menu_service_types, start=1):
        snap = _get_service_snapshot(group_id, stype)
        enabled = bool(getattr(snap, "enabled", False)) if snap else False
        lines.append(f"{index}. {stype.chinese_name} {'✅' if enabled else '⛔'}")
    lines.append("回复序号继续，或输入“退出”取消。")
    return "\n".join(lines)


def _get_service_command_count(service_type: Services) -> int:
    return len(
        [
            cmd
            for cmd in service_manager.get_service_commands(service_type)
            if cmd.handler_name not in ("enable_service", "disable_service")
        ]
    )


def _build_service_selector_items(group_id: int) -> tuple[list[dict], int]:
    items: list[dict] = []
    enabled_count = 0
    for index, stype in enumerate(_get_menu_service_types(), start=1):
        snap = _get_service_snapshot(group_id, stype)
        enabled = bool(getattr(snap, "enabled", False)) if snap else False
        if enabled:
            enabled_count += 1
        command_count = _get_service_command_count(stype)
        items.append(
            {
                "index": str(index),
                "title": stype.chinese_name,
                "description": f"共 {command_count} 个可用命令",
                "meta": f"可回复序号 {index} 或服务名 {stype.chinese_name}",
                "status": "开启" if enabled else "关闭",
                "status_tone": "success" if enabled else "danger",
            }
        )
    return items, enabled_count


def _build_service_selector_card(
    group_id: int,
    *,
    title: str,
    subtitle: str,
    footer: str,
    admin_only: bool = False,
) -> dict:
    items, enabled_count = _build_service_selector_items(group_id)
    total_count = len(items)
    badges = [
        {"text": "回复序号或服务名", "tone": "accent"},
        {"text": "仅管理员可操作" if admin_only else "直接进入服务主页", "tone": "warning" if admin_only else "success"},
    ]
    return {
        "template": "service_menu",
        "title": title,
        "subtitle": subtitle,
        "stats": [
            {"label": "服务总数", "value": total_count},
            {"label": "已开启", "value": enabled_count},
            {"label": "已关闭", "value": max(0, total_count - enabled_count)},
        ],
        "badges": badges,
        "sections": [
            {
                "title": "服务列表",
                "description": "状态会实时读取本群当前配置。",
                "columns": 2,
                "items": items,
            }
        ],
        "hint": footer,
        "card_width": 860,
    }


def _build_service_action_card(
    service_type: Services,
    visible_commands: list,
    *,
    service_enabled: bool,
) -> dict:
    items = []
    for index, cmd in enumerate(visible_commands, start=1):
        meta_parts = []
        if cmd.allow_when_disabled:
            meta_parts.append("关闭状态也可使用")
        if not meta_parts:
            meta_parts.append("回复序号即可执行")
        items.append(
            {
                "index": str(index),
                "title": cmd.cmd,
                "description": cmd.desc or "执行该操作",
                "meta": " / ".join(meta_parts),
                "status": "需参数" if cmd.need_arg else "直达",
                "status_tone": "warning" if cmd.need_arg else "accent",
            }
        )

    return {
        "template": "service_menu",
        "title": f"{service_type.chinese_name}菜单" if service_enabled else f"{service_type.chinese_name}管理菜单",
        "subtitle": (
            "选择一个操作继续。"
            if service_enabled
            else "当前总开关为关闭状态，仅展示可直接使用的管理命令。"
        ),
        "badges": [
            {
                "text": "总开关已开启" if service_enabled else "总开关已关闭",
                "tone": "success" if service_enabled else "danger",
            }
        ],
        "sections": [
            {
                "title": "可用操作",
                "description": "需要参数的操作会在下一步提示输入。",
                "columns": 1,
                "items": items,
            }
        ],
        "hint": "回复序号执行，输入“退出”取消。",
        "card_width": 820,
    }


def _build_feature_settings_card(service_type: Services, snap, feature_cmds: list) -> dict:
    enabled_count = 0
    items = []
    for index, cmd in enumerate(feature_cmds, start=1):
        is_on = snap.is_feature_enabled(cmd.handler_name, default=True) if snap else True
        if is_on:
            enabled_count += 1
        items.append(
            {
                "index": str(index),
                "title": cmd.cmd,
                "description": cmd.desc or "切换该子功能的开关状态",
                "meta": "回复序号即可切换",
                "status": "开启" if is_on else "关闭",
                "status_tone": "success" if is_on else "danger",
            }
        )

    total_count = len(items)
    return {
        "template": "service_menu",
        "title": f"{service_type.chinese_name}命令子功能",
        "subtitle": "这里配置的是命令级开关，不会覆盖业务配置项。",
        "stats": [
            {"label": "命令数", "value": total_count},
            {"label": "已开启", "value": enabled_count},
            {"label": "已关闭", "value": max(0, total_count - enabled_count)},
        ],
        "badges": [{"text": "回复序号切换", "tone": "accent"}],
        "sections": [
            {
                "title": "命令子功能列表",
                "description": "关闭总开关时，命令子功能配置会保留但暂不生效。",
                "columns": 1,
                "items": items,
            }
        ],
        "hint": "回复序号切换开关，输入“退出”取消。",
        "card_width": 820,
    }


def _get_config_option_type_label(option: ServiceConfigOption) -> str:
    option_type = str(option.type or "text").strip().lower()
    mapping = {
        "bool": "开关",
        "int": "整数",
        "text": "文本",
        "time": "时间",
        "select": "选项",
    }
    return mapping.get(option_type, option_type or "文本")


def _get_config_option_status_tone(option: ServiceConfigOption, display_value: str) -> str:
    option_type = str(option.type or "text").strip().lower()
    if option_type == "bool":
        return "success" if display_value == "开启" else "danger"
    return "accent"


def _build_config_settings_card(service_type: Services, service, options: list[ServiceConfigOption]) -> dict:
    sections = []
    grouped_items: dict[str, list[dict]] = {}
    order: list[str] = []
    for index, option in enumerate(options, start=1):
        group_name = str(option.group or "基础设置")
        if group_name not in grouped_items:
            grouped_items[group_name] = []
            order.append(group_name)
        display_value = service.format_config_option_value(option)
        grouped_items[group_name].append(
            {
                "index": str(index),
                "title": option.title,
                "description": option.description or "调整该配置项的当前值",
                "meta": f"类型：{_get_config_option_type_label(option)}",
                "status": display_value,
                "status_tone": _get_config_option_status_tone(option, display_value),
            }
        )

    for group_name in order:
        sections.append(
            {
                "title": group_name,
                "description": f"{group_name}下的业务配置项。",
                "columns": 1,
                "items": grouped_items[group_name],
            }
        )

    return {
        "template": "service_menu",
        "title": f"{service_type.chinese_name}配置项",
        "subtitle": "这里配置的是业务参数，不同于命令级子功能开关。",
        "stats": [
            {"label": "配置项数", "value": len(options)},
            {"label": "分组数", "value": len(sections)},
        ],
        "badges": [
            {"text": "回复序号进入", "tone": "accent"},
            {"text": "支持开关/时间/数值", "tone": "success"},
        ],
        "sections": sections,
        "hint": "回复序号进入编辑，输入“退出”取消。",
        "card_width": 820,
    }


def _build_config_option_prompt(service_type: Services, service, option: ServiceConfigOption) -> str:
    current_value = service.format_config_option_value(option)
    lines = [
        f"⚙️ {service_type.chinese_name} · {option.title}",
        f"当前值：{current_value}",
    ]
    if option.description:
        lines.append(f"说明：{option.description}")

    option_type = str(option.type or "text").strip().lower()
    if option_type == "int":
        limit_text = []
        if option.min_value is not None:
            limit_text.append(f"最小值 {option.min_value}")
        if option.max_value is not None:
            limit_text.append(f"最大值 {option.max_value}")
        if limit_text:
            lines.append(f"请输入整数（{'，'.join(limit_text)}）")
        else:
            lines.append("请输入整数")
    elif option_type == "time":
        lines.append("请输入 HH:MM 格式，例如 22:00")
    elif option_type == "select":
        lines.append("请选择以下选项之一：")
        for index, choice in enumerate(option.choices or [], start=1):
            label = str(choice.get("label") or choice.get("value") or f"选项 {index}")
            description = str(choice.get("description") or "").strip()
            if description:
                lines.append(f"{index}. {label} - {description}")
            else:
                lines.append(f"{index}. {label}")
        lines.append("可输入序号、标签或实际值")
    else:
        lines.append(option.placeholder or "请输入新的配置值")

    lines.append("输入“退出”可取消。")
    return "\n".join(lines)


def _build_service_settings_card(
    service_type: Services,
    *,
    enabled_now: bool,
    feature_count: int,
    config_count: int,
) -> dict:
    return {
        "template": "service_menu",
        "title": f"{service_type.chinese_name}设置",
        "subtitle": "先决定总开关，再区分命令级子功能和业务配置项。",
        "badges": [
            {
                "text": "总开关已开启" if enabled_now else "总开关已关闭",
                "tone": "success" if enabled_now else "danger",
            },
            {"text": "仅管理员可操作", "tone": "warning"},
        ],
        "sections": [
            {
                "title": "设置入口",
                "description": "选择要调整的层级。",
                "columns": 1,
                "items": [
                    {
                        "index": "1",
                        "title": "总开关",
                        "description": f"当前状态：{'开启' if enabled_now else '关闭'}",
                        "meta": "切换后会影响整个服务的可用性",
                        "status": "开启" if enabled_now else "关闭",
                        "status_tone": "success" if enabled_now else "danger",
                    },
                    {
                        "index": "2",
                        "title": "命令子功能",
                        "description": f"当前共 {feature_count} 个命令级子功能",
                        "meta": "总开关关闭时，命令子功能状态会被保留",
                        "status": "配置",
                        "status_tone": "accent",
                    },
                    {
                        "index": "3",
                        "title": "配置项",
                        "description": f"当前共 {config_count} 个业务配置项",
                        "meta": "用于设置时间、阈值、自动功能等业务参数",
                        "status": "配置",
                        "status_tone": "success",
                    },
                ],
            }
        ],
        "hint": "回复序号继续，输入“退出”取消。",
        "card_width": 820,
    }


def _parse_service_choice(text: str) -> Optional[Services]:
    menu_service_types = _get_menu_service_types()
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        index = int(cleaned) - 1
        if 0 <= index < len(menu_service_types):
            return menu_service_types[index]
    for stype in menu_service_types:
        if cleaned in {stype.name, stype.value, stype.chinese_name}:
            return stype
    return None


async def _open_default_service_entry(event: GroupMessageEvent, service_type: Services) -> None:
    await run_service(
        group_id=event.group_id,
        service_enum=service_type,
        action=service_manager.get_default_action_name(service_type),
        event=event,
    )


def _build_service_navigation_flow(event: GroupMessageEvent) -> dict:
    lines = ["请选择服务："]
    routes = {}
    items = []
    enabled_count = 0
    for index, stype in enumerate(_get_menu_service_types(), start=1):
        snap = _get_service_snapshot(event.group_id, stype, self_id=event.self_id)
        enabled = bool(getattr(snap, "enabled", False)) if snap else False
        if enabled:
            enabled_count += 1
        lines.append(f"{index}. {stype.chinese_name} {'✅' if enabled else '⛔'}")
        items.append(
            {
                "index": str(index),
                "title": stype.chinese_name,
                "description": f"共 {_get_service_command_count(stype)} 个可用命令",
                "meta": f"回复 {index} 或 {stype.chinese_name}",
                "status": "开启" if enabled else "关闭",
                "status_tone": "success" if enabled else "danger",
            }
        )

        async def runner(target_service: Services = stype):
            await _open_default_service_entry(event, target_service)

        for key in {str(index), stype.name, stype.value, stype.chinese_name}:
            routes[key] = runner

    lines.append("输入序号或服务名称，或输入“退出”取消。")
    return {
        "title": "服务中心",
        "subtitle": "按服务浏览功能，直接进入对应服务主页。",
        "text": "\n".join(lines),
        "template": "service_menu",
        "stats": [
            {"label": "服务总数", "value": len(items)},
            {"label": "已开启", "value": enabled_count},
            {"label": "已关闭", "value": max(0, len(items) - enabled_count)},
        ],
        "badges": [
            {"text": "回复序号或服务名称", "tone": "accent"},
            {"text": "直接进入服务主页", "tone": "success"},
        ],
        "sections": [
            {
                "title": "服务列表",
                "description": "每个服务都会显示当前群内的总开关状态。",
                "columns": 2,
                "items": items,
            }
        ],
        "hint": "输入序号或服务名称，或输入“退出”取消。",
        "routes": routes,
    }


async def _prompt_text(matcher: Matcher, prompt, timeout: int = 60) -> Optional[str]:
    if isinstance(prompt, dict):
        try:
            await matcher.send(await render_card_message(prompt))
        except Exception as exc:
            print(exc)
            await matcher.send(format_card_fallback_text(prompt))
    else:
        await matcher.send(prompt)
    response = await wait_for(timeout)
    if not response:
        await matcher.send("❌ 超时，已取消。")
        return None
    response = response.strip()
    if response.lower() == "退出":
        await matcher.send("❌ 已取消。")
        return None
    return response


async def _send_text_message(msg: str, *, at_sender: bool = False) -> None:
    try:
        await UniMessage.text(msg).send(at_sender=at_sender)
    except ActionFailed:
        pass


async def _send_audio_message(path) -> None:
    try:
        await UniMessage.audio(path=path).send()
    except ActionFailed:
        pass


async def _run_menu_command(
    *,
    matcher: Matcher,
    event: GroupMessageEvent,
    service_type: Services,
    handler_name: str,
    need_arg: bool,
) -> None:
    kwargs = {"event": event}
    if need_arg:
        arg_text = await _prompt_text(matcher, "请输入参数内容（60 秒内），或输入“退出”取消：")
        if arg_text is None:
            return
        kwargs["arg"] = Message(arg_text)

    await run_service(
        group_id=event.group_id,
        service_enum=service_type,
        action=handler_name,
        **kwargs,
    )


async def _open_service_menu(matcher: Matcher, event: GroupMessageEvent, service_type: Services) -> None:
    snap = _get_service_snapshot(event.group_id, service_type, self_id=event.self_id)
    service_enabled = bool(getattr(snap, "enabled", False)) if snap else False
    commands_meta = service_manager.get_service_commands(service_type)
    visible_commands = []
    for cmd in commands_meta:
        if cmd.handler_name in ("enable_service", "disable_service"):
            continue
        if not service_enabled and not cmd.allow_when_disabled:
            continue
        if snap and not snap.is_feature_enabled(cmd.handler_name, default=True):
            continue
        visible_commands.append(cmd)

    if not visible_commands:
        if service_enabled:
            await matcher.send(f"{service_type.chinese_name}当前没有可用命令。")
        else:
            await matcher.send(
                f"🚫 本群{service_type.chinese_name}未开启，且当前没有可在关闭状态下使用的管理命令。\n"
                "管理员请使用『/设置』开启。"
            )
        return

    if service_enabled:
        prompt_card = _build_service_action_card(
            service_type,
            visible_commands,
            service_enabled=True,
        )
    else:
        prompt_card = _build_service_action_card(
            service_type,
            visible_commands,
            service_enabled=False,
        )
    choice = await _prompt_text(matcher, prompt_card)
    if choice is None:
        return
    if not choice.isdigit():
        await matcher.send("❌ 请输入有效序号。")
        return

    index = int(choice) - 1
    if not (0 <= index < len(visible_commands)):
        await matcher.send("❌ 无效序号。")
        return

    selected = visible_commands[index]
    await _run_menu_command(
        matcher=matcher,
        event=event,
        service_type=service_type,
        handler_name=selected.handler_name,
        need_arg=selected.need_arg,
    )


async def _open_feature_settings(matcher: Matcher, event: GroupMessageEvent, service_type: Services) -> None:
    snap = _get_service_snapshot(event.group_id, service_type, self_id=event.self_id)
    commands_meta = service_manager.get_service_commands(service_type)
    feature_cmds = [c for c in commands_meta if c.handler_name not in ("enable_service", "disable_service")]
    if not feature_cmds:
        await matcher.send("当前没有可配置的命令级子功能。")
        return

    choice = await _prompt_text(
        matcher,
        _build_feature_settings_card(service_type, snap, feature_cmds),
    )
    if choice is None:
        return
    if not choice.isdigit():
        await matcher.send("❌ 请输入有效序号。")
        return

    index = int(choice) - 1
    if not (0 <= index < len(feature_cmds)):
        await matcher.send("❌ 无效序号。")
        return

    selected = feature_cmds[index]
    service = await service_manager.get_service(
        event.group_id,
        service_type,
        self_id=event.self_id,
    )
    current = service.is_feature_enabled(selected.handler_name, default=True)
    service.set_feature_enabled(selected.handler_name, not current)
    await matcher.send(f"✅ 命令子功能『{selected.cmd}』已{'开启' if not current else '关闭'}。")
    if hasattr(service, "enabled") and not getattr(service, "enabled", False):
        await matcher.send("提示：当前总开关仍为关闭状态，命令子功能开启后需先开启总开关才会生效。")


async def _open_config_settings(matcher: Matcher, event: GroupMessageEvent, service_type: Services) -> None:
    service = await service_manager.get_service(
        event.group_id,
        service_type,
        self_id=event.self_id,
    )
    options = service.get_config_options()
    if not options:
        await matcher.send("当前没有可配置的业务配置项。")
        return

    choice = await _prompt_text(
        matcher,
        _build_config_settings_card(service_type, service, options),
    )
    if choice is None:
        return
    if not choice.isdigit():
        await matcher.send("❌ 请输入有效序号。")
        return

    index = int(choice) - 1
    if not (0 <= index < len(options)):
        await matcher.send("❌ 无效序号。")
        return

    selected = options[index]
    selected_type = str(selected.type or "text").strip().lower()
    if selected_type == "bool":
        current = bool(service.get_config_option_value(selected))
        try:
            service.apply_config_option_value(selected.key, not current)
        except Exception as exc:
            await matcher.send(f"❌ 配置项更新失败：{exc}")
            return
        new_value = service.format_config_option_value(selected)
        await matcher.send(f"✅ 配置项『{selected.title}』已更新为：{new_value}")
    else:
        raw_value = await _prompt_text(
            matcher,
            _build_config_option_prompt(service_type, service, selected),
        )
        if raw_value is None:
            return
        success, normalized_value, error_message = service.parse_config_option_input(selected, raw_value)
        if not success:
            await matcher.send(f"❌ {error_message}")
            return
        try:
            service.apply_config_option_value(selected.key, normalized_value)
        except Exception as exc:
            await matcher.send(f"❌ 配置项更新失败：{exc}")
            return
        new_value = service.format_config_option_value(selected)
        await matcher.send(f"✅ 配置项『{selected.title}』已更新为：{new_value}")

    if hasattr(service, "enabled") and not getattr(service, "enabled", False):
        await matcher.send("提示：当前总开关仍为关闭状态，配置项已保存，开启服务后才会生效。")


async def _open_service_settings(matcher: Matcher, event: GroupMessageEvent, service_type: Services) -> None:
    snap = _get_service_snapshot(event.group_id, service_type, self_id=event.self_id)
    enabled_now = bool(getattr(snap, "enabled", False)) if snap else False
    commands_meta = service_manager.get_service_commands(service_type)
    feature_cmds = [c for c in commands_meta if c.handler_name not in ("enable_service", "disable_service")]
    config_options = snap.get_config_options() if snap else []
    choice = await _prompt_text(
        matcher,
        _build_service_settings_card(
            service_type,
            enabled_now=enabled_now,
            feature_count=len(feature_cmds),
            config_count=len(config_options),
        ),
    )
    if choice is None:
        return

    if choice == "1":
        service = await service_manager.get_service(
            event.group_id,
            service_type,
            self_id=event.self_id,
        )
        current = bool(getattr(service, "enabled", False))
        if current:
            await service.disable_service()
        else:
            await service.enable_service()
        if current and not bool(getattr(service, "enabled", False)):
            await matcher.send("提示：总开关关闭时，所有子功能都会暂时失效，但子开关配置会保留。")
        return

    if choice == "2":
        await _open_feature_settings(matcher, event, service_type)
        return

    if choice == "3":
        await _open_config_settings(matcher, event, service_type)
        return

    await matcher.send("❌ 无效序号。")


async def handle_menu(matcher: Matcher, event: GroupMessageEvent, arg: Message) -> None:
    service_type = _parse_service_choice(arg.extract_plain_text())
    if service_type is not None:
        await _open_default_service_entry(event, service_type)
        return

    group = service_manager.get_group(event.group_id, self_id=event.self_id)
    await run_flow(group, _build_service_navigation_flow(event))


async def handle_settings(matcher: Matcher, event: GroupMessageEvent, arg: Message) -> None:
    if not _is_admin(event):
        await matcher.finish("⛔ 仅管理员可使用『/设置』。")

    service_type = _parse_service_choice(arg.extract_plain_text())
    if service_type is None:
        choice = await _prompt_text(
            matcher,
            _build_service_selector_card(
                event.group_id,
                title="群服务设置",
                subtitle="先选择服务，再决定总开关或子功能开关。",
                footer="回复序号继续，输入“退出”取消。",
                admin_only=True,
            ),
        )
        if choice is None:
            return
        service_type = _parse_service_choice(choice)
    if service_type is None:
        await matcher.send("❌ 无法识别服务，请重试。")
        return
    await _open_service_settings(matcher, event, service_type)


def get_private_ai_manager():
    global _private_ai_manager
    if _private_ai_manager is None:
        _private_ai_manager = AIAssistantManager()
    return _private_ai_manager


def _format_job_status(job: dict) -> str:
    return (
        f"任务 {job['job_id']}\n"
        f"状态：{job.get('status')}\n"
        f"模式：{job.get('resume_mode') or '未知'}\n"
        f"会话：{job.get('codex_session_id') or '未记录'}\n"
        f"创建：{job.get('created_at') or '未知'}\n"
        f"开始：{job.get('started_at') or '未开始'}\n"
        f"结束：{job.get('finished_at') or '未结束'}"
    )


def _format_command(parts: List[str]) -> str:
    return " ".join(parts) if parts else "(空)"


def _format_selftest(info: dict) -> str:
    lines = ["Codex 桥接自检："]
    lines.append(f"状态：{'就绪' if info.get('ready') else '未就绪'}")
    if info.get("resolved_executable"):
        lines.append(f"可执行文件：{info['resolved_executable']}")
    elif info.get("configured_command"):
        lines.append(f"命令配置：{_format_command(info['configured_command'])}")
    if info.get("resolved_workdir"):
        lines.append(f"工作目录：{info['resolved_workdir']}")
    elif info.get("configured_workdir"):
        lines.append(f"工作目录：{info['configured_workdir']}")
    if info.get("resolved_command"):
        lines.append(f"执行参数：{_format_command(info['resolved_command'][1:]) or '(无)'}")
    if info.get("version"):
        lines.append(f"版本：{info['version']}")
    if info.get("command_error"):
        lines.append(f"命令错误：{info['command_error']}")
    if info.get("workdir_error"):
        lines.append(f"目录错误：{info['workdir_error']}")
    if info.get("version_error"):
        lines.append(f"版本检查错误：{info['version_error']}")
    return "\n".join(lines)


services = on_command("群服务", priority=2, block=False)


@services.handle()
async def _(event: GroupMessageEvent):
    group = service_manager.get_group(event.group_id, self_id=event.self_id)
    help_text = await service_manager.group_service_help(group)
    if help_text:
        await group.send_msg(help_text)
    await service_manager.group_service_panel(group)


menu_entry = on_command("服务", aliases={"菜单"}, priority=2, block=True)


@menu_entry.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, arg: Message = CommandArg()):
    await handle_menu(matcher, event, arg)


law_query = on_command("群规", aliases={"查群规", "依据"}, priority=2, block=True)


@law_query.handle()
async def _(matcher: Matcher, arg: Message = CommandArg()):
    query = arg.extract_plain_text().strip()
    if not query:
        await matcher.send(
            "可查看：/群规原文、/简明群规、/群规FAQ原文\n"
            "可查询：/群规 弹劾冻结、/条文 第三十五条、/FAQ 荣誉群主"
        )
        return
    await matcher.send(format_law_search_response(query, source="all", limit=3))


law_faq_query = on_command("FAQ", aliases={"faq", "群规FAQ", "问答"}, priority=2, block=True)


@law_faq_query.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    query = arg.extract_plain_text().strip()
    if not query:
        await _send_law_document(matcher, bot, event, "faq")
        return
    await matcher.send(format_law_search_response(query, source="faq", limit=3))


law_article_query = on_command("条文", aliases={"查条文"}, priority=2, block=True)


@law_article_query.handle()
async def _(matcher: Matcher, arg: Message = CommandArg()):
    query = arg.extract_plain_text().strip()
    if not query:
        await matcher.send("用法：/条文 第三十五条")
        return
    await matcher.send(format_law_search_response(query, source="laws", limit=3))


law_original_query = on_command("群规原文", aliases={"群规全文", "laws原文"}, priority=2, block=True)
law_brief_original_query = on_command(
    "简明群规",
    aliases={"群规简明版", "简明版群规", "简明群规全文"},
    priority=2,
    block=True,
)
law_faq_original_query = on_command(
    "群规FAQ原文",
    aliases={"群规FAQ全文", "FAQ全文", "FAQ原文", "问答全文"},
    priority=2,
    block=True,
)

LAW_ORIGINAL_FORWARD_BATCH_DELAY_SECONDS = 1.5
LAW_ORIGINAL_FORWARD_RETRIES = 1


class LawOriginalForwardSendError(RuntimeError):
    def __init__(self, index: int, total: int, original: Exception):
        self.index = index
        self.total = total
        self.original = original
        super().__init__(f"第 {index}/{total} 批发送失败：{original}")


LAW_DOCUMENT_KEYS = {
    "正文": "laws",
    "正式": "laws",
    "正式文本": "laws",
    "原文": "laws",
    "laws": "laws",
    "law": "laws",
    "简明": "brief",
    "简明版": "brief",
    "简明群规": "brief",
    "brief": "brief",
    "FAQ": "faq",
    "faq": "faq",
    "问答": "faq",
    "群规FAQ": "faq",
}

LAW_DOCUMENT_TITLES = {
    "laws": "群规原文",
    "brief": "简明群规",
    "faq": "群规 FAQ",
}


def _resolve_law_document_key(text: str, default: str = "laws") -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return default
    return LAW_DOCUMENT_KEYS.get(normalized, default)


async def _send_law_plain_chunks(matcher: Matcher, nodes: List[dict], title: str):
    chunks = chunk_law_original_plain_text(nodes, max_chars=2800)
    if not chunks:
        await matcher.send(f"未找到可发送的{title}内容。")
        return

    if len(chunks) > 1:
        await matcher.send(f"{title}将改用普通消息分 {len(chunks)} 段发送。")
    for index, chunk in enumerate(chunks, start=1):
        prefix = f"{title}（{index}/{len(chunks)}）\n" if len(chunks) > 1 else ""
        await matcher.send(prefix + chunk)


async def _send_law_forward_chunks(chunks: List[List[dict]], send_chunk):
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        last_error: Optional[Exception] = None
        for attempt in range(LAW_ORIGINAL_FORWARD_RETRIES + 1):
            if attempt > 0:
                await asyncio.sleep(LAW_ORIGINAL_FORWARD_BATCH_DELAY_SECONDS)
            try:
                await send_chunk(chunk)
                last_error = None
                break
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise LawOriginalForwardSendError(index, total, last_error) from last_error

        if index < total:
            await asyncio.sleep(LAW_ORIGINAL_FORWARD_BATCH_DELAY_SECONDS)


async def _send_law_document(
    matcher: Matcher,
    bot: Bot,
    event: MessageEvent,
    key: str,
):
    title = LAW_DOCUMENT_TITLES.get(key, "群规文档")
    nodes = build_law_document_forward_nodes(key, name=title, uin=str(event.self_id))
    if not nodes:
        await matcher.send(f"未找到可发送的{title}。")
        return
    chunks = chunk_law_forward_nodes(nodes)
    try:
        if isinstance(event, GroupMessageEvent):
            if len(chunks) > 1:
                await matcher.send(f"{title}较长，将分 {len(chunks)} 条合并转发发送。")
            async def send_group_chunk(chunk):
                await bot.send_group_forward_msg(group_id=event.group_id, messages=chunk)

            await _send_law_forward_chunks(chunks, send_group_chunk)
            return
        if isinstance(event, PrivateMessageEvent):
            if len(chunks) > 1:
                await matcher.send(f"{title}较长，将分 {len(chunks)} 条合并转发发送。")
            async def send_private_chunk(chunk):
                await bot.send_private_forward_msg(user_id=event.user_id, messages=chunk)

            await _send_law_forward_chunks(chunks, send_private_chunk)
            return
        await matcher.send(f"当前消息类型不支持发送{title}。")
    except LawOriginalForwardSendError as exc:
        traceback.print_exc()
        await matcher.send(
            f"{title}合并转发发送失败，从第 {exc.index}/{exc.total} 批起改用普通消息分段发送。原因：{exc.original}"
        )
        remaining_nodes = [node for chunk in chunks[exc.index - 1 :] for node in chunk]
        try:
            await _send_law_plain_chunks(matcher, remaining_nodes, title)
        except Exception as fallback_exc:
            traceback.print_exc()
            await matcher.send(f"{title}普通消息发送也失败：{fallback_exc}")
    except Exception as exc:
        traceback.print_exc()
        await matcher.send(f"{title}合并转发发送失败，改用普通消息分段发送。原因：{exc}")
        try:
            await _send_law_plain_chunks(matcher, nodes, title)
        except Exception as fallback_exc:
            traceback.print_exc()
            await matcher.send(f"{title}普通消息发送也失败：{fallback_exc}")


@law_original_query.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    key = _resolve_law_document_key(arg.extract_plain_text(), default="laws")
    await _send_law_document(matcher, bot, event, key)


@law_brief_original_query.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent):
    await _send_law_document(matcher, bot, event, "brief")


@law_faq_original_query.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent):
    await _send_law_document(matcher, bot, event, "faq")


settings_entry = on_command("设置", priority=2, block=True)


@settings_entry.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, arg: Message = CommandArg()):
    await handle_settings(matcher, event, arg)


activity_viewer = on_command("群活动", priority=2, block=True)


@activity_viewer.handle()
async def _():
    await activity_viewer.send(
        "成员命令如下：\n"
        "/发起活动\n(如果您想发起编曲接龙)\n"
        "/发起议题\n(和群友们一起讨论大事)\n"
        "/发起放逐\n(禁言违规的群友)\n"
        "/发起投票\n(如果您想投票选举)\n"
        "管理员命令如下：\n"
        "/通过活动+序号\n(通过活动并发出公告)\n"
        "/整理文件\n(整理未能及时整理的文件)"
    )


menu_command = on_command("撤回", priority=5, block=True)


@menu_command.handle()
async def _(event: GroupMessageEvent):
    if event.reply:
        await service_manager.get_group(event.group_id, self_id=event.self_id).delete_msg(event.reply.message_id)


ai_private_msg = on_message(rule=Rule(_is_private_message_event), priority=20, block=True)


@ai_private_msg.handle()
async def _(event: PrivateMessageEvent):
    ai_manager = get_private_ai_manager()
    ai_assistant = ai_manager.get_private_server(event.user_id)
    if event.user_id in ai_assistant.black_list:
        return
    msg_text = event.get_message().extract_plain_text().strip()
    if not msg_text and not event.reply:
        await ai_private_msg.send("我现在只能处理文字消息。")
        return
    try:
        await ai_assistant.reply(event)
    except Exception as exc:
        traceback.print_exc()
        await ai_private_msg.send(f"私聊 AI 出错：{exc}")


ai_private_poke = on_notice(priority=5, block=True)


@ai_private_poke.handle()
async def _(event: PokeNotifyEvent):
    if getattr(event, "group_id", None):
        return
    if event.target_id != event.self_id:
        return

    ai_manager = get_private_ai_manager()
    ai_assistant = ai_manager.get_private_server(event.user_id)
    await ai_assistant.text_menu()


ai_private_speak = on_command("说", priority=2, block=True)


@ai_private_speak.handle()
async def _(event: PrivateMessageEvent, arg: Message = CommandArg()):
    ai_manager = get_private_ai_manager()
    ai_assistant = ai_manager.get_private_server(event.user_id)
    if event.user_id in ai_assistant.black_list:
        return

    if event.reply:
        msg = event.reply.message.extract_plain_text()
    elif arg.extract_plain_text():
        msg = arg.extract_plain_text()
    else:
        msg = await _prompt_text(ai_private_speak, "请指定要说的内容。", timeout=10)
        if msg is None:
            return

    if ai_assistant.speech_generator:
        speech_text = process_text(msg, for_speech=True)
        if not speech_text:
            await _send_text_message("没有可朗读的内容。")
            return

        path = await ai_assistant.speech_generator.gen_speech(
            text=speech_text,
            voice_id=ai_assistant.character.voice_id,
            music_enable=ai_assistant.music_enable,
        )
        if path:
            await _send_audio_message(path)
        else:
            await _send_text_message("语音生成失败")
    else:
        await _send_text_message("当前角色不支持语音")


codex_command = on_command("codex", priority=2, block=True)


@codex_command.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        await codex_command.send("当前事件类型不支持 Codex 桥接。")
        return

    if not codex_bridge.is_allowed(event):
        await codex_command.send("当前账号或群组未被授权使用 Codex 桥接。")
        return

    text = _extract_text(event, arg)
    if not text:
        await codex_command.send(
            "用法：\n"
            "/codex 你的任务\n"
            "/codex 状态 [任务ID]\n"
            "/codex 最近\n"
            "/codex 取消 <任务ID>\n"
            "/codex 自检"
        )
        return

    first, _, rest = text.partition(" ")
    action = first.strip().lower()
    payload = rest.strip()

    if action in {"状态", "status"}:
        jobs = codex_bridge.list_jobs(int(event.user_id))
        if payload:
            job = codex_bridge.get_job(payload)
            if not job or int(job["user_id"]) != int(event.user_id):
                await codex_command.send("未找到该任务。")
                return
            await codex_command.send(_format_job_status(job))
            return
        if not jobs:
            await codex_command.send("你还没有 Codex 任务记录。")
            return
        await codex_command.send(_format_job_status(jobs[0]))
        return

    if action in {"最近", "history", "list"}:
        jobs = codex_bridge.list_jobs(int(event.user_id))
        if not jobs:
            await codex_command.send("你还没有 Codex 任务记录。")
            return
        lines = ["最近任务："]
        for job in jobs:
            lines.append(
                f"{job['job_id']} | {job.get('status')} | "
                f"{job.get('resume_mode') or '未知'} | "
                f"{(job.get('prompt') or '').strip()[:32]}"
            )
        await codex_command.send("\n".join(lines))
        return

    if action in {"取消", "cancel"}:
        if not payload:
            await codex_command.send("请提供要取消的任务 ID。")
            return
        ok = await codex_bridge.cancel_job(job_id=payload, user_id=int(event.user_id))
        if ok:
            await codex_command.send(f"已取消任务 {payload}。")
        else:
            await codex_command.send("取消失败：任务不存在、无权限，或任务已经结束。")
        return

    if action in {"自检", "check", "health"}:
        info = await codex_bridge.run_selftest()
        await codex_command.send(_format_selftest(info))
        return

    prompt = text
    try:
        job = codex_bridge.create_job(event, prompt)
    except RuntimeError as exc:
        await codex_command.send(str(exc))
        return
    await codex_command.send(
        f"已提交 Codex 任务 {job.job_id}。\n"
        f"执行完成后我会主动把结果发回这里。\n"
        f"可用 `/codex 状态 {job.job_id}` 查看进度，`/codex 最近` 查看历史。"
    )


async def _run_runtime_cache_cleanup(reason: str) -> None:
    try:
        review = await asyncio.to_thread(run_storage_guard, reason)
    except Exception as exc:
        print(f"存储巡检与缓存清理失败（{reason}）: {exc}")
        traceback.print_exc()
        return

    if review.warnings or review.low_disk:
        print(f"存储巡检完成（{reason}）：{summarize_storage_review(review)}")


@get_driver().on_startup
async def cleanup_runtime_caches_on_startup():
    await _run_runtime_cache_cleanup("startup")


@scheduler.scheduled_job(
    "interval",
    hours=RUNTIME_CACHE_CLEANUP_INTERVAL_HOURS,
    id="runtime_cache_cleanup",
)
async def cleanup_runtime_caches_periodically():
    await _run_runtime_cache_cleanup("scheduled")


def init_scheduled_callbacks() -> None:
    try:
        migrated_service_config_count = migrate_all_legacy_service_configs()
        migrated_ai_config_count = migrate_all_legacy_ai_assistant_configs()
        restored_count, pruned_count = _restore_service_state_tasks_to_scheduler()
        tool_restored_count, tool_pruned_count = restore_scheduled_tool_jobs_to_runtime()
        runtime_tasks = iter_runtime_tasks()
        for task_id, task in runtime_tasks.items():
            callback_id = task.get("callback_id", "")
            group_id = task.get("group_id")
            if not group_id:
                continue

            if callback_id.startswith("file_organize_"):

                def make_organize_callback(gid):
                    async def cb():
                        service = await service_manager.get_service(gid, Services.File)
                        await service.organize_files()

                    return cb

                register_runtime_callback(callback_id, make_organize_callback(group_id))
            elif callback_id.startswith("file_arrange_"):

                def make_arrange_callback(gid):
                    async def cb():
                        service = await service_manager.get_service(gid, Services.File)
                        await service.arrange_files()

                    return cb

                register_runtime_callback(callback_id, make_arrange_callback(group_id))
            elif callback_id.startswith("schedule_msg_callback_"):
                message = task.get("message", "")
                if not message:
                    description = task.get("description", "")
                    if ": " in description:
                        message = description.split(": ", 1)[1].rstrip("...")
                    else:
                        message = description

                def make_msg_callback(gid, msg):
                    async def cb():
                        group = group_context_factory.get_group(gid)
                        await group.send_msg(f"⏰ 定时提醒：\n{msg}")

                    return cb

                register_runtime_callback(callback_id, make_msg_callback(group_id, message))
            elif callback_id.startswith("wordcloud_daily_"):

                def make_wordcloud_callback(gid):
                    async def cb():
                        service = await service_manager.get_service(gid, Services.Wordcloud)
                        await service.send_daily_wordcloud()

                    return cb

                register_runtime_callback(callback_id, make_wordcloud_callback(group_id))

        register_runtime_scheduler_job()
        register_reminder_scheduler_jobs()

        print(
            f"已初始化 {len(runtime_tasks)} 个定时任务回调"
            f"（迁移旧服务配置 {migrated_service_config_count} 个，"
            f"迁移旧 AI 配置 {migrated_ai_config_count} 个，"
            f"数据库回灌 {restored_count} 个任务，"
            f"恢复工具定时任务 {tool_restored_count} 个，"
            f"清理过期一次性任务 {pruned_count + tool_pruned_count} 个）"
        )
    except Exception as e:
        print(f"初始化定时任务回调失败: {e}")
        traceback.print_exc()


@scheduler.scheduled_job("cron", hour=4, minute=0, id="organize_files_fallback")
async def organize_files_fallback():
    try:
        for group_id in _iter_persisted_group_ids():
            service = await service_manager.get_service(group_id, Services.File)
            runtime_task = get_runtime_task(f"auto_organize_{group_id}")
            if _should_run_auto_organize_fallback(service, runtime_task):
                await service.organize_files()
    except Exception as e:
        print(e)
        traceback.print_exc()


@scheduler.scheduled_job("cron", hour=6, minute=0, id="release")
async def release_group_ban():
    for group_id in _iter_daily_release_group_ids():
        try:
            group = group_context_factory.get_group(group_id)
            await group.release_ban()
            await group.send_msg("全体禁言已解除，迎接新的一天吧(每日首次发言，雪豹会自动为你主页点赞哦)")
        except Exception as exc:
            print(f"[release_group_ban] 群 {group_id} 执行失败: {exc}")
            traceback.print_exc()


init_scheduled_callbacks()

__all__ = [
    "activity_viewer",
    "ai_private_msg",
    "ai_private_poke",
    "ai_private_speak",
    "codex_bridge",
    "codex_command",
    "get_private_ai_manager",
    "handle_menu",
    "handle_settings",
    "init_scheduled_callbacks",
    "internal_api_router",
    "menu_command",
    "menu_entry",
    "organize_files_fallback",
    "release_group_ban",
    "services",
    "settings_entry",
]
