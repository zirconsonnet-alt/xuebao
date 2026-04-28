"""
nonebot_bison 的 services owner facade。

`src.vendors.nonebot_bison` 只保留无副作用的包元信息；
真正的依赖声明、vendor alias 绑定与运行时激活统一由本文件以显式 facade 形式代管。
"""

import importlib
import sys
from types import ModuleType
from typing import cast

from nonebot import require
from nonebot.plugin import get_plugin, load_plugin

from src.support.core import Services, ai_tool
from src.support.group import run_flow, wait_for
from .base import BaseService, config_property, service_action


BISON_VENDOR_PACKAGE = "src.vendors.nonebot_bison"
BISON_VENDOR_ALIAS = "nonebot_bison"

BISON_DEPENDENCY_PLUGINS: tuple[str, ...] = (
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_datastore",
    "nonebot_plugin_saa",
)

# 基础支撑模块：为后续注册入口提供 import 路径与运行上下文。
BISON_SUPPORT_MODULES: tuple[str, ...] = (
    "config",
    "types",
    "utils",
    "post",
    "theme",
    "platform",
    "send",
    "scheduler",
)

# 明确承担注册/启动职责的入口模块。
BISON_ENTRY_MODULES: tuple[str, ...] = (
    "bootstrap",
    "admin_page",
    "sub_manager",
)

#
# `config` 与承担注册职责的入口模块依赖插件调用者上下文；
# 其余支撑模块优先走 `nonebot_bison.*`，避免 vendor 路径与别名路径双重导入。
BISON_VENDOR_CONTEXT_MODULES: tuple[str, ...] = (
    "config",
    "bootstrap",
    "admin_page",
    "sub_manager",
)

_RUNTIME_ACTIVATED = False


def _iter_bison_plugin_config_modules(*, ensure_loaded: bool = False) -> list[ModuleType]:
    module_names = (
        "src.vendors.nonebot_bison.plugin_config",
        "nonebot_bison.plugin_config",
    )
    modules: list[ModuleType] = []
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None and ensure_loaded:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                module = None
        if module is None:
            continue
        sys.modules["src.vendors.nonebot_bison.plugin_config"] = module
        sys.modules["nonebot_bison.plugin_config"] = module
        if module not in modules:
            modules.append(module)
    return modules


class BisonOwnerFacade:
    vendor_package = BISON_VENDOR_PACKAGE
    vendor_alias = BISON_VENDOR_ALIAS
    dependency_plugins = BISON_DEPENDENCY_PLUGINS
    support_modules = BISON_SUPPORT_MODULES
    entry_modules = BISON_ENTRY_MODULES
    vendor_context_modules = BISON_VENDOR_CONTEXT_MODULES

    def load_root_plugin(self):
        plugin = get_plugin("nonebot_bison")
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
        aliased_name = f"{self.vendor_alias}.{module_name}"
        vendor_name = f"{self.vendor_package}.{module_name}"

        if aliased_name in sys.modules:
            module = sys.modules[aliased_name]
        elif vendor_name in sys.modules:
            module = sys.modules[vendor_name]
        elif module_name in self.vendor_context_modules:
            module = importlib.import_module(vendor_name)
        else:
            module = importlib.import_module(aliased_name)

        self.sync_vendor_aliases()
        return module

    def load_support_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.support_modules)

    def load_entry_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.entry_modules)

    def activate_runtime(self) -> None:
        global _RUNTIME_ACTIVATED
        if _RUNTIME_ACTIVATED:
            return

        self.require_dependencies()

        import nonebot_plugin_saa

        self.load_root_plugin()
        self.bind_vendor_alias()
        _iter_bison_plugin_config_modules(ensure_loaded=True)
        self.load_support_modules()
        self.load_entry_modules()

        nonebot_plugin_saa.enable_auto_select_bot()
        _RUNTIME_ACTIVATED = True


BISON_OWNER = BisonOwnerFacade()


def activate_owned_vendor() -> None:
    BISON_OWNER.activate_runtime()


def ensure_bison_runtime_loaded() -> None:
    activate_owned_vendor()


class BisonService(BaseService):
    service_type = Services.Bison
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    async def _ensure_runtime(self) -> None:
        ensure_bison_runtime_loaded()

    async def _ensure_scheduler_ready(self, platform: str) -> None:
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.scheduler import init_scheduler, scheduler_dict

        if platform not in platform_manager:
            raise ValueError(f"不支持的平台：{platform}")

        site = platform_manager[platform].site
        if site in scheduler_dict:
            return

        await init_scheduler()
        if site not in scheduler_dict:
            raise RuntimeError(f"订阅平台初始化失败：{platform}")

    async def _get_cookie_client_manager(self, platform: str):
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.scheduler import scheduler_dict
        from src.vendors.nonebot_bison.utils.site import CookieClientManager, is_cookie_client_manager

        if platform not in platform_manager:
            raise ValueError(f"不支持的平台：{platform}")
        if not is_cookie_client_manager(platform_manager[platform].site.client_mgr):
            raise ValueError(f"平台 {platform} 暂不支持 Cookie")

        await self._ensure_scheduler_ready(platform)
        site = platform_manager[platform].site
        scheduler = scheduler_dict.get(site)
        if scheduler is None:
            raise RuntimeError(f"平台 {platform} 的调度器未初始化")
        return cast(CookieClientManager, scheduler.client_mgr)

    async def _prompt_bison_cookie_platform(self) -> str | None:
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.utils.site import is_cookie_client_manager

        supported_platforms = [
            f"{platform_name}: {platform_manager[platform_name].name}"
            for platform_name in platform_manager
            if is_cookie_client_manager(platform_manager[platform_name].site.client_mgr)
        ]
        if not supported_platforms:
            await self.group.send_msg("当前没有支持 Cookie 的 Bison 平台")
            return None

        await self.group.send_msg(
            "请输入想要设置 Cookie 的平台：\n"
            + "\n".join(supported_platforms)
            + "\n发送“取消”可退出"
        )
        response = await wait_for(60)
        if not response or response == "取消":
            await self.group.send_msg("已取消设置 Bison Cookie")
            return None
        return response.strip()

    async def _prompt_bison_cookie_content(self) -> str | None:
        await self.group.send_msg("请发送完整 Cookie 内容\n发送“取消”可退出")
        response = await wait_for(180)
        if not response or response == "取消":
            await self.group.send_msg("已取消设置 Bison Cookie")
            return None
        cookie_text = response.strip()
        if not cookie_text:
            await self.group.send_msg("Cookie 内容不能为空")
            return None
        return cookie_text

    @ai_tool(
        name="bison_subscribe",
        desc="订阅指定平台的 UP 主最新内容",
        parameters={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台名称，例如 bilibili"},
                "target": {"type": "string", "description": "目标用户 ID/UID"},
                "cats": {"type": "array", "items": {"type": "string"}, "description": "订阅分类，可选"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "订阅标签，可选"},
            },
            "required": ["platform", "target"],
        },
        category="bison",
        triggers=["订阅UP", "订阅"],
    )
    async def subscribe_up(
        self,
        user_id: int,
        group_id: int,
        platform: str,
        target: str,
        cats: list[str] | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ) -> dict:
        if not self.enabled:
            return {"success": False, "message": "Bison 订阅服务未开启"}

        await self._ensure_runtime()
        try:
            from nonebot_plugin_saa import TargetQQGroup
            from src.vendors.nonebot_bison.apis import check_sub_target
            from src.vendors.nonebot_bison.config import config as bison_config
            from src.vendors.nonebot_bison.config.db_config import SubscribeDupException
            from src.vendors.nonebot_bison.types import Target as BisonTarget

            await self._ensure_scheduler_ready(platform)
            target_name = await check_sub_target(platform, target)
            if not target_name:
                return {"success": False, "message": "无法解析目标，请检查平台和 UID 是否正确"}

            user_target = TargetQQGroup(group_id=group_id)
            await bison_config.add_subscribe(
                user=user_target,
                target=BisonTarget(target),
                target_name=target_name,
                platform_name=platform,
                cats=cats or [],
                tags=tags or [],
            )
            return {"success": True, "message": f"已订阅 {target_name} ({platform} {target})"}
        except SubscribeDupException:
            return {"success": False, "message": "已存在该订阅"}
        except Exception as exc:
            return {"success": False, "message": f"订阅失败: {exc}"}

    @service_action(
        cmd="添加BisonCookie",
        desc="为支持的平台录入 Bison Cookie",
        require_admin=True,
        allow_when_disabled=True,
    )
    async def set_bison_cookie(self):
        await self._ensure_runtime()

        platform = await self._prompt_bison_cookie_platform()
        if not platform:
            return

        try:
            client_mgr = await self._get_cookie_client_manager(platform)
        except Exception as exc:
            await self.group.send_msg(str(exc))
            return

        cookie_text = await self._prompt_bison_cookie_content()
        if not cookie_text:
            return

        if not await client_mgr.validate_cookie(cookie_text):
            await self.group.send_msg(
                "Cookie 校验失败，请检查格式或内容是否有效。\n"
                "详情可参考 https://nonebot-bison.netlify.app/usage/cookie.html"
            )
            return

        try:
            cookie_name = await client_mgr.get_cookie_name(cookie_text)
            new_cookie = await client_mgr.add_identified_cookie(cookie_text, cookie_name)
        except Exception as exc:
            await self.group.send_msg(f"设置 Bison Cookie 失败：{exc}")
            return

        await self.group.send_msg(
            f"已添加 Bison Cookie：{new_cookie.cookie_name}\n"
            f"平台：{platform}"
        )

    @service_action(cmd="Bison订阅服务")
    async def bison_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ Bison订阅服务未开启！")
            return
        flow = {
            "title": "欢迎使用Bison订阅服务",
            "text": "订阅功能请通过 AI 工具调用；Cookie 可使用“设置BisonCookie”命令录入。",
        }
        await run_flow(self.group, flow)


__all__ = [
    "BISON_DEPENDENCY_PLUGINS",
    "BISON_ENTRY_MODULES",
    "BISON_OWNER",
    "BISON_SUPPORT_MODULES",
    "BISON_VENDOR_CONTEXT_MODULES",
    "BISON_VENDOR_ALIAS",
    "BISON_VENDOR_PACKAGE",
    "BisonOwnerFacade",
    "activate_owned_vendor",
    "ensure_bison_runtime_loaded",
    "BisonService",
]
