from nonebot.adapters.onebot.v11 import MessageSegment, Message
from src.vendors.nonebot_plugin_werewolf.enum import Role, Kind

player_guide = {
    Role.VILLAGER: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🦌 雪豹 · 村民",
        content=Message(
            "❄️ 背景故事：\n"
            "高原的原住民，用敏锐直觉守护族群安全\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 通过推理找出猎豹人\n"
            "▸ 参与集体投票放逐可疑者\n\n"
            "✨ 技能：无"
        )
    ),
    Role.WEREWOLF: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🐆 猎豹人 · 狼人",
        content=Message(
            "🌑 背景故事：\n"
            "月夜下的掠食者，猎枪藏着千年恩怨\n\n"
            "🐾 阵营：猎豹人（狼人）\n\n"
            "🎯 使命：\n"
            "▸ 伪装成雪豹族成员\n"
            "▸ 消灭所有雪豹阵营\n\n"
            "✨ 技能1：暗夜猎杀*n次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「杀害+指定玩家」\n"
            "▸ 效果：目标死亡\n\n"
            "✨ 技能2：阴影低语*n次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「chat+消息内容」\n"
            "▸ 效果：与队友交流"
        )
    ),
    Role.HUNTER: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="💂 牢大 · 猎人",
        content=Message(
            "🏹 背景故事：\n"
            "部落最强战士，绝境中会发动致命肘击\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 在死亡时带走关键目标\n"
            "▸ 帮助好人阵营获胜\n\n"
            "✨ 技能：最后的抗争*1次\n"
            "▸ 使用时机：夜间被杀/放逐阶段\n"
            "▸ 使用方式：「肘击+指定玩家」\n"
            "▸ 效果：目标死亡"
        )
    ),
    Role.SEER: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🔮 训豹师 · 预言家",
        content=Message(
            "🔍 背景故事：\n"
            "能与雪豹灵魂对话的智者，看破一切伪装\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 引导族人避开陷阱\n"
            "▸ 小心隐藏先知身份\n\n"
            "✨ 技能：真视之眼\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「预言+指定玩家」\n"
            "▸ 效果：获知目标阵营"
        )
    ),
    Role.WITCH: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="☁️ 乌云盖雪 · 女巫",
        content=Message(
            "🧪 背景故事：\n"
            "掌握古老药术的巫女，掌中生死的抉择者\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 合理分配解药与毒药\n"
            "▸ 守护关键角色安全\n\n"
            "⏰ 行动：夜间\n\n"
            "✨ 技能1：月露救赎*1次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「治疗+指定玩家」\n"
            "▸ 效果：目标免死\n\n"
            "✨ 技能2：毒雾弥漫*1次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「毒害+指定玩家」\n"
            "▸ 效果：目标死亡"
        )
    ),
    Role.GUARD: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🛡️ 丁真 · 守卫",
        content=Message(
            "🛡️ 背景故事：\n"
            "高原的守护者，用生命缔结防护结界\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 预判狼人刀法路线\n"
            "▸ 保护核心成员存活\n\n"
            "✨ 技能：圣光庇护*n次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「守护+指定玩家」\n"
            "▸ 效果：目标免死"
        )
    ),
    Role.EXPLORER: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="💰 寻宝士 · 特殊",
        content=Message(
            "💎 背景故事：\n"
            "流浪的宝藏猎人，黄金是他的通行证\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 利用财富规避致命伤害\n"
            "▸ 为好人阵营争取优势\n\n"
            "✨ 技能：财富诱惑*1次\n"
            "▸ 使用时机：夜间被狼人杀\n"
            "▸ 使用方式：「贿赂」\n"
            "▸ 效果：被狼人杀害则免死"
        )
    ),
    Role.NERD: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🤪 傻豹 · 白痴",
        content=Message(
            "🎭 背景故事：\n"
            "装疯卖傻的智者，绝境中总能化险为夷\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 通过伪装扰乱狼人判断\n"
            "▸ 吸引火力保护神职\n\n"
            "⏰ 行动：放逐阶段\n\n"
            "✨ 技能：金蝉脱壳*1次\n"
            "▸ 使用时机：黄昏被放逐\n"
            "▸ 使用方式：「自爆」\n"
            "▸ 效果：自身免死，之后无法投票"
        )
    ),
    Role.WHITE_WOLF: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="👑 猎豹人之王 · 白狼王",
        content=Message(
            "🌪️ 背景故事：\n"
            "猎豹人的领袖，掌控风暴的毁灭者\n\n"
            "🐾 阵营：猎豹人（狼人）\n\n"
            "🎯 使命：\n"
            "▸ 精准击杀关键神职\n"
            "▸ 扭转猎豹人阵营劣势\n\n"
            "✨ 技能1：暗夜猎杀*n次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「杀害+指定玩家」\n"
            "▸ 效果：目标死亡\n\n"
            "✨ 技能2：阴影低语*n次\n"
            "▸ 使用时机：夜间\n"
            "▸ 使用方式：「chat+消息内容」\n"
            "▸ 效果：与队友交流\n\n"
            "✨ 技能3：王族之怒*1次\n"
            "▸ 使用时机：发言阶段\n"
            "▸ 使用方式：「自爆+指定玩家」\n"
            "▸ 效果：自身和目标死亡并进入黑夜"
        )
    ),
    Role.RIDER: MessageSegment.node_custom(
        user_id=2967481325,
        nickname="⚔️ 黑豹 · 骑士",
        content=Message(
            "🤺 背景故事：\n"
            "独行的骑士，用决斗捍卫真相\n\n"
            "🐾 阵营：雪豹（好人）\n\n"
            "🎯 使命：\n"
            "▸ 通过决斗揭穿伪装猎豹人\n"
            "▸ 以生命守护阵营胜利\n\n"
            "✨ 技能：生死决斗*1次\n"
            "▸ 使用时机：发言阶段\n"
            "▸ 使用方式：「决斗+指定玩家」\n"
            "▸ 效果：若目标为猎豹人，则目标死亡并进入黑夜，否则自身死亡"
        )
    )
}


werewolf_guide = [
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🌌 雪豹杀指南",
        content=Message(
            "欢迎来到雪域高原的暗夜战场！🐺\n"
            "这里上演着猎豹人与雪豹族的千年对抗..."
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="⚔️ 阵营说明",
        content=Message(
            "❄️ 背景故事：\n"
            "在冰雪覆盖的高原上，两个古老种族为生存而战\n\n"
            f"▫️ {Kind.VILLAGER.value}（好人）\n"
            "▸ 守护家园的和平卫士\n\n"
            f"▫️ {Kind.WEREWOLF.value}（狼人）\n"
            "▸ 潜伏暗影的致命猎手"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🌀 标准循环",
        content=Message(
            "🌙 黑夜 → ☀️ 白天 → 🗳️ 投票 → ❄️ 放逐\n\n"
            "1. 夜晚行动阶段\n"
            "2. 白天发言阶段\n"
            "3. 投票表决阶段\n"
            "4. 放逐执行阶段"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🎖️ 警长竞选(玩家数>=6人)",
        content=Message(
            "📢 指令：\n"
            "▸ 竞选：发送「举手」\n"
            "▸ 退选：发送「弃权」\n\n"
            "👑 警长特权：\n"
            "▸ 归票权 + 1.5票权重\n"
            "▸ 决定发言顺序\n\n"
            "⏰ 时间：首日白天开启"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🗳️ 选举阶段",
        content=Message(
            "📩 指令：\n"
            "▸ 投票：「我投@玩家」\n"
            "▸ 弃权：「弃权」\n\n"
            "⚖️ 规则：\n"
            "▸ 平票则警长空缺\n"
            "▸ 警长指定发言顺序"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🌙 夜幕降临",
        content=Message(
            "👣 行动顺序：\n"
            f"1. {Role.SEER.value}（查验身份）\n"
            f"2. {Role.WEREWOLF.value}（刀人行动）\n"
            f"3. {Role.WITCH.value}（用药选择）\n"
            f"4. {Role.GUARD.value}（守护目标）\n\n"
            "💫 被动触发：\n"
            f"▸ {Role.EXPLORER.value}（被刀时）\n"
            f"▸ {Role.HUNTER.value}（被刀时）"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="💬 高原议事",
        content=Message(
            "✉️ 指令：\n"
            "▸ 结束发言：「完毕」\n\n"
            "📣 发言规则：\n"
            "▸ 按编号顺序发言\n"
            "▸ 警长决定末位总结\n\n"
            "⚡ 特殊行动：\n"
            f"▸ {Role.WHITE_WOLF.value}可发动自爆\n"
            f"▸ {Role.RIDER.value}可发起决斗"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="✅ 神圣投票",
        content=Message(
            "✉️ 指令：\n"
            "▸ 投票：「我投@玩家」\n"
            "▸ 弃权：「弃权」\n\n"
            "⚖️ 规则：\n"
            "▸ 警长票=1.5票\n"
            "▸ 平票无人出局"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="❄️ 雪域放逐",
        content=Message(
            "⏳ 流程：\n"
            "▸ 公布投票结果\n"
            "▸ 最高票者离场\n\n"
            "✨ 技能触发：\n"
            f"▸ {Role.HUNTER.value}（被投出局）\n"
            f"▸ {Role.NERD.value}（被投出局）\n\n"
            "🌌 进入下一黑夜"
        )
    ),
    MessageSegment.node_custom(
        user_id=2967481325,
        nickname="🚀 启程时刻",
        content=Message(
            "❄️ 准备好展开雪域生存之战了吗？\n"
            "使用指令「*雪豹杀启动」开启征程！\n\n"
            "🐺 愿冰雪之神眷顾勇敢者..."
        )
    )
] + [player_guide[role] for role in Role if role not in [Role.CUPID, Role.TRAITOR]]
