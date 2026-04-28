"""AI 控制类命令动作。"""

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg

from src.support.ai import config as ai_runtime_config
from src.support.core import process_text
from src.support.group import get_id, wait_for
from src.services.base import service_action


class AIControlActionMixin:
    def _normalize_rate_limit_per_hour(self) -> int:
        try:
            return max(1, int(self.rate_limit_per_hour))
        except (TypeError, ValueError):
            return ai_runtime_config.default_rate_limit_per_hour

    def _sync_group_rate_limit_state(self, event: GroupMessageEvent) -> int:
        limit_per_hour = self._normalize_rate_limit_per_hour()
        ai_assistant = self.get_ai_assistant(event)
        if hasattr(ai_assistant, "rate_limit_enabled"):
            ai_assistant.rate_limit_enabled = bool(self.rate_limit_enable)
        if hasattr(ai_assistant, "rate_limit_per_hour"):
            ai_assistant.rate_limit_per_hour = limit_per_hour
        if self.rate_limit_per_hour != limit_per_hour:
            self.rate_limit_per_hour = limit_per_hour
        return limit_per_hour

    @service_action(cmd="语音开关", desc="切换语音回复模式")
    async def toggle_voice(self, event: GroupMessageEvent):
        self.voice_enable = not self.voice_enable
        ai_assistant = self.get_ai_assistant(event)
        service_config = {"voice_enable": self.voice_enable}
        if self.voice_enable:
            await ai_assistant.send(ai_assistant.character.voice_enable_msg, service_config)
            return
        await ai_assistant.send(ai_assistant.character.voice_disable_msg, service_config)

    @service_action(cmd="BGM开关", desc="切换背景音乐")
    async def toggle_bgm(self, event: GroupMessageEvent):
        self.music_enable = not self.music_enable
        await self.group.send_msg(f"✅ BGM已{'开启' if self.music_enable else '关闭'}。")

    @service_action(cmd="聊天模式", desc="切换群聊模式")
    async def toggle_group_mode(self, event: GroupMessageEvent):
        self.group_mode = not self.group_mode
        await self.group.send_msg(f"✅ 聊天模式已{'开启' if self.group_mode else '关闭'}。")

    @service_action(cmd="工具开关", desc="切换自动工具调用功能")
    async def toggle_tools(self, event: GroupMessageEvent):
        self.tools_enable = not self.tools_enable
        await self.group.send_msg(f"✅ 工具调用已{'开启' if self.tools_enable else '关闭'}。")

    @service_action(cmd="思考模式", desc="切换深度思考模式")
    async def toggle_thinking(self, event: GroupMessageEvent):
        self.thinking_enable = not self.thinking_enable
        await self.group.send_msg(f"✅ 深度思考模式已{'开启' if self.thinking_enable else '关闭'}。")

    @service_action(cmd="限频开关", desc="切换使用频率限制")
    async def toggle_rate_limit(self, event: GroupMessageEvent):
        self.rate_limit_enable = not self.rate_limit_enable
        limit_per_hour = self._sync_group_rate_limit_state(event)
        if self.rate_limit_enable:
            await self.group.send_msg(f"✅ 使用频率限制已开启，当前为每小时 {limit_per_hour} 次。")
            return
        await self.group.send_msg("✅ 使用频率限制已关闭，当前不限制聊天频率。")

    @service_action(cmd="查看限频", desc="查看当前聊天频率限制状态")
    async def show_rate_limit(self, event: GroupMessageEvent):
        limit_per_hour = self._sync_group_rate_limit_state(event)
        if self.rate_limit_enable:
            await self.group.send_msg(f"当前聊天限频已开启：每小时 {limit_per_hour} 次。")
            return
        await self.group.send_msg(f"当前聊天限频已关闭；若重新开启，将按每小时 {limit_per_hour} 次生效。")

    @service_action(cmd="设置限频", desc="设置每小时聊天次数", need_arg=True)
    async def set_rate_limit(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        limit_text = arg.extract_plain_text().strip()
        if not limit_text:
            await self.group.send_msg("请输入每小时允许的聊天次数，例如：设置限频 5")
            return
        try:
            limit_per_hour = int(limit_text)
        except ValueError:
            await self.group.send_msg("限频次数必须是正整数，例如：设置限频 5")
            return
        if limit_per_hour <= 0:
            await self.group.send_msg("限频次数必须大于 0。若想完全不限频，请使用【限频开关】将其关闭。")
            return

        self.rate_limit_per_hour = limit_per_hour
        self._sync_group_rate_limit_state(event)
        if self.rate_limit_enable:
            await self.group.send_msg(f"✅ 聊天限频已更新为每小时 {limit_per_hour} 次。")
            return
        await self.group.send_msg(
            f"✅ 已保存聊天限频为每小时 {limit_per_hour} 次；当前限频开关关闭中，重新开启后才会生效。"
        )

    @service_action(cmd="拉黑", desc="将用户加入黑名单", need_arg=True, require_admin=True)
    async def add_blacklist(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        ai_assistant = self.get_ai_assistant(event)
        user_id = str(arg).strip()
        if not user_id:
            await self.group.send_msg("请输入用户ID或昵称。")
            user_id = await wait_for(10)
            user_id = user_id.strip() if user_id else None
            if not user_id:
                return
        if not user_id.isdigit():
            user_id = get_id(user_id)
            if not user_id:
                await self.group.send_msg("请输入有效ID。")
                return

        success, message = ai_assistant.add_to_blacklist(int(user_id))
        await self.group.send_msg(f"{'✅' if success else '❌'} {message}")

    @service_action(cmd="解除黑名单", desc="将用户移出黑名单", need_arg=True, require_admin=True)
    async def remove_blacklist(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        ai_assistant = self.get_ai_assistant(event)
        user_id = str(arg).strip()
        if not user_id:
            await self.group.send_msg("请输入用户ID或昵称。")
            user_id = await wait_for(10)
            user_id = user_id.strip() if user_id else None
            if not user_id:
                return
        if not user_id.isdigit():
            user_id = get_id(user_id)
            if not user_id:
                await self.group.send_msg("请输入有效ID。")
                return
        if int(user_id) == event.user_id:
            await self.group.send_msg("您没有解除自己限制的权限！")
            return

        success, message = ai_assistant.remove_from_blacklist(int(user_id))
        await self.group.send_msg(f"{'✅' if success else '❌'} {message}")

    @service_action(cmd="说", desc="语音合成指定内容", need_arg=True, tool_callable=False)
    async def speak(self, event: GroupMessageEvent, arg: Message = CommandArg()):
        if not self.enabled:
            return
        ai_assistant = self.get_ai_assistant(event)
        if event.user_id in ai_assistant.black_list:
            return

        if event.reply:
            msg = event.reply.message.extract_plain_text()
        elif arg.extract_plain_text():
            msg = arg.extract_plain_text()
        else:
            await self.group.send_msg("请指定要说的内容。")
            msg = await wait_for(10)
            if not msg:
                return

        if not ai_assistant.speech_generator:
            await ai_assistant.send_text("当前角色不支持语音")
            return

        speech_text = process_text(msg, for_speech=True)
        if not speech_text:
            await ai_assistant.send_text("没有可朗读的内容。")
            return

        path = await ai_assistant.speech_generator.gen_speech(
            text=speech_text,
            voice_id=ai_assistant.character.voice_id,
            music_enable=self.music_enable,
        )
        if path:
            await ai_assistant.send_audio(path)
            return
        await ai_assistant.send_text("语音生成失败")


__all__ = ["AIControlActionMixin"]
