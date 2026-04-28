---
title: '重构 metadata_commands：引入 ports/use_cases，迁移调用点并删除 src/services'
slug: 'refactor-metadata-commands-remove-services'
created: '2026-02-06 06:34:24'
status: 'ready-for-dev'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - Python 3.12
  - Nonebot2
  - Poetry
  - nonebot-adapter-onebot (OneBot V11)
  - nonebot-plugin-alconna / arclet.alconna
  - FastAPI（通过 nonebot.get_app）
  - Pydantic
  - sqlite3
  - pytest
files_to_modify:
  - src/services/metadata_commands.py
  - src/services/__init__.py
  - src/application/commands/metadata_commands.py
  - src/application/ports/
  - src/application/ports/session_repository.py
  - src/application/ports/idempotency_repository.py
  - src/application/ports/audit_repository.py
  - src/application/ports/vote_repository.py
  - src/application/contracts/__init__.py
  - src/application/contracts/vote_metadata.py
  - src/application/contracts/bot_identity.py
  - src/application/adapters/persistence/sqlite_session_repository.py
  - src/application/adapters/persistence/sqlite_idempotency_repository.py
  - src/application/adapters/persistence/sqlite_audit_repository.py
  - src/application/adapters/persistence/sqlite_vote_repository.py
  - src/application/use_cases/vote_start.py
  - src/application/use_cases/vote_finish.py
  - src/application/use_cases/
  - src/contracts/
  - src/interfaces/nonebot/vote_runtime.py
  - src/application/strategies/vote_core.py
  - src/application/services/vote_service.py
  - src/infrastructure/persistence/topic_repository.py
  - src/infrastructure/persistence/member_stats_repository.py
  - src/infrastructure/persistence/group_database.py
  - src/plugins/nonebot_plugin_manager/database.py
  - src/plugins/nonebot_plugin_internal_api/__init__.py
  - scripts/check_layer_imports.py
  - tests/test_vote_metadata_facade.py
  - tests/test_session_version_conflict.py
  - tests/test_idempotency.py
code_patterns:
  - src/services/metadata_commands.py 作为兼容转发层（re-export）
  - src/infrastructure/persistence/group_database.py 也是 re-export（指向 src/plugins/.../database.py）
  - application.ports 使用 Protocol（已有 topic/member_stats 等示例）
  - infrastructure 侧已有 Sqlite*Repository（但当前依赖了 src.services.metadata_commands）
  - vote 相关：src/interfaces/nonebot/vote_runtime.py（控制器/流程编排）+ src/application/services/vote_service.py（服务入口）+ vote_core.py（投票/策略）
  - 会话/幂等/审计目前落在 GroupDatabase（sessions/idempotency_keys/audit_* 表）+ metadata_commands 函数集合
test_patterns:
  - pytest（已配置 tests/ 与基础用例）
  - 目前基本无业务单测；需要为首切片补充 mock ports 的用例单测
---

# Tech-Spec: 重构 metadata_commands：引入 ports/use_cases，迁移调用点并删除 src/services

**Created:** 2026-02-06 06:34:24

## Overview

### Problem Statement

当前 `metadata_commands` 通过 `src/services/metadata_commands.py` 作为全局入口被多层引用（interfaces / application / infrastructure / plugins）。`src/services` 本质是兼容转发层（re-export），但它让调用方形成“随处可用的数据库命令集合”，进而导致：

- `application` 层出现对 `interfaces` / `infrastructure` 的直接依赖，分层被打穿（门禁脚本无法变绿）。
- `domain` 包几乎为空，业务规则与状态校验散落在“命令函数/服务类”里。
- 迁移缺少“可回滚切片”，难以增量改造。

### Solution

采用 **2A** 路线：以能力域拆分 `metadata_commands`，引入 `application.ports`（契约）+ `application.use_cases`（编排）+ ports 实现（基于现有 sqlite `GroupDatabase` 的适配器），并通过稳定入口 **`src/application/contracts/`** 供插件/接口层调用。最终 **1A**：一次性迁移完所有引用点后，删除 `src/services/` 兼容层。

首个迁移切片选择 **2A**：投票/会话/幂等链路（`vote_runtime.py` + `vote_core.py`）作为模板切片打通。

### Scope

**In Scope:**
- 将投票/会话/幂等相关的 metadata 能力迁移到 ports/use_cases 架构下，并提供稳定调用入口（替代 `src.services.metadata_commands`）。
- 梳理并迁移其他直接依赖 `src.services.metadata_commands` 的调用点（internal_api、topic/member_stats、activity 等），以一次性删除 `src/services` 为目标。
- 让 `scripts/check_layer_imports.py` 的违规数量显著下降（至少清除本次涉及文件的跨层依赖）。
- 补齐最小 `domain` 规则承载点（例如活动状态字段合法性、会话步骤推进规则等），仅迁移“规则”，不迁移 DB I/O。

**Out of Scope:**
- 一次性全量迁移所有业务功能/所有插件到新结构（本 spec 聚焦 metadata 能力域）。
- 立即引入复杂 DI 容器并全量容器化（先显式组合根/显式装配）。
- 建立完整可观测性平台（仅要求最小日志/trace 口径预留）。

## Context for Development

### Codebase Patterns

- `src/services/metadata_commands.py` 仅 re-export `src/application/commands/metadata_commands.py` 的函数；但其被多处当作“数据库命令入口”直接使用。
- `application.ports` 已采用 `Protocol` 形式定义契约（例如 `TopicRepository`、`MemberStatsRepository`、`VisionGateway` 等），可复用该模式扩展“会话/审计/幂等”等 ports。
- `infrastructure/persistence/*_repository.py` 已有实现类（`SqliteTopicRepository` / `SqliteMemberStatsRepository`），但它们目前仍依赖 `src.services.metadata_commands`，属于分层未收敛状态。
- 现有门禁脚本会报出大量 `application -> interfaces/infrastructure` 的非法依赖，属于本次重构要优先消除的技术债信号。
- GroupDatabase/InternalDatabase 的真实实现位于 `src/plugins/nonebot_plugin_manager/database.py`（sqlite3），而 `src/infrastructure/persistence/group_database.py` 是再导出。
- vote 链路目前由 interfaces 层的 `VoteController` 直接编排会话与副作用，并通过 `metadata_commands` 直连 db（绕过 ports/use_cases）。

#### Ports 边界（采纳 Party Mode 建议）

为避免 ports 变成新的“万能口”，将 metadata 能力域拆成 4 个清晰边界：

1) **Session**：会话生命周期（`get/create/update_step/update_status/cleanup`），保留 **版本号/乐观锁** 语义（当前已有 `expected_version`）。
2) **Idempotency**：幂等键（`reserve`），明确 key 组成与 TTL 责任（用例定义语义；repo 只存取）。
3) **Audit**：审计日志/事件（`record_audit_log/record_audit_event`），event schema 规则进入 domain（仅规则），落库在 infrastructure。
4) **Voting**：投票记录（`reserve_vote_record`）作为 vote 子域能力（可与 Session 解耦）。

#### 迁移顺序与回滚点（1A 一次性删除的风险控制）

为保证一次性删除 `src/services` 时可控，迁移顺序固定为：

1) `src/interfaces/nonebot/vote_runtime.py`：先改走新的 facade（不再 import `src.services.metadata_commands`）。
2) `src/application/strategies/vote_core.py`：将 `reserve_vote_record` 改为依赖注入的 port（禁止直接 import）。
3) 其余调用点按依赖强度迁移：`internal_api` → `topic/member_stats` → `activity`。
4) 全库 search 结果为 0 后删除 `src/services/`。

回滚点：本次已选择“立即删除 `src/services` 兼容层”，因此不再保留基于 feature flag 的回退分支；回滚策略改为“提交/发布回滚”。

#### AGENTS 约束：`from __future__ import annotations`

仓库协作约束要求不要新增/保留该导入。本 spec 的默认策略是：

- **不把“全库清理 future annotations”作为范围**（避免扩大改动面），但
- **本次涉及的新增/改动文件必须遵守约束**：不新增该导入；如改动文件本身已存在该导入，需要你单独确认是否顺手移除。

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `src/services/metadata_commands.py` | 兼容转发层（最终删除目标） |
| `src/application/commands/metadata_commands.py` | 当前 metadata 相关真实实现（DB 命令集合） |
| `src/interfaces/nonebot/vote_runtime.py` | 投票会话流程主入口（首个迁移切片） |
| `src/application/strategies/vote_core.py` | 投票策略与投票记录（依赖 reserve_vote_record 等） |
| `src/application/services/vote_service.py` | 投票服务入口（调用 VoteController） |
| `src/plugins/nonebot_plugin_internal_api/__init__.py` | bot 内部 API / 登录 / nonce / session（后续迁移对象） |
| `src/infrastructure/persistence/topic_repository.py` | topic repository（当前仍依赖 services） |
| `src/infrastructure/persistence/member_stats_repository.py` | member stats repository（当前仍依赖 services） |
| `src/plugins/nonebot_plugin_manager/database.py` | sessions/幂等/审计/投票记录的 sqlite3 真正落点 |
| `src/infrastructure/persistence/group_database.py` | GroupDatabase/InternalDatabase 再导出（类型引用/兼容点） |
| `src/application/ports/*` | ports 现有契约示例（扩展参照） |
| `scripts/check_layer_imports.py` | 分层门禁脚本（用于验收“依赖方向收敛”） |

### Technical Decisions

- 删除策略：**1A**（一次性迁移所有引用点后删除 `src/services/`）。
- 架构路线：**2A**（ports + use_cases + infrastructure 实现；通过 contracts/facade 暴露给入口层）。
- 迁移顺序首切片：投票/会话/幂等链路（`vote_runtime.py` + `vote_core.py`）。
- 约束：`application` 禁止依赖 `interfaces/infrastructure`；`domain` 禁止依赖 nonebot/httpx/openai 等外部框架（由门禁脚本验证）。
- 已锁定：facade 入口使用 `src/application/contracts/`（更贴近应用层门面）；`src/contracts/` 继续用于 DTO（internal_api/tool_inputs）。
- 已锁定：`SessionRepository.update_session_step(...)` **统一返回 bool**（True=更新成功；False=会话不存在或版本冲突）。不抛出版本冲突异常（与现有 `GroupDatabase.update_session_step` 的语义保持一致，减少行为分叉）。
- 已锁定：不使用 feature flag 回退；`VoteMetadataFacade` 仅保留新实现路径。

## Implementation Plan

### Tasks

#### Step 2 产出要求（可直接开工的任务粒度）

- 调研与归类：
  - 枚举 `src/application/commands/metadata_commands.py` 的函数族与调用方，按 **Session/Idempotency/Audit/Voting** 归类（同时标注 topic/member_stats/activity/internal_api 的归属）。
  - 输出“函数 → 新归属 port/use_case → 调用方列表”的表格（将作为 Step 3 的任务拆解依据）。

#### 文件级任务（首切片：vote/session/幂等）

> 重要决策（已锁定）：**facade 放在 `src/application/contracts/`**（新增包），保持 `src/contracts/` 继续用于 DTO（internal_api/tool_inputs），避免混用。

- [ ] Task 1: 新建 application contracts 包作为稳定入口
  - File: `src/application/contracts/__init__.py`
  - Action: 创建包并导出本次新 facade（见 Task 5/Task 6）
  - Notes: 新文件不得添加 `from __future__ import annotations`（按仓库约束）

- [ ] Task 1.1: （移除）feature flags 回退方案
  - Reason: 已决定删除 `src/services`，不再保留旧入口回退分支

- [ ] Task 2: 定义 Session/Idempotency/Audit/Vote ports（Protocol）
  - File: `src/application/ports/session_repository.py`
  - Action: 定义 `SessionRepository`：`get_session/create_session/update_session_step/update_session_status/cleanup_expired_sessions`
  - Notes: `update_session_step` 必须显式暴露 `expected_version`；**返回 bool（不抛异常）**，并且 `False` 需要能区分“会话不存在/版本冲突”（通过 `get_session` 再读回 version/是否存在来判断即可）
  - File: `src/application/ports/idempotency_repository.py`
  - Action: 定义 `IdempotencyRepository.reserve(...) -> bool`
  - File: `src/application/ports/audit_repository.py`
  - Action: 定义 `AuditRepository.record_log(...)` 与 `record_event(...)`
  - File: `src/application/ports/vote_repository.py`
  - Action: 定义 `VoteRepository.reserve_vote_record(...) -> bool`

- [ ] Task 2.1: 补齐最小 domain 规则与类型（仅规则，不含 DB I/O）
  - File: `src/domain/models/session.py`
  - Action: 定义 `SessionSnapshot`（dataclass）：`session_key/flow/step/data/version/status/expires_at` 等字段，并提供 `is_active(now)` 判定（替代/收口 interfaces 层的 `_is_session_active` 逻辑）
  - File: `src/domain/models/audit.py`
  - Action: 定义 `AuditEvent`（dataclass）与最小校验（例如 `subject_type` 非空、`result` 在允许集合等）
  - Notes: 该任务的目标是把“规则/结构”从脚本式代码里拎出来，后续 use_cases/facade 使用这些类型以降低回归风险

- [ ] Task 3: 提供基于现有 sqlite GroupDatabase 的 ports 实现（临时落点：application adapters）
  - File: `src/application/adapters/persistence/sqlite_session_repository.py`
  - Action: 用 `src.plugins.nonebot_plugin_manager.database.GroupDatabase` 实现 `SessionRepository`
  - Notes: 这是**过渡落点**（当前 GroupDatabase 位于 plugins，且门禁脚本只禁止 `src.infrastructure` 直接被 application 引用）。退出条件：当 `GroupDatabase` 被迁移/包装进 `src/infrastructure` 且装配点迁移到 `interfaces/nonebot/composition_root.py` 后，将这些实现移动到 `src/infrastructure/persistence/` 并由组合根装配。
  - File: `src/application/adapters/persistence/sqlite_idempotency_repository.py`
  - Action: 实现 `IdempotencyRepository`（调用 `GroupDatabase.reserve_idempotency_key`）
  - File: `src/application/adapters/persistence/sqlite_audit_repository.py`
  - Action: 实现 `AuditRepository`（调用 `GroupDatabase.insert_audit_*`）
  - File: `src/application/adapters/persistence/sqlite_vote_repository.py`
  - Action: 实现 `VoteRepository`（调用 `GroupDatabase.reserve_vote_record`）

- [ ] Task 4: 把 vote_core 从“直接 import metadata_commands”改为“依赖注入 VoteRepository”
  - File: `src/application/strategies/vote_core.py`
  - Action: 删除 `from src.services import metadata_commands`
  - Action: 调整 `VoteManager.configure_session(...)` 接收 `vote_repo: VoteRepository`（或在构造函数注入）
  - Action: `vote()` 内改用 `vote_repo.reserve_vote_record(...)`
  - Notes: 这是首切片关键之一，用来证明“application 代码不再依赖 services”

- [ ] Task 5: 新增 vote 元数据 facade（替代 metadata_commands 在投票链路中的职责）
  - File: `src/application/contracts/vote_metadata.py`
  - Action: 新增 `VoteMetadataFacade`（或同等命名），封装以下能力并仅依赖 ports：
    - session：get/create/update_step/finish/cancel/cleanup
    - idempotency：reserve
    - audit：record_event / record_log
  - Notes: facade API 需覆盖 `src/interfaces/nonebot/vote_runtime.py` 当前调用点（避免在接口层散落 repo 组合逻辑），并且**必须提供下面这组明确接口**（不允许实现者自行发明/改名导致偏离）：

    **VoteMetadataFacade 必备接口（签名级约束）**
    - `cleanup_expired_sessions() -> int`
    - `get_session(session_key: str) -> SessionSnapshot | None`
    - `create_session(*, session_key: str, flow: str, owner_id: int | None, ttl_seconds: int, initial_data: dict | None) -> bool`
    - `update_session_step(*, session_key: str, step: int, patch_data: dict | None, expected_version: int, ttl_seconds: int | None = None) -> bool`
    - `finish_session(session_key: str) -> bool`
    - `cancel_session(session_key: str) -> bool`
    - `reserve_idempotency_key(*, idem_key: str, user_id: int | None, action: str, session_key: str | None) -> bool`
    - `record_audit_event(*, actor_id: int | None, action: str, subject_type: str | None, subject_id: str | None, session_key: str | None, result: str, context: dict | None = None) -> None`

    **调用点映射（从旧 metadata_commands 到新 facade）**
    - `metadata_commands.cleanup_expired_sessions(self.group.db)` → `metadata.cleanup_expired_sessions()`
    - `metadata_commands.get_session(self.group.db, session_key)` → `metadata.get_session(session_key)`
    - `metadata_commands.create_session(self.group.db, ...)` → `metadata.create_session(...)`
    - `metadata_commands.update_session_step(self.group.db, ...)` → `metadata.update_session_step(...)`
    - `metadata_commands.finish_session(self.group.db, session_key)` → `metadata.finish_session(session_key)`
    - `metadata_commands.cancel_session(self.group.db, session_key)` → `metadata.cancel_session(session_key)`
    - `metadata_commands.reserve_idempotency_key(self.group.db, ...)` → `metadata.reserve_idempotency_key(...)`
    - `metadata_commands.record_audit_event(self.group.db, ...)` → `metadata.record_audit_event(...)`

- [ ] Task 5.1: 在 use_cases 中固化“投票会话状态推进”关键动作（供 facade 调用）
  - File: `src/application/use_cases/vote_start.py`
  - Action: 定义 `start_vote_session(...)`：创建 session + 记录 `vote_start` 审计 +（可选）清理过期 session
  - File: `src/application/use_cases/vote_finish.py`
  - Action: 定义 `finish_vote_session(...)`：finish session + 记录 `vote_finish` 审计
  - Notes: 交互（等待输入/发送消息）仍在 interfaces；use_case 只负责“元数据写入与一致性”

- [ ] Task 6: 将 VoteController 依赖注入 vote_metadata，并切断对 services.metadata_commands 的依赖
  - File: `src/interfaces/nonebot/vote_runtime.py`
  - Action: 删除 `from src.services import metadata_commands`
  - Action: `VoteController` 构造函数新增参数 `metadata: VoteMetadataFacade`
  - Action: 将 `_reserve_side_effect/_record_side_effect_audit/会话推进` 相关调用全部替换为 `metadata.*`
  - Notes: nonebot 的交互（wait_for / wait_for_event / 发送消息）仍保留在 interfaces；状态推进/幂等/审计通过 facade 完成

- [ ] Task 7: 在 VoteService 中装配依赖（首切片装配点）
  - File: `src/application/services/vote_service.py`
  - Action: 在创建 `VoteController` 前构造 ports 实现（sqlite_*_repository）并构造 `VoteMetadataFacade`，传入控制器
  - Notes: 这是临时装配点；后续可迁移到 `interfaces/nonebot/composition_root.py`

#### 第二阶段：迁移其他调用点并一次性删除 src/services（1A）

- [ ] Task 8: 迁移 internal_api（bot nonce/user/session）脱离 services.metadata_commands
  - File: `src/plugins/nonebot_plugin_internal_api/__init__.py`
  - Action: 替换 `from src.services import metadata_commands`，改为 `from src.application.commands import metadata_commands`
  - Notes: 本次以“删除 services 兼容层”为目标，internal_api 暂不新增 bot_identity contract（避免扩大范围）

- [ ] Task 9: 迁移 topic/member_stats repository 脱离 services.metadata_commands
  - File: `src/infrastructure/persistence/topic_repository.py`
  - Action: 移除 `src.services.metadata_commands`；直接调用 `GroupDatabase.add_topic`（或改为依赖 `TopicRepository` 现有契约，不再借道 metadata_commands）
  - File: `src/infrastructure/persistence/member_stats_repository.py`
  - Action: 移除 `src.services.metadata_commands`；直接调用 `GroupDatabase.update_member_stats`

- [ ] Task 10: 迁移 ActivityService 脱离 services.metadata_commands
  - File: `src/application/services/activity_service.py`
  - Action: 替换 `from src.services import metadata_commands`，改为 `from src.application.commands import metadata_commands`
  - Notes: 该文件当前也依赖 interfaces（结构性债务）；本 task 只要求移除对 `src.services.metadata_commands` 的依赖，避免范围失控。若门禁脚本因此仍报 `application -> interfaces` 违规，本次切片允许通过 allowlist 临时豁免（必须写入 issue/清理期限），并在后续“目录边界收敛”切片处理。

- [ ] Task 11: 删除兼容层 `src/services`（最后一步，确保一次性删除）
  - File: `src/services/metadata_commands.py`
  - Action: 删除文件
  - File: `src/services/__init__.py`
  - Action: 删除文件
  - Notes: 删除前必须确认全库 `from src.services import metadata_commands` 搜索结果为 0

#### 门禁与测试（贯穿）

- [ ] Task 12: 更新门禁脚本 allowlist（仅过渡期、必须可清理）
  - File: `scripts/check_layer_imports.py`
  - Action: 若为迁移过渡需要 allowlist，必须添加具体文件路径 glob，并在注释中附 issue/原因/清理期限

- [ ] Task 13: 为首切片补单测（mock ports）并覆盖并发/幂等边界
  - File: `tests/test_vote_metadata_facade.py`
  - Action: mock `SessionRepository/IdempotencyRepository/AuditRepository/VoteRepository`，覆盖 happy path
  - File: `tests/test_session_version_conflict.py`
  - Action: 覆盖 `expected_version` 冲突行为（**必须返回 False**），并验证 step 与 data 不变
  - File: `tests/test_idempotency.py`
  - Action: 覆盖 idem_key 重复 reserve 的“已处理分支”（不重复副作用）

- [ ] Task 14: （移除）feature flag 清理步骤
  - Reason: 已不使用 feature flag 回退方案

### Acceptance Criteria

#### 门禁与依赖方向

- [ ] AC 1: Given 当前仓库，when 运行 `python scripts/check_layer_imports.py --root .`，then `src/interfaces/nonebot/vote_runtime.py` 与 `src/application/strategies/vote_core.py` 不再触发与 `src.services` 相关的违规（不再 import `src.services.metadata_commands`）。
- [ ] AC 2: Given 本次重构完成，when 全库搜索 `from src.services import metadata_commands`，then 搜索结果为 0，且删除 `src/services` 后应用仍可导入启动。
- [ ] AC 2.1: Given 本次切片目标，when 运行门禁脚本，then 允许存在已登记 allowlist 的“既有结构债务违规”（例如 `application -> interfaces`），但**不允许新增未登记的违规**，且 allowlist 必须带 issue 与清理期限。

#### 功能回归（Happy Path）

- [ ] AC 3: Given 群内发起“议题投票”，when 用户按提示完成投票并结束，then 会话创建→步骤推进→结束的关键行为与当前一致，且审计事件至少包含 `vote_start/vote_finish`。
- [ ] AC 4: Given 群内发起“禁言/放逐”投票，when 投票通过并执行副作用，then 同一 `idem_key` 的重复请求不会重复执行副作用，并在结果文本中体现“幂等拦截”（与当前行为一致）。

#### 边界与一致性（新增）

- [ ] AC 5: Given session version = N，when 调用 `update_session_step(... expected_version=N-1 ...)`，then **返回 False**，且 step 不推进、data 不被覆盖。
- [ ] AC 6: Given `idem_key` 已 reserve，when 再次 reserve 同 key，then 返回 False，且 vote 流程不会重复写审计/重复执行副作用。

## Additional Context

### Dependencies

- 底座数据能力：`src/plugins/nonebot_plugin_manager/database.py`（sqlite3）提供 sessions/idempotency/audit/vote_records 等能力。
- Web/API：`src/plugins/nonebot_plugin_internal_api/__init__.py` 通过 `nonebot.get_app()` 挂载 FastAPI router（保持不变，仅替换 metadata 调用入口）。
- 交互框架：nonebot/alconna 的等待输入与消息发送逻辑 **保持在 interfaces**，不进入 ports/use_cases。
- 回滚策略：不引入 feature flag；依赖提交/发布回滚作为回滚手段。
- `src/application/commands/metadata_commands.py` 的终态（明确）：本次切片不删除该文件；它会在第二阶段迁移完成后变为“仅供对照/历史”并最终在“metadata 能力域完全 ports 化”后删除（单独切片处理，避免扩大范围）。

### Testing Strategy

- 单元测试优先（快）：对 `VoteMetadataFacade` 与 vote use_cases 做 mock-ports 测试，覆盖 happy path + version 冲突 + idem_key 重复。
- 适配器测试（少量）：对 `sqlite_*_repository` 做最小行为测试（可使用临时 group_id 生成的 sqlite 文件，或 stub GroupDatabase）。
- 人工冒烟（必须）：在群里实际发起一次议题投票（通过）与一次禁言投票（通过），确认：
  - session step 推进/finish 正常
  - 幂等拦截重复副作用
  - audit_event 写入（可通过 DB 查询或临时 debug 输出）

**测试实现细节（避免“写不出来”）：**
- version 冲突：使用 fake `SessionRepository`（内存 dict）模拟 `version`，在第一次 `get_session` 返回 version=N，第二次 `update_session_step(expected_version=N-1)` 强制返回 False，并验证 data 未改变。
- 幂等重复：fake `IdempotencyRepository` 用 set 记录已 reserve 的 key；第二次 reserve 返回 False；断言：
  - 不调用 `AuditRepository.record_event`（或记录为 “idempotency_hit” 但不重复副作用，二选一需在实现中固定）
  - 不调用 side-effect 执行路径（vote_runtime 里对应分支不触发 ban/kick 等）

### Notes

- 风险点 1：`src/interfaces/nonebot/vote_runtime.py` 体积大且混杂交互与状态推进；策略是“接口层保留交互，用 facade + use_cases 收口元数据写入”，避免一次性抽完整编排导致范围爆炸。
- 风险点 2：`src/application/services/vote_service.py` 依赖 `src/interfaces/nonebot/vote_runtime.py`（application→interfaces）是既有结构债务；本次只保证切断 `src.services` 依赖，目录边界收敛留到后续架构治理切片。
- 约束提醒：仓库规则要求不要新增/保留 `from __future__ import annotations`；本 spec 不强制全库清理，但本次新增文件必须遵守。
- 约束落地策略（补充）：若必须改动“已包含 future annotations 的旧文件”，默认**不移除该导入**（避免超范围），但新增文件与新建包必须不包含该导入；如你希望顺手清理这些导入，需要你单独明确授权。
