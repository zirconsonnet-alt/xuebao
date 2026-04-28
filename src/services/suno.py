"""Suno 音乐生成服务。"""

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.support.core import Services, ai_tool

from .base import BaseService, check_enabled, config_property, service_action


_DEFAULT_SUNO_API_BASE_URL = os.getenv("SUNO_API_BASE_URL", "http://127.0.0.1:3000").strip()
_READY_AUDIO_STATUSES = {"complete"}
_FAILED_AUDIO_STATUSES = {"error", "failed"}
_SUNO_UPLOAD_FOLDER = "Suno音乐"
_SUNO_AUDIO_ARTIST = "雪豹"
_SAFE_FILE_NAME_RE = re.compile(r'[\\/:*?"<>|]+')
_SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class SunoService(BaseService):
    service_type = Services.Suno
    service_toggle_name = "Suno音乐服务"
    default_config = {
        "enabled": False,
        "base_url": _DEFAULT_SUNO_API_BASE_URL or "http://127.0.0.1:3000",
        "request_timeout_seconds": 30,
        "poll_interval_seconds": 5,
        "max_wait_seconds": 180,
    }
    settings_schema = [
        {
            "key": "base_url",
            "title": "API地址",
            "description": "suno-api 服务地址，例如 http://127.0.0.1:3000。",
            "type": "text",
            "group": "连接设置",
            "placeholder": "http://127.0.0.1:3000",
        },
        {
            "key": "request_timeout_seconds",
            "title": "请求超时",
            "description": "单次 HTTP 请求超时时间（秒）。",
            "type": "int",
            "group": "连接设置",
            "min_value": 5,
            "max_value": 300,
        },
        {
            "key": "poll_interval_seconds",
            "title": "轮询间隔",
            "description": "查询生成状态的轮询间隔（秒）。",
            "type": "int",
            "group": "连接设置",
            "min_value": 1,
            "max_value": 60,
        },
        {
            "key": "max_wait_seconds",
            "title": "最长等待",
            "description": "等待音频生成完成的最长时间（秒）。",
            "type": "int",
            "group": "连接设置",
            "min_value": 10,
            "max_value": 600,
        },
    ]

    enabled = config_property("enabled")
    base_url = config_property("base_url")
    request_timeout_seconds = config_property("request_timeout_seconds")
    poll_interval_seconds = config_property("poll_interval_seconds")
    max_wait_seconds = config_property("max_wait_seconds")

    @staticmethod
    def _coerce_int(value: Any, default: int, *, minimum: int = 1) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        return max(minimum, result)

    def _get_base_url(self) -> str:
        return str(self.base_url or _DEFAULT_SUNO_API_BASE_URL or "http://127.0.0.1:3000").strip().rstrip("/")

    def _get_timeout(self) -> aiohttp.ClientTimeout:
        timeout_seconds = self._coerce_int(
            self.get_config_value("request_timeout_seconds", self.default_config["request_timeout_seconds"]),
            int(self.default_config["request_timeout_seconds"]),
            minimum=5,
        )
        return aiohttp.ClientTimeout(total=timeout_seconds)

    def _get_poll_interval_seconds(self) -> int:
        return self._coerce_int(
            self.get_config_value("poll_interval_seconds", self.default_config["poll_interval_seconds"]),
            int(self.default_config["poll_interval_seconds"]),
            minimum=1,
        )

    def _get_max_wait_seconds(self) -> int:
        return self._coerce_int(
            self.get_config_value("max_wait_seconds", self.default_config["max_wait_seconds"]),
            int(self.default_config["max_wait_seconds"]),
            minimum=10,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._get_base_url()}{path}"
        headers = {"Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=self._get_timeout()) as session:
                async with session.request(
                    method.upper(),
                    url,
                    json=payload,
                    params=params,
                    headers=headers,
                ) as response:
                    raw_text = await response.text()
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Suno API 请求超时：{url}") from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Suno API 连接失败：{exc}") from exc

        try:
            data = json.loads(raw_text) if raw_text else None
        except json.JSONDecodeError:
            data = raw_text

        if response.status >= 400:
            detail = self._extract_error_text(data) or str(raw_text or "").strip() or "未知错误"
            raise RuntimeError(f"Suno API 请求失败（HTTP {response.status}）：{detail}")

        return data

    @staticmethod
    def _extract_error_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                text = str(payload.get(key) or "").strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _extract_audio_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("clips", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if isinstance(payload.get("clip"), dict):
                return [payload["clip"]]
            if payload.get("id") and (
                payload.get("status") or payload.get("audio_url") or payload.get("video_url")
            ):
                return [payload]
        return []

    @staticmethod
    def _extract_lyrics_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            for key in ("lyrics", "text", "content"):
                text = str(payload.get(key) or "").strip()
                if text:
                    return text
            data = payload.get("data")
            if isinstance(data, str):
                return data.strip()
            if isinstance(data, dict):
                for key in ("lyrics", "text", "content"):
                    text = str(data.get(key) or "").strip()
                    if text:
                        return text
        return ""

    @staticmethod
    def _clip_status(item: dict[str, Any]) -> str:
        return str(item.get("status") or "unknown").strip().lower()

    @staticmethod
    def _clip_audio_url(item: dict[str, Any]) -> str:
        return str(item.get("audio_url") or "").strip()

    @classmethod
    def _is_ready_audio_item(cls, item: dict[str, Any]) -> bool:
        return cls._clip_status(item) in _READY_AUDIO_STATUSES and bool(cls._clip_audio_url(item))

    @staticmethod
    def _clip_page_url(item: dict[str, Any]) -> str:
        return str(item.get("video_url") or item.get("audio_url") or "").strip()

    @staticmethod
    def _clip_title(item: dict[str, Any]) -> str:
        for key in ("title", "prompt", "gpt_description_prompt"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        clip_id = str(item.get("id") or "").strip()
        if clip_id:
            return f"Suno片段 {clip_id[:8]}"
        return "Suno音乐"

    @staticmethod
    def _default_custom_title(prompt: str) -> str:
        normalized = " ".join(str(prompt or "").strip().split())
        if not normalized:
            return "Suno音乐"
        return normalized[:24]

    @classmethod
    def _has_ready_audio(cls, items: list[dict[str, Any]]) -> bool:
        for item in items:
            if cls._is_ready_audio_item(item):
                return True
        return False

    @classmethod
    def _all_failed(cls, items: list[dict[str, Any]]) -> bool:
        return bool(items) and all(cls._clip_status(item) in _FAILED_AUDIO_STATUSES for item in items)

    @classmethod
    def _all_finished(cls, items: list[dict[str, Any]]) -> bool:
        return bool(items) and all(
            cls._clip_status(item) in (_READY_AUDIO_STATUSES | _FAILED_AUDIO_STATUSES)
            for item in items
        )

    async def _get_audio_information(self, clip_ids: list[str]) -> list[dict[str, Any]]:
        if not clip_ids:
            return []
        payload = await self._request_json(
            "GET",
            "/api/get",
            params={"ids": ",".join(clip_ids)},
        )
        return self._extract_audio_items(payload)

    async def _poll_audio_information(self, clip_ids: list[str]) -> list[dict[str, Any]]:
        if not clip_ids:
            return []

        poll_interval = self._get_poll_interval_seconds()
        deadline = time.monotonic() + self._get_max_wait_seconds()
        last_items: list[dict[str, Any]] = []

        while True:
            items = await self._get_audio_information(clip_ids)
            if items:
                last_items = items
            if items and (self._has_ready_audio(items) or self._all_finished(items)):
                return items
            if time.monotonic() >= deadline:
                return last_items
            await asyncio.sleep(poll_interval)

    @classmethod
    def _pick_primary_item(cls, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in items:
            if cls._is_ready_audio_item(item):
                return item
        return items[0] if items else None

    @classmethod
    def _build_generation_lines(cls, items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["Suno 没有返回任何音乐片段。"]

        lines = []
        primary = cls._pick_primary_item(items)
        if primary is not None:
            primary_title = cls._clip_title(primary)
            primary_status = cls._clip_status(primary)
            if cls._is_ready_audio_item(primary):
                lines.append(f"已生成 Suno 音乐：{primary_title}")
                lines.append(f"状态：{primary_status}")
                audio_url = cls._clip_audio_url(primary)
                if audio_url:
                    lines.append(f"直链：{audio_url}")
            else:
                lines.append(f"Suno 音乐仍在生成中：{primary_title}")
                lines.append(f"状态：{primary_status}")
                clip_id = str(primary.get('id') or '').strip()
                if clip_id:
                    lines.append(f"片段 ID：{clip_id}")
                lines.append("说明：当前还不是最终成品，待完整音频生成完成后再上传群文件。")

        if len(items) > 1:
            lines.append(f"共返回 {len(items)} 个候选片段：")
            for index, item in enumerate(items[:4], start=1):
                summary = f"{index}. {cls._clip_title(item)} [{cls._clip_status(item)}]"
                url = cls._clip_audio_url(item)
                if url and cls._is_ready_audio_item(item):
                    summary = f"{summary} {url}"
                lines.append(summary)

        return lines

    @staticmethod
    def _sanitize_file_stem(name: str) -> str:
        stem = Path(str(name or "suno_music")).stem.strip() or "suno_music"
        stem = _SAFE_FILE_NAME_RE.sub("_", stem)
        stem = re.sub(r"\s+", "_", stem)
        stem = stem.strip("._")
        return stem[:80] or "suno_music"

    @classmethod
    def _guess_audio_suffix(cls, item: dict[str, Any]) -> str:
        audio_url = cls._clip_audio_url(item)
        suffix = Path(urlparse(audio_url).path).suffix.lower()
        if suffix in _SUPPORTED_AUDIO_SUFFIXES:
            return suffix
        return ".mp3"

    def _get_temp_dir(self) -> Path:
        temp_dir = getattr(self.group, "temp_path", None)
        if temp_dir is None:
            temp_dir = Path("data") / "temp" / "suno"
        temp_path = Path(temp_dir)
        temp_path.mkdir(parents=True, exist_ok=True)
        return temp_path

    async def _download_ready_audio_file(self, item: dict[str, Any]) -> tuple[Path, str]:
        if not self._is_ready_audio_item(item):
            raise RuntimeError("当前片段还没有可下载的最终音频")

        audio_url = self._clip_audio_url(item)
        file_stem = self._sanitize_file_stem(self._clip_title(item))
        file_suffix = self._guess_audio_suffix(item)
        file_name = f"{file_stem}{file_suffix}"
        save_path = self._get_temp_dir() / f"{file_stem}_{uuid.uuid4().hex}{file_suffix}"

        timeout = self._get_timeout()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(audio_url) as response:
                    response.raise_for_status()
                    save_path.write_bytes(await response.read())
        except asyncio.TimeoutError as exc:
            raise RuntimeError("下载 Suno 成品音频超时") from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"下载 Suno 成品音频失败：{exc}") from exc

        return save_path, file_name

    @classmethod
    def _write_mp3_artist_metadata(cls, file_path: Path, item: dict[str, Any]) -> None:
        if file_path.suffix.lower() != ".mp3":
            return

        try:
            from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TPE2
        except ImportError as exc:
            raise RuntimeError("缺少 mutagen 依赖，无法写入 Suno 音频作者信息") from exc

        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        title = cls._clip_title(item)
        if title:
            tags.delall("TIT2")
            tags.add(TIT2(encoding=3, text=[title]))
        tags.delall("TPE1")
        tags.delall("TPE2")
        tags.add(TPE1(encoding=3, text=[_SUNO_AUDIO_ARTIST]))
        tags.add(TPE2(encoding=3, text=[_SUNO_AUDIO_ARTIST]))

        try:
            tags.save(file_path, v2_version=3)
        except Exception as exc:
            raise RuntimeError(f"写入 Suno 音频作者信息失败：{exc}") from exc

    async def _upload_generated_audio_file(self, file_path: Path, file_name: str) -> None:
        folder = await self.group.get_folder(_SUNO_UPLOAD_FOLDER)
        await self.group.upload_file(file_path, file_name, folder)

    async def _send_generation_result(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        lines = self._build_generation_lines(items)
        primary = self._pick_primary_item(items)
        fallback_text = "\n".join(lines)

        if primary is None or not self._is_ready_audio_item(primary):
            await self.group.send_msg(fallback_text)
            return {"uploaded": False, "file_name": ""}

        file_path: Path | None = None
        file_name = ""
        try:
            file_path, file_name = await self._download_ready_audio_file(primary)
            self._write_mp3_artist_metadata(file_path, primary)
            await self._upload_generated_audio_file(file_path, file_name)
            await self.group.send_msg(
                "\n".join(
                    [
                        fallback_text,
                        f"已上传到群文件：{file_name}",
                        f"目录：{_SUNO_UPLOAD_FOLDER}",
                    ]
                )
            )
            return {"uploaded": True, "file_name": file_name}
        except Exception as exc:
            await self.group.send_msg(f"{fallback_text}\n处理并上传群文件失败：{exc}")
            return {"uploaded": False, "file_name": file_name}
        finally:
            if file_path and file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _collect_clip_ids(items: list[dict[str, Any]]) -> list[str]:
        result: list[str] = []
        for item in items:
            clip_id = str(item.get("id") or "").strip()
            if clip_id and clip_id not in result:
                result.append(clip_id)
        return result

    async def _generate_music_request(
        self,
        *,
        prompt: str,
        make_instrumental: bool = False,
        title: str = "",
        tags: str = "",
        negative_tags: str = "",
        send_output: bool = False,
    ) -> dict[str, Any]:
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            if send_output:
                await self.group.send_msg("请输入音乐描述。")
            return {"success": False, "message": "请输入音乐描述"}

        normalized_title = str(title or "").strip()
        normalized_tags = str(tags or "").strip()
        normalized_negative_tags = str(negative_tags or "").strip()

        use_custom_generate = bool(normalized_title or normalized_tags or normalized_negative_tags)
        if use_custom_generate:
            request_path = "/api/custom_generate"
            request_payload = {
                "prompt": normalized_prompt,
                "tags": normalized_tags,
                "title": normalized_title or self._default_custom_title(normalized_prompt),
                "make_instrumental": bool(make_instrumental),
                "wait_audio": False,
            }
            if normalized_negative_tags:
                request_payload["negative_tags"] = normalized_negative_tags
        else:
            request_path = "/api/generate"
            request_payload = {
                "prompt": normalized_prompt,
                "make_instrumental": bool(make_instrumental),
                "wait_audio": False,
            }

        initial_payload = await self._request_json("POST", request_path, payload=request_payload)
        initial_items = self._extract_audio_items(initial_payload)
        clip_ids = self._collect_clip_ids(initial_items)

        if not initial_items:
            detail = self._extract_error_text(initial_payload) or "Suno 没有返回任何生成结果"
            if send_output:
                await self.group.send_msg(detail)
            return {"success": False, "message": detail}

        final_items = await self._poll_audio_information(clip_ids) if clip_ids else initial_items
        if not final_items:
            final_items = initial_items

        if self._all_failed(final_items):
            error_messages = [
                str(item.get("error_message") or "").strip()
                for item in final_items
                if str(item.get("error_message") or "").strip()
            ]
            detail = error_messages[0] if error_messages else "Suno 返回的所有片段都生成失败了"
            if send_output:
                await self.group.send_msg(f"生成失败：{detail}")
            return {
                "success": False,
                "message": f"生成失败：{detail}",
                "data": {"items": final_items, "clip_ids": clip_ids},
            }

        has_ready_audio = self._has_ready_audio(final_items)
        upload_result = {"uploaded": False, "file_name": ""}
        if send_output:
            upload_result = await self._send_generation_result(final_items)

        message = "已生成音乐并上传到群文件" if has_ready_audio else "音乐已提交生成，但等待时间内尚未拿到可上传的成品音频"
        if send_output and has_ready_audio and not upload_result["uploaded"]:
            message = "已生成音乐，但上传群文件失败，请稍后重试"

        return {
            "success": True,
            "message": message,
            "data": {
                "items": final_items,
                "clip_ids": clip_ids,
                "ready": has_ready_audio,
                "uploaded": bool(upload_result.get("uploaded", False)),
                "file_name": str(upload_result.get("file_name") or ""),
            },
        }

    async def _generate_lyrics_request(
        self,
        *,
        prompt: str,
        send_output: bool = False,
    ) -> dict[str, Any]:
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            if send_output:
                await self.group.send_msg("请输入歌词主题或要求。")
            return {"success": False, "message": "请输入歌词主题或要求"}

        payload = await self._request_json(
            "POST",
            "/api/generate_lyrics",
            payload={"prompt": normalized_prompt},
        )
        lyrics = self._extract_lyrics_text(payload)
        if not lyrics:
            if send_output:
                await self.group.send_msg("Suno 没有返回歌词内容。")
            return {"success": False, "message": "Suno 没有返回歌词内容"}

        if send_output:
            await self.group.send_msg(f"🎼 Suno 歌词：\n{lyrics}")

        return {"success": True, "message": "歌词已生成", "data": {"lyrics": lyrics}}

    @staticmethod
    def _format_limit_text(payload: dict[str, Any]) -> str:
        credits_left = payload.get("credits_left")
        period = payload.get("period")
        monthly_limit = payload.get("monthly_limit")
        monthly_usage = payload.get("monthly_usage")
        lines = ["Suno 额度信息："]
        if credits_left is not None:
            lines.append(f"剩余额度：{credits_left}")
        if period is not None:
            lines.append(f"周期：{period}")
        if monthly_limit is not None:
            lines.append(f"周期总额度：{monthly_limit}")
        if monthly_usage is not None:
            lines.append(f"本周期已使用：{monthly_usage}")
        return "\n".join(lines)

    async def _get_limit_request(self, *, send_output: bool = False) -> dict[str, Any]:
        payload = await self._request_json("GET", "/api/get_limit")
        if not isinstance(payload, dict):
            payload = {}
        text = self._format_limit_text(payload)
        if send_output:
            await self.group.send_msg(text)
        return {"success": True, "message": "已获取额度信息", "data": payload}

    @ai_tool(
        name="suno_generate_music",
        desc=(
            "使用 Suno 生成音乐并把最终成品上传到当前群文件。适用于用户想让机器人写歌、生成纯音乐、"
            "制作伴奏或根据描述生成歌曲的场景。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "音乐描述或歌词主题"},
                "make_instrumental": {"type": "boolean", "description": "是否生成纯音乐", "default": False},
                "title": {"type": "string", "description": "自定义标题，可选"},
                "tags": {"type": "string", "description": "曲风标签，可选，例如 pop, rock, piano"},
                "negative_tags": {"type": "string", "description": "不希望出现的风格标签，可选"},
            },
            "required": ["prompt"],
        },
        category="suno",
        triggers=["生成音乐", "写歌", "作曲", "纯音乐", "伴奏"],
    )
    async def generate_music_tool(
        self,
        user_id: int,
        group_id: int,
        prompt: str,
        make_instrumental: bool = False,
        title: str = "",
        tags: str = "",
        negative_tags: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "message": "Suno音乐服务未开启"}
        return await self._generate_music_request(
            prompt=prompt,
            make_instrumental=make_instrumental,
            title=title,
            tags=tags,
            negative_tags=negative_tags,
            send_output=True,
        )

    @ai_tool(
        name="suno_generate_lyrics",
        desc="使用 Suno 生成歌词，并把歌词发送到当前群聊。",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "歌词主题、情绪或故事要求"},
            },
            "required": ["prompt"],
        },
        category="suno",
        triggers=["写歌词", "生成歌词"],
    )
    async def generate_lyrics_tool(
        self,
        user_id: int,
        group_id: int,
        prompt: str,
        **kwargs,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "message": "Suno音乐服务未开启"}
        return await self._generate_lyrics_request(prompt=prompt, send_output=True)

    @ai_tool(
        name="suno_get_limit",
        desc="查看当前 Suno 账号的剩余额度。",
        parameters={"type": "object", "properties": {}, "required": []},
        category="suno",
        triggers=["Suno额度", "音乐额度"],
    )
    async def get_limit_tool(
        self,
        user_id: int,
        group_id: int,
        **kwargs,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "message": "Suno音乐服务未开启"}
        return await self._get_limit_request(send_output=True)

    @service_action(
        cmd="生成音乐",
        need_arg=True,
        desc="根据描述生成一首 Suno 音乐并上传到群文件",
        record_ai_context=True,
        ai_context_label="生成 Suno 音乐",
        ai_context_include_arg=True,
    )
    @check_enabled
    async def generate_music_command(self, event: GroupMessageEvent, arg: Message):
        prompt = arg.extract_plain_text().strip()
        if not prompt:
            await self.group.send_msg("请输入音乐描述。")
            return
        await self.group.send_msg("正在调用 Suno 生成音乐，完成后会上传到群文件，请稍等...")
        try:
            await self._generate_music_request(prompt=prompt, send_output=True)
        except Exception as exc:
            await self.group.send_msg(f"生成音乐失败：{exc}")

    @service_action(
        cmd="生成纯音乐",
        need_arg=True,
        desc="根据描述生成一首 Suno 纯音乐并上传到群文件",
        record_ai_context=True,
        ai_context_label="生成 Suno 纯音乐",
        ai_context_include_arg=True,
    )
    @check_enabled
    async def generate_instrumental_command(self, event: GroupMessageEvent, arg: Message):
        prompt = arg.extract_plain_text().strip()
        if not prompt:
            await self.group.send_msg("请输入纯音乐描述。")
            return
        await self.group.send_msg("正在调用 Suno 生成纯音乐，完成后会上传到群文件，请稍等...")
        try:
            await self._generate_music_request(
                prompt=prompt,
                make_instrumental=True,
                send_output=True,
            )
        except Exception as exc:
            await self.group.send_msg(f"生成纯音乐失败：{exc}")

    @service_action(
        cmd="写歌词",
        need_arg=True,
        desc="使用 Suno 生成歌词",
        record_ai_context=True,
        ai_context_label="使用 Suno 写歌词",
        ai_context_include_arg=True,
    )
    @check_enabled
    async def generate_lyrics_command(self, event: GroupMessageEvent, arg: Message):
        prompt = arg.extract_plain_text().strip()
        if not prompt:
            await self.group.send_msg("请输入歌词主题或要求。")
            return
        await self.group.send_msg("正在调用 Suno 生成歌词，请稍等...")
        try:
            await self._generate_lyrics_request(prompt=prompt, send_output=True)
        except Exception as exc:
            await self.group.send_msg(f"生成歌词失败：{exc}")

    @service_action(cmd="Suno额度", desc="查看 Suno 剩余额度")
    @check_enabled
    async def get_limit_command(self, event: GroupMessageEvent):
        try:
            await self._get_limit_request(send_output=True)
        except Exception as exc:
            await self.group.send_msg(f"获取额度失败：{exc}")


__all__ = ["SunoService"]
