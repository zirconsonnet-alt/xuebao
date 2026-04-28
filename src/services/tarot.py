import nonebot
import random
from typing import Any, Dict

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from src.support.core import EmptyInput, Services, TarotReadingInput, ai_tool
from src.support.group import Group

from .base import BaseService, check_enabled, config_property, service_action

try:
    from src.vendors.nonebot_plugin_batarot.utils import (
        load_fortune_descriptions,
        load_spread_data,
        load_tarot_data,
        random_tarot_card,
        send_image_as_base64,
        send_image_as_bytes,
    )

    _TAROT_AVAILABLE = True
except Exception:
    _TAROT_AVAILABLE = False

if not _TAROT_AVAILABLE:
    raise ImportError("tarot 依赖不可用")

class TarotService(BaseService):
    service_type = Services.Tarot
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    def __init__(self, group: Group):
        super().__init__(group)

    @staticmethod
    def _normalize_image_bytes(image_payload: Any) -> bytes | None:
        if image_payload is None:
            return None
        if isinstance(image_payload, bytes):
            return image_payload
        if isinstance(image_payload, bytearray):
            return bytes(image_payload)
        if isinstance(image_payload, memoryview):
            return image_payload.tobytes()
        if hasattr(image_payload, "getvalue"):
            return image_payload.getvalue()
        return image_payload

    async def _send_tarot_tool_message(
        self,
        *,
        user_id: int,
        group_id: int,
        reply_text: str,
        image_bytes: bytes | None = None,
        image_base64: str | None = None,
    ) -> Any:
        from src.services._ai.message_bridge import record_group_media_output

        message = Message(reply_text)
        if image_base64:
            message += MessageSegment.image(image_base64)

        bot = self.group.gateway._bot() if hasattr(self.group.gateway, "_bot") else nonebot.get_bot()
        if group_id:
            message_result = await bot.send_group_msg(group_id=group_id, message=message)
            record_group_media_output(
                group_id,
                text=reply_text,
                image_bytes_list=[image_bytes] if image_bytes else [],
                message_result=message_result,
            )
            return message_result
        return await bot.send_private_msg(user_id=user_id, message=message)

    @ai_tool(name="draw_tarot_card", desc="抽一张塔罗牌，显示牌面名称、正位含义、逆位含义和图片。当用户想抽塔罗牌、看塔罗牌、算命、占卜运势时使用。", category="tarot", triggers=["抽塔罗牌", "塔罗牌", "算命", "占卜"], input_model=EmptyInput)
    async def draw_tarot_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        try:
            cards_dict, tarot_urls = load_tarot_data()
            card_name, card_meaning_up, card_meaning_down, card_url = random_tarot_card(cards_dict, tarot_urls)
            reply_text = f"🔮 塔罗牌: {card_name}\n✨ 正位含义: {card_meaning_up}\n🌙 逆位含义: {card_meaning_down}"
            image_bytes = None
            image_base64 = None
            if card_url:
                image_bytes = self._normalize_image_bytes(send_image_as_bytes(card_url))
                image_base64 = send_image_as_base64(card_url)
            await self._send_tarot_tool_message(
                user_id=user_id,
                group_id=group_id,
                reply_text=reply_text,
                image_bytes=image_bytes,
                image_base64=image_base64,
            )
            return {"success": True, "message": f"已为用户抽取塔罗牌「{card_name}」并发送", "data": {"card_name": card_name, "meaning_up": card_meaning_up, "meaning_down": card_meaning_down}}
        except Exception as exc:
            return {"success": False, "message": f"塔罗牌功能出错: {exc}"}

    @ai_tool(name="tarot_fortune", desc="获取今日塔罗牌运势，包含运势指数和运势解读。当用户想知道今日运势、今天运气怎么样时使用。", category="tarot", triggers=["今日运势", "运势", "今天运气"], input_model=EmptyInput)
    async def fortune_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        try:
            cards_dict, tarot_urls = load_tarot_data()
            card_key = random.choice(list(cards_dict.keys()))
            card = cards_dict[card_key]
            card_name = card["name_cn"]
            card_url = tarot_urls.get(f"tarot_{card_key}")
            fortune_score = random.randint(1, 100)
            fortune_descriptions = load_fortune_descriptions()
            score_range = f"{(fortune_score - 1) // 10 * 10 + 1}-{(fortune_score - 1) // 10 * 10 + 10}"
            fortune_description = random.choice(fortune_descriptions[score_range])
            reply_text = f"🎴 今日塔罗牌: {card_name}\n📊 运势指数: {fortune_score}/100\n📝 运势解读: {fortune_description}"
            image_bytes = None
            image_base64 = None
            if card_url:
                image_bytes = self._normalize_image_bytes(send_image_as_bytes(card_url))
                image_base64 = send_image_as_base64(card_url)
            await self._send_tarot_tool_message(
                user_id=user_id,
                group_id=group_id,
                reply_text=reply_text,
                image_bytes=image_bytes,
                image_base64=image_base64,
            )
            return {"success": True, "message": f"已为用户发送今日运势，运势指数 {fortune_score}", "data": {"card_name": card_name, "fortune_score": fortune_score, "fortune_description": fortune_description}}
        except Exception as exc:
            return {"success": False, "message": f"运势功能出错: {exc}"}

    @ai_tool(
        name="tarot_reading",
        desc="解读指定的塔罗牌，获取详细的牌面含义和作者解读。参数可以是塔罗牌名称或留空随机解读一张。",
        parameters={"type": "object", "properties": {"card_name": {"type": "string", "description": "要解读的塔罗牌名称，如「愚者」「魔术师」等，留空则随机选择一张"}}, "required": []},
        category="tarot",
        triggers=["塔罗牌解读", "解读塔罗牌"],
        input_model=TarotReadingInput,
    )
    async def reading_core(self, user_id: int, group_id: int, card_name: str = "", **kwargs) -> Dict[str, Any]:
        try:
            cards_dict, tarot_urls = load_tarot_data()
            card_name_input = card_name.strip()
            if card_name_input:
                specific_card_key = next((key for key, card in cards_dict.items() if card["name_cn"].lower() == card_name_input.lower()), None)
                if not specific_card_key:
                    return {"success": False, "message": f"未找到名为「{card_name_input}」的塔罗牌"}
            else:
                specific_card_key = random.choice(list(cards_dict.keys()))
            card = cards_dict[specific_card_key]
            result_card_name = card["name_cn"]
            card_description = "\n".join(card["description"])
            card_url = tarot_urls.get(f"tarot_{specific_card_key}")
            reply_text = f"📖 塔罗牌解读: {result_card_name}\n\n{card_description}"
            image_bytes = None
            image_base64 = None
            if card_url:
                image_bytes = self._normalize_image_bytes(send_image_as_bytes(card_url))
                image_base64 = send_image_as_base64(card_url)
            await self._send_tarot_tool_message(
                user_id=user_id,
                group_id=group_id,
                reply_text=reply_text,
                image_bytes=image_bytes,
                image_base64=image_base64,
            )
            return {"success": True, "message": f"已发送「{result_card_name}」的详细解读", "data": {"card_name": result_card_name, "description": card_description}}
        except Exception as exc:
            return {"success": False, "message": f"塔罗牌解读功能出错: {exc}"}

    @service_action(
        cmd="塔罗牌",
        desc="抽一张塔罗牌",
        record_ai_context=True,
        ai_context_label="抽一张塔罗牌",
    )
    @check_enabled
    async def draw_tarot(self, event: GroupMessageEvent):
        await self.draw_tarot_core(user_id=event.user_id, group_id=event.group_id)

    @service_action(
        cmd="今日运势",
        desc="查看今日塔罗牌运势",
        record_ai_context=True,
        ai_context_label="查看今日塔罗牌运势",
    )
    @check_enabled
    async def daily_fortune(self, event: GroupMessageEvent):
        await self.fortune_core(user_id=event.user_id, group_id=event.group_id)

    @service_action(
        cmd="塔罗牌解读",
        need_arg=True,
        desc="解读指定塔罗牌",
        record_ai_context=True,
        ai_context_label="解读指定塔罗牌",
        ai_context_include_arg=True,
    )
    @check_enabled
    async def tarot_reading(self, event: GroupMessageEvent, arg: Message):
        await self.reading_core(user_id=event.user_id, group_id=event.group_id, card_name=arg.extract_plain_text().strip() if arg else "")

    @service_action(
        cmd="塔罗占卜",
        desc="进行塔罗牌阵占卜",
        record_ai_context=True,
        ai_context_label="进行塔罗牌阵占卜",
    )
    @check_enabled
    async def tarot_spread(self, bot: Bot, event: GroupMessageEvent):
        from src.services._ai.message_bridge import record_group_output

        spread_data = load_spread_data()
        cards_dict, tarot_urls = load_tarot_data()
        chosen_spread = random.choice(list(spread_data["formations"].keys()))
        spread_info = spread_data["formations"][chosen_spread]
        selected_cards = random.sample(list(cards_dict.keys()), spread_info["cards_num"])
        nodes = [{"type": "node", "data": {"name": "塔罗占卜", "uin": str(event.self_id), "content": f"老师，你抽到的牌阵是：{chosen_spread}\n"}}]
        for card_key in selected_cards:
            card = cards_dict[card_key]
            card_name = card["name_cn"]
            card_url = tarot_urls.get(f"tarot_{card_key}")
            representation = random.choice(spread_info["representations"])
            if random.random() < 0.5:
                position = "顺位"
                card_meaning = card["meaning"]["up"]
            else:
                position = "逆位"
                card_meaning = card["meaning"]["down"]
            card_message = f"{representation}：{card_name}（{position}）\n解释：{card_meaning}\n"
            if card_url:
                try:
                    base64_image = send_image_as_base64(card_url)
                except Exception:
                    base64_image = None
                if base64_image:
                    card_message += MessageSegment.image(base64_image)
                else:
                    card_message += "图片加载失败\n"
            nodes.append({"type": "node", "data": {"name": "塔罗占卜", "uin": str(event.self_id), "content": card_message}})
        try:
            message_result = await bot.send_group_forward_msg(group_id=event.group_id, messages=nodes)
            record_group_output(event.group_id, nodes, message_result=message_result)
        except Exception:
            await self.group.send_msg("消息合并发送失败，逐条发送中…")
            for node in nodes:
                await bot.send(event, node["data"]["content"])
            record_group_output(event.group_id, nodes)

__all__ = ["TarotService"]
