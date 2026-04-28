"""AI 业务域内部实现包。"""

from typing import Optional

from src.support.db import AIAssistantStateDatabase

from . import runtime
from .assistant import (
    AIAssistant,
    AIAssistantManager,
    GroupAIAssistant,
    PrivateAIAssistant,
    SpeechGuard,
    extract_image_urls,
    extract_video_urls,
    get_ai_assistant_manager,
    is_player_in_werewolf_game,
)
from .runtime import (
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
_assistant_config_db: Optional[AIAssistantStateDatabase] = None
_get_assistant_config_db = runtime._get_assistant_config_db

__all__ = [
    "AIAssistant",
    "AIAssistantApiRuntimeMixin",
    "AIAssistantBaseRuntimeMixin",
    "AIAssistantConfigRuntimeMixin",
    "AIAssistantDialogRuntimeMixin",
    "AIAssistantManager",
    "AIAssistantToolRuntimeMixin",
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
    "get_ai_assistant_manager",
    "is_player_in_werewolf_game",
    "runtime",
]
