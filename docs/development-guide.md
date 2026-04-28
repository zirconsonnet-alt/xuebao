---
project: xuebao
type: development-guide
generated_at: "2026-02-06"
---

# 开发指南

## 前置

- Python 3.12
- Poetry（依赖以 `poetry.lock` 为准）

## 常用命令

- 安装依赖：`poetry install`
- 启动：`python bot.py`
- 测试：`poetry run pytest`
- 分层门禁：`python scripts/check_layer_imports.py`

## 配置

- `.env` / `.env.dev`：运行配置入口
- LLM 配置：`src/settings/ai_assistant_config.py`（`api_key/base_url/model` 等）

## 测试注意事项

- 避免在测试里 import `src.plugins.nonebot_plugin_manager` 包（会触发 Nonebot 初始化依赖）
- 需要 DB 的测试使用 `GroupDatabase(group_id, data_root=tmp_path)` 隔离 sqlite 到临时目录

