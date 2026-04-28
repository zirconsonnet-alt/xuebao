# Story 3.2: 投票参与发放荣誉（topic_id 绑定 + 幂等）

Status: review

## Story

As a 群成员,
I want 参与某议题投票后获得荣誉,
so that 我的参与行为能被认可与累计。

## Acceptance Criteria

1. **第一次有效投票成功：记录 topic_votes + honor(+1)**
   - **Given** 议题投票流程已存在 `topic_id`  
     **When** 用户完成第一次“有效投票成功”  
     **Then** 写入 `topic_votes`（UNIQUE：group_id+topic_id+user_id）  
     **And** 写入 honor ledger（delta=+1，reason=topic_vote_participation，ref_type=topic，ref_id=topic_id，幂等键）  
   - [Source: docs/planning-artifacts/epics.md#Story 3.2]

2. **重复投票/重复回调：荣誉不重复发放**
   - **Given** 同一用户对同一 `topic_id` 已经获得过荣誉  
     **When** 再次触发发放逻辑  
     **Then** honor 不再增加（幂等）  
   - [Source: docs/planning-artifacts/epics.md#Story 3.2]

## Tasks / Subtasks

- [x] Task 1: DB 表与幂等预留（AC: 1, 2）
  - [x] Subtask 1.1: 新增 `topic_votes` 表（PRIMARY KEY: group_id,topic_id,user_id）
  - [x] Subtask 1.2: 新增 `GroupDatabase.reserve_topic_vote(...) -> bool`

- [x] Task 2: 用例层封装（AC: 1, 2）
  - [x] Subtask 2.1: 新增 `src/application/use_cases/award_honor_for_topic_vote.py`

- [x] Task 3: 对接投票流程（AC: 1）
  - [x] Subtask 3.1: 在 `src/interfaces/nonebot/vote_runtime.py` 的投票成功路径中，对 `TopicStrategy + topic_id` 发放荣誉（幂等）

- [x] Task 4: 单测（AC: 1, 2）
  - [x] Subtask 4.1: 新增 `tests/test_award_honor_for_topic_vote_use_case.py`

- [x] Task 5: 回归
  - [x] Subtask 5.1: 运行 `poetry run pytest` 全绿

## Dev Agent Record

### Agent Model Used

GPT-5.2 (Codex CLI)

### Completion Notes List

- Award honor +1 on first valid topic vote per (group_id, topic_id, user_id), idempotent via `topic_votes`.
- Tests: `poetry run pytest` passes.

### File List

- docs/implementation-artifacts/3-2-topic-vote-honor.md
- src/application/use_cases/award_honor_for_topic_vote.py
- src/interfaces/nonebot/vote_runtime.py
- src/plugins/nonebot_plugin_manager/database.py
- tests/test_award_honor_for_topic_vote_use_case.py

