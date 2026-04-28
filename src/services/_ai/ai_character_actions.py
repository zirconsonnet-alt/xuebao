"""AI 角色相关命令动作。"""

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.ai import get_voice_id_by_index, get_voice_list_text
from src.support.core import TTSType
from src.support.group import wait_for
from src.services.base import service_action

from .common import Character, get_default_character_names


class AICharacterActionMixin:
    @service_action(cmd="添加角色", desc="添加自定义AI角色")
    async def add_character(self, event: GroupMessageEvent):
        ai_assistant = self.get_ai_assistant(event)
        await self.group.send_msg("请输入新角色的名称（2-12个字符）：")
        name = await wait_for(30)
        if not name:
            await self.group.send_msg("超时，已取消添加角色。")
            return
        name = name.strip()
        if len(name) < 2 or len(name) > 12:
            await self.group.send_msg("角色名称长度需在2-12个字符之间，已取消。")
            return
        if name in ai_assistant.get_character_names():
            await self.group.send_msg(f"角色名{name}已存在，已取消。")
            return

        await self.group.send_msg(get_voice_list_text() + "\n\n请输入语音编号：")
        voice_input = await wait_for(30)
        if not voice_input:
            await self.group.send_msg("超时，已取消添加角色。")
            return
        try:
            voice_index = int(voice_input.strip())
            voice_result = get_voice_id_by_index(voice_index)
            if not voice_result:
                await self.group.send_msg("无效的语音编号，已取消。")
                return
            voice_id, tts_type_str = voice_result
            tts_type = TTSType(tts_type_str)
        except ValueError:
            await self.group.send_msg("请输入有效的数字编号，已取消。")
            return

        await self.group.send_msg(
            "请输入角色的人格设定（描述角色的性格、说话方式等）：\n"
            "提示：可以使用{name}占位符代表角色名称"
        )
        configuration = await wait_for(120)
        if not configuration:
            await self.group.send_msg("超时，已取消添加角色。")
            return

        await self.group.send_msg("请输入角色切换时的开场白（直接回复'跳过'使用默认）：")
        on_switch_msg = await wait_for(30)
        if not on_switch_msg or on_switch_msg.strip() == "跳过":
            on_switch_msg = f"你好，我是{name}！"

        new_character = Character(
            name=name,
            voice_id=voice_id,
            tts_type=tts_type,
            configuration=configuration,
            on_switch_msg=on_switch_msg,
            is_custom=True,
            creator_id=event.user_id,
        )
        if ai_assistant.add_custom_character(new_character):
            await self.group.send_msg(f"✅ 角色{name}创建成功！\n使用切换人格命令可以切换到该角色。")
            return
        await self.group.send_msg("❌ 添加角色失败，角色名可能已存在。")

    @service_action(cmd="删除角色", desc="删除自定义AI角色")
    async def delete_character(self, event: GroupMessageEvent):
        ai_assistant = self.get_ai_assistant(event)
        custom_chars = ai_assistant.get_custom_characters()
        if not custom_chars:
            await self.group.send_msg("当前没有自定义角色。")
            return

        char_list = "\n".join([f"{index + 1}. {char.name}" for index, char in enumerate(custom_chars)])
        await self.group.send_msg(f"自定义角色列表：\n{char_list}\n\n请输入要删除的角色编号：")

        response = await wait_for(30)
        if not response:
            await self.group.send_msg("超时，已取消操作。")
            return

        try:
            index = int(response.strip()) - 1
        except ValueError:
            await self.group.send_msg("请输入有效的数字编号，已取消。")
            return

        if not (0 <= index < len(custom_chars)):
            await self.group.send_msg("无效的编号，已取消。")
            return

        char_name = custom_chars[index].name
        if ai_assistant.remove_custom_character(char_name):
            await self.group.send_msg(f"✅ 角色{char_name}已删除。")
            return
        await self.group.send_msg("❌ 删除失败。")

    @service_action(cmd="角色列表", desc="查看所有可用角色", tool_callable=True)
    async def list_characters(self, event: GroupMessageEvent):
        ai_assistant = self.get_ai_assistant(event)
        default_names = get_default_character_names()
        custom_chars = ai_assistant.get_custom_characters()

        msg_lines = ["【预设角色】", "，".join(default_names)]
        if custom_chars:
            msg_lines.append("\n【自定义角色】")
            for char in custom_chars:
                msg_lines.append(f"• {char.name}")
        msg_lines.append(f"\n当前角色：{ai_assistant.character.name}")
        await self.group.send_msg("\n".join(msg_lines))


__all__ = ["AICharacterActionMixin"]
