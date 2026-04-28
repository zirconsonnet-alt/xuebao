---
stepsCompleted: [1, 2, 3]
inputDocuments:
  - docs/planning-artifacts/prd-economy-mvp.md
  - docs/planning-artifacts/architecture.md
---

# xuebao - Epic Breakdown

## Overview

本文档用于把 PRD（MVP：群签到/积分/荣誉/议题经济）与现有架构约束（分层/门禁/稳定入口）转化为可执行的 epic/story，并为后续 `create-story` / `dev-story` 提供可直接落地的验收标准（AC）。

## Requirements Inventory

### Functional Requirements

FR1: 用户在群内可执行 `/签到`，同一 `group_id + user_id + 自然日` 仅允许成功一次；重复签到给出“已签到”提示。  
FR2: 成功签到会记账（ledger）并为用户增加 `points`（默认 +1，可配置但 MVP 固定）。  
FR3: 用户可执行 `/积分` 查询本人 points 余额（按 ledger 汇总）。  
FR4: 用户可执行 `/荣誉` 查询本人 honor 余额（按 ledger 汇总）。  
FR5: 用户可执行 `/发起议题 <内容>` 创建议题；若 points >= 5 则创建并扣除 5 points；不足则拒绝并提示余额。  
FR6: 议题投票沿用现有投票流程；在“第一次有效投票成功”时，对该 `topic_id` 给投票用户 +1 honor（幂等）。  
FR7: 所有 points/honor 的变更必须写入统一账本 `points_ledger`，可追溯（含原因、引用对象、时间、幂等键）。  
FR8: 所有数据写入同一套 sqlite（现有 `GroupDatabase`），不引入第二套数据库。  
FR9: （可选）提供 `/排行榜 积分` 与 `/排行榜 荣誉` 查看本群前 N（N 可配置，MVP 可先固定 10）。  

### NonFunctional Requirements

NFR1: 幂等性：签到、扣费、荣誉发放必须具备幂等键，重复请求不会重复记账或产生不一致。  
NFR2: 一致性：points/honor 余额以账本汇总为准，避免“余额字段 + 账本”双写引发漂移（除非明确引入缓存/快照）。  
NFR3: 时区与自然日口径：自然日以“本地日期”判定，需明确服务器时区与存储格式（YYYY-MM-DD），避免跨日边界错判。  
NFR4: 可审计：账本记录必须可回溯到触发动作（reason/ref_type/ref_id/idempotency_key）。  
NFR5: 可回滚/可迁移：表结构变更应具备向后兼容策略（先建表/加列，避免破坏旧功能）。  

### Additional Requirements

- 遵循现有架构硬约束：入口（interfaces/Nonebot）保持薄适配，尽量通过 `application` 的稳定入口调用，避免入口层直接写 DB。  
- 数据落点统一到 `GroupDatabase`（sqlite），表创建与访问集中管理。  
- 议题投票链路沿用现有 `VoteService`，经济逻辑以“轻量门面/用例”方式接入，减少对投票核心流程的侵入。  
- 新功能必须可被最小测试覆盖（至少：签到幂等、扣费不足拒绝、荣誉幂等）。  

### FR Coverage Map

FR1: Epic 2 - 每日签到幂等（自然日）  
FR2: Epic 2 - 签到发放 points 并可回溯  
FR3: Epic 1 - 查询 points 余额（账本汇总）  
FR4: Epic 1 - 查询 honor 余额（账本汇总）  
FR5: Epic 3 - 发起议题扣 5 points（不足拒绝）  
FR6: Epic 3 - 议题投票参与首次有效投票 +1 honor（幂等）  
FR7: Epic 1 - points/honor 统一账本、可追溯、幂等键  
FR8: Epic 1 - 单库落地到 GroupDatabase（sqlite）  
FR9: Epic 2（可选）- 群内积分/荣誉排行榜  

## Epic List

### Epic 1: 账户与账本（积分/荣誉可追溯）
用户可以查询自己的积分与荣誉余额；系统以统一账本记录每一次加/扣分，且全部落在同一套 sqlite（GroupDatabase）。  
**FRs covered:** FR3, FR4, FR7, FR8

### Epic 2: 每日签到（自然日幂等）
用户每天可签到一次获得积分，并可（可选）查看本群排行榜；签到严格按自然日幂等，并产出可审计账本记录。  
**FRs covered:** FR1, FR2, FR9（可选）

### Epic 3: 议题经济闭环（发起扣分 + 投票得荣誉）
用户发起议题需要消耗积分；用户参与议题投票可获得荣誉（只看参与，不看结果），且与既有投票流程兼容、幂等可追溯。  
**FRs covered:** FR5, FR6

## Epic 1: 账户与账本（积分/荣誉可追溯）

目标：在现有 `GroupDatabase`（sqlite）内落地“统一账本 + 余额汇总”的最小可用闭环，为后续签到/议题经济提供稳定基础；避免余额双写漂移，且所有变更可审计回溯。

### Story 1.1: 统一账本与余额查询（DB + API）

As a 群成员,
I want 系统为我的积分与荣誉提供统一账本记录与余额汇总能力,
So that 我能随时查询余额且每一次变更都可追溯与可幂等。

**Acceptance Criteria:**

**Given** 系统使用现有 `GroupDatabase` 作为唯一 sqlite 入口  
**When** 启动/初始化数据库  
**Then** 创建或升级 `points_ledger` 表结构（包含 currency、delta、reason、ref_type、ref_id、idempotency_key、created_at 等字段）  
**And** `idempotency_key` 在表中具有唯一约束，重复写入不会产生重复记账

**Given** 存在任意 ledger 记录（包含 points 与 honor 两种 currency）  
**When** 通过 DB 层方法读取某 `group_id + user_id` 的 `points` / `honor` 余额  
**Then** 返回余额为 ledger 的 delta 汇总值  
**And** 不依赖“余额字段”双写（余额以账本汇总为准）

**Given** 重复调用同一个 `idempotency_key` 的记账写入请求  
**When** 再次写入 ledger  
**Then** 写入操作返回“不重复写入”的结果（或等价语义）  
**And** 数据库中仅存在一条对应 ledger 记录

### Story 1.2: 群内余额查询命令（/积分 /荣誉）

As a 群成员,
I want 在群内通过命令查询自己的积分与荣誉余额,
So that 我能清楚了解自己能否发起议题以及当前荣誉积累。

**Acceptance Criteria:**

**Given** 群成员在群内发送 `/积分`  
**When** 系统读取该成员 points 余额（账本汇总）  
**Then** 返回可读的余额提示文本  
**And** 当余额为 0 时也能正确返回（不报错）

**Given** 群成员在群内发送 `/荣誉`  
**When** 系统读取该成员 honor 余额（账本汇总）  
**Then** 返回可读的余额提示文本  
**And** 文本应包含 currency 名称与数值（避免歧义）

**Given** 数据库暂不可用或查询失败  
**When** 执行 `/积分` 或 `/荣誉`  
**Then** 返回失败提示（不抛出未捕获异常导致 matcher 崩溃）  
**And** 失败不应写入任何 ledger 记录

## Epic 2: 每日签到（自然日幂等）

目标：提供每日签到能力，让用户稳定获得 points；签到严格按“自然日（本地日期口径）”幂等，并把 points 变更写入统一账本（可追溯）。

### Story 2.1: 每日签到命令（/签到）与自然日幂等

As a 群成员,
I want 每天签到一次获得积分,
So that 我能积累积分用于发起议题。

**Acceptance Criteria:**

**Given** 群成员在同一自然日首次发送 `/签到`  
**When** 系统为该 `group_id + user_id + sign_date(YYYY-MM-DD)` 预留签到记录成功  
**Then** 写入 `sign_in_records`（满足唯一约束）  
**And** 写入一条 ledger 记录为 points 增加（默认 +1，reason=sign_in，带幂等键）

**Given** 群成员在同一自然日重复发送 `/签到`  
**When** 系统检测到已存在 `sign_in_records`  
**Then** 返回“已签到”提示  
**And** 不产生重复 ledger 记账（points 不增加）

**Given** `/签到` 成功后  
**When** 系统返回响应  
**Then** 响应中包含当前 points 余额（账本汇总）  
**And** 余额应与 ledger 汇总结果一致

**Given** 系统需要判定自然日  
**When** 生成 `sign_date`  
**Then** 使用“本地日期”口径并以 `YYYY-MM-DD` 存储  
**And** 在文档/配置中明确服务器时区对“本地日期”的影响（避免跨日边界错判）

### Story 2.2: （可选）本群排行榜（积分/荣誉 Top N）

As a 群成员,
I want 查看本群积分或荣誉排行榜,
So that 我能了解群内活跃度与荣誉竞争情况。

**Acceptance Criteria:**

**Given** 群成员在群内发送 `/排行榜 积分`  
**When** 系统按 points 余额（账本汇总）降序取 Top N（MVP 可固定 N=10）  
**Then** 返回包含 Top N 用户与 points 数值的列表  
**And** 仅统计当前群的 ledger（不跨群合并）

**Given** 群成员在群内发送 `/排行榜 荣誉`  
**When** 系统按 honor 余额（账本汇总）降序取 Top N  
**Then** 返回包含 Top N 用户与 honor 数值的列表  
**And** 列表对余额相同的用户有稳定排序规则（例如按 user_id 或最近变更时间）

## Epic 3: 议题经济闭环（发起扣分 + 投票得荣誉）

目标：把 points/honor 与既有“议题投票”流程闭环打通：发起议题扣 points、参与投票得 honor；整个过程可幂等、可审计，并尽量保持入口薄适配（用 application 门面/用例承载经济逻辑）。

### Story 3.1: 发起议题扣费（/发起议题 <内容>）

As a 群成员,
I want 发起议题时消耗积分并创建议题,
So that 群内讨论有成本约束且流程可持续运行。

**Acceptance Criteria:**

**Given** 群成员发送 `/发起议题 <内容>` 且 points 余额 >= 5  
**When** 系统创建一个可关联 `group_id` 的 `topic_id` 并扣除 5 points  
**Then** 写入扣费 ledger 记录（delta=-5，reason=topic_create_cost，ref_type=topic，ref_id=topic_id，幂等键）  
**And** 返回“已创建议题/已扣费”的提示，并引导进入既有投票流程（沿用 VoteService）

**Given** 群成员发送 `/发起议题 <内容>` 且 points 余额 < 5  
**When** 系统检查余额  
**Then** 拒绝创建议题与拒绝扣费  
**And** 返回“余额不足”的提示（包含当前余额与所需点数）

**Given** 由于网络抖动/重复触发导致同一请求被重复处理  
**When** 系统使用同一幂等键执行扣费与创建流程  
**Then** 不产生重复扣费 ledger 记录  
**And** 不产生重复 topic（或能稳定返回同一 topic_id 的等价结果）

### Story 3.2: 投票参与发放荣誉（topic_id 绑定 + 幂等）

As a 群成员,
I want 参与某议题投票后获得荣誉,
So that 我的参与行为能被认可与累计。

**Acceptance Criteria:**

**Given** 某个议题投票流程已经创建并可获取 `topic_id`  
**When** 群成员对该 `topic_id` 完成第一次“有效投票成功”  
**Then** 在 `topic_votes` 中记录该 `group_id + topic_id + user_id` 的投票参与（满足唯一约束）  
**And** 写入 honor ledger 记录（delta=+1，reason=topic_vote_participation，ref_type=topic，ref_id=topic_id，幂等键）

**Given** 同一用户对同一 `topic_id` 重复投票（或重复回调）  
**When** 触发荣誉发放逻辑  
**Then** honor 仅增加一次（幂等）  
**And** 重复触发会返回“已领取/已记录”的等价语义（不重复记账）

**Given** 投票成功回调触发时无法获取 `topic_id`（会话数据缺失/旧流程）  
**When** 尝试发放荣誉  
**Then** 不发放 honor 且不写入 topic_votes  
**And** 记录可诊断日志（不影响投票主流程的完成/消息发送）
