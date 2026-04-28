# Story 3.1: 发起议题扣费（/发起议题）

Status: review

## Story

As a 群成员,
I want 发起议题时消耗积分并创建议题,
so that 群内讨论有成本约束且流程可持续运行。

## Acceptance Criteria

1. **积分足够：创建议题并扣 5 points，返回余额**
   - **Given** 群成员积分 >= 5  
     **When** 发起“发起议题”流程并设置议题内容  
     **Then** 创建一个 `topic_id` 并写入扣费 ledger（delta=-5，reason=topic_create_cost，ref_type=topic，ref_id=topic_id，幂等键）  
     **And** 返回提示包含 `topic_id` 与当前积分余额  
   - [Source: docs/planning-artifacts/epics.md#Story 3.1]

2. **积分不足：拒绝创建与扣费**
   - **Given** 群成员积分 < 5  
     **When** 触发发起议题  
     **Then** 拒绝创建议题与拒绝扣费，并提示当前余额与所需点数  
   - [Source: docs/planning-artifacts/epics.md#Story 3.1]

3. **幂等：重复触发不重复扣费/不重复创建**
   - **Given** 由于重复触发导致同一请求被多次处理（同用户、同日、同内容）  
     **When** 再次发起议题扣费流程  
     **Then** 不重复扣费  
     **And** 不重复创建 topic（返回已存在的 `topic_id` 或等价语义）  
   - [Source: docs/planning-artifacts/epics.md#Story 3.1]

## Tasks / Subtasks

- [x] Task 1: DB 层支持“发起议题扣费”的幂等事务（AC: 1, 2, 3）
  - [x] Subtask 1.1: 在 `src/plugins/nonebot_plugin_manager/database.py` 新增 `topic_create_requests`（用于“同日同内容”幂等）
  - [x] Subtask 1.2: 新增 `GroupDatabase.create_topic_and_charge(...) -> (created, topic_id, balance)`

- [x] Task 2: 用例层封装（AC: 1, 2, 3）
  - [x] Subtask 2.1: 新增 `src/application/use_cases/topic_economy.py`（`CreateTopicAndChargeUseCase`）

- [x] Task 3: 对接现有投票入口（AC: 1, 2）
  - [x] Subtask 3.1: 在 `src/interfaces/nonebot/vote_runtime.py` 的 `VoteController`（TopicStrategy）开始前先校验积分是否 >= 5
  - [x] Subtask 3.2: 在收集到 topic content 后创建 topic_id 并扣费，写入 session data（topic.topic_id）

- [x] Task 4: 单测覆盖（AC: 1, 2, 3）
  - [x] Subtask 4.1: 新增 `tests/test_create_topic_and_charge.py` 覆盖：不足拒绝、足够扣费、重复不重复扣费且复用 topic_id

- [x] Task 5: 回归（全量测试）
  - [x] Subtask 5.1: 运行 `poetry run pytest` 全绿

## Dev Agent Record

### Agent Model Used

GPT-5.2 (Codex CLI)

### Completion Notes List

- Implemented idempotent topic creation + cost charging in GroupDatabase and integrated into Topic vote flow.
- Tests: `poetry run pytest` (11 passed).

### File List

- docs/implementation-artifacts/3-1-topic-create-charge.md
- src/application/use_cases/topic_economy.py
- src/interfaces/nonebot/vote_runtime.py
- src/plugins/nonebot_plugin_manager/database.py
- tests/test_create_topic_and_charge.py
