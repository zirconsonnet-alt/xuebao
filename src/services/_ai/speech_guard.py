"""语音违禁词检测辅助。"""

import jieba
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.group import Group, get_name_simple as get_name

bad_words = [
    "傻逼",
    "傻B",
    "脑残",
    "蠢货",
    "蠢B",
    "贱人",
    "贱B",
    "贱货",
    "傻屌",
    "狗屎",
    "脑瘫",
    "操你",
    "你妈",
    "他妈",
    "CNM",
    "NMB",
    "妈逼",
    "妈B",
    "妈死",
    "死妈",
    "狗东西",
    "狗群主",
    "狗管理",
    "狗日",
    "废物",
    "弱智",
]
porn_words = [
    "G片",
    "肏",
    "强奸",
    "强暴",
    "屄",
    "骚货",
    "骚B",
    "鸡巴",
    "兽交",
    "性交",
    "交配",
    "内射",
    "屁股",
    "婊子",
    "阴道",
    "生殖器",
]
politic_words = [
    "港独",
    "港D",
    "台独",
    "台D",
    "习近平",
    "毛泽东",
    "无政府",
    "叛乱",
    "叛变",
    "镇压",
    "统治",
    "离奇死亡",
    "共产党",
    "法轮功",
    "坦克人",
    "64事件",
    "六四",
]


class SpeechGuard:
    def __init__(self, group: Group):
        SpeechGuard._init_jieba()
        self.group = group
        self.black_list = []

    @staticmethod
    def _init_jieba():
        for word in bad_words + porn_words + politic_words:
            jieba.add_word(word)

    async def check(self, event: GroupMessageEvent):
        msg = event.get_message().extract_plain_text().strip()
        user_id = event.user_id
        display_name = await get_name(event)
        words = jieba.lcut(msg)
        if not any(word in (bad_words + porn_words + politic_words) for word in words):
            return
        if user_id not in self.black_list:
            self.black_list.append(user_id)
            try:
                await self.group.delete_msg(event.message_id)
            except Exception:
                pass
            try:
                await self.group.send_msg(
                    f"{display_name}，检测到您使用了违禁词，"
                    f"第二次发现，您会被禁言10分钟。"
                    f"为了维护群聊环境，请勿使用敏感词汇，谢谢"
                )
            except Exception:
                pass
            return
        try:
            await self.group.delete_msg(event.message_id)
        except Exception:
            pass
        try:
            await self.group.ban(user_id=user_id, duration=600)
        except Exception:
            pass
        try:
            await self.group.send_msg(
                f"{display_name}，您已被禁言10分钟。为了维护群聊环境，请勿使用敏感词汇，谢谢！"
            )
        except Exception:
            pass
__all__ = ["SpeechGuard"]
