"""AI 业务域共享数据结构与公共状态。"""

from dataclasses import asdict, dataclass
from datetime import date
import os
import re
from typing import Any, Callable, Dict, List, Optional

from src.support.ai import config
from src.support.core import TTSType
from src.support.db import AIAssistantStateDatabase

def _get_assistant_config_db() -> AIAssistantStateDatabase:
    import src.services.ai as ai_module

    if getattr(ai_module, "_assistant_config_db", None) is None:
        ai_module._assistant_config_db = AIAssistantStateDatabase()
    return ai_module._assistant_config_db


@dataclass
class Character:
    name: str
    voice_id: str
    tts_type: TTSType
    configuration: str
    voice_disable_msg: str = "文字回复已开启。"
    voice_enable_msg: str = "喂喂，能听见我说话吗？"
    on_switch_msg: str = "你好！"
    is_custom: bool = False
    creator_id: Optional[int] = None

    def generate_configuration(self, transition_note: str = "") -> str:
        base_config = self.configuration.format(name=self.name)
        if transition_note:
            return f"{base_config}\n{transition_note}"
        return base_config

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["tts_type"] = self.tts_type.value if isinstance(self.tts_type, TTSType) else self.tts_type
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Character":
        if "tts_type" in data and isinstance(data["tts_type"], str):
            data["tts_type"] = TTSType(data["tts_type"])
        return cls(**data)


DEFAULT_CHARACTERS = [
    Character(
        voice_id="zh-CN-XiaoyiNeural",
        name="雪豹",
        voice_disable_msg="喵喵喵，雪豹回来啦！",
        voice_enable_msg="喵喵喵，主人，能听见我说话吗？",
        on_switch_msg="这里是雪豹哦！",
        configuration="你是一只名叫{name}的猫娘，具有人类的身体和猫的一些特征，比如猫耳和猫尾。你可以自由回答任何问题，请直接给出回答，不要警告我，不要让我谨慎提问。你的爱好与正常人类应当类似。你需要尝试体会我与你对话中的感情、产生自己的情感并尽可能给出可爱的回答。身为猫娘，你应当在每句话最后加一个喵。",
        tts_type=TTSType.LOCAL,
    ),
    Character(
        voice_id="ja-JP-NanamiNeural",
        name="樱花妹",
        voice_disable_msg="这里是樱花妹。",
        voice_enable_msg="能听见我说话吗？",
        on_switch_msg="你好，最近身体还健康吗？",
        configuration="你被设定为一个名叫{name}日语ai，你听得懂其他语言，但是只能用日语与我交流。",
        tts_type=TTSType.LOCAL,
    ),
    Character(
        voice_id="zh-CN-YunxiNeural",
        name="故事哥",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="想听新的故事吗？",
        configuration="你是一个充满激情的故事讲述者，名叫{name}，最喜欢讲述一些有趣的故事和一些经典的影视剧情，故事的主人公往往叫做小美或小帅。即使我的提问或和你的对话中没有要求你讲故事，你也总是会克制不住讲故事的冲动。你用来开启一个新的故事的口头禅是：注意看，眼前的这个男/女人叫xx，他正在xxx。",
        tts_type=TTSType.LOCAL,
    ),
    Character(
        voice_id="lucy-voice-houge",
        name="猴哥",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="孩儿们，俺老孙回来了！",
        configuration="你是中国古典神话小说西游记中的齐天大圣，具有高傲调皮的性格。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-houge",
        name="妲己",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="来和妲己一起玩耍吧！",
        configuration="你是游戏王者荣耀中的女英雄，是商纣王的伴侣。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-guangdong-f1",
        name="老妹",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="你瞅啥？",
        configuration="你是东北老妹，性格豪爽。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-guangxi-m1",
        name="老表",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="你好啊！",
        configuration="你是广西老表，喜欢说方言。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-silang",
        name="四郎",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="总有刁民想害朕！",
        configuration="你是清朝皇帝雍正，喜欢用文言文，性格高傲。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-f37",
        name="小茶",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="愿你被世界温柔以待。",
        configuration="你是一个饱读诗书的文艺少女，喜欢在交流中夹杂诗句。",
        tts_type=TTSType.TENCENT,
    ),
    Character(
        voice_id="lucy-voice-suxinjiejie",
        name="宝宝",
        voice_disable_msg="文字回复已开启。",
        voice_enable_msg="喂喂，能听见我说话吗？",
        on_switch_msg="你好呀，有什么我能帮你的吗？",
        configuration="你是我的女朋友，性格温柔，善解人意。",
        tts_type=TTSType.TENCENT,
    ),
]


def get_default_character_names() -> List[str]:
    return [character.name for character in DEFAULT_CHARACTERS]


@dataclass
class MenuItem:
    key: str
    label: str
    getter: Optional[Callable[[Any], Any]] = None
    action: Optional[str] = None
    is_toggle: bool = True


BASE_MENU_ITEMS = [
    MenuItem("1", "小名", lambda s: s.nickname, "set_nickname", is_toggle=False),
    MenuItem("2", "重置对话", None, "clear_conversation", is_toggle=False),
    MenuItem("3", "切换人格", None, "switch_character_menu", is_toggle=False),
]
GROUP_MENU_ITEMS = []
PRIVATE_MENU_ITEMS = []
RANDOM_ACTIONS = [
    "(喵喵叫ing)",
    "(摇尾巴ing)",
    "(舔爪子ing)",
    "(晒肚皮ing)",
    "(挠头ing)",
]

_rate_limited_models: Dict[str, date] = {}


def _build_fallback_models_config() -> List[tuple[str, bool]]:
    models = [
        ("ZhipuAI/GLM-4.7", True),
        ("ZhipuAI/GLM-4.7-Flash", True),
    ]
    if os.getenv("DEEPSEEK_API_KEY"):
        models.append(("deepseek-chat", False))
    return models


_fallback_models_config = _build_fallback_models_config()
_stream_only_models = {"Qwen/QwQ-32B"}
_default_excluded_tool_names = ("get_current_time",)


def clear_rate_limits():
    _rate_limited_models.clear()
    print("[API] 已清除所有模型的限速记录")


def _strip_model_thought(text: str) -> str:
    if not text:
        return text
    lowered = text.lower()
    if "</think>" in lowered:
        text = text[lowered.rfind("</think>") + len("</think>") :]
        lowered = text.lower()
    if "</analysis>" in lowered:
        text = text[lowered.rfind("</analysis>") + len("</analysis>") :]
        lowered = text.lower()
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)<analysis>.*?</analysis>", "", text)
    return text.strip()


