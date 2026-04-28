# 群聊多层状态机

用于 `law` 插件设计的群治理状态机草案。

## 1. 文档目标

这份文档不是把“群法律”直接翻译成代码，而是把它抽象成一个适合插件实现的多层状态机模型。

目标有四个：

1. 把法律文本里的角色、案件、程序、冻结、复核拆成可实现的状态域。
2. 避免把整个群治理做成一个巨大的单状态机，转而采用“分层 + 正交状态域”的建模方式。
3. 让 `law` 插件后续可以增量扩展，例如先做治理案件，再接规范层级与立规程序。
4. 保证状态机首先服从法律文本，其次才考虑当前已有实现。

## 2. 法律来源

本设计主要来自以下文本：

1. `群规·总则`
2. `规范层级与立规程序条例`
3. `荣誉群主选举条例`
4. `荣誉群主与元老会成员弹劾及职责条例`
5. `紧急防护与代理程序条例`
6. `民主动议重组元老会条例`

## 3. 设计结论

最重要的结论是：`law` 插件不应只有一个“群当前状态”。

更合理的模型是：

- 群聊有一个全局治理上下文状态机。
- 每个成员有一个角色/能力状态机。
- 每个治理案件有一个案件状态机。
- 每个互动命令有一个会话状态机。
- 每个正式规范有一个规范生命周期状态机。
- 权力冻结本身不是案件状态，而是一个独立的锁状态域。

也就是说，最终运行态应是一个聚合快照：

```text
GroupSnapshot =
  GovernanceContext
  x MemberRoleStates
  x OpenCases
  x ActiveLocks
  x ActiveSessions
  x EffectiveNorms
```

## 4. 总体分层

建议把状态机分成 5 层 + 1 个正交锁层。

### 4.1 L0 规范层 `NormLayer`

处理“规则本身”的生命周期，而不是处理某个治理案件。

适合承载：

- 新设规范
- 修订规范
- 废止规范
- 规范层级认定
- 规范冲突处理

### 4.2 L1 群治理上下文层 `GovernanceContextLayer`

处理整个群当前处于什么治理模式。

适合承载：

- 是否已初始化
- 是否存在荣誉群主
- 是否处于紧急代理期
- 是否处于元老会重组冷却/表决期
- 是否允许执行高风险权力

### 4.3 L2 成员角色层 `MemberRoleLayer`

处理单个成员在治理体系中的身份与能力。

适合承载：

- 普通成员
- 荣誉群主
- 元老
- 候选人
- 被冻结治理权成员
- 被紧急措施指向成员

### 4.4 L3 案件层 `GovernanceCaseLayer`

处理每一个治理案件自己的生命周期。

适合承载：

- 荣誉群主选举
- 荣誉群主弹劾
- 元老弹劾
- 紧急防护
- 重组元老会
- 未来的规范转化案件

### 4.5 L4 交互会话层 `InteractionSessionLayer`

处理机器人与群成员之间的一次程序性交互。

适合承载：

- 命令发起
- 参数收集
- 联署收集
- 投票收集
- 复核等待
- 超时取消

### 4.6 正交锁层 `LockLayer`

这是整个模型里非常关键的一层。

法律文本里大量规则其实不是“状态迁移”，而是“能力锁”：

- 荣誉群主权力冻结
- 单个元老职权冻结
- 全局禁言权冻结
- 全局踢人权冻结
- 紧急代理期间的临时治理权

这层应该独立存储，供所有命令在 guard 阶段查询。

## 5. 推荐的顶层模型

建议把群治理上下文拆成 4 个正交子状态机，而不是一棵硬编码大树。

### 5.1 初始化子状态机 `BootstrapState`

```text
uninitialized -> initialized
```

含义：

- `uninitialized`：群法律未导入，核心角色未建立。
- `initialized`：至少已导入法律模板，成员档案可同步，治理命令可运行。

触发事件：

- `治理初始化成功`：`uninitialized -> initialized`

### 5.2 行政治理可用性子状态机 `ExecutiveAvailability`

```text
honor_owner_absent <-> honor_owner_present
```

含义：

- `honor_owner_absent`：无荣誉群主，行政权缺位，只能走补位/选举/有限应急路径。
- `honor_owner_present`：有且仅有一名荣誉群主。

触发事件：

- 设置荣誉群主
- 荣誉群主选举通过
- 荣誉群主弹劾通过
- 荣誉群主主动卸任或被撤销

### 5.3 紧急代理子状态机 `EmergencyProxyMode`

```text
idle -> support_collecting -> proxy_active -> review_pending -> idle
```

含义：

- `idle`：没有紧急代理生效。
- `support_collecting`：紧急防护联署中。
- `proxy_active`：元老会可以请求机器人执行临时禁言/临时剥夺群政权力。
- `review_pending`：紧急措施结束，等待元老会报告或荣誉群主复核。

法律约束：

- 仅在存在现实且紧迫风险时进入。
- 只能采取最小干预的可逆措施。
- 不构成治理权转移。
- 不得永久踢人。

### 5.4 结构冻结子状态机 `StructuralFreezeMode`

```text
none -> impeachment_freeze -> none
none -> reboot_freeze -> reboot_cooling -> reboot_voting -> none
```

含义：

- `impeachment_freeze`：弹劾对象的相关权力被冻结。
- `reboot_freeze`：重组元老会程序一经启动，禁言/踢人权冻结。
- `reboot_cooling`：进入冷却讨论期。
- `reboot_voting`：进入最终表决期。

注意：

- `StructuralFreezeMode` 和 `EmergencyProxyMode` 不能简单相互覆盖，它们应共同作用于 guard。
- 根据法律文本，重组元老会冷却期内应禁止紧急防护与代理程序。

## 6. 成员角色状态机

成员不是只有一个角色字段，建议拆成三个维度。

### 6.1 身份维度 `InstitutionalRole`

```text
member
candidate_honor_owner
elder
honor_owner
```

说明：

- `candidate_honor_owner` 是过程态，不是长期治理身份。
- `elder` 与 `honor_owner` 原则上不应同时长期并存，若业务允许兼任，也应在规则里显式声明。

### 6.2 能力维度 `GovernanceCapability`

```text
normal
governance_suspended
temporary_proxy_actor
under_impeachment
under_emergency_measure
```

说明：

- `governance_suspended`：被剥夺发起治理、联署或投票等权利。
- `temporary_proxy_actor`：元老在紧急代理期可临时触发有限机器人操作。
- `under_impeachment`：被案件直接指向，相关职权冻结。
- `under_emergency_measure`：被临时禁言或被临时剥夺群政权力。

### 6.3 平台身份维度 `PlatformRole`

```text
owner
admin
member
bot
```

这个维度不属于法律角色，但会影响初始化、平台管理员同步、真实可执行权限。

## 7. 通用案件状态机

所有治理案件建议复用一套统一外壳：

```text
draft
-> supporting
-> cooling? 
-> voting?
-> active?
-> approved | rejected | cancelled | expired
-> closed
```

解释：

- `draft`：已创建但还没正式进入程序。
- `supporting`：联署/资格收集中。
- `cooling`：进入法定冷却期。
- `voting`：群体表决中。
- `active`：已生效但尚未完成后续复核，比如紧急代理。
- `approved` / `rejected`：已形成结果。
- `closed`：审计、解锁、善后完成。

## 8. 各案件类型的专用流转

### 8.1 荣誉群主选举 `honor_owner_election`

依据法律文本，建议最终插件按这个流程实现：

```text
draft
-> nomination_publicity
-> campaign_statement
-> voting
-> approved | rejected
-> closed
```

当前已有实现更像简化版：

```text
draft -> voting -> approved/rejected -> closed
```

设计建议：

- 插件层保留完整法律版状态机。
- 若前期只做 MVP，可以把 `nomination_publicity` 和 `campaign_statement` 折叠成 `draft` 的子步骤。

### 8.2 荣誉群主弹劾 `honor_owner_impeachment`

```text
draft
-> supporting
-> threshold_reached
-> honor_owner_power_frozen
-> voting
-> approved | rejected
-> closed
```

关键 guard：

- 只有元老会成员能联署。
- 达到多数门槛后立即冻结荣誉群主高风险权力。

关键 side effect：

- `lock(honor_owner_powers, target_user_id)`
- 通过后撤销荣誉群主身份
- 未通过则释放冻结

### 8.3 元老弹劾 `elder_impeachment`

```text
draft
-> supporting
-> threshold_reached
-> elder_power_frozen(target)
-> voting
-> approved | rejected
-> closed
```

关键 guard：

- 目标必须当前是元老。
- 发起与联署主体应是普通成员共同体，而不是只限元老。

### 8.4 紧急防护 `emergency_protection`

```text
draft
-> supporting
-> threshold_reached
-> proxy_active
-> emergency_measure_executed?
-> review_pending
-> approved | rejected | expired
-> closed
```

说明：

- 这类案件的“通过”不是最终裁决，而是“允许临时程序性代理”。
- `proxy_active` 期间元老会只能请求临时禁言、临时禁权。
- 结束后必须进入 `review_pending`。

关键 guard：

- 荣誉群主未在合理时间响应。
- 重组元老会冷却期内不得启动。
- 不得用于观点争执、普通分歧。

### 8.5 重组元老会 `elder_reboot`

```text
draft
-> supporting
-> threshold_reached
-> global_ban_kick_frozen
-> cooling
-> voting
-> approved | rejected
-> closed
```

关键规则：

- 一旦达到联署门槛，立即冻结禁言和踢人权。
- 冷却期内禁止最终表决。
- 冷却期内禁止紧急防护与代理程序。
- 通过后整体解散本届元老会并触发新一届选举。

## 9. 规范层状态机

`law` 插件后续如果要支持“群友议题 -> 正式规范”，建议不要复用治理案件状态机，而是单独做 `NormProposal`。

```text
proposed
-> level_classifying
-> deliberating
-> voting
-> effective | rejected
-> amended | abolished
```

关键属性：

- `norm_level`
  - `constitutional`
  - `basic_governance`
  - `procedural`
  - `temporary_measure`
- `norm_action`
  - `create`
  - `amend`
  - `abolish`

关键 guard：

- 宪制级修订不得走紧急程序。
- 高位规范不能被低位程序实质性架空。
- 废止视同修订，沿用同级或更高门槛。

## 10. 会话状态机

每个交互命令建议复用统一的会话状态机模板。

```text
idle
-> command_received
-> validating_actor
-> collecting_arguments
-> creating_case
-> collecting_support?
-> collecting_vote?
-> executing_effect?
-> auditing
-> finished | cancelled | timeout | rejected
```

说明：

- `validating_actor`：做身份、冻结、重复案件检查。
- `collecting_arguments`：补齐目标成员、理由、候选层级、措施类型等参数。
- `creating_case`：落库并发出首条公告。
- `collecting_support`：联署型案件使用。
- `collecting_vote`：群体表决型案件使用。
- `executing_effect`：执行禁言、撤销角色、解散元老会等副作用。
- `auditing`：记录审计日志、写入可追溯上下文、释放锁。

## 11. 推荐的锁模型

锁应做成独立表，而不是埋在 case status 里。

推荐锁类型：

| lock_type | 作用对象 | 含义 |
| --- | --- | --- |
| `honor_owner_powers` | 指定成员 | 荣誉群主高风险权力冻结 |
| `elder_powers` | 指定成员 | 指定元老职权冻结 |
| `ban_global` | 全群 | 禁言权冻结 |
| `kick_global` | 全群 | 踢人权冻结 |
| `governance_suspended` | 指定成员 | 禁止发起治理、联署、参与治理动作 |
| `temporary_ban` | 指定成员 | 紧急代理或治理动作导致的临时禁言 |
| `temporary_governance_restriction` | 指定成员 | 临时剥夺群政参与能力 |

锁的统一规则：

1. 锁必须可审计。
2. 锁必须有来源案件。
3. 锁必须有释放条件。
4. 锁释放应幂等。

## 12. 命令到状态机的映射

| 命令 | 主要触发层 | 前置 guard | 主要迁移 |
| --- | --- | --- | --- |
| `治理初始化` | L1 | 未初始化或允许重入同步 | `uninitialized -> initialized` |
| `设置荣誉群主` | L1/L2 | 平台管理员或当前荣誉群主 | `honor_owner_absent/present -> honor_owner_present` |
| `添加元老` | L2 | 初始化完成且具备授权 | `member -> elder` |
| `移除元老` | L2 | 初始化完成且具备授权 | `elder -> member/revoked` |
| `发起荣誉群主选举` | L3 | 发起人未禁权、目标合法 | 创建 `honor_owner_election` |
| `发起弹劾荣誉群主` | L3/L5 | 发起人为元老 | 创建 `honor_owner_impeachment`，门槛到达后加锁 |
| `发起弹劾元老` | L3/L5 | 发起人未禁权、目标为元老 | 创建 `elder_impeachment`，门槛到达后加锁 |
| `发起重组元老会` | L3/L5 | 未存在同类开启案件 | 创建 `elder_reboot`，立即冻结 `ban_global/kick_global` |
| `发起紧急防护` | L3 | 未处于重组冷却期、目标合法 | 创建 `emergency_protection` |
| `联署治理案件` | L3 | 发起人未禁权、案件在 `supporting` | `supporting -> threshold_reached` |
| `推进治理案件` | L3 | 案件处于需外部推进的阶段 | `cooling -> voting` 或 `active -> review_pending` |
| `治理禁言` | L1/L5 | 荣誉群主未被冻结，或代理期内元老具备临时权限 | 执行副作用并记录 |
| `治理放逐` | L1/L5 | 仅荣誉群主且未全局冻结 | 执行副作用并记录 |

## 13. 不变量

这些规则建议作为全局 invariant，每次状态迁移后都校验：

1. 任一时刻最多只有一名 `active honor_owner`。
2. 任一时刻同一目标上不得存在重复的同类型开放案件。
3. `ban_global` 或 `kick_global` 存在时，不得执行对应高风险操作。
4. `honor_owner_powers` 存在时，荣誉群主不得执行对应治理动作。
5. `elder_powers` 存在时，被弹劾元老不得执行元老会能力。
6. 紧急代理不得产生永久性后果。
7. 紧急代理结束后必须进入复核。
8. 宪制级规范不得通过普通程序直接改写。
9. 所有治理副作用必须可追溯到会话、案件或审计事件。

## 14. 推荐的数据模型

建议最少有以下持久化对象：

### 14.1 `group_governance_context`

- `group_id`
- `bootstrap_state`
- `executive_availability`
- `emergency_proxy_mode`
- `structural_freeze_mode`
- `active_norm_version`
- `updated_at`

### 14.2 `member_governance_roles`

- `group_id`
- `user_id`
- `institutional_role`
- `governance_capability`
- `platform_role`
- `status`
- `source_case_id`
- `updated_at`

### 14.3 `governance_cases`

- `case_id`
- `group_id`
- `case_type`
- `status`
- `phase`
- `proposer_id`
- `target_user_id`
- `payload_json`
- `support_threshold`
- `vote_threshold`
- `cooldown_until`
- `resolved_at`

### 14.4 `governance_case_supports`

- `case_id`
- `user_id`
- `supported_at`

### 14.5 `governance_case_votes`

- `case_id`
- `user_id`
- `choice`
- `voted_at`

### 14.6 `governance_locks`

- `lock_id`
- `group_id`
- `lock_type`
- `target_user_id`
- `source_case_id`
- `active`
- `expires_at`
- `released_at`

### 14.7 `interaction_sessions`

- `session_id`
- `group_id`
- `session_type`
- `status`
- `owner_user_id`
- `bound_case_id`
- `data_json`
- `expires_at`

### 14.8 `norm_registry`

- `norm_id`
- `title`
- `norm_level`
- `status`
- `source_case_id`
- `version`
- `effective_at`
- `abolished_at`

## 15. 推荐实现方式

建议 `law` 插件不要把流程写死在命令函数里，而是拆成：

1. `aggregates`
   - `GroupGovernanceAggregate`
   - `GovernanceCaseAggregate`
   - `MemberRoleAggregate`
   - `NormAggregate`
2. `events`
   - `CaseCreated`
   - `SupportAdded`
   - `SupportThresholdReached`
   - `VoteOpened`
   - `VoteClosed`
   - `CaseApproved`
   - `CaseRejected`
   - `LockApplied`
   - `LockReleased`
   - `NormBecameEffective`
3. `guards`
   - 判断能否发起
   - 判断能否联署
   - 判断能否投票
   - 判断能否执行禁言/放逐
4. `side_effect_handlers`
   - 发消息
   - 调 OneBot 管理接口
   - 写审计日志
   - 同步平台管理员

换句话说：

- 状态机只负责“能不能变、变成什么”。
- 副作用处理器只负责“变完以后做什么”。

## 16. 推荐的 MVP 切分

如果你想按最小可用路径做 `law` 插件，我建议分 3 期：

### Phase 1：治理案件状态机

先做：

- 荣誉群主选举
- 荣誉群主弹劾
- 元老弹劾
- 重组元老会
- 紧急防护
- 锁模型
- 审计模型

### Phase 2：角色与群上下文状态机

补上：

- 群初始化
- 荣誉群主缺位
- 平台管理员同步
- 成员角色快照

### Phase 3：规范层状态机

最后做：

- 议题转规范
- 规范层级认定
- 修订/废止
- 冲突处理

## 17. 一句话总结

`law` 插件最适合被设计成“群上下文 + 成员角色 + 治理案件 + 会话 + 锁 + 规范”的多层并发状态机，而不是一个单线流程机器人。

如果后面你愿意，我可以基于这份文档继续往下做两步中的任一步：

1. 把这份状态机直接细化成 Python 枚举、事件、仓储模型。
2. 按这份状态机给 `src/vendors/nonebot_plugin_law` 画出具体模块结构和实现顺序。
