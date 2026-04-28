---
project: xuebao
type: deployment-guide
generated_at: "2026-02-06"
---

# 部署指南（最小）

当前仓库未内置 CI/CD 配置（未见 `.github/workflows` 等）。建议部署方式以“运行 bot.py + 环境变量/配置文件”为核心。

## 运行

- 入口：`python bot.py`
- 配置：`.env` / `.env.dev`（以及 `BOT_API_*` 等内部接口变量，详见 `docs/README.md`）

## 数据

- `data/` 目录包含 sqlite 与缓存；建议做持久化挂载与备份策略（至少对 `data/group_management/**`、`data/internal_api.db`）。

