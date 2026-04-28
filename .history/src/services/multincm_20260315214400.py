"""
nonebot_plugin_multincm 的 services owner facade。

`src.vendors.nonebot_plugin_multincm` 根包只保留无副作用元信息；
真正的依赖声明、命令加载、缓存清理与登录启动任务统一由本文件显式代管。
"""

import asyncio
import importlib
import os
import shutil
import sys
from types import ModuleType

from nonebot import get_driver, require
from nonebot.plugin import get_plugin, load_plugin

from src.support.core import Services, ai_tool
from .base import BaseService, config_property


MULTINCM_VENDOR_PACKAGE = "src.vendors.nonebot_plugin_multincm"
MULTINCM_VENDOR_ALIAS = "nonebot_plugin_multincm"

MULTINCM_DEPENDENCY_PLUGINS: tuple[str, ...] = (
    "nonebot_plugin_alconna",
    "nonebot_plugin_waiter",
    "nonebot_plugin_localstore",
    "nonebot_plugin_htmlrender",
)

MULTINCM_SUPPORT_MODULES: tuple[str, ...] = (
    "config",
    "const",
    "data_source",
    "interaction",
)

_RUNTIME_ACTIVATED = False
_STARTUP_HOOK_REGISTERED = False


class MultiNCMOwnerFacade:
    vendor_package = MULTINCM_VENDOR_PACKAGE
    vendor_alias = MULTINCM_VENDOR_ALIAS
    dependency_plugins = MULTINCM_DEPENDENCY_PLUGINS
    support_modules = MULTINCM_SUPPORT_MODULES

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
            alias_name = alias_prefix + module_name[len(prefix) :]
            sys.modules.setdefault(alias_name, module)

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

    def configure_localstore(self) -> None:
        os.environ.setdefault("LOCALSTORE_USE_CWD", "True")

    def import_vendor_module(self, module_name: str) -> ModuleType:
        module = importlib.import_module(f"{self.vendor_package}.{module_name}")
        self.sync_vendor_aliases()
        return module

    def load_support_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.support_modules)

    def clean_song_cache(self) -> None:
        config_module = sys.modules.get(f"{self.vendor_package}.config")
        const_module = sys.modules.get(f"{self.vendor_package}.const")
        if config_module is None or const_module is None:
            return

        config = getattr(config_module, "config", None)
        song_cache_dir = getattr(const_module, "SONG_CACHE_DIR", None)
        if not config or song_cache_dir is None:
            return

        if getattr(config, "clean_cache_on_startup", False) and song_cache_dir.exists():
            shutil.rmtree(song_cache_dir)

    def register_login_startup_hook(self) -> None:
        global _STARTUP_HOOK_REGISTERED
        if _STARTUP_HOOK_REGISTERED:
            return

        data_source_module = sys.modules.get(f"{self.vendor_package}.data_source")
        login = getattr(data_source_module, "login", None) if data_source_module else None
        if login is None:
            return

        driver = get_driver()

        @driver.on_startup
        async def _multincm_login_startup() -> None:
            asyncio.create_task(login())

        _STARTUP_HOOK_REGISTERED = True

    def load_command_entries(self) -> None:
        interaction_module = sys.modules.get(f"{self.vendor_package}.interaction")
        load_commands = getattr(interaction_module, "load_commands", None) if interaction_module else None
        if callable(load_commands):
            load_commands()

    def activate_runtime(self) -> None:
        global _RUNTIME_ACTIVATED
        if _RUNTIME_ACTIVATED:
            return

        self.configure_localstore()
        self.require_dependencies()
        self.load_root_plugin()
        self.bind_vendor_alias()
        self.load_support_modules()
        self.clean_song_cache()
        self.register_login_startup_hook()
        self.load_command_entries()
        _RUNTIME_ACTIVATED = True


MULTINCM_OWNER = MultiNCMOwnerFacade()


def activate_owned_vendor() -> None:
    MULTINCM_OWNER.activate_runtime()


def ensure_multincm_runtime_loaded() -> None:
    activate_owned_vendor()


class MultiNCMService(BaseService):
    service_type = Services.Multincm
    default_config = {"enabled": True}
    enabled = config_property("enabled")

    async def _ensure_runtime(self) -> None:
        # 确保 vendor 运行时已加载
        ensure_multincm_runtime_loaded()

    @ai_tool(
        name="multincm_search_song",
        desc="搜索点歌，返回歌曲列表（包含标题/歌手/时长/封面）",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回结果数量", "default": 5},
            },
            "required": ["keyword"],
        },
        category="multincm",
        triggers=["点歌", "搜索歌曲"],
    )
    async def search_song(self, user_id: int, group_id: int, keyword: str, limit: int = 5) -> dict:
        if not self.enabled:
            return {"success": False, "message": "点歌服务未开启"}

        await self._ensure_runtime()
        try:
            from src.vendors.nonebot_plugin_multincm.data_source.song import SongSearcher

            searcher = SongSearcher(keyword)
            page = await searcher.get_page(1)
            if not page:
                return {"success": True, "message": "未找到任何结果", "data": {"results": []}}

            # 如果返回单个歌曲
            from src.vendors.nonebot_plugin_multincm.data_source.song import Song as SongModel

            results = []
            if isinstance(page, SongModel):
                info = await page.get_info()
                results.append(
                    {
                        "id": page.id,
                        "name": info.display_name,
                        "artists": info.display_artists,
                        "duration": info.display_duration,
                        "url": info.playable_url,
                        "cover_url": info.cover_url,
                    }
                )
            else:
                cards = await page.transform_to_list_cards()
                for card in cards[:limit]:
                    results.append(
                        {
                            "title": card.title,
                            "alias": card.alias,
                            "extras": card.extras,
                            "small_extras": card.small_extras,
                        }
                    )

            return {"success": True, "data": {"results": results}}
        except Exception as exc:
            return {"success": False, "message": f"点歌失败: {exc}"}

    @ai_tool(
        name="multincm_get_song_url",
        desc="获取点歌链接（可用于下载或播放）",
        parameters={
            "type": "object",
            "properties": {
                "song_id": {"type": "integer", "description": "歌曲 ID"},
            },
            "required": ["song_id"],
        },
        category="multincm",
        triggers=["获取歌曲链接", "下载歌曲"],
    )
    async def get_song_url(self, user_id: int, group_id: int, song_id: int) -> dict:
        if not self.enabled:
            return {"success": False, "message": "点歌服务未开启"}

        await self._ensure_runtime()
        try:
            from src.vendors.nonebot_plugin_multincm.data_source.song import Song

            song = await Song.from_id(song_id)
            info = await song.get_info()
            return {
                "success": True,
                "data": {
                    "id": song.id,
                    "name": info.display_name,
                    "artists": info.display_artists,
                    "duration": info.display_duration,
                    "url": info.playable_url,
                    "cover_url": info.cover_url,
                },
            }
        except Exception as exc:
            return {"success": False, "message": f"获取歌曲链接失败: {exc}"}


__all__ = [
    "MULTINCM_DEPENDENCY_PLUGINS",
    "MULTINCM_OWNER",
    "MULTINCM_SUPPORT_MODULES",
    "MULTINCM_VENDOR_ALIAS",
    "MULTINCM_VENDOR_PACKAGE",
    "MultiNCMOwnerFacade",
    "activate_owned_vendor",
    "ensure_multincm_runtime_loaded",
    "MultiNCMService",
]
