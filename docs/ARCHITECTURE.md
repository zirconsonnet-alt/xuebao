---
project: xuebao
type: architecture
generated_at: "2026-02-06"
---

# 架构参考（可执行约束）

## 1. 分层与依赖方向（目标）

- `interfaces`：Nonebot 入口适配；尽量薄（解析输入/组装 DTO/调用 application；不直接写 DB）
- `application`：用例编排；通过 ports 访问外部能力；提供稳定入口（contracts/services）
- `domain`：业务规则；不依赖外部框架/网络库
- `infrastructure`：外部系统实现（HTTP/存储/持久化适配）

门禁脚本：`scripts/check_layer_imports.py`  
架构决策细节：`planning-artifacts/architecture.md`

## 2. 入口模式与副作用

- `src/plugins/nonebot_plugin_manager/__init__.py`：import 即注册 handlers + 定时任务（测试/脚本不要 import）
- Service 模式：`BaseService` + `@service_action`，由 `service_manager` 统一收集并注册（见 `docs/CONTROL_MAP.md`）

## 3. 数据与幂等

- 群内 SQLite：`GroupDatabase`（每群一个 db 文件）
- 核心幂等：`idempotency_keys` + 业务侧 gate（UNIQUE/PK）
- 经济系统：统一账本 `points_ledger`（points/honor），以及签到/议题/投票的幂等表

## 4. 迁移策略建议

- 新功能优先落在“use_case + service”，入口层保持薄适配
- DB 变更以增量方式进行（`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`），迁移逻辑集中到 `GroupDatabase._migrate_schema()`

