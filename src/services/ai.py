"""AI 服务实现与公开入口。"""

from typing import Optional

from src.support.core import Services
from src.support.db import AIAssistantStateDatabase
from src.support.group import run_flow

from src.services.base import BaseService, config_property, service_action
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
    get_ai_assistant_manager,
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
        "rate_limit_per_hour": config.default_rate_limit_per_hour,
        "thinking_enable": False,
        "group_mode": True,
    }
    settings_schema = [
        {"key": "random_reply_enabled", "title": "随机回复", "description": "控制 AI 是否会进行随机主动回复。", "type": "bool", "group": "回复策略"},
        {"key": "keyword_reply_enabled", "title": "关键词回复", "description": "控制 AI 是否根据关键词触发回复。", "type": "bool", "group": "回复策略"},
        {"key": "group_mode", "title": "群聊模式", "description": "控制 AI 是否以群聊模式处理当前会话。", "type": "bool", "group": "回复策略"},
        {"key": "voice_enable", "title": "语音能力", "description": "允许 AI 发送或处理语音相关能力。", "type": "bool", "group": "能力开关"},
        {"key": "music_enable", "title": "音乐能力", "description": "允许 AI 处理音乐相关能力。", "type": "bool", "group": "能力开关"},
        {"key": "tools_enable", "title": "工具调用", "description": "控制 AI 是否允许调用工具。", "type": "bool", "group": "能力开关"},
        {"key": "thinking_enable", "title": "思考模式", "description": "控制 AI 是否启用思考模式。", "type": "bool", "group": "能力开关"},
        {"key": "rate_limit_enable", "title": "限频开关", "description": "控制 AI 是否启用群内限频。", "type": "bool", "group": "限频设置"},
        {"key": "rate_limit_per_hour", "title": "每小时上限", "description": "设置群内每小时允许触发 AI 的次数。", "type": "int", "group": "限频设置", "min_value": 1, "max_value": 999},
    ]
    enabled = config_property("enabled")
    random_reply_enabled = config_property("random_reply_enabled")
    keyword_reply_enabled = config_property("keyword_reply_enabled")
    voice_enable = config_property("voice_enable")
    music_enable = config_property("music_enable")
    tools_enable = config_property("tools_enable")
    rate_limit_enable = config_property("rate_limit_enable")
    rate_limit_per_hour = config_property("rate_limit_per_hour")
    thinking_enable = config_property("thinking_enable")
    group_mode = config_property("group_mode")

    _ai_manager = None

    def __init__(self, group):
        super().__init__(group)
        if AIService._ai_manager is None:
            AIService._ai_manager = get_ai_assistant_manager()

    def get_ai_assistant(self, event):
        return self._ai_manager.get_client(event)

    @service_action(cmd="AI助手服务")
    async def ai_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ AI助手服务未开启！")
            return
        routes = {
            "1": self.switch_character,
            "2": self.reset_conversation,
        }
        flow = {
            "title": "欢迎使用AI助手服务",
            "subtitle": "这里放的是群内 AI 助手的基础管理操作。",
            "text": (
                "请选择以下操作：\n"
                "1. 切换人格\n"
                "2. 重置对话\n\n"
                "输入【序号】或【指令】"
            ),
            "template": "service_menu",
            "badges": [
                {"text": "回复序号或命令", "tone": "accent"},
                {"text": "AI 对话配置", "tone": "success"},
            ],
            "sections": [
                {
                    "title": "可用操作",
                    "description": "切换人格会影响后续回复风格，重置对话会清空上下文。",
                    "columns": 1,
                    "items": [
                        {
                            "index": "1",
                            "title": "切换人格",
                            "description": "切换当前群 AI 的角色设定。",
                            "meta": "回复 1 执行",
                            "status": "管理",
                            "status_tone": "accent",
                        },
                        {
                            "index": "2",
                            "title": "重置对话",
                            "description": "清空当前群 AI 的对话历史。",
                            "meta": "回复 2 执行",
                            "status": "重置",
                            "status_tone": "warning",
                        },
                    ],
                }
            ],
            "hint": "输入【序号】或【指令】",
            "routes": routes,
        }
        await run_flow(self.group, flow)


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
    "get_ai_assistant_manager",
    "is_player_in_werewolf_game",
    "runtime",
]
