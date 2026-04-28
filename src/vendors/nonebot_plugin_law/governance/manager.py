import asyncio
import math
import re
import traceback
from datetime import datetime, timedelta
from fractions import Fraction
from types import SimpleNamespace
from typing import TYPE_CHECKING, Dict, List, Optional

from arclet.alconna import Alconna
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot_plugin_alconna import on_alconna

from ..metadata import (
    VoteMetadataFacade,
    _build_idempotency_key,
    _build_session_key,
)
from ..spec import CASE_TYPE_LABELS, load_law_spec
from .storage import GovernanceStorage

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from src.services.vote import VoteService


class GovernanceManager:
    _CASE_THRESHOLD_REFS = {
        "ordinary_proposal": "ordinary_proposal",
        "honor_owner_election": "honor_owner_election_single_candidate",
        "honor_owner_impeachment": "honor_owner_impeachment",
        "elder_impeachment": "elder_impeachment",
        "elder_reboot": "elder_reboot",
    }
    _PROPOSAL_TYPE_LABELS = {
        "ordinary_proposal": "普通议题案",
        "basic_governance_norm": "基础治理条例案",
        "constitutional_amendment": "宪制修订案",
        "temporary_measure": "临时管理措施",
        "emergency_motion": "紧急动议",
    }
    _PROPOSAL_TYPE_ALIASES = {
        "普通议题": "ordinary_proposal",
        "普通议题案": "ordinary_proposal",
        "普通提案": "ordinary_proposal",
        "ordinary_proposal": "ordinary_proposal",
        "基础治理条例": "basic_governance_norm",
        "基础治理条例案": "basic_governance_norm",
        "治理条例": "basic_governance_norm",
        "条例修订": "basic_governance_norm",
        "basic_governance_norm": "basic_governance_norm",
        "宪制修订": "constitutional_amendment",
        "宪制修订案": "constitutional_amendment",
        "宪法修订": "constitutional_amendment",
        "修宪": "constitutional_amendment",
        "constitutional_amendment": "constitutional_amendment",
        "临时管理措施": "temporary_measure",
        "临时措施": "temporary_measure",
        "temporary_measure": "temporary_measure",
        "紧急动议": "emergency_motion",
        "emergency_motion": "emergency_motion",
    }
    _PROPOSAL_DISCUSSION_HOURS = {
        "ordinary_proposal": 12,
        "basic_governance_norm": 24,
        "constitutional_amendment": 48,
        "temporary_measure": 12,
    }
    _PROPOSAL_THRESHOLD_REFS = {
        "ordinary_proposal": "ordinary_proposal",
        "basic_governance_norm": "basic_governance_norm",
        "constitutional_amendment": "constitutional_amendment",
        "temporary_measure": "ordinary_proposal",
    }
    _PROPOSAL_ESCALATION_FIXED_SUPPORTERS = 5
    _PROPOSAL_ESCALATION_RATIO = Fraction(1, 10)
    _PROPOSAL_REVIEW_HOURS = 48
    _TEMPORARY_MEASURE_MAX_DAYS = 7
    _BOOLEAN_TRUE_ALIASES = {"是", "高风险", "涉及高风险", "需要", "需要高风险", "yes", "true", "1"}
    _BOOLEAN_FALSE_ALIASES = {"否", "非高风险", "不涉及高风险", "不需要", "no", "false", "0"}
    _HONOR_OWNER_CANDIDATE_MIN_JOIN_DAYS = 14
    _HONOR_OWNER_TERM_DAYS = 90
    _HONOR_OWNER_CARETAKER_MAX_DAYS = 7
    _HONOR_OWNER_RECOMMENDATION_FIXED_SUPPORTERS = 5
    _HONOR_OWNER_RECOMMENDATION_RATIO = Fraction(1, 10)
    _HONOR_OWNER_TEMPORARY_AUTONOMY_RESTART_HOURS = 72
    _HONOR_OWNER_CARETAKER_SCOPE = "仅可处理日常事务和紧急安全事项，不得行使高风险权力"
    _ELDER_CANDIDATE_MIN_JOIN_DAYS = 14
    _ELDER_TERM_DAYS = 90
    _REBOOT_TEMPORARY_COLLECTIVE_SUPERVISION_FAILURES = 2
    _FORMAL_DISCIPLINE_SCOPE_SANCTIONS = (
        "long_mute",
        "restrict_vote",
        "restrict_candidacy",
        "remove_member",
    )
    _FORMAL_SANCTION_LABELS = {
        "long_mute": "长期禁言",
        "restrict_candidacy": "限制被选举资格",
        "restrict_vote": "限制表决资格",
        "remove_member": "移出群聊",
    }
    _DAILY_MANAGEMENT_ACTION_LABELS = {
        "reminder": "提醒",
        "warning": "警告",
        "short_mute": "短期禁言",
        "motion_restriction": "限制发起提案/动议",
    }
    _DAILY_MANAGEMENT_ACTION_ALIASES = {
        "提醒": "reminder",
        "reminder": "reminder",
        "警告": "warning",
        "warning": "warning",
        "短期禁言": "short_mute",
        "短禁言": "short_mute",
        "short_mute": "short_mute",
        "限制提案": "motion_restriction",
        "提案限制": "motion_restriction",
        "限制动议": "motion_restriction",
        "动议限制": "motion_restriction",
        "限制提案动议": "motion_restriction",
        "限制发起": "motion_restriction",
        "motion_restriction": "motion_restriction",
    }
    _DAILY_MANAGEMENT_FORMAL_ONLY_ALIASES = {
        "长期禁言": "long_mute",
        "限制表决": "restrict_vote",
        "限制表决资格": "restrict_vote",
        "限制被选举": "restrict_candidacy",
        "限制被选举资格": "restrict_candidacy",
        "限制竞选": "restrict_candidacy",
        "限制竞选资格": "restrict_candidacy",
        "移出": "remove_member",
        "移出群聊": "remove_member",
        "放逐": "remove_member",
    }
    _FORMAL_SANCTION_ALIASES = {
        "长期禁言": "long_mute",
        "禁言": "long_mute",
        "long_mute": "long_mute",
        "限制参选": "restrict_candidacy",
        "限制候选": "restrict_candidacy",
        "限制被选举": "restrict_candidacy",
        "限制被选举资格": "restrict_candidacy",
        "restrict_candidacy": "restrict_candidacy",
        "限制表决": "restrict_vote",
        "限制投票": "restrict_vote",
        "限制表决资格": "restrict_vote",
        "restrict_vote": "restrict_vote",
        "移出": "remove_member",
        "移出群聊": "remove_member",
        "放逐": "remove_member",
        "remove_member": "remove_member",
    }
    _FORMAL_SANCTION_THRESHOLD_REFS = {
        "long_mute": "formal_discipline_long_mute",
        "restrict_candidacy": "formal_discipline_restrict_candidacy",
        "restrict_vote": "formal_discipline_restrict_vote_or_remove",
        "remove_member": "formal_discipline_restrict_vote_or_remove",
    }
    _FORMAL_SANCTION_FALLBACKS = {
        "remove_member": "restrict_vote",
        "restrict_vote": "restrict_candidacy",
        "restrict_candidacy": "long_mute",
        "long_mute": None,
    }
    _FORMAL_RESTRICTION_LOCK_TYPES = {
        "restrict_vote": "formal_discipline_restrict_vote",
        "restrict_candidacy": "formal_discipline_restrict_candidacy",
    }
    _FORMAL_REVIEW_REASON_ALIASES = {
        "新证据": "new_evidence",
        "新材料": "new_evidence",
        "关键程序错误": "procedural_error",
        "程序错误": "procedural_error",
        "程序违法": "procedural_error",
        "程序瑕疵": "procedural_error",
        "事实错误": "fact_error",
        "事实认定错误": "fact_error",
        "认定错误": "fact_error",
        "处分失衡": "manifest_disproportion",
        "明显失衡": "manifest_disproportion",
        "明显过重": "manifest_disproportion",
        "处罚过重": "manifest_disproportion",
    }
    _FORMAL_REVIEW_REASON_LABELS = {
        "new_evidence": "新证据出现",
        "procedural_error": "关键程序错误",
        "fact_error": "主要事实明显认定错误",
        "manifest_disproportion": "处分明显失衡",
    }
    _LEGACY_REVIEW_EXCEPTION_LABELS = {
        "major_procedural_illegality": "重大程序违法",
        "safety_risk": "安全风险",
    }
    _LEGACY_REVIEW_SAFETY_RISK_KEYWORDS = (
        "安全风险",
        "重大安全风险",
        "严重安全风险",
        "持续安全风险",
        "现实安全风险",
        "再次危害",
        "继续危害",
        "仍有危险",
    )
    _HONOR_OWNER_IMPEACHMENT_REASON_ALIASES = {
        "滥用高风险权力": "abuse_high_risk_power",
        "滥用高风险权限": "abuse_high_risk_power",
        "高风险权力滥用": "abuse_high_risk_power",
        "越权": "abuse_high_risk_power",
        "阻碍选举": "obstruct_lawful_process",
        "阻碍投票": "obstruct_lawful_process",
        "阻碍弹劾": "obstruct_lawful_process",
        "阻碍重组": "obstruct_lawful_process",
        "阻碍复核": "obstruct_lawful_process",
        "阻碍程序": "obstruct_lawful_process",
        "报复": "retaliation_or_discrimination",
        "歧视": "retaliation_or_discrimination",
        "严重失职": "serious_dereliction",
        "程序失职": "serious_dereliction",
        "玩忽职守": "serious_dereliction",
        "怠于履职": "serious_dereliction",
        "拒绝紧急防护复核": "refuse_emergency_review",
        "拒绝复核": "refuse_emergency_review",
        "七日不处理": "seven_day_dereliction",
        "7日不处理": "seven_day_dereliction",
        "连续七日无正当理由不处理": "seven_day_dereliction",
        "连续7日无正当理由不处理": "seven_day_dereliction",
        "严重违反群规": "serious_rule_violation",
        "严重违法群规": "serious_rule_violation",
        "严重破坏秩序": "serious_rule_violation",
        "危害安全": "serious_rule_violation",
    }
    _HONOR_OWNER_IMPEACHMENT_REASON_LABELS = {
        "abuse_high_risk_power": "滥用高风险权力",
        "obstruct_lawful_process": "阻碍合法选举、表决或复核程序",
        "retaliation_or_discrimination": "报复或歧视成员",
        "serious_dereliction": "严重失职或怠于履职",
        "refuse_emergency_review": "拒绝履行紧急防护复核责任",
        "seven_day_dereliction": "连续七日无正当理由不处理必要群务",
        "serious_rule_violation": "严重违反群规并危害秩序或安全",
    }
    _ELDER_IMPEACHMENT_REASON_ALIASES = {
        "监督失职": "supervision_dereliction",
        "复核失职": "supervision_dereliction",
        "不回应": "supervision_dereliction",
        "不处理": "supervision_dereliction",
        "滥用紧急代理": "abuse_proxy_or_review_power",
        "滥用代理权": "abuse_proxy_or_review_power",
        "滥用复核权": "abuse_proxy_or_review_power",
        "阻碍提案": "obstruct_lawful_process",
        "阻碍弹劾": "obstruct_lawful_process",
        "阻碍选举": "obstruct_lawful_process",
        "阻碍重组": "obstruct_lawful_process",
        "阻碍程序": "obstruct_lawful_process",
        "泄露隐私": "privacy_or_record_misconduct",
        "报复": "privacy_or_record_misconduct",
        "销毁记录": "privacy_or_record_misconduct",
        "毁坏记录": "privacy_or_record_misconduct",
        "回避违规": "serious_recusal_violation",
        "不回避": "serious_recusal_violation",
        "严重违反回避": "serious_recusal_violation",
    }
    _ELDER_IMPEACHMENT_REASON_LABELS = {
        "supervision_dereliction": "监督、复核或回应严重失职",
        "abuse_proxy_or_review_power": "滥用紧急代理或复核权",
        "obstruct_lawful_process": "阻碍合法提案、弹劾、选举或重组程序",
        "privacy_or_record_misconduct": "泄露隐私、报复成员或毁坏记录",
        "serious_recusal_violation": "严重违反回避义务",
    }
    _ELDER_REBOOT_REASON_ALIASES = {
        "长期无法形成法定人数": "long_no_quorum_or_timeout",
        "无法形成法定人数": "long_no_quorum_or_timeout",
        "连续7日不处理关键程序": "long_no_quorum_or_timeout",
        "连续七日不处理关键程序": "long_no_quorum_or_timeout",
        "连续7日不处理": "long_no_quorum_or_timeout",
        "连续七日不处理": "long_no_quorum_or_timeout",
        "阻碍合法议题": "collective_obstruction",
        "阻碍弹劾": "collective_obstruction",
        "阻碍选举": "collective_obstruction",
        "阻碍复核": "collective_obstruction",
        "阻碍重组": "collective_obstruction",
        "阻碍程序": "collective_obstruction",
        "集体滥用紧急代理权": "collective_abuse_of_review_power",
        "集体滥用紧急代理": "collective_abuse_of_review_power",
        "集体滥用审查权": "collective_abuse_of_review_power",
        "滥用紧急代理权": "collective_abuse_of_review_power",
        "滥用审查权": "collective_abuse_of_review_power",
        "失去代表性": "lost_representativeness",
        "拒绝补选": "lost_representativeness",
        "拒绝换届": "lost_representativeness",
        "监督机制整体失灵": "other_institutional_breakdown",
        "制度性理由": "other_institutional_breakdown",
        "制度失灵": "other_institutional_breakdown",
        "整体失灵": "other_institutional_breakdown",
    }
    _ELDER_REBOOT_REASON_LABELS = {
        "long_no_quorum_or_timeout": "长期无法形成法定人数或连续七日不处理关键程序",
        "collective_obstruction": "元老会集体阻碍合法议题、弹劾、选举、重组或复核",
        "collective_abuse_of_review_power": "元老会集体滥用紧急代理权或审查权",
        "lost_representativeness": "元老会明显失去代表性并拒绝补选或换届",
        "other_institutional_breakdown": "其他足以证明监督机制整体失灵的制度性理由",
    }
    _ELDER_REBOOT_FORBIDDEN_REASON_KEYWORDS = (
        "不满裁决",
        "不服裁决",
        "政治立场",
        "立场差异",
        "个人恩怨",
        "私人恩怨",
        "看不顺眼",
    )

    def __init__(self, service: "VoteService", metadata: VoteMetadataFacade):
        self.service = service
        self.group = service.group
        self.db = service.group.db
        self.metadata = metadata
        self.storage = GovernanceStorage(self.db)

    async def initialize(self, event: GroupMessageEvent) -> None:
        if not await self._ensure_bootstrap_permission(event):
            return
        imported_count = self.storage.import_law_templates(self.group.laws_path)
        sync_result = await self.sync_members(silent=True)
        human_admins = sync_result["human_admin_ids"]

        lines = [
            "治理初始化完成。",
            f"- 已导入群法律模板：{imported_count} 份",
            f"- 已同步群成员档案：{sync_result['member_count']} 人",
        ]
        if len(human_admins) == 1:
            summary = await self._set_honor_owner(
                target_user_id=human_admins[0],
                operator_id=event.user_id,
                source="bootstrap_auto_detect",
                sync_platform_admin=False,
            )
            lines.append(f"- 已自动识别唯一管理员为荣誉群主：{summary['display_name']}")
        elif len(human_admins) == 0:
            lines.append("- 当前未检测到人类管理员，请使用“设置荣誉群主 @成员”完成绑定。")
        else:
            lines.append("- 检测到多个管理员，未自动绑定荣誉群主，请先清理后再设置。")
        lines.append("- 如需初始化元老会，请使用“添加元老 @成员”。")
        await self.group.send_msg("\n".join(lines))

    async def sync_members_command(self, event: GroupMessageEvent) -> None:
        if not await self._ensure_bootstrap_permission(event):
            return
        result = await self.sync_members(silent=False)
        await self.group.send_msg(
            "\n".join(
                [
                    "治理成员同步完成。",
                    f"- 成员总数：{result['member_count']}",
                    f"- 平台群主：{self._format_user_list(result['platform_owner_ids']) or '无'}",
                    f"- 平台管理员：{self._format_user_list(result['human_admin_ids']) or '无'}",
                ]
            )
        )

    async def show_status(self, event: GroupMessageEvent) -> None:
        self._release_expired_formal_discipline_locks()
        await self.sync_members(silent=True)
        self._ensure_honor_owner_term_runtime_state()
        honor_owner_id = self.storage.get_active_role_user("honor_owner")
        if honor_owner_id and int(event.user_id) == int(honor_owner_id):
            self._record_honor_owner_governance_summary_publication(
                actor_id=int(event.user_id),
                trigger="show_status",
            )
        elder_ids = self.storage.get_active_role_users("elder")
        desired_elder_seat_count = self._desired_elder_seat_count()
        elder_quorum_threshold = self._elder_meeting_quorum_threshold()
        elder_special_threshold = self._elder_special_decision_threshold()
        suspended_ids = self.storage.get_active_role_users("suspended")
        human_admin_ids = self.storage.get_platform_human_admin_ids(self.group.self_id)
        active_cases = self.storage.list_active_cases(limit=8)
        recent_cases = self.storage.list_recent_cases(limit=12)
        active_locks = self.storage.list_active_locks()

        lines = [
            "治理状态：",
            f"- 群法律模板：{len(self.group.get_all_laws())} 份",
            f"- 成员档案：{self.storage.member_count()} 人",
            f"- 荣誉群主：{self._format_user(honor_owner_id) if honor_owner_id else '未设置'}",
            f"- 元老会：{self._format_user_list(elder_ids) or '未设置'}",
            f"- 治理禁权成员：{self._format_user_list(suspended_ids) or '无'}",
            f"- 平台管理员：{self._format_user_list(human_admin_ids) or '无'}",
        ]
        lines.extend(self._format_law_regime_status_lines())
        lines.extend(self._format_honor_owner_status_lines(honor_owner_id=honor_owner_id))
        if desired_elder_seat_count > 0:
            if elder_quorum_threshold > 0 and elder_special_threshold > 0:
                lines.append(
                    f"- 元老会席位：{len(elder_ids)}/{desired_elder_seat_count}，法定参与至少 {elder_quorum_threshold} 人，特别表决至少 {elder_special_threshold} 人"
                )
            else:
                lines.append(f"- 元老会席位：{len(elder_ids)}/{desired_elder_seat_count}")
        if honor_owner_id and human_admin_ids != [honor_owner_id]:
            lines.append("- 状态告警：平台管理员与数据库中的荣誉群主不一致。")
        if active_cases:
            lines.append("- 活跃案件：")
            for case in active_cases:
                lines.append(f"  {self._format_case_summary(case, include_proposer=False)}")
        else:
            lines.append("- 活跃案件：无")
        pending_deadline_notice = self._find_pending_new_council_election_notice(recent_cases)
        if pending_deadline_notice:
            lines.append(f"- 重组后续：{pending_deadline_notice}")
        reboot_supervision_notice = self._find_reboot_supervision_notice(recent_cases)
        if reboot_supervision_notice:
            lines.append(f"- 重组监督：{reboot_supervision_notice}")
        if active_locks:
            lines.append("- 生效冻结：")
            for lock in active_locks:
                reason = str(lock.get("reason") or "").strip()
                lines.append(
                    f"  {self._format_lock_type(str(lock['lock_type']))} / 目标：{self._format_user(lock.get('target_user_id'))} / 来源案件：{lock.get('source_case_id') or '-'}"
                    + (f" / {reason}" if reason else "")
                )
        else:
            lines.append("- 生效冻结：无")
        await self.group.send_msg("\n".join(lines))

    async def set_honor_owner_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_bootstrap_permission(event):
            return
        target_user_id, _ = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“设置荣誉群主 @成员”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("机器人不能被设置为荣誉群主。")
            return
        summary = await self._set_honor_owner(
            target_user_id=target_user_id,
            operator_id=event.user_id,
            source="manual_designation",
            sync_platform_admin=True,
        )
        lines = [f"已设置荣誉群主：{summary['display_name']}"]
        if summary.get("revoked_elder"):
            lines.append("- 已按职务分离要求同步解除其元老身份")
        if summary["platform_sync_warnings"]:
            lines.append(f"- 平台管理员同步提醒：{'; '.join(summary['platform_sync_warnings'])}")
        else:
            lines.append("- 平台管理员同步：已完成")
        await self.group.send_msg("\n".join(lines))

    async def add_elder_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_bootstrap_permission(event):
            return
        target_user_id, _ = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“添加元老 @成员”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("机器人不能被设置为元老。")
            return
        if self.storage.get_active_role_user("honor_owner") == target_user_id:
            await self.group.send_msg("荣誉群主不得兼任元老，请先改任或通过正式程序完成调整。")
            return
        await self._ensure_member_profile(target_user_id)
        self.storage.set_role_status(
            user_id=target_user_id,
            role_code="elder",
            status="active",
            source="manual_seed",
            operator_id=event.user_id,
            notes="manual_seed",
        )
        await self.group.send_msg(f"已添加元老：{self._format_user(target_user_id)}")

    async def remove_elder_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_bootstrap_permission(event):
            return
        target_user_id, _ = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“移除元老 @成员”。")
            return
        self.storage.revoke_role(target_user_id, "elder", operator_id=event.user_id, notes="manual_remove")
        await self.group.send_msg(f"已移除元老：{self._format_user(target_user_id)}")

    async def create_honor_owner_election_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起选举。")
            return
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起荣誉群主选举",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        target_user_id, reason = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“发起荣誉群主选举 @成员 [理由]”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("机器人不能成为荣誉群主候选人。")
            return
        candidate_ok, candidate_reason = self._ensure_honor_owner_candidate_eligibility(target_user_id)
        if not candidate_ok:
            await self.group.send_msg(candidate_reason)
            return
        open_case = self.storage.find_open_case_by_type("honor_owner_election")
        if open_case:
            open_case_full = self.storage.get_case(int(open_case["case_id"]))
            if open_case_full and self._can_attach_candidate_to_honor_owner_case(open_case_full):
                nomination_update = await self._attach_candidate_to_honor_owner_case(
                    case=open_case_full,
                    target_user_id=target_user_id,
                    proposer_id=event.user_id,
                    reason=reason,
                )
                await self.group.send_msg(self._format_honor_owner_nomination_feedback(case_id=int(open_case_full["case_id"]), update=nomination_update))
                return
            await self.group.send_msg("当前已有进行中的荣誉群主选举案件，请先推进或结束现有案件。")
            return
        await self._ensure_member_profile(target_user_id)
        nomination_hours = self._config_int("governance_nomination_publicity_hours", 24)
        nomination_opened_at = datetime.now()
        nomination_closes_at = nomination_opened_at + timedelta(hours=nomination_hours)
        recommendation_threshold = self._honor_owner_nomination_support_threshold()
        case_id = self.storage.create_case(
            case_type="honor_owner_election",
            title="荣誉群主选举提名公示",
            description=reason or "荣誉群主选举",
            proposer_id=event.user_id,
            target_user_id=None,
            status="nomination_publicity",
            phase="nomination_publicity",
            support_threshold=0,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "candidate_member_ids": [],
                "candidate_nominations": {},
                "nomination_method": "pending_nomination",
                "nomination_support_threshold": recommendation_threshold,
                "reason": reason or "",
                "nomination_opened_at": nomination_opened_at.isoformat(),
                "nomination_closes_at": nomination_closes_at.isoformat(),
            },
        )
        created_case = self.storage.get_case(case_id)
        if created_case is None:
            await self.group.send_msg(f"荣誉群主选举案件 #{case_id} 已创建，但暂时读取失败，请稍后重试。")
            return
        nomination_update = await self._attach_candidate_to_honor_owner_case(
            case=created_case,
            target_user_id=target_user_id,
            proposer_id=event.user_id,
            reason=reason,
        )
        await self.group.send_msg(self._format_honor_owner_nomination_feedback(case_id=case_id, update=nomination_update))

    async def create_elder_election_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起元老选举。")
            return
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起元老选举",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        target_user_id, reason = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“发起元老选举 @成员 [理由]”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("机器人不能成为元老候选人。")
            return
        await self._ensure_member_profile(target_user_id)
        candidate_ok, candidate_reason = self._ensure_elder_candidate_eligibility(target_user_id)
        if not candidate_ok:
            await self.group.send_msg(candidate_reason)
            return
        open_case = self.storage.find_open_case_by_type("elder_election")
        if open_case:
            open_case_full = self.storage.get_case(int(open_case["case_id"]))
            if open_case_full and self._can_attach_candidate_to_elder_case(open_case_full):
                await self._attach_candidate_to_elder_case(
                    case=open_case_full,
                    target_user_id=target_user_id,
                    reason=reason,
                )
                await self.group.send_msg(
                    f"已将 {self._format_user(target_user_id)} 录入元老选举案件 #{open_case_full['case_id']}。\n"
                    f"当前仍处于提名公示期，期满后请使用“推进治理案件 {open_case_full['case_id']}”启动表决。"
                )
                return
            await self.group.send_msg("当前已有进行中的元老选举案件，请先推进或结束现有案件。")
            return

        seat_count = self._determine_elder_election_seat_count()
        if seat_count <= 0:
            await self.group.send_msg("当前元老会席位未出缺，无需另行发起元老选举。")
            return
        desired_seat_count = self._desired_elder_seat_count()
        nomination_hours = self._elder_nomination_publicity_hours()
        nomination_opened_at = datetime.now()
        nomination_closes_at = nomination_opened_at + timedelta(hours=nomination_hours)
        case_id = self.storage.create_case(
            case_type="elder_election",
            title="元老会选举提名公示",
            description=reason or "元老选举",
            proposer_id=event.user_id,
            target_user_id=None,
            status="nomination_publicity",
            phase="nomination_publicity",
            support_threshold=0,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "candidate_member_ids": [target_user_id],
                "nomination_method": "manual_nomination",
                "reason": reason or "",
                "seat_count": seat_count,
                "desired_council_seat_count": desired_seat_count,
                "term_days": self._elder_term_days(),
                "nomination_opened_at": nomination_opened_at.isoformat(),
                "nomination_closes_at": nomination_closes_at.isoformat(),
            },
        )
        await self.group.send_msg(
            f"已创建元老选举案件 #{case_id}。\n"
            f"- 本次待补席位：{seat_count} 席\n"
            f"- 元老会目标席位：{desired_seat_count} 席\n"
            f"- 当前进入提名公示期，持续 {nomination_hours} 小时\n"
            f"- 当选任期：{self._elder_term_days()} 日，可连选连任\n"
            f"- 期满后请使用“推进治理案件 {case_id}”启动表决"
        )

    async def create_honor_owner_impeachment_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起弹劾荣誉群主",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        can_supervise, denied_reason = self._ensure_elder_supervision_authority(
            event.user_id,
            action_label="发起荣誉群主弹劾",
        )
        if not can_supervise:
            await self.group.send_msg(denied_reason)
            return
        target_user_id = self.storage.get_active_role_user("honor_owner")
        if not target_user_id:
            await self.group.send_msg("当前没有已登记的荣誉群主。")
            return
        if self.storage.find_open_case("honor_owner_impeachment", target_user_id):
            await self.group.send_msg("当前已有荣誉群主弹劾案件在进行中。")
            return
        elder_count = self._elder_current_member_count()
        threshold = self._elder_special_decision_threshold()
        if elder_count < 2 or threshold <= 0:
            await self.group.send_msg("当前在册元老不足 2 人，不能依元老会特别表决启动荣誉群主弹劾。")
            return
        reason_payload = self._parse_honor_owner_impeachment_request(self._plain_text(arg))
        if reason_payload["error"]:
            await self.group.send_msg(str(reason_payload["error"]))
            return
        description = str(reason_payload["reason_text"] or "荣誉群主弹劾")
        case_id = self.storage.create_case(
            case_type="honor_owner_impeachment",
            title=f"是否撤销 {self._format_user(target_user_id)} 的荣誉群主职权",
            description=description,
            proposer_id=event.user_id,
            target_user_id=target_user_id,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "reason": description,
                "fact_summary": description,
                "reason_codes": reason_payload["reason_codes"],
                "reason_summary": reason_payload["reason_summary"],
                "cited_articles": ["第三十三条", "第三十四条", "第三十七条"],
                "evidence_refs": [],
                "council_decision_type": "start_honor_owner_impeachment",
                "current_elder_count": elder_count,
                "required_supporters": threshold,
            },
        )
        self.storage.add_case_support(case_id, event.user_id)
        await self.group.send_msg(
            f"已创建荣誉群主弹劾案件 #{case_id}。\n当前联署：1/{threshold}（仅元老会成员可联署，需达到在册元老三分之二同意）"
        )
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_elder_impeachment_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起元老弹劾。")
            return
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起弹劾元老",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        target_user_id, reason = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“发起弹劾元老 @成员 [理由]”。")
            return
        if not self.storage.has_role(target_user_id, "elder"):
            await self.group.send_msg("目标成员当前不是元老会成员。")
            return
        if self.storage.find_open_case("elder_impeachment", target_user_id):
            await self.group.send_msg("该元老的弹劾案件已在进行中。")
            return
        threshold = max(1, math.ceil(self.storage.member_count() * self._config_float("governance_elder_impeach_ratio", 0.1)))
        reason_payload = self._parse_elder_impeachment_request(reason)
        if reason_payload["error"]:
            await self.group.send_msg(str(reason_payload["error"]))
            return
        description = str(reason_payload["reason_text"] or "元老弹劾")
        case_id = self.storage.create_case(
            case_type="elder_impeachment",
            title=f"是否撤销 {self._format_user(target_user_id)} 的元老会职权",
            description=description,
            proposer_id=event.user_id,
            target_user_id=target_user_id,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "reason": description,
                "fact_summary": description,
                "reason_codes": reason_payload["reason_codes"],
                "reason_summary": reason_payload["reason_summary"],
                "cited_articles": ["第三十八条", "第三十九条"],
                "evidence_refs": [],
            },
        )
        self.storage.add_case_support(case_id, event.user_id)
        await self.group.send_msg(f"已创建元老弹劾案件 #{case_id}。\n当前联署：1/{threshold}")
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_elder_reboot_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起重组元老会。")
            return
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起重组元老会",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        if self.storage.find_open_case("elder_reboot", None):
            await self.group.send_msg("当前已有重组元老会案件在进行中。")
            return
        threshold = self._reboot_support_threshold()
        request = self._parse_elder_reboot_request(self._plain_text(arg))
        if request["error"]:
            await self.group.send_msg(str(request["error"]))
            return
        description = str(request["reason_text"] or "重组元老会")
        case_id = self.storage.create_case(
            case_type="elder_reboot",
            title="是否启动重组元老会程序",
            description=description,
            proposer_id=event.user_id,
            target_user_id=None,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "reason": description,
                "fact_summary": str(request["major_fact_summary"] or description),
                "institutional_reason": description,
                "institutional_reason_codes": request["reason_codes"],
                "institutional_reason_summary": request["reason_summary"],
                "constitutional_remedy": True,
                "not_daily_struggle_tool": True,
                "forbidden_reason_detected": bool(request["forbidden_reason_detected"]),
            },
        )
        self.storage.add_case_support(case_id, event.user_id)
        summary = str(request["reason_summary"] or "制度性理由待人工解释")
        await self.group.send_msg(
            f"已创建重组元老会案件 #{case_id}。\n"
            f"- 制度性理由：{summary}\n"
            f"- 当前联署：1/{threshold}"
        )
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_emergency_protection_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起紧急防护。")
            return
        target_user_id, reason = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“发起紧急防护 @成员 [理由]”。")
            return
        if self.storage.find_open_case("emergency_protection", target_user_id):
            await self.group.send_msg("该成员已有进行中的紧急防护案件。")
            return
        threshold = self._config_int("governance_emergency_supporters", 5)
        description = reason or "紧急防护"
        case_id = self.storage.create_case(
            case_type="emergency_protection",
            title=f"是否对 {self._format_user(target_user_id)} 启动紧急防护",
            description=description,
            proposer_id=event.user_id,
            target_user_id=target_user_id,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=0,
            payload={"reason": description},
        )
        self.storage.add_case_support(case_id, event.user_id)
        await self.group.send_msg(f"已创建紧急防护案件 #{case_id}。\n当前联署：1/{threshold}")
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_formal_discipline_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        target_user_id, plain_text = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg(
                "请使用“发起正式处分 @成员 处分类型 [时长] [事实与理由]”。\n"
                "示例：发起正式处分 @成员 长期禁言 7d 持续刷屏并多次辱骂。"
            )
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("不能对机器人发起正式处分。")
            return
        if target_user_id == event.user_id:
            await self.group.send_msg("当前不支持对自己发起正式处分。")
            return
        if self.storage.find_open_case("formal_discipline", target_user_id):
            await self.group.send_msg("该成员已有进行中的正式处分案件。")
            return
        application = self._parse_formal_discipline_request(plain_text)
        if application["error"]:
            await self.group.send_msg(str(application["error"]))
            return

        await self._ensure_member_profile(target_user_id)
        now = datetime.now()
        sanction_type = str(application["sanction_type"])
        sanction_label = self._formal_sanction_label(sanction_type)
        fact_summary = str(application["fact_summary"])
        requested_duration_seconds = int(application["requested_duration_seconds"])
        direct_filing = self._can_direct_file_formal_discipline(event.user_id)
        acceptance_hours = self._config_int("governance_formal_acceptance_hours", 48)
        payload = {
            "filer_id": int(event.user_id),
            "target_member_id": target_user_id,
            "fact_summary": fact_summary,
            "evidence_refs": [f"manual_submission:{event.user_id}:{now.strftime('%Y%m%d%H%M%S')}"],
            "requested_sanction": sanction_type,
            "current_sanction": sanction_type,
            "requested_duration_seconds": requested_duration_seconds,
            "submitted_at": now.isoformat(),
            "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
            **self._formal_discipline_scope_payload(),
        }
        if direct_filing:
            payload["acceptance_due_at"] = (now + timedelta(hours=acceptance_hours)).isoformat()
            case_id = self.storage.create_case(
                case_type="formal_discipline",
                title=f"是否对 {self._format_user(target_user_id)} 作出{sanction_label}",
                description=fact_summary,
                proposer_id=event.user_id,
                target_user_id=target_user_id,
                status="active",
                phase="acceptance_review",
                support_threshold=0,
                vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
                payload=payload,
            )
            await self.group.send_msg(
                f"已创建正式处分案件 #{case_id}。\n"
                f"- 适用范围：{self._formal_discipline_scope_summary()}\n"
                f"- 建议处分：{sanction_label}{self._format_sanction_duration_suffix(sanction_type, requested_duration_seconds)}\n"
                f"- 当前阶段：受理审查\n"
                f"- 受理最晚截止：{(now + timedelta(hours=acceptance_hours)).strftime('%Y-%m-%d %H:%M')}\n"
                f"- 可由元老会成员或荣誉群主使用“推进治理案件 {case_id}”提前受理；逾期视为受理。"
            )
            return

        threshold = self._formal_discipline_support_threshold()
        case_id = self.storage.create_case(
            case_type="formal_discipline",
            title=f"是否对 {self._format_user(target_user_id)} 作出{sanction_label}",
            description=fact_summary,
            proposer_id=event.user_id,
            target_user_id=target_user_id,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload=payload,
        )
        supporter_count = 0
        if self._can_count_as_formal_discipline_filer(event.user_id):
            self.storage.add_case_support(case_id, event.user_id)
            supporter_count = 1
        lines = [
            f"已创建正式处分申请案件 #{case_id}。",
            f"- 适用范围：{self._formal_discipline_scope_summary()}",
            f"- 建议处分：{sanction_label}{self._format_sanction_duration_suffix(sanction_type, requested_duration_seconds)}",
            f"- 当前联署：{supporter_count}/{threshold}",
        ]
        if supporter_count == 0:
            lines.append("- 发起人当前不计入正式立案联署，仍可继续征集表决权成员联署。")
        lines.append(f"- 达到门槛后将进入受理审查；请使用“联署治理案件 {case_id}”。")
        await self.group.send_msg("\n".join(lines))
        if supporter_count > 0:
            await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_formal_discipline_review_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        source_case_id, reason_text = self._parse_case_id_and_reason(arg)
        if source_case_id is None:
            await self.group.send_msg(
                "请使用“申请处分复核 处分案件ID [复核理由]”。\n"
                "法定理由包括：新证据、关键程序错误、事实错误、处分明显失衡。"
            )
            return
        source_case = self.storage.get_case(source_case_id)
        if not source_case or source_case["case_type"] != "formal_discipline":
            await self.group.send_msg("只能对已存在的正式处分案件申请复核。")
            return
        legacy_case = self._is_pre_effective_completed_case(source_case)
        review_request = self._parse_formal_review_request(reason_text, allow_legacy_safety_only=legacy_case)
        if review_request["error"]:
            await self.group.send_msg(str(review_request["error"]))
            return
        legacy_exception_basis = self._legacy_formal_review_exception_basis(
            review_request=review_request,
            legacy_case=legacy_case,
        )
        if not self._formal_discipline_reviewable(source_case, legacy_exception_basis=legacy_exception_basis):
            if legacy_case and not legacy_exception_basis:
                await self.group.send_msg(
                    "该正式处分案件属于现行规则生效前已完成的旧程序，按第六十九条原则上不溯及既往。\n"
                    "仅在存在重大程序违法或安全风险时，才可按附则例外复核。"
                )
            else:
                await self.group.send_msg("该正式处分案件当前不在可申请复核的公示窗口内。")
            return
        if self.storage.find_open_case("formal_discipline_review", int(source_case.get("target_user_id") or 0) or None):
            existing = self.storage.find_open_case("formal_discipline_review", int(source_case.get("target_user_id") or 0) or None)
            if existing:
                existing_case = self.storage.get_case(int(existing["case_id"]))
                if existing_case and self._case_payload_int(existing_case, "source_case_id") == source_case_id:
                    await self.group.send_msg("该正式处分案件已有进行中的复核案件。")
                    return
        requester_is_target = int(source_case.get("target_user_id") or 0) == int(event.user_id)
        if not requester_is_target:
            can_support, denied_reason = self._ensure_formal_review_supporter(event.user_id)
            if not can_support:
                await self.group.send_msg(denied_reason)
                return

        now = datetime.now()
        payload = {
            "source_case_id": source_case_id,
            "requester_id": int(event.user_id),
            "review_reasons": str(review_request["reason_text"]),
            "review_reason_codes": list(review_request["reason_codes"]),
            "submitted_at": now.isoformat(),
            "pause_execution_requested": bool(review_request["pause_execution_requested"]),
            "source_case_ref": f"formal_case:{source_case_id}",
            "legacy_case_under_transition": legacy_case,
            "legacy_exception_requested": bool(legacy_exception_basis),
            "legacy_exception_basis": legacy_exception_basis,
            "law_regime_version": self._current_law_version_label(),
            "law_regime_effective_at": self._current_law_effective_at_iso(),
        }
        legacy_entry_note = self._format_legacy_review_entry_note(legacy_exception_basis)
        if requester_is_target:
            start_check_due_at = now + timedelta(hours=self._config_int("governance_formal_review_start_hours", 48))
            payload["start_check_due_at"] = start_check_due_at.isoformat()
            case_id = self.storage.create_case(
                case_type="formal_discipline_review",
                title=f"是否启动对正式处分案件 #{source_case_id} 的复核",
                description=str(review_request["reason_text"]),
                proposer_id=event.user_id,
                target_user_id=int(source_case.get("target_user_id") or 0) or None,
                status="active",
                phase="review_start_check",
                support_threshold=0,
                vote_duration_seconds=0,
                payload=payload,
            )
            self.storage.update_case_fields(
                source_case_id,
                {
                    "payload_json": self._merge_case_payload(
                        source_case,
                        {
                            "review_started_case_id": case_id,
                        },
                    )
                },
            )
            lines = [
                f"已创建处分复核案件 #{case_id}。",
                f"- 原处分案件：#{source_case_id}",
                "- 当前阶段：启动审查",
                f"- 启动最晚截止：{start_check_due_at.strftime('%Y-%m-%d %H:%M')}",
            ]
            if legacy_entry_note:
                lines.append(f"- 适用边界：{legacy_entry_note}")
            lines.append(
                f"- 可由元老会成员或荣誉群主使用“推进治理案件 {case_id}”提前作出启动/驳回决定；逾期按法定理由自动处理。"
            )
            await self.group.send_msg("\n".join(lines))
            return

        threshold = self._formal_discipline_support_threshold()
        case_id = self.storage.create_case(
            case_type="formal_discipline_review",
            title=f"是否启动对正式处分案件 #{source_case_id} 的复核",
            description=str(review_request["reason_text"]),
            proposer_id=event.user_id,
            target_user_id=int(source_case.get("target_user_id") or 0) or None,
            status="supporting",
            phase="support",
            support_threshold=threshold,
            vote_duration_seconds=0,
            payload=payload,
        )
        self.storage.update_case_fields(
            source_case_id,
            {
                "payload_json": self._merge_case_payload(
                    source_case,
                    {
                        "review_started_case_id": case_id,
                    },
                )
            },
        )
        self.storage.add_case_support(case_id, event.user_id)
        lines = [
            f"已创建处分复核联署案件 #{case_id}。",
            f"- 原处分案件：#{source_case_id}",
            f"- 当前联署：1/{threshold}",
        ]
        if legacy_entry_note:
            lines.append(f"- 适用边界：{legacy_entry_note}")
        lines.append(f"- 达到门槛后将进入启动审查；请使用“联署治理案件 {case_id}”。")
        await self.group.send_msg("\n".join(lines))
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def create_proposal_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能发起提案。")
            return
        motion_allowed, denied_reason = self.ensure_motion_initiation_permission(
            event.user_id,
            action_label="发起提案",
        )
        if not motion_allowed:
            await self.group.send_msg(denied_reason)
            return
        request = self._parse_proposal_request(self._plain_text(arg))
        if request["error"]:
            await self.group.send_msg(str(request["error"]))
            return
        proposal_type = str(request["proposal_type"])
        if proposal_type == "emergency_motion":
            await self.group.send_msg(
                "紧急动议当前由现有紧急程序承接；请改用“发起紧急防护 @成员 [理由]”处理正在发生的安全风险。"
            )
            return
        now = datetime.now()
        review_due_at = now + timedelta(hours=self._PROPOSAL_REVIEW_HOURS)
        vote_duration_seconds = self._proposal_vote_duration_seconds(proposal_type)
        case_id = self.storage.create_case(
            case_type="ordinary_proposal",
            title=str(request["title"]),
            description=str(request["purpose_and_reason"]),
            proposer_id=event.user_id,
            target_user_id=None,
            status="active",
            phase="procedural_review",
            support_threshold=0,
            vote_duration_seconds=vote_duration_seconds,
            payload={
                "proposal_type": proposal_type,
                "proposal_type_label": self._proposal_type_label(proposal_type),
                "purpose_and_reason": str(request["purpose_and_reason"]),
                "proposed_text_or_measure": str(request["proposed_text_or_measure"]),
                "effective_time_or_expiry": str(request["effective_time_or_expiry"]),
                "high_risk_power_requested": bool(request["high_risk_power_requested"]),
                "submitted_at": now.isoformat(),
                "review_started_at": now.isoformat(),
                "review_due_at": review_due_at.isoformat(),
                "discussion_required_hours": self._proposal_discussion_hours(proposal_type),
                "threshold_set": self._proposal_threshold_ref(proposal_type),
                "law_version_snapshot": "",
                "non_retroactivity_boundary_notice": self._proposal_non_retroactivity_note(),
                "proposal_review_channel": "申请提案复核 <案件ID> [理由]",
                "review_requests": [],
            },
        )
        lines = [
            f"已创建提案案件 #{case_id}。",
            f"- 类型：{self._proposal_type_label(proposal_type)}",
            f"- 标题：{request['title']}",
            f"- 程序审查截止：{review_due_at.strftime('%Y-%m-%d %H:%M')}",
            f"- 讨论期下限：{self._proposal_discussion_hours(proposal_type)} 小时",
            f"- 投票期下限：{self._format_duration(vote_duration_seconds)}",
        ]
        if bool(request["high_risk_power_requested"]):
            lines.append("- 高风险权力：是")
        if proposal_type == "temporary_measure":
            lines.append("- 临时措施说明：已校验显式期限，超过 7 日需改走普通议题或立规程序。")
        lines.append(
            f"- 元老会可使用“审查提案 {case_id} 通过/补正/驳回 ...”作出程序审查；逾期将自动进入讨论期。"
        )
        await self.group.send_msg("\n".join(lines))

    async def review_proposal_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not self.storage.has_role(event.user_id, "elder"):
            await self.group.send_msg("只有元老会成员可以作提案程序审查。")
            return
        case_id, action, detail = self._parse_proposal_review_argument(self._plain_text(arg))
        if case_id is None or not action:
            await self.group.send_msg("请使用“审查提案 <案件ID> 通过”或“审查提案 <案件ID> 补正 <补正项>”或“审查提案 <案件ID> 驳回 <理由>”。")
            return
        case = self.storage.get_case(case_id)
        if not case or case["case_type"] != "ordinary_proposal":
            await self.group.send_msg("未找到对应提案案件。")
            return
        if str(case.get("phase") or "") != "procedural_review" or str(case.get("status") or "") != "active":
            await self.group.send_msg(f"案件 #{case_id} 当前不处于程序审查阶段。")
            return
        if int(case.get("proposer_id") or 0) == int(event.user_id):
            await self.group.send_msg("提案人本人应回避自己的程序审查，请由其他元老处理。")
            return
        if action == "pass":
            await self._move_proposal_to_discussion(case=case, reviewer_id=event.user_id, timeout_entry=False)
            await self.group.send_msg(
                f"案件 #{case_id} 已通过程序审查，进入讨论期。\n"
                f"期满后请使用“推进治理案件 {case_id}”或等待自动推进进入表决。"
            )
            return
        if action == "request_correction":
            if not detail:
                await self.group.send_msg("请补充补正项。")
                return
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "correction_requested",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "reviewed_at": datetime.now().isoformat(),
                            "reviewer_id": int(event.user_id),
                            "correction_requested_at": datetime.now().isoformat(),
                            "correction_items": str(detail),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已要求补正。\n"
                f"- 补正项：{detail}\n"
                f"- 提案人可使用“补正提案 {case_id} 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”重新提交。"
            )
            return
        if not detail:
            await self.group.send_msg("请补充程序性驳回理由。")
            return
        escalation_threshold = self._proposal_escalation_support_threshold()
        self.storage.update_case_fields(
            case_id,
            {
                "status": "supporting",
                "phase": "procedurally_rejected",
                "support_threshold": escalation_threshold,
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "reviewed_at": datetime.now().isoformat(),
                        "reviewer_id": int(event.user_id),
                        "rejection_reason": str(detail),
                        "cited_articles": ["第十六条", "第十九条"],
                        "escalation_support_threshold": escalation_threshold,
                    },
                ),
            },
        )
        await self.group.send_msg(
            f"案件 #{case_id} 已作程序性驳回。\n"
            f"- 理由：{detail}\n"
            f"- 如提案人不服，可由不少于 {escalation_threshold} 名表决权成员联署“联署治理案件 {case_id}”直接进入表决。"
        )

    async def correct_proposal_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        case_id, request = self._parse_proposal_correction_request(self._plain_text(arg))
        if case_id is None:
            await self.group.send_msg("请使用“补正提案 <案件ID> 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”。")
            return
        case = self.storage.get_case(case_id)
        if not case or case["case_type"] != "ordinary_proposal":
            await self.group.send_msg("未找到对应提案案件。")
            return
        if str(case.get("phase") or "") != "correction_requested" or str(case.get("status") or "") != "active":
            await self.group.send_msg(f"案件 #{case_id} 当前不处于待补正阶段。")
            return
        if int(case.get("proposer_id") or 0) != int(event.user_id):
            await self.group.send_msg("只有提案人本人可以提交补正后的提案文本。")
            return
        if request["error"]:
            await self.group.send_msg(str(request["error"]))
            return
        now = datetime.now()
        review_due_at = now + timedelta(hours=self._PROPOSAL_REVIEW_HOURS)
        self.storage.update_case_fields(
            case_id,
            {
                "phase": "procedural_review",
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "purpose_and_reason": str(request["purpose_and_reason"]),
                        "proposed_text_or_measure": str(request["proposed_text_or_measure"]),
                        "effective_time_or_expiry": str(request["effective_time_or_expiry"]),
                        "high_risk_power_requested": bool(request["high_risk_power_requested"]),
                        "correction_submitted_at": now.isoformat(),
                        "review_started_at": now.isoformat(),
                        "review_due_at": review_due_at.isoformat(),
                        "correction_items": "",
                    },
                ),
            },
        )
        with self.storage.db.conn:
            self.storage.db.conn.execute(
                """
                UPDATE governance_cases
                SET title = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE case_id = ?
            """,
                (str(request["title"]), str(request["purpose_and_reason"]), case_id),
            )
        await self.group.send_msg(
            f"案件 #{case_id} 已完成补正并重新进入程序审查。\n"
            f"- 新标题：{request['title']}\n"
            f"- 审查截止：{review_due_at.strftime('%Y-%m-%d %H:%M')}"
        )

    async def request_proposal_review_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        case_id, reason_text = self._parse_case_id_and_reason(arg)
        if case_id is None:
            await self.group.send_msg("请使用“申请提案复核 <案件ID> [理由]”。")
            return
        can_request, denied_reason = await self._ensure_governance_vote_participant(event.user_id)
        if not can_request:
            await self.group.send_msg(denied_reason)
            return
        case = self.storage.get_case(case_id)
        if not case or case["case_type"] != "ordinary_proposal":
            await self.group.send_msg("未找到对应提案案件。")
            return
        payload = case.get("payload") or {}
        existing_requests = payload.get("review_requests") or []
        if not isinstance(existing_requests, list):
            existing_requests = []
        request_reason = str(reason_text or "程序错误待补充说明").strip()
        request_record = {
            "requester_id": int(event.user_id),
            "requested_at": datetime.now().isoformat(),
            "reason": request_reason,
        }
        updated_requests = [*existing_requests, request_record]
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "review_requests": updated_requests,
                        "latest_review_request_at": request_record["requested_at"],
                    },
                )
            },
        )
        self.metadata.record_audit_event(
            actor_id=event.user_id,
            action="proposal_review_requested",
            subject_type="governance_case",
            subject_id=str(case_id),
            session_key=None,
            result="recorded",
            context={
                "case_type": "ordinary_proposal",
                "reason": request_reason,
            },
        )
        await self.group.send_msg(
            f"已记录对提案案件 #{case_id} 的程序复核请求。\n"
            f"- 理由：{request_reason}\n"
            "- 该请求已写入案件记录，供后续程序审查、复盘和群内公示时核对。"
        )

    async def designate_temporary_proxy_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        can_designate, denied_reason = self._ensure_elder_supervision_authority(
            event.user_id,
            action_label="指定临时代理",
        )
        if not can_designate:
            await self.group.send_msg(denied_reason)
            return
        vacancy_case = self._active_honor_owner_vacancy_case()
        if not vacancy_case:
            await self.group.send_msg("当前没有处于空缺期的荣誉群主补选案件，无需指定临时代理。")
            return
        payload = vacancy_case.get("payload") or {}
        temporary_proxy_status = str(payload.get("temporary_proxy_status") or "").strip()
        if temporary_proxy_status == "bot_temporary_autonomy":
            await self.group.send_msg("当前已进入机器人临时自治阶段，荣誉群主职权争议应改用“发起职权争议表决”。")
            return
        if temporary_proxy_status not in {"", "pending_elder_designation", "elder_designated_proxy"}:
            await self.group.send_msg("当前空缺案件不支持再指定临时代理。")
            return
        target_user_id, reason = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“指定临时代理 @成员 [说明]”。")
            return
        if not self.storage.has_role(target_user_id, "elder"):
            await self.group.send_msg("临时程序代理必须由当前在册元老担任。")
            return
        if self.storage.has_active_lock(lock_type="elder_powers", target_user_id=target_user_id):
            await self.group.send_msg("该元老当前职权被冻结，不能担任临时程序代理。")
            return
        if self.storage.has_role(target_user_id, "suspended"):
            await self.group.send_msg("该成员当前处于治理禁权状态，不能担任临时程序代理。")
            return
        designated_at = datetime.now()
        expires_at = designated_at + timedelta(days=self._HONOR_OWNER_CARETAKER_MAX_DAYS)
        self.storage.update_case_fields(
            int(vacancy_case["case_id"]),
            {
                "payload_json": self._merge_case_payload(
                    vacancy_case,
                    {
                        "temporary_proxy_status": "elder_designated_proxy",
                        "temporary_proxy_scope": "经元老会指定，临时处理必要程序事务，不得行使高风险权力",
                        "temporary_proxy_user_id": target_user_id,
                        "temporary_proxy_designated_at": designated_at.isoformat(),
                        "temporary_proxy_expires_at": expires_at.isoformat(),
                        "temporary_proxy_designated_by": int(event.user_id),
                        "temporary_proxy_designation_note": str(reason or "").strip(),
                        "dispute_resolution_channel": "elder_designated_proxy",
                    },
                )
            },
        )
        self.metadata.record_audit_event(
            actor_id=event.user_id,
            action="honor_owner_temporary_proxy_designated",
            subject_type="governance_case",
            subject_id=str(vacancy_case["case_id"]),
            session_key=None,
            result="recorded",
            context={
                "target_user_id": target_user_id,
                "expires_at": expires_at.isoformat(),
                "note": str(reason or "").strip(),
            },
        )
        lines = [
            f"已记录荣誉群主空缺期的临时程序代理：{self._format_user(target_user_id)}",
            f"- 来源补选案件：#{vacancy_case['case_id']}",
            f"- 代理期限最晚至：{expires_at.strftime('%Y-%m-%d %H:%M')}",
            "- 代理范围：仅处理必要程序事务，不得行使高风险权力。",
        ]
        if reason:
            lines.append(f"- 说明：{reason}")
        await self.group.send_msg("\n".join(lines))

    async def create_vacancy_dispute_vote_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        can_request, denied_reason = await self._ensure_governance_vote_participant(event.user_id)
        if not can_request:
            await self.group.send_msg(denied_reason)
            return
        vacancy_case = self._active_honor_owner_vacancy_case()
        if not vacancy_case:
            await self.group.send_msg("当前没有处于空缺期的荣誉群主补选案件，不能发起职权争议表决。")
            return
        payload = vacancy_case.get("payload") or {}
        if str(payload.get("dispute_resolution_channel") or "").strip() != "full_voting_members":
            await self.group.send_msg("当前空缺案件仍应先由元老会指定的临时代理处理，尚未进入争议直达全体表决阶段。")
            return
        existing_dispute_case = self._find_active_vacancy_dispute_case(int(vacancy_case["case_id"]))
        if existing_dispute_case:
            await self.group.send_msg(f"当前已有荣誉群主职权争议直达表决案件 #{existing_dispute_case['case_id']}，请先等待其结束。")
            return
        request = self._parse_vacancy_dispute_request(self._plain_text(arg))
        if request["error"]:
            await self.group.send_msg(str(request["error"]))
            return
        now = datetime.now()
        vote_duration_seconds = self._proposal_vote_duration_seconds("ordinary_proposal")
        case_id = self.storage.create_case(
            case_type="ordinary_proposal",
            title=f"荣誉群主职权争议：{request['title']}",
            description=str(request["purpose_and_reason"]),
            proposer_id=event.user_id,
            target_user_id=None,
            status="active",
            phase="discussion",
            support_threshold=0,
            vote_duration_seconds=vote_duration_seconds,
            payload={
                "proposal_type": "ordinary_proposal",
                "proposal_type_label": self._proposal_type_label("ordinary_proposal"),
                "purpose_and_reason": str(request["purpose_and_reason"]),
                "proposed_text_or_measure": str(request["proposed_text_or_measure"]),
                "effective_time_or_expiry": str(request["effective_time_or_expiry"]),
                "high_risk_power_requested": bool(request["high_risk_power_requested"]),
                "submitted_at": now.isoformat(),
                "discussion_opened_at": now.isoformat(),
                "discussion_closes_at": now.isoformat(),
                "direct_collective_dispute_vote": True,
                "vacancy_case_id": int(vacancy_case["case_id"]),
                "review_bypassed_by_article": "第二十五条",
                "threshold_set": self._proposal_threshold_ref("ordinary_proposal"),
                "law_version_snapshot": "",
                "non_retroactivity_boundary_notice": self._proposal_non_retroactivity_note(),
                "proposal_review_channel": "申请提案复核 <案件ID> [理由]",
                "review_requests": [],
            },
        )
        lines = [
            f"已创建荣誉群主职权争议直达表决案件 #{case_id}。",
            f"- 来源空缺案件：#{vacancy_case['case_id']}",
            f"- 标题：{request['title']}",
            "- 当前根据第二十五条，跳过元老会程序审查，直接提交全体表决权成员表决。",
        ]
        if bool(request["high_risk_power_requested"]):
            lines.append("- 高风险权力：是")
        await self.group.send_msg("\n".join(lines))
        await self._start_case_vote(case_id=case_id, event=event)

    async def support_case_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        if not await self._ensure_governance_participant(event.user_id):
            await self.group.send_msg("当前处于治理禁权状态，不能联署治理案件。")
            return
        case_id = self._parse_case_id(arg)
        if case_id is None:
            await self.group.send_msg("请使用“联署治理案件 案件ID”。")
            return
        case = self.storage.get_case(case_id)
        if not case:
            await self.group.send_msg("未找到对应治理案件。")
            return
        if case["status"] != "supporting":
            await self.group.send_msg(f"案件 #{case_id} 当前状态为 {case['status']}，无需继续联署。")
            return
        if case["case_type"] == "honor_owner_impeachment":
            can_support, denied_reason = self._ensure_elder_supervision_authority(
                event.user_id,
                action_label="联署荣誉群主弹劾",
            )
            if not can_support:
                await self.group.send_msg(denied_reason)
                return
        if case["case_type"] == "formal_discipline":
            can_support, denied_reason = self._ensure_formal_discipline_supporter(event.user_id)
            if not can_support:
                await self.group.send_msg(denied_reason)
                return
        if case["case_type"] == "formal_discipline_review":
            can_support, denied_reason = self._ensure_formal_review_supporter(event.user_id)
            if not can_support:
                await self.group.send_msg(denied_reason)
                return
        if case["case_type"] == "ordinary_proposal" and str(case.get("phase") or "") == "procedurally_rejected":
            can_support, denied_reason = await self._ensure_governance_vote_participant(event.user_id)
            if not can_support:
                await self.group.send_msg(denied_reason)
                return
        if not self.storage.add_case_support(case_id, event.user_id):
            await self.group.send_msg(f"您已联署案件 #{case_id}。")
            return
        await self.group.send_msg(
            f"已联署案件 #{case_id}，当前联署：{self.storage.count_case_supporters(case_id)}/{case['support_threshold']}"
        )
        await self._advance_case_after_support(case_id=case_id, event=event)

    async def advance_case_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        case_id = self._parse_case_id(arg)
        if case_id is None:
            await self.group.send_msg("请使用“推进治理案件 案件ID”。")
            return
        case = self.storage.get_case(case_id)
        if not case:
            await self.group.send_msg("未找到对应治理案件。")
            return
        if case["case_type"] == "formal_discipline_review":
            await self._advance_formal_discipline_review_case(case=case, event=event)
            return
        if case["case_type"] == "honor_owner_election":
            await self._advance_honor_owner_election_case(case=case, event=event)
            return
        if case["case_type"] == "elder_election":
            await self._advance_elder_election_case(case=case, event=event)
            return
        if case["case_type"] == "ordinary_proposal":
            await self._advance_proposal_case(case=case, event=event)
            return
        if case["case_type"] in {"honor_owner_impeachment", "elder_impeachment"} and case["status"] == "response_window":
            await self._advance_impeachment_response_window(case=case, event=event)
            return
        if case["case_type"] == "emergency_protection" and case["status"] == "active":
            await self._advance_emergency_protection_case(case=case)
            return
        if case["case_type"] == "formal_discipline" and case["status"] == "active":
            await self._advance_formal_discipline_case(case=case, event=event)
            return
        if case["case_type"] == "formal_discipline" and case["status"] == "approved" and str(case.get("phase") or "") == "approved":
            await self._retry_formal_discipline_execution(case=case)
            return
        if case["case_type"] == "elder_reboot" and case["status"] == "cooling":
            cooldown_until = self._parse_datetime(case.get("cooldown_until"))
            if cooldown_until and datetime.now() < cooldown_until:
                remain = cooldown_until - datetime.now()
                minutes = max(int(remain.total_seconds() // 60), 1)
                await self.group.send_msg(f"案件 #{case_id} 仍在冷却期，约剩余 {minutes} 分钟。")
                return
            await self.group.send_msg(f"案件 #{case_id} 冷却期已结束，开始进入最终表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        await self.group.send_msg(f"案件 #{case_id} 当前状态为 {case['status']}，无需推进。")

    async def list_cases_command(self, event: GroupMessageEvent) -> None:
        cases = self.storage.list_recent_cases(limit=10)
        if not cases:
            await self.group.send_msg("当前暂无治理案件。")
            return
        lines = ["最近治理案件："]
        for case in cases:
            lines.append(self._format_case_summary(case, include_proposer=True))
        await self.group.send_msg("\n".join(lines))

    async def govern_ban_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        target_user_id, plain_text = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“治理禁言 @成员 [分钟] [理由]”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("不能对机器人执行治理禁言。")
            return
        tokens = [token for token in plain_text.split() if token]
        duration_minutes = self._config_int("governance_default_ban_minutes", 60)
        if tokens and tokens[0].isdigit():
            duration_minutes = max(1, min(int(tokens[0]), self._config_int("governance_max_ban_minutes", 1440)))
        authorized, source_case_id, denied_reason = self._can_execute_governance_ban(
            actor_user_id=event.user_id,
            target_user_id=target_user_id,
        )
        if not authorized:
            await self.group.send_msg(denied_reason)
            return
        await self.group.ban(target_user_id, duration_minutes * 60)
        if source_case_id:
            source_case = self.storage.get_case(source_case_id)
            if source_case:
                await self._record_emergency_ban_measure(
                    case=source_case,
                    actor_user_id=event.user_id,
                    duration_minutes=duration_minutes,
                )
        await self.group.send_msg(f"已执行治理禁言：{self._format_user(target_user_id)}，时长 {duration_minutes} 分钟。")

    async def govern_kick_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        target_user_id, plain_text = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“治理放逐 @成员 [理由]”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("不能对机器人执行治理放逐。")
            return
        if self.storage.has_active_lock(lock_type="kick_global"):
            await self.group.send_msg("当前存在重组元老会程序，踢人权力已被冻结。")
            return
        authorized, source_case_id, denied_reason = self._can_execute_governance_kick(
            actor_user_id=event.user_id,
            target_user_id=target_user_id,
        )
        if not authorized:
            await self.group.send_msg(denied_reason)
            return
        reason_text = plain_text.strip()
        if source_case_id is None and self.storage.get_active_role_user("honor_owner") == event.user_id and not reason_text:
            await self.group.send_msg("直接执行治理放逐属于高风险操作，请同时说明理由并留痕。用法：治理放逐 @成员 理由。")
            return
        await self.group.kick(target_user_id)
        if source_case_id:
            emergency_case = self.storage.get_case(source_case_id)
            if emergency_case:
                await self._record_emergency_kick_measure(
                    case=emergency_case,
                    actor_user_id=event.user_id,
                )
            await self.group.send_msg(f"已执行治理放逐：{self._format_user(target_user_id)}")
            return
        self._record_honor_owner_high_risk_action(
            actor_id=int(event.user_id),
            action_type="kick_member",
            target_user_id=int(target_user_id),
            reason=reason_text,
        )
        await self.group.send_msg(
            "\n".join(
                [
                    f"已执行治理放逐：{self._format_user(target_user_id)}",
                    "- 高风险操作理由已留痕。",
                ]
            )
        )

    async def daily_management_command(self, event: GroupMessageEvent, arg: "Message") -> None:
        target_user_id, plain_text = self._parse_target_argument(event, arg)
        if not target_user_id:
            await self.group.send_msg("请使用“日常管理 @成员 动作 [时长] [理由]”。")
            return
        if target_user_id == self.group.self_id:
            await self.group.send_msg("不能对机器人执行日常管理。")
            return
        authorized, denied_reason = self._ensure_honor_owner_execution_authority(
            event.user_id,
            action_label="执行日常管理",
            allow_caretaker=True,
        )
        if not authorized:
            await self.group.send_msg(denied_reason)
            return
        request = self._parse_daily_management_request(plain_text)
        if request["error"]:
            await self.group.send_msg(str(request["error"]))
            return
        action_type = str(request["action_type"])
        duration_seconds = int(request["duration_seconds"])
        reason = str(request["reason"]).strip()
        if action_type == "motion_restriction" and self.storage.has_active_lock(
            lock_type="daily_management_motion_restriction",
            target_user_id=target_user_id,
        ):
            await self.group.send_msg(
                "该成员当前已处于提案/动议限制期间；日常管理不应以重复续期替代正式处分。"
                "如仍需更强处理，请改用“发起正式处分 @成员 ...”。"
            )
            return

        await self._ensure_member_profile(target_user_id)
        prior_actions = self._recent_daily_management_actions(target_user_id, limit=3)
        now = datetime.now()
        expires_at = now + timedelta(seconds=duration_seconds) if duration_seconds > 0 else None
        action_label = self._daily_management_action_label(action_type)
        payload = {
            "action_type": action_type,
            "action_label": action_label,
            "reason": reason,
            "duration_seconds": duration_seconds,
            "expires_at": expires_at.isoformat() if expires_at else "",
            "prior_action_labels": [action["action_label"] for action in prior_actions],
            "public_summary_ref": "",
            "execution_ref": "",
            "bridge_hint": self._daily_management_bridge_hint(action_type),
            "executed_at": now.isoformat(),
        }
        case_id = self.storage.create_case(
            case_type="daily_management",
            title=f"对 {self._format_user(target_user_id)} 作出日常管理：{action_label}",
            description=reason,
            proposer_id=event.user_id,
            target_user_id=target_user_id,
            status="approved",
            phase="closed",
            support_threshold=0,
            vote_duration_seconds=0,
            payload=payload,
        )
        execution_ref = ""
        try:
            if action_type == "short_mute":
                await self.group.ban(target_user_id, duration_seconds)
                execution_ref = f"daily_short_mute:{duration_seconds}s"
            elif action_type == "motion_restriction":
                execution_ref = f"daily_management_motion_restriction:{target_user_id}"
                self.storage.upsert_lock(
                    lock_key=execution_ref,
                    lock_type="daily_management_motion_restriction",
                    target_user_id=target_user_id,
                    source_case_id=case_id,
                    reason=reason,
                    payload={
                        "expires_at": expires_at.isoformat() if expires_at else "",
                        "action_type": action_type,
                        "action_label": action_label,
                        "case_id": case_id,
                    },
                )
            else:
                execution_ref = f"daily_note:{action_type}"
        except Exception as exc:
            self.storage.resolve_case_status(
                case_id=case_id,
                status="cancelled",
                phase="closed",
                resolved_at=datetime.now().isoformat(),
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": {
                        **payload,
                        "execution_error": str(exc),
                        "public_summary_ref": f"daily_management:{case_id}:public_summary",
                    }
                },
            )
            await self.group.send_msg(f"日常管理执行失败：{exc}")
            return

        public_summary_ref = f"daily_management:{case_id}:public_summary"
        self.storage.update_case_fields(
            case_id,
            {
                "resolved_at": now.isoformat(),
                "payload_json": {
                    **payload,
                    "execution_ref": execution_ref,
                    "public_summary_ref": public_summary_ref,
                },
            },
        )
        self.metadata.record_audit_event(
            actor_id=event.user_id,
            action="daily_management_applied",
            subject_type="governance_case",
            subject_id=str(case_id),
            session_key=None,
            result="success",
            context={
                "target_user_id": target_user_id,
                "action_type": action_type,
                "duration_seconds": duration_seconds,
                "reason": reason,
                "public_summary_ref": public_summary_ref,
            },
        )
        lines = [
            f"已记录日常管理 #{case_id}：{self._format_user(target_user_id)} / {action_label}",
            f"- 事实与理由：{reason}",
        ]
        if duration_seconds > 0 and expires_at:
            lines.append(f"- 期限：至 {expires_at.strftime('%Y-%m-%d %H:%M')}（{self._format_duration(duration_seconds)}）")
        if prior_actions:
            prior_labels = "、".join(action["action_label"] for action in prior_actions)
            lines.append(f"- 前序记录：{prior_labels}")
        bridge_hint = self._daily_management_bridge_hint(action_type)
        if bridge_hint:
            lines.append(f"- 后续衔接：{bridge_hint}")
        await self.group.send_msg("\n".join(lines))

    async def sync_members(self, *, silent: bool) -> Dict[str, object]:
        members = await self.group.get_group_member_list()
        member_count = 0
        human_admin_ids: List[int] = []
        platform_owner_ids: List[int] = []
        for member in members:
            user_id = int(member.get("user_id") or 0)
            if user_id <= 0:
                continue
            member_count += 1
            self.storage.upsert_member_profile(member)
            role_code = str(member.get("role") or "member").strip().lower() or "member"
            if role_code == "admin" and user_id != self.group.self_id:
                human_admin_ids.append(user_id)
            if role_code == "owner":
                platform_owner_ids.append(user_id)
        return {
            "member_count": member_count,
            "human_admin_ids": sorted(human_admin_ids),
            "platform_owner_ids": sorted(platform_owner_ids),
        }

    async def _ensure_bootstrap_permission(self, event: GroupMessageEvent) -> bool:
        if self._has_bootstrap_override_authority(user_id=event.user_id, event=event):
            return True
        await self.group.send_msg("该操作需要当前平台管理员或已登记的荣誉群主权限。")
        return False

    async def _ensure_member_profile(self, user_id: int) -> Dict[str, object]:
        profile = self.storage.get_member_profile(user_id)
        if profile:
            return profile
        try:
            member_info = await self.group.get_group_member_info(user_id)
        except Exception:
            member_info = {"user_id": user_id, "nickname": f"QQ:{user_id}", "role": "member"}
        self.storage.upsert_member_profile(member_info)
        return self.storage.get_member_profile(user_id) or {"user_id": user_id}

    def _build_governance_system_event(self, *, action: str, case_id: int):
        try:
            system_user_id = int(self.group.self_id)
        except Exception:
            system_user_id = 0
        event_ref = f"auto-{action}-{case_id}-{int(datetime.now().timestamp())}"
        return SimpleNamespace(
            group_id=int(getattr(self.group, "group_id", 0) or 0),
            self_id=system_user_id,
            user_id=system_user_id,
            event_id=event_ref,
            message_id=event_ref,
            sender=SimpleNamespace(role="admin"),
        )

    def _detect_due_governance_action(self, case: Dict[str, object]) -> str:
        case_type = str(case.get("case_type") or "")
        status = str(case.get("status") or "")
        phase = str(case.get("phase") or "")
        payload = case.get("payload") or {}
        now = datetime.now()
        if case_type == "elder_reboot" and status == "cooling":
            cooldown_until = self._parse_datetime(case.get("cooldown_until"))
            if cooldown_until and now >= cooldown_until:
                return "cooling_elapsed"
        if case_type == "honor_owner_election":
            nomination_closes_at = self._case_payload_datetime(case, "nomination_closes_at")
            if status == "nomination_publicity" and nomination_closes_at and now >= nomination_closes_at:
                return "nomination_publicity_elapsed"
            questioning_closes_at = self._case_payload_datetime(case, "questioning_closes_at")
            if status == "statement_and_questioning" and questioning_closes_at and now >= questioning_closes_at:
                return "questioning_elapsed"
            if status == "runoff_voting":
                return "runoff_ready"
        if case_type == "elder_election":
            nomination_closes_at = self._case_payload_datetime(case, "nomination_closes_at")
            if status == "nomination_publicity" and nomination_closes_at and now >= nomination_closes_at:
                return "nomination_publicity_elapsed"
            if status == "runoff_voting":
                return "runoff_ready"
        if case_type == "ordinary_proposal":
            review_due_at = self._case_payload_datetime(case, "review_due_at")
            discussion_closes_at = self._case_payload_datetime(case, "discussion_closes_at")
            if status == "active" and phase == "procedural_review" and review_due_at and now >= review_due_at:
                return "proposal_review_due"
            if status == "active" and phase == "discussion" and discussion_closes_at and now >= discussion_closes_at:
                return "proposal_discussion_elapsed"
        if case_type in {"honor_owner_impeachment", "elder_impeachment"} and status == "response_window":
            response_window_closes_at = self._case_payload_datetime(case, "response_window_closes_at")
            if response_window_closes_at and now >= response_window_closes_at:
                return "response_window_elapsed"
        if case_type == "emergency_protection" and status == "active":
            response_due_at = self._case_payload_datetime(case, "response_due_at")
            if phase == "honor_owner_response_pending" and response_due_at and now >= response_due_at:
                return "honor_owner_response_elapsed"
            executed_measure_type = str(payload.get("executed_measure_type") or "").strip()
            if executed_measure_type:
                temporary_measure_ends_at = self._case_payload_datetime(case, "temporary_measure_ends_at")
                if executed_measure_type == "ban" and temporary_measure_ends_at and now >= temporary_measure_ends_at:
                    return "temporary_measure_elapsed"
                formal_bridge_due_at = self._case_payload_datetime(case, "formal_bridge_due_at") or self._case_payload_datetime(
                    case,
                    "measure_expires_at",
                )
                if formal_bridge_due_at and now >= formal_bridge_due_at:
                    return "formal_bridge_due"
                initial_review_due_at = self._case_payload_datetime(case, "initial_review_due_at")
                if initial_review_due_at and now >= initial_review_due_at and not payload.get("objective_reason_published_at"):
                    return "initial_review_due"
        if case_type == "formal_discipline" and status == "active":
            if phase == "acceptance_review":
                acceptance_due_at = self._case_payload_datetime(case, "acceptance_due_at")
                if acceptance_due_at and now >= acceptance_due_at:
                    return "acceptance_due"
            if phase == "accepted":
                return "notice_ready"
            if phase == "notice_in_progress":
                deemed_service_deadline = self._case_payload_datetime(case, "deemed_service_deadline")
                if deemed_service_deadline and now >= deemed_service_deadline:
                    return "notice_due"
            if phase == "defense_window":
                defense_closes_at = self._case_payload_datetime(case, "defense_closes_at")
                if defense_closes_at and now >= defense_closes_at:
                    return "defense_due"
        if case_type == "formal_discipline_review":
            if phase == "review_start_check":
                start_check_due_at = self._case_payload_datetime(case, "start_check_due_at")
                if start_check_due_at and now >= start_check_due_at:
                    return "review_start_due"
            if phase == "reopened":
                return "reopened_followup"
            if status == "rejected" and phase == "denied":
                return "denied_followup"
        return ""

    async def _queue_case_vote_start(
        self,
        *,
        case_id: int,
        event,
    ) -> bool:
        if self.group.is_voting:
            return False
        self.group.set_voting(True)
        asyncio.create_task(self._start_case_vote(case_id=case_id, event=event, preclaimed=True))
        return True

    async def _auto_advance_due_case(
        self,
        *,
        case: Dict[str, object],
        reason: str,
    ) -> str:
        case_id = int(case["case_id"])
        event = self._build_governance_system_event(action=reason, case_id=case_id)
        if case["case_type"] == "honor_owner_election":
            if reason in {"questioning_elapsed", "runoff_ready"}:
                notice = (
                    f"案件 #{case_id} 陈述与质询期已结束，开始进入群体表决。"
                    if reason == "questioning_elapsed"
                    else f"案件 #{case_id} 已进入荣誉群主复选，开始第二轮表决。"
                )
                await self.group.send_msg(notice)
                return "queued_vote" if await self._queue_case_vote_start(case_id=case_id, event=event) else "vote_deferred"
            await self._advance_honor_owner_election_case(case=case, event=event)
            return "advanced"
        if case["case_type"] == "elder_election":
            if reason in {"nomination_publicity_elapsed", "runoff_ready"} and (
                reason == "runoff_ready" or bool(self._case_candidate_ids(case))
            ):
                notice = (
                    f"案件 #{case_id} 提名公示期已结束，现有候选人 {len(self._case_candidate_ids(case))} 名，开始进入元老会选举表决。"
                    if reason == "nomination_publicity_elapsed"
                    else f"案件 #{case_id} 已进入元老选举加投阶段，开始新一轮表决。"
                )
                await self.group.send_msg(notice)
                return "queued_vote" if await self._queue_case_vote_start(case_id=case_id, event=event) else "vote_deferred"
            await self._advance_elder_election_case(case=case, event=event)
            return "advanced"
        if case["case_type"] == "ordinary_proposal":
            if reason == "proposal_discussion_elapsed":
                await self.group.send_msg(f"案件 #{case_id} 讨论期已结束，开始进入表决。")
                return "queued_vote" if await self._queue_case_vote_start(case_id=case_id, event=event) else "vote_deferred"
            await self._advance_proposal_case(case=case, event=event)
            return "advanced"
        if case["case_type"] in {"honor_owner_impeachment", "elder_impeachment"} and reason == "response_window_elapsed":
            await self.group.send_msg(f"案件 #{case_id} 回应期已结束，开始进入群体表决。")
            return "queued_vote" if await self._queue_case_vote_start(case_id=case_id, event=event) else "vote_deferred"
        if case["case_type"] == "elder_reboot" and reason == "cooling_elapsed":
            await self.group.send_msg(f"案件 #{case_id} 冷却期已结束，开始进入最终表决。")
            return "queued_vote" if await self._queue_case_vote_start(case_id=case_id, event=event) else "vote_deferred"
        if case["case_type"] == "emergency_protection":
            await self._advance_emergency_protection_case(case=case)
            return "advanced"
        if case["case_type"] == "formal_discipline":
            await self._advance_formal_discipline_case(case=case, event=event)
            return "advanced"
        if case["case_type"] == "formal_discipline_review":
            await self._advance_formal_discipline_review_case(case=case, event=event)
            return "advanced"
        return "ignored"

    async def auto_advance_due_cases(
        self,
        *,
        trigger: str,
        actor_id: Optional[int] = None,
    ) -> Dict[str, object]:
        self._release_expired_formal_discipline_locks()
        scanned_cases = list(reversed(self.storage.list_active_cases(limit=64)))
        summary = {
            "checked": len(scanned_cases),
            "advanced": 0,
            "queued_votes": 0,
            "deferred_votes": 0,
            "case_ids": [],
        }
        for listed_case in scanned_cases:
            case_id = int(listed_case["case_id"])
            for _ in range(4):
                case = self.storage.get_case(case_id)
                if not case:
                    break
                reason = self._detect_due_governance_action(case)
                if not reason:
                    break
                before_status = str(case.get("status") or "")
                before_phase = str(case.get("phase") or "")
                try:
                    result = await self._auto_advance_due_case(case=case, reason=reason)
                except Exception as exc:
                    traceback.print_exc()
                    self.metadata.record_audit_event(
                        actor_id=actor_id,
                        action="governance_case_auto_advanced",
                        subject_type="governance_case",
                        subject_id=str(case_id),
                        session_key=None,
                        result="failed",
                        context={
                            "trigger": trigger,
                            "reason": reason,
                            "case_type": str(case.get("case_type") or ""),
                            "before_status": before_status,
                            "before_phase": before_phase,
                            "error": str(exc),
                        },
                    )
                    break
                refreshed_case = self.storage.get_case(case_id) or case
                after_status = str(refreshed_case.get("status") or "")
                after_phase = str(refreshed_case.get("phase") or "")
                self.metadata.record_audit_event(
                    actor_id=actor_id,
                    action="governance_case_auto_advanced",
                    subject_type="governance_case",
                    subject_id=str(case_id),
                    session_key=None,
                    result="success" if result != "vote_deferred" else "deferred",
                    context={
                        "trigger": trigger,
                        "reason": reason,
                        "result": result,
                        "case_type": str(case.get("case_type") or ""),
                        "before_status": before_status,
                        "before_phase": before_phase,
                        "after_status": after_status,
                        "after_phase": after_phase,
                    },
                )
                if result == "ignored":
                    break
                summary["advanced"] += 1
                if case_id not in summary["case_ids"]:
                    summary["case_ids"].append(case_id)
                if result == "queued_vote":
                    summary["queued_votes"] += 1
                    break
                if result == "vote_deferred":
                    summary["deferred_votes"] += 1
                    break
        return summary

    async def _ensure_governance_participant(self, user_id: int) -> bool:
        self._release_expired_formal_discipline_locks()
        await self._ensure_member_profile(user_id)
        return not self.storage.has_role(user_id, "suspended")

    async def _set_honor_owner(
        self,
        *,
        target_user_id: int,
        operator_id: int,
        source: str,
        sync_platform_admin: bool,
    ) -> Dict[str, object]:
        await self._ensure_member_profile(target_user_id)
        previous = self.storage.get_active_role_user("honor_owner")
        if previous and previous != target_user_id:
            self.storage.revoke_role(previous, "honor_owner", operator_id=operator_id, notes="replace_honor_owner")
        revoked_elder = False
        if self.storage.has_role(target_user_id, "elder"):
            self.storage.revoke_role(
                target_user_id,
                "elder",
                operator_id=operator_id,
                notes=f"honor_owner_assignment:{source}",
            )
            revoked_elder = True
        self.storage.set_role_status(
            user_id=target_user_id,
            role_code="honor_owner",
            status="active",
            source=source,
            operator_id=operator_id,
            notes=source,
        )
        warnings: List[str] = []
        if sync_platform_admin:
            warnings = await self._sync_platform_admin(target_user_id)
        return {
            "display_name": self._format_user(target_user_id),
            "platform_sync_warnings": warnings,
            "revoked_elder": revoked_elder,
        }

    async def _sync_platform_admin(self, target_user_id: Optional[int]) -> List[str]:
        warnings: List[str] = []
        try:
            members = await self.group.get_group_member_list()
        except Exception as exc:
            return [f"读取群成员列表失败：{exc}"]
        for member in members:
            user_id = int(member.get("user_id") or 0)
            role_code = str(member.get("role") or "member").strip().lower() or "member"
            if user_id == self.group.self_id or role_code != "admin":
                continue
            if target_user_id is None or user_id != target_user_id:
                try:
                    await self.group.set_group_admin(user_id, False)
                except Exception as exc:
                    warnings.append(f"取消管理员 {self._format_user(user_id)} 失败：{exc}")
        if target_user_id is not None:
            try:
                await self.group.set_group_admin(target_user_id, True)
            except Exception as exc:
                warnings.append(f"设置管理员 {self._format_user(target_user_id)} 失败：{exc}")
        await self.sync_members(silent=True)
        return warnings

    async def _advance_case_after_support(self, *, case_id: int, event: GroupMessageEvent) -> None:
        case = self.storage.get_case(case_id)
        if not case or case["status"] != "supporting":
            return
        supporters = self.storage.count_case_supporters(case_id)
        threshold = int(case.get("support_threshold") or 0)
        if supporters < threshold:
            return
        if case["case_type"] == "ordinary_proposal" and str(case.get("phase") or "") == "procedurally_rejected":
            await self.group.send_msg(
                f"案件 #{case_id} 已达到提案驳回复决联署门槛，开始进入全体表决。"
            )
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if case["case_type"] == "formal_discipline":
            acceptance_hours = self._config_int("governance_formal_acceptance_hours", 48)
            accepted_due_at = datetime.now() + timedelta(hours=acceptance_hours)
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "active",
                    "phase": "acceptance_review",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "acceptance_due_at": accepted_due_at.isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已达到正式立案联署门槛，进入受理审查。\n"
                f"- 受理最晚截止：{accepted_due_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- 可由元老会成员或荣誉群主使用“推进治理案件 {case_id}”提前受理；逾期视为受理。"
            )
            return
        if case["case_type"] == "formal_discipline_review":
            now = datetime.now()
            source_case_id = self._case_payload_int(case, "source_case_id")
            source_case = self.storage.get_case(source_case_id) if source_case_id > 0 else None
            request_deadline = self._formal_discipline_review_request_deadline(source_case) if source_case else None
            if source_case is None:
                self.storage.update_case_fields(
                    case_id,
                    {
                        "status": "rejected",
                        "phase": "denied",
                        "resolved_at": now.isoformat(),
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "denied_at": now.isoformat(),
                                "denial_reason": "原正式处分案件不存在，无法进入复核启动审查。",
                            },
                        ),
                    },
                )
                await self.group.send_msg(
                    f"案件 #{case_id} 对应的原正式处分案件不存在，已直接驳回复核申请。"
                )
                return
            if request_deadline is None or now > request_deadline:
                self.storage.update_case_fields(
                    case_id,
                    {
                        "status": "rejected",
                        "phase": "denied",
                        "resolved_at": now.isoformat(),
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "submitted_at": now.isoformat(),
                                "denied_at": now.isoformat(),
                                "denial_reason": "已超过正式处分结果公示后的 48 小时复核申请期限。",
                            },
                        ),
                    },
                )
                await self.group.send_msg(
                    f"案件 #{case_id} 虽已达到处分复核联署门槛，但已超过法定复核申请期限，现直接驳回。"
                )
                return
            start_check_due_at = now + timedelta(hours=self._config_int("governance_formal_review_start_hours", 48))
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "active",
                    "phase": "review_start_check",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "submitted_at": now.isoformat(),
                            "start_check_due_at": start_check_due_at.isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已达到处分复核联署门槛，进入启动审查。\n"
                f"- 启动最晚截止：{start_check_due_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- 可由元老会成员或荣誉群主使用“推进治理案件 {case_id}”提前作出启动/驳回决定；逾期按法定理由自动处理。"
            )
            return
        if case["case_type"] == "honor_owner_impeachment":
            response_hours = self._config_int("governance_impeachment_response_hours", 12)
            response_opened_at = datetime.now()
            self._record_elder_council_resolution(
                case_id=case_id,
                proposer_id=int(case["proposer_id"]),
                decision_kind="start_honor_owner_impeachment",
                reason=str(case.get("description") or (case.get("payload") or {}).get("reason") or "").strip(),
                supporter_ids=self._case_supporter_ids(case_id),
            )
            self.storage.upsert_lock(
                lock_key=f"case:{case_id}:honor_owner_powers",
                lock_type="honor_owner_powers",
                target_user_id=case.get("target_user_id"),
                source_case_id=case_id,
                reason="荣誉群主弹劾已成立，冻结治理权力",
                payload={},
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "response_window",
                    "phase": "response_window",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "response_window_opened_at": response_opened_at.isoformat(),
                            "response_window_closes_at": (
                                response_opened_at + timedelta(hours=response_hours)
                            ).isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已达到元老联署门槛，进入 {response_hours} 小时回应期。\n"
                f"期满后请使用“推进治理案件 {case_id}”进入群体表决。"
            )
            return
        if case["case_type"] == "elder_impeachment":
            response_hours = self._config_int("governance_impeachment_response_hours", 12)
            response_opened_at = datetime.now()
            self.storage.upsert_lock(
                lock_key=f"case:{case_id}:elder_powers:{case.get('target_user_id')}",
                lock_type="elder_powers",
                target_user_id=case.get("target_user_id"),
                source_case_id=case_id,
                reason="元老弹劾已成立，冻结元老职权",
                payload={},
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "response_window",
                    "phase": "response_window",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "response_window_opened_at": response_opened_at.isoformat(),
                            "response_window_closes_at": (
                                response_opened_at + timedelta(hours=response_hours)
                            ).isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已达到联署门槛，进入 {response_hours} 小时回应期。\n"
                f"期满后请使用“推进治理案件 {case_id}”进入群体表决。"
            )
            return
        if case["case_type"] == "elder_reboot":
            cooldown_hours = self._config_int("governance_reboot_cooldown_hours", 12)
            cooling_opened_at = datetime.now()
            cooling_closes_at = cooling_opened_at + timedelta(hours=cooldown_hours)
            self.storage.upsert_lock(
                lock_key=f"case:{case_id}:ban_global",
                lock_type="ban_global",
                target_user_id=None,
                source_case_id=case_id,
                reason="重组元老会动议已成立，冻结禁言权力",
                payload={},
            )
            self.storage.upsert_lock(
                lock_key=f"case:{case_id}:kick_global",
                lock_type="kick_global",
                target_user_id=None,
                source_case_id=case_id,
                reason="重组元老会动议已成立，冻结踢人权力",
                payload={},
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "cooling",
                    "phase": "cooldown",
                    "cooldown_until": cooling_closes_at.isoformat(),
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "established_at": cooling_opened_at.isoformat(),
                            "protected_at": cooling_opened_at.isoformat(),
                            "cooling_opened_at": cooling_opened_at.isoformat(),
                            "cooling_closes_at": cooling_closes_at.isoformat(),
                            "constitutional_remedy": True,
                            "not_daily_struggle_tool": True,
                            "procedure_protection_active": True,
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已达到联署门槛，进入 {cooldown_hours} 小时冷却期。\n"
                "- 当前按宪制级救济程序处理，不得作为日常斗争工具使用。\n"
                "- 禁言与踢人权力现已冻结。"
            )
            return
        if case["case_type"] == "emergency_protection":
            established_at = datetime.now()
            initial_review_due_at = established_at + timedelta(hours=24)
            measure_expires_at = established_at + timedelta(hours=48)
            response_due_at = established_at + timedelta(hours=2)
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "active",
                    "phase": "honor_owner_response_pending",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "established_at": established_at.isoformat(),
                            "response_due_at": response_due_at.isoformat(),
                            "initial_review_due_at": initial_review_due_at.isoformat(),
                            "measure_expires_at": measure_expires_at.isoformat(),
                            "formal_bridge_due_at": measure_expires_at.isoformat(),
                            "notice_ref": f"group_emergency_case:{case_id}",
                            "requested_measures": ["temporary_mute", "temporary_removal"],
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已生效，进入荣誉群主响应期。\n"
                f"- 响应截止：{response_due_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- 初步复核节点：{initial_review_due_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- 转正式处分截止：{measure_expires_at.strftime('%Y-%m-%d %H:%M')}"
            )

    async def _start_case_vote(self, *, case_id: int, event: GroupMessageEvent, preclaimed: bool = False) -> None:
        case = self.storage.get_case(case_id)
        if not case:
            await self.group.send_msg("案件不存在，无法启动表决。")
            return
        if self.group.is_voting and not preclaimed:
            await self.group.send_msg("本群已有投票活动正在进行，请稍后再试。")
            return
        self.group.set_voting(True)
        ballot = self._build_case_ballot(case)
        options = ballot["options"]
        max_selections = int(ballot["max_selections"])
        vote_status = "runoff_voting" if case["status"] == "runoff_voting" else "voting"
        vote_phase = "runoff_voting" if case["status"] == "runoff_voting" else "vote"

        vote_duration_seconds = int(case.get("vote_duration_seconds") or 0) or self._config_int(
            "governance_vote_duration_seconds", 300
        )
        session_key = _build_session_key(self.group.group_id, f"governance_case_vote_{case_id}", "group")
        if not self.metadata.start_vote_session(
            actor_id=event.user_id,
            session_key=session_key,
            flow="governance_vote",
            ttl_seconds=vote_duration_seconds + 300,
            idempotency_key=_build_idempotency_key(event, "governance_vote_start", session_key),
            initial_data={"case_id": case_id, "case_type": case["case_type"]},
            audit_context={"case_id": case_id, "case_type": case["case_type"]},
        ):
            await self.group.send_msg("治理投票会话创建失败，请稍后再试。")
            return

        self.storage.update_case_fields(
            case_id,
            {
                "status": vote_status,
                "phase": vote_phase,
                "vote_started_at": datetime.now().isoformat(),
                "vote_ends_at": (datetime.now() + timedelta(seconds=vote_duration_seconds)).isoformat(),
            },
        )
        matcher = None
        try:
            option_lines = [f"{index}. {label}" for index, label in enumerate(options, start=1)]
            selection_hint = (
                f"请在 {vote_duration_seconds} 秒内发送序号完成表态。"
                if max_selections == 1
                else f"请在 {vote_duration_seconds} 秒内发送 1 到 {max_selections} 个序号，可用空格或逗号分隔。"
            )
            await self.group.send_msg(
                f"治理案件 #{case_id} 开始表决：\n{case['title']}\n"
                + "\n".join(option_lines)
                + f"\n{selection_hint}"
            )
            matcher = on_alconna(Alconna(r"re:^[\d\s,，]+$"))

            async def _handle_vote(vote_event: GroupMessageEvent):
                choice_text = vote_event.get_message().extract_plain_text().strip()
                choices = self._parse_vote_choices(
                    raw_text=choice_text,
                    option_count=len(options),
                    max_selections=max_selections,
                )
                if not choices:
                    return
                can_vote, denied_reason = await self._ensure_governance_vote_participant(vote_event.user_id)
                if not can_vote:
                    await self.group.send_msg(denied_reason)
                    return
                if not self.storage.reserve_case_votes(case_id, vote_event.user_id, choices):
                    await self.group.send_msg("您已参与过该治理表决。")
                    return
                await self.group.send_msg(self._format_ballot_acknowledgement(vote_event.user_id, options, choices))

            matcher.append_handler(_handle_vote)
            await asyncio.sleep(vote_duration_seconds)
            tallies = self.storage.count_case_votes(case_id)
            voter_count = self.storage.count_case_voters(case_id)
            latest_case = self.storage.get_case(case_id) or case
            result_text = await self._finalize_case_vote(
                case_id=case_id,
                case=latest_case,
                tallies=tallies,
                voter_count=voter_count,
            )
            await matcher.send(result_text)
            matcher.destroy()
            matcher = None
            self.metadata.finish_vote_session(
                actor_id=event.user_id,
                session_key=session_key,
                audit_context={"case_id": case_id, "tallies": tallies},
            )
        except Exception as exc:
            traceback.print_exc()
            await self.group.send_msg(f"治理投票执行失败：{exc}")
        finally:
            if matcher is not None:
                matcher.destroy()
            self.group.set_voting(False)

    async def _finalize_case_vote(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        tallies: Dict[int, int],
        voter_count: int,
    ) -> str:
        if case["case_type"] == "honor_owner_election":
            return await self._finalize_honor_owner_election_vote(
                case_id=case_id,
                case=case,
                tallies=tallies,
                voter_count=voter_count,
            )
        if case["case_type"] == "elder_election":
            return await self._finalize_elder_election_vote(
                case_id=case_id,
                case=case,
                tallies=tallies,
                voter_count=voter_count,
            )
        if case["case_type"] == "ordinary_proposal":
            return await self._finalize_proposal_vote(
                case_id=case_id,
                case=case,
                tallies=tallies,
                voter_count=voter_count,
            )
        if case["case_type"] == "formal_discipline":
            return await self._finalize_formal_discipline_vote(
                case_id=case_id,
                case=case,
                tallies=tallies,
                voter_count=voter_count,
            )
        yes_votes = int(tallies.get(1, 0))
        no_votes = int(tallies.get(2, 0))
        member_count = max(self.storage.member_count(), voter_count)
        approved, threshold_lines = self._evaluate_vote_result(
            case_type=str(case["case_type"]),
            yes_votes=yes_votes,
            no_votes=no_votes,
            member_count=member_count,
            turnout=voter_count,
        )
        resolution_lines: List[str] = list(threshold_lines)
        if approved:
            resolution_lines.append("表决结果：通过")
            if case["case_type"] == "honor_owner_election":
                summary = await self._set_honor_owner(
                    target_user_id=int(case["target_user_id"]),
                    operator_id=int(case["proposer_id"]),
                    source=f"case:{case_id}",
                    sync_platform_admin=True,
                )
                resolution_lines.append(f"执行结果：已任命 {summary['display_name']} 为荣誉群主")
            elif case["case_type"] == "honor_owner_impeachment":
                self.storage.revoke_role(
                    int(case["target_user_id"]),
                    "honor_owner",
                    operator_id=int(case["proposer_id"]),
                    notes=f"case:{case_id}",
                )
                warnings = await self._sync_platform_admin(None)
                resolution_lines.append(f"执行结果：已撤销 {self._format_user(case['target_user_id'])} 的荣誉群主职权")
                by_election_case_id = self._ensure_honor_owner_by_election_case(
                    operator_id=int(case["proposer_id"]),
                    source_case_id=case_id,
                    reopen_reason="荣誉群主弹劾已通过，自动进入补选提名程序。",
                    failure_count=0,
                )
                resolution_lines.append(f"已自动启动荣誉群主补选提名：案件 #{by_election_case_id}")
                if warnings:
                    resolution_lines.append(f"平台管理员同步提醒：{'; '.join(warnings)}")
            elif case["case_type"] == "elder_impeachment":
                self.storage.revoke_role(
                    int(case["target_user_id"]),
                    "elder",
                    operator_id=int(case["proposer_id"]),
                    notes=f"case:{case_id}",
                )
                resolution_lines.append(f"执行结果：已撤销 {self._format_user(case['target_user_id'])} 的元老会职权")
                vacancy_count = self._determine_elder_election_seat_count()
                if vacancy_count > 0:
                    by_election_case_id = self._ensure_elder_by_election_case(
                        operator_id=int(case["proposer_id"]),
                        source_case_id=case_id,
                        reopen_reason="元老弹劾已通过，自动进入补选提名程序。",
                        seat_count=vacancy_count,
                    )
                    resolution_lines.append(f"已自动启动元老补选提名：案件 #{by_election_case_id}")
                else:
                    resolution_lines.append("后续处理：当前未检测到待补席位。")
                impeachment_vacancies, original_seat_count = self._elder_impeachment_vacancy_progress()
                if original_seat_count > 0 and impeachment_vacancies * 2 >= original_seat_count:
                    resolution_lines.append(
                        f"制度提醒：本届元老会因弹劾累计出缺 {impeachment_vacancies}/{original_seat_count} 席，已达到原席位半数。"
                    )
                    resolution_lines.append("任何有表决资格成员现可直接以此为新的重大事实发起重组元老会。")
            elif case["case_type"] == "elder_reboot":
                previous_elder_count = len(self.storage.get_active_role_users("elder"))
                expected_seat_count = (
                    previous_elder_count
                    if previous_elder_count in {3, 5, 7}
                    else self._desired_elder_seat_count()
                )
                self.storage.revoke_all_roles("elder", operator_id=int(case["proposer_id"]), notes=f"case:{case_id}")
                resolution_lines.append("执行结果：本届元老会已整体解散，请后续补选。")
                deadline_at = datetime.now() + timedelta(hours=72)
                election_case_id = self._ensure_elder_by_election_case(
                    operator_id=int(case["proposer_id"]),
                    source_case_id=case_id,
                    reopen_reason="重组元老会已通过，自动启动新一届元老会提名程序。",
                    seat_count=max(expected_seat_count, 1),
                )
                self.storage.update_case_fields(
                    case_id,
                    {
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "new_council_election_required": True,
                                "new_council_election_deadline_at": deadline_at.isoformat(),
                                "new_council_election_seat_count": max(expected_seat_count, 1),
                                "new_council_election_started_case_id": election_case_id,
                                "constitutional_remedy_effective_at": datetime.now().isoformat(),
                                "interim_supervision_active": True,
                                "interim_supervision_mode": "honor_owner_daily_only",
                                "interim_supervision_scope": "新元老会产生前，由荣誉群主仅处理日常事务与客观安全风险。",
                                "honor_owner_self_review_channel": "涉及荣誉群主自身监督事项，应提交全体表决权成员临时复核。",
                                "new_council_failed_election_rounds": 0,
                                "temporary_collective_supervision_active": False,
                                "temporary_collective_supervision_threshold": self._reboot_temporary_collective_supervision_failures(),
                                "restoration_state": "pending_new_council",
                            },
                        )
                    },
                )
                resolution_lines.append(
                    f"已自动启动新一届元老会选举：案件 #{election_case_id}，最晚启动时限 {deadline_at.strftime('%Y-%m-%d %H:%M')}。"
                )
                resolution_lines.append("临时监督：新元老会产生前，由荣誉群主仅处理日常事务；涉及其自身监督事项，应提交全体表决权成员临时复核。")
            status = "approved"
        else:
            resolution_lines.append("表决结果：未通过")
            if case["case_type"] == "honor_owner_election":
                if not self.storage.get_active_role_user("honor_owner"):
                    failed_rounds = self._case_payload_int(case, "consecutive_failed_by_election_rounds") + 1
                    by_election_case_id = self._ensure_honor_owner_by_election_case(
                        operator_id=int(case["proposer_id"]),
                        source_case_id=case_id,
                        reopen_reason="前次荣誉群主选举未产生新任，自动重新开启提名。",
                        ignore_case_id=case_id,
                        failure_count=failed_rounds,
                    )
                    resolution_lines.append(f"已自动重新开启荣誉群主补选提名：案件 #{by_election_case_id}")
                else:
                    resolution_lines.append("后续处理：当前未产生新任荣誉群主，可重新提名后再次发起。")
            elif case["case_type"] == "honor_owner_impeachment":
                resolution_lines.append("执行结果：已恢复被冻结的荣誉群主职权，弹劾记录保留。")
                resolution_lines.append("如存在伪造证据或反复滥用弹劾情形，可另行按日常管理追责。")
            elif case["case_type"] == "elder_impeachment":
                resolution_lines.append("执行结果：已恢复被冻结的元老职权，弹劾记录保留。")
            status = "rejected"
        self.storage.resolve_case_status(case_id=case_id, status=status, phase="closed", resolved_at=datetime.now().isoformat())
        self.storage.release_case_locks(case_id)
        lines = [
            f"治理案件 #{case_id}（{CASE_TYPE_LABELS.get(case['case_type'], case['case_type'])}）投票结束。",
            f"- 赞成：{yes_votes} 票",
            f"- 反对：{no_votes} 票",
            f"- 参与投票：{voter_count} 人",
        ]
        lines.extend(f"- {line}" for line in resolution_lines)
        return "\n".join(lines)

    async def _finalize_proposal_vote(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        tallies: Dict[int, int],
        voter_count: int,
    ) -> str:
        payload = case.get("payload") or {}
        proposal_type = str(payload.get("proposal_type") or "ordinary_proposal")
        threshold_ref = self._proposal_threshold_ref(proposal_type)
        yes_votes = int(tallies.get(1, 0))
        no_votes = int(tallies.get(2, 0))
        abstain_votes = int(tallies.get(3, 0))
        roster_total = max(self._current_voting_member_count(), voter_count)
        approved, threshold_lines = self._evaluate_threshold_ref_vote_result(
            threshold_ref=threshold_ref,
            yes_votes=yes_votes,
            no_votes=no_votes,
            member_count=roster_total,
            turnout=voter_count,
        )
        now = datetime.now()
        tally_payload = {
            "approve": yes_votes,
            "reject": no_votes,
            "abstain": abstain_votes,
            "turnout": voter_count,
            "roster_total": roster_total,
        }
        decision_summary = self._build_proposal_decision_summary(
            case=case,
            approved=approved,
            tally_payload=tally_payload,
            closed_at=now,
        )
        resolution_status = "approved" if approved else "rejected"
        self.storage.resolve_case_status(case_id=case_id, status=resolution_status, phase="closed", resolved_at=now.isoformat())
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "threshold_set": threshold_ref,
                        "tally": tally_payload,
                        "decision_summary": decision_summary,
                        "law_version_snapshot": self._current_law_version_label(),
                        "public_summary_ref": f"proposal_case:{case_id}:public_summary",
                        "published_at": now.isoformat(),
                        "closed_at": now.isoformat(),
                        "effective_at": now.isoformat() if approved else "",
                        "non_retroactivity_boundary_notice": self._proposal_non_retroactivity_note(),
                    },
                )
            },
        )
        self.metadata.record_audit_event(
            actor_id=int(case.get("proposer_id") or 0),
            action="proposal_result_published",
            subject_type="governance_case",
            subject_id=str(case_id),
            session_key=None,
            result="approved" if approved else "rejected",
            context={
                "proposal_type": proposal_type,
                "tally": tally_payload,
                "threshold_ref": threshold_ref,
            },
        )
        lines = [
            f"治理案件 #{case_id}（{self._proposal_type_label(proposal_type)}）投票结束。",
            f"- 标题：{case['title']}",
            f"- 选民名册总数：{roster_total}",
            f"- 赞成：{yes_votes} 票",
            f"- 反对：{no_votes} 票",
            f"- 弃权：{abstain_votes} 票",
            f"- 参与投票：{voter_count} 人",
        ]
        lines.extend(f"- {line}" for line in threshold_lines)
        lines.append(f"- 表决结果：{'通过' if approved else '未通过'}")
        lines.append(f"- 结果摘要：{decision_summary}")
        lines.append("- 表决结果已在群内公示；如认为存在程序错误，可使用“申请提案复核 <案件ID> [理由]”。")
        return "\n".join(lines)

    async def _advance_honor_owner_election_case(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        if case["status"] == "nomination_publicity":
            nomination_closes_at = self._case_payload_datetime(case, "nomination_closes_at")
            if nomination_closes_at and datetime.now() < nomination_closes_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在提名公示期，约剩余 {self._format_remaining_time(nomination_closes_at)}。"
                )
                return
            if not self._honor_owner_case_has_candidate(case):
                nomination_hours = self._config_int("governance_nomination_publicity_hours", 24)
                reopened_at = datetime.now()
                pending_confirmations = self._pending_honor_owner_nomination_count(case, status="pending_self_confirmation")
                pending_support = self._pending_honor_owner_nomination_count(case, status="pending_support")
                self.storage.update_case_fields(
                    case_id,
                    {
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "nomination_opened_at": reopened_at.isoformat(),
                                "nomination_closes_at": (reopened_at + timedelta(hours=nomination_hours)).isoformat(),
                                "nomination_reopen_count": self._case_payload_int(case, "nomination_reopen_count") + 1,
                            },
                        )
                    },
                )
                detail_lines = [f"案件 #{case_id} 当前仍无正式候选人，已自动续开 {nomination_hours} 小时提名公示。"]
                if pending_confirmations > 0:
                    detail_lines.append(f"- 当前有 {pending_confirmations} 项联名推荐已达门槛，待候选人本人确认愿意履职并接受监督。")
                elif pending_support > 0:
                    detail_lines.append(f"- 当前另有 {pending_support} 项联名推荐仍未达联名门槛。")
                await self.group.send_msg("\n".join(detail_lines))
                return
            candidate_count = len(self._case_candidate_ids(case))
            questioning_hours = self._config_int("governance_questioning_hours", 12)
            questioning_opened_at = datetime.now()
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "statement_and_questioning",
                    "phase": "statement_and_questioning",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "questioning_opened_at": questioning_opened_at.isoformat(),
                            "questioning_closes_at": (
                                questioning_opened_at + timedelta(hours=questioning_hours)
                            ).isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 提名公示期已结束，现有候选人 {candidate_count} 名，进入 {questioning_hours} 小时陈述与质询期。\n"
                f"期满后请使用“推进治理案件 {case_id}”启动表决。"
            )
            return
        if case["status"] == "statement_and_questioning":
            questioning_closes_at = self._case_payload_datetime(case, "questioning_closes_at")
            if questioning_closes_at and datetime.now() < questioning_closes_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在陈述与质询期，约剩余 {self._format_remaining_time(questioning_closes_at)}。"
                )
                return
            await self.group.send_msg(f"案件 #{case_id} 陈述与质询期已结束，开始进入群体表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if case["status"] == "runoff_voting":
            await self.group.send_msg(f"案件 #{case_id} 已进入荣誉群主复选，开始第二轮表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if case["status"] == "voting":
            await self.group.send_msg(f"案件 #{case_id} 已处于表决阶段，请等待投票结束。")
            return
        await self.group.send_msg(f"案件 #{case_id} 当前状态为 {case['status']}，无需推进。")

    async def _advance_elder_election_case(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        if case["status"] == "nomination_publicity":
            nomination_closes_at = self._case_payload_datetime(case, "nomination_closes_at")
            if nomination_closes_at and datetime.now() < nomination_closes_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在提名公示期，约剩余 {self._format_remaining_time(nomination_closes_at)}。"
                )
                return
            candidate_ids = self._case_candidate_ids(case)
            if not candidate_ids:
                nomination_hours = self._elder_nomination_publicity_hours()
                reopened_at = datetime.now()
                self.storage.update_case_fields(
                    case_id,
                    {
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "nomination_opened_at": reopened_at.isoformat(),
                                "nomination_closes_at": (reopened_at + timedelta(hours=nomination_hours)).isoformat(),
                                "nomination_reopen_count": self._case_payload_int(case, "nomination_reopen_count") + 1,
                            },
                        )
                    },
                )
                await self.group.send_msg(
                    f"案件 #{case_id} 当前仍无候选人，已自动续开 {nomination_hours} 小时提名公示。"
                )
                return
            await self.group.send_msg(
                f"案件 #{case_id} 提名公示期已结束，现有候选人 {len(candidate_ids)} 名，开始进入元老会选举表决。"
            )
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if case["status"] == "runoff_voting":
            await self.group.send_msg(f"案件 #{case_id} 已进入元老选举加投阶段，开始新一轮表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if case["status"] == "voting":
            await self.group.send_msg(f"案件 #{case_id} 已处于表决阶段，请等待投票结束。")
            return
        await self.group.send_msg(f"案件 #{case_id} 当前状态为 {case['status']}，无需推进。")

    async def _advance_proposal_case(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        status = str(case.get("status") or "")
        phase = str(case.get("phase") or "")
        if status == "active" and phase == "procedural_review":
            review_due_at = self._case_payload_datetime(case, "review_due_at")
            if review_due_at and datetime.now() < review_due_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在程序审查期，约剩余 {self._format_remaining_time(review_due_at)}。"
                )
                return
            timeout_patch: Dict[str, object] = {}
            reviewer_id: Optional[int] = None
            if review_due_at is not None:
                timeout_ready, timeout_patch, timeout_message = await self._resolve_timeout_fallback_transition(
                    case=case,
                    event=event,
                    request_kind="proposal_procedural_review",
                    due_at=review_due_at,
                    fallback_stage="discussion",
                )
                if not timeout_ready:
                    await self.group.send_msg(timeout_message)
                    return
                if str(timeout_patch.get("timeout_fallback_actor_stage") or "") != "bot":
                    reviewer_id = int(event.user_id)
            await self._move_proposal_to_discussion(
                case=case,
                reviewer_id=reviewer_id,
                timeout_entry=True,
                extra_payload=timeout_patch,
            )
            lines = [
                f"案件 #{case_id} 的程序审查期已届满，现自动进入讨论期。",
                f"期满后请使用“推进治理案件 {case_id}”或等待自动推进进入表决。",
            ]
            if timeout_patch:
                self._record_elder_council_timeout(
                    case_id=case_id,
                    actor_id=int(case["proposer_id"]),
                    request_kind="proposal_procedural_review",
                    due_at=review_due_at,
                    fallback_stage="discussion",
                    acting_stage=str(timeout_patch.get("timeout_fallback_actor_stage") or ""),
                )
                lines.insert(
                    1,
                    f"- 程序失职记录：已按顺位转由{self._timeout_fallback_stage_label(str(timeout_patch.get('timeout_fallback_actor_stage') or ''))}推进。",
                )
            await self.group.send_msg("\n".join(lines))
            return
        if status == "active" and phase == "correction_requested":
            correction_items = str((case.get("payload") or {}).get("correction_items") or "").strip()
            message = f"案件 #{case_id} 当前待提案人补正。"
            if correction_items:
                message += f"\n- 补正项：{correction_items}"
            message += f"\n- 提案人请使用“补正提案 {case_id} ...”重新提交。"
            await self.group.send_msg(message)
            return
        if status == "active" and phase == "discussion":
            discussion_closes_at = self._case_payload_datetime(case, "discussion_closes_at")
            if discussion_closes_at and datetime.now() < discussion_closes_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在讨论期，约剩余 {self._format_remaining_time(discussion_closes_at)}。"
                )
                return
            await self.group.send_msg(f"案件 #{case_id} 讨论期已结束，开始进入表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if status == "supporting" and phase == "procedurally_rejected":
            current_supporters = self.storage.count_case_supporters(case_id)
            threshold = int(case.get("support_threshold") or 0)
            if current_supporters < threshold:
                await self.group.send_msg(
                    f"案件 #{case_id} 当前为程序性驳回状态。\n"
                    f"- 复决联署：{current_supporters}/{threshold}\n"
                    "- 达到门槛后将直接进入全体表决。"
                )
                return
            await self.group.send_msg(f"案件 #{case_id} 已达到提案驳回复决联署门槛，开始进入全体表决。")
            await self._start_case_vote(case_id=case_id, event=event)
            return
        if status == "voting":
            await self.group.send_msg(f"案件 #{case_id} 已处于表决阶段，请等待投票结束。")
            return
        await self.group.send_msg(f"案件 #{case_id} 当前状态为 {case['status']}，无需推进。")

    async def _advance_impeachment_response_window(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        response_window_closes_at = self._case_payload_datetime(case, "response_window_closes_at")
        if response_window_closes_at and datetime.now() < response_window_closes_at:
            await self.group.send_msg(
                f"案件 #{case_id} 仍在回应期，约剩余 {self._format_remaining_time(response_window_closes_at)}。"
            )
            return
        await self.group.send_msg(f"案件 #{case_id} 回应期已结束，开始进入群体表决。")
        await self._start_case_vote(case_id=case_id, event=event)

    async def _advance_emergency_protection_case(self, *, case: Dict[str, object]) -> None:
        case_id = int(case["case_id"])
        now = datetime.now()
        phase = str(case.get("phase") or "")
        payload = case.get("payload") or {}
        initial_review_due_at = self._case_payload_datetime(case, "initial_review_due_at")
        response_due_at = self._case_payload_datetime(case, "response_due_at")
        formal_bridge_due_at = self._case_payload_datetime(case, "formal_bridge_due_at") or self._case_payload_datetime(
            case,
            "measure_expires_at",
        )
        temporary_measure_ends_at = self._case_payload_datetime(case, "temporary_measure_ends_at")
        executed_measure_type = str(payload.get("executed_measure_type") or "").strip()

        if not executed_measure_type:
            if response_due_at and now < response_due_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在荣誉群主响应期，约剩余 {self._format_remaining_time(response_due_at)}。"
                )
                return
            if phase != "initial_review_due":
                self.storage.update_case_fields(
                    case_id,
                    {
                        "phase": "initial_review_due",
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "response_window_elapsed_at": now.isoformat(),
                            },
                        ),
                    },
                )
            await self.group.send_msg(
                f"案件 #{case_id} 的荣誉群主响应期已过。\n"
                f"- 目标成员：{self._format_user(case.get('target_user_id'))}\n"
                "- 现可由荣誉群主或元老会紧急代理执行临时禁言或临时移出群聊。"
            )
            return

        if executed_measure_type == "ban":
            if temporary_measure_ends_at and now < temporary_measure_ends_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 的临时禁言仍在生效，约剩余 {self._format_remaining_time(temporary_measure_ends_at)}。"
                )
                return
            self.storage.resolve_case_status(
                case_id=case_id,
                status="approved",
                phase="closed",
                resolved_at=now.isoformat(),
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "closure_report_ref": f"emergency_case:{case_id}:post_review",
                            "participation_restored_at": now.isoformat(),
                            "closed_at": now.isoformat(),
                        },
                    )
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 的临时禁言已结束，紧急防护案件自动关闭。\n"
                "当前默认恢复正常参与。"
            )
            return

        if initial_review_due_at and now < initial_review_due_at:
            await self.group.send_msg(
                f"案件 #{case_id} 的临时移出仍在初步复核窗口内。\n"
                f"- 初步复核约剩余：{self._format_remaining_time(initial_review_due_at)}"
            )
            return

        if formal_bridge_due_at and now >= formal_bridge_due_at:
            formal_case_id = self._ensure_formal_discipline_bridge_case(case=case)
            self.storage.resolve_case_status(
                case_id=case_id,
                status="approved",
                phase="closed",
                resolved_at=now.isoformat(),
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "escalated_case_ref": formal_case_id,
                            "bridge_created_at": now.isoformat(),
                            "closed_at": now.isoformat(),
                            "closure_report_ref": f"emergency_case:{case_id}:escalated",
                        },
                    )
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 的紧急措施已累计超过 48 小时，已自动转入正式处分程序：案件 #{formal_case_id}。\n"
                "紧急阶段形成的事实摘要、日志引用和临时措施时长已一并带入。"
            )
            return

        if initial_review_due_at and not payload.get("objective_reason_published_at"):
            off_group_statement_channel = str(
                payload.get("off_group_statement_channel") or self._default_off_group_statement_channel()
            )
            objective_reason = self._build_emergency_objective_reason(case)
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "off_group_statement_channel": off_group_statement_channel,
                            "objective_reason_if_any": objective_reason,
                            "objective_reason_published_at": now.isoformat(),
                            "extension_granted_at": now.isoformat(),
                            "extension_basis": "临时移出群聊超过 24 小时未完成初步复核，先公告客观原因并保留站外陈述渠道。",
                            "expires_at": formal_bridge_due_at.isoformat() if formal_bridge_due_at else "",
                        },
                    ),
                    "phase": "extended_once",
                },
            )
            remaining = self._format_remaining_time(formal_bridge_due_at) if formal_bridge_due_at else "未知"
            await self.group.send_msg(
                f"案件 #{case_id} 已超过 24 小时初步复核节点。\n"
                f"- 客观原因公告：{objective_reason}\n"
                f"- 站外陈述渠道：{off_group_statement_channel}\n"
                f"- 如仍需维持措施，须在 {remaining} 内转入正式处分程序。"
            )
            return

        if formal_bridge_due_at:
            await self.group.send_msg(
                f"案件 #{case_id} 已公告客观原因并保留站外陈述渠道。\n"
                f"- 转正式处分约剩余：{self._format_remaining_time(formal_bridge_due_at)}"
            )
            return

        await self.group.send_msg("该紧急防护案件仍在处理中。")

    async def _advance_formal_discipline_case(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        now = datetime.now()
        phase = str(case.get("phase") or "")
        current_sanction = self._formal_discipline_current_sanction(case)
        sanction_label = self._formal_sanction_label(current_sanction)

        if phase == "acceptance_review":
            acceptance_due_at = self._case_payload_datetime(case, "acceptance_due_at")
            can_accept_early = self._can_manually_accept_formal_discipline(event.user_id)
            if acceptance_due_at and now < acceptance_due_at and not can_accept_early:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在受理审查期，约剩余 {self._format_remaining_time(acceptance_due_at)}。\n"
                    "当前仅元老会成员或荣誉群主可提前确认受理；逾期将自动视为受理。"
                )
                return
            accepted_marker = (
                f"manual_accept:{event.user_id}" if can_accept_early and (not acceptance_due_at or now < acceptance_due_at) else "timeout_deemed_accepted"
            )
            timeout_patch: Dict[str, object] = {}
            if accepted_marker == "timeout_deemed_accepted" and acceptance_due_at is not None:
                timeout_ready, timeout_patch, timeout_message = await self._resolve_timeout_fallback_transition(
                    case=case,
                    event=event,
                    request_kind="formal_discipline_acceptance_review",
                    due_at=acceptance_due_at,
                    fallback_stage="accepted",
                )
                if not timeout_ready:
                    await self.group.send_msg(timeout_message)
                    return
                self._record_elder_council_timeout(
                    case_id=case_id,
                    actor_id=int(case["proposer_id"]),
                    request_kind="formal_discipline_acceptance_review",
                    due_at=acceptance_due_at,
                    fallback_stage="accepted",
                    acting_stage=str(timeout_patch.get("timeout_fallback_actor_stage") or ""),
                )
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "accepted",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "accepted_at": now.isoformat(),
                            "accepted_by_or_timeout_marker": accepted_marker,
                            **timeout_patch,
                        },
                    ),
                },
            )
            lines = [
                f"案件 #{case_id} 已完成受理，建议处分为：{sanction_label}{self._format_sanction_duration_suffix_from_case(case, current_sanction)}。",
            ]
            if timeout_patch:
                lines.append(
                    f"- 程序失职记录：已按顺位转由{self._timeout_fallback_stage_label(str(timeout_patch.get('timeout_fallback_actor_stage') or ''))}推进。"
                )
            lines.append(f"请继续使用“推进治理案件 {case_id}”发送程序告知。")
            await self.group.send_msg("\n".join(lines))
            return

        if phase == "accepted":
            notice_deadline = self._formal_discipline_notice_deadline(case)
            notice_refs = [f"group_notice:formal_case:{case_id}"]
            off_group_channel = self._formal_discipline_off_group_channel(case)
            if off_group_channel:
                notice_refs.append(f"off_group_channel:{off_group_channel}")
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "notice_in_progress",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "notice_refs": notice_refs,
                            "sent_at": now.isoformat(),
                            "deemed_service_deadline": notice_deadline.isoformat(),
                        },
                    ),
                },
            )
            lines = [
                f"案件 #{case_id} 已发送正式处分程序告知。",
                f"- 建议处分：{sanction_label}{self._format_sanction_duration_suffix_from_case(case, current_sanction)}",
                f"- 视为送达时间：{notice_deadline.strftime('%Y-%m-%d %H:%M')}",
            ]
            if off_group_channel:
                lines.append(f"- 站外陈述渠道：{off_group_channel}")
            lines.append(f"- 届时请使用“推进治理案件 {case_id}”进入申辩期。")
            await self.group.send_msg("\n".join(lines))
            return

        if phase == "notice_in_progress":
            deemed_service_deadline = self._case_payload_datetime(case, "deemed_service_deadline")
            if deemed_service_deadline and now < deemed_service_deadline:
                await self.group.send_msg(
                    f"案件 #{case_id} 的程序告知仍在送达等待中，约剩余 {self._format_remaining_time(deemed_service_deadline)}。"
                )
                return
            defense_hours = self._formal_discipline_defense_hours(current_sanction)
            defense_closes_at = now + timedelta(hours=defense_hours)
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "defense_window",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "deemed_served_at": now.isoformat(),
                            "defense_opened_at": now.isoformat(),
                            "defense_closes_at": defense_closes_at.isoformat(),
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已视为送达，进入申辩期。\n"
                f"- 申辩最短期限：{defense_hours} 小时\n"
                f"- 截止时间：{defense_closes_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- 期满后请使用“推进治理案件 {case_id}”进入证据审查。"
            )
            return

        if phase == "defense_window":
            defense_closes_at = self._case_payload_datetime(case, "defense_closes_at")
            if defense_closes_at and now < defense_closes_at:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在申辩期，约剩余 {self._format_remaining_time(defense_closes_at)}。"
                )
                return
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "evidence_review",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "defense_elapsed_at_or_waived_at": now.isoformat(),
                            "defense_summary_ref_if_any": f"formal_case:{case_id}:defense_summary",
                            "evidence_matrix_ref": f"formal_case:{case_id}:evidence_matrix",
                            "summary_ref": f"formal_case:{case_id}:evidence_summary",
                            "proposed_sanction": current_sanction,
                        },
                    ),
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 申辩期已结束，进入证据审查。\n"
                f"- 当前建议处分：{sanction_label}{self._format_sanction_duration_suffix_from_case(case, current_sanction)}\n"
                f"- 请使用“推进治理案件 {case_id}”启动匿名表决。"
            )
            return

        if phase == "evidence_review":
            vote_duration_seconds = int(case.get("vote_duration_seconds") or 0) or self._config_int(
                "governance_vote_duration_seconds",
                300,
            )
            vote_opened_at = now
            vote_closes_at = vote_opened_at + timedelta(seconds=vote_duration_seconds)
            reviewer_ids = self._merge_reviewer_ids(case, event.user_id)
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "summary_ref": f"formal_case:{case_id}:evidence_summary",
                            "reviewer_ids": reviewer_ids,
                            "roster_snapshot_id": f"formal_case:{case_id}:roster_snapshot",
                            "vote_id": f"formal_case:{case_id}:vote",
                            "vote_opened_at": vote_opened_at.isoformat(),
                            "vote_closes_at": vote_closes_at.isoformat(),
                            "threshold_set": self._formal_discipline_threshold_ref(current_sanction),
                            "current_sanction": current_sanction,
                            "evidence_review_completed_at": now.isoformat(),
                        },
                    )
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 证据审查已完成，当前提交表决的处分为：{sanction_label}{self._format_sanction_duration_suffix_from_case(case, current_sanction)}。"
            )
            await self._start_case_vote(case_id=case_id, event=event)
            return

        if case["status"] == "voting":
            await self.group.send_msg(f"案件 #{case_id} 已处于正式处分表决阶段，请等待投票结束。")
            return
        if phase == "approved":
            await self._retry_formal_discipline_execution(case=case)
            return
        await self.group.send_msg(f"案件 #{case_id} 当前阶段为 {self._format_case_stage(case)}，无需推进。")

    async def _advance_formal_discipline_review_case(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
    ) -> None:
        case_id = int(case["case_id"])
        phase = str(case.get("phase") or "")
        payload = case.get("payload") or {}
        source_case_id = self._case_payload_int(case, "source_case_id")
        source_case = self.storage.get_case(source_case_id) if source_case_id > 0 else None
        now = datetime.now()

        if case["status"] == "supporting":
            supporters = self.storage.count_case_supporters(case_id)
            await self.group.send_msg(
                f"案件 #{case_id} 仍在复核联署阶段，当前联署：{supporters}/{case['support_threshold']}。"
            )
            return

        if phase == "review_start_check":
            start_check_due_at = self._case_payload_datetime(case, "start_check_due_at")
            can_decide_early = self._can_manually_accept_formal_discipline(event.user_id)
            if start_check_due_at and now < start_check_due_at and not can_decide_early:
                await self.group.send_msg(
                    f"案件 #{case_id} 仍在复核启动审查期，约剩余 {self._format_remaining_time(start_check_due_at)}。\n"
                    "当前仅元老会成员或荣誉群主可提前作出启动/驳回决定；逾期将按法定理由自动处理。"
                )
                return
            timed_out = bool(start_check_due_at and now >= start_check_due_at)
            review_decision = self._evaluate_formal_review_request(case=case, source_case=source_case)
            timeout_patch: Dict[str, object] = {}
            if timed_out and start_check_due_at is not None:
                timeout_ready, timeout_patch, timeout_message = await self._resolve_timeout_fallback_transition(
                    case=case,
                    event=event,
                    request_kind="formal_discipline_review_start_check",
                    due_at=start_check_due_at,
                    fallback_stage="reopened" if review_decision["valid"] else "denied",
                )
                if not timeout_ready:
                    await self.group.send_msg(timeout_message)
                    return
            if not review_decision["valid"]:
                if timed_out and start_check_due_at is not None:
                    self._record_elder_council_timeout(
                        case_id=case_id,
                        actor_id=int(case["proposer_id"]),
                        request_kind="formal_discipline_review_start_check",
                        due_at=start_check_due_at,
                        fallback_stage="denied",
                        acting_stage=str(timeout_patch.get("timeout_fallback_actor_stage") or ""),
                    )
                self.storage.update_case_fields(
                    case_id,
                    {
                        "status": "rejected",
                        "phase": "denied",
                        "resolved_at": now.isoformat(),
                        "payload_json": self._merge_case_payload(
                            case,
                            {
                                "denied_at": now.isoformat(),
                                "denial_reason": str(review_decision["denial_reason"]),
                                **timeout_patch,
                            },
                        ),
                    },
                )
                lines = [
                    f"案件 #{case_id} 的处分复核申请未获启动。",
                    f"- 驳回原因：{review_decision['denial_reason']}",
                ]
                if timeout_patch:
                    lines.append(
                        f"- 程序失职记录：已按顺位转由{self._timeout_fallback_stage_label(str(timeout_patch.get('timeout_fallback_actor_stage') or ''))}作出处理。"
                    )
                lines.append(f"- 如需结束该复核案，请使用“推进治理案件 {case_id}”。")
                await self.group.send_msg("\n".join(lines))
                return
            if timed_out and start_check_due_at is not None:
                self._record_elder_council_timeout(
                    case_id=case_id,
                    actor_id=int(case["proposer_id"]),
                    request_kind="formal_discipline_review_start_check",
                    due_at=start_check_due_at,
                    fallback_stage="reopened",
                    acting_stage=str(timeout_patch.get("timeout_fallback_actor_stage") or ""),
                )
            pause_execution = False
            pause_lines: List[str] = []
            if source_case:
                pause_execution, pause_lines = await self._pause_formal_discipline_execution_for_review(
                    source_case=source_case,
                    review_case=case,
                )
            self.storage.update_case_fields(
                case_id,
                {
                    "phase": "reopened",
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "reopened_at": now.isoformat(),
                            "pause_execution": pause_execution,
                            "pause_execution_lines": pause_lines,
                            **timeout_patch,
                        },
                    ),
                },
            )
            lines = [
                f"案件 #{case_id} 已启动处分复核。",
                f"- 原处分案件：#{source_case_id}" if source_case_id else "- 原处分案件：-",
            ]
            if timeout_patch:
                lines.append(
                    f"- 程序失职记录：已按顺位转由{self._timeout_fallback_stage_label(str(timeout_patch.get('timeout_fallback_actor_stage') or ''))}推进。"
                )
            if pause_lines:
                lines.extend(f"- {line}" for line in pause_lines)
            else:
                lines.append("- 原处分执行状态：本轮未作暂停调整。")
            lines.append(f"- 请继续使用“推进治理案件 {case_id}”重开新的正式处分审查流程。")
            await self.group.send_msg("\n".join(lines))
            return

        if phase == "reopened":
            if not source_case:
                await self.group.send_msg("原正式处分案件不存在，无法继续创建复核重开案件。")
                return
            new_case_id = self._create_reopened_formal_discipline_case(source_case=source_case, review_case=case)
            self.storage.resolve_case_status(case_id=case_id, status="approved", phase="closed", resolved_at=now.isoformat())
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "new_case_ref": new_case_id,
                            "published_at": now.isoformat(),
                            "closed_at": now.isoformat(),
                            "public_summary_ref": f"formal_review:{case_id}:public_summary",
                        },
                    )
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 已重开新的正式处分流程：案件 #{new_case_id}。\n"
                f"- 新案件已直接进入待送达阶段，请使用“推进治理案件 {new_case_id}”继续处理。"
            )
            return

        if phase == "denied":
            self.storage.resolve_case_status(case_id=case_id, status="rejected", phase="closed", resolved_at=now.isoformat())
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "published_at": now.isoformat(),
                            "closed_at": now.isoformat(),
                            "public_summary_ref": f"formal_review:{case_id}:public_summary",
                        },
                    )
                },
            )
            await self.group.send_msg(
                f"案件 #{case_id} 的复核驳回结果已发布，复核案关闭。"
            )
            return

        await self.group.send_msg(f"案件 #{case_id} 当前阶段为 {self._format_case_stage(case)}，无需推进。")

    async def _retry_formal_discipline_execution(self, *, case: Dict[str, object]) -> None:
        case_id = int(case["case_id"])
        success, lines = await self._execute_formal_discipline_case(case=case)
        header = f"正式处分案件 #{case_id} 执行重试结果："
        await self.group.send_msg("\n".join([header] + [f"- {line}" for line in lines]))
        if not success:
            return

    async def _finalize_formal_discipline_vote(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        tallies: Dict[int, int],
        voter_count: int,
    ) -> str:
        current_sanction = self._formal_discipline_current_sanction(case)
        sanction_label = self._formal_sanction_label(current_sanction)
        yes_votes = int(tallies.get(1, 0))
        no_votes = int(tallies.get(2, 0))
        member_count = max(self.storage.member_count(), voter_count)
        approved, threshold_lines = self._evaluate_threshold_ref_vote_result(
            threshold_ref=self._formal_discipline_threshold_ref(current_sanction),
            yes_votes=yes_votes,
            no_votes=no_votes,
            member_count=member_count,
            turnout=voter_count,
        )
        lines = [
            f"治理案件 #{case_id}（正式处分）投票结束。",
            f"- 当前表决处分：{sanction_label}{self._format_sanction_duration_suffix_from_case(case, current_sanction)}",
            f"- 赞成：{yes_votes} 票",
            f"- 反对：{no_votes} 票",
            f"- 参与投票：{voter_count} 人",
        ]
        lines.extend(f"- {line}" for line in threshold_lines)
        now = datetime.now()
        tally_payload = {"approve": yes_votes, "reject": no_votes, "turnout": voter_count}

        if approved:
            decision_patch = self._build_formal_discipline_vote_resolution_patch(
                case=case,
                sanction_type=current_sanction,
                tally_payload=tally_payload,
                closed_at=now,
            )
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "approved",
                    "phase": "approved",
                    "resolved_at": now.isoformat(),
                    "payload_json": self._merge_case_payload(case, decision_patch),
                },
            )
            latest_case = self.storage.get_case(case_id) or case
            success, execution_lines = await self._execute_formal_discipline_case(case=latest_case)
            lines.append("- 表决结果：通过")
            lines.extend(f"- {line}" for line in execution_lines)
            if not success:
                lines.append(f"- 请在排除执行失败原因后，使用“推进治理案件 {case_id}”重试执行。")
            return "\n".join(lines)

        next_sanction = self._next_formal_discipline_sanction(current_sanction)
        if next_sanction:
            self.storage.delete_case_votes(case_id)
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "active",
                    "phase": "evidence_review",
                    "vote_started_at": None,
                    "vote_ends_at": None,
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "current_sanction": next_sanction,
                            "previous_vote_tally": tally_payload,
                            "fallback_from_sanction": current_sanction,
                            "fallback_started_at": now.isoformat(),
                        },
                    ),
                },
            )
            lines.append("- 表决结果：当前处分未通过")
            lines.append(
                f"- 已按较轻处分转入下一轮审查建议：{self._formal_sanction_label(next_sanction)}"
                f"{self._format_sanction_duration_suffix_from_case(case, next_sanction)}"
            )
            lines.append(f"- 请使用“推进治理案件 {case_id}”启动下一轮匿名表决。")
            return "\n".join(lines)

        rejection_patch = self._build_formal_discipline_rejection_patch(case=case, tally_payload=tally_payload, closed_at=now)
        self.storage.resolve_case_status(case_id=case_id, status="rejected", phase="closed", resolved_at=now.isoformat())
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(case, rejection_patch),
            },
        )
        lines.append("- 表决结果：未通过，当前正式处分案件已结束。")
        return "\n".join(lines)

    async def _finalize_honor_owner_election_vote(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        tallies: Dict[int, int],
        voter_count: int,
    ) -> str:
        candidate_ids = self._case_ballot_candidate_ids(case)
        member_count = max(self.storage.member_count(), voter_count)
        lines = [f"治理案件 #{case_id}（荣誉群主选举）投票结束。", f"- 参与投票：{voter_count} 人"]

        if case["status"] == "runoff_voting":
            turnout_ok, turnout_lines, threshold_spec = self._evaluate_turnout_requirement(
                threshold_ref="honor_owner_election_runoff",
                member_count=member_count,
                turnout=voter_count,
            )
            lines.extend(f"- {line}" for line in turnout_lines)
            candidate_vote_items = self._candidate_vote_items(candidate_ids, tallies)
            lines.extend(self._format_candidate_tally_lines(candidate_vote_items))
            if not turnout_ok:
                lines.extend(
                    await self._reject_honor_owner_election_case(
                        case_id=case_id,
                        case=case,
                        reason="复选未达到投票人数门槛，已结束本次选举。",
                    )
                )
                return "\n".join(lines)

            top_votes = max((votes for _, votes in candidate_vote_items), default=0)
            top_candidates = [candidate_id for candidate_id, votes in candidate_vote_items if votes == top_votes]
            winner_floor = self._ceil_ratio(
                voter_count,
                ((threshold_spec.get("approval") or {}).get("winner_min_of_turnout")),
            )
            lines.append(f"- 通过条件：得票最高，且不少于 {winner_floor} 票")
            if len(top_candidates) == 1 and top_votes >= winner_floor:
                lines.extend(
                    await self._approve_honor_owner_election_case(
                        case_id=case_id,
                        case=case,
                        winner_member_id=top_candidates[0],
                    )
                )
                return "\n".join(lines)

            lines.extend(
                await self._reject_honor_owner_election_case(
                    case_id=case_id,
                    case=case,
                    reason="复选仍未产生唯一且过半的新任荣誉群主，已转回重新提名。",
                )
            )
            return "\n".join(lines)

        if len(candidate_ids) <= 1:
            yes_votes = int(tallies.get(1, 0))
            no_votes = int(tallies.get(2, 0))
            approved, threshold_lines = self._evaluate_vote_result(
                case_type="honor_owner_election",
                yes_votes=yes_votes,
                no_votes=no_votes,
                member_count=member_count,
                turnout=voter_count,
            )
            lines.append(f"- 赞成：{yes_votes} 票")
            lines.append(f"- 反对：{no_votes} 票")
            lines.extend(f"- {line}" for line in threshold_lines)
            if approved and candidate_ids:
                lines.extend(
                    await self._approve_honor_owner_election_case(
                        case_id=case_id,
                        case=case,
                        winner_member_id=candidate_ids[0],
                    )
                )
                return "\n".join(lines)
            lines.extend(
                await self._reject_honor_owner_election_case(
                    case_id=case_id,
                    case=case,
                    reason="单候选人未达到当选门槛，已转回重新提名。",
                )
            )
            return "\n".join(lines)

        turnout_ok, turnout_lines, _ = self._evaluate_turnout_requirement(
            threshold_ref="honor_owner_election_single_candidate",
            member_count=member_count,
            turnout=voter_count,
        )
        lines.extend(f"- {line}" for line in turnout_lines)
        candidate_vote_items = self._candidate_vote_items(candidate_ids, tallies)
        lines.extend(self._format_candidate_tally_lines(candidate_vote_items))
        if not turnout_ok:
            lines.extend(
                await self._reject_honor_owner_election_case(
                    case_id=case_id,
                    case=case,
                    reason="首轮未达到投票人数门槛，已转回重新提名。",
                )
            )
            return "\n".join(lines)

        top_votes = max((votes for _, votes in candidate_vote_items), default=0)
        top_candidates = [candidate_id for candidate_id, votes in candidate_vote_items if votes == top_votes]
        if len(top_candidates) == 1 and top_votes * 2 > voter_count:
            lines.append("- 首轮结果：已有候选人获得超过半数投票支持")
            lines.extend(
                await self._approve_honor_owner_election_case(
                    case_id=case_id,
                    case=case,
                    winner_member_id=top_candidates[0],
                )
            )
            return "\n".join(lines)

        runoff_candidate_ids = self._select_honor_owner_runoff_candidates(candidate_vote_items)
        self.storage.delete_case_votes(case_id)
        self.storage.update_case_fields(
            case_id,
            {
                "status": "runoff_voting",
                "phase": "runoff_voting",
                "vote_started_at": None,
                "vote_ends_at": None,
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "first_round_tally": self._serialize_candidate_tallies(candidate_vote_items),
                        "first_round_voter_count": voter_count,
                        "runoff_candidate_member_ids": runoff_candidate_ids,
                        "runoff_round": self._case_payload_int(case, "runoff_round") + 1,
                    },
                ),
            },
        )
        lines.append(
            "- 首轮结果：暂无候选人获得超过半数投票支持，已进入复选候选："
            + self._format_user_list(runoff_candidate_ids)
        )
        lines.append(f"- 请使用“推进治理案件 {case_id}”启动第二轮表决")
        return "\n".join(lines)

    async def _finalize_elder_election_vote(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        tallies: Dict[int, int],
        voter_count: int,
    ) -> str:
        candidate_ids = self._case_ballot_candidate_ids(case)
        seat_count = self._elder_case_current_round_seat_count(case)
        member_count = max(self.storage.member_count(), voter_count)
        lines = [
            f"治理案件 #{case_id}（元老选举）投票结束。",
            f"- 参与投票：{voter_count} 人",
            f"- 本轮待定席位：{seat_count} 席",
        ]
        fixed_winner_ids = self._case_member_id_list(case, "fixed_winner_member_ids")

        turnout_ok, turnout_lines, _ = self._evaluate_turnout_requirement(
            threshold_ref="elder_election",
            member_count=member_count,
            turnout=voter_count,
        )
        lines.extend(f"- {line}" for line in turnout_lines)
        candidate_vote_items = self._candidate_vote_items(candidate_ids, tallies)
        lines.extend(self._format_candidate_tally_lines(candidate_vote_items))
        if not turnout_ok:
            if fixed_winner_ids:
                remaining_seats = max(self._elder_case_total_seat_count(case) - len(fixed_winner_ids), 0)
                lines.append("- 本轮加投未达投票门槛，但此前已明确当选席位仍然保留。")
                lines.extend(
                    await self._approve_elder_election_case(
                        case_id=case_id,
                        case=case,
                        winner_member_ids=fixed_winner_ids,
                        remaining_seats=remaining_seats,
                    )
                )
                return "\n".join(lines)
            lines.extend(
                await self._reject_elder_election_case(
                    case_id=case_id,
                    case=case,
                    remaining_seats=self._elder_case_total_seat_count(case),
                    reason="未达到元老选举的投票人数门槛，已重新开启补选提名。",
                )
            )
            return "\n".join(lines)

        round_result = self._resolve_ranked_winners(candidate_vote_items, seat_count)
        if round_result["runoff_candidate_ids"]:
            next_round = self._case_payload_int(case, "runoff_round") + 1
            fixed_winner_ids = list(dict.fromkeys(fixed_winner_ids + round_result["winner_ids"]))
            self.storage.delete_case_votes(case_id)
            self.storage.update_case_fields(
                case_id,
                {
                    "status": "runoff_voting",
                    "phase": "runoff_voting",
                    "vote_started_at": None,
                    "vote_ends_at": None,
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "fixed_winner_member_ids": fixed_winner_ids,
                            "runoff_candidate_member_ids": round_result["runoff_candidate_ids"],
                            "runoff_seat_count": round_result["runoff_seat_count"],
                            "runoff_round": next_round,
                            "latest_round_tally": self._serialize_candidate_tallies(candidate_vote_items),
                        },
                    ),
                },
            )
            if fixed_winner_ids:
                lines.append("- 本轮已明确当选：" + self._format_user_list(fixed_winner_ids))
            lines.append(
                "- 末位同票影响席位归属，需对以下候选人加投："
                + self._format_user_list(round_result["runoff_candidate_ids"])
            )
            lines.append(f"- 请使用“推进治理案件 {case_id}”启动下一轮加投")
            return "\n".join(lines)

        winner_ids = list(dict.fromkeys(fixed_winner_ids + round_result["winner_ids"]))
        remaining_seats = max(self._elder_case_total_seat_count(case) - len(winner_ids), 0)
        lines.extend(
            await self._approve_elder_election_case(
                case_id=case_id,
                case=case,
                winner_member_ids=winner_ids,
                remaining_seats=remaining_seats,
            )
        )
        return "\n".join(lines)

    async def _approve_honor_owner_election_case(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        winner_member_id: int,
    ) -> List[str]:
        resolved_at = datetime.now()
        term_expires_at = resolved_at + timedelta(days=self._honor_owner_term_days())
        summary = await self._set_honor_owner(
            target_user_id=winner_member_id,
            operator_id=int(case["proposer_id"]),
            source=f"case:{case_id}",
            sync_platform_admin=True,
        )
        self.storage.resolve_case_status(case_id=case_id, status="approved", phase="closed", resolved_at=resolved_at.isoformat())
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "winner_member_id": winner_member_id,
                        "term_days": self._honor_owner_term_days(),
                        "term_started_at": resolved_at.isoformat(),
                        "term_expires_at": term_expires_at.isoformat(),
                    },
                )
            },
        )
        lines = [
            "表决结果：通过",
            f"执行结果：已任命 {summary['display_name']} 为荣誉群主",
            f"任期记录：自即日起 {self._honor_owner_term_days()} 日（至 {term_expires_at.strftime('%Y-%m-%d %H:%M')}）",
        ]
        if summary.get("revoked_elder"):
            lines.append("职务分离：已同步解除其元老身份")
        return lines

    async def _reject_honor_owner_election_case(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        reason: str,
    ) -> List[str]:
        resolved_at = datetime.now()
        failure_count = self._case_payload_int(case, "consecutive_failed_by_election_rounds")
        if not self.storage.get_active_role_user("honor_owner"):
            failure_count += 1
        self.storage.resolve_case_status(case_id=case_id, status="rejected", phase="closed", resolved_at=resolved_at.isoformat())
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "rejection_reason": reason,
                        "consecutive_failed_by_election_rounds": failure_count,
                    },
                )
            },
        )
        lines = ["表决结果：未通过", reason]
        if not self.storage.get_active_role_user("honor_owner"):
            by_election_case_id = self._ensure_honor_owner_by_election_case(
                operator_id=int(case["proposer_id"]),
                source_case_id=case_id,
                reopen_reason=reason,
                ignore_case_id=case_id,
                failure_count=failure_count,
            )
            lines.append(f"已自动重新开启荣誉群主补选提名：案件 #{by_election_case_id}")
            if failure_count >= 2:
                lines.append(
                    f"后续处理：已进入机器人临时自治，范围仅限日常秩序与紧急安全，并将在 {self._honor_owner_temporary_autonomy_restart_hours()} 小时窗口内继续补选。"
                )
        else:
            lines.append("后续处理：可重新提名后再次发起。")
        return lines

    async def _approve_elder_election_case(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        winner_member_ids: List[int],
        remaining_seats: int,
    ) -> List[str]:
        lines: List[str] = ["表决结果：通过"]
        resolved_at = datetime.now()
        term_expires_at = resolved_at + timedelta(days=self._elder_term_days())
        term_expires_at_by_member: Dict[str, str] = {}
        for winner_member_id in winner_member_ids:
            await self._ensure_member_profile(winner_member_id)
            term_expires_at_by_member[str(winner_member_id)] = term_expires_at.isoformat()
            self.storage.set_role_status(
                user_id=winner_member_id,
                role_code="elder",
                status="active",
                source=f"case:{case_id}",
                operator_id=int(case["proposer_id"]),
                notes=f"case:{case_id};term_expires_at:{term_expires_at.isoformat()}",
            )
        self.storage.resolve_case_status(case_id=case_id, status="approved", phase="closed", resolved_at=resolved_at.isoformat())
        if winner_member_ids:
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "winner_member_ids": winner_member_ids,
                            "term_days": self._elder_term_days(),
                            "term_started_at": resolved_at.isoformat(),
                            "term_expires_at_by_member": term_expires_at_by_member,
                        },
                    )
                },
            )
        if winner_member_ids:
            lines.append("执行结果：已当选元老：" + self._format_user_list(winner_member_ids))
            lines.append(f"任期记录：自即日起 {self._elder_term_days()} 日")
        else:
            lines.append("执行结果：本轮未产生元老。")
        source_case_id = self._case_payload_int(case, "source_case_id")
        if source_case_id:
            self._mark_reboot_election_started(source_case_id=source_case_id, election_case_id=case_id)
        reboot_source_case_id = self._reboot_source_case_id(case)
        if reboot_source_case_id and winner_member_ids:
            self._mark_reboot_council_restored(
                reboot_case_id=reboot_source_case_id,
                election_case_id=case_id,
                winner_member_ids=winner_member_ids,
            )
        if remaining_seats > 0:
            next_case_id = self._ensure_elder_by_election_case(
                operator_id=int(case["proposer_id"]),
                source_case_id=case_id,
                reopen_reason="本轮元老选举未补满全部席位，自动继续开启补选提名。",
                seat_count=remaining_seats,
                ignore_case_id=case_id,
            )
            lines.append(f"仍有 {remaining_seats} 个席位空缺，已自动继续补选：案件 #{next_case_id}")
        return lines

    async def _reject_elder_election_case(
        self,
        *,
        case_id: int,
        case: Dict[str, object],
        remaining_seats: int,
        reason: str,
    ) -> List[str]:
        self.storage.resolve_case_status(case_id=case_id, status="rejected", phase="closed", resolved_at=datetime.now().isoformat())
        lines = ["表决结果：未通过", reason]
        reboot_source_case_id = self._reboot_source_case_id(case)
        if reboot_source_case_id:
            reboot_status = self._record_reboot_election_failure(
                reboot_case_id=reboot_source_case_id,
                election_case_id=case_id,
                reason=reason,
            )
            if reboot_status["temporary_collective_supervision_active"]:
                lines.append(
                    f"后续处理：新一届元老会选举已连续 {reboot_status['failed_rounds']} 次流产，现由全体表决权成员临时行使监督与复核权，直至补选完成。"
                )
        if remaining_seats > 0:
            next_case_id = self._ensure_elder_by_election_case(
                operator_id=int(case["proposer_id"]),
                source_case_id=case_id,
                reopen_reason=reason,
                seat_count=remaining_seats,
                ignore_case_id=case_id,
            )
            lines.append(f"已自动重新开启元老补选提名：案件 #{next_case_id}")
        return lines

    def _evaluate_turnout_requirement(
        self,
        *,
        threshold_ref: str,
        member_count: int,
        turnout: int,
    ) -> tuple[bool, List[str], Dict[str, object]]:
        threshold_spec = self._get_threshold_spec(threshold_ref)
        turnout_floor = self._ceil_ratio(member_count, threshold_spec.get("turnout_min_of_all_voting_members"))
        lines: List[str] = []
        if turnout_floor > 0:
            lines.append(f"参与门槛：有效投票不少于 {turnout_floor} 人")
        if turnout < turnout_floor:
            lines.append(f"本次有效投票：{turnout} 人，未达到参与门槛")
            return False, lines, threshold_spec
        lines.append(f"本次有效投票：{turnout} 人，已达到参与门槛")
        return True, lines, threshold_spec

    def _get_threshold_spec(self, threshold_ref: str) -> Dict[str, object]:
        threshold_sets = load_law_spec().get("threshold_sets") or {}
        threshold_spec = threshold_sets.get(threshold_ref) if isinstance(threshold_sets, dict) else None
        return threshold_spec if isinstance(threshold_spec, dict) else {}

    def _candidate_vote_items(self, candidate_ids: List[int], tallies: Dict[int, int]) -> List[tuple[int, int]]:
        return sorted(
            [(candidate_id, int(tallies.get(index + 1, 0))) for index, candidate_id in enumerate(candidate_ids)],
            key=lambda item: (-item[1], item[0]),
        )

    def _format_candidate_tally_lines(self, candidate_vote_items: List[tuple[int, int]]) -> List[str]:
        lines: List[str] = []
        for candidate_id, votes in candidate_vote_items:
            lines.append(f"- {self._format_user(candidate_id)}：{votes} 票")
        return lines

    @staticmethod
    def _serialize_candidate_tallies(candidate_vote_items: List[tuple[int, int]]) -> List[Dict[str, int]]:
        return [
            {"member_id": int(candidate_id), "votes": int(votes)}
            for candidate_id, votes in candidate_vote_items
        ]

    @staticmethod
    def _resolve_ranked_winners(
        candidate_vote_items: List[tuple[int, int]],
        seat_count: int,
    ) -> Dict[str, object]:
        positive_items = [(candidate_id, votes) for candidate_id, votes in candidate_vote_items if votes > 0]
        if seat_count <= 0 or not positive_items:
            return {"winner_ids": [], "runoff_candidate_ids": [], "runoff_seat_count": 0}
        if len(positive_items) <= seat_count:
            return {
                "winner_ids": [candidate_id for candidate_id, _ in positive_items],
                "runoff_candidate_ids": [],
                "runoff_seat_count": 0,
            }
        cutoff_votes = positive_items[seat_count - 1][1]
        winner_ids = [candidate_id for candidate_id, votes in positive_items if votes > cutoff_votes]
        tied_candidate_ids = [candidate_id for candidate_id, votes in positive_items if votes == cutoff_votes]
        runoff_seat_count = seat_count - len(winner_ids)
        if len(tied_candidate_ids) <= runoff_seat_count:
            return {
                "winner_ids": winner_ids + tied_candidate_ids,
                "runoff_candidate_ids": [],
                "runoff_seat_count": 0,
            }
        return {
            "winner_ids": winner_ids,
            "runoff_candidate_ids": tied_candidate_ids,
            "runoff_seat_count": runoff_seat_count,
        }

    @staticmethod
    def _select_honor_owner_runoff_candidates(candidate_vote_items: List[tuple[int, int]]) -> List[int]:
        if len(candidate_vote_items) <= 2:
            return [candidate_id for candidate_id, _ in candidate_vote_items]
        cutoff_votes = candidate_vote_items[1][1]
        return [candidate_id for candidate_id, votes in candidate_vote_items if votes >= cutoff_votes]

    async def _record_emergency_ban_measure(
        self,
        *,
        case: Dict[str, object],
        actor_user_id: int,
        duration_minutes: int,
    ) -> None:
        if str((case.get("payload") or {}).get("executed_measure_type") or "").strip():
            return
        now = datetime.now()
        self.storage.update_case_fields(
            int(case["case_id"]),
            {
                "phase": "temporary_measure_active",
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "executed_measure_type": "ban",
                        "measure_applied_by": actor_user_id,
                        "measure_started_at": now.isoformat(),
                        "measure_completed_at": now.isoformat(),
                        "measure_duration_minutes": duration_minutes,
                        "temporary_measure_ends_at": (now + timedelta(minutes=duration_minutes)).isoformat(),
                        "active_measure_refs": [f"ban:{duration_minutes}m"],
                        "total_duration_seconds": duration_minutes * 60,
                    },
                ),
            },
        )

    async def _record_emergency_kick_measure(
        self,
        *,
        case: Dict[str, object],
        actor_user_id: int,
    ) -> None:
        if str((case.get("payload") or {}).get("executed_measure_type") or "").strip():
            return
        now = datetime.now()
        self.storage.update_case_fields(
            int(case["case_id"]),
            {
                "phase": "initial_review_due",
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "executed_measure_type": "kick",
                        "measure_applied_by": actor_user_id,
                        "measure_started_at": now.isoformat(),
                        "measure_completed_at": now.isoformat(),
                        "active_measure_refs": ["kick"],
                        "total_duration_seconds": 0,
                        "off_group_statement_channel": self._default_off_group_statement_channel(),
                    },
                ),
            },
        )

    def _ensure_formal_discipline_bridge_case(self, *, case: Dict[str, object]) -> int:
        target_user_id = int(case.get("target_user_id") or 0)
        existing = self.storage.find_open_case("formal_discipline", target_user_id or None)
        if existing:
            return int(existing["case_id"])
        payload = case.get("payload") or {}
        executed_measure_type = str(payload.get("executed_measure_type") or "").strip()
        requested_sanction = "remove_member" if executed_measure_type == "kick" else "long_mute"
        credit_seconds = self._emergency_measure_credit_seconds(case)
        fact_summary = str(payload.get("reason") or case.get("description") or "紧急防护自动转正式处分")
        now = datetime.now()
        acceptance_due_at = now + timedelta(hours=self._config_int("governance_formal_acceptance_hours", 48))
        return self.storage.create_case(
            case_type="formal_discipline",
            title=f"是否对 {self._format_user(target_user_id)} 作出{self._formal_sanction_label(requested_sanction)}",
            description=f"由紧急防护案件 #{case['case_id']} 自动转入正式处分程序。",
            proposer_id=int(case["proposer_id"]),
            target_user_id=target_user_id or None,
            status="active",
            phase="acceptance_review",
            support_threshold=0,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "source_case_id": int(case["case_id"]),
                "origin": "emergency_bridge",
                "filer_id": int(case["proposer_id"]),
                "target_member_id": target_user_id or None,
                "fact_summary": fact_summary,
                "evidence_refs": [f"emergency_case:{case['case_id']}"],
                "requested_sanction": requested_sanction,
                "temporary_credit_seconds": credit_seconds,
                "executed_measure_type": executed_measure_type,
                "off_group_statement_channel": str(payload.get("off_group_statement_channel") or ""),
                "submitted_at": now.isoformat(),
                "created_at": now.isoformat(),
                "acceptance_due_at": acceptance_due_at.isoformat(),
                "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
                **self._formal_discipline_scope_payload(),
            },
        )

    def _emergency_measure_credit_seconds(self, case: Dict[str, object]) -> int:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return 0
        try:
            if payload.get("executed_measure_type") == "ban":
                return int(payload.get("measure_duration_minutes") or 0) * 60
        except Exception:
            return 0
        measure_started_at = self._parse_datetime(payload.get("measure_started_at"))
        if not measure_started_at:
            return 0
        return max(int((datetime.now() - measure_started_at).total_seconds()), 0)

    def _build_emergency_objective_reason(self, case: Dict[str, object]) -> str:
        target_text = self._format_user(case.get("target_user_id"))
        return (
            f"{target_text} 当前仍因客观安全风险无法立即恢复群内参与，"
            "已保留站外陈述与证据提交渠道，并将在 48 小时上限前转入正式处分程序。"
        )

    @staticmethod
    def _default_off_group_statement_channel() -> str:
        return "机器人私信或平台私聊（需人工保持可达）"

    def ensure_motion_initiation_permission(self, user_id: int, *, action_label: str) -> tuple[bool, str]:
        self._release_expired_formal_discipline_locks()
        lock = self.storage.get_active_lock(
            lock_type="daily_management_motion_restriction",
            target_user_id=user_id,
        )
        if not lock:
            return True, ""
        payload = lock.get("payload") or {}
        expires_at = self._parse_datetime((payload or {}).get("expires_at"))
        reason = str(lock.get("reason") or "").strip()
        if expires_at and datetime.now() < expires_at:
            message = (
                f"当前处于日常管理的提案/动议限制期间，约剩余 {self._format_remaining_time(expires_at)}，"
                f"不能{action_label}。"
            )
        else:
            message = f"当前处于日常管理的提案/动议限制期间，不能{action_label}。"
        if reason:
            message += f" 原因：{reason}"
        return False, message

    def _recent_daily_management_actions(self, target_user_id: int, *, limit: int = 3) -> List[Dict[str, object]]:
        rows = self.storage.fetchall(
            """
            SELECT case_id, payload_json, resolved_at
            FROM governance_cases
            WHERE case_type = 'daily_management' AND target_user_id = ?
            ORDER BY case_id DESC
            LIMIT ?
        """,
            (target_user_id, limit),
        )
        actions: List[Dict[str, object]] = []
        for row in rows:
            payload = row.get("payload") or {}
            action_type = str(payload.get("action_type") or "").strip()
            actions.append(
                {
                    "case_id": int(row.get("case_id") or 0),
                    "action_type": action_type,
                    "action_label": self._daily_management_action_label(action_type),
                }
            )
        return actions

    def _release_expired_formal_discipline_locks(self) -> None:
        now = datetime.now()
        for lock in self.storage.list_active_locks():
            lock_type = str(lock.get("lock_type") or "").strip()
            if lock_type not in {*self._FORMAL_RESTRICTION_LOCK_TYPES.values(), "daily_management_motion_restriction"}:
                continue
            payload = lock.get("payload") or {}
            expires_at = self._parse_datetime((payload or {}).get("expires_at"))
            if expires_at and now >= expires_at:
                self.storage.release_lock(str(lock.get("lock_key") or ""))

    @classmethod
    def _formal_sanction_label(cls, sanction_type: str) -> str:
        return cls._FORMAL_SANCTION_LABELS.get(sanction_type, sanction_type or "正式处分")

    @classmethod
    def _format_lock_type(cls, lock_type: str) -> str:
        lock_labels = {
            "honor_owner_powers": "荣誉群主权力冻结",
            "elder_powers": "元老职权冻结",
            "ban_global": "全局禁言冻结",
            "kick_global": "全局放逐冻结",
            "daily_management_motion_restriction": "限制发起提案/动议",
            "formal_discipline_restrict_vote": "限制表决资格",
            "formal_discipline_restrict_candidacy": "限制被选举资格",
        }
        return lock_labels.get(lock_type, lock_type)

    @classmethod
    def _daily_management_action_label(cls, action_type: str) -> str:
        return cls._DAILY_MANAGEMENT_ACTION_LABELS.get(action_type, action_type or "日常管理")

    @staticmethod
    def _daily_management_bridge_hint(action_type: str) -> str:
        if action_type in {"short_mute", "motion_restriction"}:
            return "如仍需长期禁言、移出群聊、限制表决或被选举资格，请改用“发起正式处分 @成员 ...”；如存在现实安全风险，请改用“发起紧急防护 @成员 ...”。"
        return "如需更高强度处置，请改用“发起正式处分 @成员 ...”或在现实安全风险下使用“发起紧急防护 @成员 ...”。"

    def _can_direct_file_formal_discipline(self, user_id: int) -> bool:
        honor_owner_ok, _ = self._ensure_honor_owner_execution_authority(
            user_id,
            action_label="直接发起正式处分",
        )
        if honor_owner_ok:
            return True
        elder_ok, _ = self._ensure_elder_supervision_authority(
            user_id,
            action_label="直接发起正式处分",
        )
        return elder_ok

    def _can_manually_accept_formal_discipline(self, user_id: int) -> bool:
        honor_owner_ok, _ = self._ensure_honor_owner_execution_authority(
            user_id,
            action_label="提前处理正式处分或复核审查",
        )
        if honor_owner_ok:
            return True
        elder_ok, _ = self._ensure_elder_supervision_authority(
            user_id,
            action_label="提前处理正式处分或复核审查",
        )
        return elder_ok

    def _formal_discipline_support_threshold(self) -> int:
        return max(3, self._ceil_ratio(self.storage.member_count(), Fraction(1, 10)))

    def _formal_discipline_scope_summary(self) -> str:
        return "、".join(self._formal_sanction_label(sanction) for sanction in self._FORMAL_DISCIPLINE_SCOPE_SANCTIONS)

    def _formal_discipline_scope_payload(self) -> Dict[str, object]:
        return {
            "formal_scope_sanction_types": list(self._FORMAL_DISCIPLINE_SCOPE_SANCTIONS),
            "formal_scope_summary": self._formal_discipline_scope_summary(),
            "formal_scope_article": "第五十九条",
        }

    def _can_count_as_formal_discipline_filer(self, user_id: int) -> bool:
        self._release_expired_formal_discipline_locks()
        return not self.storage.has_role(user_id, "suspended") and not self.storage.has_active_lock(
            lock_type="formal_discipline_restrict_vote",
            target_user_id=user_id,
        )

    def _ensure_formal_discipline_supporter(self, user_id: int) -> tuple[bool, str]:
        if self.storage.has_role(user_id, "suspended"):
            return False, "当前处于治理禁权状态，不能联署正式处分案件。"
        self._release_expired_formal_discipline_locks()
        if self.storage.has_active_lock(lock_type="formal_discipline_restrict_vote", target_user_id=user_id):
            return False, "当前处于正式处分限制表决资格期间，不能联署正式处分案件。"
        return True, ""

    def _ensure_formal_review_supporter(self, user_id: int) -> tuple[bool, str]:
        if self.storage.has_role(user_id, "suspended"):
            return False, "当前处于治理禁权状态，不能联署处分复核案件。"
        self._release_expired_formal_discipline_locks()
        if self.storage.has_active_lock(lock_type="formal_discipline_restrict_vote", target_user_id=user_id):
            return False, "当前处于正式处分限制表决资格期间，不能联署处分复核案件。"
        return True, ""

    async def _ensure_governance_vote_participant(self, user_id: int) -> tuple[bool, str]:
        if not await self._ensure_governance_participant(user_id):
            return False, "当前处于治理禁权状态，不能参与该表决。"
        self._release_expired_formal_discipline_locks()
        if self.storage.has_active_lock(lock_type="formal_discipline_restrict_vote", target_user_id=user_id):
            return False, "当前处于正式处分限制表决资格期间，不能参与该表决。"
        return True, ""

    def _ensure_candidate_governance_eligibility(self, user_id: int) -> tuple[bool, str]:
        self._release_expired_formal_discipline_locks()
        if self.storage.has_active_lock(lock_type="formal_discipline_restrict_vote", target_user_id=user_id):
            return False, "该成员当前处于正式处分限制表决资格期间，不能被提名。"
        if self.storage.has_active_lock(lock_type="formal_discipline_restrict_candidacy", target_user_id=user_id):
            return False, "该成员当前处于正式处分限制被选举资格期间，不能被提名。"
        if self.storage.has_role(user_id, "suspended"):
            return False, "该成员当前处于治理禁权状态，不能被提名。"
        return True, ""

    def _ensure_honor_owner_candidate_eligibility(self, user_id: int) -> tuple[bool, str]:
        candidate_ok, candidate_reason = self._ensure_candidate_governance_eligibility(user_id)
        if not candidate_ok:
            return False, candidate_reason
        if self.storage.get_active_role_user("honor_owner") == user_id:
            return False, "该成员当前已经是荣誉群主，无需再次提名。"
        if self.storage.has_active_lock(lock_type="elder_powers", target_user_id=user_id) or self.storage.has_active_lock(
            lock_type="honor_owner_powers",
            target_user_id=user_id,
        ):
            return False, "该成员当前处于弹劾冻结状态，不能被提名为荣誉群主。"
        joined_at = self._member_joined_at(user_id)
        if joined_at is None:
            return False, "暂无法确认该成员入群时长，请先执行“同步治理成员”后再提名。"
        if datetime.now() - joined_at < timedelta(days=self._honor_owner_candidate_min_join_days()):
            return False, f"该成员入群未满 {self._honor_owner_candidate_min_join_days()} 日，当前不能成为荣誉群主候选人。"
        return True, ""

    def _ensure_elder_candidate_eligibility(self, user_id: int) -> tuple[bool, str]:
        candidate_ok, candidate_reason = self._ensure_candidate_governance_eligibility(user_id)
        if not candidate_ok:
            return False, candidate_reason
        if self.storage.has_role(user_id, "elder"):
            return False, "该成员当前已经是元老，无需再次提名。"
        if self.storage.get_active_role_user("honor_owner") == user_id:
            return False, "荣誉群主不能同时作为元老候选人。"
        if self.storage.has_active_lock(lock_type="elder_powers", target_user_id=user_id) or self.storage.has_active_lock(
            lock_type="honor_owner_powers",
            target_user_id=user_id,
        ):
            return False, "该成员当前处于弹劾冻结状态，不能被提名为元老。"
        joined_at = self._member_joined_at(user_id)
        if joined_at is None:
            return False, "暂无法确认该成员入群时长，请先执行“同步治理成员”后再提名。"
        if datetime.now() - joined_at < timedelta(days=self._elder_candidate_min_join_days()):
            return False, f"该成员入群未满 {self._elder_candidate_min_join_days()} 日，当前不能成为元老候选人。"
        return True, ""

    def _parse_reason_catalog(
        self,
        *,
        reason_text: str,
        aliases: Dict[str, str],
        labels: Dict[str, str],
        subject_label: str,
    ) -> Dict[str, object]:
        normalized_reason = str(reason_text or "").strip()
        catalog_text = "、".join(dict.fromkeys(labels.values()))
        if not normalized_reason:
            return {
                "error": f"请写明{subject_label}的法定理由。当前支持：{catalog_text}。",
                "reason_text": "",
                "reason_codes": [],
                "reason_summary": "",
            }
        reason_codes: List[str] = []
        for keyword, reason_code in aliases.items():
            if keyword in normalized_reason and reason_code not in reason_codes:
                reason_codes.append(reason_code)
        if not reason_codes:
            return {
                "error": f"{subject_label}理由不在法定范围内。请围绕：{catalog_text}。",
                "reason_text": normalized_reason,
                "reason_codes": [],
                "reason_summary": "",
            }
        reason_labels = [labels.get(reason_code, reason_code) for reason_code in reason_codes]
        return {
            "error": "",
            "reason_text": normalized_reason,
            "reason_codes": reason_codes,
            "reason_summary": "、".join(reason_labels),
        }

    def _parse_honor_owner_impeachment_request(self, reason_text: str) -> Dict[str, object]:
        return self._parse_reason_catalog(
            reason_text=reason_text,
            aliases=self._HONOR_OWNER_IMPEACHMENT_REASON_ALIASES,
            labels=self._HONOR_OWNER_IMPEACHMENT_REASON_LABELS,
            subject_label="荣誉群主弹劾",
        )

    def _parse_elder_impeachment_request(self, reason_text: str) -> Dict[str, object]:
        return self._parse_reason_catalog(
            reason_text=reason_text,
            aliases=self._ELDER_IMPEACHMENT_REASON_ALIASES,
            labels=self._ELDER_IMPEACHMENT_REASON_LABELS,
            subject_label="元老弹劾",
        )

    def _parse_elder_reboot_request(self, reason_text: str) -> Dict[str, object]:
        normalized_reason = str(reason_text or "").strip()
        if not normalized_reason:
            return {
                "error": (
                    "请写明重组元老会的制度性理由和主要事实。法定情形包括："
                    + "；".join(self._ELDER_REBOOT_REASON_LABELS.values())
                    + "。"
                ),
                "reason_text": "",
                "reason_codes": [],
                "reason_summary": "",
                "major_fact_summary": "",
                "forbidden_reason_detected": False,
            }
        reason_codes: List[str] = []
        for keyword, reason_code in self._ELDER_REBOOT_REASON_ALIASES.items():
            if keyword in normalized_reason and reason_code not in reason_codes:
                reason_codes.append(reason_code)
        forbidden_reason_detected = any(keyword in normalized_reason for keyword in self._ELDER_REBOOT_FORBIDDEN_REASON_KEYWORDS)
        if not reason_codes:
            if forbidden_reason_detected:
                return {
                    "error": "重组元老会不得仅以具体裁决不满、政治立场差异或个人恩怨作为理由。",
                    "reason_text": normalized_reason,
                    "reason_codes": [],
                    "reason_summary": "",
                    "major_fact_summary": "",
                    "forbidden_reason_detected": True,
                }
            return {
                "error": (
                    "未识别到法定的制度性理由。请围绕："
                    + "；".join(self._ELDER_REBOOT_REASON_LABELS.values())
                    + "。"
                ),
                "reason_text": normalized_reason,
                "reason_codes": [],
                "reason_summary": "",
                "major_fact_summary": "",
                "forbidden_reason_detected": False,
            }
        reason_labels = [self._ELDER_REBOOT_REASON_LABELS.get(reason_code, reason_code) for reason_code in reason_codes]
        return {
            "error": "",
            "reason_text": normalized_reason,
            "reason_codes": reason_codes,
            "reason_summary": "、".join(reason_labels),
            "major_fact_summary": normalized_reason,
            "forbidden_reason_detected": forbidden_reason_detected,
        }

    def _formal_discipline_current_sanction(self, case: Dict[str, object]) -> str:
        payload = case.get("payload") or {}
        current_sanction = str(payload.get("current_sanction") or payload.get("requested_sanction") or "").strip()
        return current_sanction or "long_mute"

    def _formal_discipline_review_request_deadline(self, source_case: Optional[Dict[str, object]]) -> Optional[datetime]:
        if source_case is None or source_case["case_type"] != "formal_discipline":
            return None
        payload = source_case.get("payload") or {}
        published_at = self._parse_datetime(payload.get("published_at")) or self._parse_datetime(source_case.get("resolved_at"))
        if not published_at:
            return None
        return published_at + timedelta(hours=self._config_int("governance_formal_review_start_hours", 48))

    def _current_law_version_label(self) -> str:
        source_of_truth = (load_law_spec().get("meta") or {}).get("source_of_truth") or {}
        version = str(source_of_truth.get("version") or "").strip()
        if version:
            return version
        title = str((load_law_spec().get("meta") or {}).get("title") or "").strip()
        return title or "未标注版本"

    def _current_law_effective_at(self) -> Optional[datetime]:
        configured = str(self.service.get_config_value("governance_law_effective_at", "") or "").strip()
        if configured:
            parsed = self._parse_datetime(configured)
            if parsed is not None:
                return parsed
        baseline = str((load_law_spec().get("meta") or {}).get("acceptance_baseline_date") or "").strip()
        return self._parse_datetime(baseline)

    def _current_law_effective_at_iso(self) -> str:
        effective_at = self._current_law_effective_at()
        return effective_at.isoformat() if effective_at else ""

    def _format_law_regime_status_lines(self) -> List[str]:
        lines = [f"- 现行法版本：{self._current_law_version_label()}"]
        effective_at = self._current_law_effective_at()
        if effective_at is not None:
            lines.append(f"- 现行法生效：{effective_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("- 附则边界：总则/核心制度修订走宪制修订案；生效前已完成程序原则上不溯及既往")
        return lines

    def _case_completed_at(self, case: Optional[Dict[str, object]]) -> Optional[datetime]:
        if not case:
            return None
        payload = case.get("payload") or {}
        candidates = [case.get("resolved_at")]
        if isinstance(payload, dict):
            candidates.extend(
                [
                    payload.get("published_at"),
                    payload.get("closed_at"),
                    payload.get("effective_at"),
                ]
            )
        for candidate in candidates:
            parsed = self._parse_datetime(candidate)
            if parsed is not None:
                return parsed
        return None

    def _is_pre_effective_completed_case(self, source_case: Optional[Dict[str, object]]) -> bool:
        effective_at = self._current_law_effective_at()
        completed_at = self._case_completed_at(source_case)
        if effective_at is None or completed_at is None:
            return False
        return completed_at < effective_at

    def _legacy_formal_review_exception_basis(
        self,
        *,
        review_request: Dict[str, object],
        legacy_case: bool,
    ) -> str:
        if not legacy_case:
            return ""
        reason_codes = [str(value).strip() for value in (review_request.get("reason_codes") or []) if str(value).strip()]
        if "procedural_error" in reason_codes:
            return "major_procedural_illegality"
        if bool(review_request.get("legacy_safety_risk_requested")):
            return "safety_risk"
        return ""

    def _format_legacy_review_entry_note(self, legacy_exception_basis: str) -> str:
        label = self._LEGACY_REVIEW_EXCEPTION_LABELS.get(legacy_exception_basis, "")
        if not label:
            return ""
        return f"现行法生效前旧程序，按第六十九条例外复核：{label}"

    def _case_law_applicability_note(self, case: Dict[str, object]) -> str:
        if not self._is_pre_effective_completed_case(case):
            return ""
        return "适用：旧规则已完结程序（原则上不溯及既往）"

    @classmethod
    def _proposal_type_label(cls, proposal_type: str) -> str:
        return cls._PROPOSAL_TYPE_LABELS.get(proposal_type, proposal_type or "提案")

    @classmethod
    def _proposal_discussion_hours(cls, proposal_type: str) -> int:
        return int(cls._PROPOSAL_DISCUSSION_HOURS.get(proposal_type, 12))

    @classmethod
    def _proposal_threshold_ref(cls, proposal_type: str) -> str:
        return str(cls._PROPOSAL_THRESHOLD_REFS.get(proposal_type, "ordinary_proposal"))

    def _proposal_vote_duration_seconds(self, proposal_type: str) -> int:
        threshold_ref = self._proposal_threshold_ref(proposal_type)
        threshold_spec = self._get_threshold_spec(threshold_ref)
        raw_value = str((threshold_spec or {}).get("min_vote_period") or "").strip().lower()
        if raw_value.endswith("h") and raw_value[:-1].isdigit():
            return int(raw_value[:-1]) * 3600
        if raw_value.endswith("m") and raw_value[:-1].isdigit():
            return int(raw_value[:-1]) * 60
        return self._config_int("governance_vote_duration_seconds", 300)

    def _proposal_non_retroactivity_note(self) -> str:
        effective_at = self._current_law_effective_at()
        if effective_at is None:
            return "现行法生效后的提案结果按公示时间生效；生效前已完成程序原则上不溯及既往。"
        return (
            "现行法生效后的提案结果按公示时间生效；"
            f"{effective_at.strftime('%Y-%m-%d %H:%M')} 前已完成程序原则上不溯及既往。"
        )

    def _proposal_escalation_support_threshold(self) -> int:
        return max(
            self._PROPOSAL_ESCALATION_FIXED_SUPPORTERS,
            self._ceil_ratio(self._current_voting_member_count(), self._PROPOSAL_ESCALATION_RATIO),
        )

    def _parse_high_risk_flag(self, raw_value: str) -> Optional[bool]:
        normalized = str(raw_value or "").strip().lower()
        if not normalized:
            return None
        if normalized in {value.lower() for value in self._BOOLEAN_TRUE_ALIASES}:
            return True
        if normalized in {value.lower() for value in self._BOOLEAN_FALSE_ALIASES}:
            return False
        return None

    def _validate_temporary_measure_expiry(self, effective_time_or_expiry: str) -> str:
        normalized = str(effective_time_or_expiry or "").strip()
        if not normalized:
            return "临时管理措施必须明确写明期限、失效条件或到期时间。"
        match = re.search(r"(\d+)\s*(d|天|h|小时)", normalized, flags=re.IGNORECASE)
        if not match:
            return "临时管理措施当前需要显式写明不超过 7 日的期限，例如“3天后失效”或“24h”。"
        amount = int(match.group(1))
        unit = str(match.group(2) or "").lower()
        if unit in {"d", "天"} and amount > self._TEMPORARY_MEASURE_MAX_DAYS:
            return "临时管理措施期限不得超过 7 日；超过 7 日的，应转化为普通议题或条例修订。"
        if unit in {"h", "小时"} and amount > self._TEMPORARY_MEASURE_MAX_DAYS * 24:
            return "临时管理措施期限不得超过 7 日；超过 7 日的，应转化为普通议题或条例修订。"
        return ""

    def _parse_proposal_segments(self, raw_text: str, *, require_type: bool) -> Dict[str, object]:
        normalized = str(raw_text or "").strip()
        if not normalized:
            return {
                "error": (
                    "请使用“发起提案 类型 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”。"
                    if require_type
                    else "请使用“补正提案 <案件ID> 标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”。"
                ),
                "proposal_type": "",
                "title": "",
                "purpose_and_reason": "",
                "proposed_text_or_measure": "",
                "effective_time_or_expiry": "",
                "high_risk_power_requested": False,
            }
        proposal_type = ""
        remainder = normalized
        if require_type:
            pieces = normalized.split(None, 1)
            if len(pieces) < 2:
                return {
                    "error": "请先写明提案类型，再按“标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”填写内容。",
                    "proposal_type": "",
                    "title": "",
                    "purpose_and_reason": "",
                    "proposed_text_or_measure": "",
                    "effective_time_or_expiry": "",
                    "high_risk_power_requested": False,
                }
            proposal_type = str(self._PROPOSAL_TYPE_ALIASES.get(pieces[0].strip(), "")).strip()
            if not proposal_type:
                supported = "、".join(
                    [
                        self._proposal_type_label("ordinary_proposal"),
                        self._proposal_type_label("basic_governance_norm"),
                        self._proposal_type_label("constitutional_amendment"),
                        self._proposal_type_label("temporary_measure"),
                        self._proposal_type_label("emergency_motion"),
                    ]
                )
                return {
                    "error": f"未识别的提案类型。当前支持：{supported}。",
                    "proposal_type": "",
                    "title": "",
                    "purpose_and_reason": "",
                    "proposed_text_or_measure": "",
                    "effective_time_or_expiry": "",
                    "high_risk_power_requested": False,
                }
            remainder = pieces[1].strip()
        fields = [segment.strip() for segment in remainder.split("|")]
        if len(fields) != 5 or not all(fields[:4]):
            return {
                "error": "提案内容必须完整填写 5 项：标题 | 目的和理由 | 具体文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力。",
                "proposal_type": proposal_type,
                "title": "",
                "purpose_and_reason": "",
                "proposed_text_or_measure": "",
                "effective_time_or_expiry": "",
                "high_risk_power_requested": False,
            }
        high_risk_flag = self._parse_high_risk_flag(fields[4])
        if high_risk_flag is None:
            return {
                "error": "“是否涉及高风险权力”请填写“是”或“否”。",
                "proposal_type": proposal_type,
                "title": fields[0],
                "purpose_and_reason": fields[1],
                "proposed_text_or_measure": fields[2],
                "effective_time_or_expiry": fields[3],
                "high_risk_power_requested": False,
            }
        if proposal_type == "temporary_measure":
            validation_error = self._validate_temporary_measure_expiry(fields[3])
            if validation_error:
                return {
                    "error": validation_error,
                    "proposal_type": proposal_type,
                    "title": fields[0],
                    "purpose_and_reason": fields[1],
                    "proposed_text_or_measure": fields[2],
                    "effective_time_or_expiry": fields[3],
                    "high_risk_power_requested": bool(high_risk_flag),
                }
        return {
            "error": "",
            "proposal_type": proposal_type,
            "title": fields[0],
            "purpose_and_reason": fields[1],
            "proposed_text_or_measure": fields[2],
            "effective_time_or_expiry": fields[3],
            "high_risk_power_requested": bool(high_risk_flag),
        }

    def _parse_proposal_request(self, raw_text: str) -> Dict[str, object]:
        return self._parse_proposal_segments(raw_text, require_type=True)

    def _parse_vacancy_dispute_request(self, raw_text: str) -> Dict[str, object]:
        request = self._parse_proposal_segments(raw_text, require_type=False)
        if not request["error"]:
            return request
        request["error"] = (
            "请使用“发起职权争议表决 标题 | 争议事实与请求裁决 | 具体裁决文本或措施 | 生效时间/期限/失效条件 | 是否涉及高风险权力”。"
        )
        return request

    def _parse_proposal_correction_request(self, raw_text: str) -> tuple[Optional[int], Dict[str, object]]:
        normalized = str(raw_text or "").strip()
        if not normalized:
            return None, self._parse_proposal_segments("", require_type=False)
        pieces = normalized.split(None, 1)
        if not pieces or not pieces[0].isdigit():
            return None, self._parse_proposal_segments("", require_type=False)
        case_id = int(pieces[0])
        request = self._parse_proposal_segments(pieces[1] if len(pieces) > 1 else "", require_type=False)
        return case_id, request

    @staticmethod
    def _parse_proposal_review_argument(raw_text: str) -> tuple[Optional[int], str, str]:
        normalized = str(raw_text or "").strip()
        if not normalized:
            return None, "", ""
        parts = normalized.split(None, 2)
        if len(parts) < 2 or not parts[0].isdigit():
            return None, "", ""
        action_raw = str(parts[1]).strip()
        detail = str(parts[2]).strip() if len(parts) > 2 else ""
        if action_raw in {"通过", "同意", "pass"}:
            return int(parts[0]), "pass", detail
        if action_raw in {"补正", "修正", "request_correction"}:
            return int(parts[0]), "request_correction", detail
        if action_raw in {"驳回", "拒绝", "reject"}:
            return int(parts[0]), "reject", detail
        return None, "", ""

    async def _move_proposal_to_discussion(
        self,
        *,
        case: Dict[str, object],
        reviewer_id: Optional[int],
        timeout_entry: bool,
        extra_payload: Optional[Dict[str, object]] = None,
    ) -> None:
        case_id = int(case["case_id"])
        payload = case.get("payload") or {}
        proposal_type = str(payload.get("proposal_type") or "ordinary_proposal")
        discussion_hours = self._proposal_discussion_hours(proposal_type)
        now = datetime.now()
        patch = {
            "status": "active",
            "phase": "discussion",
            "payload_json": self._merge_case_payload(
                case,
                {
                    "reviewed_at": now.isoformat(),
                    "reviewer_id": int(reviewer_id) if reviewer_id is not None else 0,
                    "review_timeout_auto_entered": bool(timeout_entry),
                    "discussion_opened_at": now.isoformat(),
                    "discussion_closes_at": (now + timedelta(hours=discussion_hours)).isoformat(),
                    "fallback_actor_id": int(reviewer_id) if reviewer_id is not None else int(self.group.self_id),
                    **(extra_payload or {}),
                },
            ),
        }
        self.storage.update_case_fields(case_id, patch)

    def _build_proposal_decision_summary(
        self,
        *,
        case: Dict[str, object],
        approved: bool,
        tally_payload: Dict[str, int],
        closed_at: datetime,
    ) -> str:
        payload = case.get("payload") or {}
        decision = "通过" if approved else "未通过"
        proposal_type = self._proposal_type_label(str(payload.get("proposal_type") or "ordinary_proposal"))
        effective_note = str(payload.get("effective_time_or_expiry") or "按结果公示执行").strip()
        return (
            f"{proposal_type}《{case.get('title') or '未命名提案'}》已{decision}"
            f"；赞成 {tally_payload['approve']}、反对 {tally_payload['reject']}、弃权 {tally_payload['abstain']}"
            f"；结果公示时间 {closed_at.strftime('%Y-%m-%d %H:%M')}"
            f"；生效/期限说明：{effective_note}"
        )

    def _formal_discipline_reviewable(self, source_case: Dict[str, object], *, legacy_exception_basis: str = "") -> bool:
        if source_case["case_type"] != "formal_discipline":
            return False
        payload = source_case.get("payload") or {}
        review_started_case_id = int(payload.get("review_started_case_id") or 0)
        if review_started_case_id > 0:
            existing_review_case = self.storage.get_case(review_started_case_id)
            if existing_review_case and existing_review_case["status"] in {"supporting", "active"}:
                return False
        legacy_case = self._is_pre_effective_completed_case(source_case)
        if legacy_case and not legacy_exception_basis:
            return False
        review_deadline = self._formal_discipline_review_request_deadline(source_case)
        if review_deadline is None:
            return False
        if datetime.now() <= review_deadline:
            return True
        return legacy_case and bool(legacy_exception_basis)

    @staticmethod
    def _parse_case_id_and_reason(arg: Optional["Message"]) -> tuple[Optional[int], str]:
        try:
            plain_text = str(arg.extract_plain_text() or "").strip() if arg is not None else ""
        except Exception:
            plain_text = str(arg or "").strip()
        if not plain_text:
            return None, ""
        tokens = [token for token in plain_text.split() if token]
        if not tokens or not tokens[0].isdigit():
            return None, plain_text
        reason_text = " ".join(tokens[1:]).strip()
        return int(tokens[0]), reason_text

    def _parse_formal_review_request(self, reason_text: str, *, allow_legacy_safety_only: bool = False) -> Dict[str, object]:
        normalized_reason = str(reason_text or "").strip()
        if not normalized_reason:
            return {
                "error": "请写明复核理由。法定理由包括：新证据、关键程序错误、事实错误、处分明显失衡。",
                "reason_text": "",
                "reason_codes": [],
                "pause_execution_requested": False,
                "legacy_safety_risk_requested": False,
            }
        reason_codes: List[str] = []
        for keyword, reason_code in self._FORMAL_REVIEW_REASON_ALIASES.items():
            if keyword in normalized_reason and reason_code not in reason_codes:
                reason_codes.append(reason_code)
        legacy_safety_risk_requested = any(
            keyword in normalized_reason for keyword in self._LEGACY_REVIEW_SAFETY_RISK_KEYWORDS
        )
        if not reason_codes:
            if allow_legacy_safety_only and legacy_safety_risk_requested:
                return {
                    "error": "",
                    "reason_text": normalized_reason,
                    "reason_codes": [],
                    "pause_execution_requested": False,
                    "legacy_safety_risk_requested": True,
                }
            return {
                "error": "复核理由不在法定范围内。请围绕新证据、关键程序错误、事实错误或处分明显失衡提出。",
                "reason_text": normalized_reason,
                "reason_codes": [],
                "pause_execution_requested": False,
                "legacy_safety_risk_requested": False,
            }
        pause_keywords = ("程序违法", "程序错误", "关键证据失实", "证据失实", "伪造证据", "证据造假")
        return {
            "error": "",
            "reason_text": normalized_reason,
            "reason_codes": reason_codes,
            "pause_execution_requested": any(keyword in normalized_reason for keyword in pause_keywords),
            "legacy_safety_risk_requested": legacy_safety_risk_requested,
        }

    def _evaluate_formal_review_request(
        self,
        *,
        case: Dict[str, object],
        source_case: Optional[Dict[str, object]],
    ) -> Dict[str, object]:
        if source_case is None:
            return {"valid": False, "denial_reason": "原正式处分案件不存在。"}
        payload = case.get("payload") or {}
        reason_codes = [str(value).strip() for value in (payload.get("review_reason_codes") or []) if str(value).strip()]
        legacy_case = self._is_pre_effective_completed_case(source_case)
        legacy_exception_basis = str(payload.get("legacy_exception_basis") or "").strip()
        if not reason_codes and not (legacy_case and legacy_exception_basis == "safety_risk"):
            return {"valid": False, "denial_reason": "复核理由不在法定范围内。"}
        request_deadline = self._formal_discipline_review_request_deadline(source_case)
        if request_deadline is None:
            return {"valid": False, "denial_reason": "原正式处分案件尚未形成可复核的结果公示。"}
        submitted_at = self._parse_datetime(payload.get("submitted_at"))
        if submitted_at is None:
            return {"valid": False, "denial_reason": "复核申请缺少有效提交时间。"}
        if legacy_case and not legacy_exception_basis:
            return {
                "valid": False,
                "denial_reason": "原正式处分案件属于现行规则生效前已完成的旧程序，原则上不溯及既往。",
            }
        if submitted_at > request_deadline:
            if legacy_case and legacy_exception_basis:
                return {"valid": True, "denial_reason": ""}
            return {"valid": False, "denial_reason": "已经超过正式处分结果公示后的 48 小时复核期限。"}
        return {"valid": True, "denial_reason": ""}

    async def _pause_formal_discipline_execution_for_review(
        self,
        *,
        source_case: Dict[str, object],
        review_case: Dict[str, object],
    ) -> tuple[bool, List[str]]:
        payload = source_case.get("payload") or {}
        if not bool((review_case.get("payload") or {}).get("pause_execution_requested")):
            return False, ["复核理由未达到“先行暂停执行”的最小实现条件，原处分继续执行。"]
        sanction_type = str(payload.get("sanction_type") or "").strip()
        execution_ref = str(payload.get("execution_ref") or "").strip()
        if not sanction_type or not execution_ref:
            return False, ["原正式处分当前没有可暂停的已执行记录。"]
        target_user_id = int(source_case.get("target_user_id") or payload.get("target_member_id") or 0)
        if sanction_type == "long_mute":
            expires_at = self._parse_datetime(payload.get("expires_at"))
            if target_user_id <= 0 or (expires_at and datetime.now() >= expires_at):
                return False, ["长期禁言已自然结束或缺少目标成员，未再暂停执行。"]
            await self.group.ban(target_user_id, 0)
            self.storage.update_case_fields(
                int(source_case["case_id"]),
                {
                    "payload_json": self._merge_case_payload(
                        source_case,
                        {
                            "review_paused_at": datetime.now().isoformat(),
                            "review_pause_case_id": int(review_case["case_id"]),
                            "review_pause_result": "muted_execution_paused",
                        },
                    )
                },
            )
            return True, ["已先行暂停原长期禁言执行，等待复核重开。"]
        if sanction_type in {"restrict_vote", "restrict_candidacy"}:
            released_count = 0
            for lock in self.storage.list_active_locks():
                if int(lock.get("source_case_id") or 0) != int(source_case["case_id"]):
                    continue
                lock_type = str(lock.get("lock_type") or "").strip()
                if lock_type not in self._FORMAL_RESTRICTION_LOCK_TYPES.values():
                    continue
                self.storage.release_lock(str(lock.get("lock_key") or ""))
                released_count += 1
            self.storage.update_case_fields(
                int(source_case["case_id"]),
                {
                    "payload_json": self._merge_case_payload(
                        source_case,
                        {
                            "review_paused_at": datetime.now().isoformat(),
                            "review_pause_case_id": int(review_case["case_id"]),
                            "review_pause_result": "restriction_execution_paused",
                        },
                    )
                },
            )
            if released_count > 0:
                return True, ["已先行暂停原资格限制执行，等待复核重开。"]
            return False, ["原资格限制当前没有生效中的锁，未再暂停执行。"]
        if sanction_type == "remove_member":
            self.storage.update_case_fields(
                int(source_case["case_id"]),
                {
                    "payload_json": self._merge_case_payload(
                        source_case,
                        {
                            "review_pause_case_id": int(review_case["case_id"]),
                            "review_pause_result": "manual_restore_required",
                        },
                    )
                },
            )
            return False, ["原处分为移出群聊，当前仓库无法自动恢复入群，只记录为需人工恢复评估。"]
        return False, ["当前仓库未识别可暂停的原处分执行类型。"]

    def _create_reopened_formal_discipline_case(
        self,
        *,
        source_case: Dict[str, object],
        review_case: Dict[str, object],
    ) -> int:
        source_payload = source_case.get("payload") or {}
        review_payload = review_case.get("payload") or {}
        current_sanction = str(source_payload.get("sanction_type") or source_payload.get("requested_sanction") or "").strip()
        if not current_sanction:
            current_sanction = self._formal_discipline_current_sanction(source_case)
        now = datetime.now()
        review_reason_codes = [str(value).strip() for value in (review_payload.get("review_reason_codes") or []) if str(value).strip()]
        reason_labels = [self._FORMAL_REVIEW_REASON_LABELS.get(code, code) for code in review_reason_codes]
        return self.storage.create_case(
            case_type="formal_discipline",
            title=f"处分复核重开：是否对 {self._format_user(source_case.get('target_user_id'))} 作出{self._formal_sanction_label(current_sanction)}",
            description=str(review_payload.get("review_reasons") or source_case.get("description") or "处分复核重开"),
            proposer_id=int(review_payload.get("requester_id") or review_case.get("proposer_id") or source_case.get("proposer_id") or 0),
            target_user_id=int(source_case.get("target_user_id") or 0) or None,
            status="active",
            phase="accepted",
            support_threshold=0,
            vote_duration_seconds=int(source_case.get("vote_duration_seconds") or 0) or self._config_int(
                "governance_vote_duration_seconds",
                300,
            ),
            payload={
                "filer_id": int(review_payload.get("requester_id") or review_case.get("proposer_id") or source_case.get("proposer_id") or 0),
                "target_member_id": int(source_case.get("target_user_id") or source_payload.get("target_member_id") or 0) or None,
                "fact_summary": str(source_payload.get("fact_summary") or source_case.get("description") or ""),
                "evidence_refs": list(source_payload.get("evidence_refs") or []) + [f"review_case:{review_case['case_id']}"],
                "requested_sanction": current_sanction,
                "current_sanction": current_sanction,
                "requested_duration_seconds": int(source_payload.get("requested_duration_seconds") or self._formal_discipline_duration_seconds(source_case, current_sanction)),
                "accepted_at": now.isoformat(),
                "accepted_by_or_timeout_marker": f"review_case:{review_case['case_id']}",
                "origin": "review_reopen",
                "review_source_case_id": int(source_case["case_id"]),
                "review_request_case_id": int(review_case["case_id"]),
                "review_reasons": str(review_payload.get("review_reasons") or ""),
                "review_reason_codes": review_reason_codes,
                "review_reason_summary": "、".join(reason_labels) if reason_labels else "",
                "temporary_credit_seconds": int(source_payload.get("temporary_credit_seconds") or 0),
                "off_group_statement_channel": str(source_payload.get("off_group_statement_channel") or ""),
                "submitted_at": now.isoformat(),
                "review_channel": "申请处分复核 <处分案件ID> [复核理由]",
                **self._formal_discipline_scope_payload(),
            },
        )

    def _formal_discipline_threshold_ref(self, sanction_type: str) -> str:
        return self._FORMAL_SANCTION_THRESHOLD_REFS.get(sanction_type, "formal_discipline_long_mute")

    def _next_formal_discipline_sanction(self, sanction_type: str) -> Optional[str]:
        next_sanction = self._FORMAL_SANCTION_FALLBACKS.get(sanction_type)
        return str(next_sanction) if next_sanction else None

    def _formal_discipline_defense_hours(self, sanction_type: str) -> int:
        if sanction_type in {"remove_member", "restrict_vote", "restrict_candidacy"}:
            return self._config_int("governance_formal_severe_defense_hours", 24)
        return self._config_int("governance_formal_defense_hours", 12)

    def _formal_discipline_off_group_channel(self, case: Dict[str, object]) -> str:
        payload = case.get("payload") or {}
        channel = str(payload.get("off_group_statement_channel") or "").strip()
        if channel:
            return channel
        if str(payload.get("executed_measure_type") or "").strip() == "kick":
            return self._default_off_group_statement_channel()
        return ""

    def _formal_discipline_notice_deadline(self, case: Dict[str, object]) -> datetime:
        off_group_channel = self._formal_discipline_off_group_channel(case)
        if not off_group_channel:
            return datetime.now()
        if "私信" in off_group_channel:
            hours = self._config_int("governance_formal_notice_dm_hours", 6)
        else:
            hours = self._config_int("governance_formal_notice_offgroup_hours", 12)
        return datetime.now() + timedelta(hours=hours)

    def _merge_reviewer_ids(self, case: Dict[str, object], reviewer_id: int) -> List[int]:
        reviewer_ids = self._case_member_id_list(case, "reviewer_ids")
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)
        return reviewer_ids

    def _formal_discipline_duration_seconds(self, case: Dict[str, object], sanction_type: str) -> int:
        payload = case.get("payload") or {}
        requested_sanction = str(payload.get("requested_sanction") or "").strip()
        try:
            requested_duration_seconds = int(payload.get("requested_duration_seconds") or 0)
        except Exception:
            requested_duration_seconds = 0
        if sanction_type == requested_sanction and requested_duration_seconds > 0:
            return requested_duration_seconds
        if sanction_type == "long_mute":
            return self._config_int("governance_formal_default_long_mute_days", 7) * 24 * 3600
        if sanction_type in {"restrict_vote", "restrict_candidacy"}:
            return self._config_int("governance_formal_default_restrict_days", 30) * 24 * 3600
        return 0

    def _format_sanction_duration_suffix(self, sanction_type: str, duration_seconds: int) -> str:
        if sanction_type == "remove_member" or duration_seconds <= 0:
            return ""
        return f"（{self._format_duration(duration_seconds)}）"

    def _format_sanction_duration_suffix_from_case(self, case: Dict[str, object], sanction_type: str) -> str:
        return self._format_sanction_duration_suffix(
            sanction_type,
            self._formal_discipline_duration_seconds(case, sanction_type),
        )

    @staticmethod
    def _format_duration(duration_seconds: int) -> str:
        if duration_seconds <= 0:
            return "0 分钟"
        total_minutes = max(duration_seconds // 60, 1)
        days, remainder_minutes = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(remainder_minutes, 60)
        parts: List[str] = []
        if days:
            parts.append(f"{days} 天")
        if hours:
            parts.append(f"{hours} 小时")
        if minutes:
            parts.append(f"{minutes} 分钟")
        return "".join(parts) if parts else "1 分钟"

    def _parse_daily_management_request(self, plain_text: str) -> Dict[str, object]:
        tokens = [token for token in plain_text.split() if token]
        if not tokens:
            return {
                "error": "请在 @成员 后填写日常管理动作。支持：提醒 / 警告 / 短期禁言 / 限制提案 / 限制动议。",
                "action_type": "",
                "duration_seconds": 0,
                "reason": "",
            }
        formal_only = self._DAILY_MANAGEMENT_FORMAL_ONLY_ALIASES.get(tokens[0].strip())
        if formal_only:
            return {
                "error": (
                    "长期禁言、移出群聊、限制表决资格、限制被选举资格不得由日常管理直接作出。"
                    "如存在现实安全风险，请使用“发起紧急防护 @成员 理由”；否则请使用“发起正式处分 @成员 处分类型 [时长] [事实与理由]”。"
                ),
                "action_type": "",
                "duration_seconds": 0,
                "reason": "",
            }
        action_type = self._DAILY_MANAGEMENT_ACTION_ALIASES.get(tokens[0].strip())
        if not action_type:
            return {
                "error": "未识别的日常管理动作。支持：提醒 / 警告 / 短期禁言 / 限制提案 / 限制动议。",
                "action_type": "",
                "duration_seconds": 0,
                "reason": "",
            }
        duration_seconds = 0
        reason_start_index = 1
        if action_type in {"short_mute", "motion_restriction"}:
            if len(tokens) < 2:
                return {
                    "error": "该日常管理动作需要明确期限，例如：短期禁言 30m 或 限制提案 12h。",
                    "action_type": action_type,
                    "duration_seconds": 0,
                    "reason": "",
                }
            duration_seconds = self._parse_daily_management_duration_token(tokens[1])
            if duration_seconds <= 0:
                return {
                    "error": "日常管理期限格式无效或超出上限。支持单位：m / h / d 或 分钟 / 小时 / 天，且不得超过 24 小时。",
                    "action_type": action_type,
                    "duration_seconds": 0,
                    "reason": "",
                }
            reason_start_index = 2
        reason = " ".join(tokens[reason_start_index:]).strip()
        if not reason:
            return {
                "error": "请补充日常管理的事实与理由。",
                "action_type": action_type,
                "duration_seconds": duration_seconds,
                "reason": "",
            }
        return {
            "error": "",
            "action_type": action_type,
            "duration_seconds": duration_seconds,
            "reason": reason,
        }

    @staticmethod
    def _parse_daily_management_duration_token(token: str) -> int:
        match = re.fullmatch(r"(\d+)(m|min|分钟|h|小时|d|天)", token.strip(), flags=re.IGNORECASE)
        if not match:
            return 0
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            return 0
        if unit in {"m", "min", "分钟"}:
            duration_seconds = amount * 60
        elif unit in {"h", "小时"}:
            duration_seconds = amount * 3600
        else:
            duration_seconds = amount * 24 * 3600
        return duration_seconds if duration_seconds <= 24 * 3600 else 0

    def _parse_formal_discipline_request(self, plain_text: str) -> Dict[str, object]:
        tokens = [token for token in plain_text.split() if token]
        if not tokens:
            return {
                "error": "请在 @成员 后填写处分类型。支持：长期禁言 / 限制表决 / 限制被选举 / 移出群聊。",
                "sanction_type": "",
                "requested_duration_seconds": 0,
                "fact_summary": "",
            }
        sanction_type = self._FORMAL_SANCTION_ALIASES.get(tokens[0].strip())
        if not sanction_type:
            return {
                "error": "未识别的处分类型。支持：长期禁言 / 限制表决 / 限制被选举 / 移出群聊。",
                "sanction_type": "",
                "requested_duration_seconds": 0,
                "fact_summary": "",
            }
        requested_duration_seconds = 0
        reason_start_index = 1
        if sanction_type != "remove_member":
            if len(tokens) < 2:
                return {
                    "error": "该处分需要明确期限，例如：长期禁言 7d 或 限制表决 30d。",
                    "sanction_type": sanction_type,
                    "requested_duration_seconds": 0,
                    "fact_summary": "",
                }
            requested_duration_seconds = self._parse_formal_duration_token(tokens[1], sanction_type)
            if requested_duration_seconds <= 0:
                return {
                    "error": "处分期限格式无效或超出法定上限。支持单位：m / h / d 或 分钟 / 小时 / 天。",
                    "sanction_type": sanction_type,
                    "requested_duration_seconds": 0,
                    "fact_summary": "",
                }
            reason_start_index = 2
        fact_summary = " ".join(tokens[reason_start_index:]).strip()
        if not fact_summary:
            return {
                "error": "请补充正式处分的事实、理由或证据摘要。",
                "sanction_type": sanction_type,
                "requested_duration_seconds": requested_duration_seconds,
                "fact_summary": "",
            }
        return {
            "error": "",
            "sanction_type": sanction_type,
            "requested_duration_seconds": requested_duration_seconds,
            "fact_summary": fact_summary,
        }

    def _parse_formal_duration_token(self, token: str, sanction_type: str) -> int:
        match = re.fullmatch(r"(\d+)(m|min|分钟|h|小时|d|天)", token.strip(), flags=re.IGNORECASE)
        if not match:
            return 0
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            return 0
        if unit in {"m", "min", "分钟"}:
            duration_seconds = amount * 60
        elif unit in {"h", "小时"}:
            duration_seconds = amount * 3600
        else:
            duration_seconds = amount * 24 * 3600
        cap_seconds = 30 * 24 * 3600 if sanction_type == "long_mute" else 90 * 24 * 3600
        return duration_seconds if duration_seconds <= cap_seconds else 0

    def _evaluate_threshold_ref_vote_result(
        self,
        *,
        threshold_ref: str,
        yes_votes: int,
        no_votes: int,
        member_count: int,
        turnout: Optional[int] = None,
    ) -> tuple[bool, List[str]]:
        turnout = int(turnout if turnout is not None else yes_votes + no_votes)
        threshold_spec = self._get_threshold_spec(threshold_ref)
        if not threshold_spec:
            return yes_votes > no_votes and yes_votes > 0, []
        lines: List[str] = []
        turnout_floor = self._ceil_ratio(member_count, threshold_spec.get("turnout_min_of_all_voting_members"))
        if turnout_floor > 0:
            lines.append(f"参与门槛：有效投票不少于 {turnout_floor} 人")
        if turnout < turnout_floor:
            lines.append(f"本次有效投票：{turnout} 人，未达到参与门槛")
            return False, lines

        approval_spec = threshold_spec.get("approval") or {}
        approval_type = str(approval_spec.get("type") or "").strip()
        if approval_type == "approve_gt_reject":
            approve_floor = self._ceil_ratio(turnout, approval_spec.get("approve_min_of_turnout"))
            lines.append(f"通过条件：赞成票多于反对票，且不少于有效投票的 {approval_spec.get('approve_min_of_turnout')}")
            return yes_votes > no_votes and yes_votes >= approve_floor, lines
        if approval_type == "approve_gte_effective_votes_2_over_3":
            super_majority_floor = self._ceil_ratio(turnout, Fraction(2, 3))
            approve_floor = self._ceil_ratio(turnout, approval_spec.get("approve_min_of_turnout"))
            lines.append(
                f"通过条件：赞成票不少于 {super_majority_floor} 票，且不少于有效投票的 {approval_spec.get('approve_min_of_turnout')}"
            )
            return yes_votes >= super_majority_floor and yes_votes >= approve_floor, lines
        return yes_votes > no_votes and yes_votes > 0, lines

    def _build_formal_discipline_vote_resolution_patch(
        self,
        *,
        case: Dict[str, object],
        sanction_type: str,
        tally_payload: Dict[str, int],
        closed_at: datetime,
    ) -> Dict[str, object]:
        return {
            "tally": tally_payload,
            "sanction_type": sanction_type,
            "decision_summary": (
                f"案件已通过正式处分表决，处分类型为{self._formal_sanction_label(sanction_type)}"
                f"{self._format_sanction_duration_suffix_from_case(case, sanction_type)}。"
            ),
            "closed_at": closed_at.isoformat(),
        }

    def _build_formal_discipline_rejection_patch(
        self,
        *,
        case: Dict[str, object],
        tally_payload: Dict[str, int],
        closed_at: datetime,
    ) -> Dict[str, object]:
        current_sanction = self._formal_discipline_current_sanction(case)
        return {
            "tally": tally_payload,
            "decision_summary": (
                f"正式处分案件未通过。最后一轮表决处分为{self._formal_sanction_label(current_sanction)}"
                f"{self._format_sanction_duration_suffix_from_case(case, current_sanction)}。"
            ),
            "public_summary_ref": f"formal_case:{case['case_id']}:public_summary",
            "published_at": closed_at.isoformat(),
            "closed_at": closed_at.isoformat(),
        }

    async def _execute_formal_discipline_case(self, *, case: Dict[str, object]) -> tuple[bool, List[str]]:
        case_id = int(case["case_id"])
        payload = case.get("payload") or {}
        sanction_type = self._formal_discipline_current_sanction(case)
        target_user_id = int(case.get("target_user_id") or payload.get("target_member_id") or 0)
        duration_seconds = self._formal_discipline_duration_seconds(case, sanction_type)
        credited_seconds = 0
        effective_duration_seconds = duration_seconds
        if sanction_type == "long_mute":
            try:
                credited_seconds = min(int(payload.get("temporary_credit_seconds") or 0), duration_seconds)
            except Exception:
                credited_seconds = 0
            effective_duration_seconds = max(duration_seconds - credited_seconds, 0)
        now = datetime.now()
        expires_at = (
            now + timedelta(seconds=effective_duration_seconds)
            if sanction_type != "remove_member" and effective_duration_seconds > 0
            else (now if sanction_type == "long_mute" and duration_seconds > 0 else None)
        )

        try:
            if sanction_type == "long_mute":
                if target_user_id <= 0:
                    raise ValueError("缺少正式处分目标成员。")
                if effective_duration_seconds > 0:
                    await self.group.ban(target_user_id, effective_duration_seconds)
                    execution_ref = f"formal_ban:{effective_duration_seconds}s"
                    execution_line = f"已执行长期禁言：{self._format_user(target_user_id)}，追加时长 {self._format_duration(effective_duration_seconds)}。"
                else:
                    execution_ref = "formal_ban:credited_full"
                    execution_line = "临时禁言时长已足额折抵，无需追加执行。"
            elif sanction_type == "remove_member":
                if target_user_id <= 0:
                    raise ValueError("缺少正式处分目标成员。")
                if str(payload.get("executed_measure_type") or "").strip() == "kick":
                    execution_ref = "formal_remove_member:already_effective"
                    execution_line = "目标成员已在紧急程序中被临时移出，正式处分转为确认持续生效。"
                else:
                    await self.group.kick(target_user_id)
                    execution_ref = "formal_remove_member:kicked"
                    execution_line = f"已执行移出群聊：{self._format_user(target_user_id)}。"
            else:
                if target_user_id <= 0:
                    raise ValueError("缺少正式处分目标成员。")
                lock_type = self._FORMAL_RESTRICTION_LOCK_TYPES[sanction_type]
                if not expires_at:
                    raise ValueError("缺少正式处分期限。")
                self.storage.upsert_lock(
                    lock_key=f"case:{case_id}:{lock_type}:{target_user_id}",
                    lock_type=lock_type,
                    target_user_id=target_user_id,
                    source_case_id=case_id,
                    reason=(
                        f"正式处分：{self._formal_sanction_label(sanction_type)}，"
                        f"至 {expires_at.strftime('%Y-%m-%d %H:%M')}"
                    ),
                    payload={
                        "sanction_type": sanction_type,
                        "expires_at": expires_at.isoformat(),
                        "review_channel": str(payload.get("review_channel") or "申请处分复核 <处分案件ID> [复核理由]"),
                    },
                )
                execution_ref = f"{lock_type}:active"
                execution_line = (
                    f"已生效：{self._formal_sanction_label(sanction_type)}，持续至 {expires_at.strftime('%Y-%m-%d %H:%M')}。"
                )
        except Exception as exc:
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "execution_error": str(exc),
                            "execution_attempted_at": now.isoformat(),
                        },
                    )
                },
            )
            return False, [f"表决虽已通过，但执行失败：{exc}"]

        decision_summary = self._build_formal_discipline_decision_summary(
            case=case,
            sanction_type=sanction_type,
            duration_seconds=duration_seconds,
            effective_duration_seconds=effective_duration_seconds,
            credited_seconds=credited_seconds,
            effective_at=now,
            expires_at=expires_at,
        )
        self.storage.resolve_case_status(case_id=case_id, status="approved", phase="closed", resolved_at=now.isoformat())
        self.storage.update_case_fields(
            case_id,
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "sanction_type": sanction_type,
                        "execution_ref": execution_ref,
                        "effective_at": now.isoformat(),
                        "expires_at": expires_at.isoformat() if expires_at else "",
                        "credited_seconds_applied": credited_seconds,
                        "decision_summary": decision_summary,
                        "public_summary_ref": f"formal_case:{case_id}:public_summary",
                        "published_at": now.isoformat(),
                        "closed_at": now.isoformat(),
                    },
                )
            },
        )
        return True, [
            execution_line,
            decision_summary,
            "结果摘要已生成，并已保留处分复核入口说明。"
            if sanction_type != "remove_member"
            else "结果摘要已生成，并已保留处分复核入口说明。",
        ]

    def _build_formal_discipline_decision_summary(
        self,
        *,
        case: Dict[str, object],
        sanction_type: str,
        duration_seconds: int,
        effective_duration_seconds: int,
        credited_seconds: int,
        effective_at: datetime,
        expires_at: Optional[datetime],
    ) -> str:
        payload = case.get("payload") or {}
        fact_summary = str(payload.get("fact_summary") or case.get("description") or "").strip()
        evidence_refs = payload.get("evidence_refs") or []
        review_channel = str(payload.get("review_channel") or "申请处分复核 <处分案件ID> [复核理由]")
        parts = [
            f"事实认定：{fact_summary or '见案件材料'}",
            "依据条款：第六十条至第六十四条",
            f"证据摘要：{len(evidence_refs)} 项材料已进入案件记录",
            f"处分内容：{self._formal_sanction_label(sanction_type)}{self._format_sanction_duration_suffix(sanction_type, duration_seconds)}",
            f"生效时间：{effective_at.strftime('%Y-%m-%d %H:%M')}",
            f"复核渠道：{review_channel}",
        ]
        if sanction_type != "remove_member" and expires_at:
            parts.insert(
                4,
                f"起止时间：{effective_at.strftime('%Y-%m-%d %H:%M')} 至 {expires_at.strftime('%Y-%m-%d %H:%M')}",
            )
        if credited_seconds > 0:
            parts.append(f"临时措施折抵：{self._format_duration(credited_seconds)}")
        if sanction_type == "long_mute" and effective_duration_seconds <= 0:
            parts.append("执行结果：全部由前序临时禁言折抵，无需追加禁言")
        return "；".join(parts)

    @staticmethod
    def _merge_case_payload(case: Dict[str, object], patch: Dict[str, object]) -> Dict[str, object]:
        payload = dict(case.get("payload") or {})
        payload.update(patch)
        return payload

    def _format_case_stage(self, case: Dict[str, object]) -> str:
        phase = str(case.get("phase") or "").strip()
        phase_labels = {
            "procedural_review": "程序审查",
            "correction_requested": "待补正",
            "procedurally_rejected": "程序驳回",
            "discussion": "讨论期",
            "nomination_publicity": "提名公示",
            "statement_and_questioning": "陈述质询",
            "runoff_voting": "复选/加投",
            "honor_owner_response_pending": "响应等待",
            "temporary_measure_active": "临时措施中",
            "initial_review_due": "待初步复核",
            "extended_once": "客观原因公告",
            "acceptance_review": "受理审查",
            "accepted": "待送达",
            "notice_in_progress": "送达中",
            "defense_window": "申辩期",
            "evidence_review": "证据审查",
            "review_start_check": "复核启动审查",
            "reopened": "已启动复核",
            "denied": "复核驳回",
            "approved": "待执行",
            "closed": "已关闭",
        }
        if phase and phase not in {"draft", "support", "vote"}:
            return phase_labels.get(phase, phase)
        return str(case["status"])

    def _format_case_summary(self, case: Dict[str, object], *, include_proposer: bool) -> str:
        label = CASE_TYPE_LABELS.get(case["case_type"], case["case_type"])
        parts = [f"#{case['case_id']} {label}", self._format_case_stage(case)]
        if include_proposer:
            parts.append(f"发起人：{self._format_user(case.get('proposer_id'))}")
        parts.append(f"目标：{self._format_case_target(case)}")
        if case["case_type"] != "daily_management":
            parts.append(f"联署：{self.storage.count_case_supporters(int(case['case_id']))}/{case['support_threshold']}")
        extra = self._format_case_extra(case)
        if extra:
            parts.append(extra)
        applicability_note = self._case_law_applicability_note(case)
        if applicability_note:
            parts.append(applicability_note)
        return " / ".join(parts)

    def _format_case_target(self, case: Dict[str, object]) -> str:
        target_user_id = int(case.get("target_user_id") or 0)
        if target_user_id:
            return self._format_user(target_user_id)
        if case["case_type"] == "ordinary_proposal":
            return "全体表决权成员"
        if case["case_type"] in {"honor_owner_election", "elder_election"}:
            if case["case_type"] == "honor_owner_election":
                pending_candidates = self._pending_honor_owner_nomination_target_ids(case)
                if not self._case_candidate_ids(case) and len(pending_candidates) == 1:
                    return "待确认：" + self._format_user(pending_candidates[0])
                if not self._case_candidate_ids(case) and pending_candidates:
                    return f"{len(pending_candidates)} 项待确认提名"
            runoff_candidate_ids = self._case_member_id_list(case, "runoff_candidate_member_ids")
            if case["status"] == "runoff_voting" and runoff_candidate_ids:
                return "复选：" + self._format_user_list(runoff_candidate_ids)
            candidate_ids = self._case_candidate_ids(case)
            if len(candidate_ids) == 1:
                return self._format_user(candidate_ids[0])
            if candidate_ids:
                return f"{len(candidate_ids)} 名候选人"
            return "待提名"
        return "-"

    def _format_case_extra(self, case: Dict[str, object]) -> str:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return ""

        if case["case_type"] == "ordinary_proposal":
            extras: List[str] = []
            proposal_type = str(payload.get("proposal_type") or "").strip()
            if proposal_type:
                extras.append(f"类型：{self._proposal_type_label(proposal_type)}")
            if bool(payload.get("direct_collective_dispute_vote")):
                extras.append("争议直达：荣誉群主职权争议")
            review_due_at = self._parse_datetime(payload.get("review_due_at"))
            if str(case.get("phase") or "") == "procedural_review" and review_due_at:
                extras.append(f"审查截止：{review_due_at.strftime('%m-%d %H:%M')}")
            timeout_pending = self._format_timeout_pending_support(payload)
            if timeout_pending:
                extras.append(timeout_pending)
            correction_items = str(payload.get("correction_items") or "").strip()
            if str(case.get("phase") or "") == "correction_requested" and correction_items:
                extras.append(f"补正项：{correction_items}")
            discussion_closes_at = self._parse_datetime(payload.get("discussion_closes_at"))
            if str(case.get("phase") or "") == "discussion" and discussion_closes_at:
                extras.append(f"讨论截止：{discussion_closes_at.strftime('%m-%d %H:%M')}")
            rejection_reason = str(payload.get("rejection_reason") or "").strip()
            if str(case.get("phase") or "") == "procedurally_rejected" and rejection_reason:
                extras.append(f"驳回理由：{rejection_reason}")
            if str(case.get("phase") or "") == "procedurally_rejected":
                extras.append(f"复决联署：{self.storage.count_case_supporters(int(case['case_id']))}/{int(case.get('support_threshold') or 0)}")
            effective_time_or_expiry = str(payload.get("effective_time_or_expiry") or "").strip()
            if effective_time_or_expiry:
                extras.append(f"生效/期限：{effective_time_or_expiry}")
            if bool(payload.get("high_risk_power_requested")):
                extras.append("高风险：是")
            review_requests = payload.get("review_requests") or []
            if isinstance(review_requests, list) and review_requests:
                extras.append(f"复核请求：{len(review_requests)}")
            return "；".join(extras)

        if case["case_type"] == "honor_owner_election":
            extras: List[str] = []
            nomination_closes_at = self._parse_datetime(payload.get("nomination_closes_at"))
            if case["status"] == "nomination_publicity" and nomination_closes_at:
                extras.append(f"提名截止：{nomination_closes_at.strftime('%m-%d %H:%M')}")
            nomination_support_threshold = self._case_honor_owner_nomination_support_threshold(case)
            if nomination_support_threshold > 0:
                extras.append(f"联名门槛：{nomination_support_threshold}")
            questioning_closes_at = self._parse_datetime(payload.get("questioning_closes_at"))
            if case["status"] == "statement_and_questioning" and questioning_closes_at:
                extras.append(f"质询截止：{questioning_closes_at.strftime('%m-%d %H:%M')}")
            runoff_candidate_ids = self._case_member_id_list(case, "runoff_candidate_member_ids")
            if case["status"] == "runoff_voting" and runoff_candidate_ids:
                extras.append(f"复选候选：{self._format_user_list(runoff_candidate_ids)}")
            source_case_id = payload.get("source_case_id")
            if source_case_id:
                extras.append(f"来源案件：#{source_case_id}")
            vacancy_announced_at = self._parse_datetime(payload.get("vacancy_announced_at"))
            if vacancy_announced_at:
                extras.append(f"空缺公告：{vacancy_announced_at.strftime('%m-%d %H:%M')}")
            reopen_count = self._case_payload_int(case, "nomination_reopen_count")
            if reopen_count > 0:
                extras.append(f"已续开：{reopen_count} 次")
            failure_count = self._case_payload_int(case, "consecutive_failed_by_election_rounds")
            if failure_count > 0:
                extras.append(f"补选流产：{failure_count} 次")
            temporary_autonomy_deadline = self._parse_datetime(payload.get("temporary_autonomy_restart_deadline_at"))
            if temporary_autonomy_deadline:
                extras.append(f"临时自治至：{temporary_autonomy_deadline.strftime('%m-%d %H:%M')}")
            temporary_proxy_status = str(payload.get("temporary_proxy_status") or "").strip()
            if temporary_proxy_status == "pending_elder_designation":
                extras.append("临时代理：待元老会指定")
            elif temporary_proxy_status == "elder_designated_proxy":
                temporary_proxy_user_id = int(payload.get("temporary_proxy_user_id") or 0)
                if temporary_proxy_user_id > 0:
                    extras.append(f"临时代理：{self._format_user(temporary_proxy_user_id)}")
                temporary_proxy_expires_at = self._parse_datetime(payload.get("temporary_proxy_expires_at"))
                if temporary_proxy_expires_at:
                    extras.append(f"代理至：{temporary_proxy_expires_at.strftime('%m-%d %H:%M')}")
            elif temporary_proxy_status == "bot_temporary_autonomy":
                extras.append("临时代理：机器人临时自治")
            if str(payload.get("dispute_resolution_channel") or "").strip() == "full_voting_members":
                extras.append("争议直达：全体表决权成员表决")
            candidate_ids = self._case_candidate_ids(case)
            if candidate_ids:
                extras.append(f"候选人数：{len(candidate_ids)}")
            nomination_previews = self._format_pending_honor_owner_nomination_previews(case)
            if nomination_previews:
                extras.append("联名待确认：" + "、".join(nomination_previews))
            term_expires_at = self._parse_datetime(payload.get("term_expires_at"))
            if term_expires_at:
                extras.append(f"任期至：{term_expires_at.strftime('%Y-%m-%d %H:%M')}")
            caretaker_deadline_at = self._parse_datetime(payload.get("caretaker_deadline_at"))
            if caretaker_deadline_at:
                extras.append(f"看守至：{caretaker_deadline_at.strftime('%Y-%m-%d %H:%M')}")
            last_summary_at = self._parse_datetime(payload.get("last_governance_summary_at"))
            if last_summary_at:
                extras.append(f"最近摘要：{last_summary_at.strftime('%m-%d %H:%M')}")
            return "；".join(extras)

        if case["case_type"] == "elder_election":
            extras = [f"席位：{self._elder_case_total_seat_count(case)}"]
            nomination_closes_at = self._parse_datetime(payload.get("nomination_closes_at"))
            if case["status"] == "nomination_publicity" and nomination_closes_at:
                extras.append(f"提名截止：{nomination_closes_at.strftime('%m-%d %H:%M')}")
            runoff_candidate_ids = self._case_member_id_list(case, "runoff_candidate_member_ids")
            if case["status"] == "runoff_voting" and runoff_candidate_ids:
                extras.append(f"加投候选：{self._format_user_list(runoff_candidate_ids)}")
            reopen_count = self._case_payload_int(case, "nomination_reopen_count")
            if reopen_count > 0:
                extras.append(f"已续开：{reopen_count} 次")
            fixed_winner_ids = self._case_member_id_list(case, "fixed_winner_member_ids")
            if fixed_winner_ids:
                extras.append(f"已确定：{self._format_user_list(fixed_winner_ids)}")
            return "；".join(extras)

        if case["case_type"] == "honor_owner_impeachment":
            extras = []
            reason_summary = str(payload.get("reason_summary") or "").strip()
            if reason_summary:
                extras.append(f"理由：{reason_summary}")
            response_window_closes_at = self._parse_datetime(payload.get("response_window_closes_at"))
            if case["status"] == "response_window" and response_window_closes_at:
                extras.append(f"回应截止：{response_window_closes_at.strftime('%m-%d %H:%M')}")
            return "；".join(extras)

        if case["case_type"] == "elder_impeachment":
            extras = []
            reason_summary = str(payload.get("reason_summary") or "").strip()
            if reason_summary:
                extras.append(f"理由：{reason_summary}")
            response_window_closes_at = self._parse_datetime(payload.get("response_window_closes_at"))
            if case["status"] == "response_window" and response_window_closes_at:
                extras.append(f"回应截止：{response_window_closes_at.strftime('%m-%d %H:%M')}")
            return "；".join(extras)

        if case["case_type"] == "elder_reboot":
            extras: List[str] = []
            reason_summary = str(payload.get("institutional_reason_summary") or "").strip()
            if reason_summary:
                extras.append(f"理由：{reason_summary}")
            cooling_closes_at = self._parse_datetime(payload.get("cooling_closes_at"))
            if case["status"] == "cooling" and cooling_closes_at:
                extras.append(f"冷却截止：{cooling_closes_at.strftime('%m-%d %H:%M')}")
            deadline = self._parse_datetime(payload.get("new_council_election_deadline_at"))
            if deadline:
                extras.append(f"新元老会选举截止：{deadline.strftime('%m-%d %H:%M')}")
            failed_rounds = self._case_payload_int(case, "new_council_failed_election_rounds")
            if failed_rounds > 0:
                extras.append(f"换届流产：{failed_rounds} 次")
            if bool(payload.get("temporary_collective_supervision_active")):
                extras.append("已转全体表决权成员临时监督")
            elif bool(payload.get("interim_supervision_active")):
                extras.append("监督中：荣誉群主仅处理日常事务")
            return "；".join(extras)
        if case["case_type"] == "daily_management":
            extras: List[str] = []
            action_label = str(payload.get("action_label") or "").strip()
            if action_label:
                extras.append(f"动作：{action_label}")
            duration_seconds = self._case_payload_int(case, "duration_seconds")
            expires_at = self._parse_datetime(payload.get("expires_at"))
            if duration_seconds > 0 and expires_at:
                extras.append(f"期限：{expires_at.strftime('%m-%d %H:%M')}（{self._format_duration(duration_seconds)}）")
            prior_action_labels = payload.get("prior_action_labels") or []
            if isinstance(prior_action_labels, list) and prior_action_labels:
                extras.append(f"前序：{'、'.join(str(label) for label in prior_action_labels if str(label).strip())}")
            return "；".join(extras)
        if case["case_type"] == "emergency_protection":
            extras: List[str] = []
            response_due_at = self._parse_datetime(payload.get("response_due_at"))
            if case.get("phase") == "honor_owner_response_pending" and response_due_at:
                extras.append(f"响应截止：{response_due_at.strftime('%m-%d %H:%M')}")
            initial_review_due_at = self._parse_datetime(payload.get("initial_review_due_at"))
            if case.get("phase") in {"initial_review_due", "extended_once"} and initial_review_due_at:
                extras.append(f"初步复核：{initial_review_due_at.strftime('%m-%d %H:%M')}")
            formal_bridge_due_at = self._parse_datetime(payload.get("formal_bridge_due_at")) or self._parse_datetime(
                payload.get("measure_expires_at")
            )
            if case["status"] == "active" and formal_bridge_due_at:
                extras.append(f"转正式处分：{formal_bridge_due_at.strftime('%m-%d %H:%M')}")
            executed_measure_type = str(payload.get("executed_measure_type") or "").strip()
            if executed_measure_type:
                extras.append(f"已执行：{executed_measure_type}")
            temporary_measure_ends_at = self._parse_datetime(payload.get("temporary_measure_ends_at"))
            if temporary_measure_ends_at:
                extras.append(f"措施截止：{temporary_measure_ends_at.strftime('%m-%d %H:%M')}")
            off_group_statement_channel = str(payload.get("off_group_statement_channel") or "").strip()
            if off_group_statement_channel:
                extras.append(f"站外陈述：{off_group_statement_channel}")
            escalated_case_ref = payload.get("escalated_case_ref")
            if escalated_case_ref:
                extras.append(f"已转正式处分：#{escalated_case_ref}")
            objective_reason = str(payload.get("objective_reason_if_any") or "").strip()
            if objective_reason and case.get("phase") == "extended_once":
                extras.append("已公告客观原因")
            return "；".join(extras)
        if case["case_type"] == "formal_discipline":
            extras = []
            source_case_id = payload.get("source_case_id")
            if source_case_id:
                extras.append(f"来源紧急案件：#{source_case_id}")
            formal_scope_summary = str(payload.get("formal_scope_summary") or "").strip()
            if formal_scope_summary:
                extras.append(f"适用范围：{formal_scope_summary}")
            current_sanction = self._formal_discipline_current_sanction(case)
            if current_sanction:
                extras.append(
                    "建议处分："
                    + self._formal_sanction_label(current_sanction)
                    + self._format_sanction_duration_suffix_from_case(case, current_sanction)
                )
            try:
                temporary_credit_seconds = int(payload.get("temporary_credit_seconds") or 0)
            except Exception:
                temporary_credit_seconds = 0
            if temporary_credit_seconds > 0:
                extras.append(f"临时措施折抵：{temporary_credit_seconds // 60} 分钟")
            acceptance_due_at = self._parse_datetime(payload.get("acceptance_due_at"))
            if case.get("phase") == "acceptance_review" and acceptance_due_at:
                extras.append(f"受理截止：{acceptance_due_at.strftime('%m-%d %H:%M')}")
            timeout_pending = self._format_timeout_pending_support(payload)
            if timeout_pending:
                extras.append(timeout_pending)
            deemed_service_deadline = self._parse_datetime(payload.get("deemed_service_deadline"))
            if case.get("phase") == "notice_in_progress" and deemed_service_deadline:
                extras.append(f"视为送达：{deemed_service_deadline.strftime('%m-%d %H:%M')}")
            defense_closes_at = self._parse_datetime(payload.get("defense_closes_at"))
            if case.get("phase") == "defense_window" and defense_closes_at:
                extras.append(f"申辩截止：{defense_closes_at.strftime('%m-%d %H:%M')}")
            off_group_statement_channel = str(payload.get("off_group_statement_channel") or "").strip()
            if off_group_statement_channel:
                extras.append(f"送达/陈述：{off_group_statement_channel}")
            execution_ref = str(payload.get("execution_ref") or "").strip()
            if execution_ref:
                extras.append(f"执行记录：{execution_ref}")
            expires_at = self._parse_datetime(payload.get("expires_at"))
            if expires_at:
                extras.append(f"到期：{expires_at.strftime('%m-%d %H:%M')}")
            timeout_stage = str(payload.get("timeout_fallback_actor_stage") or "").strip()
            if timeout_stage:
                extras.append(f"超时转接：{self._timeout_fallback_stage_label(timeout_stage)}")
            return "；".join(extras)
        if case["case_type"] == "formal_discipline_review":
            extras = []
            source_case_id = payload.get("source_case_id")
            if source_case_id:
                extras.append(f"原处分：#{source_case_id}")
            requester_id = payload.get("requester_id")
            if requester_id:
                extras.append(f"申请人：{self._format_user(requester_id)}")
            review_reasons = str(payload.get("review_reasons") or "").strip()
            if review_reasons:
                extras.append(f"理由：{review_reasons}")
            start_check_due_at = self._parse_datetime(payload.get("start_check_due_at"))
            if case.get("phase") == "review_start_check" and start_check_due_at:
                extras.append(f"启动截止：{start_check_due_at.strftime('%m-%d %H:%M')}")
            timeout_pending = self._format_timeout_pending_support(payload)
            if timeout_pending:
                extras.append(timeout_pending)
            if case.get("phase") == "reopened":
                pause_execution = bool(payload.get("pause_execution"))
                extras.append(f"暂停执行：{'已处理' if pause_execution else '未处理'}")
            denial_reason = str(payload.get("denial_reason") or "").strip()
            if denial_reason:
                extras.append(f"驳回原因：{denial_reason}")
            new_case_ref = payload.get("new_case_ref")
            if new_case_ref:
                extras.append(f"重开案件：#{new_case_ref}")
            legacy_exception_basis = str(payload.get("legacy_exception_basis") or "").strip()
            legacy_exception_label = self._LEGACY_REVIEW_EXCEPTION_LABELS.get(legacy_exception_basis, "")
            if legacy_exception_label:
                extras.append(f"附则例外：{legacy_exception_label}")
            timeout_stage = str(payload.get("timeout_fallback_actor_stage") or "").strip()
            if timeout_stage:
                extras.append(f"超时转接：{self._timeout_fallback_stage_label(timeout_stage)}")
            return "；".join(extras)
        return ""

    def _find_pending_new_council_election_notice(self, cases: List[Dict[str, object]]) -> str:
        for case in cases:
            if case.get("case_type") != "elder_reboot":
                continue
            payload = case.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            deadline = self._parse_datetime(payload.get("new_council_election_deadline_at"))
            if not deadline:
                continue
            if payload.get("new_council_election_started_case_id"):
                continue
            if datetime.now() <= deadline:
                return (
                    f"案件 #{case['case_id']} 需在 {deadline.strftime('%Y-%m-%d %H:%M')} 前启动新一届元老会选举"
                )
            return f"案件 #{case['case_id']} 的新一届元老会选举启动期限已过"
        return ""

    def _find_reboot_supervision_notice(self, cases: List[Dict[str, object]]) -> str:
        for case in cases:
            if case.get("case_type") != "elder_reboot":
                continue
            payload = case.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if bool(payload.get("temporary_collective_supervision_active")):
                return (
                    f"案件 #{case['case_id']} 的新元老会选举已连续 "
                    f"{int(payload.get('new_council_failed_election_rounds') or 0)} 次流产，"
                    "现由全体表决权成员临时行使监督与复核权"
                )
            if bool(payload.get("interim_supervision_active")):
                restored_at = self._parse_datetime(payload.get("new_council_restored_at"))
                if restored_at:
                    continue
                return (
                    f"案件 #{case['case_id']} 正处于重组后的临时监督期："
                    "荣誉群主仅处理日常事务；涉及其自身监督事项，应提交全体表决权成员临时复核"
                )
        return ""

    def _ensure_honor_owner_by_election_case(
        self,
        *,
        operator_id: int,
        source_case_id: int,
        reopen_reason: str,
        ignore_case_id: Optional[int] = None,
        failure_count: int = 0,
    ) -> int:
        existing = self.storage.find_open_case_by_type("honor_owner_election")
        if existing and int(existing["case_id"]) != int(ignore_case_id or 0):
            existing_case = self.storage.get_case(int(existing["case_id"]))
            if existing_case and existing_case["status"] == "nomination_publicity":
                vacancy_announced_at = self._case_payload_datetime(existing_case, "vacancy_announced_at") or datetime.now()
                effective_failure_count = max(
                    self._case_payload_int(existing_case, "consecutive_failed_by_election_rounds"),
                    failure_count,
                )
                patch = {
                    "payload_json": self._merge_case_payload(
                        existing_case,
                        {
                            "source_case_id": source_case_id,
                            "reopen_reason": reopen_reason,
                            "nomination_support_threshold": self._honor_owner_nomination_support_threshold(),
                            "vacancy_announced_at": vacancy_announced_at.isoformat(),
                            "vacancy_reason": reopen_reason,
                            "consecutive_failed_by_election_rounds": effective_failure_count,
                            "temporary_proxy_status": "bot_temporary_autonomy"
                            if effective_failure_count >= 2
                            else "pending_elder_designation",
                            "temporary_proxy_scope": "仅维持日常秩序与紧急安全，不得行使高风险权限"
                            if effective_failure_count >= 2
                            else "待元老会指定 1 名临时程序代理处理必要事务",
                            "dispute_resolution_channel": "full_voting_members"
                            if effective_failure_count >= 2
                            else "elder_designated_proxy",
                        },
                    )
                }
                if effective_failure_count >= 2:
                    autonomy_started_at = datetime.now()
                    patch["payload_json"].update(
                        {
                            "temporary_autonomy_active": True,
                            "temporary_autonomy_started_at": autonomy_started_at.isoformat(),
                            "temporary_autonomy_restart_deadline_at": (
                                autonomy_started_at + timedelta(hours=self._honor_owner_temporary_autonomy_restart_hours())
                            ).isoformat(),
                            "temporary_autonomy_scope": "仅维持日常秩序与紧急安全，不得行使高风险权限",
                        }
                    )
                self.storage.update_case_fields(int(existing["case_id"]), patch)
            return int(existing["case_id"])
        nomination_hours = self._config_int("governance_nomination_publicity_hours", 24)
        nomination_opened_at = datetime.now()
        payload = {
            "candidate_member_ids": [],
            "candidate_nominations": {},
            "nomination_method": "by_election",
            "nomination_support_threshold": self._honor_owner_nomination_support_threshold(),
            "source_case_id": source_case_id,
            "reopen_reason": reopen_reason,
            "nomination_opened_at": nomination_opened_at.isoformat(),
            "nomination_closes_at": (nomination_opened_at + timedelta(hours=nomination_hours)).isoformat(),
            "nomination_reopen_count": 0,
            "vacancy_announced_at": nomination_opened_at.isoformat(),
            "vacancy_reason": reopen_reason,
            "consecutive_failed_by_election_rounds": max(failure_count, 0),
            "temporary_proxy_status": "bot_temporary_autonomy" if failure_count >= 2 else "pending_elder_designation",
            "temporary_proxy_scope": "仅维持日常秩序与紧急安全，不得行使高风险权限"
            if failure_count >= 2
            else "待元老会指定 1 名临时程序代理处理必要事务",
            "dispute_resolution_channel": "full_voting_members" if failure_count >= 2 else "elder_designated_proxy",
        }
        if failure_count >= 2:
            payload.update(
                {
                    "temporary_autonomy_active": True,
                    "temporary_autonomy_started_at": nomination_opened_at.isoformat(),
                    "temporary_autonomy_restart_deadline_at": (
                        nomination_opened_at + timedelta(hours=self._honor_owner_temporary_autonomy_restart_hours())
                    ).isoformat(),
                    "temporary_autonomy_scope": "仅维持日常秩序与紧急安全，不得行使高风险权限",
                }
            )
        return self.storage.create_case(
            case_type="honor_owner_election",
            title="荣誉群主补选提名公示",
            description=reopen_reason,
            proposer_id=operator_id,
            target_user_id=None,
            status="nomination_publicity",
            phase="nomination_publicity",
            support_threshold=0,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload=payload,
        )

    async def _attach_candidate_to_honor_owner_case(
        self,
        *,
        case: Dict[str, object],
        target_user_id: int,
        proposer_id: int,
        reason: str,
    ) -> Dict[str, object]:
        await self._ensure_member_profile(target_user_id)
        candidate_ids = self._case_candidate_ids(case)
        nominations = self._case_honor_owner_nominations(case)
        entry_key = str(target_user_id)
        entry = dict(nominations.get(entry_key) or {})
        supporter_ids = [value for value in self._entry_member_ids(entry, "supporter_ids") if value > 0]
        support_added = proposer_id not in supporter_ids
        if support_added:
            supporter_ids.append(proposer_id)
        is_self_nomination = proposer_id == target_user_id
        willing_confirmed = bool(entry.get("willing_to_serve_confirmed")) or is_self_nomination
        nomination_method = str(entry.get("nomination_method") or "").strip()
        if not nomination_method:
            nomination_method = "self_nomination" if is_self_nomination else "joint_recommendation"
        elif nomination_method == "joint_recommendation" and is_self_nomination:
            nomination_method = "joint_recommendation"
        threshold = self._case_honor_owner_nomination_support_threshold(case)
        qualified = target_user_id in candidate_ids or is_self_nomination or (
            willing_confirmed and len(supporter_ids) >= threshold
        )
        if qualified and target_user_id not in candidate_ids:
            candidate_ids.append(target_user_id)
        if not qualified and target_user_id in candidate_ids:
            candidate_ids.remove(target_user_id)
        nomination_status = "qualified"
        if not qualified:
            nomination_status = "pending_self_confirmation" if len(supporter_ids) >= threshold else "pending_support"
        entry.update(
            {
                "candidate_id": target_user_id,
                "nomination_method": nomination_method,
                "supporter_ids": supporter_ids,
                "supporter_threshold": threshold,
                "supporter_count": len(supporter_ids),
                "willing_to_serve_confirmed": willing_confirmed,
                "willing_confirmed_by": target_user_id if willing_confirmed else None,
                "willing_confirmed_at": datetime.now().isoformat() if willing_confirmed else None,
                "latest_reason": reason or str(entry.get("latest_reason") or ""),
                "nomination_status": nomination_status,
                "latest_nominated_at": datetime.now().isoformat(),
                "self_nominated": bool(entry.get("self_nominated")) or is_self_nomination,
            }
        )
        if not entry.get("first_nominated_at"):
            entry["first_nominated_at"] = datetime.now().isoformat()
        nominations[entry_key] = entry
        payload = self._merge_case_payload(
            case,
            {
                "candidate_member_ids": candidate_ids,
                "candidate_nominations": nominations,
                "candidate_id": target_user_id if len(candidate_ids) == 1 else None,
                "nomination_method": self._derive_honor_owner_case_nomination_method(
                    candidate_ids=candidate_ids,
                    nominations=nominations,
                    fallback=str((case.get("payload") or {}).get("nomination_method") or "pending_nomination"),
                ),
                "nomination_support_threshold": threshold,
                "reason": reason or str((case.get("payload") or {}).get("reason") or ""),
            },
        )
        self.storage.update_case_fields(
            int(case["case_id"]),
            {
                "payload_json": payload,
            },
        )
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_cases
                SET target_user_id = ?,
                    title = ?,
                    description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = ?
            """,
                (
                    target_user_id if len(candidate_ids) == 1 else None,
                    "荣誉群主选举提名公示",
                    str(case.get("description") or reason or "荣誉群主选举"),
                    int(case["case_id"]),
                ),
            )
        return {
            "target_user_id": target_user_id,
            "qualified": qualified,
            "support_added": support_added,
            "supporter_count": len(supporter_ids),
            "supporter_threshold": threshold,
            "pending_self_confirmation": nomination_status == "pending_self_confirmation",
            "nomination_method": nomination_method,
            "candidate_count": len(candidate_ids),
            "pending_nomination_count": len(self._pending_honor_owner_nomination_target_ids({"payload": payload})),
            "candidate_is_elder": self.storage.has_role(target_user_id, "elder"),
            "is_self_nomination": is_self_nomination,
        }

    @staticmethod
    def _can_attach_candidate_to_honor_owner_case(case: Dict[str, object]) -> bool:
        return case["status"] == "nomination_publicity"

    def _ensure_elder_by_election_case(
        self,
        *,
        operator_id: int,
        source_case_id: int,
        reopen_reason: str,
        seat_count: int,
        ignore_case_id: Optional[int] = None,
    ) -> int:
        existing = self.storage.find_open_case_by_type("elder_election")
        if existing and int(existing["case_id"]) != int(ignore_case_id or 0):
            existing_case = self.storage.get_case(int(existing["case_id"]))
            if existing_case and existing_case["status"] == "nomination_publicity":
                merged_seat_count = max(self._elder_case_total_seat_count(existing_case), seat_count)
                self.storage.update_case_fields(
                    int(existing["case_id"]),
                    {
                        "payload_json": self._merge_case_payload(
                            existing_case,
                            {
                                "seat_count": merged_seat_count,
                                "source_case_id": source_case_id,
                                "reboot_source_case_id": self._reboot_source_case_id(existing_case)
                                or self._resolve_reboot_source_case_id(source_case_id),
                                "reopen_reason": reopen_reason,
                                "desired_council_seat_count": self._desired_elder_seat_count(),
                                "term_days": self._elder_term_days(),
                            },
                        )
                    },
                )
            return int(existing["case_id"])
        nomination_hours = self._elder_nomination_publicity_hours()
        nomination_opened_at = datetime.now()
        case_id = self.storage.create_case(
            case_type="elder_election",
            title="元老选举提名公示",
            description=reopen_reason,
            proposer_id=operator_id,
            target_user_id=None,
            status="nomination_publicity",
            phase="nomination_publicity",
            support_threshold=0,
            vote_duration_seconds=self._config_int("governance_vote_duration_seconds", 300),
            payload={
                "candidate_member_ids": [],
                "nomination_method": "by_election",
                "source_case_id": source_case_id,
                "reboot_source_case_id": self._resolve_reboot_source_case_id(source_case_id),
                "reopen_reason": reopen_reason,
                "seat_count": max(1, seat_count),
                "desired_council_seat_count": self._desired_elder_seat_count(),
                "term_days": self._elder_term_days(),
                "nomination_opened_at": nomination_opened_at.isoformat(),
                "nomination_closes_at": (nomination_opened_at + timedelta(hours=nomination_hours)).isoformat(),
                "nomination_reopen_count": 0,
            },
        )
        self._mark_reboot_election_started(source_case_id=source_case_id, election_case_id=case_id)
        return case_id

    async def _attach_candidate_to_elder_case(
        self,
        *,
        case: Dict[str, object],
        target_user_id: int,
        reason: str,
    ) -> None:
        await self._ensure_member_profile(target_user_id)
        candidate_ids = self._case_candidate_ids(case)
        if target_user_id not in candidate_ids:
            candidate_ids.append(target_user_id)
        self.storage.update_case_fields(
            int(case["case_id"]),
            {
                "payload_json": self._merge_case_payload(
                    case,
                    {
                        "candidate_member_ids": candidate_ids,
                        "nomination_method": "manual_nomination",
                        "reason": reason or "",
                    },
                )
            },
        )
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_cases
                SET title = ?,
                    description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = ?
            """,
                (
                    "元老选举提名公示",
                    reason or "元老补选",
                    int(case["case_id"]),
                ),
            )

    @staticmethod
    def _can_attach_candidate_to_elder_case(case: Dict[str, object]) -> bool:
        return case["status"] == "nomination_publicity"

    def _honor_owner_case_has_candidate(self, case: Dict[str, object]) -> bool:
        return bool(self._case_candidate_ids(case))

    def _case_honor_owner_nominations(self, case: Dict[str, object]) -> Dict[str, Dict[str, object]]:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return {}
        raw_nominations = payload.get("candidate_nominations") or {}
        if not isinstance(raw_nominations, dict):
            return {}
        nominations: Dict[str, Dict[str, object]] = {}
        for raw_key, raw_value in raw_nominations.items():
            if not isinstance(raw_value, dict):
                continue
            try:
                candidate_id = int(raw_value.get("candidate_id") or raw_key)
            except Exception:
                continue
            if candidate_id <= 0:
                continue
            entry = dict(raw_value)
            entry["candidate_id"] = candidate_id
            entry["supporter_ids"] = self._entry_member_ids(entry, "supporter_ids")
            nominations[str(candidate_id)] = entry
        return nominations

    @staticmethod
    def _entry_member_ids(entry: Dict[str, object], key: str) -> List[int]:
        member_ids: List[int] = []
        for value in entry.get(key) or []:
            try:
                member_id = int(value)
            except Exception:
                continue
            if member_id > 0 and member_id not in member_ids:
                member_ids.append(member_id)
        return member_ids

    def _case_honor_owner_nomination_support_threshold(self, case: Dict[str, object]) -> int:
        payload = case.get("payload") or {}
        if isinstance(payload, dict):
            try:
                threshold = int(payload.get("nomination_support_threshold") or 0)
                if threshold > 0:
                    return threshold
            except Exception:
                pass
        return self._honor_owner_nomination_support_threshold()

    def _pending_honor_owner_nomination_target_ids(self, case: Dict[str, object]) -> List[int]:
        pending_ids: List[int] = []
        for entry in self._case_honor_owner_nominations(case).values():
            status = str(entry.get("nomination_status") or "").strip()
            candidate_id = int(entry.get("candidate_id") or 0)
            if candidate_id > 0 and status in {"pending_support", "pending_self_confirmation"} and candidate_id not in pending_ids:
                pending_ids.append(candidate_id)
        return pending_ids

    def _pending_honor_owner_nomination_count(self, case: Dict[str, object], *, status: str) -> int:
        total = 0
        for entry in self._case_honor_owner_nominations(case).values():
            if str(entry.get("nomination_status") or "").strip() == status:
                total += 1
        return total

    def _format_pending_honor_owner_nomination_previews(self, case: Dict[str, object]) -> List[str]:
        previews: List[str] = []
        threshold = self._case_honor_owner_nomination_support_threshold(case)
        for entry in self._case_honor_owner_nominations(case).values():
            status = str(entry.get("nomination_status") or "").strip()
            if status not in {"pending_support", "pending_self_confirmation"}:
                continue
            candidate_id = int(entry.get("candidate_id") or 0)
            if candidate_id <= 0:
                continue
            supporter_count = len(self._entry_member_ids(entry, "supporter_ids"))
            suffix = "待本人确认" if status == "pending_self_confirmation" else "联名中"
            previews.append(f"{self._format_user(candidate_id)} {supporter_count}/{threshold} {suffix}")
            if len(previews) >= 2:
                break
        return previews

    @staticmethod
    def _derive_honor_owner_case_nomination_method(
        *,
        candidate_ids: List[int],
        nominations: Dict[str, Dict[str, object]],
        fallback: str,
    ) -> str:
        if not candidate_ids:
            return fallback
        active_methods: List[str] = []
        for candidate_id in candidate_ids:
            entry = nominations.get(str(candidate_id)) or {}
            method = str(entry.get("nomination_method") or "").strip()
            if method and method not in active_methods:
                active_methods.append(method)
        if not active_methods:
            return fallback
        if len(active_methods) == 1 and len(candidate_ids) == 1:
            return active_methods[0]
        return "mixed"

    def _case_candidate_ids(self, case: Dict[str, object]) -> List[int]:
        payload = case.get("payload") or {}
        candidate_ids: List[int] = []
        if int(case.get("target_user_id") or 0):
            candidate_ids.append(int(case["target_user_id"]))
        if isinstance(payload, dict):
            for value in payload.get("candidate_member_ids") or []:
                try:
                    candidate_id = int(value)
                except Exception:
                    continue
                if candidate_id > 0 and candidate_id not in candidate_ids:
                    candidate_ids.append(candidate_id)
        return candidate_ids

    def _case_ballot_candidate_ids(self, case: Dict[str, object]) -> List[int]:
        if case["status"] == "runoff_voting":
            runoff_candidate_ids = self._case_member_id_list(case, "runoff_candidate_member_ids")
            if runoff_candidate_ids:
                return runoff_candidate_ids
        return self._case_candidate_ids(case)

    def _case_member_id_list(self, case: Dict[str, object], key: str) -> List[int]:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return []
        member_ids: List[int] = []
        for value in payload.get(key) or []:
            try:
                member_id = int(value)
            except Exception:
                continue
            if member_id > 0 and member_id not in member_ids:
                member_ids.append(member_id)
        return member_ids

    def _elder_case_total_seat_count(self, case: Dict[str, object]) -> int:
        payload = case.get("payload") or {}
        if isinstance(payload, dict):
            try:
                seat_count = int(payload.get("seat_count") or 0)
                if seat_count > 0:
                    return seat_count
            except Exception:
                pass
        return max(self._determine_elder_election_seat_count(), 1)

    def _elder_case_current_round_seat_count(self, case: Dict[str, object]) -> int:
        if case["status"] == "runoff_voting":
            payload = case.get("payload") or {}
            if isinstance(payload, dict):
                try:
                    runoff_seat_count = int(payload.get("runoff_seat_count") or 0)
                    if runoff_seat_count > 0:
                        return runoff_seat_count
                except Exception:
                    pass
        return self._elder_case_total_seat_count(case)

    def _determine_elder_election_seat_count(self) -> int:
        desired_seat_count = self._desired_elder_seat_count()
        active_elder_count = len(self.storage.get_active_role_users("elder"))
        return max(desired_seat_count - active_elder_count, 0)

    def _desired_elder_seat_count(self) -> int:
        reboot_case = self.storage.fetchone(
            """
            SELECT case_id, payload_json
            FROM governance_cases
            WHERE case_type = 'elder_reboot'
            ORDER BY case_id DESC
            LIMIT 1
        """
        )
        if reboot_case:
            payload = reboot_case.get("payload") or {}
            if isinstance(payload, dict):
                try:
                    reboot_seat_count = int(payload.get("new_council_election_seat_count") or 0)
                    if reboot_seat_count in {3, 5, 7}:
                        return reboot_seat_count
                except Exception:
                    pass
        active_elder_count = len(self.storage.get_active_role_users("elder"))
        if active_elder_count >= 3:
            return min(active_elder_count if active_elder_count % 2 == 1 else active_elder_count + 1, 7)
        return 3

    def _mark_reboot_election_started(self, *, source_case_id: int, election_case_id: int) -> None:
        reboot_case_id = self._resolve_reboot_source_case_id(source_case_id)
        if reboot_case_id <= 0:
            return
        source_case = self.storage.get_case(reboot_case_id)
        if not source_case or source_case.get("case_type") != "elder_reboot":
            return
        self.storage.update_case_fields(
            reboot_case_id,
            {
                "payload_json": self._merge_case_payload(
                    source_case,
                    {
                        "new_council_election_started_case_id": election_case_id,
                    },
                )
            },
        )

    def _resolve_reboot_source_case_id(self, source_case_id: int) -> int:
        if source_case_id <= 0:
            return 0
        source_case = self.storage.get_case(source_case_id)
        if not source_case:
            return 0
        if source_case.get("case_type") == "elder_reboot":
            return source_case_id
        payload = source_case.get("payload") or {}
        if not isinstance(payload, dict):
            return 0
        try:
            reboot_source_case_id = int(payload.get("reboot_source_case_id") or 0)
        except Exception:
            reboot_source_case_id = 0
        return reboot_source_case_id if reboot_source_case_id > 0 else 0

    def _reboot_source_case_id(self, case: Dict[str, object]) -> int:
        if str(case.get("case_type") or "") == "elder_reboot":
            return int(case.get("case_id") or 0)
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return 0
        try:
            reboot_source_case_id = int(payload.get("reboot_source_case_id") or 0)
        except Exception:
            reboot_source_case_id = 0
        return reboot_source_case_id if reboot_source_case_id > 0 else 0

    def _record_reboot_election_failure(self, *, reboot_case_id: int, election_case_id: int, reason: str) -> Dict[str, object]:
        reboot_case = self.storage.get_case(reboot_case_id)
        if not reboot_case or reboot_case.get("case_type") != "elder_reboot":
            return {"failed_rounds": 0, "temporary_collective_supervision_active": False}
        current_failures = self._case_payload_int(reboot_case, "new_council_failed_election_rounds") + 1
        patch = {
            "new_council_failed_election_rounds": current_failures,
            "last_failed_election_case_id": election_case_id,
            "last_failed_election_reason": reason,
            "restoration_state": "pending_new_council",
        }
        if current_failures >= self._reboot_temporary_collective_supervision_failures():
            patch.update(
                {
                    "temporary_collective_supervision_active": True,
                    "temporary_collective_supervision_started_at": datetime.now().isoformat(),
                    "interim_supervision_active": False,
                    "interim_supervision_mode": "all_voters_temporary_review",
                    "interim_supervision_scope": "新元老会连续两次流产后，由全体表决权成员临时行使监督与复核权。",
                }
            )
        self.storage.update_case_fields(
            reboot_case_id,
            {
                "payload_json": self._merge_case_payload(
                    reboot_case,
                    patch,
                )
            },
        )
        return {
            "failed_rounds": current_failures,
            "temporary_collective_supervision_active": current_failures >= self._reboot_temporary_collective_supervision_failures(),
        }

    def _mark_reboot_council_restored(
        self,
        *,
        reboot_case_id: int,
        election_case_id: int,
        winner_member_ids: List[int],
    ) -> None:
        reboot_case = self.storage.get_case(reboot_case_id)
        if not reboot_case or reboot_case.get("case_type") != "elder_reboot":
            return
        self.storage.update_case_fields(
            reboot_case_id,
            {
                "payload_json": self._merge_case_payload(
                    reboot_case,
                    {
                        "new_council_restored_at": datetime.now().isoformat(),
                        "new_council_restored_by_case_id": election_case_id,
                        "new_council_member_ids": winner_member_ids,
                        "interim_supervision_active": False,
                        "temporary_collective_supervision_active": False,
                        "restoration_state": "new_council_restored",
                    },
                )
            },
        )

    def _build_case_ballot(self, case: Dict[str, object]) -> Dict[str, object]:
        if case["case_type"] == "ordinary_proposal":
            return {
                "options": ["赞成", "反对", "弃权"],
                "max_selections": 1,
            }
        if case["case_type"] == "honor_owner_election":
            candidate_ids = self._case_ballot_candidate_ids(case)
            if case["status"] == "runoff_voting":
                return {
                    "options": [self._format_user(candidate_id) for candidate_id in candidate_ids],
                    "max_selections": 1,
                }
            if len(candidate_ids) <= 1:
                return {
                    "options": ["同意", "反对"],
                    "max_selections": 1,
                }
            return {
                "options": [self._format_user(candidate_id) for candidate_id in candidate_ids],
                "max_selections": 1,
            }
        if case["case_type"] == "elder_election":
            candidate_ids = self._case_ballot_candidate_ids(case)
            seat_count = self._elder_case_current_round_seat_count(case)
            return {
                "options": [self._format_user(candidate_id) for candidate_id in candidate_ids],
                "max_selections": max(1, min(seat_count, len(candidate_ids))),
            }
        return {
            "options": ["同意", "反对"],
            "max_selections": 1,
        }

    @staticmethod
    def _parse_vote_choices(*, raw_text: str, option_count: int, max_selections: int) -> List[int]:
        tokens = [token for token in re.split(r"[\s,，]+", raw_text.strip()) if token]
        if not tokens:
            return []
        choices: List[int] = []
        for token in tokens:
            if not token.isdigit():
                return []
            choice = int(token)
            if choice < 1 or choice > option_count:
                return []
            if choice not in choices:
                choices.append(choice)
        if not choices or len(choices) > max_selections:
            return []
        return sorted(choices)

    def _format_ballot_acknowledgement(self, user_id: int, options: List[str], choices: List[int]) -> str:
        if len(choices) == 1:
            return f"{self._format_user(user_id)} 已完成表态：{options[choices[0] - 1]}。"
        selected_labels = "、".join(options[choice - 1] for choice in choices)
        return f"{self._format_user(user_id)} 已完成表态：{selected_labels}。"

    def _case_payload_datetime(self, case: Dict[str, object], key: str) -> Optional[datetime]:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        return self._parse_datetime(payload.get(key))

    @staticmethod
    def _case_payload_int(case: Dict[str, object], key: str) -> int:
        payload = case.get("payload") or {}
        if not isinstance(payload, dict):
            return 0
        try:
            return int(payload.get(key) or 0)
        except Exception:
            return 0

    @staticmethod
    def _format_remaining_time(deadline: datetime) -> str:
        remaining_seconds = max(int((deadline - datetime.now()).total_seconds()), 0)
        hours, rem = divmod(remaining_seconds, 3600)
        minutes = max(rem // 60, 0)
        if hours > 0:
            return f"{hours} 小时 {minutes} 分钟"
        return f"{max(minutes, 1)} 分钟"

    def _reboot_support_threshold(self) -> int:
        fixed_floor = self._config_int("governance_reboot_supporters", 7)
        ratio_floor = math.ceil(self.storage.member_count() * 0.2)
        return max(1, fixed_floor, ratio_floor)

    def _reboot_temporary_collective_supervision_failures(self) -> int:
        return self._REBOOT_TEMPORARY_COLLECTIVE_SUPERVISION_FAILURES

    def _evaluate_vote_result(
        self,
        *,
        case_type: str,
        yes_votes: int,
        no_votes: int,
        member_count: int,
        turnout: Optional[int] = None,
    ) -> tuple[bool, List[str]]:
        turnout = int(turnout if turnout is not None else yes_votes + no_votes)
        threshold_ref = self._CASE_THRESHOLD_REFS.get(case_type)
        threshold_spec = ((load_law_spec().get("threshold_sets") or {}).get(threshold_ref or "")) if threshold_ref else None
        if not isinstance(threshold_spec, dict):
            return yes_votes > no_votes and yes_votes > 0, []

        lines: List[str] = []
        turnout_floor = self._ceil_ratio(member_count, threshold_spec.get("turnout_min_of_all_voting_members"))
        if turnout_floor > 0:
            lines.append(f"参与门槛：有效投票不少于 {turnout_floor} 票")
        if turnout < turnout_floor:
            lines.append(f"本次有效投票：{turnout} 票，未达到参与门槛")
            return False, lines

        approval_spec = threshold_spec.get("approval") or {}
        approval_type = str(approval_spec.get("type") or "").strip()
        if approval_type == "approve_gt_reject":
            approve_floor = self._ceil_ratio(turnout, approval_spec.get("approve_min_of_turnout"))
            lines.append(f"通过条件：赞成票多于反对票，且不少于有效投票的 {approval_spec.get('approve_min_of_turnout')}")
            return yes_votes > no_votes and yes_votes >= approve_floor, lines
        if approval_type == "approve_gte_effective_votes_2_over_3":
            super_majority_floor = self._ceil_ratio(turnout, Fraction(2, 3))
            approve_floor = self._ceil_ratio(turnout, approval_spec.get("approve_min_of_turnout"))
            lines.append(
                f"通过条件：赞成票不少于 {super_majority_floor} 票，且不少于有效投票的 {approval_spec.get('approve_min_of_turnout')}"
            )
            return yes_votes >= super_majority_floor and yes_votes >= approve_floor, lines

        return yes_votes > no_votes and yes_votes > 0, lines

    @staticmethod
    def _ceil_ratio(base: int, ratio: object) -> int:
        if base <= 0:
            return 0
        return int(math.ceil(base * GovernanceManager._parse_ratio(ratio)))

    @staticmethod
    def _parse_ratio(value: object) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        try:
            return float(Fraction(raw))
        except Exception:
            try:
                return float(raw)
            except Exception:
                return 0.0

    def _find_active_emergency_case_id(self, target_user_id: int) -> Optional[int]:
        case = self._get_active_emergency_case(target_user_id)
        return int(case["case_id"]) if case else None

    def _get_active_emergency_case(self, target_user_id: int) -> Optional[Dict[str, object]]:
        return self.storage.fetchone(
            """
            SELECT case_id, case_type, title, description, proposer_id, target_user_id,
                status, phase, support_threshold, vote_duration_seconds, payload_json,
                cooldown_until, vote_started_at, vote_ends_at, resolved_at, created_at, updated_at
            FROM governance_cases
            WHERE case_type = 'emergency_protection'
                AND target_user_id = ?
                AND status = 'active'
            ORDER BY case_id DESC
            LIMIT 1
        """,
            (target_user_id,),
        )

    def _can_execute_governance_ban(self, *, actor_user_id: int, target_user_id: int) -> tuple[bool, Optional[int], str]:
        if self.storage.has_active_lock(lock_type="ban_global"):
            return False, None, "当前存在重组元老会程序，禁言权力已被冻结。"
        emergency_case = self._get_active_emergency_case(target_user_id)
        honor_owner_ok, honor_owner_reason = self._ensure_honor_owner_execution_authority(
            actor_user_id,
            action_label="执行治理禁言",
            allow_caretaker=True,
        )
        if honor_owner_ok:
            if emergency_case and str((emergency_case.get("payload") or {}).get("executed_measure_type") or "").strip():
                return False, None, "该紧急防护案件已执行过临时措施，请先推进案件。"
            return True, int(emergency_case["case_id"]) if emergency_case else None, ""
        elder_ok, elder_reason = self._ensure_elder_supervision_authority(
            actor_user_id,
            action_label="执行治理禁言",
        )
        if not elder_ok:
            return False, None, honor_owner_reason or elder_reason or "只有荣誉群主或元老会紧急代理成员可执行治理禁言。"
        if not emergency_case:
            return False, None, "当前没有针对该成员生效的紧急防护案件。"
        if str((emergency_case.get("payload") or {}).get("executed_measure_type") or "").strip():
            return False, None, "该紧急防护案件已执行过临时措施，请先推进案件。"
        proxy_ready, denied_reason = self._can_use_emergency_proxy(case=emergency_case)
        if not proxy_ready:
            return False, None, denied_reason
        return True, int(emergency_case["case_id"]), ""

    def _can_execute_governance_kick(self, *, actor_user_id: int, target_user_id: int) -> tuple[bool, Optional[int], str]:
        emergency_case = self._get_active_emergency_case(target_user_id)
        honor_owner_ok, honor_owner_reason = self._ensure_honor_owner_execution_authority(
            actor_user_id,
            action_label="执行治理放逐",
        )
        if honor_owner_ok:
            if emergency_case and str((emergency_case.get("payload") or {}).get("executed_measure_type") or "").strip():
                return False, None, "该紧急防护案件已执行过临时措施，请先推进案件。"
            return True, int(emergency_case["case_id"]) if emergency_case else None, ""
        elder_ok, elder_reason = self._ensure_elder_supervision_authority(
            actor_user_id,
            action_label="执行治理放逐",
        )
        if not elder_ok:
            return False, None, honor_owner_reason or elder_reason or "只有荣誉群主或元老会紧急代理成员可执行治理放逐。"
        if not emergency_case:
            return False, None, "当前没有针对该成员生效的紧急防护案件。"
        if str((emergency_case.get("payload") or {}).get("executed_measure_type") or "").strip():
            return False, None, "该紧急防护案件已执行过临时措施，请先推进案件。"
        proxy_ready, denied_reason = self._can_use_emergency_proxy(case=emergency_case)
        if not proxy_ready:
            return False, None, denied_reason
        return True, int(emergency_case["case_id"]), ""

    def _can_use_emergency_proxy(self, *, case: Dict[str, object]) -> tuple[bool, str]:
        honor_owner_id = self.storage.get_active_role_user("honor_owner")
        if not honor_owner_id:
            return True, ""
        response_due_at = self._case_payload_datetime(case, "response_due_at")
        if response_due_at and datetime.now() < response_due_at:
            return False, f"当前仍在荣誉群主响应期，约剩余 {self._format_remaining_time(response_due_at)}。"
        return True, ""

    def _has_bootstrap_override_authority(
        self,
        *,
        user_id: int,
        event: Optional[GroupMessageEvent] = None,
    ) -> bool:
        if self.storage.get_active_role_user("honor_owner") == user_id:
            return True
        return self._has_platform_custodian_authority(user_id=user_id, event=event)

    def _has_platform_custodian_authority(
        self,
        *,
        user_id: int,
        event: Optional[GroupMessageEvent] = None,
    ) -> bool:
        role_code = str(getattr(getattr(event, "sender", None), "role", None) or "").strip().lower()
        if role_code not in {"admin", "owner"}:
            profile = self.storage.get_member_profile(user_id)
            role_code = str((profile or {}).get("role_code") or "").strip().lower()
        return role_code in {"admin", "owner"} and user_id != self.group.self_id

    def _ensure_honor_owner_execution_authority(
        self,
        user_id: int,
        *,
        action_label: str,
        allow_caretaker: bool = False,
    ) -> tuple[bool, str]:
        if self.storage.get_active_role_user("honor_owner") != user_id:
            return False, f"只有荣誉群主可以{action_label}。"
        if self.storage.has_active_lock(lock_type="honor_owner_powers", target_user_id=user_id):
            return False, f"当前荣誉群主权力已被冻结，不能{action_label}。"
        term_state = self._ensure_honor_owner_term_runtime_state()
        if bool(term_state.get("caretaker_active")) and not allow_caretaker:
            return False, f"当前荣誉群主任期已届满，正处于看守期，只能处理日常事务和紧急安全事项，不能{action_label}。"
        return True, ""

    def _ensure_elder_supervision_authority(self, user_id: int, *, action_label: str) -> tuple[bool, str]:
        if not self.storage.has_role(user_id, "elder"):
            return False, f"只有元老会成员可以{action_label}。"
        if self.storage.has_active_lock(lock_type="elder_powers", target_user_id=user_id):
            return False, f"当前元老职权已被冻结，不能{action_label}。"
        return True, ""

    def _format_honor_owner_status_lines(self, *, honor_owner_id: Optional[int]) -> List[str]:
        lines: List[str] = []
        if honor_owner_id:
            term_state = self._ensure_honor_owner_term_runtime_state()
            term_expires_at = term_state.get("term_expires_at")
            if isinstance(term_expires_at, datetime):
                if datetime.now() <= term_expires_at:
                    lines.append(f"- 荣誉群主任期：至 {term_expires_at.strftime('%Y-%m-%d %H:%M')}")
                else:
                    lines.append(f"- 荣誉群主任期：已于 {term_expires_at.strftime('%Y-%m-%d %H:%M')} 届满")
            caretaker_deadline_at = term_state.get("caretaker_deadline_at")
            if bool(term_state.get("caretaker_active")) and isinstance(caretaker_deadline_at, datetime):
                lines.append(f"- 荣誉群主看守期：至 {caretaker_deadline_at.strftime('%Y-%m-%d %H:%M')}")
                lines.append(f"- 看守权限：{self._HONOR_OWNER_CARETAKER_SCOPE}")
                by_election_case_id = int(term_state.get("caretaker_by_election_case_id") or 0)
                if by_election_case_id > 0:
                    lines.append(f"- 看守补选：案件 #{by_election_case_id} 已开启")
            last_summary_at = term_state.get("last_governance_summary_at")
            if isinstance(last_summary_at, datetime):
                lines.append(f"- 最近治理摘要：{last_summary_at.strftime('%Y-%m-%d %H:%M')}")
            return lines
        vacancy_case = self._active_honor_owner_vacancy_case()
        if not vacancy_case:
            return lines
        payload = vacancy_case.get("payload") or {}
        vacancy_announced_at = self._case_payload_datetime(vacancy_case, "vacancy_announced_at")
        if vacancy_announced_at:
            lines.append(f"- 荣誉群主空缺：已于 {vacancy_announced_at.strftime('%Y-%m-%d %H:%M')} 公告补选")
        if str(payload.get("temporary_proxy_status") or "").strip() == "pending_elder_designation":
            lines.append("- 临时程序代理：待元老会指定 1 名元老处理必要事务")
        elif str(payload.get("temporary_proxy_status") or "").strip() == "elder_designated_proxy":
            temporary_proxy_user_id = int(payload.get("temporary_proxy_user_id") or 0)
            temporary_proxy_expires_at = self._case_payload_datetime(vacancy_case, "temporary_proxy_expires_at")
            if temporary_proxy_user_id > 0:
                line = f"- 临时程序代理：{self._format_user(temporary_proxy_user_id)}"
                if temporary_proxy_expires_at:
                    line += f"（至 {temporary_proxy_expires_at.strftime('%Y-%m-%d %H:%M')}）"
                lines.append(line)
        autonomy_deadline = self._case_payload_datetime(vacancy_case, "temporary_autonomy_restart_deadline_at")
        if autonomy_deadline:
            lines.append(f"- 机器人临时自治：至 {autonomy_deadline.strftime('%Y-%m-%d %H:%M')}，范围仅限日常秩序与紧急安全")
        if str(payload.get("dispute_resolution_channel") or "").strip() == "full_voting_members":
            lines.append("- 争议处理：涉及荣誉群主职权的争议，直接提交全体表决权成员表决")
        return lines

    def _format_honor_owner_nomination_feedback(self, *, case_id: int, update: Dict[str, object]) -> str:
        target_user_id = int(update.get("target_user_id") or 0)
        supporter_count = int(update.get("supporter_count") or 0)
        supporter_threshold = int(update.get("supporter_threshold") or 0)
        candidate_label = self._format_user(target_user_id)
        lines: List[str] = []
        if bool(update.get("qualified")):
            lines.append(f"已将 {candidate_label} 录入荣誉群主选举案件 #{case_id}。")
            if bool(update.get("is_self_nomination")):
                lines.append("- 提名方式：候选人自荐，已视为确认愿意履职并接受监督。")
            else:
                lines.append(f"- 联名推荐：{supporter_count}/{supporter_threshold}，候选人已确认愿意履职并接受监督。")
            if bool(update.get("candidate_is_elder")):
                lines.append("- 该候选人当前兼任元老；若当选，将自动解除其元老身份。")
        else:
            if bool(update.get("support_added")):
                lines.append(f"已登记对 {candidate_label} 的联名推荐：{supporter_count}/{supporter_threshold}。")
            else:
                lines.append(f"{candidate_label} 的联名推荐已记录：{supporter_count}/{supporter_threshold}。")
            if bool(update.get("pending_self_confirmation")):
                lines.append("- 联名已达法定门槛，待候选人本人执行“发起荣誉群主选举 @自己 理由”确认愿意履职并接受监督。")
            else:
                lines.append("- 候选人本人仍需确认愿意履职并接受监督；联名达到门槛后才会进入候选名单。")
        lines.append(f"- 当前候选人数：{int(update.get('candidate_count') or 0)}")
        pending_nomination_count = int(update.get("pending_nomination_count") or 0)
        if pending_nomination_count > 0:
            lines.append(f"- 当前另有待确认提名：{pending_nomination_count} 项")
        lines.append(f"- 当前仍处于提名公示期，期满后请使用“推进治理案件 {case_id}”进入陈述与质询期。")
        return "\n".join(lines)

    def _current_voting_member_count(self) -> int:
        self._release_expired_formal_discipline_locks()
        restricted_ids = set(self.storage.get_active_role_users("suspended"))
        for lock in self.storage.list_active_locks():
            if str(lock.get("lock_type") or "").strip() != "formal_discipline_restrict_vote":
                continue
            try:
                target_user_id = int(lock.get("target_user_id") or 0)
            except Exception:
                target_user_id = 0
            if target_user_id > 0:
                restricted_ids.add(target_user_id)
        return max(self.storage.member_count() - len(restricted_ids), 1)

    def _honor_owner_nomination_support_threshold(self) -> int:
        voting_member_count = self._current_voting_member_count()
        return max(
            self._HONOR_OWNER_RECOMMENDATION_FIXED_SUPPORTERS,
            self._ceil_ratio(voting_member_count, self._HONOR_OWNER_RECOMMENDATION_RATIO),
        )

    def _honor_owner_candidate_min_join_days(self) -> int:
        return self._HONOR_OWNER_CANDIDATE_MIN_JOIN_DAYS

    def _honor_owner_term_days(self) -> int:
        return self._HONOR_OWNER_TERM_DAYS

    def _honor_owner_temporary_autonomy_restart_hours(self) -> int:
        return self._HONOR_OWNER_TEMPORARY_AUTONOMY_RESTART_HOURS

    def _ensure_honor_owner_term_runtime_state(self) -> Dict[str, object]:
        honor_owner_id = self.storage.get_active_role_user("honor_owner")
        status: Dict[str, object] = {
            "honor_owner_id": honor_owner_id,
            "caretaker_active": False,
            "caretaker_by_election_case_id": 0,
        }
        if not honor_owner_id:
            return status
        term_case = self._latest_honor_owner_term_case(honor_owner_id)
        if not term_case:
            return status
        status["term_case_id"] = int(term_case["case_id"])
        term_expires_at = self._case_payload_datetime(term_case, "term_expires_at")
        if term_expires_at is None:
            return status
        status["term_expires_at"] = term_expires_at
        last_summary_at = self._case_payload_datetime(term_case, "last_governance_summary_at")
        if last_summary_at is not None:
            status["last_governance_summary_at"] = last_summary_at
        if datetime.now() <= term_expires_at:
            return status
        caretaker_started_at = self._case_payload_datetime(term_case, "caretaker_started_at") or term_expires_at
        caretaker_deadline_at = self._case_payload_datetime(term_case, "caretaker_deadline_at") or (
            term_expires_at + timedelta(days=self._HONOR_OWNER_CARETAKER_MAX_DAYS)
        )
        open_case = self.storage.find_open_case_by_type("honor_owner_election")
        by_election_case_id = int(open_case["case_id"]) if open_case else self._ensure_honor_owner_by_election_case(
            operator_id=int(honor_owner_id),
            source_case_id=int(term_case["case_id"]),
            reopen_reason="荣誉群主任期届满，进入看守期并启动补选。",
        )
        payload_patch = {
            "caretaker_started_at": caretaker_started_at.isoformat(),
            "caretaker_deadline_at": caretaker_deadline_at.isoformat(),
            "caretaker_scope": self._HONOR_OWNER_CARETAKER_SCOPE,
            "caretaker_by_election_case_id": by_election_case_id,
        }
        current_payload = term_case.get("payload") or {}
        if any(current_payload.get(key) != value for key, value in payload_patch.items()):
            self.storage.update_case_fields(
                int(term_case["case_id"]),
                {
                    "payload_json": self._merge_case_payload(term_case, payload_patch),
                },
            )
        status.update(
            {
                "caretaker_active": True,
                "caretaker_started_at": caretaker_started_at,
                "caretaker_deadline_at": caretaker_deadline_at,
                "caretaker_by_election_case_id": by_election_case_id,
            }
        )
        return status

    def _elder_current_member_count(self) -> int:
        return len(self.storage.get_active_role_users("elder"))

    def _elder_meeting_quorum_threshold(self) -> int:
        elder_count = self._elder_current_member_count()
        if elder_count <= 0:
            return 0
        return max(elder_count // 2 + 1, 2)

    def _elder_majority_threshold(self) -> int:
        quorum_threshold = self._elder_meeting_quorum_threshold()
        if quorum_threshold <= 0:
            return 0
        return quorum_threshold // 2 + 1

    def _elder_special_decision_threshold(self) -> int:
        elder_count = self._elder_current_member_count()
        if elder_count <= 0:
            return 0
        return max(self._ceil_ratio(elder_count, Fraction(2, 3)), 2)

    def _elder_nomination_publicity_hours(self) -> int:
        return max(self._config_int("governance_nomination_publicity_hours", 24), 24)

    def _elder_candidate_min_join_days(self) -> int:
        return self._ELDER_CANDIDATE_MIN_JOIN_DAYS

    def _elder_term_days(self) -> int:
        return self._ELDER_TERM_DAYS

    def _latest_honor_owner_term_case(self, honor_owner_id: int) -> Optional[Dict[str, object]]:
        rows = self.storage.fetchall(
            """
            SELECT case_id, case_type, title, description, proposer_id, target_user_id,
                status, phase, support_threshold, vote_duration_seconds, payload_json,
                cooldown_until, vote_started_at, vote_ends_at, resolved_at, created_at, updated_at
            FROM governance_cases
            WHERE case_type = 'honor_owner_election'
            ORDER BY case_id DESC
            LIMIT 20
        """
        )
        for row in rows:
            payload = row.get("payload") or {}
            try:
                winner_member_id = int(payload.get("winner_member_id") or 0)
            except Exception:
                winner_member_id = 0
            if winner_member_id == honor_owner_id:
                return row
        return None

    def _active_honor_owner_vacancy_case(self) -> Optional[Dict[str, object]]:
        open_case = self.storage.find_open_case_by_type("honor_owner_election")
        if not open_case:
            return None
        case = self.storage.get_case(int(open_case["case_id"]))
        if case is None:
            return None
        payload = case.get("payload") or {}
        if not isinstance(payload, dict) or not payload.get("vacancy_announced_at"):
            return None
        return case

    def _find_active_vacancy_dispute_case(self, vacancy_case_id: int) -> Optional[Dict[str, object]]:
        for listed_case in self.storage.list_active_cases(limit=64):
            if str(listed_case.get("case_type") or "") != "ordinary_proposal":
                continue
            payload = listed_case.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if not bool(payload.get("direct_collective_dispute_vote")):
                continue
            if int(payload.get("vacancy_case_id") or 0) != int(vacancy_case_id):
                continue
            return self.storage.get_case(int(listed_case["case_id"])) or listed_case
        return None

    def _elder_impeachment_vacancy_progress(self) -> tuple[int, int]:
        anchor = self.storage.fetchone(
            """
            SELECT case_type, resolved_at, payload_json
            FROM governance_cases
            WHERE case_type IN ('elder_reboot', 'elder_election')
                AND status = 'approved'
            ORDER BY case_id DESC
            LIMIT 1
        """
        )
        anchor_time = self._parse_datetime((anchor or {}).get("resolved_at"))
        rows = self.storage.fetchall(
            """
            SELECT target_user_id, resolved_at
            FROM governance_cases
            WHERE case_type = 'elder_impeachment'
                AND status = 'approved'
            ORDER BY case_id DESC
        """
        )
        vacancy_targets: List[int] = []
        for row in rows:
            resolved_at = self._parse_datetime(row.get("resolved_at"))
            if anchor_time and resolved_at and resolved_at < anchor_time:
                continue
            try:
                target_user_id = int(row.get("target_user_id") or 0)
            except Exception:
                target_user_id = 0
            if target_user_id > 0 and target_user_id not in vacancy_targets:
                vacancy_targets.append(target_user_id)
        return len(vacancy_targets), self._desired_elder_seat_count()

    def _member_joined_at(self, user_id: int) -> Optional[datetime]:
        profile = self.storage.get_member_profile(user_id)
        if not profile:
            return None
        raw_join_time = profile.get("join_time")
        if raw_join_time in {None, ""}:
            return None
        if isinstance(raw_join_time, (int, float)):
            try:
                return datetime.fromtimestamp(int(raw_join_time))
            except Exception:
                return None
        text = str(raw_join_time).strip()
        if not text:
            return None
        if text.isdigit():
            try:
                return datetime.fromtimestamp(int(text))
            except Exception:
                return None
        return self._parse_datetime(text)

    def _case_supporter_ids(self, case_id: int) -> List[int]:
        rows = self.storage.fetchall(
            """
            SELECT user_id
            FROM governance_case_supporters
            WHERE case_id = ?
            ORDER BY user_id
        """,
            (case_id,),
        )
        supporter_ids: List[int] = []
        for row in rows:
            try:
                supporter_id = int(row.get("user_id") or 0)
            except Exception:
                continue
            if supporter_id > 0 and supporter_id not in supporter_ids:
                supporter_ids.append(supporter_id)
        return supporter_ids

    def _record_elder_council_resolution(
        self,
        *,
        case_id: int,
        proposer_id: int,
        decision_kind: str,
        reason: str,
        supporter_ids: List[int],
    ) -> None:
        special_decisions = {"start_honor_owner_impeachment", "extend_emergency_proxy", "high_risk_procedure"}
        elder_count = self._elder_current_member_count()
        quorum_threshold = self._elder_meeting_quorum_threshold()
        required_support = (
            self._elder_special_decision_threshold()
            if decision_kind in special_decisions
            else self._elder_majority_threshold()
        )
        actual_support = len(supporter_ids)
        self.metadata.record_audit_event(
            actor_id=proposer_id,
            action="elder_council_resolution_recorded",
            subject_type="governance_case",
            subject_id=str(case_id),
            session_key=None,
            result="passed" if actual_support >= max(quorum_threshold, required_support) else "rejected",
            context={
                "decision_kind": decision_kind,
                "reason": reason,
                "active_elder_count": elder_count,
                "quorum_threshold": quorum_threshold,
                "required_support": required_support,
                "actual_support": actual_support,
                "supporter_ids": supporter_ids,
            },
        )

    def _record_elder_council_timeout(
        self,
        *,
        case_id: int,
        actor_id: int,
        request_kind: str,
        due_at: datetime,
        fallback_stage: str,
        acting_stage: str = "",
    ) -> None:
        self.metadata.record_audit_event(
            actor_id=actor_id,
            action="elder_council_review_timeout",
            subject_type="governance_case",
            subject_id=str(case_id),
            session_key=None,
            result="recorded",
            context={
                "request_kind": request_kind,
                "due_at": due_at.isoformat(),
                "active_elder_count": self._elder_current_member_count(),
                "fallback_stage": fallback_stage,
                "acting_stage": acting_stage or "bot",
                "fallback_order": ["bot", "other_unrecused_elders", "honor_owner", "any_two_voting_members"],
            },
        )

    def _timeout_fallback_stage_for_actor(self, actor_user_id: int) -> str:
        if actor_user_id and int(actor_user_id) == int(getattr(self.group, "self_id", 0) or 0):
            return "bot"
        if actor_user_id and int(actor_user_id) == int(self.storage.get_active_role_user("honor_owner") or 0):
            return "honor_owner"
        if actor_user_id and self.storage.has_role(int(actor_user_id), "elder"):
            return "other_unrecused_elders"
        return "any_two_voting_members"

    @staticmethod
    def _timeout_fallback_stage_label(stage: str) -> str:
        labels = {
            "bot": "机器人自动转接",
            "other_unrecused_elders": "其他未回避元老",
            "honor_owner": "荣誉群主",
            "any_two_voting_members": "任意两名表决权成员联署触发",
        }
        return labels.get(stage, stage or "机器人自动转接")

    def _build_timeout_fallback_payload(
        self,
        *,
        request_kind: str,
        due_at: datetime,
        fallback_stage: str,
        actor_user_id: int,
        recorded_at: datetime,
        supporter_ids: Optional[List[int]] = None,
        support_threshold: int = 0,
    ) -> Dict[str, object]:
        payload = {
            "timeout_recorded_at": recorded_at.isoformat(),
            "timeout_at": recorded_at.isoformat(),
            "timeout_request_kind": request_kind,
            "timeout_due_at": due_at.isoformat(),
            "timeout_fallback_stage": fallback_stage,
            "timeout_fallback_actor_stage": self._timeout_fallback_stage_for_actor(actor_user_id),
            "timeout_fallback_order": ["bot", "other_unrecused_elders", "honor_owner", "any_two_voting_members"],
            "timeout_pending_request_kind": "",
            "timeout_pending_due_at": "",
            "timeout_pending_supporter_ids": [],
            "timeout_pending_support_threshold": 0,
        }
        if supporter_ids:
            payload["timeout_fallback_supporter_ids"] = [int(user_id) for user_id in supporter_ids if int(user_id) > 0]
        if support_threshold > 0:
            payload["timeout_fallback_support_threshold"] = int(support_threshold)
        return payload

    @staticmethod
    def _timeout_request_label(request_kind: str) -> str:
        labels = {
            "proposal_procedural_review": "提案程序审查",
            "formal_discipline_acceptance_review": "正式处分受理审查",
            "formal_discipline_review_start_check": "处分复核启动审查",
        }
        return labels.get(request_kind, request_kind or "程序审查")

    def _format_timeout_pending_support(self, payload: Dict[str, object]) -> str:
        if not isinstance(payload, dict):
            return ""
        supporter_ids = [int(user_id) for user_id in (payload.get("timeout_pending_supporter_ids") or []) if int(user_id) > 0]
        threshold = int(payload.get("timeout_pending_support_threshold") or 0)
        if threshold <= 0 or not supporter_ids:
            return ""
        return f"超时承接：{len(supporter_ids)}/{threshold}"

    async def _resolve_timeout_fallback_transition(
        self,
        *,
        case: Dict[str, object],
        event: GroupMessageEvent,
        request_kind: str,
        due_at: datetime,
        fallback_stage: str,
    ) -> tuple[bool, Dict[str, object], str]:
        actor_user_id = int(getattr(event, "user_id", 0) or 0)
        actor_stage = self._timeout_fallback_stage_for_actor(actor_user_id)
        case_id = int(case["case_id"])
        if actor_stage == "bot":
            return (
                True,
                self._build_timeout_fallback_payload(
                    request_kind=request_kind,
                    due_at=due_at,
                    fallback_stage=fallback_stage,
                    actor_user_id=actor_user_id,
                    recorded_at=datetime.now(),
                ),
                "",
            )
        if actor_stage == "other_unrecused_elders":
            can_advance, denied_reason = self._ensure_elder_supervision_authority(
                actor_user_id,
                action_label=f"承接{self._timeout_request_label(request_kind)}超时程序",
            )
            if not can_advance:
                return False, {}, denied_reason
            return (
                True,
                self._build_timeout_fallback_payload(
                    request_kind=request_kind,
                    due_at=due_at,
                    fallback_stage=fallback_stage,
                    actor_user_id=actor_user_id,
                    recorded_at=datetime.now(),
                ),
                "",
            )
        active_elder_ids = self.storage.get_active_role_users("elder")
        if actor_stage == "honor_owner":
            if active_elder_ids:
                return False, {}, f"案件 #{case_id} 当前仍应先由其他未回避元老承接该超时程序。"
            honor_owner_id = int(self.storage.get_active_role_user("honor_owner") or 0)
            if honor_owner_id <= 0 or honor_owner_id != actor_user_id:
                return False, {}, "当前荣誉群主身份无效，不能承接该超时程序。"
            if self.storage.has_active_lock(lock_type="honor_owner_powers", target_user_id=actor_user_id):
                return False, {}, "当前荣誉群主职权已被冻结，不能承接该超时程序。"
            return (
                True,
                self._build_timeout_fallback_payload(
                    request_kind=request_kind,
                    due_at=due_at,
                    fallback_stage=fallback_stage,
                    actor_user_id=actor_user_id,
                    recorded_at=datetime.now(),
                ),
                "",
            )
        if active_elder_ids:
            return False, {}, f"案件 #{case_id} 当前仍应先由其他未回避元老承接该超时程序。"
        honor_owner_id = int(self.storage.get_active_role_user("honor_owner") or 0)
        if honor_owner_id > 0 and not self.storage.has_active_lock(lock_type="honor_owner_powers", target_user_id=honor_owner_id):
            return False, {}, f"案件 #{case_id} 当前仍应先由荣誉群主承接该超时程序。"
        can_vote, denied_reason = await self._ensure_governance_vote_participant(actor_user_id)
        if not can_vote:
            return False, {}, denied_reason
        payload = case.get("payload") or {}
        supporter_ids: List[int] = []
        if (
            str(payload.get("timeout_pending_request_kind") or "").strip() == request_kind
            and str(payload.get("timeout_pending_due_at") or "").strip() == due_at.isoformat()
        ):
            supporter_ids = [int(user_id) for user_id in (payload.get("timeout_pending_supporter_ids") or []) if int(user_id) > 0]
        if actor_user_id not in supporter_ids:
            supporter_ids.append(actor_user_id)
        threshold = 2
        if len(supporter_ids) < threshold:
            self.storage.update_case_fields(
                case_id,
                {
                    "payload_json": self._merge_case_payload(
                        case,
                        {
                            "timeout_pending_request_kind": request_kind,
                            "timeout_pending_due_at": due_at.isoformat(),
                            "timeout_pending_supporter_ids": supporter_ids,
                            "timeout_pending_support_threshold": threshold,
                            "timeout_pending_recorded_at": datetime.now().isoformat(),
                        },
                    )
                },
            )
            return (
                False,
                {},
                f"案件 #{case_id} 的{self._timeout_request_label(request_kind)}已超时。\n"
                f"- 当前无机器人、元老或荣誉群主承接。\n"
                f"- 已登记任意两名表决权成员联署触发：{len(supporter_ids)}/{threshold}\n"
                f"- 请另一名表决权成员再执行“推进治理案件 {case_id}”。",
            )
        return (
            True,
            self._build_timeout_fallback_payload(
                request_kind=request_kind,
                due_at=due_at,
                fallback_stage=fallback_stage,
                actor_user_id=actor_user_id,
                recorded_at=datetime.now(),
                supporter_ids=supporter_ids,
                support_threshold=threshold,
            ),
            "",
        )

    def _record_honor_owner_governance_summary_publication(self, *, actor_id: int, trigger: str) -> None:
        if self.storage.get_active_role_user("honor_owner") != actor_id:
            return
        term_case = self._latest_honor_owner_term_case(actor_id)
        if not term_case:
            return
        now = datetime.now()
        summary_ref = f"governance_status:{now.strftime('%Y%m%d%H%M%S')}"
        self.storage.update_case_fields(
            int(term_case["case_id"]),
            {
                "payload_json": self._merge_case_payload(
                    term_case,
                    {
                        "last_governance_summary_at": now.isoformat(),
                        "last_governance_summary_ref": summary_ref,
                        "last_governance_summary_actor_id": actor_id,
                        "last_governance_summary_trigger": trigger,
                    },
                )
            },
        )
        self.metadata.record_audit_event(
            actor_id=actor_id,
            action="honor_owner_governance_summary_published",
            subject_type="governance_case",
            subject_id=str(term_case["case_id"]),
            session_key=None,
            result="recorded",
            context={
                "trigger": trigger,
                "summary_ref": summary_ref,
            },
        )

    def _record_honor_owner_high_risk_action(
        self,
        *,
        actor_id: int,
        action_type: str,
        target_user_id: int,
        reason: str,
    ) -> None:
        term_state = self._ensure_honor_owner_term_runtime_state()
        self.metadata.record_audit_event(
            actor_id=actor_id,
            action="honor_owner_high_risk_action_recorded",
            subject_type="member",
            subject_id=str(target_user_id),
            session_key=None,
            result="recorded",
            context={
                "action_type": action_type,
                "reason": reason,
                "law_article": "第二十六条",
                "caretaker_active": bool(term_state.get("caretaker_active")),
            },
        )

    def _parse_target_argument(self, event: GroupMessageEvent, arg: Optional["Message"]) -> tuple[Optional[int], str]:
        raw_text = str(arg or "")
        plain_text = re.sub(r"\[CQ:at,qq=\d+]", "", self._plain_text(arg)).strip()
        match = re.search(r"\[CQ:at,qq=(\d+)]", raw_text)
        target_user_id = int(match.group(1)) if match else None
        if target_user_id is None:
            reply = getattr(event, "reply", None)
            sender = getattr(reply, "sender", None) if reply else None
            reply_user_id = getattr(sender, "user_id", None)
            if reply_user_id is not None:
                target_user_id = int(reply_user_id)
        return target_user_id, plain_text.strip()

    def _parse_case_id(self, arg: Optional["Message"]) -> Optional[int]:
        plain_text = self._plain_text(arg)
        token = plain_text.split()[0] if plain_text else ""
        return int(token) if token.isdigit() else None

    def _format_user(self, user_id: Optional[int]) -> str:
        if not user_id:
            return "-"
        profile = self.storage.get_member_profile(int(user_id))
        if profile:
            display_name = str(profile.get("card") or profile.get("nickname") or f"QQ:{user_id}")
            return f"{display_name}(QQ:{user_id})"
        return f"QQ:{user_id}"

    def _format_user_list(self, user_ids: List[int]) -> str:
        return "、".join(self._format_user(user_id) for user_id in user_ids)

    def _config_int(self, key: str, default: int) -> int:
        try:
            return int(self.service.get_config_value(key, default))
        except Exception:
            return int(default)

    def _config_float(self, key: str, default: float) -> float:
        try:
            return float(self.service.get_config_value(key, default))
        except Exception:
            return float(default)

    @staticmethod
    def _is_platform_admin(event: GroupMessageEvent) -> bool:
        role = getattr(getattr(event, "sender", None), "role", None)
        return str(role or "member").lower() in {"admin", "owner"}

    @staticmethod
    def _plain_text(arg: Optional["Message"]) -> str:
        if arg is None:
            return ""
        try:
            return str(arg.extract_plain_text() or "").strip()
        except Exception:
            return str(arg or "").strip()

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None


__all__ = [
    "GovernanceManager",
]
