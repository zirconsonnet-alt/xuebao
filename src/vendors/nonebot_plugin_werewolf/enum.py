from enum import Enum


# 玩家信息存放目录
data_dir = r'data\nonebot_plugins_werewolf\'werewolf.db'


# 玩家职业设置（使用枚举）
class Role(Enum):
    VILLAGER = "雪豹(村民)"
    WEREWOLF = "猎豹人(狼人)"
    SEER = "训豹师(预言家)"
    WITCH = "乌云盖雪(女巫)"
    HUNTER = "牢大(猎人)"
    GUARD = "丁真(守卫)"
    NERD = "傻豹(白痴)"
    EXPLORER = "寻宝士(特殊)"
    TRAITOR = '狼奸(特殊)'
    WHITE_WOLF = '猎豹人之王(白狼王)'
    CUPID = '丘比特(特殊)'
    RIDER = '黑豹(骑士)'


class Kind(Enum):
    VILLAGER = f'雪豹阵营'
    WEREWOLF = f'猎豹人阵营'
    CUPID = f'丘比特阵营'


class Phase(Enum):
    BEFORE_ELECTION = '选举前'
    ELECTION = '选举'
    NIGHT = "夜晚"
    DAWN = "凌晨"
    DAY = "白天"
    DUSK = "黄昏"
    MORNING = '早晨'


class Mode(Enum):
    CLASSIC = "经典（女巫）模式"
    HUNTER = "牢大（猎人）模式"
    GUARD = "丁真（守卫）模式"
    RIDER = "黑豹（骑士）模式"
    SUPER_HUNTER = '超级牢大模式'


class Arg(Enum):
    TARGET_PLAYER = 'target_player'
    TARGET_PLAYERS = 'target_players'
    RAW_MESSAGE = 'raw_message'
    CHAT_ROOM = 'chat_room'
    PHASE = 'phase'


class MessageType(Enum):
    GROUP_MESSAGE = 0
    PRIVATE_MESSAGE = 1


role_emojis = {
    Role.VILLAGER: "🐆",
    Role.WEREWOLF: "🥷",
    Role.SEER: "🔮",
    Role.WITCH: "🧪",
    Role.HUNTER: "💪",
    Role.GUARD: "🛡️",
    Role.NERD: "🤓",
    Role.EXPLORER: "🧭",
    Role.TRAITOR: "🐺",
    Role.WHITE_WOLF: "🥷👑",
    Role.CUPID: "💘",
    Role.RIDER: "⚔️",
}
