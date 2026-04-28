import re
from typing import Any, Dict, List

import nonebot
from nonebot.adapters.onebot.v11 import (
    GroupIncreaseNoticeEvent,
    GroupRequestEvent,
    Message,
    MessageSegment,
)
from nonebot.params import CommandArg

from src.support.core import Services
from src.support.group import run_flow, wait_for

from .base import (
    BaseService,
    check_enabled,
    config_property,
    service_action,
    service_notice,
    service_request,
)


def _normalize_answer_patterns(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = re.split(r"[\n,，]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item) for item in raw]
    else:
        return []
    return [item.strip().upper() for item in values if str(item).strip()]


def _normalize_welcome_nodes(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for group_id, nodes in raw.items():
        if not isinstance(nodes, list):
            continue
        cleaned_nodes: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            content = str(node.get("content", "")).strip()
            if not content:
                continue
            cleaned_nodes.append(
                {
                    "user_id": node.get("user_id"),
                    "nickname": str(node.get("nickname", "")).strip() or "欢迎助手",
                    "content": content,
                }
            )
        normalized[str(group_id)] = cleaned_nodes
    return normalized


class RequestService(BaseService):
    service_type = Services.Request
    service_toggle_name = "入群审核服务"
    enable_requires_bot_admin = True
    disable_requires_bot_admin = True
    default_config = {
        "enabled": False,
        "welcome_enabled": True,
        "welcome_nodes": {},
        "answer_enabled": False,
        "answer": [],
    }
    enabled = config_property("enabled")
    welcome_enabled = config_property("welcome_enabled")
    welcome_nodes = config_property("welcome_nodes")
    answer_enabled = config_property("answer_enabled")
    answer = config_property("answer")

    @service_action(cmd="入群管理服务")
    @check_enabled
    async def request_system(self):
        try:
            request_system_flow = {
                "title": "欢迎来到入群管理服务系统",
                "subtitle": "审核、欢迎语、问答和设置都在这里管理。",
                "text": "请选择以下操作：\n1. 开启 / 关闭 入群审核\n2. 欢迎管理\n3. 入群问答管理\n4. 设置\n\n输入【序号】",
                "template": "service_menu",
                "sections": [
                    {
                        "title": "入群管理入口",
                        "description": "先选择模块，再进入对应的管理流程。",
                        "columns": 2,
                        "items": [
                            {"index": "1", "title": "入群审核开关", "description": "开启或关闭入群审核服务。", "meta": "回复 1 进入", "status": "审核", "status_tone": "warning"},
                            {"index": "2", "title": "欢迎管理", "description": "设置欢迎内容与欢迎功能状态。", "meta": "回复 2 进入", "status": "欢迎", "status_tone": "success"},
                            {"index": "3", "title": "入群问答管理", "description": "设置答案并切换问答审核。", "meta": "回复 3 进入", "status": "问答", "status_tone": "accent"},
                            {"index": "4", "title": "设置", "description": "查看当前服务的附加设置项。", "meta": "回复 4 进入", "status": "设置", "status_tone": "accent"},
                        ],
                    }
                ],
                "hint": "输入【序号】",
                "routes": {
                    "1": {
                        "title": "入群审核开关",
                        "subtitle": "切换整个入群审核服务的总开关。",
                        "text": "请选择操作：\n1. 开启入群审核服务\n2. 关闭入群审核服务\n\n输入【序号】",
                        "template": "service_menu",
                        "sections": [
                            {
                                "title": "审核开关",
                                "columns": 1,
                                "items": [
                                    {"index": "1", "title": "开启入群审核服务", "description": "允许新成员入群时先经过审核。", "meta": "回复 1 执行", "status": "开启", "status_tone": "success"},
                                    {"index": "2", "title": "关闭入群审核服务", "description": "停止当前入群审核流程。", "meta": "回复 2 执行", "status": "关闭", "status_tone": "danger"},
                                ],
                            }
                        ],
                        "hint": "输入【序号】",
                        "routes": {"1": self.enable_service, "2": self.disable_service},
                    },
                    "2": {
                        "title": "欢迎管理",
                        "subtitle": "欢迎语内容和欢迎功能总开关都在这里。",
                        "text": "请选择操作：\n1. 设置欢迎内容\n2. 开启欢迎功能\n3. 关闭欢迎功能\n\n输入【序号】",
                        "template": "service_menu",
                        "sections": [
                            {
                                "title": "欢迎功能",
                                "columns": 1,
                                "items": [
                                    {"index": "1", "title": "设置欢迎内容", "description": "更新新人入群时发送的欢迎消息。", "meta": "回复 1 执行", "status": "编辑", "status_tone": "accent"},
                                    {"index": "2", "title": "开启欢迎功能", "description": "开启新人欢迎消息。", "meta": "回复 2 执行", "status": "开启", "status_tone": "success"},
                                    {"index": "3", "title": "关闭欢迎功能", "description": "关闭新人欢迎消息。", "meta": "回复 3 执行", "status": "关闭", "status_tone": "danger"},
                                ],
                            }
                        ],
                        "hint": "输入【序号】",
                        "routes": {"1": self.set_welcome_nodes, "2": self.enable_welcome, "3": self.disable_welcome},
                    },
                    "3": {
                        "title": "入群问答管理",
                        "subtitle": "答案配置和问答审核开关在这里处理。",
                        "text": "请选择操作：\n1. 设置入群答案\n2. 开启问答审核\n3. 关闭问答审核\n\n输入【序号】",
                        "template": "service_menu",
                        "sections": [
                            {
                                "title": "问答管理",
                                "columns": 1,
                                "items": [
                                    {"index": "1", "title": "设置入群答案", "description": "更新通过审核需要匹配的答案。", "meta": "回复 1 执行", "status": "编辑", "status_tone": "accent"},
                                    {"index": "2", "title": "开启问答审核", "description": "启用入群答案匹配审核。", "meta": "回复 2 执行", "status": "开启", "status_tone": "success"},
                                    {"index": "3", "title": "关闭问答审核", "description": "关闭当前问答审核。", "meta": "回复 3 执行", "status": "关闭", "status_tone": "danger"},
                                ],
                            }
                        ],
                        "hint": "输入【序号】",
                        "routes": {"1": self._set_answer_internal, "2": self.enable_answer, "3": self.disable_answer},
                    },
                    "4": {
                        "title": "入群管理 · 设置",
                        "subtitle": "当前这个服务暂时没有额外配置项。",
                        "text": "⚙️ 暂无可配置项",
                        "template": "service_menu",
                        "sections": [
                            {
                                "title": "设置状态",
                                "columns": 1,
                                "items": [
                                    {"index": "-", "title": "暂无可配置项", "description": "后续如果增加更多设置，会显示在这里。", "meta": "返回上一级可继续选择其他模块", "status": "空", "status_tone": "muted"}
                                ],
                            }
                        ],
                        "routes": {},
                    },
                },
            }
            await run_flow(self.group, request_system_flow)
        except Exception as exc:
            print(exc)
            await self.group.send_msg("❌ 操作超时或出错")

    async def enable_answer(self):
        if self.answer_enabled:
            await self.group.send_msg("🚫 入群问答审核已开启")
            return
        if not self._get_answer_patterns():
            await self.group.send_msg("⚠️ 请先设置入群答案，再开启入群问答审核")
            return
        self.answer_enabled = True
        await self.group.send_msg("✅ 入群问答审核已开启")

    async def disable_answer(self):
        if not self.answer_enabled:
            await self.group.send_msg("🚫 入群问答审核已关闭")
            return
        self.answer_enabled = False
        await self.group.send_msg("✅ 入群问答审核已关闭")

    async def enable_welcome(self):
        if self.welcome_enabled:
            await self.group.send_msg("🚫 欢迎功能已开启")
            return
        self.welcome_enabled = True
        await self.group.send_msg("✅ 欢迎功能已开启")

    async def disable_welcome(self):
        if not self.welcome_enabled:
            await self.group.send_msg("🚫 欢迎功能已关闭")
            return
        self.welcome_enabled = False
        await self.group.send_msg("✅ 欢迎功能已关闭")

    def _get_answer_patterns(self) -> List[str]:
        return _normalize_answer_patterns(self.answer)

    def _get_welcome_nodes_map(self) -> Dict[str, List[Dict[str, Any]]]:
        return _normalize_welcome_nodes(self.welcome_nodes)

    @service_notice(desc="新成员入群欢迎", event_type="GroupIncreaseNoticeEvent", priority=5, block=True)
    async def welcome(self, event: GroupIncreaseNoticeEvent):
        if not self.enabled or not self.welcome_enabled:
            return
        if event.user_id == event.self_id:
            return
        await self.group.send_msg(Message(MessageSegment.at(event.user_id) + " 欢迎入群！记得阅读入群指南。"))
        nodes_list = self._get_welcome_nodes_map().get(str(event.group_id), [])
        forward_nodes = []
        for node in nodes_list:
            try:
                forward_nodes.append(
                    MessageSegment.node_custom(
                        user_id=node["user_id"],
                        nickname=node["nickname"],
                        content=Message(node["content"]),
                    )
                )
            except Exception as exc:
                print(f"发送欢迎节点失败: {exc}")
        if forward_nodes:
            await self.group.send_forward_msg(forward_nodes)

    @service_request(desc="入群申请审核", event_type="GroupRequestEvent", priority=5, block=False)
    async def check(self, event: GroupRequestEvent):
        if not self.enabled:
            return
        if event.user_id == event.self_id:
            return
        res = await nonebot.get_bot().get_stranger_info(user_id=event.user_id)
        name = res["nickname"]
        if event.sub_type == "invite":
            await self.group.send_msg(f"✅ 用户{name}被邀请入群。")
            await self.group.set_group_add(event, True)
            return
        if not self.answer_enabled:
            await self.group.send_msg(f"ℹ️ 用户{name}申请入群，当前未开启自动问答审核，请管理员手动处理。")
            return
        raw_answer = event.comment.strip().upper()
        correct_patterns = self._get_answer_patterns()
        if not correct_patterns:
            await self.group.send_msg(f"ℹ️ 用户{name}申请入群，但当前未配置自动审核答案，请管理员手动处理。")
            return
        answer_match = re.search(r"答案：\s*(\S+)", raw_answer, re.IGNORECASE)
        if answer_match:
            raw_answer = answer_match.group(1)
        raw_answer = raw_answer.strip().upper()
        if raw_answer in correct_patterns:
            await self.group.send_msg(f"✅ 用户{name}回答{raw_answer}并加入了群聊。")
            await self.group.set_group_add(event, True)
            return
        await self.group.send_msg(f"❌ 用户{name}回答{raw_answer}并被拒绝入群。")
        await self.group.set_group_add(event, False, reason="❌ 请正确回答入群问题(群助手自动审核)")

    @service_action(cmd="设置欢迎内容", desc="新成员入群时，会发送欢迎内容。")
    @check_enabled
    async def set_welcome_nodes(self):
        await self.group.send_msg("⚡ 请输入每条欢迎消息内容，输入完成后发送 '完成'，输入 '退出' 可取消设置")
        nodes = []
        while True:
            response = await wait_for(60)
            if not response or response.strip().lower() == "退出":
                await self.group.send_msg("❌ 欢迎内容设置已取消")
                return
            if response.strip().lower() == "完成":
                break
            nodes.append({"user_id": self.group.self_id, "nickname": "欢迎助手", "content": response.strip()})
            await self.group.send_msg("✅ 已添加该欢迎内容，继续输入下一条或发送 '完成'")
        config_nodes = self._get_welcome_nodes_map()
        config_nodes[str(self.group.group_id)] = nodes
        self.welcome_nodes = config_nodes
        await self.group.send_msg("✅ 欢迎内容设置完成")

    @service_action(cmd="设置入群答案", need_arg=True, desc="判断是否通过入群申请的依据。")
    @check_enabled
    async def set_answer_cmd(self, arg: Message = CommandArg()):
        await self._set_answer_internal(arg)

    async def _set_answer_internal(self, arg: Message | None = None):
        if arg:
            raw_text = arg.extract_plain_text().strip()
        else:
            await self.group.send_msg("⚡ 请输入入群答案，多个答案用英文逗号分隔\n示例：北京,上海\n输入【退出】可取消")
            response = await wait_for(60)
            if not response or response.strip().lower() == "退出":
                await self.group.send_msg("❌ 入群答案设置已取消")
                return
            raw_text = response.strip()
        answers = _normalize_answer_patterns(raw_text)
        if not answers:
            await self.group.send_msg("❌ 未检测到有效答案")
            return
        self.answer = answers
        await self.group.send_msg(f"✅ 入群答案已更新：{', '.join(answers)}")

__all__ = [
    "RequestService",
    "_normalize_answer_patterns",
    "_normalize_welcome_nodes",
]
