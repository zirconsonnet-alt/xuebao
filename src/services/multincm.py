"""
nonebot_plugin_multincm 的 services owner facade。

`src.vendors.nonebot_plugin_multincm` 根包只保留无副作用元信息；
真正的依赖声明、命令加载、缓存清理与登录启动任务统一由本文件显式代管。
"""

import asyncio
import importlib
import os
import json
import re
import shutil
import sys
from typing import Any
from types import ModuleType

import nonebot
from nonebot import get_driver, require
from nonebot.plugin import get_plugin, load_plugin

from src.support.core import Services, ai_tool
from .base import BaseService, config_property, service_action


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

    async def _send_song_card_message(self, info: Any) -> None:
        from nonebot.adapters.onebot.v11 import Message, MessageSegment

        await self.group.send_msg(
            Message(
                MessageSegment(
                    "music",
                    {
                        "type": "custom",
                        "url": info.url,
                        "audio": info.playable_url,
                        "title": info.display_name,
                        "image": info.cover_url,
                        "singer": info.display_artists,
                    },
                )
            )
        )

    async def _send_song_text_fallback(self, info: Any) -> None:
        await self.group.send_msg(
            "\n".join(
                [
                    f"已为你找到歌曲：{info.display_name}",
                    f"歌手：{info.display_artists}",
                    f"页面：{info.url}",
                    f"直链：{info.playable_url}",
                ]
            )
        )

    async def _get_song_and_info(self, song_id: int) -> tuple[Any, Any]:
        from src.vendors.nonebot_plugin_multincm.data_source.song import Song

        song = await Song.from_id(song_id)
        info = await song.get_info()
        return song, info

    async def _resolve_song_from_text(self, text: str) -> Any | None:
        if not text:
            return None

        from src.vendors.nonebot_plugin_multincm.data_source import registered_song
        from src.vendors.nonebot_plugin_multincm.interaction.resolver import resolve_from_plaintext

        resolved = await resolve_from_plaintext(
            text,
            expected_type=tuple(registered_song),
            use_cool_down=False,
        )
        return resolved

    @staticmethod
    def _extract_song_id_from_text(text: str) -> int | None:
        if not text:
            return None

        patterns = (
            r"music\.163\.com/(?:#/)?song\?id=(\d+)",
            r"music\.163\.com/(?:#/)?program(?:/|\?id=)(\d+)",
            r"\bid=(\d+)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _extract_song_id_from_reply_message(self, event: Any) -> int | None:
        reply = getattr(event, "reply", None)
        if not reply or not getattr(reply, "message", None):
            return None

        reply_message = reply.message
        try:
            for segment in reply_message:
                segment_type = getattr(segment, "type", "")
                segment_data = getattr(segment, "data", {}) or {}

                if segment_type == "music":
                    direct_id = segment_data.get("id")
                    if direct_id and str(direct_id).isdigit():
                        return int(direct_id)

                    for key in ("url", "audio"):
                        song_id = self._extract_song_id_from_text(str(segment_data.get(key, "")))
                        if song_id:
                            return song_id

                if segment_type == "json":
                    raw_json = str(segment_data.get("data", "") or "")
                    if raw_json:
                        song_id = self._extract_song_id_from_text(raw_json)
                        if song_id:
                            return song_id
                        try:
                            parsed = json.loads(raw_json)
                        except Exception:
                            parsed = None
                        if isinstance(parsed, dict):
                            raw_dump = json.dumps(parsed, ensure_ascii=False)
                            song_id = self._extract_song_id_from_text(raw_dump)
                            if song_id:
                                return song_id
        except Exception:
            pass

        reply_text = ""
        try:
            reply_text = reply_message.extract_plain_text().strip()
        except Exception:
            reply_text = str(reply_message)
        return self._extract_song_id_from_text(reply_text)

    async def _resolve_song_and_info_from_command(
        self,
        arg_text: str,
        event: Any = None,
    ) -> tuple[Any, Any] | tuple[None, None]:
        reply = getattr(event, "reply", None)
        if reply and getattr(reply, "message", None):
            reply_message = reply.message
            try:
                for segment in reply_message:
                    segment_data = getattr(segment, "data", {}) or {}
                    candidates = []
                    if getattr(segment, "type", "") == "music":
                        candidates.extend(
                            str(segment_data.get(key, "") or "")
                            for key in ("url", "audio", "id")
                        )
                    elif getattr(segment, "type", "") == "json":
                        candidates.append(str(segment_data.get("data", "") or ""))

                    for candidate in candidates:
                        song = await self._resolve_song_from_text(candidate)
                        if song:
                            return song, await song.get_info()
            except Exception:
                pass

            try:
                reply_text = reply_message.extract_plain_text().strip()
            except Exception:
                reply_text = str(reply_message)
            song = await self._resolve_song_from_text(reply_text)
            if song:
                return song, await song.get_info()

        song = await self._resolve_song_from_text(arg_text)
        if song:
            return song, await song.get_info()

        song_id = self._resolve_song_id_from_command(arg_text, event)
        if not song_id:
            return None, None
        return await self._get_song_and_info(song_id)

    def _resolve_song_id_from_command(self, arg_text: str, event: Any = None) -> int | None:
        reply_song_id = self._extract_song_id_from_reply_message(event)
        if reply_song_id:
            return reply_song_id

        text_song_id = self._extract_song_id_from_text(arg_text)
        if text_song_id:
            return text_song_id

        match = re.search(r"\d+", arg_text or "")
        if match:
            return int(match.group())
        return None

    async def _resolve_song_id_from_keyword(self, keyword: str) -> int | None:
        if not keyword:
            return None

        from src.vendors.nonebot_plugin_multincm.data_source.song import Song as SongModel
        from src.vendors.nonebot_plugin_multincm.data_source.song import SongSearcher

        searcher = SongSearcher(keyword)
        page = await searcher.get_page(1)
        if not page:
            return None
        if isinstance(page, SongModel):
            return int(page.id)

        content = getattr(page, "content", None)
        if content is None:
            return None
        if not isinstance(content, list):
            content = list(content)
        for raw_song in content:
            song_id = getattr(raw_song, "id", None)
            if song_id is None:
                continue
            try:
                return int(song_id)
            except (TypeError, ValueError):
                continue
        return None

    async def prepare_schedule_tool_args(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        args = dict(tool_args or {})
        context = dict(context or {})

        if tool_name not in {"multincm_get_song_url", "multincm_upload_song"}:
            return args, ""

        if not self.enabled:
            return None, "点歌服务未开启"

        raw_song_id = args.get("song_id")
        if raw_song_id not in (None, ""):
            try:
                args["song_id"] = int(raw_song_id)
                return args, ""
            except (TypeError, ValueError):
                return None, f"歌曲 ID 无效：{raw_song_id}"

        await self._ensure_runtime()

        candidate_texts: list[str] = []
        for key in ("keyword", "song_keyword", "song_name", "song_query", "query", "url", "link", "message", "arg_text"):
            value = str(args.get(key) or "").strip()
            if value:
                candidate_texts.append(value)

        for key in ("reply_text", "message"):
            value = str(context.get(key) or "").strip()
            if value:
                candidate_texts.append(value)

        normalized_candidates: list[str] = []
        seen_candidates = set()
        for text in candidate_texts:
            if text in seen_candidates:
                continue
            normalized_candidates.append(text)
            seen_candidates.add(text)

        for candidate in normalized_candidates:
            direct_song_id = self._extract_song_id_from_text(candidate)
            if direct_song_id:
                return {"song_id": int(direct_song_id)}, ""

        for candidate in normalized_candidates:
            resolved_song_id = await self._resolve_song_id_from_keyword(candidate)
            if resolved_song_id:
                return {"song_id": int(resolved_song_id)}, ""

        return None, "定时点歌需要 song_id，或在创建时提供可解析的关键词/网易云链接"

    async def _resolve_upload_source_path(self, info: Any) -> str:
        from src.vendors.nonebot_plugin_multincm.config import config as multincm_config
        from src.vendors.nonebot_plugin_multincm.interaction.message.song_file import download_song

        if multincm_config.ob_v11_local_mode:
            file_path = await download_song(info)
            return str(file_path.resolve())

        bot = self.group.gateway._bot() if hasattr(self.group.gateway, "_bot") else nonebot.get_bot()
        download_result = await bot.download_file(url=info.playable_url)
        remote_file = download_result.get("file") if isinstance(download_result, dict) else None
        if remote_file:
            return str(remote_file)

        file_path = await download_song(info)
        return str(file_path.resolve())

    async def _upload_song_to_group_file(self, info: Any) -> str:
        file_path = await self._resolve_upload_source_path(info)
        bot = self.group.gateway._bot() if hasattr(self.group.gateway, "_bot") else nonebot.get_bot()
        await bot.upload_group_file(
            group_id=self.group.group_id,
            file=file_path,
            name=info.display_filename,
        )
        return file_path

    @service_action(
        cmd="下载歌曲",
        aliases={"上传歌曲"},
        desc="回复音乐卡片或提供歌曲 ID，下载并上传到群文件",
        need_arg=True,
        record_ai_context=True,
        ai_context_label="下载并上传歌曲到群文件",
        ai_context_include_arg=True,
    )
    async def download_song_command(self, arg, event=None, **kwargs):
        if not self.enabled:
            await self.group.send_msg("点歌服务未开启")
            return

        arg_text = arg.extract_plain_text().strip()

        await self._ensure_runtime()
        try:
            song, info = await self._resolve_song_and_info_from_command(arg_text, event)
            if song is None or info is None:
                await self.group.send_msg(
                    "请回复一条音乐卡片后发送“下载歌曲”，或直接使用“下载歌曲 1901371647”"
                )
                return
            await self._upload_song_to_group_file(info)
            await self.group.send_msg(f"已上传到群文件：{info.display_filename}")
        except (IndexError, ValueError):
            await self.group.send_msg("未找到对应歌曲")
        except Exception as exc:
            await self.group.send_msg(f"上传歌曲失败：{exc}")

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
    async def search_song(
        self,
        user_id: int,
        group_id: int,
        keyword: str,
        limit: int = 5,
        **kwargs,
    ) -> dict:
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
                if not isinstance(page.content, list):
                    page.content = list(page.content)
                cards = await page.transform_to_list_cards()
                for raw_song, card in zip(page.content[:limit], cards[:limit]):
                    results.append(
                        {
                            "id": raw_song.id,
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
        desc="发送音乐卡片并返回歌曲直链（用于播放或查看链接，不上传群文件）",
        parameters={
            "type": "object",
            "properties": {
                "song_id": {"type": "integer", "description": "歌曲 ID"},
            },
            "required": ["song_id"],
        },
        category="multincm",
        triggers=["获取歌曲链接", "发送音乐卡片", "播放歌曲"],
    )
    async def get_song_url(
        self,
        user_id: int,
        group_id: int,
        song_id: int,
        **kwargs,
    ) -> dict:
        if not self.enabled:
            return {"success": False, "message": "点歌服务未开启"}

        await self._ensure_runtime()
        try:
            song, info = await self._get_song_and_info(song_id)
            card_sent = True
            try:
                await self._send_song_card_message(info)
            except Exception:
                card_sent = False
                await self._send_song_text_fallback(info)

            return {
                "success": True,
                "message": "已发送音乐卡片" if card_sent else "音乐卡片发送失败，已改为发送文本链接",
                "data": {
                    "id": song.id,
                    "name": info.display_name,
                    "artists": info.display_artists,
                    "duration": info.display_duration,
                    "url": info.playable_url,
                    "page_url": info.url,
                    "cover_url": info.cover_url,
                    "card_sent": card_sent,
                },
            }
        except (IndexError, ValueError):
            return {"success": False, "message": f"未找到歌曲 ID：{song_id}"}
        except Exception as exc:
            return {"success": False, "message": f"获取歌曲链接失败: {exc}"}

    @ai_tool(
        name="multincm_upload_song",
        desc="下载歌曲并上传到群文件。当用户要求下载歌曲、上传歌曲文件、发送到群文件时使用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "song_id": {"type": "integer", "description": "歌曲 ID"},
            },
            "required": ["song_id"],
        },
        category="multincm",
        triggers=["下载歌曲", "上传歌曲", "发送到群文件", "群文件音乐"],
    )
    async def upload_song(
        self,
        user_id: int,
        group_id: int,
        song_id: int,
        **kwargs,
    ) -> dict:
        if not self.enabled:
            return {"success": False, "message": "点歌服务未开启"}

        await self._ensure_runtime()
        try:
            _, info = await self._get_song_and_info(song_id)
            file_path = await self._upload_song_to_group_file(info)
            return {
                "success": True,
                "message": "歌曲已上传到群文件",
                "data": {
                    "id": song_id,
                    "name": info.display_name,
                    "artists": info.display_artists,
                    "duration": info.display_duration,
                    "file_name": info.display_filename,
                    "source_path": file_path,
                    "page_url": info.url,
                    "url": info.playable_url,
                },
            }
        except (IndexError, ValueError):
            return {"success": False, "message": f"未找到歌曲 ID：{song_id}"}
        except Exception as exc:
            return {"success": False, "message": f"上传歌曲失败: {exc}"}


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
