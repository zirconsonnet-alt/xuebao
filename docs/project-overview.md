---
project: xuebao
type: overview
generated_at: "2026-02-06"
---

# 项目总览

## 1. 项目定位

`xuebao` 是基于 Nonebot2 + OneBot V11 的群管理机器人，提供：

- 群服务/群管理（活动、投票、头衔、文件、定时等）
- AI 助手（聊天/工具调用/视觉等）
- 内部 HTTP 接口（Bot 对接、鉴权与会话）

## 2. 入口与运行方式

- 启动入口：`bot.py`（`nonebot.init()` + `load_from_toml("pyproject.toml")`）
- 插件目录：`src/plugins`、`src/vendors`（见 `pyproject.toml [tool.nonebot]`）

## 3. 关键架构模式（当前与目标）

- 当前主入口插件：`src/plugins/nonebot_plugin_manager/__init__.py`
  - 顶层注册 matcher、动态注册 service handlers、初始化 apscheduler 定时任务（存在 import 副作用）
- 服务模式：`src/application/services/*` + `BaseService` + `@service_action`
  - `src/application/services/service_manager.py` 收集并动态注册命令（参见 `docs/CONTROL_MAP.md`）
- 分层收敛（目标约束）：`interfaces -> application -> domain`（门禁脚本：`scripts/check_layer_imports.py`；架构决策：`docs/planning-artifacts/architecture.md`）

## 4. 数据存储

- 群数据：`data/group_management/<group_id>/group_data.db`（SQLite，`GroupDatabase`）
- 账号对接：`data/internal_api.db`（SQLite，`InternalDatabase`）

## 5. 最近新增能力（经济系统 MVP）

- `points_ledger`：统一账本（points/honor），支持幂等写入与余额汇总
- `sign_in_records`：每日签到（自然日幂等）
- `topic_create_requests`：议题创建扣费幂等（同用户/同日/同内容）
- `topic_votes`：议题投票参与幂等（首次有效投票发 honor）

对应实现与测试均在 `tests/` 覆盖，`poetry run pytest` 全绿。

