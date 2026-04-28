from datetime import timedelta

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    GroupUploadNoticeEvent,
    Message,
    MessageSegment,
)
from nonebot.internal.matcher import Matcher

from src.support.core import Services
from src.support.group import get_name_simple as get_name, wait_for_event, run_flow

from .base import BaseService, config_property, service_action, service_notice

class CompositionService(BaseService):
    service_type = Services.Composition
    default_config = {
        "enabled": True,
        "auto_card_enabled": True,
        "auto_essence_enabled": True,
        "supported_formats": [".wav", ".mp3"]
    }
    enabled = config_property("enabled")
    auto_card_enabled = config_property("auto_card_enabled")
    auto_essence_enabled = config_property("auto_essence_enabled")
    supported_formats = config_property("supported_formats")

    @service_notice(desc="作品发布通知", event_type="GroupUploadNoticeEvent", priority=5, block=False)
    async def on_file_upload(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        if not self.enabled:
            return
        uploaded_file_name = event.file.name
        if uploaded_file_name.startswith('['):
            return
        if not any(uploaded_file_name.endswith(fmt) for fmt in self.supported_formats):
            return
        await self._send_music_card(event, matcher)

    async def _send_music_card(self, event: GroupUploadNoticeEvent, matcher: Matcher):
        try:
            name, audio_url = await self.group.get_resent_file_url()
            img_url = await self.group.get_user_img(event.user_id)
            uploader_name = await get_name(event)

            if self.auto_card_enabled:
                await matcher.send(
                    MessageSegment(
                        "music",
                        {
                            "type": "custom",
                            "url": 'www.baidu.com',
                            'audio': audio_url,
                            "title": name,
                            "image": img_url,
                            "singer": uploader_name
                        }
                    )
                )
                await matcher.send(
                    Message(
                        f"{uploader_name}老师发布了新作品，快来看看吧！(引用群文件并回复" +
                        MessageSegment.face(63) +
                        "即可助力此作品成为群精华)"
                    )
                )

            if self.auto_essence_enabled:
                self._setup_essence_listener(matcher, uploader_name, event.file)
        except Exception as e:
            print(f"作品发布处理异常: {e}")

    def _setup_essence_listener(self, matcher: Matcher, uploader_name: str, file):
        async def waiter_task():
            deadline = timedelta(minutes=10).total_seconds()
            start_ts = None
            while True:
                if start_ts is None:
                    import time

                    start_ts = time.time()
                remain = int(deadline - (time.time() - start_ts))
                if remain <= 0:
                    return
                event = await wait_for_event(remain)
                if not event:
                    return
                if not isinstance(event, GroupMessageEvent):
                    continue
                if not event.reply:
                    continue
                if not event.message or event.message[0].type != "face":
                    continue
                try:
                    if int(event.message[0].data.get("id", -1)) != 63:
                        continue
                except Exception:
                    continue
                if event.reply.message and event.reply.message[0].data.get("file") != file.name:
                    continue
                await self.group.set_msg(event.reply.message_id)
                await matcher.send(f"{uploader_name}老师的作品深受喜爱，并被设为精华!")
                return

        import asyncio

        asyncio.create_task(waiter_task())

    @service_action(cmd="作品发布服务")
    async def composition_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ 作品发布服务未开启！")
            return
        flow = {
            "title": "欢迎使用作品发布服务",
            "text": "该服务暂无可用操作，主要通过文件上传自动处理。",
        }
        await run_flow(self.group, flow)
