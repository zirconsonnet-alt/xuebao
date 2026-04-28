import random
import traceback
from typing import Any, Dict, List, Optional

import aiohttp
import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.support.core import GenerateMemeInput, ListMemesInput, Services, ai_tool
from src.support.group import Group

from .base import BaseService, check_enabled, config_property, service_action

try:
    from nonebot.utils import run_sync
    from nonebot_plugin_alconna import UniMessage
    from meme_generator import (
        DeserializeError,
        ImageAssetMissing,
        ImageDecodeError,
        ImageEncodeError,
        ImageNumberMismatch,
        MemeFeedback,
        TextNumberMismatch,
        TextOverLength,
    )
    from meme_generator import Image as MemeImage
    from src.vendors.nonebot_plugin_memes.manager import meme_manager

    _MEME_AVAILABLE = True
except Exception:
    _MEME_AVAILABLE = False

if not _MEME_AVAILABLE:
    raise ImportError("meme 依赖不可用")

class MemeService(BaseService):
    service_type = Services.Meme
    default_config = {"enabled": False}
    enabled = config_property("enabled")

    def __init__(self, group: Group):
        super().__init__(group)

    @ai_tool(
        name="generate_meme",
        desc="生成表情包。根据关键词生成对应的表情包图片。可以使用群成员头像或指定文字。",
        parameters={"type": "object", "properties": {"keyword": {"type": "string", "description": "表情包关键词，如「摸」「揉」「拍」「亲」「打拳」「吃」等"}, "texts": {"type": "array", "items": {"type": "string"}, "description": "表情包文字内容列表，部分表情包需要文字"}, "user_ids": {"type": "array", "items": {"type": "integer"}, "description": "要使用头像的用户QQ号列表，不填则使用发送者头像"}}, "required": ["keyword"]},
        category="memes",
        triggers=["表情包", "做表情", "生成表情"],
        input_model=GenerateMemeInput,
    )
    async def generate_meme_core(self, user_id: int, group_id: int, keyword: str = "", texts: List[str] = None, user_ids: List[int] = None, **kwargs) -> Dict[str, Any]:
        texts = texts or []
        user_ids = user_ids or []
        if not keyword:
            return {"success": False, "message": "请提供表情包关键词"}

        memes = meme_manager.find(keyword.lower())
        if not memes:
            memes = meme_manager.search(keyword)
            if not memes:
                available = [meme.info.keywords[0] for meme in meme_manager.get_memes()[:20]]
                return {"success": False, "message": f"未找到关键词「{keyword}」对应的表情包。部分可用关键词：{', '.join(available)}"}

        meme = memes[0]
        params = meme.info.params
        if not user_ids:
            user_ids = [user_id]

        meme_images: list[MemeImage] = []
        bot = nonebot.get_bot()
        for uid in user_ids[:params.max_images]:
            try:
                user_info = await bot.get_stranger_info(user_id=uid)
                avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=640"
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as response:
                        if response.status == 200:
                            image_bytes = await response.read()
                            name = user_info.get("nickname", str(uid))
                            meme_images.append(MemeImage(name, image_bytes))
            except Exception as exc:
                print(f"[表情包] 获取用户 {uid} 头像失败: {exc}")

        if len(meme_images) < params.min_images:
            return {"success": False, "message": f"表情包「{keyword}」需要 {params.min_images} 张图片，但只获取到 {len(meme_images)} 张"}

        if len(texts) < params.min_texts:
            texts.extend(params.default_texts[len(texts):])
        texts = texts[:params.max_texts]

        try:
            result = await run_sync(meme.generate)(meme_images, texts, {})
            if isinstance(result, bytes):
                receipt = await UniMessage.image(raw=result).send()
                from src.services._ai.message_bridge import record_group_media_output

                record_group_media_output(
                    group_id,
                    text=f"已生成表情包：{meme.info.keywords[0] if meme.info.keywords else meme.key}",
                    image_bytes_list=[result],
                    message_result=receipt,
                )
                return {"success": True, "message": f"已生成表情包「{meme.info.keywords[0]}」", "data": {"meme_key": meme.key, "keyword": keyword}}
            error_msg = self._handle_meme_error(result)
            return {"success": False, "message": error_msg or "表情包生成失败"}
        except Exception as exc:
            return {"success": False, "message": f"表情包生成出错: {exc}"}

    @ai_tool(
        name="list_memes",
        desc="列出可用的表情包关键词。当用户询问有哪些表情包可用时调用。",
        parameters={"type": "object", "properties": {"search": {"type": "string", "description": "可选的搜索关键词，用于过滤表情包"}, "limit": {"type": "integer", "description": "返回数量限制，默认20"}}, "required": []},
        category="memes",
        triggers=["表情包列表", "有哪些表情包"],
        input_model=ListMemesInput,
    )
    async def list_memes_core(self, user_id: int, group_id: int, search: str = "", limit: int = 20, **kwargs) -> Dict[str, Any]:
        try:
            memes = meme_manager.search(search, include_tags=True) if search else meme_manager.get_memes()
            memes = memes[:limit]
            meme_list = []
            for meme in memes:
                info = meme.info
                params = info.params
                meme_list.append(
                    {
                        "关键词": info.keywords[0] if info.keywords else meme.key,
                        "别名": info.keywords[1:3] if len(info.keywords) > 1 else [],
                        "需要图片": f"{params.min_images}-{params.max_images}" if params.min_images != params.max_images else str(params.min_images),
                        "需要文字": f"{params.min_texts}-{params.max_texts}" if params.min_texts != params.max_texts else str(params.min_texts),
                    }
                )
            return {"success": True, "message": f"找到 {len(meme_list)} 个表情包", "data": {"memes": meme_list, "total": len(meme_manager.get_memes())}}
        except Exception as exc:
            return {"success": False, "message": f"获取表情包列表出错: {exc}"}

    def _handle_meme_error(self, result) -> Optional[str]:
        if isinstance(result, ImageDecodeError):
            return f"图片解码出错：{result.error}"
        if isinstance(result, ImageEncodeError):
            return f"图片编码出错：{result.error}"
        if isinstance(result, ImageAssetMissing):
            return f"缺少表情包资源文件：{result.path}，请检查 meme_generator 资源是否完整"
        if isinstance(result, DeserializeError):
            return f"表情选项解析出错：{result.error}"
        if isinstance(result, ImageNumberMismatch):
            num = f"{result.min} ~ {result.max}" if result.min != result.max else str(result.min)
            return f"图片数量不符，应为 {num}，实际传入 {result.actual}"
        if isinstance(result, TextNumberMismatch):
            num = f"{result.min} ~ {result.max}" if result.min != result.max else str(result.min)
            return f"文字数量不符，应为 {num}，实际传入 {result.actual}"
        if isinstance(result, TextOverLength):
            text_repr = result.text if len(result.text) <= 10 else (result.text[:10] + "...")
            return f"文字过长：{text_repr}"
        if isinstance(result, MemeFeedback):
            return result.feedback
        return None

    @service_action(cmd="表情包列表", desc="查看可用的表情包")
    @check_enabled
    async def list_memes(self, event: GroupMessageEvent):
        memes = meme_manager.get_memes()
        meme_keywords = []
        for meme in memes[:50]:
            if meme.info.keywords:
                meme_keywords.append(meme.info.keywords[0])
        msg = f"可用表情包（共{len(memes)}个，显示前50个）：\n" + "、".join(meme_keywords)
        msg += "\n\n使用方式：表情包 <关键词> [图片/@某人] [文字]"
        await self.group.send_msg(msg)

    @service_action(cmd="表情包搜索", need_arg=True, desc="搜索表情包")
    @check_enabled
    async def search_memes(self, event: GroupMessageEvent, arg: Message):
        keyword = arg.extract_plain_text().strip()
        if not keyword:
            await self.group.send_msg("请输入搜索关键词")
            return
        memes = meme_manager.search(keyword, include_tags=True)
        if not memes:
            await self.group.send_msg(f"未找到与「{keyword}」相关的表情包")
            return
        meme_list = []
        for meme in memes[:20]:
            keywords = "、".join(meme.info.keywords[:3]) if meme.info.keywords else meme.key
            meme_list.append(f"  {keywords}")
        await self.group.send_msg(f"搜索「{keyword}」的结果（共{len(memes)}个）：\n" + "\n".join(meme_list))

    @service_action(cmd="表情包详情", need_arg=True, desc="查看表情包详情")
    @check_enabled
    async def meme_info(self, event: GroupMessageEvent, arg: Message):
        keyword = arg.extract_plain_text().strip()
        if not keyword:
            await self.group.send_msg("请输入表情包关键词")
            return
        memes = meme_manager.find(keyword.lower()) or meme_manager.search(keyword)
        if not memes:
            await self.group.send_msg(f"未找到表情包「{keyword}」")
            return
        meme = memes[0]
        info = meme.info
        params = info.params
        msg = f"表情包：{meme.key}\n关键词：{', '.join(info.keywords)}\n需要图片：{params.min_images} ~ {params.max_images}\n需要文字：{params.min_texts} ~ {params.max_texts}\n"
        if params.default_texts:
            msg += f"默认文字：{', '.join(params.default_texts)}\n"
        if info.shortcuts:
            shortcuts = [shortcut.humanized or shortcut.pattern for shortcut in info.shortcuts[:5]]
            msg += f"快捷方式：{', '.join(shortcuts)}"
        await self.group.send_msg(msg)

    @service_action(
        cmd="表情包",
        need_arg=True,
        desc="生成表情包",
        record_ai_context=True,
        ai_context_label="生成表情包",
        ai_context_include_arg=True,
    )
    @check_enabled
    async def generate_meme(self, event: GroupMessageEvent, arg: Message):
        keyword = ""
        texts = []
        user_ids = []
        for seg in arg:
            if seg.type == "text":
                text = seg.data.get("text", "").strip()
                if text:
                    parts = text.split()
                    if not keyword and parts:
                        keyword = parts[0]
                        texts.extend(parts[1:])
                    else:
                        texts.extend(parts)
            elif seg.type == "at":
                qq = seg.data.get("qq")
                if qq:
                    user_ids.append(int(qq))
        if not keyword:
            await self.group.send_msg("请输入表情包关键词")
            return
        result = await self.generate_meme_core(
            user_id=event.user_id,
            group_id=event.group_id,
            keyword=keyword,
            texts=texts,
            user_ids=user_ids if user_ids else None,
        )
        if not result.get("success"):
            await self.group.send_msg(result.get("message", "表情包生成失败"))

    @service_action(
        cmd="随机表情包",
        desc="随机生成一个表情包",
        record_ai_context=True,
        ai_context_label="随机生成一个表情包",
    )
    @check_enabled
    async def random_meme(self, event: GroupMessageEvent):
        try:
            user_info = await nonebot.get_bot().get_stranger_info(user_id=event.user_id)
            avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={event.user_id}&s=640"
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as response:
                    if response.status != 200:
                        await self.group.send_msg("获取头像失败")
                        return
                    image_bytes = await response.read()
                    name = user_info.get("nickname", str(event.user_id))
                    meme_images = [MemeImage(name, image_bytes)]
        except Exception as exc:
            await self.group.send_msg(f"获取头像失败: {exc}")
            return

        available_memes = [
            meme
            for meme in meme_manager.get_memes()
            if meme.info.params.min_images <= 1 <= meme.info.params.max_images and meme.info.params.min_texts == 0
        ]
        if not available_memes:
            await self.group.send_msg("没有符合条件的表情包")
            return

        meme = random.choice(available_memes)
        try:
            result = await run_sync(meme.generate)(meme_images, [], {})
            if isinstance(result, bytes):
                keyword = meme.info.keywords[0] if meme.info.keywords else meme.key
                message = UniMessage.text(f"随机表情包：{keyword}\n")
                message += UniMessage.image(raw=result)
                receipt = await message.send()
                from src.services._ai.message_bridge import record_group_media_output

                record_group_media_output(
                    event.group_id,
                    text=f"随机表情包：{keyword}",
                    image_bytes_list=[result],
                    message_result=receipt,
                )
                return
            error_msg = self._handle_meme_error(result)
            if error_msg:
                await self.group.send_msg(error_msg)
        except Exception as exc:
            print(f"[随机表情包] 生成失败: {traceback.format_exc()}")
            await self.group.send_msg(f"表情包生成失败: {exc}")

__all__ = ["MemeService"]
