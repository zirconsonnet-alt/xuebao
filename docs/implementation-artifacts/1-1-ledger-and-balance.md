# Story 1.1: 统一账本与余额查询（DB + API）

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a 群成员,
I want 系统提供 points/honor 的统一账本记录与余额汇总能力,
so that 我能随时查询余额且每一次变更都可追溯并具备幂等保障。

## Acceptance Criteria

1. **（Schema）账本表可用 + 幂等键唯一**
   - **Given** 系统使用现有 `GroupDatabase`（sqlite）作为唯一数据入口  
     **When** 启动/初始化数据库  
     **Then** 创建或升级 `points_ledger` 表结构（至少包含 `group_id/user_id/currency/delta/reason/ref_type/ref_id/idempotency_key/created_at`）  
     **And** `idempotency_key` 具有唯一约束，重复写入不会产生重复记账  
   - [Source: docs/planning-artifacts/epics.md#Story 1.1]

2. **（Balance）余额以账本汇总为准**
   - **Given** 存在任意 ledger 记录（包含 points 与 honor 两种 currency）  
     **When** 读取某 `group_id + user_id` 的 `points` / `honor` 余额  
     **Then** 返回值等于 ledger 的 `delta` 汇总  
     **And** 不引入“余额字段 + 账本”双写  
   - [Source: docs/planning-artifacts/epics.md#Story 1.1]

3. **（Idempotency）重复幂等键不重复入账**
   - **Given** 以同一个 `idempotency_key` 重复请求记账写入  
     **When** 再次写入 ledger  
     **Then** 不产生重复记录（写入返回 False 或等价语义）  
     **And** 数据库仅存在一条对应记录  
   - [Source: docs/planning-artifacts/epics.md#Story 1.1]

## Tasks / Subtasks

- [x] Task 1: 为 `GroupDatabase` 增加 `points_ledger`（AC: 1）
  - [x] Subtask 1.1: 在 `src/plugins/nonebot_plugin_manager/database.py` 的 `GroupDatabase._create_tables()` 增加 `CREATE TABLE IF NOT EXISTS points_ledger (...)`
  - [x] Subtask 1.2: 加唯一约束：`idempotency_key` UNIQUE（可直接列级 UNIQUE 或独立 UNIQUE INDEX）
  - [x] Subtask 1.3: 增加必要索引（建议：`(user_id, currency, created_at)` 或 `(user_id, currency)`；以查询余额性能为准）

- [x] Task 2: 增加账本写入与余额查询方法（AC: 2, 3）
  - [x] Subtask 2.1: 新增 `GroupDatabase.insert_ledger(...) -> bool`（重复幂等键时捕获 `sqlite3.IntegrityError` 并返回 False）
  - [x] Subtask 2.2: 新增 `GroupDatabase.get_balance(user_id: int, currency: str) -> int`（余额=SUM(delta)，无记录返回 0）
  - [x] Subtask 2.3: 方法内部对 `group_id` 使用 `self.group_id` 写入/查询（即使 DB 是“按群分库”，仍写入 `group_id` 字段以满足 PRD 数据口径）

- [x] Task 3: 单测覆盖账本幂等与余额汇总（AC: 2, 3）
  - [x] Subtask 3.1: 新增 `tests/test_points_ledger.py`，覆盖：
    - [x] 同一 `idempotency_key` 写入两次仅成功一次
    - [x] points/honor 分币种汇总正确
    - [x] 无记录余额返回 0
  - [x] Subtask 3.2: 测试隔离：不得污染真实 `data/`；推荐为 `GroupDatabase` 增加可选 `data_root: Path | None = None`（默认仍用 `Path('data')`），测试用临时目录注入

- [x] Task 4: 回归（全量测试）与文档记录（AC: 1, 2, 3）
  - [x] Subtask 4.1: 运行 `poetry run pytest` 全绿
  - [x] Subtask 4.2: 在本 story 的 Dev Agent Record 中记录：改动文件清单 + 测试覆盖点

## Dev Notes

- 目标只覆盖 Story 1.1（账本 + 余额 API）。`sign_in_records/topic_votes` 与命令入口在后续 story 实现。  
  [Source: docs/planning-artifacts/epics.md#Epic 2]
- DB 单一入口：`src/plugins/nonebot_plugin_manager/database.py::GroupDatabase`；`src/infrastructure/persistence/group_database.py` 只是 re-export。  
  [Source: src/infrastructure/persistence/group_database.py]
- 幂等写入模式参考现有实现：`GroupDatabase.reserve_vote_record()` / `InternalDatabase.reserve_bot_nonce()`（捕获 `sqlite3.IntegrityError` 返回 False）。  
  [Source: src/plugins/nonebot_plugin_manager/database.py]
- 不要新增 `from __future__ import annotations`（仓库约束）。

### Project Structure Notes

- 本 story 属于“infrastructure/persistence + application 后续服务使用”的基础能力，直接落在 `GroupDatabase` 以符合“单库”要求；入口层/投票链路对接不在本 story 内。  
  [Source: docs/planning-artifacts/prd-economy-mvp.md#4. 数据设计（一套 DB)]

### References

- [Source: docs/planning-artifacts/prd-economy-mvp.md]
- [Source: docs/planning-artifacts/epics.md]
- [Source: docs/planning-artifacts/architecture.md]
- [Source: src/plugins/nonebot_plugin_manager/database.py]

## Dev Agent Record

### Agent Model Used

GPT-5.2 (Codex CLI)

### Debug Log References

### Completion Notes List

- Implemented `GroupDatabase` ledger schema and APIs: `points_ledger`, `insert_ledger`, `get_balance`. (AC: 1/2/3)
- Added `GroupDatabase(data_root=...)` to isolate sqlite under tests. (Task 3.2)
- Tests: `poetry run pytest` (8 passed). (Task 4.1)

### File List

- docs/implementation-artifacts/1-1-ledger-and-balance.md
- src/plugins/nonebot_plugin_manager/database.py
- tests/test_points_ledger.py
