"""AI 服务实现与公开入口。"""

from typing import Optional

from src.support.core import Services
from src.support.db import AIAssistantStateDatabase
from src.support.group import run_flow

from ._ai import runtime
from ._ai.ai_service_actions import AIServiceActionMixin
from ._ai.ai_service_handlers import AIServiceHandlerMixin
from ._ai.assistant import (
    AIAssistant,
    AIAssistantManager,
    GroupAIAssistant,
    PrivateAIAssistant,
    SpeechGuard,
    extract_image_urls,
    extract_video_urls,
    is_player_in_werewolf_game,
)
from ._ai.runtime import (
    AIAssistantApiRuntimeMixin,
    AIAssistantBaseRuntimeMixin,
    AIAssistantConfigRuntimeMixin,
    AIAssistantDialogRuntimeMixin,
    AIAssistantToolRuntimeMixin,
    BASE_MENU_ITEMS,
    Character,
    DEFAULT_CHARACTERS,
    GROUP_MENU_ITEMS,
    GroupAIAssistantRuntimeMixin,
    MenuItem,
    PRIVATE_MENU_ITEMS,
    clear_rate_limits,
    config,
    get_default_character_names,
)
from .base import BaseService, config_property

_assistant_config_db: Optional[AIAssistantStateDatabase] = None
_get_assistant_config_db = runtime._get_assistant_config_db


class AIService(AIServiceHandlerMixin, AIServiceActionMixin, BaseService):
    service_type = Services.AI
    service_toggle_name = "AI服务"
    default_config = {
        "enabled": False,
        "random_reply_enabled": True,
        "keyword_reply_enabled": True,
        "voice_enable": True,
        "music_enable": True,
        "tools_enable": True,
        "rate_limit_enable": True,
        "thinking_enable": False,
        "group_mode": True,
    }
    enabled = config_property("enabled")
    random_reply_enabled = config_property("random_reply_enabled")
    keyword_reply_enabled = config_property("keyword_reply_enabled")
    voice_enable = config_property("voice_enable")
    music_enable = config_property("music_enable")
    tools_enable = config_property("tools_enable")
    rate_limit_enable = config_property("rate_limit_enable")
    thinking_enable = config_property("thinking_enable")
    group_mode = config_property("group_mode")

    _ai_manager = None

    def __init__(self, group):
        super().__init__(group)
        if AIService._ai_manager is None:
            AIService._ai_manager = AIAssistantManager()

    def get_ai_assistant(self, event):
        return self._ai_manager.get_client(event)


__all__ = [
    "AIAssistant",
    "AIAssistantApiRuntimeMixin",
    "AIAssistantBaseRuntimeMixin",
    "AIAssistantConfigRuntimeMixin",
    "AIAssistantDialogRuntimeMixin",
    "AIAssistantManager",
    "AIAssistantToolRuntimeMixin",
    "AIService",
    "BASE_MENU_ITEMS",
    "Character",
    "DEFAULT_CHARACTERS",
    "GROUP_MENU_ITEMS",
    "GroupAIAssistant",
    "GroupAIAssistantRuntimeMixin",
    "MenuItem",
    "PRIVATE_MENU_ITEMS",
    "PrivateAIAssistant",
    "SpeechGuard",
    "clear_rate_limits",
    "config",
    "extract_image_urls",
    "extract_video_urls",
    "get_default_character_names",
    "is_player_in_werewolf_game",
    "runtime",
]
