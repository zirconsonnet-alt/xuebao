import time
from typing import Dict, Optional

from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.core import Services, ai_tool
from src.support.group import run_flow

from .base import BaseService, config_property, service_message

try:
    from src.vendors.nonebot_plugin_auto_emojimix.config import plugin_config
    from src.vendors.nonebot_plugin_auto_emojimix.service import (
        ComboNotFoundError,
        DownloadError,
        UnsupportedEmojiError,
        emoji_mix_service,
    )

    _EMOJIMIX_AVAILABLE = True
except Exception:
    _EMOJIMIX_AVAILABLE = False

if not _EMOJIMIX_AVAILABLE:
    raise ImportError("emojimix 依赖不可用")

_LAST_TRIGGER_AT: dict[str, float] = {}


def _extract_text(event: GroupMessageEvent) -> str:
    return event.get_message().extract_plain_text().strip()


def _match_explicit(text: str) -> Optional[tuple[str, str]]:
    if not plugin_config.emojimix_explicit:
        return None
    if "+" not in text:
        return None
    matched = emoji_mix_service.explicit_pattern.match(text)
    if not matched:
        return None
    return matched.group("code1"), matched.group("code2")


def _match_auto(text: str) -> Optional[tuple[str, str]]:
    if not plugin_config.emojimix_auto:
        return None
    if not text or "+" in text:
        return None
    matched = emoji_mix_service.auto_pattern.search(text)
    if not matched:
        return None
    return matched.group("code1"), matched.group("code2")


def _is_in_cooldown(user_id: int) -> bool:
    cooldown = int(getattr(plugin_config, "emojimix_cd", 0) or 0)
    if cooldown <= 0:
        return False
    user_key = str(user_id)
    last_trigger_at = _LAST_TRIGGER_AT.get(user_key)
    if last_trigger_at is None:
        return False
    return (time.monotonic() - last_trigger_at) < cooldown


def _mark_cooldown(user_id: int) -> None:
    cooldown = int(getattr(plugin_config, "emojimix_cd", 0) or 0)
    if cooldown <= 0:
        return
    _LAST_TRIGGER_AT[str(user_id)] = time.monotonic()


def emojimix_rule(event: GroupMessageEvent) -> bool:
    return _match_explicit(_extract_text(event)) is not None


def auto_emojimix_rule(event: GroupMessageEvent) -> bool:
    return _match_auto(_extract_text(event)) is not None


class EmojimixService(BaseService):
    service_type = Services.Emojimix
    default_config = {"enabled": True}
    enabled = config_property("enabled")

    async def _send_mix_result(
        self,
        *,
        code1: str,
        code2: str,
        silent: bool,
    ) -> None:
        require("nonebot_plugin_alconna")
        from nonebot_plugin_alconna import UniMessage

        try:
            result = await emoji_mix_service.mix_emoji(code1, code2)
        except UnsupportedEmojiError as exc:
            if not silent:
                await UniMessage.text(f"不支持的emoji：{exc.emoji}").send(reply=True)
            return
        except ComboNotFoundError:
            if not silent:
                await UniMessage.text("不支持该emoji组合").send(reply=True)
            return
        except DownloadError:
            if not silent:
                await UniMessage.text("下载表情出错").send(reply=True)
            return

        await UniMessage.image(raw=result).send(reply=not silent)

    @ai_tool(
        name="emojimix",
        desc="根据两个 emoji 生成新的合成表情",
        parameters={
            "type": "object",
            "properties": {
                "emoji1": {"type": "string", "description": "第一个 emoji"},
                "emoji2": {"type": "string", "description": "第二个 emoji"},
                "silent": {"type": "boolean", "description": "是否静默（不回复）", "default": False},
            },
            "required": ["emoji1", "emoji2"],
        },
        category="emojimix",
        triggers=["emoji合成", "表情合成"],
    )
    async def mix_emoji_tool(
        self,
        user_id: int,
        group_id: int,
        emoji1: str,
        emoji2: str,
        silent: bool = False,
    ) -> Dict[str, object]:
        if not self.enabled:
            return {"success": False, "message": "Emoji合成服务未开启"}

        try:
            await self._send_mix_result(code1=emoji1, code2=emoji2, silent=silent)
            return {"success": True, "message": "已发送合成结果"}
        except Exception as exc:
            return {"success": False, "message": f"合成失败: {exc}"}

    @service_message(desc="emoji1+emoji2 合成", rule=emojimix_rule, priority=13, block=True)
    async def handle_emojimix(self, event: GroupMessageEvent):
        if not self.enabled or _is_in_cooldown(event.user_id):
            return

        matched = _match_explicit(_extract_text(event))
        if not matched:
            return

        _mark_cooldown(event.user_id)
        code1, code2 = matched
        await self._send_mix_result(code1=code1, code2=code2, silent=False)

    @service_message(desc="自动 emoji 合成", rule=auto_emojimix_rule, priority=20, block=False)
    async def handle_auto_emojimix(self, event: GroupMessageEvent):
        if not self.enabled or _is_in_cooldown(event.user_id):
            return

        matched = _match_auto(_extract_text(event))
        if not matched:
            return

        _mark_cooldown(event.user_id)
        code1, code2 = matched
        await self._send_mix_result(code1=code1, code2=code2, silent=True)


__all__ = ["EmojimixService"]
