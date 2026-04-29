# `laws.spec.v0.yaml` 验收清单与覆盖矩阵

## 一、使用说明

本文件用于核对 `laws/laws.spec.v0.yaml` 是否以当前 `laws/laws.md` 为唯一法律来源。当前 source of truth 是：

- `laws/laws.md`
- 标题：`群宪法及治理条例`
- 结构：正文 20 条 + 附表一至附表五

本矩阵衡量的是 **spec 覆盖度**，不是运行时代码完成度。`laws.spec.v0.yaml` 仍是可执行规范骨架，不是法律原文逐字镜像。

## 二、汇总

| 项目 | 结论 |
| --- | --- |
| 当前法律来源 | `laws/laws.md` |
| 覆盖口径 | 20 条正文 + 5 个附表 |
| 正文覆盖 | 已覆盖 |
| 附表覆盖 | 已覆盖 |
| 是否逐字镜像 | 否 |
| 是否保留运行时骨架 | 是，保留 `threshold_sets`、`workflow_fsm`、`workflow_dev_contracts` 等结构 |

## 三、正文覆盖矩阵

| 条文 | 标题 | 状态 | 主要 spec 落点 | 备注 |
| --- | --- | --- | --- | --- |
| 第一条 | 群体性质、成员主权与规范层级 | 已覆盖 | `meta.source_of_truth`、`spec_semantics`、`rule_atoms`、`human_review_gates`、`invariants` | 旧的分条 rule atom 作为兼容别名保留，但解释以当前正式文本为准 |
| 第二条 | 基本原则、成员权利义务与执法说理 | 已覆盖 | `rule_atoms`、`human_review_gates.gate_member_basic_rights_boundary`、`gate_member_basic_duty_match`、`gate_rule_basis_match` | 覆盖权利、义务、执法说明、事后补正和无依据不得处分 |
| 第三条 | 核心术语 | 已覆盖 | `derived_statuses`、`entities`、`lock_types` | 覆盖表决权成员、计票基数成员、合法禁权状态、高风险权力、技术保管人、代理人等 |
| 第四条 | 表决名册、活跃确认与资格争议 | 已覆盖 | `functions.voter_roster_snapshot`、`threshold_sets`、`human_review_gates.gate_roster_correction_review`、`workflow_dev_contracts` | 覆盖名册冻结、活跃确认、争议票、资格复核和投票计算 |
| 第五条 | 事实、证据、隐私与证明标准 | 已覆盖 | `human_review_gates.gate_evidence_sufficiency_and_privacy`、`gate_privacy_safe_public_summary`、`audit_event_catalog` | 覆盖证据强度、匿名投诉、隐私保护、事实认定记录和复核纠错 |
| 第六条 | 治理机构、职务分离与缺位 | 已覆盖 | `rule_atoms`、`lock_types`、`workflow_fsm` | 覆盖分权结构、回避、程序顺位、缺位、小规模补位 |
| 第七至十条 | 机构与权限通则 | 已覆盖 | `rule_atoms`、`human_review_gates.gate_governance_authority_boundary`、`side_effect_contracts`、`workflow_fsm` | 覆盖荣誉群主、元老会、机器人、技术保管人、代理、破窗和越权处理 |
| 第十一条 | 提案、讨论与表决通则 | 已覆盖 | `workflow_fsm.ordinary_proposal`、`threshold_sets`、`workflow_dev_contracts.ordinary_proposal` | 覆盖提案字段、撤回修改、审查、讨论、投票、公告和复核 |
| 第十二条 | 重大程序通则 | 已覆盖 | `workflow_fsm`、`threshold_sets`、`human_review_gates.gate_signature_identity_and_case_completeness` | 覆盖重大程序申请、最低可核验条件、申辩期、匿名投票和执行公告 |
| 第十三条 | 紧急防护 | 已覆盖 | `workflow_fsm.emergency_protection`、`lock_types.temporary_mute`、`temporary_motion_restriction`、`temporary_high_risk_power_suspension` | 覆盖紧急状态、动议门槛、响应、临时措施、48 小时转正式程序和防规避 |
| 第十四条 | 送达、审计与复核通则 | 已覆盖 | `functions.notice_delivery_deadline`、`workflow_fsm.formal_discipline_review`、`audit_event_catalog` | 覆盖送达顺位、站外渠道、匿名票审计、票向保存和复核理由 |
| 第十五至十九条 | 具体制度效果表 | 已覆盖 | `workflow_fsm.honor_owner_election`、`elder_election`、`honor_owner_impeachment`、`elder_impeachment`、`elder_reboot`、`formal_discipline` | 覆盖选举、弹劾、重组、迁移、日常管理、快速移出与正式处分 |
| 第二十条 | 解释、修订、生效与过渡 | 已覆盖 | `human_review_gates.gate_temporary_interpretation_boundary`、`gate_core_norm_amendment_boundary`、`gate_non_retroactivity_exception_review` | 覆盖最终解释、技术性修正、生效、不溯及既往和首届选举 |

## 四、附表覆盖矩阵

| 附表 | 标题 | 状态 | 主要 spec 落点 |
| --- | --- | --- | --- |
| 附表一 | 主要门槛、期限与匿名要求总表 | 已覆盖 | `threshold_sets`、各 `workflow_fsm.*.threshold_ref` |
| 附表二 | 联署、启动门槛与计算示例 | 已覆盖 | `functions.higher_of`、`workflow_dev_contracts`、联署/门槛字段 |
| 附表三 | 权限矩阵与代理范围表 | 已覆盖 | `lock_types`、`side_effect_contracts`、权限边界审查 gate |
| 附表四 | 事实、证据、争议与复核处理表 | 已覆盖 | `human_review_gates`、`audit_event_catalog`、复核类 workflow |
| 附表五 | 日常管理、内容治理与执法执行表 | 已覆盖 | `workflow_fsm.daily_management`、`formal_discipline`、通知和证据摘要字段 |

## 五、验收结论

`laws.spec.v0.yaml` 当前应按“基于 `laws.md` 的可执行骨架”验收：它覆盖当前正式正文与附表，但保留实现所需的状态机、门槛表、审查 gate、事件目录和兼容性标识。若 `laws.md` 与 spec 的解释发生冲突，以 `laws.md` 正文及附表为准。
