---
project: xuebao
type: source-tree
generated_at: "2026-02-06"
---

# 源码结构分析

## 顶层目录

- `bot.py`：启动入口
- `pyproject.toml` / `poetry.lock`：依赖与锁定
- `src/`：主要源码
- `docs/`：文档（本索引与 brownfield 参考文档）
- `scripts/`：门禁脚本（分层 import 检查）
- `tests/`：pytest
- `data/`：运行期数据（sqlite、缓存等；不入库）

## `src/` 结构（关键目录）

- `src/plugins/`：Nonebot 插件（运行时注册入口；注意 import 副作用）
- `src/vendors/`：第三方/外部插件适配
- `src/application/`：应用层（services/use_cases/commands/contracts/ports/adapters/strategies）
- `src/interfaces/`：Nonebot 适配（vote_runtime、group_gateway、flow_runtime 等）
- `src/infrastructure/`：持久化与外部能力适配（persistence/storage 等）
- `src/domain/`：领域层（仍在逐步补齐）

## 测试组织

- `tests/test_*.py`：用例/门禁/存储相关测试
- 需要 DB 的测试通过 `GroupDatabase(group_id, data_root=tmp_path)` 隔离 sqlite 到临时目录
- 避免 import `src.plugins.nonebot_plugin_manager` 包（会触发 Nonebot 初始化依赖）

