"""
nonebot_plugin_resolver 的 services owner facade。

`src.vendors.nonebot_plugin_resolver` 根包只保留无副作用元信息；
真正的 matcher 注册、vendor alias 绑定与运行时激活统一由本文件显式代管。
"""

import importlib
import json
import re
import shutil
import sys
from types import ModuleType

import nonebot
from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from nonebot.plugin import get_plugin, load_plugin

from src.support.core import Services
from .base import BaseService, service_action, service_message


RESOLVER_VENDOR_PACKAGE = "src.vendors.nonebot_plugin_resolver"
RESOLVER_VENDOR_ALIAS = "nonebot_plugin_resolver"

RESOLVER_DEPENDENCY_PLUGINS: tuple[str, ...] = (
    "nonebot_plugin_localstore",
)

RESOLVER_ENTRY_MODULES: tuple[str, ...] = (
    "bootstrap",
)

_RUNTIME_ACTIVATED = False
_STARTUP_CHECK_REGISTERED = False
_PREREQUISITES_VALIDATED = False

RESOLVER_RUNTIME_DEPENDENCIES: tuple[tuple[str, str, str], ...] = (
    ("bilibili-api-python", "bilibili_api", "B站解析运行库"),
    ("PyExecJS", "execjs", "抖音/TikTok 签名运行库"),
    ("aiofiles", "aiofiles", "异步文件写入支持"),
    ("yt-dlp", "yt_dlp", "YouTube/TikTok 下载运行库"),
)

RESOLVER_SYSTEM_DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("ffmpeg", "视频合并与转码"),
)

RESOLVER_CANDIDATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(bilibili\.com|b23\.tv|bili2233\.cn|(?:^|\b)BV[0-9a-zA-Z]{10}(?:\b|$))", re.IGNORECASE),
)


def _import_dependency_module(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, ""
    except ModuleNotFoundError as exc:
        missing_name = str(getattr(exc, "name", "") or "").strip()
        if missing_name == module_name or missing_name.startswith(f"{module_name}."):
            return False, "未安装"
        if missing_name:
            return False, f"缺少传递依赖 `{missing_name}`"
        return False, "导入失败"
    except Exception as exc:
        return False, str(exc)


def collect_resolver_prerequisite_failures(*, include_system: bool = True) -> tuple[str, ...]:
    failures: list[str] = []

    for distribution_name, module_name, description in RESOLVER_RUNTIME_DEPENDENCIES:
        ok, detail = _import_dependency_module(module_name)
        if ok:
            continue
        failures.append(f"`{distribution_name}`（{description}）：{detail}")

    if include_system:
        for command_name, description in RESOLVER_SYSTEM_DEPENDENCIES:
            if shutil.which(command_name):
                continue
            failures.append(f"系统命令 `{command_name}`（{description}）：未安装或不在 PATH 中")

    return tuple(failures)


def validate_resolver_runtime_prerequisites(*, include_system: bool = True) -> tuple[str, ...]:
    global _PREREQUISITES_VALIDATED
    if _PREREQUISITES_VALIDATED:
        return ()

    failures = collect_resolver_prerequisite_failures(include_system=include_system)
    if failures:
        raise RuntimeError(
            "链接解析服务启动预检失败，缺少以下硬依赖：\n"
            + "\n".join(f"- {item}" for item in failures)
            + "\n请先执行 `poetry install`，并确认系统环境变量中可用 `ffmpeg` 后再启动。"
        )

    _PREREQUISITES_VALIDATED = True
    return ()


def _register_resolver_startup_precheck() -> None:
    global _STARTUP_CHECK_REGISTERED
    if _STARTUP_CHECK_REGISTERED:
        return

    try:
        driver = nonebot.get_driver()
    except Exception:
        return

    @driver.on_startup
    async def _resolver_runtime_startup_precheck() -> None:
        validate_resolver_runtime_prerequisites()

    _STARTUP_CHECK_REGISTERED = True


def _get_loaded_bootstrap_module():
    module_names = (
        f"{RESOLVER_VENDOR_PACKAGE}.bootstrap",
        f"{RESOLVER_VENDOR_ALIAS}.bootstrap",
    )
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is not None:
            return module
    return None


def _load_resolver_shutdown_list() -> list[int]:
    bootstrap_module = _get_loaded_bootstrap_module()
    get_snapshot = getattr(bootstrap_module, "get_shutdown_list_snapshot", None) if bootstrap_module else None
    if callable(get_snapshot):
        raw_items = get_snapshot()
    else:
        from src.vendors.nonebot_plugin_resolver.core.common import load_or_initialize_list

        raw_items = load_or_initialize_list()

    normalized: list[int] = []
    seen: set[int] = set()
    for item in raw_items:
        if isinstance(item, int):
            normalized_item = item
        elif isinstance(item, str) and item.isdigit():
            normalized_item = int(item)
        else:
            continue
        if normalized_item in seen:
            continue
        seen.add(normalized_item)
        normalized.append(normalized_item)
    return normalized


def _save_resolver_shutdown_list(group_ids: list[int]) -> None:
    bootstrap_module = _get_loaded_bootstrap_module()
    replace_shutdown_list = getattr(bootstrap_module, "replace_shutdown_list", None) if bootstrap_module else None
    if callable(replace_shutdown_list):
        replace_shutdown_list(group_ids, persist=True)
        return

    from src.vendors.nonebot_plugin_resolver.core.common import save_sub_user

    deduped: list[int] = []
    seen: set[int] = set()
    for group_id in group_ids:
        if group_id in seen:
            continue
        seen.add(group_id)
        deduped.append(group_id)
    save_sub_user(deduped)


class ResolverOwnerFacade:
    vendor_package = RESOLVER_VENDOR_PACKAGE
    vendor_alias = RESOLVER_VENDOR_ALIAS
    dependency_plugins = RESOLVER_DEPENDENCY_PLUGINS
    entry_modules = RESOLVER_ENTRY_MODULES

    def load_root_plugin(self):
        plugin = get_plugin(self.vendor_alias) or get_plugin(self.vendor_package)
        if plugin is not None:
            return plugin
        return load_plugin(self.vendor_package)

    def sync_vendor_aliases(self) -> None:
        prefix = f"{self.vendor_package}."
        alias_prefix = f"{self.vendor_alias}."
        for module_name, module in list(sys.modules.items()):
            if module_name == self.vendor_package:
                continue
            if not module_name.startswith(prefix):
                continue
            aliased_name = alias_prefix + module_name[len(prefix) :]
            sys.modules.setdefault(aliased_name, module)
        for module_name, module in list(sys.modules.items()):
            if module_name == self.vendor_alias:
                continue
            if not module_name.startswith(alias_prefix):
                continue
            vendor_name = prefix + module_name[len(alias_prefix) :]
            sys.modules.setdefault(vendor_name, module)

    def bind_vendor_alias(self) -> ModuleType:
        plugin = self.load_root_plugin()
        if plugin is None:
            vendor_package = importlib.import_module(self.vendor_package)
        else:
            vendor_package = plugin.module
        sys.modules[self.vendor_alias] = vendor_package
        sys.modules[self.vendor_package] = vendor_package
        self.sync_vendor_aliases()
        return vendor_package

    def require_dependencies(self) -> None:
        for plugin_name in self.dependency_plugins:
            require(plugin_name)

    def import_vendor_module(self, module_name: str) -> ModuleType:
        module = importlib.import_module(f"{self.vendor_package}.{module_name}")
        self.sync_vendor_aliases()
        return module

    def load_entry_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.entry_modules)

    def activate_runtime(self) -> None:
        global _RUNTIME_ACTIVATED
        if _RUNTIME_ACTIVATED:
            return

        self.require_dependencies()
        self.load_root_plugin()
        self.bind_vendor_alias()
        self.load_entry_modules()
        _RUNTIME_ACTIVATED = True


RESOLVER_OWNER = ResolverOwnerFacade()


def activate_owned_vendor() -> None:
    RESOLVER_OWNER.activate_runtime()


def ensure_resolver_runtime_loaded() -> None:
    validate_resolver_runtime_prerequisites()
    activate_owned_vendor()


class ResolverService(BaseService):
    service_type = Services.Resolver
    service_toggle_name = "链接解析服务"
    default_config = {"enabled": True}
    _NETEASE_CARD_HOST_MARKERS: tuple[str, ...] = (
        "music.163.com",
        "y.music.163.com",
        "163cn.tv",
    )

    @property
    def enabled(self) -> bool:
        try:
            return self._sync_runtime_enabled()
        except Exception:
            return bool(self._config.get("enabled", True))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        enabled = bool(value)
        try:
            self._set_runtime_enabled(enabled)
            return
        except Exception:
            pass

        if self._config.get("enabled") != enabled:
            self._config["enabled"] = enabled
            self._save_config()

    async def _ensure_runtime(self) -> None:
        ensure_resolver_runtime_loaded()

    @staticmethod
    def _append_candidate_text(candidates: list[str], seen: set[str], raw_text) -> None:
        text = str(raw_text or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append(text)

    @classmethod
    def _collect_forward_payload_texts(cls, payload) -> tuple[str, ...]:
        candidates: list[str] = []
        seen: set[str] = set()

        def walk(value) -> None:
            if value is None:
                return
            if isinstance(value, str):
                cls._append_candidate_text(candidates, seen, value)
                return
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if isinstance(value, dict):
                for key in ("content", "message", "data", "text", "title", "url"):
                    if key in value:
                        walk(value.get(key))
                try:
                    dumped = json.dumps(value, ensure_ascii=False)
                except Exception:
                    dumped = ""
                cls._append_candidate_text(candidates, seen, dumped)

        walk(payload.get("messages") if isinstance(payload, dict) else payload)
        return tuple(candidates)

    async def _collect_candidate_texts(self, bot, event: GroupMessageEvent) -> tuple[str, ...]:
        candidates: list[str] = []
        seen: set[str] = set()

        message = event.get_message()
        self._append_candidate_text(candidates, seen, str(message))

        try:
            plain_text = message.extract_plain_text().strip()
        except Exception:
            plain_text = ""
        self._append_candidate_text(candidates, seen, plain_text)

        reply = getattr(event, "reply", None)
        reply_message = getattr(reply, "message", None) if reply else None
        if reply_message is not None:
            self._append_candidate_text(candidates, seen, str(reply_message))
            try:
                self._append_candidate_text(candidates, seen, reply_message.extract_plain_text().strip())
            except Exception:
                pass

        for segment in message:
            segment_type = getattr(segment, "type", "")
            segment_data = getattr(segment, "data", {}) or {}

            if segment_type == "json":
                self._append_candidate_text(candidates, seen, segment_data.get("data"))
            elif segment_type == "share":
                for key in ("url", "title", "content", "image"):
                    self._append_candidate_text(candidates, seen, segment_data.get(key))
            elif segment_type in {"text", "image", "video", "record"}:
                for key in ("text", "url", "file"):
                    self._append_candidate_text(candidates, seen, segment_data.get(key))
            elif segment_type == "forward":
                forward_id = str(segment_data.get("id") or "").strip()
                if not forward_id:
                    continue
                try:
                    payload = await bot.get_forward_msg(id=forward_id)
                except Exception:
                    payload = None
                if payload is None:
                    continue
                for candidate in self._collect_forward_payload_texts(payload):
                    self._append_candidate_text(candidates, seen, candidate)

        return tuple(candidates)

    @staticmethod
    def _matches_supported_candidate(candidate: str) -> bool:
        return any(pattern.search(candidate) for pattern in RESOLVER_CANDIDATE_PATTERNS)

    @classmethod
    def _is_blocked_netease_candidate(cls, candidate: str) -> bool:
        normalized_candidate = str(candidate or "").strip().lower()
        if not normalized_candidate:
            return False
        return any(marker in normalized_candidate for marker in cls._NETEASE_CARD_HOST_MARKERS)

    async def _dispatch_auto_resolve(self, event: GroupMessageEvent) -> bool:
        bot = nonebot.get_bot()
        candidates = tuple(
            candidate
            for candidate in await self._collect_candidate_texts(bot, event)
            if self._matches_supported_candidate(candidate)
            and not self._is_blocked_netease_candidate(candidate)
        )
        if not candidates:
            return False

        await self._ensure_runtime()

        from src.vendors.nonebot_plugin_resolver import bootstrap

        for candidate in candidates:
            try:
                handled = await bootstrap.dispatch_resolver_message(bot, event, message_text=candidate)
            except Exception as exc:
                candidate_preview = candidate if len(candidate) <= 120 else candidate[:117] + "..."
                logger.warning(
                    f"链接解析候选处理失败，已跳过：group={event.group_id} candidate={candidate_preview!r} error={exc}"
                )
                continue
            if handled:
                return True
        return False

    def _get_runtime_enabled(self) -> bool:
        return self.group.group_id not in _load_resolver_shutdown_list()

    def _sync_runtime_enabled(self) -> bool:
        enabled = self._get_runtime_enabled()
        if self._config.get("enabled") != enabled:
            self._config["enabled"] = enabled
            self._save_config()
        return enabled

    def _set_runtime_enabled(self, enabled: bool) -> None:
        group_id = self.group.group_id
        shutdown_list = _load_resolver_shutdown_list()

        if enabled:
            shutdown_list = [item for item in shutdown_list if item != group_id]
        elif group_id not in shutdown_list:
            shutdown_list.append(group_id)

        _save_resolver_shutdown_list(shutdown_list)
        if self._config.get("enabled") != enabled:
            self._config["enabled"] = enabled
            self._save_config()

    @service_action(
        cmd="链接解析服务",
        desc="查看链接解析服务说明与当前状态",
        allow_when_disabled=True,
    )
    async def resolver_service_menu(self):
        from src.support.group import run_flow

        await self._ensure_runtime()
        enabled = self._sync_runtime_enabled()
        status = "已开启" if enabled else "已关闭"
        await run_flow(
            self.group,
            {
                "template": "service_menu",
                "title": "链接解析服务",
                "subtitle": "群里直接发送 B 站链接时，机器人会自动尝试解析。",
                "badges": [
                    {"text": status, "tone": "success" if enabled else "danger"},
                    {"text": "自动解析", "tone": "accent"},
                ],
                "sections": [
                    {
                        "title": "服务说明",
                        "description": "这个服务主要依赖自动触发，不需要复杂菜单操作。",
                        "columns": 1,
                        "items": [
                            {
                                "index": "1",
                                "title": "触发方式",
                                "description": "群内直接分享 B 站链接后自动解析。",
                                "meta": "无需额外命令",
                                "status": "自动",
                                "status_tone": "accent",
                            },
                            {
                                "index": "2",
                                "title": "支持平台",
                                "description": "当前仅支持 B 站。",
                                "meta": "支持 bilibili.com、b23.tv 和 BV 号",
                                "status": "平台",
                                "status_tone": "success",
                            },
                            {
                                "index": "3",
                                "title": "服务开关",
                                "description": f"{self.get_enable_command_name()} / {self.get_disable_command_name()}",
                                "meta": "也兼容 @机器人 开启解析 / 关闭解析 / 查看关闭解析",
                                "status": status,
                                "status_tone": "success" if enabled else "danger",
                            },
                        ],
                    }
                ],
                "hint": "这个页面主要用于查看说明和当前状态，不需要回复序号。",
            },
        )

    @service_message(
        desc="自动链接解析",
        priority=1,
        block=False,
    )
    async def handle_auto_resolve(self, event: GroupMessageEvent):
        if not self.enabled:
            return
        await self._dispatch_auto_resolve(event)

    async def enable_service(self):
        await self._ensure_runtime()
        if self._sync_runtime_enabled():
            await self.group.send_msg(f"🚫 本群{self.get_service_switch_name()}已开启！")
            return

        self._set_runtime_enabled(True)
        await self.group.send_msg(f"✅ 本群{self.get_service_switch_name()}开启成功！")

    async def disable_service(self):
        await self._ensure_runtime()
        if not self._sync_runtime_enabled():
            await self.group.send_msg(f"🚫 本群{self.get_service_switch_name()}已关闭！")
            return

        self._set_runtime_enabled(False)
        await self.group.send_msg(f"✅ 本群{self.get_service_switch_name()}关闭成功！")


_register_resolver_startup_precheck()


__all__ = [
    "RESOLVER_CANDIDATE_PATTERNS",
    "RESOLVER_DEPENDENCY_PLUGINS",
    "RESOLVER_ENTRY_MODULES",
    "RESOLVER_OWNER",
    "RESOLVER_RUNTIME_DEPENDENCIES",
    "RESOLVER_SYSTEM_DEPENDENCIES",
    "RESOLVER_VENDOR_ALIAS",
    "RESOLVER_VENDOR_PACKAGE",
    "ResolverOwnerFacade",
    "ResolverService",
    "activate_owned_vendor",
    "collect_resolver_prerequisite_failures",
    "ensure_resolver_runtime_loaded",
    "validate_resolver_runtime_prerequisites",
]
