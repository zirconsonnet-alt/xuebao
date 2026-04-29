# `laws.spec.v0.yaml` 与现行 `laws.md` 勘误说明

## 一、当前结论

当前 `laws/laws.md` 是唯一正式来源，标题为：

> 群宪法及治理条例

`laws.spec.v0.yaml` 不是法律原文逐字镜像，而是从 `laws.md` 编译出来的运行时可执行骨架。它可以保留 `threshold_sets`、`workflow_fsm`、`human_review_gates`、`lock_types`、`side_effect_contracts` 等实现结构，但这些结构不得反向改变 `laws.md` 的含义。

## 二、需要避免的旧判断

旧验收材料曾按“多编、多条、七十余条”的结构描述 spec 覆盖范围。当前 `laws.md` 采用：

- 第一章至第五章；
- 正文 20 条；
- 附表一至附表五。

因此，旧的“第十条之一”“第六十条之一”“第六十九条之一”等条号，不再是当前 `laws.md` 的规范引用口径。它们只能作为历史分稿或兼容骨架中的旧编号线索，不能作为当前执行引用。

## 三、当前对齐原则

| 事项 | 当前处理 |
| --- | --- |
| 法律来源 | 只以 `laws/laws.md` 为准 |
| 条文引用 | 使用当前正文条号、款号和附表名 |
| spec 结构 | 保留执行骨架，不要求逐字镜像 |
| 旧 rule atom / workflow 名称 | 可作为兼容标识保留 |
| 解释冲突 | 一律以 `laws.md` 正文和附表为准 |

## 四、spec 字段性质

以下字段属于实现或编译层，不是法律原文字段：

| spec 区块 | 性质 |
| --- | --- |
| `meta`、`spec_semantics` | spec 元信息与解释约束 |
| `entities`、`derived_statuses` | 领域模型和派生状态 |
| `rule_atoms` | 从正文和附表抽取的原子规则，名称可保留历史兼容 |
| `threshold_sets` | 附表一、附表二的门槛编译结果 |
| `human_review_gates` | 人工审查入口 |
| `lock_types`、`side_effect_contracts` | 权限冻结与副作用契约 |
| `workflow_fsm`、`workflow_dev_contracts` | 程序状态机和开发契约 |
| `audit_event_catalog`、`projections`、`invariants` | 审计、投影和运行时不变量 |

## 五、后续维护规则

1. 修改 `laws.md` 后，应同步检查 `threshold_sets` 和对应 `workflow_fsm.*.sources`。
2. 若只改错别字、编号、格式或交叉引用，spec 可只更新来源说明和验收矩阵。
3. 若改变门槛、期限、匿名要求、处分范围、代理范围或复核规则，应同步更新 YAML 中对应门槛表、状态机、审查 gate 和开发契约。
4. 旧分条例、FAQ、简明版与 spec 有差异时，均不得覆盖 `laws.md`。
