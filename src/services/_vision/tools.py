"""视觉工具方法。"""

import asyncio
from typing import Any, Awaitable, Callable, Dict

import aiohttp
from nonebot_plugin_alconna import UniMessage

from src.support.core import (
    DescribeImageInput,
    DescribeUserAvatarInput,
    DescribeVideoInput,
    GenerateImageInput,
    ai_tool,
)
from src.support.group import Group

from .api import VisionApiMixin


class VisionToolMixin(VisionApiMixin):
    async def _send_media_analysis_feedback(self, ai_assistant: Any, media_type: str):
        if not ai_assistant or not hasattr(ai_assistant, "send_text"):
            return

        media_label = "图片" if media_type == "image" else "视频"
        if media_type == "video":
            feedback = f"正在分析{media_label}内容，可能需要一点时间，请稍等。"
        else:
            feedback = f"正在分析{media_label}内容，请稍等。"

        try:
            await ai_assistant.send_text(feedback)
        except Exception:
            pass

    async def _describe_media_with_pending_task(
        self,
        *,
        ai_assistant: Any,
        media_type: str,
        media_id: str,
        media_url: str,
        prompt: str,
        describe_func: Callable[[str, str | None], Awaitable[str]],
    ) -> str:
        required_methods = (
            "build_media_description_key",
            "get_pending_media_description_task",
            "set_pending_media_description_task",
            "clear_pending_media_description_task",
        )
        normalized_prompt = (prompt or "").strip()
        prompt_value = normalized_prompt or None

        if not ai_assistant or not all(hasattr(ai_assistant, method) for method in required_methods):
            return await describe_func(media_url, prompt_value)

        task_key = ai_assistant.build_media_description_key(media_type, media_url, normalized_prompt)
        if hasattr(ai_assistant, "get_completed_media_description"):
            cached_result = ai_assistant.get_completed_media_description(task_key)
            if cached_result:
                return cached_result

        pending_task = ai_assistant.get_pending_media_description_task(task_key)
        if pending_task:
            return await pending_task

        async def _runner():
            return await describe_func(media_url, prompt_value)

        task = asyncio.create_task(_runner(), name=f"vision_{media_type}_{media_id or 'media'}")
        ai_assistant.set_pending_media_description_task(
            task_key,
            task,
            media_type=media_type,
            media_id=media_id,
            prompt=normalized_prompt,
        )
        try:
            await self._send_media_analysis_feedback(ai_assistant, media_type)
            result = await task
            if hasattr(ai_assistant, "set_completed_media_description"):
                ai_assistant.set_completed_media_description(
                    task_key,
                    result,
                    media_type=media_type,
                    media_id=media_id,
                    prompt=normalized_prompt,
                )
            return result
        finally:
            ai_assistant.clear_pending_media_description_task(task_key)

    @ai_tool(
        name="describe_user_avatar",
        desc="获取并描述指定用户的QQ头像。当用户请求查看、描述某人的头像时使用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "要查看头像的用户QQ号，不填则查看当前说话用户的头像",
                },
                "prompt": {
                    "type": "string",
                    "description": "可选的自定义提示词，用于指定想了解头像的哪些方面，如'描述这个人的表情'",
                },
            },
            "required": [],
        },
        category="vision",
        triggers=["看头像", "查看头像", "描述头像", "头像是什么"],
        input_model=DescribeUserAvatarInput,
    )
    async def describe_avatar_core(
        self,
        user_id: int,
        group_id: int,
        prompt: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        avatar_url = await Group.get_user_img(user_id)
        if not prompt:
            prompt = "请描述这个QQ头像的内容，包括主要元素、风格、颜色等，不超过100字。"
        description = await self._describe_image_api(avatar_url, prompt)
        return {
            "success": True,
            "message": description,
            "data": {
                "user_id": user_id,
                "avatar_url": avatar_url,
                "description": description,
            },
        }

    @ai_tool(
        name="describe_image",
        desc="获取群聊中图片的内容描述。当群聊记录或用户消息中包含图片标记（如 [图片:img_001]），且需要了解图片内容时调用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "image_id": {
                    "type": "string",
                    "description": "图片标识符，如 img_001、img_002 等",
                },
                "prompt": {
                    "type": "string",
                    "description": "可选的自定义提示词，用于指定想了解图片的哪些方面",
                },
            },
            "required": ["image_id"],
        },
        category="vision",
        triggers=["查看图片", "看图片", "图片内容"],
        input_model=DescribeImageInput,
    )
    async def describe_image_core(
        self,
        user_id: int,
        group_id: int,
        image_id: str = "",
        prompt: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        if not image_id:
            return {"success": False, "message": "未提供图片标识符"}

        image_registry = kwargs.get("image_registry", {})
        image_url = kwargs.get("_resolved_image_url") or image_registry.get(image_id)
        if not image_url:
            return {
                "success": False,
                "message": f"未找到图片 {image_id}，可能已过期或不存在",
            }

        description = await self._describe_media_with_pending_task(
            ai_assistant=kwargs.get("ai_assistant"),
            media_type="image",
            media_id=image_id,
            media_url=image_url,
            prompt=prompt,
            describe_func=self._describe_image_api,
        )
        return {
            "success": True,
            "message": description,
            "data": {
                "image_id": image_id,
                "description": description,
            },
        }

    @ai_tool(
        name="describe_video",
        desc="获取群聊中视频的内容描述。当群聊记录或用户消息中包含视频标记（如 [视频:vid_001]），且需要了解视频内容时调用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "video_id": {
                    "type": "string",
                    "description": "视频标识符，如 vid_001、vid_002 等",
                },
                "prompt": {
                    "type": "string",
                    "description": "可选的自定义提示词，用于指定想了解视频的哪些方面",
                },
            },
            "required": ["video_id"],
        },
        category="vision",
        triggers=["查看视频", "看视频", "视频内容"],
        input_model=DescribeVideoInput,
    )
    async def describe_video_core(
        self,
        user_id: int,
        group_id: int,
        video_id: str = "",
        prompt: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        if not video_id:
            return {"success": False, "message": "未提供视频标识符"}

        video_registry = kwargs.get("video_registry", {})
        video_url = kwargs.get("_resolved_video_url") or video_registry.get(video_id)
        if not video_url:
            return {
                "success": False,
                "message": f"未找到视频 {video_id}，可能已过期或不存在",
            }

        description = await self._describe_media_with_pending_task(
            ai_assistant=kwargs.get("ai_assistant"),
            media_type="video",
            media_id=video_id,
            media_url=video_url,
            prompt=prompt,
            describe_func=self._describe_video_api,
        )
        return {
            "success": True,
            "message": description,
            "data": {
                "video_id": video_id,
                "description": description,
            },
        }

    @ai_tool(
        name="generate_image",
        desc="根据文字描述生成图片。当用户请求画图、生成图片、创作图像时使用此工具。不可以用文字代替画图糊弄用户！",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片描述提示词，用英文描述效果更好。例如：'A cute cat sitting on a sofa' 或 'A beautiful sunset over the ocean'",
                }
            },
            "required": ["prompt"],
        },
        gate={
            "user_keywords": ["画图", "生成图片", "生成一张", "画一张", "画一个", "画一幅", "画个", "帮我画", "绘制", "作图", "出图"],
            "assistant_keywords": ["画图", "图片", "生成图片", "出图", "帮你画", "我来画", "画好"],
            "system_prompt": "检测到用户请求画图，但助手回复中仍在谈论“画图/图片/生成”等关键词却没有实际出图。必须调用 generate_image 工具并返回真实结果，禁止用文字敷衍。",
        },
        category="vision",
        triggers=["画图", "生成图片", "画一张", "创作图像", "帮我画"],
        input_model=GenerateImageInput,
        points_cost=5,
        points_reason="vision_generate_image",
        points_insufficient_message=(
            "❌ 积分不足，无法生成图片。\n"
            "当前积分：{current_balance}\n"
            "所需积分：{required_points}\n"
            "提示：可以先发送“签到”获取积分。"
        ),
    )
    async def generate_image_core(
        self,
        user_id: int,
        group_id: int,
        prompt: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        if not prompt:
            return {"success": False, "message": "未提供图片描述"}

        success, result = await self._generate_image_api(prompt)
        if not success:
            return {"success": False, "message": result}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(result) as response:
                    if response.status != 200:
                        return {
                            "success": False,
                            "message": f"图片下载失败: HTTP {response.status}",
                            "data": {"image_url": result},
                        }
                    image_bytes = await response.read()
                    msg = UniMessage.text("图片已生成并发送\n")
                    msg += UniMessage.image(raw=image_bytes)
                    receipt = await msg.send()
                    from src.services._ai.message_bridge import record_group_media_output

                    record_group_media_output(
                        group_id,
                        text="图片已生成并发送",
                        image_bytes_list=[image_bytes],
                        message_result=receipt,
                    )
        except Exception as exc:
            error_str = str(exc)
            if "Timeout" in error_str or "timeout" in error_str:
                return {
                    "success": True,
                    "message": "图片已生成并发送（发送确认超时，但图片应该已送达）",
                    "data": {"prompt": prompt, "image_url": result},
                }
            return {
                "success": False,
                "message": f"图片生成成功但发送失败: {exc}",
                "data": {"image_url": result},
            }

        return {
            "success": True,
            "message": "图片已生成并发送",
            "data": {
                "prompt": prompt,
                "image_url": result,
            },
        }


__all__ = ["VisionToolMixin"]
