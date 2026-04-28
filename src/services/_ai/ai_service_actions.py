"""AI 服务命令动作。"""

import json
from typing import Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.services.base import service_action

from .ai_character_actions import AICharacterActionMixin
from .ai_control_actions import AIControlActionMixin


class AIServiceActionMixin(AICharacterActionMixin, AIControlActionMixin):
    @staticmethod
    def _shorten_text(content: Any, limit: int = 72) -> str:
        text = " ".join(str(content or "").split())
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)]}..."

    def _build_ai_context_snapshot(self, ai_assistant) -> dict:
        msg_list = list(getattr(ai_assistant, "msg_list", []) or [])
        image_registry = dict(getattr(ai_assistant, "_image_registry", {}) or {})
        video_registry = dict(getattr(ai_assistant, "_video_registry", {}) or {})
        pending_meta = getattr(ai_assistant, "_pending_media_description_meta", {}) or {}
        pending_items = []
        for meta in pending_meta.values():
            if not isinstance(meta, dict):
                continue
            pending_items.append(
                {
                    "media_type": str(meta.get("media_type", "")),
                    "media_id": str(meta.get("media_id", "")),
                    "prompt": str(meta.get("prompt", "")),
                }
            )

        black_list = getattr(ai_assistant, "black_list", None)
        if isinstance(black_list, set):
            black_list = sorted(black_list)
        elif isinstance(black_list, (list, tuple)):
            black_list = list(black_list)
        else:
            black_list = []

        return {
            "assistant": {
                "server_type": getattr(ai_assistant, "server_type", ""),
                "server_id": getattr(ai_assistant, "server_id", 0),
                "character": getattr(getattr(ai_assistant, "character", None), "name", ""),
            },
            "service_config": {
                "enabled": bool(getattr(self, "enabled", False)),
                "random_reply_enabled": bool(getattr(self, "random_reply_enabled", False)),
                "keyword_reply_enabled": bool(getattr(self, "keyword_reply_enabled", False)),
                "voice_enable": bool(getattr(self, "voice_enable", False)),
                "music_enable": bool(getattr(self, "music_enable", False)),
                "tools_enable": bool(getattr(self, "tools_enable", False)),
                "rate_limit_enable": bool(getattr(self, "rate_limit_enable", False)),
                "rate_limit_per_hour": getattr(self, "rate_limit_per_hour", 0),
                "thinking_enable": bool(getattr(self, "thinking_enable", False)),
                "group_mode": bool(getattr(self, "group_mode", False)),
            },
            "msg_count": len(msg_list),
            "last_messages": [
                {
                    "role": str(item.get("role", "")),
                    "content": str(item.get("content", "")),
                }
                for item in msg_list[-6:]
                if isinstance(item, dict)
            ],
            "image_count": len(image_registry),
            "image_registry": image_registry,
            "video_count": len(video_registry),
            "video_registry": video_registry,
            "pending_media_task_count": len(pending_items),
            "pending_media_tasks": pending_items,
            "black_list": black_list,
        }

    def _build_ai_context_summary(self, snapshot: dict) -> str:
        assistant_info = snapshot.get("assistant", {})
        lines = [
            "AI上下文已打印到后台。",
            f"角色：{assistant_info.get('character') or '未设置'}",
            f"历史消息：{snapshot.get('msg_count', 0)} 条",
            f"图片登记：{snapshot.get('image_count', 0)} 个",
            f"视频登记：{snapshot.get('video_count', 0)} 个",
            f"待描述任务：{snapshot.get('pending_media_task_count', 0)} 个",
        ]

        recent_messages = snapshot.get("last_messages", [])[-3:]
        if recent_messages:
            lines.append("最近消息：")
            for item in recent_messages:
                role = str(item.get("role", "") or "unknown")
                content = self._shorten_text(item.get("content", ""), limit=54) or "[空]"
                lines.append(f"- {role}: {content}")

        return "\n".join(lines)

    @staticmethod
    def _print_ai_context_snapshot(snapshot: dict):
        assistant_info = snapshot.get("assistant", {})
        print(
            "[AIService] context_snapshot "
            f"group_id={assistant_info.get('server_id', 0)} "
            f"msg_count={snapshot.get('msg_count', 0)} "
            f"image_count={snapshot.get('image_count', 0)} "
            f"video_count={snapshot.get('video_count', 0)} "
            f"pending_media_task_count={snapshot.get('pending_media_task_count', 0)}"
        )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))

    @staticmethod
    def _extract_message_id(message_result: Any) -> int | None:
        if isinstance(message_result, dict):
            raw_message_id = message_result.get("message_id") or message_result.get("messageId")
        else:
            raw_message_id = getattr(message_result, "message_id", None)
        if raw_message_id is None:
            return None
        try:
            return int(raw_message_id)
        except (TypeError, ValueError):
            return None

    async def _send_debug_summary(
        self,
        event: GroupMessageEvent,
        message: str,
        ai_assistant=None,
        bot: Any = None,
    ):
        try:
            runtime_bot = bot
            if ai_assistant is not None and hasattr(ai_assistant, "_get_runtime_bot"):
                runtime_bot = ai_assistant._get_runtime_bot(bot)
            if runtime_bot is not None:
                message_result = await runtime_bot.send_group_msg(group_id=event.group_id, message=message)
                normalized_message_id = self._extract_message_id(message_result)
                if (
                    normalized_message_id is not None
                    and ai_assistant is not None
                    and hasattr(ai_assistant, "_remember_recorded_assistant_message_id")
                ):
                    ai_assistant._remember_recorded_assistant_message_id(normalized_message_id)
                return
        except Exception:
            pass
        try:
            await self.group.send_msg(message)
        except Exception:
            pass

    @service_action(cmd="切换人格", desc="切换AI人格角色", tool_callable=True)
    async def switch_character(self, event: GroupMessageEvent):
        await self.get_ai_assistant(event).switch_character_menu()

    @service_action(cmd="重置对话", desc="清空对话历史", tool_callable=True)
    async def reset_conversation(self, event: GroupMessageEvent):
        await self.get_ai_assistant(event).clear_conversation()

    @service_action(cmd="AI上下文", aliases={"AI调试", "test"}, desc="查看当前群聊AI上下文快照")
    async def print_message_log(self, event: GroupMessageEvent, bot: Any = None):
        ai_assistant = self.get_ai_assistant(event)
        snapshot = self._build_ai_context_snapshot(ai_assistant)
        self._print_ai_context_snapshot(snapshot)
        await self._send_debug_summary(
            event,
            self._build_ai_context_summary(snapshot),
            ai_assistant=ai_assistant,
            bot=bot,
        )

__all__ = ["AIServiceActionMixin"]
