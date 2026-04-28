---
project_name: "xuebao"
user_name: "Bylou"
date: "2026-02-06"
sections_completed:
  [
    "technology_stack",
    "language_rules",
    "framework_rules",
    "testing_rules",
    "quality_rules",
    "workflow_rules",
    "anti_patterns",
  ]
status: "complete"
rule_count: 27
optimized_for_llm: true
existing_patterns_found: 10
---

# Project Context for AI Agents

_本文件记录 AI 在本仓库实现代码时必须遵守的关键规则与既有模式（偏“容易踩坑/不明显”的内容），用于降低误改与回归风险。_

---

## Technology Stack & Versions

- Python：`^3.12`（Poetry；见 `pyproject.toml`）
- 依赖锁定：实现时以 `poetry.lock` 的解析结果为准（`pyproject.toml` 里大量 `*` 依赖不代表可假设“最新行为”）
- Bot 框架：`nonebot2 >=2.0,<3.0`（extras: `fastapi`），适配器：`nonebot.adapters.onebot.v11`
- Nonebot 插件（多为未 pin 版本；以 `poetry.lock` 为准）：`nonebot-plugin-alconna`、`nonebot-plugin-apscheduler`、`nonebot-plugin-waiter`、`nonebot-plugin-orm(default)`、`nonebot-plugin-datastore`、`nonebot-plugin-chatrecorder`、`nonebot-plugin-htmlrender`、`nonebot-plugin-cesaa`、`nonebot-plugin-saa` 等（见 `pyproject.toml [tool.nonebot]`）
- HTTP/AI：`aiohttp ^3.13.3`、`httpx >=0.26,<1.0`、`openai ^2.14.0`
- MCP SDK：`mcp == 1.26.0`（已加入 `pyproject.toml` 并写入 `poetry.lock`）
- 测试：`pytest ^8.3.0`（配置在 `pyproject.toml [tool.pytest.ini_options]`）

## Critical Implementation Rules

### Language-Specific Rules (Python)

- 不要新增 `from __future__ import annotations`；如需移除已有该行，必须先提示并征得确认（仓库约束）。
- 避免在测试/脚本中 `import src.plugins.nonebot_plugin_manager`（其 `__init__.py` import 时会注册 matcher/定时任务并触发 Nonebot driver 初始化，导致 `ValueError: NoneBot has not been initialized.`）。
- 测试若需要 `GroupDatabase`：用 `importlib.util.spec_from_file_location` 直接加载 `src/plugins/nonebot_plugin_manager/database.py`，避免触发插件包 import 副作用（现有测试已采用该模式）。
- 运行入口：`bot.py` 会 `nonebot.init()` + `load_from_toml("pyproject.toml")`；不要在模块 import 顶层依赖 `nonebot.get_driver()`（除非确定在 Nonebot 初始化之后）。

### Framework-Specific Rules (Nonebot2)

- 命令/消息入口优先走 `BaseService + @service_action/@service_message/...`，由 `src/application/services/service_manager.py` 收集并动态注册（见 `docs/CONTROL_MAP.md`）。
- 插件入口尽量保持薄：解析输入→调用 application/service/use_case→发送结果；避免在入口层直接写 SQL。
- 注意导入副作用：`src/plugins/nonebot_plugin_manager/__init__.py` 顶层会注册 handlers + 定时任务；库代码不要依赖它来拿工具函数（否则会在 import 时初始化 Nonebot 相关依赖）。

### Testing Rules

- `pytest`：用例测试必须可在未初始化 Nonebot 的情况下运行（避免 import 触发 driver 初始化）。
- 需要用到 `GroupDatabase` 的测试：使用 `GroupDatabase(group_id, data_root=tmp_path)` 把 sqlite 写到临时目录，禁止污染真实 `data/`。
- 不要 import `src.plugins.nonebot_plugin_manager` 包本身；如需 DB 类，直接用 `importlib` 从 `src/plugins/nonebot_plugin_manager/database.py` 加载（避免导入副作用）。
- 新增/改动业务逻辑优先写用例级单测（纯 Python），再做少量入口集成冒烟（如确有需要）。

### Code Quality & Style Rules

- 目录/模块边界：尽量遵循 `interfaces -> application -> domain` 的单向依赖；运行 `scripts/check_layer_imports.py` 作为门禁参考（历史债务允许 allowlist，但新代码别引入新的跨层依赖）。
- “共享 utils”优先就近放回所属用例/模块；只有跨域且纯通用才进 `src/core/`，并尽量仅依赖标准库（见 `docs/planning-artifacts/architecture.md`）。
- 命名与落点：新功能优先以 “use_case + service” 组织；Nonebot 入口只做薄适配。

### Development Workflow Rules

- 依赖变更：修改 `pyproject.toml` 后必须同步更新 `poetry.lock`（本仓库依赖大量 `*`，锁文件是事实真源）。
- 变更验证：至少跑 `poetry run pytest`；涉及分层依赖的改动，建议同时跑 `python scripts/check_layer_imports.py`（允许对历史债务加 allowlist，但新增代码应保持干净）。

### Critical Don't-Miss Rules

- 不要在会被测试导入的模块顶层触发 Nonebot 初始化（`nonebot.get_driver()` 等）；否则 `pytest` 收集期会报 `NoneBot has not been initialized.`。
- `src/plugins/nonebot_plugin_manager/__init__.py` 顶层副作用很重（注册 matcher/定时任务）；不要把它当成可复用库模块来依赖。
- DB 变更优先“可增量”：`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`，避免破坏现有群数据；迁移集中在 `GroupDatabase._migrate_schema()`。
- 幂等优先：涉及积分/荣誉/投票副作用等必须有 DB 级 gate（UNIQUE/PK）+ 幂等键（见 `docs/CONTROL_MAP.md`、`docs/DOMAIN_MODEL.md`）。

---

## Usage Guidelines

**For AI Agents:**

- 实现任何代码前先读本文件，并严格遵守全部规则。
- 有歧义时优先选择更保守/更少副作用的实现方案（尤其是 import 副作用、DB 迁移、幂等）。
- 若发现新模式/新坑，请同步更新本文件（保持精简）。

**For Humans:**

- 本文件只记录“AI 容易忽略/容易踩坑”的规则，避免堆通用常识。
- 技术栈或关键模式变更（依赖、入口方式、DB 迁移策略）后及时更新。

Last Updated: 2026-02-06
