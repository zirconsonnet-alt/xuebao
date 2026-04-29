"""AI 助手对话与菜单运行时。"""

import json
import random
from pathlib import Path
from typing import Any, Dict, List

import aiohttp
import nonebot
from nonebot.adapters.onebot.v11 import ActionFailed
from nonebot_plugin_alconna import UniMessage

from src.support.core import ServerType, TTSType, make_dict, process_text, tool_registry
from src.support.group import wait_for

from .common import (
    BASE_MENU_ITEMS,
    MenuItem,
    RANDOM_ACTIONS,
    _default_excluded_tool_names,
    _strip_model_thought,
    config,
)
from .config_runtime import AIAssistantConfigRuntimeMixin


def _describe_audio_file(path: str) -> str:
    audio_path = Path(path)
    try:
        exists = audio_path.exists()
        size = audio_path.stat().st_size if exists else 0
        return f"path={audio_path}, exists={exists}, size={size}"
    except Exception as exc:
        return f"path={audio_path}, stat_error={exc!r}"


class AIAssistantDialogRuntimeMixin:
    def _can_record_group_output(self) -> bool:
        return getattr(self, "server_type", None) == ServerType.GROUP.value

    def _record_group_text_output(
        self,
        message: str,
        *,
        message_result: Any = None,
        remember_only: bool = False,
    ):
        if not self._can_record_group_output():
            return

        from .message_bridge import record_group_output

        record_group_output(
            int(self.server_id),
            message,
            message_result=message_result,
            remember_only=remember_only,
        )

    def _record_group_audio_output(
        self,
        *,
        transcript: str = "",
        message_result: Any = None,
        remember_only: bool = False,
    ):
        if not self._can_record_group_output():
            return

        from .message_bridge import record_group_media_output

        record_group_media_output(
            int(self.server_id),
            text=transcript,
            markers=["[语音]"],
            message_result=message_result,
            remember_only=remember_only,
        )

    def _bind_runtime_bot(self, bot: Any = None):
        if bot is not None:
            self._runtime_bot = bot

    def _get_runtime_bot(self, bot: Any = None):
        if bot is not None:
            self._runtime_bot = bot
            return bot

        runtime_bot = getattr(self, "_runtime_bot", None)
        if runtime_bot is not None:
            return runtime_bot

        bots = nonebot.get_bots()
        if not bots:
            return None

        runtime_bot = next(iter(bots.values()))
        self._runtime_bot = runtime_bot
        return runtime_bot

    async def send_text(
        self,
        message: str,
        at_sender: bool = False,
        *,
        at_user_id: int | None = None,
        record_history: bool = True,
    ):
        try:
            receipt: Any = None
            should_at_user = (
                at_user_id is not None
                and getattr(self, "server_type", None) == ServerType.GROUP.value
            )
            runtime_bot = self._get_runtime_bot()
            if should_at_user and runtime_bot is not None:
                from src.support.group import build_group_message

                rendered_message = build_group_message(message, at_user_id=at_user_id)
                receipt = await runtime_bot.send_group_msg(
                    group_id=int(self.server_id),
                    message=rendered_message,
                )
            else:
                receipt = await UniMessage.text(message).send(at_sender=at_sender)
            self._record_group_text_output(
                message,
                message_result=receipt,
                remember_only=(not record_history),
            )
        except Exception:
            pass

    async def send_audio(self, path: str, transcript: str = "", *, record_history: bool = True):
        audio_file_debug = _describe_audio_file(path)
        print(f"[AI TTS] 准备发送语音: {audio_file_debug}")
        try:
            receipt = await UniMessage.audio(path=path).send()
            print(f"[AI TTS] 语音发送成功: receipt={receipt!r}")
            self._record_group_audio_output(
                transcript=transcript,
                message_result=receipt,
                remember_only=(not record_history),
            )
        except ActionFailed as exc:
            print(f"[AI TTS] 语音发送失败 ActionFailed: {audio_file_debug}, error={exc!r}")
        except Exception as exc:
            print(f"[AI TTS] 语音发送异常: {audio_file_debug}, error={exc!r}")

    async def send_voice_tencent(
        self,
        character_id: str,
        message: str,
        transcript: str = "",
        *,
        record_history: bool = True,
    ):
        async with aiohttp.ClientSession() as session:
            payload = {
                "group_id": self.server_id,
                "character": character_id,
                "text": message,
            }
            async with session.post(
                "http://127.0.0.1:3005/send_group_ai_record",
                headers={"Content-Type": "application/json"},
                json=payload,
            ) as response:
                response_text = await response.text()
                response_payload: Any = None
                if response_text:
                    try:
                        response_payload = json.loads(response_text)
                    except Exception:
                        response_payload = response_text
                self._record_group_audio_output(
                    transcript=transcript or message,
                    message_result=response_payload,
                    remember_only=(not record_history),
                )

    async def send(
        self,
        message: str,
        service_config: Dict[str, Any] = None,
        *,
        at_user_id: int | None = None,
        record_history: bool = True,
    ):
        service_config = service_config or {}
        voice_enable = service_config.get("voice_enable", self.voice_enable)
        music_enable = service_config.get("music_enable", self.music_enable)

        message = _strip_model_thought(message)
        if not message or not message.strip():
            return
        display_text = process_text(message, for_speech=False)

        if voice_enable and self.character:
            speech_text = process_text(message, for_speech=True)
            if not speech_text or len(speech_text.strip()) < 2:
                print(f"[TTS] 语音文本过短，改为发送文本: '{speech_text}'")
                await self.send_text(
                    display_text if display_text else message,
                    at_user_id=at_user_id,
                    record_history=record_history,
                )
                return

            if self.character.tts_type == TTSType.TENCENT:
                await self.send_voice_tencent(
                    self.character.voice_id,
                    speech_text,
                    transcript=display_text or message,
                    record_history=record_history,
                )
            elif self.speech_generator:
                audio_path = await self.speech_generator.gen_speech(
                    speech_text,
                    self.character.voice_id,
                    music_enable,
                )
                if audio_path:
                    await self.send_audio(
                        audio_path,
                        transcript=display_text or message,
                        record_history=record_history,
                    )
                else:
                    await self.send_text(display_text, at_user_id=at_user_id, record_history=record_history)
            else:
                await self.send_text(display_text, at_user_id=at_user_id, record_history=record_history)
        else:
            await self.send_text(display_text, at_user_id=at_user_id, record_history=record_history)

    async def switch_character(self, target_name: str) -> bool:
        if target_name not in self.character_dict:
            return False

        previous_name = self.character.name if self.character else None
        new_character = self.character_dict[target_name]
        self.set_character(new_character, previous_name)
        self._config["current_character"] = target_name
        self._save_config()
        await self.send(self.character.on_switch_msg)
        return True

    def set_character(self, character, previous_name: str = None):
        self.character = character
        self._update_speech_generator()

        transition_note = ""
        if previous_name and previous_name != character.name:
            transition_note = f"（注意：在之前的对话中你被称为{previous_name}，现在你的身份是{character.name}）"

        tools_note = f"""你是群聊机器人“雪豹”，你必须严格遵守“工具优先与可审计交付”协议。
            【总原则：工具是能力边界】
            - 只要某个任务在工具清单中有对应工具，你必须优先调用工具完成。
            - 禁止用纯文本“假装已经做了工具能做的事”。
            - 任何时候都不能编造工具输出、不能编造已发送的图片/文件、不能编造查询到的结果。

            【强制工具调用（Hard MUST Call）】
            1) 用户请求画图/出图/生成图片时，必须调用生成工具。
            2) 只有当当前用户明确要求看图/识图，或者当前消息、被回复消息里的图片引用会直接影响回答时，才调用图片描述工具。
               不要因为群聊历史里出现过图片、表情包或聊天背景中带了图片引用，就主动调用图片描述工具。
            3) 用户目标明确属于工具能力范围时，必须调用对应工具。

            可用工具如下：
            {tool_registry.get_tools_prompt(exclude_tool_names=list(_default_excluded_tool_names))}

            现在开始工作。
        """
        base_config = character.generate_configuration(transition_note)
        full_config = base_config + tools_note

        new_msg = make_dict("system", full_config)
        if len(self.msg_list) == 0:
            self.msg_list.append(new_msg)
        else:
            self.msg_list[0] = new_msg

    async def set_nickname(self):
        await self.send_text("您想用什么昵称来召唤我呢？")
        new_nickname = await wait_for(10)
        if new_nickname:
            self.nickname = new_nickname
            await self.send_text("嗯嗯，明白了！随时来找我玩哦~")

    async def clear_conversation(self):
        self.msg_list = [self.msg_list[0]] if self.msg_list else []
        await self.send("呜呜，头好痛...")

    async def switch_character_menu(self):
        await self.send_text(f"可用的人格如下：\n{'，'.join(self.get_character_names())}。")
        target_name = await wait_for(10)
        if target_name:
            for name in self.get_character_names():
                if target_name.startswith(name):
                    await self.switch_character(name)
                    break

    def add_message(self, record: Dict):
        self.msg_list.append(record)
        record_text = record.get("content", "")
        if len(record_text) > config.max_single_msg_length:
            record["content"] = record_text[-config.max_single_msg_length:]
        if len(self.msg_list) > config.max_msg_count:
            self.msg_list = [self.msg_list[0]] + self.msg_list[-(config.max_msg_count - 1) :]
        self.truncate_msg_list()

    def clean_invalid_tool_calls(self):
        if len(self.msg_list) <= 1:
            return

        cleaned = [self.msg_list[0]]
        index = 1
        while index < len(self.msg_list):
            message = self.msg_list[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                tool_call_ids = {tool_call.get("id") for tool_call in message.get("tool_calls", [])}
                next_index = index + 1
                found_responses = set()

                while next_index < len(self.msg_list):
                    next_message = self.msg_list[next_index]
                    if next_message.get("role") == "tool":
                        found_responses.add(next_message.get("tool_call_id"))
                        next_index += 1
                    else:
                        break

                if tool_call_ids == found_responses:
                    for position in range(index, next_index):
                        cleaned.append(self.msg_list[position])
                    index = next_index
                else:
                    print("[清理] 移除无效的工具调用消息（缺少 tool 响应）")
                    index = next_index
            else:
                cleaned.append(message)
                index += 1

        self.msg_list = cleaned

    def truncate_msg_list(self):
        total_length = sum(len(message.get("content", "")) for message in self.msg_list)
        while total_length > config.max_total_length and len(self.msg_list) > 1:
            del self.msg_list[1]
            total_length = sum(len(message.get("content", "")) for message in self.msg_list)

    def _get_menu_items(self) -> List[MenuItem]:
        return BASE_MENU_ITEMS

    def _build_menu_text(self) -> str:
        lines = [
            "------*AI助手菜单*------",
            f"{self.character.name if self.character else 'AI'}为您服务！",
        ]
        for item in self._get_menu_items():
            if item.getter:
                value = item.getter(self)
                status = ("开" if value else "关") if item.is_toggle else (value if value else "无")
                lines.append(f"*{item.key}.{item.label}：{status}；")
            else:
                lines.append(f"*{item.key}.{item.label}。")
        lines.append("输入序号，修改对应设置！")
        lines.append(random.choice(RANDOM_ACTIONS))
        return "\n".join(lines)

    async def _handle_menu_response(self, response: str):
        for item in self._get_menu_items():
            if response == item.key and item.action:
                method = getattr(self, item.action, None)
                if method:
                    await method()
                return

    async def text_menu(self):
        await self.send_text(self._build_menu_text())
        response = await wait_for(10)
        if response:
            await self._handle_menu_response(response)


class AIAssistantBaseRuntimeMixin(
    AIAssistantConfigRuntimeMixin,
    AIAssistantDialogRuntimeMixin,
):
    pass


