---
status: draft
workflowType: prd
project_name: xuebao
date: "2026-02-06"
owner: Bylou
---

# 最小 PRD（MVP）——群签到 + 积分 + 议题发起扣分 + 议题投票参与得荣誉（单库）

## 1. 目标与成功标准

### 目标

- 群成员每天可签到一次，获得积分（points）
- 成员发起议题需要消耗积分（5 points）
- 成员参与某议题投票（第一次有效投票）获得荣誉（honor）
- 全部数据落在同一套 sqlite（现有 GroupDatabase）

### 成功标准（DoD）

- `/签到`：同一用户同一自然日只能成功一次；成功返回当前积分；重复签到提示已签到
- `/发起议题 <内容>`：积分 >= 5 时创建议题并扣 5；不足时拒绝并提示余额
- `/议题投票`：沿用现有投票流程；每个用户对某个 `topic_id` 第一次有效投票 +1 honor（幂等）
- `/积分`、`/荣誉`：能查询个人余额；可选 `/排行榜` 查看本群前 N
- 所有加/扣分都有可追溯记录（账本）

## 2. 范围（In/Out）

### In-scope（MVP）

- 自然日签到
- points/honor 两种货币
- 发起议题扣 5 points
- 参与议题投票 +1 honor（只要参与，不看结果）
- 最小榜单/查询

### Out-of-scope（先不做）

- 连续签到奖励/补签
- 改票/撤回投票导致荣誉回滚
- 复杂反作弊（先靠幂等 + 审计）
- 跨群积分/荣誉合并

## 3. 核心规则（不可变更点）

- 签到周期：自然日（按本地日期）
- 发起议题消耗：5 points
- 荣誉发放绑定：`topic_id`（不是 `session_key`）
- 荣誉发放条件：第一次有效投票成功（幂等）

## 4. 数据设计（一套 DB）

新增/扩展建议表（在现有 `database.py::GroupDatabase` 中创建与访问）：

### `points_ledger`（统一账本，记录 points/honor）

- `ledger_id` PK
- `group_id`, `user_id`
- `currency` TEXT（points/honor）
- `delta` INTEGER（+1 / -5）
- `reason` TEXT（sign_in/topic_create_cost/topic_vote_participation…）
- `ref_type` TEXT（topic/…）
- `ref_id` TEXT（topic_id 等）
- `idempotency_key` TEXT UNIQUE
- `created_at` DATETIME

### `sign_in_records`（自然日幂等）

- `group_id`, `user_id`, `sign_date`（YYYY-MM-DD）
- UNIQUE(`group_id`,`user_id`,`sign_date`)

### `topic_votes`（议题投票参与幂等）

- `group_id`, `topic_id`, `user_id`, `choice`, `created_at`
- UNIQUE(`group_id`,`topic_id`,`user_id`)

### `topics`（已有就复用；补字段/或新表）

- 至少确保能拿到 `topic_id` 并可关联 `group_id`

## 5. 接口/命令（Nonebot）

新建服务：`SignInService`（“签到系统新建 service”）

- `/签到`：写 `sign_in_records` + ledger(+1 points)
- `/积分`：返回 points 余额（sum ledger）
- `/荣誉`：返回 honor 余额（sum ledger)
- （可选）`/排行榜`：积分、`/排行榜`：荣誉

议题投票：沿用 `VoteService`

- 发起议题：新增命令 `/发起议题 <内容>`（或复用现有“议题投票”入口，但必须在收集到内容后创建 topic）
- 投票参与：在投票成功的回调里，对 `topic_id + user_id` 幂等发 honor

## 6. 最小实现清单（按改动顺序）

### DB 层（GroupDatabase）

- 加建表：`points_ledger`、`sign_in_records`、`topic_votes`
- 加方法：
  - `reserve_sign_in(group_id,user_id,sign_date)->bool`
  - `insert_ledger(..., idempotency_key)->bool`
  - `get_balance(group_id,user_id,currency)->int`
  - `reserve_topic_vote(group_id,topic_id,user_id,choice)->bool`

### Application 层（新 service + 用例/门面）

- 新建 `sign_in_service.py`
- （建议）新增轻量门面/用例模块（避免 `vote_runtime` 直接写 DB）：
  - `TopicEconomyFacade.create_topic_and_charge(...) -> topic_id`
  - `HonorFacade.award_for_topic_vote(...) -> bool`

### 对接 VoteService / vote_runtime

在 topic 收集完成后：

- 创建 `topic_id`
- 扣 5 points（ledger，幂等 key：`{group}:{user}:topic_create:{topic_id}` 或 `{group}:{user}:topic_create:{hash(content)}:{date}`）
- 把 `topic_id` 写入 vote session data（现有 session 机制）

在投票成功时：

- 从 session data 取 `topic_id`
- `reserve_topic_vote` 成功后写 ledger(+1 honor，idem key：`{group}:{user}:honor:topic_vote:{topic_id}`）

### 验收与测试

- 单测：sign-in 幂等、扣分不足拒绝、荣誉幂等
- 集成/冒烟：群里实际跑 `/签到`、`/发起议题`、完成一次议题投票后查 `/荣誉`

