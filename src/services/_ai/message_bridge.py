"""AI 群聊上下文的出站消息桥接。"""

from typing import Any, Iterable, Optional

from src.support.core import make_dict

from .message_utils import build_message_record


def _resolve_group_assistant(group_id: int, assistant: Any = None):
    if assistant is not None:
        return assistant

    try:
        from .assistant import get_ai_assistant_manager

        return get_ai_assistant_manager().get_group_server(group_id)
    except Exception:
        return None


def _extract_message_id(message_result: Any) -> Optional[int]:
    if isinstance(message_result, int):
        raw_message_id = message_result
    elif isinstance(message_result, str) and message_result.isdigit():
        raw_message_id = int(message_result)
    elif isinstance(message_result, (list, tuple)):
        for item in message_result:
            extracted = _extract_message_id(item)
            if extracted is not None:
                return extracted
        return None
    elif isinstance(message_result, dict):
        raw_message_id = message_result.get("message_id") or message_result.get("messageId")
    else:
        raw_message_id = getattr(message_result, "message_id", None)
        if raw_message_id is None:
            msg_ids = getattr(message_result, "msg_ids", None)
            if isinstance(msg_ids, (list, tuple)):
                for item in msg_ids:
                    extracted = _extract_message_id(item)
                    if extracted is not None:
                        return extracted
            raw_message_id = getattr(message_result, "raw", None)

    if raw_message_id is None:
        return None

    try:
        return int(raw_message_id)
    except (TypeError, ValueError):
        return None


def record_group_output(
    group_id: int,
    message: Any,
    *,
    message_id: Any = None,
    message_result: Any = None,
    assistant: Any = None,
    remember_only: bool = False,
) -> bool:
    ai_assistant = _resolve_group_assistant(group_id, assistant)
    if ai_assistant is None:
        return False
    normalized_message_id = _extract_message_id(message_id if message_id is not None else message_result)
    if remember_only:
        return ai_assistant.record_assistant_output(
            message_id=normalized_message_id,
            remember_only=True,
        )

    message_record = build_message_record(message)

    return ai_assistant.record_assistant_output(
        message_record.get("text", ""),
        image_urls=message_record.get("image_urls", []),
        video_urls=message_record.get("video_urls", []),
        markers=message_record.get("markers", []),
        message_id=normalized_message_id,
    )


def record_group_user_command(
    group_id: int,
    content: str,
    *,
    assistant: Any = None,
) -> bool:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return False

    ai_assistant = _resolve_group_assistant(group_id, assistant)
    if ai_assistant is None:
        return False

    ai_assistant.add_message(make_dict("user", normalized_content))
    return True


def record_group_media_output(
    group_id: int,
    *,
    text: str = "",
    image_bytes_list: list[bytes] | None = None,
    video_bytes_list: list[bytes] | None = None,
    markers: list[str] | None = None,
    image_suffix: str = ".png",
    video_suffix: str = ".mp4",
    message_id: Any = None,
    message_result: Any = None,
    assistant: Any = None,
    remember_only: bool = False,
) -> bool:
    ai_assistant = _resolve_group_assistant(group_id, assistant)
    if ai_assistant is None:
        return False

    normalized_message_id = _extract_message_id(message_id if message_id is not None else message_result)
    if ai_assistant._has_recorded_assistant_message_id(normalized_message_id):
        return False
    if remember_only:
        return ai_assistant.record_assistant_output(
            message_id=normalized_message_id,
            remember_only=True,
        )

    image_urls = []
    for image_bytes in image_bytes_list or []:
        image_urls.append(
            ai_assistant.cache_media_bytes(
                image_bytes,
                "image",
                suffix=image_suffix,
            )
        )

    video_urls = []
    for video_bytes in video_bytes_list or []:
        video_urls.append(
            ai_assistant.cache_media_bytes(
                video_bytes,
                "video",
                suffix=video_suffix,
            )
        )

    return ai_assistant.record_assistant_output(
        text,
        image_urls=image_urls,
        video_urls=video_urls,
        markers=markers or [],
        message_id=normalized_message_id,
    )


def _iter_history_messages(history_payload: Any) -> Iterable[dict]:
    messages = history_payload.get("messages", []) if isinstance(history_payload, dict) else history_payload
    if not isinstance(messages, (list, tuple)):
        return ()
    return tuple(item for item in messages if isinstance(item, dict))


def _history_sort_key(item: dict) -> tuple[int, int]:
    time_value = item.get("time") or 0
    sequence_value = (
        item.get("message_seq")
        or item.get("real_id")
        or item.get("message_id")
        or item.get("id")
        or 0
    )
    try:
        time_key = int(time_value)
    except (TypeError, ValueError):
        time_key = 0
    try:
        sequence_key = int(sequence_value)
    except (TypeError, ValueError):
        sequence_key = 0
    return time_key, sequence_key


def _extract_sender_id(item: dict) -> Optional[int]:
    sender = item.get("sender") if isinstance(item.get("sender"), dict) else {}
    for raw_value in (
        item.get("user_id"),
        item.get("sender_id"),
        sender.get("user_id"),
        sender.get("id"),
    ):
        if raw_value is None:
            continue
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            continue
    return None


async def sync_recent_group_bot_outputs(group_id: int, self_id: int, *, limit: int = 12) -> int:
    try:
        normalized_self_id = int(self_id)
    except (TypeError, ValueError):
        return 0

    from src.support.group import GroupManager
    from .assistant import get_ai_assistant_manager

    assistant = get_ai_assistant_manager().get_group_server(group_id)

    try:
        group = GroupManager.get_group(group_id)
        history_payload = await group.get_message_history(count=limit)
    except Exception:
        return 0

    recorded_count = 0
    for item in sorted(_iter_history_messages(history_payload), key=_history_sort_key):
        if _extract_sender_id(item) != normalized_self_id:
            continue

        message_payload = item.get("message")
        if message_payload is None:
            message_payload = item.get("content")

        if record_group_output(
            group_id,
            message_payload,
            message_id=item.get("message_id") or item.get("id"),
            assistant=assistant,
        ):
            recorded_count += 1

    return recorded_count


__all__ = [
    "record_group_media_output",
    "record_group_output",
    "record_group_user_command",
    "sync_recent_group_bot_outputs",
]
