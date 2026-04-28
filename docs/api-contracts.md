---
project: xuebao
type: contracts
generated_at: "2026-02-06"
---

# API / 命令契约（运行期入口清单）

> 本项目主要对外接口是 Nonebot 命令/事件；另有内部 HTTP 接口用于 bot 对接与账号同步。

## 1. Nonebot 命令（service_action）

命令注册由 `src/plugins/nonebot_plugin_manager/__init__.py` 动态完成（读取 `BaseService` 子类上的 `@service_action` 元数据）。

已实现（部分示例，完整以服务代码为准）：

- 投票：`发起议题`、`发起放逐`、`发起禁言`、`发起投票`（`src/application/services/vote_service.py`）
- 经济系统：`签到`（`src/application/services/sign_in_service.py`）
- 群服务面板：`群服务`（插件内 `on_command`）
- 群活动：`群活动`（插件内 `on_command`）
- 撤回：`撤回`（插件内 `on_command`）

## 2. 交互式流程（投票 runtime）

- 议题投票：`src/interfaces/nonebot/vote_runtime.py`
  - TopicStrategy：先校验 points>=5 → 收集 topic → 创建 topic_id 并扣费 → 等待投票 → 投票成功时首次参与发 honor（幂等）

## 3. 内部 HTTP（若启用）

参照 `docs/CONTROL_MAP.md` 的描述：

- `/internal/*`：Bot 对接鉴权与账号同步（签名 + nonce）
- `/auth/login`：网页登录换取 session cookie

