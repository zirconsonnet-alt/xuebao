---
project: xuebao
type: inventory
generated_at: "2026-02-06"
---

# 组件/模块清单（高层）

## 1. 启动与插件

- 启动：`bot.py`
- 主插件：`src/plugins/nonebot_plugin_manager/__init__.py`（动态注册 service handlers、定时任务、私聊 AI 等）
- 内部 HTTP：`src/plugins/nonebot_plugin_internal_api`（若启用）

## 2. 服务层（application/services）

服务命令由 `src/application/services/service_manager.py` 统一收集并注册。常见服务：

- Vote：`src/application/services/vote_service.py`（投票入口；运行时适配在 `src/interfaces/nonebot/vote_runtime.py`）
- SignIn：`src/application/services/sign_in_service.py`（签到）
- AI/Vision/Info 等：`src/application/services/*`

## 3. 用例层（application/use_cases）

- 经济系统：
  - `src/application/use_cases/sign_in.py`
  - `src/application/use_cases/topic_economy.py`
  - `src/application/use_cases/award_honor_for_topic_vote.py`
- 其他：投票审批公告等（例如 `approve_topic_and_refresh_notice.py`）

## 4. 持久化与数据

- `GroupDatabase`：`src/plugins/nonebot_plugin_manager/database.py`（SQLite schema + 操作）
- re-export：`src/infrastructure/persistence/group_database.py`
- 仓储适配：`src/infrastructure/persistence/*_repository.py`

