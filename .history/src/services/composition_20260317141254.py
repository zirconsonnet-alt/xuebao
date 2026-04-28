import asyncio
import time
from datetime import timedelta
from typing import Any, Dict, Optional

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    GroupUploadNoticeEvent,
    Message,
    MessageSegment,
)
from nonebot.internal.matcher import Matcher

from src.support.core import Services
from src.support.group import get_name_simple as get_name, wait_for_event, run_flow

from .base import BaseService, config_property, service_action, service_notice

class CompositionService(BaseService):
    CARD_MAP_TTL_SECONDS = int(timedelta(minutes=10).total_seconds())
    HISTORY_LOOKUP_RETRIES = 5
    HISTORY_LOOKUP_INTERVAL_SECONDS = 0.4
    HISTORY_LOOKUP_COUNT = 30
    service_type = Services.Composition
    default_config = {
        "enabled": True,
        "auto_card_enabled": True,
        "auto_essence_enabled": True,
        "supported_formats": [".wav", ".mp3"]
    }
    enabled = config_property("enabled")
    auto_card_enabled = config_property("auto_card_enabled")
    auto_essence_enabled = config_property("auto_essence_enabled")
    supported_formats = config_property("supported_formats")

    def __init__(self, group):
        super().__init__(group)
        self._card_message_map: Dict[str, Dict[str, Any]] = {}

    @service_notice(desc="作品发布通知", event_type="GroupUploadNoticeEvent", priority=5, block=False)
    async def on_file_upload(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        if not self.enabled:
            return
        uploaded_file_name = event.file.name
        if uploaded_file_name.startswith('['):
            return
        if not any(uploaded_file_name.endswith(fmt) for fmt in self.supported_formats):
            return
        await self._send_music_card(event, matcher)

    async def _send_music_card(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        try:
            name, audio_url = await self.group.get_resent_file_url()
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
                            "url": 'https://vdse.bdstatic.com//192d9a98d782d9c74c96f09db9378d93.mp4',
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
            deadline = timedelta(minutes=10).total_seconds()
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
