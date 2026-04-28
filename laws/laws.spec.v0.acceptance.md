# `laws.spec.v0.yaml` 验收清单与覆盖矩阵

## 一、使用说明

本文件用于回答两个问题：

1. `laws/laws.spec.v0.yaml` 当前到底覆盖了哪些条文；
2. 哪些条文已经进入“可执行骨架”，哪些还只是部分进入，哪些尚未进入 spec。

说明：

- 本矩阵衡量的是 **spec 覆盖度**，不是运行时代码完成度。
- 运行时是否已落地，应另看 `side_effect_contracts.effects.*.binding_status`。
- 本矩阵以 `laws/laws.md` 为 source of truth，以当前 `laws/laws.spec.v0.yaml` `v0.2` 为核对对象。

状态定义：

| 状态 | 含义 |
| --- | --- |
| 已覆盖 | 已进入 spec 的可执行骨架：至少形成了明确的 `rule_atoms`、`workflow_fsm`、`threshold_sets`、`lock_types`、`workflow_dev_contracts` 或同等强度映射 |
| 部分覆盖 | 已进入 spec，但仍停留在 `sources`、局部门槛、局部工作流或部分 contract，尚未把条文全部拆成可执行骨架 |
| 尚未进入 spec | 当前没有明确的 article-level 落点；最多只有设计层或整体语义上的间接影响 |

## 二、汇总

| 状态 | 数量 |
| --- | --- |
| 已覆盖 | 71 |
| 部分覆盖 | 0 |
| 尚未进入 spec | 0 |

## 三、逐条覆盖矩阵

### 第一编　群规·总则

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第一条 | 群体性质 | 已覆盖 | `rule_atoms.art_01_group_commonwealth_nature`、`human_review_gates.gate_collective_sovereignty_boundary`、`invariants.inv_group_not_private_property` | 群体公共共同体性质、禁止私人/派系所有权主张、治理正当性源自成员授权与成员加入即接受规则已进入骨架 |
| 第二条 | 群成员主权 | 已覆盖 | `rule_atoms.art_02_collective_sovereignty`、`human_review_gates.gate_collective_sovereignty_boundary`、`invariants.inv_collective_sovereignty_over_office_and_technical_power` | 全体表决权成员的最高自治地位，以及职务、机构和技术权限不得超越群规的约束已进入骨架 |
| 第三条 | 规范层级 | 已覆盖 | `rule_atoms.art_03_norm_hierarchy`、`human_review_gates.gate_norm_conflict_core_guarantee` | 已形成规范层级与冲突审查入口 |
| 第四条 | 术语定义 | 已覆盖 | `functions.ceil_ratio`、`functions.voter_roster_snapshot`、`derived_statuses.voting_member`、`derived_statuses.legal_disenfranchisement`、`derived_statuses.high_risk_power`、`rule_atoms.art_04_02_voting_member_eligibility`、`rule_atoms.art_04_05_voter_roster_freeze`、`rule_atoms.art_04_12_procedural_review_scope` | 术语、名册冻结和高风险权力已进入核心骨架 |
| 第五条 | 成员基本权利 | 已覆盖 | `rule_atoms.art_05_basic_member_rights`、`human_review_gates.gate_member_basic_rights_boundary`、`invariants.inv_basic_member_rights_require_lawful_process` | 讨论、提案、知情、申辩、复核、免受报复，以及隐私、尊严与群聊安全保障已进入骨架 |
| 第六条 | 成员基本义务 | 已覆盖 | `rule_atoms.art_06_basic_member_duties`、`human_review_gates.gate_member_basic_duty_match` | 禁止刷屏辱骂骚扰威胁、隐私侵害、诈骗冒充、违法违规内容、虚构紧急状态和程序干扰，以及尊重程序结果与保留合法异议渠道已进入骨架 |
| 第七条 | 权力合法性 | 已覆盖 | `rule_atoms.art_07_rule_basis_required`、`human_review_gates.gate_rule_basis_match` | 已形成规则依据与记录要求 |
| 第八条 | 治理机构 | 已覆盖 | `rule_atoms.art_08_governance_organs_boundary`、`human_review_gates.gate_governance_authority_boundary` | 表决成员、荣誉群主、元老会、机器人、技术保管人的边界已进入骨架 |
| 第九条 | 职务分离 | 已覆盖 | `rule_atoms.art_09_office_separation`、`human_review_gates.gate_bootstrap_override_boundary` | 荣誉群主/元老不得兼任与技术控制不得替代程序已进入骨架 |
| 第十条 | 群主机器人 | 已覆盖 | `rule_atoms.art_10_bot_boundary`、`invariants.inv_bot_not_above_law` | 已进入机器人边界与不可越权约束 |
| 第十条之一 | 平台控制权与交接 | 已覆盖 | `rule_atoms.art_10_bot_boundary`、`human_review_gates.gate_platform_constraint_review` | 平台保管人与交接边界已进入审查入口 |
| 第十一条 | 荣誉群主的权力 | 已覆盖 | `rule_atoms.art_11_honor_owner_authority`、`human_review_gates.gate_governance_authority_boundary` | 日常执行权限与不得越权、报复、删改记录等边界已进入骨架 |
| 第十二条 | 元老会的权力 | 已覆盖 | `rule_atoms.art_12_elder_council_authority`、`human_review_gates.gate_governance_authority_boundary` | 监督、程序审查、复核受理、有限紧急代理与禁止越权已进入骨架 |
| 第十三条 | 回避规则 | 已覆盖 | `rule_atoms.art_13_recusal`、`human_review_gates.gate_conflict_of_interest` | 已形成回避审查入口 |

### 第二编　规范层级与立规程序条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第十四条 | 提案分类 | 已覆盖 | `rule_atoms.art_14_proposal_classification`、`workflow_fsm.ordinary_proposal`、`workflow_dev_contracts.ordinary_proposal` | 提案类型分类、基础治理条例/宪制修订的类型化路由、临时措施约束与紧急动议转现有紧急程序已进入骨架 |
| 第十五条 | 提案内容要求 | 已覆盖 | `rule_atoms.art_15_proposal_required_fields`、`workflow_dev_contracts.ordinary_proposal` | 标题、发起人、目的理由、具体文本或措施、生效/期限/失效条件与高风险标记已形成完整字段约束 |
| 第十六条 | 普通议题审查 | 已覆盖 | `rule_atoms.art_16_ordinary_proposal_review`、`human_review_gates.gate_group_matter_scope`、`workflow_fsm.ordinary_proposal`、`workflow_dev_contracts.ordinary_proposal` | 审查、补正、超时自动推进都已进入骨架 |
| 第十七条 | 讨论与冷却期 | 已覆盖 | `rule_atoms.art_17_discussion_periods`、`workflow_fsm.ordinary_proposal`、`workflow_dev_contracts.ordinary_proposal` | 讨论期长度已进入规则和流程 |
| 第十八条 | 表决规则 | 已覆盖 | `rule_atoms.art_18_general_vote_thresholds`、`threshold_sets.ordinary_proposal`、`threshold_sets.basic_governance_norm`、`threshold_sets.constitutional_amendment`、`workflow_fsm.ordinary_proposal`、`invariants.inv_rights_sensitive_vote_anonymous` | 门槛、投票期、匿名性和开票公示已进入核心骨架 |
| 第十九条 | 记录与公示 | 已覆盖 | `rule_atoms.art_19_proposal_record_and_publication`、`workflow_fsm.ordinary_proposal`、`human_review_gates.gate_vote_validity_review`、`workflow_dev_contracts.ordinary_proposal` | 提案文本、讨论期、投票窗口、人数、票数、结果公示与程序复核请求记录已进入骨架 |
| 第二十条 | 临时措施 | 已覆盖 | `rule_atoms.art_20_temporary_measure_limit`、`human_review_gates.gate_bypass_formal_rulemaking`、`workflow_fsm.ordinary_proposal` | 期限、不得反复续用、不得永久剥权已进入骨架 |

### 第三编　荣誉群主选举条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第二十一条 | 候选资格 | 已覆盖 | `rule_atoms.art_21_honor_owner_candidate_eligibility`、`human_review_gates.gate_honor_owner_candidate_commitment_review`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election` | 14 日入群、禁权/冻结排除、愿意履职并接受监督与“当选后适用职务分离”已进入骨架 |
| 第二十二条 | 提名方式 | 已覆盖 | `rule_atoms.art_22_honor_owner_nomination_channels`、`human_review_gates.gate_honor_owner_candidate_commitment_review`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election` | 自荐、5 人/10% 联名推荐门槛、联名待本人确认与 supporter 记录已进入骨架 |
| 第二十三条 | 选举程序 | 已覆盖 | `threshold_sets.honor_owner_election_single_candidate`、`threshold_sets.honor_owner_election_runoff`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election` | 公示、质询、首轮/复选、匿名和投票门槛已进入骨架 |
| 第二十四条 | 任期 | 已覆盖 | `rule_atoms.art_24_honor_owner_term_and_caretaker`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election` | 90 日任期、届满转看守、看守期补选启动与对应 contract 已进入骨架 |
| 第二十五条 | 缺位与代理 | 已覆盖 | `rule_atoms.art_25_honor_owner_vacancy_and_proxy`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election`、`side_effect_contracts.start_by_election` | 空缺公告、临时代理指定、补选重开、两次流产后机器人临时自治，以及争议直达全体表决都已进入骨架 |
| 第二十六条 | 履职要求 | 已覆盖 | `rule_atoms.art_26_honor_owner_duty_requirements`、`workflow_fsm.honor_owner_election`、`workflow_dev_contracts.honor_owner_election` | 高风险操作留痕、治理摘要发布与荣誉群主履职边界已进入骨架 |

### 第四编　元老会设立与选举条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第二十七条 | 组成 | 已覆盖 | `rule_atoms.art_27_elder_council_composition`、`workflow_fsm.elder_election`、`workflow_dev_contracts.elder_election` | 元老会 3-7 奇数席位、默认 3 席与 90 日任期已进入骨架 |
| 第二十八条 | 候选资格 | 已覆盖 | `rule_atoms.art_28_elder_candidate_eligibility`、`human_review_gates.gate_elder_candidate_commitment_review`、`workflow_fsm.elder_election` | 14 日入群、禁权/冻结排除与中立承诺已进入骨架 |
| 第二十九条 | 选举方式 | 已覆盖 | `rule_atoms.art_29_elder_election_process`、`threshold_sets.elder_election`、`workflow_fsm.elder_election`、`workflow_dev_contracts.elder_election` | 提名公示、席位内多选、末位同票加投、半数出席门槛已形成完整 workflow 骨架 |
| 第三十条 | 元老会会议与表决 | 已覆盖 | `rule_atoms.art_30_elder_council_decision_thresholds`、`human_review_gates.gate_elder_council_high_risk_review` | 法定参与人数、普通/特别表决门槛与记录义务已进入骨架 |
| 第三十一条 | 程序审查期限 | 已覆盖 | `rule_atoms.art_31_elder_council_review_deadlines`、`human_review_gates.gate_elder_council_timeout_fallback_review`、`workflow_dev_contracts.ordinary_proposal`、`workflow_dev_contracts.formal_discipline`、`workflow_dev_contracts.formal_discipline_review` | 48h/2h、程序失职留痕、顺位承接，以及“任意两名表决权成员联署触发”都已进入骨架 |
| 第三十二条 | 禁止事项 | 已覆盖 | `rule_atoms.art_32_elder_council_prohibitions`、`human_review_gates.gate_elder_council_prohibition_review` | 压制异见、泄密、不回避、越权与阻碍程序已形成独立约束表 |

### 第五编　弹劾及职责条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第三十三条 | 弹劾理由 | 已覆盖 | `rule_atoms.art_33_honor_owner_impeachment_reason_catalog`、`human_review_gates.gate_impeachment_reason_catalog_match`、`workflow_fsm.honor_owner_impeachment`、`workflow_dev_contracts.honor_owner_impeachment` | 荣誉群主弹劾理由目录、reason code 与法定理由审查已进入骨架 |
| 第三十四条 | 弹劾发起 | 已覆盖 | `functions.higher_of`、`rule_atoms.art_34_impeachment_establishment`、`human_review_gates.gate_signature_identity_and_case_completeness`、`workflow_fsm.honor_owner_impeachment`、`workflow_dev_contracts.honor_owner_impeachment` | 联署门槛、形式审查、超时视为成立已进入骨架 |
| 第三十五条 | 权力冻结 | 已覆盖 | `rule_atoms.art_35_impeachment_freeze`、`lock_types.honor_owner_powers`、`workflow_fsm.honor_owner_impeachment`、`workflow_dev_contracts.honor_owner_impeachment` | 冻结及客观安全风险例外已进入骨架 |
| 第三十六条 | 弹劾程序 | 已覆盖 | `threshold_sets.honor_owner_impeachment`、`workflow_fsm.honor_owner_impeachment`、`workflow_dev_contracts.honor_owner_impeachment` | 回应期、投票期、罢免门槛已进入骨架 |
| 第三十七条 | 弹劾结果 | 已覆盖 | `rule_atoms.art_37_honor_owner_impeachment_outcomes`、`workflow_fsm.honor_owner_impeachment`、`workflow_dev_contracts.honor_owner_impeachment`、`side_effect_contracts.start_by_election` | 通过后立即卸任并补选、未通过恢复冻结权力并保留记录、恶意弹劾可转日常管理都已进入骨架 |
| 第三十八条 | 弹劾理由 | 已覆盖 | `rule_atoms.art_38_elder_impeachment_reason_catalog`、`human_review_gates.gate_impeachment_reason_catalog_match`、`workflow_fsm.elder_impeachment`、`workflow_dev_contracts.elder_impeachment` | 元老弹劾理由目录、reason code 与法定理由审查已进入骨架 |
| 第三十九条 | 发起与程序 | 已覆盖 | `threshold_sets.elder_impeachment`、`lock_types.elder_powers`、`human_review_gates.gate_signature_identity_and_case_completeness`、`workflow_fsm.elder_impeachment`、`workflow_dev_contracts.elder_impeachment` | 联署、冻结、投票、补选触发都已进入骨架 |

### 第六编　紧急防护与代理程序条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第四十条 | 紧急状态 | 已覆盖 | `rule_atoms.art_40_41_emergency_definition`、`human_review_gates.gate_emergency_state_confirmation`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 紧急状态定义已进入审查入口和主流程 |
| 第四十一条 | 不得认定为紧急状态的情形 | 已覆盖 | `rule_atoms.art_40_41_emergency_definition`、`human_review_gates.gate_emergency_state_confirmation`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 排除项已进入紧急状态判断规则 |
| 第四十二条 | 紧急动议发起 | 已覆盖 | `rule_atoms.art_42_emergency_motion_establishment`、`human_review_gates.gate_objective_safety_risk_exception`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 报告、联署成立、机器人最低技术动作已进入骨架 |
| 第四十三条 | 荣誉群主响应 | 已覆盖 | `rule_atoms.art_43_honor_owner_response`、`human_review_gates.gate_conflict_of_interest`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 2 小时/30 分钟响应与利益冲突代理已进入骨架 |
| 第四十四条 | 可采取措施 | 已覆盖 | `rule_atoms.art_44_46_emergency_measure_limits`、`lock_types.temporary_mute`、`lock_types.temporary_motion_restriction`、`lock_types.temporary_high_risk_power_suspension`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 临时禁言、限制提案、高风险权限暂停、临时移出及初步复核已进入骨架 |
| 第四十五条 | 禁止事项 | 已覆盖 | `rule_atoms.art_45_emergency_prohibitions`、`human_review_gates.gate_retaliation_review`、`workflow_fsm.emergency_protection`、`invariants.inv_emergency_not_permanent` | 禁止压制批评、永久处分、报复性管理已进入骨架 |
| 第四十六条 | 期限与续期 | 已覆盖 | `rule_atoms.art_44_46_emergency_measure_limits`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 明确期限、24h 复核、48h 转正式程序已进入骨架 |
| 第四十七条 | 事后复核 | 已覆盖 | `rule_atoms.art_47_emergency_post_review`、`human_review_gates.gate_emergency_abuse_review`、`workflow_fsm.emergency_protection`、`workflow_dev_contracts.emergency_protection` | 报告、复核、确认滥用后的纠正已进入骨架 |

### 第七编　民主动议重组元老会条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第四十八条 | 制度性质 | 已覆盖 | `rule_atoms.art_48_reboot_constitutional_remedy_nature`、`human_review_gates.gate_reboot_institutional_breakdown_review`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 宪制级救济属性、不得作为日常斗争工具与制度性失灵边界已进入骨架 |
| 第四十九条 | 适用情形 | 已覆盖 | `rule_atoms.art_49_reboot_applicability_catalog`、`human_review_gates.gate_reboot_institutional_breakdown_review`、`human_review_gates.gate_same_major_fact_and_institutional_reason`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 法定适用情形、禁止仅以个案不满/立场差异/私人冲突发起、制度性理由目录已进入骨架 |
| 第五十条 | 发起门槛 | 已覆盖 | `functions.higher_of`、`rule_atoms.art_50_reboot_establishment`、`human_review_gates.gate_same_major_fact_and_institutional_reason`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 联署门槛、文本完整性、超时成立已进入骨架 |
| 第五十一条 | 权力冻结范围 | 已覆盖 | `rule_atoms.art_51_reboot_protection_scope`、`lock_types.reboot_procedure_protection`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 对发起人/联署人/讨论范围的保护已进入骨架 |
| 第五十二条 | 冷却与回应 | 已覆盖 | `rule_atoms.art_52_55_reboot_cooling_and_frequency`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 冷却期和回应要求已进入骨架 |
| 第五十三条 | 表决 | 已覆盖 | `threshold_sets.elder_reboot`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 投票期与通过门槛已进入骨架 |
| 第五十四条 | 重组效果 | 已覆盖 | `rule_atoms.art_54_reboot_effects_and_interim_supervision`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot`、`side_effect_contracts.dissolve_current_council`、`side_effect_contracts.start_new_council_election_within_72h`、`side_effect_contracts.enter_reboot_interim_supervision`、`side_effect_contracts.escalate_reboot_collective_supervision` | 整体解散、72h 内换届启动、重组后的临时监督，以及两次流产后改由全体表决权成员临时监督都已进入骨架 |
| 第五十五条 | 频率限制 | 已覆盖 | `rule_atoms.art_52_55_reboot_cooling_and_frequency`、`human_review_gates.gate_same_major_fact_and_institutional_reason`、`workflow_fsm.elder_reboot`、`workflow_dev_contracts.elder_reboot` | 14 日重复限制、新重大事实和更高门槛例外已进入骨架 |

### 第八编　日常管理规则

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第五十六条 | 一般管理原则 | 已覆盖 | `rule_atoms.art_56_daily_management_ladder`、`workflow_fsm.daily_management`、`workflow_dev_contracts.daily_management` | 阶梯原则、直接必要措施例外与升级提示已进入骨架 |
| 第五十七条 | 处分种类 | 已覆盖 | `rule_atoms.art_57_daily_management_sanction_catalog`、`lock_types.daily_management_motion_restriction`、`side_effect_contracts.record_daily_management_note`、`side_effect_contracts.apply_daily_management_short_mute`、`side_effect_contracts.apply_daily_management_motion_restriction` | 提醒、警告、短期禁言、提案/动议限制与 formal boundary 已进入骨架 |
| 第五十八条 | 记录、证据与隐私 | 已覆盖 | `rule_atoms.art_58_evidence_baseline`、`human_review_gates.gate_evidence_sufficiency_and_privacy`、`human_review_gates.gate_privacy_safe_public_summary` | 日志优先、匿名投诉限制、隐私保护和最小充分摘要已进入骨架 |

### 第九编　正式处分程序条例

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第五十九条 | 适用范围 | 已覆盖 | `rule_atoms.art_59_formal_discipline_scope`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | formal discipline 的处分范围、与日常管理/紧急防护的边界及 scope contract 已进入骨架 |
| 第六十条 | 立案与受理 | 已覆盖 | `rule_atoms.art_60_formal_discipline_acceptance`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 立案门槛、受理时限、超时视为受理已进入骨架 |
| 第六十条之一 | 送达与站外程序 | 已覆盖 | `functions.notice_delivery_deadline`、`rule_atoms.art_60_1_notice_delivery`、`human_review_gates.gate_notice_feasibility_review`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 送达顺位、视为送达时间、至少保留一个站外渠道已进入骨架 |
| 第六十一条 | 告知与申辩 | 已覆盖 | `rule_atoms.art_61_defense_window`、`human_review_gates.gate_notice_feasibility_review`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 申辩期和送达后继续程序的规则已进入骨架 |
| 第六十二条 | 证据审查 | 已覆盖 | `rule_atoms.art_62_evidence_review_for_major_sanction`、`human_review_gates.gate_evidence_sufficiency_and_privacy`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline`、`invariants.inv_no_major_sanction_if_facts_unclear` | 关键事实不清不得直接作重处分已进入骨架 |
| 第六十三条 | 裁决与表决门槛 | 已覆盖 | `rule_atoms.art_63_formal_discipline_vote`、`threshold_sets.formal_discipline_long_mute`、`threshold_sets.formal_discipline_restrict_candidacy`、`threshold_sets.formal_discipline_restrict_vote_or_remove`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 正式处分门槛、匿名投票和轻处分回退顺序已进入骨架 |
| 第六十四条 | 处分决定与执行 | 已覆盖 | `rule_atoms.art_64_execution_limits`、`human_review_gates.gate_privacy_safe_public_summary`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 决定字段、期限上限、机器人执行与结果摘要已进入骨架 |
| 第六十五条 | 复核 | 已覆盖 | `rule_atoms.art_65_review_entry`、`human_review_gates.gate_review_reason_validity`、`workflow_fsm.formal_discipline_review`、`workflow_dev_contracts.formal_discipline_review` | 复核门槛、复核理由、超时视为启动已进入骨架 |
| 第六十六条 | 与紧急程序的衔接 | 已覆盖 | `rule_atoms.art_66_emergency_to_formal_bridge`、`workflow_fsm.emergency_protection`、`workflow_fsm.formal_discipline`、`workflow_dev_contracts.formal_discipline` | 超过 48h 或拟作重处分时转 formal discipline 已进入骨架 |

### 第十编　附则

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第六十七条 | 解释权 | 已覆盖 | `rule_atoms.art_67_interpretation_boundary`、`human_review_gates.gate_temporary_interpretation_boundary` | 临时解释边界已进入骨架 |
| 第六十八条 | 修订 | 已覆盖 | `rule_atoms.art_68_revision_boundary`、`human_review_gates.gate_core_norm_amendment_boundary`、`threshold_sets.basic_governance_norm`、`threshold_sets.constitutional_amendment`、`workflow_dev_contracts.ordinary_proposal` | 总则/核心制度修订需走宪制修订案程序、不得含糊取消核心保障、核心制度变更需明示修改内容，已进入骨架 |
| 第六十九条 | 生效 | 已覆盖 | `rule_atoms.art_69_effective_and_non_retroactivity`、`human_review_gates.gate_non_retroactivity_exception_review`、`workflow_dev_contracts.ordinary_proposal`、`workflow_dev_contracts.formal_discipline_review` | 生效时间记录、新旧规则冲突适用与生效前已完成程序的不溯及既往边界，已进入骨架 |

## 四、当前主要缺口

按文档层看，article-level 的空白已经清零。

当前更值得继续补的，不是“还有哪些条文没进 spec”，而是：

1. 把第一、二、五、六条继续下沉为更细的不变量、权限矩阵和审计 contract；
2. 把这些总则级原则与运行时权限判断、记录要求做更严格的一致性核对。
## 五、最需要补的下一层文档工作

如果继续只做文档、不动代码，建议按这个顺序补：

1. 为第一、二、五、六条补更细的 article-level contract、audit event 和 projection 字段。
2. 把总则级原则和现有 workflow / side effect binding 做一轮逐项一致性核对。
