"""AI 助手对象与管理器。"""

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PokeNotifyEvent, PrivateMessageEvent

from src.support.ai import SpeechGenerator
from src.support.core import ServerType, make_dict

from .api_runtime import AIAssistantApiRuntimeMixin
from .common import BASE_MENU_ITEMS, MenuItem, PRIVATE_MENU_ITEMS, Character
from .dialog_runtime import AIAssistantBaseRuntimeMixin
from .group_runtime import GroupAIAssistantRuntimeMixin
from .speech_guard import SpeechGuard
from .tool_runtime import AIAssistantToolRuntimeMixin

try:
    from src.vendors.nonebot_plugin_werewolf.player_registry import PlayerRegistry
except Exception:
    PlayerRegistry = None

class AIAssistant(
    AIAssistantBaseRuntimeMixin,
    AIAssistantApiRuntimeMixin,
    AIAssistantToolRuntimeMixin,
    ABC,
):
    """AI 助手基类，提供角色、配置和消息状态。"""

    def __init__(self, server_id: int, data_path: Path, server_type: str):
        self.server_id = server_id
        self.server_type = server_type
        self.config_path = data_path / f"{server_type}_{server_id}.json"

        self._config = self._load_config()
        self.character: Optional[Character] = None
        self.character_dict: Dict[str, Character] = {}
        self.speech_generator: Optional[SpeechGenerator] = None
        self._init_characters()

        self.msg_list: List[Dict] = []
        self.client = self._init_client()

        current_char_name = self._config.get("current_character", "雪豹")
        if current_char_name in self.character_dict:
            self.set_character(self.character_dict[current_char_name])
        else:
            self.set_character(self.character_dict["雪豹"])

    @abstractmethod
    async def reply(self, event: Any):
        pass


class GroupAIAssistant(GroupAIAssistantRuntimeMixin, AIAssistant):
    CHAT_BUFFER_MAX_MESSAGES = 10
    CHAT_BUFFER_MAX_LENGTH = 1500

    def __init__(self, group_id: int, data_path: Path):
        super().__init__(group_id, data_path, ServerType.GROUP.value)
        self.user_reply_history = defaultdict(list)
        self.is_searching = False
        self._chat_buffer: List[Dict[str, Any]] = []
        self._image_registry: Dict[str, str] = {}
        self._image_counter: int = 0
        self._video_registry: Dict[str, str] = {}
        self._video_counter: int = 0
        self._media_cache_dir = data_path / "media_cache" / f"group_{group_id}"
        self._media_cache_dir.mkdir(parents=True, exist_ok=True)
        self._media_cache_files: List[Path] = []
        self._recorded_assistant_message_ids: set[int] = set()
        self._recorded_assistant_message_order: List[int] = []
        self._pending_media_description_tasks: Dict[tuple[str, str, str], asyncio.Task[Any]] = {}
        self._pending_media_description_meta: Dict[tuple[str, str, str], Dict[str, str]] = {}
        self._completed_media_description_results: Dict[tuple[str, str, str], str] = {}
        self._completed_media_description_meta: Dict[tuple[str, str, str], Dict[str, str]] = {}
        self._completed_media_description_order: List[tuple[str, str, str]] = []


class PrivateAIAssistant(AIAssistant):
    def __init__(self, user_id: int, data_path: Path):
        super().__init__(user_id, data_path, ServerType.PRIVATE.value)

    def _get_menu_items(self) -> List[MenuItem]:
        return BASE_MENU_ITEMS + PRIVATE_MENU_ITEMS

    async def reply(self, event: PrivateMessageEvent):
        user_input = event.get_message().extract_plain_text()
        if event.reply:
            user_input = f"对于你所说的：{event.reply.message.extract_plain_text()}，我的回复是：{user_input}"
        self.add_message(make_dict("user", user_input))
        context = {"user_id": event.user_id}
        response = await self.call_api(context)
        await self.send(response)


class AIAssistantManager:
    _data_path = Path("data") / "ai_assistant"

    def __init__(self):
        self.group_dict: Dict[int, GroupAIAssistant] = {}
        self.user_dict: Dict[int, PrivateAIAssistant] = {}
        self._data_path.mkdir(parents=True, exist_ok=True)

    def get_group_server(self, group_id: int) -> GroupAIAssistant:
        if group_id not in self.group_dict:
            self.group_dict[group_id] = GroupAIAssistant(group_id, self._data_path)
        return self.group_dict[group_id]

    def get_private_server(self, private_id: int) -> PrivateAIAssistant:
        if private_id not in self.user_dict:
            self.user_dict[private_id] = PrivateAIAssistant(private_id, self._data_path)
        return self.user_dict[private_id]

    def get_client(self, event):
        if isinstance(event, GroupMessageEvent):
            return self.get_group_server(event.group_id)
        if isinstance(event, PokeNotifyEvent):
            if event.group_id:
                return self.get_group_server(event.group_id)
            return self.get_private_server(event.user_id)
        if isinstance(event, PrivateMessageEvent):
            return self.get_private_server(event.user_id)
        group_id = getattr(event, "group_id", None)
        user_id = getattr(event, "user_id", None)
        if group_id:
            return self.get_group_server(group_id)
        if user_id:
            return self.get_private_server(user_id)
        return None


_shared_ai_manager: Optional[AIAssistantManager] = None


def get_ai_assistant_manager() -> AIAssistantManager:
    global _shared_ai_manager
    if _shared_ai_manager is None:
        _shared_ai_manager = AIAssistantManager()
    return _shared_ai_manager


def extract_image_urls(message: Message) -> List[str]:
    urls = []
    for seg in message:
        if seg.type == "image":
            url = seg.data.get("url") or seg.data.get("file")
            if url:
                urls.append(url)
    return urls


def extract_video_urls(message: Message) -> List[str]:
    urls = []
    for seg in message:
        if seg.type == "video":
            url = seg.data.get("url") or seg.data.get("file")
            if url:
                urls.append(url)
    return urls


def is_player_in_werewolf_game(user_id: int) -> bool:
    if PlayerRegistry is None:
        return False
    try:
        return PlayerRegistry().is_player_in_game(user_id)
    except Exception:
        return False




__all__ = [
    "AIAssistant",
    "AIAssistantManager",
    "GroupAIAssistant",
    "PrivateAIAssistant",
    "SpeechGuard",
    "extract_image_urls",
    "extract_video_urls",
    "get_ai_assistant_manager",
    "is_player_in_werewolf_game",
]
