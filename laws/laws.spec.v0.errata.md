# `laws.spec.v0.yaml` 与现行 `laws.md` 逐条勘误表

## 一、结论

当前磁盘上的 `laws/laws.md` 与 `laws/laws.spec.v0.yaml` 对照后，结论应修正为：

- **不存在“spec 引用了现行 `laws.md` 中不存在的条号”这一类问题。**
- `laws.spec.v0.yaml` 中出现的条文引用，按“条”一级核对，**缺失条号数量为 0**。
- spec 与 `laws.md` 的真实差异，主要不在“条号越界”，而在于 spec 新增了大量**执行层/建模层字段**，因此它不能视为“法律原文逐字镜像”。

## 二、条号核对结果

### 1. 误判为不存在、但现行 `laws.md` 实际存在的条号

| 条号 | spec 中用途 | `laws.md` 现状 | 结论 |
| --- | --- | --- | --- |
| 第十条之一 | 平台约束审查来源 | 现行 `laws.md` 存在 `第十条之一【平台控制权与交接】` | 不是越界引用 |
| 第六十条之一 | 送达与站外程序来源 | 现行 `laws.md` 存在 `第六十条之一【送达与站外程序】` | 不是越界引用 |

### 2. 全量核对结果

| 项目 | 结果 |
| --- | --- |
| `laws.md` 中可识别条标题数量 | 71 |
| spec 中出现的唯一条号引用数量 | 53 |
| spec 引用了但 `laws.md` 中不存在的条号数量 | 0 |

## 三、真正需要勘误的内容

以下内容**不是现行 `laws.md` 的原文字段**，而是 `laws.spec.v0.yaml` 为了执行建模新增的结构。  
如果目标是“严格一致于法律原文”，这些内容都不能直接当作“法律文本本身”。

### A. 元信息与说明性字段

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `meta` | `spec_id`、`status: acceptance_ready_executable_skeleton`、`design`、`scope`、`non_goals` | 纯 spec 元信息 | 若追求严格镜像，应移出正文规范层 |
| `conventions` | `article_ref_style`、`percentage_rounding`、`voting_math`、`interpretation_defaults` | 执行约定与归纳规则 | 可保留为实现附录，不应冒充法律原文 |
| `functions` | `ceil_ratio`、`higher_of`、`voter_roster_snapshot`、`notice_delivery_deadline` | 计算函数抽象 | 属于执行层定义，不是法律条文字段 |

### B. 领域对象与派生状态

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `entities` | `Member`、`GovernanceCase`、`Vote`、`Evidence`、`GovernanceEvent` 等 | 领域建模对象 | 可作为实现模型，但不属于法律原文 |
| `derived_statuses` | `voting_member`、`legal_disenfranchisement`、`high_risk_power` | 对条文定义的程序化派生 | 可保留，但应明确标注为 derived |

### C. 原子规则的统一结构壳

`rule_atoms` 里虽然大多有明确条文来源，但以下字段不是 `laws.md` 的原文字段，而是 spec 自己引入的统一壳：

| 字段 | 性质 |
| --- | --- |
| `id` | 规则编号，属 spec 内部标识 |
| `category` | 规则分类，属建模标签 |
| `subject` | 作用对象抽象，属建模字段 |
| `when` / `trigger` | 触发条件抽象 |
| `then` | 执行动作抽象 |
| `deadline` | 统一时限字段 |
| `exceptions` | 例外列表抽象 |
| `review_entry` | 人工审查入口引用 |
| `decidability` | 机器可判定 / 人工裁量标签 |

结论：`rule_atoms` 属于“**有条文依据，但字段结构不是法律原文**”。

### D. 统一门槛表

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `threshold_sets` | `approval`、`turnout_min_of_all_voting_members`、`min_vote_period`、`anonymous` | 对多个条文门槛的归一化整理 | 可作为执行表，但不是法律原文字段 |

说明：

- 这里的门槛大体与 `laws.md` 一致；
- 但 `threshold_sets` 整个区块本身是编译后的结构，不是原文结构。

### E. 人工裁量入口

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `human_review_gates` | `gate_duplicate_account_determination`、`gate_conflict_of_interest`、`gate_evidence_sufficiency_and_privacy` 等 | 人工审查节点注册表 | 合理，但属于执行层抽象 |

说明：

- `laws.md` 确实包含这些需要人工判断的事项；
- 但 `gate_*` 这种命名和“问题提示语”不是法律原文。

### F. 冻结与锁模型

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `lock_types` | `honor_owner_powers`、`elder_powers`、`temporary_mute`、`temporary_motion_restriction` 等 | 锁模型归一化 | 法律有冻结/限制效果，但没有这套 lock registry 原文字段 |

### G. 工作流状态机

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `workflow_fsm` | `initial_state`、`terminal_states`、`states`、`transitions` | 程序状态机抽象 | 这是实现骨架，不是法律原文 |

其中以下字段都属于新增建模字段，而非 `laws.md` 原文字段：

| 字段 | 性质 |
| --- | --- |
| `initial_state` | 初始状态建模 |
| `terminal_states` | 终态集合 |
| `states` | 状态枚举 |
| `transitions` | 状态迁移表 |
| `event` | 迁移触发事件 |
| `guards` | 守卫条件 |
| `min_duration` | 最小时长抽象 |
| `threshold_ref` | 引用门槛表的实现字段 |
| `side_effects` | 副作用声明 |

### H. 审计事件流

| spec 区块 | 典型字段 | 性质 | 处理建议 |
| --- | --- | --- | --- |
| `audit_event_catalog` | `event_type`、`payload` | 事件溯源模型 | 符合设计目标，但不是法律原文字段 |
| `projections` | `active_cases`、`active_locks`、`member_governance_rights` | 投影视图 | 纯执行层 |
| `invariants` | `inv_single_honor_owner` 等 | 运行时不变量 | 属于实现约束表达，不是法律原文 |

## 四、这份勘误表对应的准确结论

### 1. 可以保留的判断

- `laws.spec.v0.yaml` 不是 `laws.md` 的逐字镜像；
- 它本质上是“从法律文本编译出来的执行骨架”；
- 因此不能说它与法律原文“严格一致”。

### 2. 需要修正的判断

- 不能再说它“存在条文引用越界”；
- 至少按当前磁盘上的 `laws.md` 版本，`第十条之一` 与 `第六十条之一` 都真实存在；
- 因而“条号不存在”不是当前 spec 的实际问题。

### 3. 当前真正的问题定义

更准确的表述应是：

> `laws.spec.v0.yaml` 与现行 `laws.md` **条号引用层面一致**，  
> 但它包含大量**执行层新增字段与状态机结构**，  
> 因此只能算“基于原文的编译骨架”，不能视为“严格等同于法律原文的镜像表示”。

## 五、当前状态与后续收敛方向

截至当前仓库中的 `laws.spec.v0.yaml` `v0.2`：

- 已采用“保留 executable skeleton”这条路线；
- 已在 spec 中显式加入：
  - `derived_from_law`
  - `implementation_only`
  - `not_verbatim_from_law`
- 因此“新增字段未标注来源语义”这一问题，已经完成收口。

如果下一步还要继续收敛，最直接的动作仍是二选一：

1. 做一版“**strict mirror spec**”：只保留原文可直接落字段的内容，不保留 `workflow_fsm / audit_event_catalog / projections / invariants` 这类执行层结构。
2. 继续保留当前 spec 作为“**acceptance-ready executable skeleton**”，后续只维护条文对齐、勘误同步与实现映射，不再回退为“未标注语义的骨架”。

这两条路线都成立，但语义不能混用。
