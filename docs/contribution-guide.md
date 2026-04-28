---
project: xuebao
type: contribution-guide
generated_at: "2026-02-06"
---

# 贡献指南（最小）

- 修改依赖：同步更新 `pyproject.toml` 与 `poetry.lock`
- 新增/修改功能：优先写用例级单测；跑 `poetry run pytest` 全绿
- 涉及分层依赖：建议跑 `python scripts/check_layer_imports.py`；新代码避免引入新的跨层依赖
- DB 变更：优先增量迁移；逻辑集中在 `GroupDatabase`（不要在入口层直接写 SQL）

