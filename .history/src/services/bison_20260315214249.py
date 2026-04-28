"""
nonebot_bison 的 services owner facade。

`src.vendors.nonebot_bison` 只保留无副作用的包元信息；
真正的依赖声明、vendor alias 绑定与运行时激活统一由本文件以显式 facade 形式代管。
"""

import importlib
import sys
from types import ModuleType

from nonebot import require
from nonebot.plugin import get_plugin, load_plugin

from src.support.core import Services, ai_tool
from .base import BaseService, config_property


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
        self.load_support_modules()
        self.load_entry_modules()

        nonebot_plugin_saa.enable_auto_select_bot()
        _RUNTIME_ACTIVATED = True


BISON_OWNER = BisonOwnerFacade()


def activate_owned_vendor() -> None:
    BISON_OWNER.activate_runtime()


def ensure_bison_runtime_loaded() -> None:
    activate_owned_vendor()


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
]
