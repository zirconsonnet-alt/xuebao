import asyncio
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    GroupUploadNoticeEvent,
    Message,
    MessageSegment,
)
from nonebot.internal.matcher import Matcher
from nonebot.log import logger

from src.support.cache_cleanup import cleanup_group_temp_cache
from src.support.core import Services
from src.support.group import get_name_simple as get_name, wait_for_event, run_flow

from .base import BaseService, config_property, service_action, service_notice

class CompositionService(BaseService):
    CARD_MAP_TTL_SECONDS = int(timedelta(hours=24).total_seconds())
    HISTORY_LOOKUP_RETRIES = 5
    HISTORY_LOOKUP_INTERVAL_SECONDS = 0.4
    HISTORY_LOOKUP_COUNT = 30
    MUSIC_CARD_UPLOAD_RETRIES = 6
    MUSIC_CARD_UPLOAD_WAIT_SECONDS = 0.5
    MUSIC_CARD_TRANSCODE_SUFFIXES = (".m4a", ".flac")
    LEGACY_SUPPORTED_FORMATS = [".wav", ".mp3"]
    service_type = Services.Composition
    default_config = {
        "enabled": True,
        "auto_card_enabled": True,
        "auto_essence_enabled": True,
        "supported_formats": [".wav", ".mp3", ".m4a", ".flac"],
        "music_card_cache_group_id": 0,
    }
    settings_schema = [
        {
            "key": "music_card_cache_group_id",
            "title": "音乐卡片缓存群",
            "description": "填群号后，m4a/flac 转出的 mp3 将优先上传到该群；填 0 表示直接上传到当前群。",
            "type": "int",
            "group": "音乐卡片",
            "min_value": 0,
        }
    ]
    enabled = config_property("enabled")
    auto_card_enabled = config_property("auto_card_enabled")
    auto_essence_enabled = config_property("auto_essence_enabled")
    supported_formats = config_property("supported_formats")
    music_card_cache_group_id = config_property("music_card_cache_group_id")

    def __init__(self, group):
        super().__init__(group)
        self._card_message_map: Dict[str, Dict[str, Any]] = {}
        self._ensure_supported_formats_config()

    @service_notice(desc="作品发布通知", event_type="GroupUploadNoticeEvent", priority=5, block=False)
    async def on_file_upload(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        if not self.enabled:
            return
        uploaded_file_name = str(getattr(event.file, "name", "") or "")
        if uploaded_file_name.startswith('['):
            return
        supported_formats = self._ensure_supported_formats_config()
        if not any(uploaded_file_name.lower().endswith(fmt) for fmt in supported_formats):
            return
        await self._send_music_card(event, matcher)

    @classmethod
    def _normalize_supported_formats(cls, raw_formats: Any) -> list[str]:
        if not isinstance(raw_formats, list):
            raw_formats = []

        normalized_formats: list[str] = []
        seen_formats: set[str] = set()
        for item in raw_formats:
            normalized = str(item or "").strip().lower()
            if not normalized:
                continue
            if not normalized.startswith("."):
                normalized = f".{normalized}"
            if normalized in seen_formats:
                continue
            normalized_formats.append(normalized)
            seen_formats.add(normalized)
        return normalized_formats

    def _ensure_supported_formats_config(self) -> list[str]:
        configured_formats = self._normalize_supported_formats(self._config.get("supported_formats"))
        legacy_formats = self._normalize_supported_formats(self.LEGACY_SUPPORTED_FORMATS)
        default_formats = self._normalize_supported_formats(self.default_config.get("supported_formats"))

        should_update = False
        if not configured_formats:
            configured_formats = list(default_formats)
            should_update = True
        elif configured_formats == legacy_formats:
            configured_formats = list(default_formats)
            should_update = True

        if self._config.get("supported_formats") != configured_formats:
            self._config["supported_formats"] = configured_formats
            should_update = True

        if should_update:
            self._save_config()
        return configured_formats

    async def _send_music_card(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        try:
            name, audio_url = await self._resolve_music_card_audio(event)
            if not audio_url:
                raise RuntimeError(f"未能为作品生成可播放的音乐卡片音频：{getattr(event.file, 'name', '')}")
            img_url = await self.group.get_user_img(event.user_id)
            uploader_name = await get_name(event)
            file_message_id = None

            if self.auto_essence_enabled:
                file_message_id = await self._find_file_message_id(event)

            if self.auto_card_enabled:
                card_result = await matcher.send(
                    MessageSegment(
                        "music",
                        {
                            "type": "custom",
                            "url": 'https://plm.xuebao.chat/',
                            'audio': audio_url,
                            "title": name,
                            "image": img_url,
                            "singer": uploader_name
                        }
                    )
                )
                card_message_id = self._extract_message_id_from_send_result(card_result)
                if self.auto_essence_enabled and card_message_id and file_message_id:
                    self._save_card_message_mapping(card_message_id, file_message_id, event.file)
                await matcher.send(
                    Message(
                        f"{uploader_name}老师发布了新作品，快来看看吧！(回复音乐卡片或群文件并发送" +
                        MessageSegment.face(63) +
                        "即可助力此作品成为群精华)"
                    )
                )

            if self.auto_essence_enabled:
                self._setup_essence_listener(matcher, uploader_name, event.file, file_message_id)
        except Exception as e:
            print(f"作品发布处理异常: {e}")

    async def _resolve_music_card_audio(self, event: GroupUploadNoticeEvent) -> tuple[str | None, str | None]:
        uploaded_file_name = str(getattr(event.file, "name", "") or "").strip()
        uploaded_suffix = Path(uploaded_file_name).suffix.lower()
        if uploaded_suffix not in self.MUSIC_CARD_TRANSCODE_SUFFIXES:
            return await self.group.get_resent_file_url()

        uploaded_file = await self._find_uploaded_file_entry(event)
        if not uploaded_file:
            logger.warning(f"作品发布未找到刚上传的音频文件，无法生成音乐卡片：{uploaded_file_name}")
            return uploaded_file_name or None, None

        audio_path, cache_key = await self._ensure_transcoded_audio_file(uploaded_file, event)
        if not audio_path or not cache_key:
            return self._extract_group_file_name(uploaded_file) or uploaded_file_name or None, None

        audio_url = await self._upload_music_card_audio_url(audio_path, cache_key)
        return self._extract_group_file_name(uploaded_file) or uploaded_file_name or audio_path.name, audio_url

    @staticmethod
    def _extract_group_files(payload: Any) -> list[dict]:
        if isinstance(payload, dict):
            files = payload.get("files")
            if isinstance(files, list):
                return [item for item in files if isinstance(item, dict)]
            data = payload.get("data")
            if isinstance(data, dict) and isinstance(data.get("files"), list):
                return [item for item in data["files"] if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_group_file_name(file_entry: dict[str, Any]) -> str:
        return str(file_entry.get("file_name") or file_entry.get("name") or "").strip()

    @staticmethod
    def _build_transcoded_cache_key(file_entry: dict[str, Any], event: GroupUploadNoticeEvent) -> str:
        raw_file_id = str(
            file_entry.get("file_id")
            or getattr(event.file, "id", "")
            or getattr(event.file, "file_id", "")
            or ""
        ).strip()
        if raw_file_id:
            return raw_file_id.replace("/", "_").replace("\\", "_")

        fallback_name = CompositionService._extract_group_file_name(file_entry) or str(
            getattr(event.file, "name", "") or "uploaded_audio"
        )
        normalized_name = "".join(
            char if char.isalnum() or char in {"-", "_", "."} else "_"
            for char in Path(fallback_name).stem
        ).strip("._")
        if not normalized_name:
            normalized_name = "uploaded_audio"
        return f"{int(getattr(event, 'group_id', 0) or 0)}_{int(getattr(event, 'user_id', 0) or 0)}_{normalized_name}"

    async def _find_uploaded_file_entry(self, event: GroupUploadNoticeEvent) -> dict[str, Any] | None:
        target_name = str(getattr(event.file, "name", "") or "").strip()
        target_file_id = str(getattr(event.file, "id", "") or getattr(event.file, "file_id", "") or "").strip()
        target_user_id = int(getattr(event, "user_id", 0) or 0)

        for attempt in range(self.MUSIC_CARD_UPLOAD_RETRIES):
            try:
                files = await self.group.get_files()
            except Exception as exc:
                logger.warning(f"作品发布查询群文件失败：{exc}")
                return None

            for file_entry in files:
                if not isinstance(file_entry, dict):
                    continue
                if target_file_id and str(file_entry.get("file_id") or "").strip() == target_file_id:
                    return file_entry

            for file_entry in files:
                if not isinstance(file_entry, dict):
                    continue
                file_name = self._extract_group_file_name(file_entry)
                if file_name != target_name:
                    continue
                try:
                    uploader = int(file_entry.get("uploader") or 0)
                except (TypeError, ValueError):
                    uploader = 0
                if target_user_id and uploader == target_user_id:
                    return file_entry

            for file_entry in files:
                if not isinstance(file_entry, dict):
                    continue
                if self._extract_group_file_name(file_entry) == target_name:
                    return file_entry

            if attempt < self.MUSIC_CARD_UPLOAD_RETRIES - 1:
                await asyncio.sleep(self.MUSIC_CARD_UPLOAD_WAIT_SECONDS)
        return None

    async def _ensure_transcoded_audio_file(
        self,
        uploaded_file: dict[str, Any],
        event: GroupUploadNoticeEvent,
    ) -> tuple[Path | None, str | None]:
        cache_key = self._build_transcoded_cache_key(uploaded_file, event)
        target_mp3_path = self.group.temp_path / "composition_music_card" / f"{cache_key}.mp3"
        if target_mp3_path.exists():
            cleanup_group_temp_cache(int(self.group.group_id), protected_paths=[target_mp3_path])
            return target_mp3_path, cache_key

        source_path = await self.group.download_file(uploaded_file)
        if not source_path:
            logger.warning(f"作品发布下载源音频失败：{self._extract_group_file_name(uploaded_file)}")
            return None, cache_key

        source_file = Path(source_path)
        try:
            converted_path = await self._convert_audio_to_mp3(source_file, target_mp3_path)
        finally:
            source_file.unlink(missing_ok=True)

        if not converted_path:
            target_mp3_path.unlink(missing_ok=True)
            return None, cache_key
        cleanup_group_temp_cache(int(self.group.group_id), protected_paths=[converted_path])
        return converted_path, cache_key

    @staticmethod
    async def _convert_audio_to_mp3(source_path: Path, target_path: Path) -> Path | None:
        if not source_path.exists():
            return None

        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ab",
                "192k",
                str(target_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            logger.warning(f"作品发布音频转码失败，未找到 ffmpeg：{exc}")
            return None

        _, stderr = await process.communicate()
        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="ignore")
            logger.warning(f"作品发布音频转码失败：{stderr_text[-300:]}")
            return None
        return target_path if target_path.exists() else None

    def _get_music_card_upload_group_ids(self) -> list[int]:
        upload_group_ids: list[int] = []
        raw_cache_group_id = self.music_card_cache_group_id
        try:
            cache_group_id = int(raw_cache_group_id or 0)
        except (TypeError, ValueError):
            cache_group_id = 0

        for group_id in (cache_group_id, int(self.group.group_id)):
            if group_id <= 0:
                continue
            if group_id in upload_group_ids:
                continue
            upload_group_ids.append(group_id)
        return upload_group_ids

    async def _find_group_file(self, group_id: int, file_name: str) -> dict[str, Any] | None:
        try:
            payload = await self.group.gateway.get_group_root_files(group_id)
        except Exception as exc:
            logger.warning(f"作品发布查询群文件失败：group={group_id} {exc}")
            return None

        for file_entry in self._extract_group_files(payload):
            if self._extract_group_file_name(file_entry) == file_name:
                return file_entry
        return None

    async def _resolve_group_file_url(self, group_id: int, file_entry: dict[str, Any]) -> str | None:
        try:
            payload = await self.group.gateway.get_group_file_url(
                group_id,
                str(file_entry["file_id"]),
                int(file_entry["busid"]),
            )
        except Exception as exc:
            logger.warning(f"作品发布获取群文件外链失败：group={group_id} {exc}")
            return None

        if isinstance(payload, dict):
            direct_url = payload.get("url")
            if isinstance(direct_url, str) and direct_url:
                return direct_url
            data = payload.get("data")
            if isinstance(data, dict):
                nested_url = data.get("url")
                if isinstance(nested_url, str) and nested_url:
                    return nested_url
        return None

    async def _get_or_upload_group_file_url(self, group_id: int, audio_path: Path, file_name: str) -> str | None:
        existing_file = await self._find_group_file(group_id, file_name)
        if existing_file:
            return await self._resolve_group_file_url(group_id, existing_file)

        try:
            await self.group.gateway.upload_file(
                group_id,
                str(audio_path.resolve()),
                file_name,
                "/",
            )
        except Exception as exc:
            logger.warning(f"作品发布上传音乐卡片音频失败：group={group_id} {exc}")
            return None

        for _ in range(self.MUSIC_CARD_UPLOAD_RETRIES):
            await asyncio.sleep(self.MUSIC_CARD_UPLOAD_WAIT_SECONDS)
            uploaded_file = await self._find_group_file(group_id, file_name)
            if not uploaded_file:
                continue
            if file_url := await self._resolve_group_file_url(group_id, uploaded_file):
                return file_url

        logger.warning(f"作品发布上传音频后未获取到外链：group={group_id} file={file_name}")
        return None

    async def _upload_music_card_audio_url(self, audio_path: Path, cache_key: str) -> str | None:
        file_name = f"composition_{cache_key}.mp3"
        for group_id in self._get_music_card_upload_group_ids():
            audio_url = await self._get_or_upload_group_file_url(group_id, audio_path, file_name)
            if audio_url:
                return audio_url
        return None

    @staticmethod
    def _extract_message_id_from_send_result(result: Any) -> Optional[int]:
        if isinstance(result, int):
            return result
        if isinstance(result, dict):
            message_id = result.get("message_id")
            if message_id is None and isinstance(result.get("data"), dict):
                message_id = result["data"].get("message_id")
        else:
            message_id = getattr(result, "message_id", None)
        try:
            if message_id is None:
                return None
            return int(message_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_history_messages(result: Any) -> list[dict]:
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if not isinstance(result, dict):
            return []
        if isinstance(result.get("messages"), list):
            return [item for item in result["messages"] if isinstance(item, dict)]
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return [item for item in data["messages"] if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_message_segments(message: Any) -> list[dict]:
        if not message or isinstance(message, str):
            return []
        segments = []
        try:
            iterator = list(message)
        except TypeError:
            iterator = []
        for segment in iterator:
            if isinstance(segment, dict):
                segment_type = segment.get("type")
                data = segment.get("data") or {}
            else:
                segment_type = getattr(segment, "type", None)
                data = getattr(segment, "data", None) or {}
            if segment_type:
                segments.append({"type": segment_type, "data": data})
        return segments

    @staticmethod
    def _extract_history_user_id(message_entry: Dict[str, Any]) -> Optional[int]:
        user_id = message_entry.get("user_id")
        if user_id is None and isinstance(message_entry.get("sender"), dict):
            user_id = message_entry["sender"].get("user_id")
        try:
            if user_id is None:
                return None
            return int(user_id)
        except (TypeError, ValueError):
            return None

    def _message_matches_file(self, message: Any, file: Any) -> bool:
        target_file_id = str(getattr(file, "id", "") or "")
        target_file_name = str(getattr(file, "name", "") or "")
        for segment in self._extract_message_segments(message):
            if segment["type"] != "file":
                continue
            data = segment["data"]
            message_file_id = str(data.get("file_id") or data.get("id") or "")
            if target_file_id and message_file_id == target_file_id:
                return True
            message_file_name = str(data.get("file") or data.get("name") or "")
            if target_file_name and message_file_name == target_file_name:
                return True
        return False

    async def _find_file_message_id(self, event: GroupUploadNoticeEvent) -> Optional[int]:
        for _ in range(self.HISTORY_LOOKUP_RETRIES):
            try:
                history = await self.group.get_message_history(count=self.HISTORY_LOOKUP_COUNT)
                for message_entry in self._extract_history_messages(history):
                    user_id = self._extract_history_user_id(message_entry)
                    if user_id is not None and user_id != event.user_id:
                        continue
                    if not self._message_matches_file(message_entry.get("message"), event.file):
                        continue
                    message_id = self._extract_message_id_from_send_result(message_entry)
                    if message_id is not None:
                        return message_id
            except Exception as exc:
                print(f"查询作品原始消息失败: {exc}")
            await asyncio.sleep(self.HISTORY_LOOKUP_INTERVAL_SECONDS)
        return None

    def _prune_card_message_mappings(self) -> None:
        now = time.time()
        expired_keys = [
            key for key, value in self._card_message_map.items()
            if value.get("expires_at", 0) <= now
        ]
        for key in expired_keys:
            self._card_message_map.pop(key, None)

    def _save_card_message_mapping(self, card_message_id: int, file_message_id: int, file: Any) -> None:
        self._prune_card_message_mappings()
        self._card_message_map[str(card_message_id)] = {
            "file_message_id": int(file_message_id),
            "file_id": str(getattr(file, "id", "") or ""),
            "file_name": str(getattr(file, "name", "") or ""),
            "expires_at": time.time() + self.CARD_MAP_TTL_SECONDS,
        }

    def _get_card_message_mapping(self, card_message_id: Optional[int]) -> Optional[Dict[str, Any]]:
        self._prune_card_message_mappings()
        if card_message_id is None:
            return None
        return self._card_message_map.get(str(card_message_id))

    def _delete_card_message_mapping(self, card_message_id: Optional[int]) -> None:
        if card_message_id is None:
            return
        self._card_message_map.pop(str(card_message_id), None)

    def _resolve_essence_target_message_id(
        self,
        reply: Any,
        file: Any,
        file_message_id: Optional[int],
    ) -> Optional[int]:
        reply_message_id = self._extract_message_id_from_send_result({"message_id": getattr(reply, "message_id", None)})
        if file_message_id is not None and reply_message_id == int(file_message_id):
            return file_message_id
        if self._message_matches_file(getattr(reply, "message", None), file):
            return reply_message_id or file_message_id

        mapping = self._get_card_message_mapping(reply_message_id)
        if not mapping:
            return None

        target_file_id = str(getattr(file, "id", "") or "")
        if target_file_id and mapping.get("file_id") != target_file_id:
            return None
        try:
            return int(mapping["file_message_id"])
        except (KeyError, TypeError, ValueError):
            return None

    def _setup_essence_listener(
        self,
        matcher: Matcher,
        uploader_name: str,
        file: Any,
        file_message_id: Optional[int],
    ):
        async def waiter_task():
            deadline = self.CARD_MAP_TTL_SECONDS
            start_ts = None
            while True:
                if start_ts is None:
                    start_ts = time.time()
                remain = int(deadline - (time.time() - start_ts))
                if remain <= 0:
                    return
                event = await wait_for_event(remain)
                if not event:
                    return
                if not isinstance(event, GroupMessageEvent):
                    continue
                if not event.reply:
                    continue
                if not event.message or event.message[0].type != "face":
                    continue
                try:
                    if int(event.message[0].data.get("id", -1)) != 63:
                        continue
                except Exception:
                    continue
                target_message_id = self._resolve_essence_target_message_id(
                    event.reply,
                    file,
                    file_message_id,
                )
                if target_message_id is None:
                    continue
                await self.group.set_msg(target_message_id)
                self._delete_card_message_mapping(getattr(event.reply, "message_id", None))
                await matcher.send(f"{uploader_name}老师的作品深受喜爱，并被设为精华!")
                return

        asyncio.create_task(waiter_task())

    @service_action(cmd="作品发布服务")
    async def composition_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ 作品发布服务未开启！")
            return
        flow = {
            "title": "欢迎使用作品发布服务",
            "text": "该服务暂无可用操作，主要通过文件上传自动处理。",
        }
        await run_flow(self.group, flow)
