---
project: xuebao
type: project-documentation
scan_level: exhaustive
generated_at: "2026-02-06"
---

# xuebao 项目文档索引（Brownfield）

本索引是 AI 辅助开发与后续 PRD/架构演进的入口。仓库定位：Nonebot2 机器人（群管理 + AI 助手），以“服务层 + 用例层 + 分层门禁”逐步收敛。

## 快速开始

- 启动：`python bot.py`
- 测试：`poetry run pytest`
- 分层门禁：`python scripts/check_layer_imports.py`

## 文档导航（生成/维护）

- 项目总览：`project-overview.md`
- 源码结构：`source-tree-analysis.md`
- 架构参考：`architecture.md`
- 组件/模块清单：`component-inventory.md`
- API/命令契约：`api-contracts.md`
- 数据模型（SQLite）：`data-models.md`
- 开发指南：`development-guide.md`
- 部署指南：`deployment-guide.md`
- 贡献指南：`contribution-guide.md`
- AI 规则（LLM 上下文）：`project-context.md`

## 现有规划工件（可直接引用）

- `planning-artifacts/prd.md`（重构 PRD）
- `planning-artifacts/architecture.md`（重构架构决策）
- `planning-artifacts/prd-economy-mvp.md`（经济系统 MVP PRD）
- `planning-artifacts/epics.md`（经济系统 Epics/Stories/AC）

## 运行期关键提示

- `src/plugins/nonebot_plugin_manager/__init__.py` 顶层会注册 matcher/定时任务；测试或脚本不要 import 它（会触发 Nonebot 初始化依赖）。

