# Story 2.1: 每日签到命令（/签到）与自然日幂等

Status: review

## Story

As a 群成员,
I want 每天签到一次获得积分,
so that 我能积累积分用于发起议题。

## Acceptance Criteria

1. **（/签到）首次签到成功：写 sign_in_records + points_ledger(+1) + 返回余额**
   - **Given** 同一自然日首次发送“签到”  
     **When** 系统预留 `group_id + user_id + sign_date(YYYY-MM-DD)` 成功  
     **Then** 写入 `sign_in_records`（唯一约束生效）  
     **And** 写入 points ledger（delta=+1，reason=sign_in，带幂等键）  
     **And** 返回消息包含当前 points 余额（账本汇总）  
   - [Source: docs/planning-artifacts/epics.md#Story 2.1]

2. **（/签到）重复签到：提示已签到 + 不重复记账**
   - **Given** 同一自然日重复发送“签到”  
     **When** 系统检测到已存在 `sign_in_records`  
     **Then** 返回“已签到”提示  
     **And** 不产生重复 ledger 记账（points 不增加）  
   - [Source: docs/planning-artifacts/epics.md#Story 2.1]

3. **（自然日口径）sign_date 使用本地日期并以 YYYY-MM-DD 存储**
   - **Given** 系统需要判定自然日  
     **When** 生成 `sign_date`  
     **Then** 使用本地日期口径并以 `YYYY-MM-DD` 存储  
   - [Source: docs/planning-artifacts/epics.md#Story 2.1]

## Tasks / Subtasks

- [x] Task 1: `GroupDatabase` 增加 `sign_in_records` + `reserve_sign_in`（AC: 1, 2, 3）
  - [x] Subtask 1.1: 在 `src/plugins/nonebot_plugin_manager/database.py` 创建 `sign_in_records`（PRIMARY KEY: group_id,user_id,sign_date）
  - [x] Subtask 1.2: 新增 `GroupDatabase.reserve_sign_in(user_id, sign_date) -> bool`（重复返回 False）

- [x] Task 2: 用例层实现签到逻辑（AC: 1, 2, 3）
  - [x] Subtask 2.1: 新增 `src/application/use_cases/sign_in.py`（不依赖 Nonebot）
  - [x] Subtask 2.2: 用例实现：自然日 `sign_date`、预留签到、写 ledger(+1 points)、返回余额

- [x] Task 3: Service 命令接入（AC: 1, 2）
  - [x] Subtask 3.1: 新增 `src/application/services/sign_in_service.py`，注册 `@service_action(cmd="签到")`
  - [x] Subtask 3.2: 在 `src/application/enums.py` 增加 `Services.SignIn`，并在 `src/application/services/service_manager.py` 注册

- [x] Task 4: 单测覆盖（AC: 1, 2, 3）
  - [x] Subtask 4.1: 新增 `tests/test_sign_in_use_case.py`：首次签到 points +1；重复签到不重复加分；sign_date 固定（注入 now）

- [x] Task 5: 回归（全量测试）与记录
  - [x] Subtask 5.1: 运行 `poetry run pytest` 全绿
  - [x] Subtask 5.2: 在 Dev Agent Record 填写完成说明与 File List

## Dev Notes

- 入口薄适配：Nonebot 命令入口仅调用 service；核心逻辑在 `SignInUseCase`（便于测试，避免 Nonebot 初始化依赖）。  
  [Source: docs/planning-artifacts/architecture.md#4. 用例中心（Use Case First）]
- 幂等键推荐：`sign_in:{group_id}:{user_id}:{YYYY-MM-DD}`。  
  [Source: docs/planning-artifacts/prd-economy-mvp.md#6. 最小实现清单（按改动顺序）]

## Dev Agent Record

### Agent Model Used

GPT-5.2 (Codex CLI)

### Debug Log References

### Completion Notes List

- Added daily sign-in persistence: `sign_in_records` + `reserve_sign_in`. (AC: 1/2/3)
- Added `SignInUseCase` to keep core logic testable without Nonebot init. (AC: 1/2/3)
- Added `SignInService` command `签到` and registered `Services.SignIn`. (AC: 1/2)
- Tests: `poetry run pytest` (9 passed). (Task 5.1)

### File List

- docs/implementation-artifacts/2-1-daily-sign-in.md
- src/application/enums.py
- src/application/services/service_manager.py
- src/application/services/sign_in_service.py
- src/application/use_cases/sign_in.py
- src/plugins/nonebot_plugin_manager/database.py
- tests/test_sign_in_use_case.py
