"""视觉服务命令入口。"""

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.params import CommandArg

from src.services.base import service_action
from src.support.group import wait_for, wait_for_event
from src.support.points import format_points_insufficient_message

from .tools import VisionToolMixin


class VisionCommandMixin(VisionToolMixin):
    _GENERATE_IMAGE_POINTS_COST = 5
    _GENERATE_IMAGE_POINTS_REASON = "vision_generate_image"

    def _consume_generate_image_points(self, event: GroupMessageEvent) -> tuple[bool, str]:
        required_points = int(self._GENERATE_IMAGE_POINTS_COST)
        idempotency_key = (
            f"service_points:{self.group.group_id}:{event.user_id}:"
            f"{self.service_type.value}:generate_image_cmd:message:{int(getattr(event, 'message_id', 0) or 0)}"
        )
        allowed, balance, _already_applied = self.group.db.apply_points_cost(
            user_id=event.user_id,
            cost_points=required_points,
            reason=self._GENERATE_IMAGE_POINTS_REASON,
            ref_type="service_action",
            ref_id=f"{self.service_type.value}:generate_image_cmd",
            idempotency_key=idempotency_key,
        )
        if allowed:
            return True, ""
        return (
            False,
            format_points_insufficient_message(
                required_points=required_points,
                current_balance=balance,
                action_label="根据提示词生成图片",
                custom_message=(
                    "❌ 积分不足，无法生成图片。\n"
                    "当前积分：{current_balance}\n"
                    "所需积分：{required_points}\n"
                    "提示：可以先发送“签到”获取积分。"
                ),
            ),
        )

    @service_action(
        cmd="识别图片",
        desc="识别你发送的图片内容",
        record_ai_context=True,
        ai_context_label="识别图片内容",
    )
    async def describe_image_cmd(self, event: GroupMessageEvent):
        await self.group.send_msg("请发送一张图片（60 秒内），或输入【退出】取消。")
        ev = await wait_for_event(60)
        if not ev:
            await self.group.send_msg("⏱️ 超时，已取消。")
            return

        text = ev.get_message().extract_plain_text().strip()
        if text.lower() == "退出":
            await self.group.send_msg("❌ 已取消")
            return

        image_url = None
        for seg in ev.get_message():
            if seg.type == "image":
                image_url = seg.data.get("url") or seg.data.get("file")
                if image_url:
                    break

        if not image_url:
            await self.group.send_msg("❌ 未检测到图片，请重新发送一张图片。")
            return

        await self.group.send_msg("可选：想重点关注哪些细节？直接回复【跳过】。")
        prompt = await wait_for(20)
        prompt_text = None
        if prompt and prompt.strip() and prompt.strip() != "跳过":
            prompt_text = prompt.strip()

        description = await self._describe_image_api(image_url, prompt_text)
        await self.group.send_msg(description)

    @service_action(
        cmd="生成图片",
        desc="根据提示词生成图片",
        need_arg=True,
        record_ai_context=True,
        ai_context_label="根据提示词生成图片",
        ai_context_include_arg=True,
        points_cost=5,
        points_reason="vision_generate_image",
        points_insufficient_message=(
            "❌ 积分不足，无法生成图片。\n"
            "当前积分：{current_balance}\n"
            "所需积分：{required_points}\n"
            "提示：可以先发送“签到”获取积分。"
        ),
        defer_points_charge=True,
    )
    async def generate_image_cmd(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        prompt = arg.extract_plain_text().strip()
        if not prompt:
            await self.group.send_msg("请输入提示词（60 秒内），或输入【退出】取消。")
            resp = await wait_for(60)
            if not resp or resp.strip().lower() == "退出":
                await self.group.send_msg("❌ 已取消")
                return
            prompt = resp.strip()

        allowed, error_message = self._consume_generate_image_points(event)
        if not allowed:
            await self.group.send_msg(error_message)
            return

        ok, result = await self._generate_image_api(prompt)
        if not ok:
            await self.group.send_msg(f"❌ 图片生成失败：{result}")
            return

        await self.group.send_msg(MessageSegment.image(result))
        await self.group.send_msg(f"✅ 图片已生成：{result}")


__all__ = ["VisionCommandMixin"]
