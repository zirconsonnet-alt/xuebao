import traceback

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.support.core import Services
from src.vendors.nonebot_plugin_law.controller import VoteController
from src.vendors.nonebot_plugin_law.manager import VoteManager
from src.vendors.nonebot_plugin_law.metadata import VoteMetadataFacade, finish_vote_session, start_vote_session
from src.vendors.nonebot_plugin_law.runtime import build_vote_handler, wait_for_condition
from src.vendors.nonebot_plugin_law.service import (
    GOVERNANCE_DEFAULT_CONFIG,
    GovernanceManager,
    build_governance_manager,
    build_vote_metadata_facade,
)
from src.vendors.nonebot_plugin_law.strategies import (
    BanStrategy,
    GeneralStrategy,
    KickStrategy,
    SetStrategy,
    Strategy,
    TopicStrategy,
)
from src.vendors.nonebot_plugin_law.use_cases import (
    ApproveTopicAndRefreshNoticeUseCase,
    AwardHonorForTopicVoteUseCase,
    CreateTopicAndChargeUseCase,
)
from .base import BaseService, config_property, service_action


class VoteService(BaseService):
    service_type = Services.Vote
    allowed_governance_group_ids = {1034063784}
    command_usage_examples = {
        "设置荣誉群主": "@成员",
        "添加元老": "@成员",
        "移除元老": "@成员",
        "发起荣誉群主选举": "@成员 愿意履职并接受监督",
        "发起元老选举": "@成员 候选理由",
        "发起弹劾荣誉群主": "严重失职 事实与理由",
        "发起弹劾元老": "@成员 严重失职 事实与理由",
        "发起重组元老会": "制度性失灵 事实与理由",
        "发起紧急防护": "@成员 临时禁言 1h 紧急理由",
        "发起正式处分": "@成员 长期禁言 7d 事实与理由",
        "日常管理": "@成员 警告 理由",
        "申请处分复核": "12 关键证据失实 复核理由",
        "发起提案": "普通议题案 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 否",
        "审查提案": "12 通过",
        "补正提案": "12 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 否",
        "申请提案复核": "12 程序错误说明",
        "指定临时代理": "@成员 说明",
        "发起职权争议表决": "标题 | 争议事实与请求裁决 | 具体裁决文本或措施 | 生效时间/期限/失效条件 | 否",
        "联署治理案件": "12",
        "推进治理案件": "12",
        "治理禁言": "@成员 1h 理由",
        "治理放逐": "@成员 理由",
    }
    default_config = {
        "enabled": True,
        "min_voters_topic": 5,
        "min_voters_kick": 5,
        "min_voters_ban": 3,
        **GOVERNANCE_DEFAULT_CONFIG,
    }
    enabled = config_property("enabled")
    min_voters_topic = config_property("min_voters_topic")
    min_voters_kick = config_property("min_voters_kick")
    min_voters_ban = config_property("min_voters_ban")

    @service_action(cmd="发起议题", desc="发起一个议题投票", tool_callable=True)
    async def start_topic_vote(self, event: GroupMessageEvent):
        try:
            if not await self._ensure_motion_initiation_allowed(event, action_label="发起议题"):
                return
            metadata = self._build_metadata_facade()
            vote_controller = VoteController(self.group, TopicStrategy(), metadata)
            await vote_controller.vote(event)
        except Exception as exc:
            print(exc)
            traceback.print_exc()

    @service_action(cmd="发起放逐", desc="发起放逐成员投票", tool_callable=True, require_admin=True)
    async def start_kick_vote(self, event: GroupMessageEvent):
        try:
            if not await self._ensure_motion_initiation_allowed(event, action_label="发起放逐投票"):
                return
            metadata = self._build_metadata_facade()
            vote_controller = VoteController(self.group, KickStrategy(), metadata)
            await vote_controller.vote(event)
        except Exception as exc:
            print(exc)
            traceback.print_exc()

    @service_action(cmd="发起禁言", desc="发起禁言成员投票", tool_callable=True, require_admin=True)
    async def start_ban_vote(self, event: GroupMessageEvent):
        try:
            if not await self._ensure_motion_initiation_allowed(event, action_label="发起禁言投票"):
                return
            metadata = self._build_metadata_facade()
            vote_controller = VoteController(self.group, BanStrategy(), metadata)
            await vote_controller.vote(event)
        except Exception as exc:
            print(exc)
            traceback.print_exc()

    @service_action(cmd="发起投票", desc="发起一个通用投票", tool_callable=True)
    async def start_general_vote(self, event: GroupMessageEvent):
        try:
            if not await self._ensure_motion_initiation_allowed(event, action_label="发起通用投票"):
                return
            metadata = self._build_metadata_facade()
            vote_controller = VoteController(self.group, GeneralStrategy(), metadata)
            await vote_controller.vote(event)
        except Exception as exc:
            print(exc)
            traceback.print_exc()

    @service_action(cmd="治理初始化", desc="导入群法律模板并初始化治理成员")
    async def initialize_governance(self, event: GroupMessageEvent):
        await self._run_governance("initialize", event)

    @service_action(cmd="同步治理成员", desc="同步群成员档案与平台管理员信息")
    async def sync_governance_members(self, event: GroupMessageEvent):
        await self._run_governance("sync_members_command", event)

    @service_action(cmd="查看治理状态", desc="查看荣誉群主、元老会、冻结与活跃案件")
    async def show_governance_status(self, event: GroupMessageEvent):
        await self._run_governance("show_status", event)

    @service_action(cmd="指令用法", desc="查询任意服务指令的示例聊天记录", need_arg=True, allow_when_disabled=True)
    async def show_command_usage(self, event: GroupMessageEvent, arg: Message):
        await self.group.send_msg(self._build_command_usage_text(arg.extract_plain_text()))

    @service_action(cmd="设置荣誉群主", desc="设置唯一荣誉群主并同步平台管理员", need_arg=True)
    async def set_honor_owner(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("set_honor_owner_command", event, arg)

    @service_action(cmd="添加元老", desc="手动添加元老会成员", need_arg=True)
    async def add_elder(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("add_elder_command", event, arg)

    @service_action(cmd="移除元老", desc="手动移除元老会成员", need_arg=True)
    async def remove_elder(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("remove_elder_command", event, arg)

    @service_action(cmd="发起荣誉群主选举", desc="对候选人发起荣誉群主公投", need_arg=True)
    async def create_honor_owner_election(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_honor_owner_election_command", event, arg)

    @service_action(cmd="发起元老选举", desc="对候选人发起元老补选或换届提名", need_arg=True)
    async def create_elder_election(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_elder_election_command", event, arg)

    @service_action(cmd="发起弹劾荣誉群主", desc="元老会发起荣誉群主弹劾", need_arg=True)
    async def create_honor_owner_impeachment(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_honor_owner_impeachment_command", event, arg)

    @service_action(cmd="发起弹劾元老", desc="群成员发起元老弹劾", need_arg=True)
    async def create_elder_impeachment(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_elder_impeachment_command", event, arg)

    @service_action(cmd="发起重组元老会", desc="发起重组元老会民主动议", need_arg=True)
    async def create_elder_reboot(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_elder_reboot_command", event, arg)

    @service_action(cmd="发起紧急防护", desc="发起紧急防护联署", need_arg=True)
    async def create_emergency_protection(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_emergency_protection_command", event, arg)

    @service_action(cmd="发起正式处分", desc="发起正式处分申请或联署立案", need_arg=True)
    async def create_formal_discipline(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_formal_discipline_command", event, arg)

    @service_action(cmd="日常管理", desc="执行提醒、警告、短期禁言或提案动议限制", need_arg=True)
    async def daily_management(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("daily_management_command", event, arg)

    @service_action(cmd="申请处分复核", desc="对已公示的正式处分结果申请复核", need_arg=True)
    async def create_formal_discipline_review(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_formal_discipline_review_command", event, arg)

    @service_action(cmd="发起提案", desc="发起普通议题、基础治理条例、宪制修订或临时措施提案", need_arg=True)
    async def create_governance_proposal(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_proposal_command", event, arg)

    @service_action(cmd="审查提案", desc="元老会对提案作通过、补正或程序性驳回决定", need_arg=True)
    async def review_governance_proposal(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("review_proposal_command", event, arg)

    @service_action(cmd="补正提案", desc="按补正要求重新提交提案内容", need_arg=True)
    async def correct_governance_proposal(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("correct_proposal_command", event, arg)

    @service_action(cmd="申请提案复核", desc="对提案程序错误提出复核请求并留痕", need_arg=True)
    async def request_governance_proposal_review(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("request_proposal_review_command", event, arg)

    @service_action(cmd="指定临时代理", desc="在荣誉群主空缺期指定一名元老担任临时程序代理", need_arg=True)
    async def designate_temporary_proxy(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("designate_temporary_proxy_command", event, arg)

    @service_action(cmd="发起职权争议表决", desc="在机器人临时自治期将荣誉群主职权争议直达全体表决", need_arg=True)
    async def create_vacancy_dispute_vote(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("create_vacancy_dispute_vote_command", event, arg)

    @service_action(cmd="联署治理案件", desc="联署一个治理案件", need_arg=True)
    async def support_governance_case(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("support_case_command", event, arg)

    @service_action(cmd="推进治理案件", desc="推进已满足条件的治理案件", need_arg=True)
    async def advance_governance_case(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("advance_case_command", event, arg)

    @service_action(cmd="查看治理案件", desc="查看最近治理案件")
    async def list_governance_cases(self, event: GroupMessageEvent):
        await self._run_governance("list_cases_command", event)

    @service_action(cmd="治理禁言", desc="荣誉群主或元老会紧急代理执行禁言", need_arg=True)
    async def governance_ban(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("govern_ban_command", event, arg)

    @service_action(cmd="治理放逐", desc="荣誉群主执行治理放逐", need_arg=True)
    async def governance_kick(self, event: GroupMessageEvent, arg: Message):
        await self._run_governance("govern_kick_command", event, arg)

    def _build_metadata_facade(self) -> VoteMetadataFacade:
        return build_vote_metadata_facade(self.group)

    def _build_governance_manager(self) -> GovernanceManager:
        return build_governance_manager(self)

    def _build_command_usage_text(self, raw_query: str) -> str:
        from difflib import get_close_matches

        from src.services import registry

        query = self._normalize_command_query(raw_query)
        if not query:
            return "请输入要查询的指令，例如：/指令用法 设置荣誉群主"

        indexed_commands = []
        for service_type in registry.service_manager.get_all_service_types():
            for command in registry.service_manager.get_service_commands(service_type):
                indexed_commands.append((service_type, command))

        matches = [
            (service_type, command)
            for service_type, command in indexed_commands
            if query == command.cmd or query.startswith(f"{command.cmd} ")
        ]
        if not matches:
            command_names = [command.cmd for _, command in indexed_commands]
            suggestions = get_close_matches(query.split()[0], command_names, n=3, cutoff=0.45)
            hint = f"\n你可能想查：{', '.join(suggestions)}" if suggestions else ""
            return f"未找到指令：{raw_query.strip() or query}{hint}\n示例：/指令用法 设置荣誉群主"

        service_type, command = max(matches, key=lambda item: len(item[1].cmd))
        example_arg = self.command_usage_examples.get(command.cmd, "测试参数" if command.need_arg else "")
        example = f"/{command.cmd}"
        if command.need_arg and example_arg:
            example += f" {example_arg}"

        lines = [
            f"【{command.cmd}】",
            f"服务：{service_type.chinese_name}",
        ]
        if command.desc:
            lines.append(f"用途：{command.desc}")
        lines.extend(
            [
                f"需要参数：{'是' if command.need_arg else '否'}",
                "示例聊天记录：",
                f"群友：{example}",
                f"机器人：开始处理【{command.desc or command.cmd}】",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _normalize_command_query(raw_query: str) -> str:
        text = str(raw_query or "").strip()
        while text.startswith("/"):
            text = text[1:].lstrip()
        return text

    async def check_service_availability(self, *, action: str, action_meta=None, event=None) -> tuple[bool, str]:
        if action == "disable_service":
            return True, ""

        group_id = int(getattr(event, "group_id", getattr(self.group, "group_id", 0)) or 0)
        if group_id not in self.allowed_governance_group_ids:
            allowed_groups = "、".join(str(item) for item in sorted(self.allowed_governance_group_ids))
            return (
                False,
                f"⛔ 群法律治理插件仅允许在授权群使用。当前授权群：{allowed_groups}。",
            )

        bot_id = getattr(event, "self_id", None)
        if bot_id in (None, ""):
            try:
                bot_id = self.group.self_id
            except Exception:
                bot_id = None
        if bot_id in (None, ""):
            return False, "⛔ 无法确认机器人是否为群主，群法律治理插件暂不可用。"

        try:
            bot_member = await self.group.get_group_member_info(int(bot_id))
        except Exception:
            return False, "⛔ 无法确认机器人是否为群主，群法律治理插件暂不可用。"

        if str((bot_member or {}).get("role") or "").lower() != "owner":
            return False, "⛔ 群法律治理插件只能在机器人为群主的群开启或使用。"
        return True, ""

    async def _ensure_motion_initiation_allowed(self, event: GroupMessageEvent, *, action_label: str) -> bool:
        manager = self._build_governance_manager()
        allowed, denied_reason = manager.ensure_motion_initiation_permission(
            event.user_id,
            action_label=action_label,
        )
        if allowed:
            return True
        await self.group.send_msg(denied_reason)
        return False

    async def _run_governance(self, method_name: str, *args):
        try:
            manager = self._build_governance_manager()
            if method_name not in {"initialize", "sync_members_command", "advance_case_command"}:
                governance_event = next(
                    (arg for arg in args if hasattr(arg, "group_id") and hasattr(arg, "user_id")),
                    None,
                )
                await manager.auto_advance_due_cases(
                    trigger=f"service:{method_name}",
                    actor_id=getattr(governance_event, "user_id", None),
                )
            method = getattr(manager, method_name)
            await method(*args)
        except Exception as exc:
            print(exc)
            traceback.print_exc()


__all__ = [
    "ApproveTopicAndRefreshNoticeUseCase",
    "AwardHonorForTopicVoteUseCase",
    "BanStrategy",
    "CreateTopicAndChargeUseCase",
    "GeneralStrategy",
    "KickStrategy",
    "SetStrategy",
    "Strategy",
    "TopicStrategy",
    "VoteController",
    "VoteManager",
    "VoteMetadataFacade",
    "VoteService",
    "build_vote_handler",
    "finish_vote_session",
    "start_vote_session",
    "wait_for_condition",
    "GovernanceManager",
]
