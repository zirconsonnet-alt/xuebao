"""群聊 AI 助手状态管理。"""

import asyncio
from io import BytesIO
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
import uuid

from src.support.ai import config
from src.support.cache_cleanup import cleanup_ai_media_cache
from src.support.core import make_dict
from src.support.storage_guard import ensure_optional_write_allowed

from .common import BASE_MENU_ITEMS, GROUP_MENU_ITEMS, MenuItem
from .message_utils import resolve_local_media_path, to_file_uri


class GroupStateMixin:
    MEDIA_CACHE_MAX_FILES = 24
    COMPLETED_MEDIA_DESCRIPTION_MAX = 12
    RECORDED_ASSISTANT_MESSAGE_ID_MAX = 200

    @staticmethod
    def _normalize_media_prompt(prompt: str = "") -> str:
        return " ".join((prompt or "").split())

    @staticmethod
    def _normalize_inline_text(text: str) -> str:
        normalized = " ".join(str(text or "").split())
        return normalized or "[空消息]"

    def _build_group_user_message(
        self,
        identity: Dict[str, Any],
        message_text: str,
        *,
        reply_text: str = "",
    ) -> str:
        display_name = str(identity.get("display_name") or f"QQ:{identity.get('user_id', 0)}")
        nickname = str(identity.get("nickname") or "").strip()
        role_name = str(identity.get("role_name") or "成员").strip() or "成员"

        lines = [
            "[群消息]",
            f"发送者：{display_name}",
        ]
        if nickname and nickname != display_name:
            lines.append(f"昵称：{nickname}")
        lines.append(f"QQ：{identity.get('user_id', 0)}")
        lines.append(f"群角色：{role_name}")

        normalized_reply_text = self._normalize_inline_text(reply_text) if reply_text else ""
        if normalized_reply_text:
            lines.append(f"回复内容：{normalized_reply_text}")
        lines.append(f"内容：{self._normalize_inline_text(message_text)}")
        return "\n".join(lines)

    def _normalize_group_buffer_identity(
        self,
        nickname: str,
        user_id: int,
        member_identity: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        identity = dict(member_identity or {})
        normalized_user_id = int(identity.get("user_id") or user_id or 0)
        display_name = str(identity.get("display_name") or nickname or f"QQ:{normalized_user_id}")
        nickname_text = str(identity.get("nickname") or display_name)
        role_name = str(identity.get("role_name") or "成员").strip() or "成员"
        return {
            "user_id": normalized_user_id,
            "display_name": display_name,
            "nickname": nickname_text,
            "role_name": role_name,
        }

    @staticmethod
    def _coerce_media_bytes(media_bytes: Any) -> bytes:
        if isinstance(media_bytes, bytes):
            return media_bytes
        if isinstance(media_bytes, bytearray):
            return bytes(media_bytes)
        if isinstance(media_bytes, memoryview):
            return media_bytes.tobytes()
        if isinstance(media_bytes, BytesIO):
            return media_bytes.getvalue()
        raise TypeError("media_bytes must be bytes-like or BytesIO")

    def _load_config(self) -> Dict[str, Any]:
        default_config = super()._load_config()
        group_defaults = {
            "group_mode": True,
            "rate_limit_enabled": config.default_rate_limit_enabled,
            "rate_limit_per_hour": config.default_rate_limit_per_hour,
            "rate_limit_warning": config.default_rate_limit_warning,
            "redirect_group": config.default_redirect_group,
        }
        for key, value in group_defaults.items():
            if key not in default_config:
                default_config[key] = value
        return default_config

    @property
    def group_mode(self) -> bool:
        return self._config.get("group_mode", True)

    @group_mode.setter
    def group_mode(self, value: bool):
        self._config["group_mode"] = value
        self._save_config()

    @property
    def rate_limit_enabled(self) -> bool:
        return self._config.get("rate_limit_enabled", True)

    @rate_limit_enabled.setter
    def rate_limit_enabled(self, value: bool):
        self._config["rate_limit_enabled"] = value
        self._save_config()

    @property
    def rate_limit_per_hour(self) -> int:
        return self._config.get("rate_limit_per_hour", 3)

    @rate_limit_per_hour.setter
    def rate_limit_per_hour(self, value: int):
        self._config["rate_limit_per_hour"] = value
        self._save_config()

    @property
    def rate_limit_warning(self) -> str:
        return self._config.get("rate_limit_warning", config.default_rate_limit_warning)

    @rate_limit_warning.setter
    def rate_limit_warning(self, value: str):
        self._config["rate_limit_warning"] = value
        self._save_config()

    @property
    def redirect_group(self) -> int:
        return self._config.get("redirect_group", config.default_redirect_group)

    @redirect_group.setter
    def redirect_group(self, value: int):
        self._config["redirect_group"] = value
        self._save_config()

    def _get_menu_items(self) -> List[MenuItem]:
        return BASE_MENU_ITEMS + GROUP_MENU_ITEMS

    def _has_recorded_assistant_message_id(self, message_id: Any) -> bool:
        try:
            normalized_message_id = int(message_id)
        except (TypeError, ValueError):
            return False
        return normalized_message_id in getattr(self, "_recorded_assistant_message_ids", set())

    def _remember_recorded_assistant_message_id(self, message_id: Any):
        try:
            normalized_message_id = int(message_id)
        except (TypeError, ValueError):
            return

        recorded_ids = getattr(self, "_recorded_assistant_message_ids", None)
        recorded_order = getattr(self, "_recorded_assistant_message_order", None)
        if recorded_ids is None or recorded_order is None:
            return

        if normalized_message_id in recorded_ids:
            return

        recorded_ids.add(normalized_message_id)
        recorded_order.append(normalized_message_id)
        while len(recorded_order) > self.RECORDED_ASSISTANT_MESSAGE_ID_MAX:
            expired_message_id = recorded_order.pop(0)
            recorded_ids.discard(expired_message_id)

    def _cache_media_file(self, media_url: str, media_type: str) -> str:
        local_path = resolve_local_media_path(media_url)
        if local_path is None:
            return str(media_url)
        if not local_path.exists():
            return str(media_url)

        cache_dir = getattr(self, "_media_cache_dir", None)
        cache_files = getattr(self, "_media_cache_files", None)
        if cache_dir is None or cache_files is None:
            return str(media_url)

        try:
            resolved_local_path = local_path.resolve(strict=False)
        except Exception:
            resolved_local_path = Path(local_path)

        try:
            resolved_cache_dir = Path(cache_dir).resolve(strict=False)
            if resolved_local_path.parent == resolved_cache_dir:
                return to_file_uri(resolved_local_path)
        except Exception:
            pass

        suffix = resolved_local_path.suffix or (".mp4" if media_type == "video" else ".jpg")
        cached_path = Path(cache_dir) / f"{media_type}_{uuid.uuid4().hex}{suffix}"
        try:
            expected_bytes = resolved_local_path.stat().st_size
        except OSError:
            expected_bytes = None
        decision = ensure_optional_write_allowed(
            "AI 媒体缓存写入",
            cached_path,
            expected_bytes=expected_bytes,
        )
        if not decision.allowed:
            print(decision.message)
            return str(media_url)
        shutil.copy2(resolved_local_path, cached_path)
        cache_files.append(cached_path)

        while len(cache_files) > self.MEDIA_CACHE_MAX_FILES:
            expired_path = cache_files.pop(0)
            try:
                if expired_path.exists():
                    expired_path.unlink()
            except Exception:
                pass

        cleanup_ai_media_cache(protected_paths=[cached_path])
        return to_file_uri(cached_path)

    def cache_media_bytes(
        self,
        media_bytes: Any,
        media_type: str,
        *,
        suffix: str = "",
    ) -> str:
        cache_dir = getattr(self, "_media_cache_dir", None)
        cache_files = getattr(self, "_media_cache_files", None)
        if cache_dir is None or cache_files is None:
            raise RuntimeError("AI 媒体缓存目录未初始化")

        normalized_suffix = str(suffix or "").strip()
        if normalized_suffix and not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"
        if not normalized_suffix:
            normalized_suffix = ".mp4" if media_type == "video" else ".png"

        normalized_media_bytes = self._coerce_media_bytes(media_bytes)
        cached_path = Path(cache_dir) / f"{media_type}_{uuid.uuid4().hex}{normalized_suffix}"
        decision = ensure_optional_write_allowed(
            "AI 媒体字节缓存写入",
            cached_path,
            expected_bytes=len(normalized_media_bytes),
        )
        if not decision.allowed:
            raise RuntimeError(decision.message)
        cached_path.write_bytes(normalized_media_bytes)
        cache_files.append(cached_path)

        while len(cache_files) > self.MEDIA_CACHE_MAX_FILES:
            expired_path = cache_files.pop(0)
            try:
                if expired_path.exists():
                    expired_path.unlink()
            except Exception:
                pass

        cleanup_ai_media_cache(protected_paths=[cached_path])
        return to_file_uri(cached_path)

    def _normalize_registry_media_url(self, media_url: str, media_type: str) -> str:
        normalized_url = str(media_url or "").strip()
        if not normalized_url:
            return normalized_url
        try:
            return self._cache_media_file(normalized_url, media_type)
        except Exception:
            return normalized_url

    def register_image(self, url: str) -> str:
        self._image_counter += 1
        image_id = f"img_{self._image_counter:03d}"
        self._image_registry[image_id] = self._normalize_registry_media_url(url, "image")
        return image_id

    def get_image_url(self, image_id: str) -> Optional[str]:
        return self._image_registry.get(image_id)

    def clear_image_registry(self):
        self._image_registry.clear()
        self._image_counter = 0

    def register_video(self, url: str) -> str:
        self._video_counter += 1
        video_id = f"vid_{self._video_counter:03d}"
        self._video_registry[video_id] = self._normalize_registry_media_url(url, "video")
        return video_id

    def get_video_url(self, video_id: str) -> Optional[str]:
        return self._video_registry.get(video_id)

    def clear_video_registry(self):
        self._video_registry.clear()
        self._video_counter = 0

    def _cleanup_pending_media_description_tasks(self):
        tasks = getattr(self, "_pending_media_description_tasks", None)
        if not tasks:
            return

        stale_keys = [key for key, task in tasks.items() if task.done()]
        for key in stale_keys:
            tasks.pop(key, None)
            self._pending_media_description_meta.pop(key, None)

    def get_completed_media_description(
        self,
        key: tuple[str, str, str],
    ) -> Optional[str]:
        results = getattr(self, "_completed_media_description_results", None)
        if not results:
            return None
        return results.get(key)

    def set_completed_media_description(
        self,
        key: tuple[str, str, str],
        result: str,
        *,
        media_type: str,
        media_id: str,
        prompt: str = "",
    ):
        normalized_result = str(result or "").strip()
        if not normalized_result:
            return

        results = getattr(self, "_completed_media_description_results", None)
        meta_map = getattr(self, "_completed_media_description_meta", None)
        order = getattr(self, "_completed_media_description_order", None)
        if results is None or meta_map is None or order is None:
            return

        if key in order:
            order.remove(key)
        order.append(key)
        results[key] = normalized_result
        meta_map[key] = {
            "media_type": media_type,
            "media_id": media_id,
            "prompt": self._normalize_media_prompt(prompt),
        }

        while len(order) > self.COMPLETED_MEDIA_DESCRIPTION_MAX:
            expired_key = order.pop(0)
            results.pop(expired_key, None)
            meta_map.pop(expired_key, None)

    def build_media_description_key(
        self,
        media_type: str,
        media_url: str,
        prompt: str = "",
    ) -> tuple[str, str, str]:
        return (
            (media_type or "").strip(),
            (media_url or "").strip(),
            self._normalize_media_prompt(prompt),
        )

    def get_pending_media_description_task(
        self,
        key: tuple[str, str, str],
    ) -> Optional[asyncio.Task]:
        self._cleanup_pending_media_description_tasks()
        return self._pending_media_description_tasks.get(key)

    def set_pending_media_description_task(
        self,
        key: tuple[str, str, str],
        task: asyncio.Task,
        *,
        media_type: str,
        media_id: str,
        prompt: str = "",
    ):
        self._pending_media_description_tasks[key] = task
        self._pending_media_description_meta[key] = {
            "media_type": media_type,
            "media_id": media_id,
            "prompt": self._normalize_media_prompt(prompt),
        }

    def clear_pending_media_description_task(self, key: tuple[str, str, str]):
        self._pending_media_description_tasks.pop(key, None)
        self._pending_media_description_meta.pop(key, None)

    def build_pending_media_status_message(self) -> str:
        self._cleanup_pending_media_description_tasks()
        pending_meta = getattr(self, "_pending_media_description_meta", None) or {}
        completed_meta = getattr(self, "_completed_media_description_meta", None) or {}
        completed_order = getattr(self, "_completed_media_description_order", None) or []
        if not pending_meta and not completed_meta:
            return ""

        lines: List[str] = []
        if pending_meta:
            lines.append("以下媒体描述任务正在进行中：")
            for meta in pending_meta.values():
                media_type = meta.get("media_type", "")
                media_label = "图片" if media_type == "image" else "视频"
                media_id = meta.get("media_id") or "未命名媒体"
                prompt = meta.get("prompt", "")
                if prompt:
                    prompt = prompt[:40]
                    lines.append(f"- {media_label} {media_id} 正在分析中，提示词：{prompt}")
                else:
                    lines.append(f"- {media_label} {media_id} 正在分析中")

        if completed_meta:
            if lines:
                lines.append("")
            lines.append("以下媒体描述任务最近已完成：")
            for key in reversed(list(completed_order)):
                meta = completed_meta.get(key) or {}
                media_type = meta.get("media_type", "")
                media_label = "图片" if media_type == "image" else "视频"
                media_id = meta.get("media_id") or "未命名媒体"
                prompt = meta.get("prompt", "")
                if prompt:
                    prompt = prompt[:40]
                    lines.append(f"- {media_label} {media_id} 已分析完成，提示词：{prompt}")
                else:
                    lines.append(f"- {media_label} {media_id} 已分析完成")

        lines.append("如果当前用户是在追问上述同一媒体，优先基于已有工具结果回答，不要重复调用 describe_image 或 describe_video。")
        if pending_meta:
            lines.append("对于仍在进行中的媒体，直接说明还在分析中即可。")
        return "\n".join(lines)

    def buffer_chat_message(
        self,
        nickname: str,
        user_id: int,
        message: str,
        image_urls: List[str] = None,
        video_urls: List[str] = None,
        *,
        member_identity: Dict[str, Any] | None = None,
    ):
        if not self.group_mode:
            return

        if image_urls:
            for url in image_urls:
                image_id = self.register_image(url)
                message += f" [图片:{image_id}]"

        if video_urls:
            for url in video_urls:
                video_id = self.register_video(url)
                message += f" [视频:{video_id}]"

        buffer_entry = {
            "identity": self._normalize_group_buffer_identity(nickname, user_id, member_identity),
            "message": self._normalize_inline_text(message),
        }
        self._chat_buffer.append(buffer_entry)
        while len(self._chat_buffer) > self.CHAT_BUFFER_MAX_MESSAGES:
            self._chat_buffer.pop(0)

        total_len = sum(
            len(self._build_group_user_message(entry["identity"], entry["message"]))
            for entry in self._chat_buffer
        )
        while total_len > self.CHAT_BUFFER_MAX_LENGTH and self._chat_buffer:
            removed = self._chat_buffer.pop(0)
            total_len -= len(self._build_group_user_message(removed["identity"], removed["message"]))

    def _build_assistant_message_content(
        self,
        message: str = "",
        *,
        image_urls: List[str] = None,
        video_urls: List[str] = None,
        markers: List[str] = None,
    ) -> str:
        parts: List[str] = []
        normalized_message = self._normalize_media_prompt(message)
        if normalized_message:
            parts.append(normalized_message)

        for marker in markers or []:
            marker_text = str(marker or "").strip()
            if marker_text:
                parts.append(marker_text)

        for url in image_urls or []:
            image_id = self.register_image(url)
            parts.append(f"[图片:{image_id}]")

        for url in video_urls or []:
            video_id = self.register_video(url)
            parts.append(f"[视频:{video_id}]")

        return " ".join(parts).strip()

    def record_assistant_output(
        self,
        message: str = "",
        *,
        image_urls: List[str] = None,
        video_urls: List[str] = None,
        markers: List[str] = None,
        message_id: Any = None,
        remember_only: bool = False,
    ) -> bool:
        if self._has_recorded_assistant_message_id(message_id):
            return False

        self._remember_recorded_assistant_message_id(message_id)
        if remember_only:
            return self._has_recorded_assistant_message_id(message_id)

        content = self._build_assistant_message_content(
            message,
            image_urls=image_urls,
            video_urls=video_urls,
            markers=markers,
        )
        if not content:
            return False

        self.add_message(make_dict("assistant", content))
        return True

    def flush_chat_buffer(self):
        if not self._chat_buffer:
            return

        lines = ["[群聊记录]"]
        for entry in self._chat_buffer:
            lines.append(self._build_group_user_message(entry["identity"], entry["message"]))

        chat_record = "\n".join(lines)
        self.add_message(make_dict("user", chat_record))
        self._chat_buffer.clear()


__all__ = ["GroupStateMixin"]
