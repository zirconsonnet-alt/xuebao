from typing import Any, Dict, Tuple

from src.support.core import Services, ToolDefinition


DEFAULT_TOOL_SCHEDULE_CAPABILITY = {
    "enabled": True,
    "mode": "direct",
    "delivery_mode": "render_message",
    "risk_level": "normal",
}

_TOOL_SCHEDULE_CAPABILITIES = {
    "audio2midi_transcribe": {
        "mode": "snapshot",
    },
    "describe_image": {
        "mode": "snapshot",
    },
    "describe_video": {
        "mode": "snapshot",
    },
    "draw_tarot_card": {
        "delivery_mode": "self_output",
    },
    "emojimix": {
        "delivery_mode": "self_output",
    },
    "generate_image": {
        "delivery_mode": "self_output",
    },
    "generate_meme": {
        "delivery_mode": "self_output",
    },
    "multincm_get_song_url": {
        "mode": "snapshot",
        "delivery_mode": "self_output",
    },
    "multincm_upload_song": {
        "mode": "snapshot",
    },
    "schedule_tool_call": {
        "enabled": False,
    },
    "tarot_fortune": {
        "delivery_mode": "self_output",
    },
    "tarot_reading": {
        "delivery_mode": "self_output",
    },
}


def _infer_schedule_mode(
    tool_override: Dict[str, Any],
    *,
    tool: ToolDefinition | None = None,
) -> str:
    explicit_mode = str(tool_override.get("mode") or "").strip().lower()
    if explicit_mode:
        return explicit_mode

    if tool and str(tool.category or "").strip().lower() == "service":
        service_name = str(tool.name or "")
        if service_name.startswith(f"{Services.Vote.value}_"):
            return "event_only"

    return str(DEFAULT_TOOL_SCHEDULE_CAPABILITY.get("mode") or "direct")


def get_tool_schedule_capability(
    tool_name: str,
    *,
    tool: ToolDefinition | None = None,
) -> Dict[str, Any]:
    capability = dict(DEFAULT_TOOL_SCHEDULE_CAPABILITY)
    tool_override = dict(_TOOL_SCHEDULE_CAPABILITIES.get(str(tool_name), {}))
    capability.update(tool_override)
    capability["mode"] = _infer_schedule_mode(tool_override, tool=tool)
    if tool and (tool.require_admin or tool.require_owner):
        capability["risk_level"] = "protected"
    return capability


async def _prepare_multincm_schedule_arguments(
    tool_name: str,
    tool_args: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[Dict[str, Any] | None, str]:
    group_id = int(context.get("group_id") or 0)
    if group_id <= 0:
        return None, "无法获取群ID，当前无法创建定时点歌任务"

    from src.services.registry import service_manager

    service = await service_manager.get_service(group_id, Services.Multincm)
    return await service.prepare_schedule_tool_args(
        tool_name=tool_name,
        tool_args=tool_args,
        context=context,
    )


async def prepare_tool_arguments_for_schedule(
    tool_name: str,
    tool_args: Dict[str, Any] | None,
    context: Dict[str, Any] | None,
    *,
    tool: ToolDefinition | None = None,
) -> Tuple[Dict[str, Any] | None, str]:
    args = dict(tool_args or {})
    context = context or {}
    capability = get_tool_schedule_capability(tool_name, tool=tool)

    if not capability.get("enabled", True):
        return None, f"工具 {tool_name} 暂不支持递归定时调用"

    mode = str(capability.get("mode") or "direct").strip().lower()
    if mode == "event_only":
        return None, f"工具 {tool_name} 依赖实时消息事件，当前不支持直接创建定时任务"

    if tool_name == "describe_image":
        image_id = str(args.get("image_id") or "").strip()
        image_registry = dict(context.get("image_registry") or {})
        image_url = str(args.get("_resolved_image_url") or image_registry.get(image_id) or "").strip()
        if not image_url:
            return None, f"未找到图片 {image_id}，当前无法创建定时图片分析任务"
        args["_resolved_image_url"] = image_url
        return args, ""

    if tool_name == "describe_video":
        video_id = str(args.get("video_id") or "").strip()
        video_registry = dict(context.get("video_registry") or {})
        video_url = str(args.get("_resolved_video_url") or video_registry.get(video_id) or "").strip()
        if not video_url:
            return None, f"未找到视频 {video_id}，当前无法创建定时视频分析任务"
        args["_resolved_video_url"] = video_url
        return args, ""

    if tool_name == "audio2midi_transcribe":
        source_url = str(args.get("source_url") or "").strip()
        reply_message_id = args.get("reply_message_id")
        if reply_message_id is None:
            reply_message_id = context.get("reply_message_id")
        if source_url:
            return args, ""
        if reply_message_id:
            args["reply_message_id"] = int(reply_message_id)
            return args, ""
        return None, "扒谱定时任务需要音频直链，或在创建时明确回复一条带音频的消息"

    if tool_name in {"multincm_get_song_url", "multincm_upload_song"}:
        return await _prepare_multincm_schedule_arguments(tool_name, args, context)

    if mode == "snapshot":
        return None, f"工具 {tool_name} 需要先固化上下文参数，当前暂不支持直接定时"

    return args, ""
