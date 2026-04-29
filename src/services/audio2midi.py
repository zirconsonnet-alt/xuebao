import asyncio
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.compat import type_validate_python

from src.support.core import Services, ai_tool

from .base import BaseService, config_property, service_action

_BasicPitchClass: Any = None
_NormalPitchDetectorClass: Any = None
_AUDIO2MIDI_AVAILABLE: Optional[bool] = None
_AUDIO2MIDI_IMPORT_ERROR = ""


def _load_audio2midi_classes() -> None:
    global _AUDIO2MIDI_AVAILABLE, _AUDIO2MIDI_IMPORT_ERROR
    global _BasicPitchClass, _NormalPitchDetectorClass

    if _AUDIO2MIDI_AVAILABLE is not None:
        return

    try:
        from audio2midi.basic_pitch_pitch_detector import BasicPitch
        from audio2midi.librosa_pitch_detector import Normal_Pitch_Det

        _BasicPitchClass = BasicPitch
        _NormalPitchDetectorClass = Normal_Pitch_Det
        _AUDIO2MIDI_AVAILABLE = True
        _AUDIO2MIDI_IMPORT_ERROR = ""
    except Exception as exc:
        _BasicPitchClass = None
        _NormalPitchDetectorClass = None
        _AUDIO2MIDI_AVAILABLE = False
        _AUDIO2MIDI_IMPORT_ERROR = str(exc)


_AUDIO_URL_RE = re.compile(
    r"https?://[^\s\"']+\.(?:mp3|wav|ogg|flac|m4a|aac|opus|amr)(?:\?[^\s\"']*)?",
    re.IGNORECASE,
)
_SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|]+")
_SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".m4a",
    ".aac",
    ".opus",
    ".amr",
}
_PREFERRED_AUDIO_KEYS = (
    "audio",
    "musicUrl",
    "music_url",
    "playUrl",
    "play_url",
    "src",
    "source",
    "url",
)
_PREFERRED_TITLE_KEYS = ("title", "name", "music_name", "songName", "song_name")


class Audio2MidiService(BaseService):
    service_type = Services.Audio2Midi
    default_config = {"enabled": True}
    enabled = config_property("enabled")
    _basic_pitch_detector: Optional[Any] = None
    _basic_pitch_init_error: str | None = None
    _basic_pitch_lock = threading.Lock()
    _detector: Any = None

    def __init__(self, group):
        super().__init__(group)
        self._detector = None

    @classmethod
    def _get_dependency_error_message(cls) -> str:
        detail = _AUDIO2MIDI_IMPORT_ERROR or "未安装 audio2midi 依赖"
        return f"扒谱依赖不可用：{detail}"

    @classmethod
    def _ensure_audio2midi_available(cls) -> None:
        _load_audio2midi_classes()
        if not _AUDIO2MIDI_AVAILABLE or _BasicPitchClass is None or _NormalPitchDetectorClass is None:
            raise RuntimeError(cls._get_dependency_error_message())

    @classmethod
    def _get_basic_pitch_detector(cls) -> Any:
        cls._ensure_audio2midi_available()
        if cls._basic_pitch_detector is not None:
            return cls._basic_pitch_detector

        with cls._basic_pitch_lock:
            if cls._basic_pitch_detector is not None:
                return cls._basic_pitch_detector
            detector = _BasicPitchClass()
            cls._basic_pitch_detector = detector
            cls._basic_pitch_init_error = None
            return detector

    def _get_librosa_detector(self) -> Any:
        detector = getattr(self, "_detector", None)
        if detector is not None:
            return detector

        self._ensure_audio2midi_available()
        detector = _NormalPitchDetectorClass()
        self._detector = detector
        return detector

    @staticmethod
    def _extract_audio_url(text: str) -> str:
        if not text:
            return ""
        match = _AUDIO_URL_RE.search(text)
        return match.group(0) if match else ""

    @staticmethod
    def _is_supported_audio_name(file_name: str) -> bool:
        return Path(str(file_name or "")).suffix.lower() in _SUPPORTED_EXTENSIONS

    @staticmethod
    def _guess_suffix(*, url: str = "", file_name: str = "") -> str:
        for candidate in (file_name, urlparse(url).path):
            suffix = Path(candidate).suffix.lower()
            if suffix in _SUPPORTED_EXTENSIONS:
                return suffix
        return ".mp3"

    @staticmethod
    def _sanitize_stem(name: str) -> str:
        stem = Path(str(name or "audio")).stem.strip() or "audio"
        stem = _SAFE_NAME_RE.sub("_", stem)
        stem = re.sub(r"\s+", "_", stem)
        stem = stem.strip("._")
        return stem[:48] or "audio"

    async def _get_message_by_id(self, message_id: int) -> Optional[Message]:
        try:
            response = await nonebot.get_bot().get_msg(message_id=message_id)
            return type_validate_python(Message, response["message"])
        except Exception:
            return None

    def _extract_from_json_payload(self, raw_json: str) -> Optional[dict[str, str]]:
        if not raw_json:
            return None

        direct_url = self._extract_audio_url(raw_json)
        if direct_url:
            return {"url": direct_url, "name": "audio"}

        try:
            payload = json.loads(raw_json)
        except Exception:
            return None

        best_url = ""
        best_name = ""

        def walk(value: Any) -> None:
            nonlocal best_url, best_name
            if best_url:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    if isinstance(child, str):
                        if not best_name and key in _PREFERRED_TITLE_KEYS and child.strip():
                            best_name = child.strip()
                        if key in _PREFERRED_AUDIO_KEYS:
                            matched_url = self._extract_audio_url(child)
                            if matched_url:
                                best_url = matched_url
                                return
                        if not best_url:
                            matched_url = self._extract_audio_url(child)
                            if matched_url:
                                best_url = matched_url
                                return
                    walk(child)
                    if best_url:
                        return
            elif isinstance(value, list):
                for item in value:
                    walk(item)
                    if best_url:
                        return
            elif isinstance(value, str) and not best_url:
                matched_url = self._extract_audio_url(value)
                if matched_url:
                    best_url = matched_url

        walk(payload)
        if not best_url:
            return None
        return {"url": best_url, "name": best_name or "audio"}

    async def _resolve_group_file_segment(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        file_name = str(
            data.get("name")
            or data.get("file_name")
            or data.get("file")
            or data.get("title")
            or "audio"
        )

        file_id = data.get("file_id") or data.get("id")
        busid = data.get("busid")
        if file_id and busid is not None:
            try:
                url_info = await self.group.gateway.get_group_file_url(
                    self.group.group_id,
                    str(file_id),
                    int(busid),
                )
                file_url = str(url_info.get("url") or "")
                if file_url:
                    return {"url": file_url, "name": file_name}
            except Exception:
                pass

        if not self._is_supported_audio_name(file_name):
            return None

        try:
            for group_file in await self.group.get_files():
                if str(group_file.get("file_name") or "") != file_name:
                    continue
                downloaded = await self.group.download_file(group_file)
                if downloaded:
                    return {"path": Path(downloaded), "name": file_name, "cleanup": True}
        except Exception:
            return None
        return None

    async def _resolve_source_from_message(self, message: Message) -> Optional[dict[str, Any]]:
        if not message:
            return None

        for segment in message:
            segment_type = getattr(segment, "type", "")
            segment_data = getattr(segment, "data", {}) or {}

            if segment_type == "music":
                audio_url = str(segment_data.get("audio") or "")
                if audio_url:
                    return {
                        "url": audio_url,
                        "name": str(segment_data.get("title") or "music"),
                    }

            if segment_type == "record":
                file_value = str(segment_data.get("file") or "")
                audio_url = str(segment_data.get("url") or "")
                if audio_url:
                    return {"url": audio_url, "name": Path(audio_url).name or "record"}
                if file_value.startswith(("http://", "https://")):
                    return {"url": file_value, "name": Path(file_value).name or "record"}
                if file_value and Path(file_value).exists():
                    return {"path": Path(file_value), "name": Path(file_value).name}

            if segment_type == "file":
                resolved = await self._resolve_group_file_segment(segment_data)
                if resolved:
                    return resolved

            if segment_type == "json":
                resolved = self._extract_from_json_payload(str(segment_data.get("data") or ""))
                if resolved:
                    return resolved

        plain_text = message.extract_plain_text().strip()
        audio_url = self._extract_audio_url(plain_text)
        if audio_url:
            return {"url": audio_url, "name": Path(urlparse(audio_url).path).name or "audio"}
        return None

    async def _resolve_recent_uploaded_audio(self, user_id: int) -> Optional[dict[str, Any]]:
        try:
            for group_file in await self.group.get_files():
                if int(group_file.get("uploader", 0) or 0) != int(user_id):
                    continue
                file_name = str(group_file.get("file_name") or "")
                if not self._is_supported_audio_name(file_name):
                    continue
                downloaded = await self.group.download_file(group_file)
                if downloaded:
                    return {"path": Path(downloaded), "name": file_name, "cleanup": True}
        except Exception:
            return None
        return None

    async def _download_remote_audio(self, url: str, *, file_name: str = "") -> Path:
        suffix = self._guess_suffix(url=url, file_name=file_name)
        save_path = self.group.temp_path / f"audio2midi_{uuid.uuid4().hex}{suffix}"
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                with save_path.open("wb") as handle:
                    handle.write(await response.read())
        return save_path

    async def _resolve_audio_source(
        self,
        *,
        user_id: int,
        event: Optional[GroupMessageEvent] = None,
        source_url: str = "",
        reply_message_id: Optional[int] = None,
        reply_message_obj: Any = None,
    ) -> Optional[dict[str, Any]]:
        direct_url = self._extract_audio_url(source_url)
        if direct_url:
            return {"url": direct_url, "name": Path(urlparse(direct_url).path).name or "audio"}

        reply_message = None
        if event is not None and getattr(event, "reply", None) and getattr(event.reply, "message", None):
            reply_message = event.reply.message
        elif reply_message_obj is not None:
            reply_message = reply_message_obj
        elif reply_message_id:
            reply_message = await self._get_message_by_id(int(reply_message_id))

        if reply_message is not None:
            resolved = await self._resolve_source_from_message(reply_message)
            if resolved:
                return resolved

        return await self._resolve_recent_uploaded_audio(user_id)

    async def _prepare_audio_file(self, source: dict[str, Any]) -> tuple[Path, bool]:
        source_path = source.get("path")
        if source_path:
            return Path(source_path), bool(source.get("cleanup", False))

        source_url = str(source.get("url") or "")
        if not source_url:
            raise ValueError("未找到可用音频源")

        downloaded = await self._download_remote_audio(source_url, file_name=str(source.get("name") or ""))
        return downloaded, True

    async def _generate_midi_file(
        self,
        audio_path: Path,
        *,
        source_name: str,
        tempo_bpm: int = 120,
        min_note_length: int = 2,
        threshold: float = 0.1,
    ) -> tuple[Path, str, str]:
        stem = self._sanitize_stem(source_name)
        midi_name = f"{stem}.mid"
        midi_path = self.group.temp_path / f"{stem}_{uuid.uuid4().hex}.mid"

        def run_basic_pitch_predict() -> None:
            detector = self._get_basic_pitch_detector()
            detector.predict(
                str(audio_path),
                onset_thresh=0.35,
                frame_thresh=0.25,
                min_note_len=8,
                infer_onsets=True,
                include_pitch_bends=False,
                multiple_pitch_bends=False,
                melodia_trick=True,
                midi_tempo=int(tempo_bpm),
                output_file=str(midi_path),
            )

        def run_librosa_predict() -> None:
            detector = self._get_librosa_detector()
            detector.predict(
                str(audio_path),
                tempo_bpm=int(tempo_bpm),
                min_note_length=int(min_note_length),
                threshold=float(threshold),
                output_file=str(midi_path),
            )

        try:
            await asyncio.to_thread(run_basic_pitch_predict)
            return midi_path, midi_name, "basic_pitch"
        except Exception as exc:
            self.__class__._basic_pitch_init_error = str(exc)
            if midi_path.exists():
                try:
                    midi_path.unlink()
                except OSError:
                    pass

        await asyncio.to_thread(run_librosa_predict)
        return midi_path, midi_name, "librosa"

    async def _upload_midi_file(self, midi_path: Path, midi_name: str) -> None:
        folder = await self.group.get_folder("扒谱结果")
        await self.group.upload_file(midi_path, midi_name, folder)

    async def _transcribe_and_upload(
        self,
        *,
        user_id: int,
        event: Optional[GroupMessageEvent] = None,
        source_url: str = "",
        reply_message_id: Optional[int] = None,
        reply_message_obj: Any = None,
        tempo_bpm: int = 120,
        min_note_length: int = 2,
        threshold: float = 0.1,
    ) -> dict[str, Any]:
        try:
            self._ensure_audio2midi_available()
        except RuntimeError as exc:
            return {"success": False, "message": str(exc)}

        source = await self._resolve_audio_source(
            user_id=user_id,
            event=event,
            source_url=source_url,
            reply_message_id=reply_message_id,
            reply_message_obj=reply_message_obj,
        )
        if not source:
            return {
                "success": False,
                "message": "请回复一条音频/音乐卡片/群文件消息后再使用“扒谱”，或直接提供音频直链。",
            }

        audio_path = None
        midi_path = None
        cleanup_audio = False
        try:
            audio_path, cleanup_audio = await self._prepare_audio_file(source)
            midi_path, midi_name, backend = await self._generate_midi_file(
                audio_path,
                source_name=str(source.get("name") or audio_path.name),
                tempo_bpm=tempo_bpm,
                min_note_length=min_note_length,
                threshold=threshold,
            )
            await self._upload_midi_file(midi_path, midi_name)
            return {
                "success": True,
                "message": "扒谱完成，MIDI 已上传到群文件",
                "data": {
                    "file_name": midi_name,
                    "source_name": str(source.get("name") or audio_path.name),
                    "backend": backend,
                },
            }
        finally:
            if cleanup_audio and audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            if midi_path and Path(midi_path).exists():
                try:
                    Path(midi_path).unlink()
                except OSError:
                    pass

    @service_action(
        cmd="扒谱",
        aliases={"转MIDI", "音频转MIDI"},
        desc="回复音频、音乐卡片或群文件消息，将其转成 MIDI 并上传到群文件",
        need_arg=True,
    )
    async def transcribe_command(self, event: GroupMessageEvent, arg: Message):
        if not self.enabled:
            await self.group.send_msg("扒谱服务未开启")
            return

        source_url = arg.extract_plain_text().strip()
        await self.group.send_msg("正在扒谱，请稍等...（当前优先使用 BasicPitch，首次加载会比较慢）")
        result = await self._transcribe_and_upload(
            user_id=event.user_id,
            event=event,
            source_url=source_url,
        )
        await self.group.send_msg(("✅ " if result["success"] else "❌ ") + result["message"])

    @ai_tool(
        name="audio2midi_transcribe",
        desc=(
            "将音频扒成 MIDI 并上传到群文件。优先用于用户明确要求扒谱、转 MIDI、生成 midi 文件的场景。"
            "如果用户没有给音频直链，可以不传 source_url，工具会优先尝试当前回复消息里的音频或用户最近上传的音频文件。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_url": {
                    "type": "string",
                    "description": "音频直链，可选；如果没有则尝试从回复消息或最近上传文件中解析",
                },
                "reply_message_id": {
                    "type": "integer",
                    "description": "被回复消息的 message_id，可选",
                },
                "tempo_bpm": {
                    "type": "integer",
                    "description": "输出 MIDI 的节拍速度，默认 120",
                    "default": 120,
                },
            },
            "required": [],
        },
        category="audio2midi",
        triggers=["扒谱", "转MIDI", "生成MIDI", "音频转MIDI"],
    )
    async def transcribe_tool(
        self,
        user_id: int,
        group_id: int,
        source_url: str = "",
        reply_message_id: Optional[int] = None,
        tempo_bpm: int = 120,
        **kwargs,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "message": "扒谱服务未开启"}

        return await self._transcribe_and_upload(
            user_id=user_id,
            source_url=source_url,
            reply_message_id=reply_message_id,
            reply_message_obj=kwargs.get("reply_message_obj"),
            tempo_bpm=tempo_bpm,
        )


__all__ = ["Audio2MidiService"]
