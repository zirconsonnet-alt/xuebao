"""AI 消息桥接用的纯工具函数。"""

import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote

from nonebot.adapters.onebot.v11 import Message, MessageSegment


_HTTP_URL_PREFIXES = ("http://", "https://", "data:")


def to_file_uri(path: str | Path) -> str:
    resolved = Path(path).resolve(strict=False).as_posix()
    if re.match(r"^[A-Za-z]:/", resolved):
        return f"file:///{resolved}"
    return f"file://{resolved}"


def resolve_local_media_path(value: str | None) -> Optional[Path]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    lower_value = raw_value.lower()
    if lower_value.startswith(_HTTP_URL_PREFIXES):
        return None

    if lower_value.startswith("file://"):
        raw_value = unquote(raw_value[7:])
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw_value):
            raw_value = raw_value[1:]

    return Path(raw_value)


def _iter_message_segments(payload: Any) -> Iterable[MessageSegment]:
    if payload is None:
        return

    if isinstance(payload, Message):
        for segment in payload:
            yield segment
        return

    if isinstance(payload, MessageSegment):
        yield payload
        return

    if isinstance(payload, str):
        yield MessageSegment.text(payload)
        return

    if isinstance(payload, dict):
        if "message" in payload:
            yield from _iter_message_segments(payload.get("message"))
            return

        if "content" in payload and "type" not in payload:
            yield from _iter_message_segments(payload.get("content"))
            return

        segment_type = payload.get("type")
        if segment_type:
            segment_data = payload.get("data")
            if not isinstance(segment_data, dict):
                segment_data = {key: value for key, value in payload.items() if key != "type"}
            yield MessageSegment(segment_type, segment_data)
            return

        text_value = payload.get("text")
        if text_value:
            yield MessageSegment.text(str(text_value))
        return

    if isinstance(payload, (list, tuple, set)):
        for item in payload:
            yield from _iter_message_segments(item)
        return

    try:
        message = Message(payload)
    except Exception:
        yield MessageSegment.text(str(payload))
        return

    yield from _iter_message_segments(message)


def _append_unique(items: List[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text or text in items:
        return
    items.append(text)


def build_message_record(message: Any) -> Dict[str, List[str] | str]:
    text_parts: List[str] = []
    image_urls: List[str] = []
    video_urls: List[str] = []
    markers: List[str] = []

    for segment in _iter_message_segments(message):
        segment_type = getattr(segment, "type", "")
        segment_data = dict(getattr(segment, "data", {}) or {})

        if segment_type == "text":
            _append_unique(text_parts, segment_data.get("text"))
            continue

        if segment_type == "at":
            target = segment_data.get("qq")
            if target and str(target) != "all":
                _append_unique(text_parts, f"@{target}")
            continue

        if segment_type == "image":
            _append_unique(image_urls, segment_data.get("url") or segment_data.get("file"))
            continue

        if segment_type == "video":
            _append_unique(video_urls, segment_data.get("url") or segment_data.get("file"))
            continue

        if segment_type in {"record", "audio"}:
            markers.append("[语音]")
            continue

        if segment_type == "file":
            file_name = segment_data.get("name") or segment_data.get("file")
            markers.append(f"[文件:{file_name}]" if file_name else "[文件]")
            continue

        if segment_type == "share":
            share_text = " ".join(
                str(part).strip()
                for part in (
                    segment_data.get("title"),
                    segment_data.get("content"),
                    segment_data.get("url"),
                )
                if str(part or "").strip()
            )
            _append_unique(text_parts, share_text)
            _append_unique(image_urls, segment_data.get("image"))
            continue

        if segment_type == "node":
            nested_content = segment_data.get("content")
            if nested_content is not None:
                nested_record = build_message_record(nested_content)
                for text in nested_record["text"].split("\n"):
                    _append_unique(text_parts, text)
                for url in nested_record["image_urls"]:
                    _append_unique(image_urls, url)
                for url in nested_record["video_urls"]:
                    _append_unique(video_urls, url)
                for marker in nested_record["markers"]:
                    _append_unique(markers, marker)
            continue

        if segment_type == "forward":
            markers.append("[转发消息]")
            continue

        if segment_type == "json":
            markers.append("[卡片消息]")
            continue

    text = " ".join(part.strip() for part in text_parts if part.strip()).strip()
    return {
        "text": text,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "markers": markers,
    }


__all__ = [
    "build_message_record",
    "resolve_local_media_path",
    "to_file_uri",
]
