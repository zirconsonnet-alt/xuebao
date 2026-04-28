---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
inputDocuments:
  - docs/brainstorming/brainstorming-session-20260206_040500.md
workflowType: 'prd'
status: 'complete'
completedAt: '2026-02-06'
---

# Product Requirements Document - xuebao（重构项目结构）

**Author:** Bylou  
**Date:** 2026-02-06

## 执行摘要

本 PRD 定义对现有 `xuebao`（Nonebot2 群管理 + AI 助手）进行结构性重构的目标、范围与验收标准，核心产出是：**单向依赖的分层架构 + 用例中心的模块边界 + 可执行的依赖门禁 + 可回滚的增量迁移路线 + 最小测试骨架**。本次重构优先提升可维护性与开发效率，并确保在重构过程中持续可运行、可回滚。

## 背景与问题

当前代码库已具备 `domain/application/interfaces/infrastructure` 等目录雏形与部分 ports/组合根骨架，但仍存在：

- 架构约束可能仅停留在文档，缺少“机器可验证”的门禁；
- 业务逻辑、编排逻辑、适配逻辑可能交织，导致修改牵一发动全身；
- 迁移缺少明确“切片”与阶段性回滚点，重构风险高；
- 测试与可观测性口径不统一，回归成本较高。

## 目标（Goals）

- **G1：单向依赖可验证**：把 `interfaces -> application -> domain` 的规则落地为脚本/CI 门禁。
- **G2：用例中心可切片迁移**：以用例为最小重构单元，先打通 1 条独立链路（Vision）作为迁移模板。
- **G3：插件薄适配**：插件入口仅负责路由/解析/组装 DTO/调用 `application.contracts`，禁止直达 domain/infrastructure。
- **G4：测试与回滚可操作**：形成“用例单测 + ports 契约测 + 少量冒烟”的最小测试金字塔，且每个切片都可回滚。

## 非目标（Non-Goals / Out of Scope）

- 一次性把所有业务插件/所有链路全部迁移到新结构；
- 立即引入复杂 DI 容器并全量容器化（允许先显式组合根，后续再做）；
- 建立完整可观测性平台（仅要求最小结构化日志与 correlation id 口径）。

## 成功指标（Success Criteria）

- **S1 门禁有效**：在 CI/本地运行 `scripts/check_layer_imports.py` 能阻止跨层 import；对正常代码无明显误报。
- **S2 首条切片可交付**：Vision 用例切片迁移完成且可运行；可通过 feature flag 或保留旧链路回滚。
- **S3 边界清晰**：插件只依赖 `application.dto` 与 `application.contracts`（或稳定 facade）；`application` 不反向依赖 `interfaces/infrastructure`。
- **S4 回归成本下降**：Vision 用例具备可读、可维护的单测（mock ports），并有最小冒烟覆盖。

## 用户与利益相关者

- **主要用户（开发者）**：希望新增/修改功能不再牵连大量模块，能快速定位变更点与回归影响。
- **维护者（你自己/未来协作者）**：希望架构约束自动化、重构可增量推进、线上问题更易排查。

## 需求范围（Scope）

### In Scope（本期必须）

- 依赖门禁脚本（import-gate）与可集成 CI 的返回码；
- 明确的分层依赖规则与目录落点；
- `application.dto.Context` 与用例输出口径（建议 `UseCaseResult`）；
- Vision 切片迁移（作为模板切片）：入口→contracts→use_case→ports→infrastructure；
- 最小测试骨架：用例单测（mock VisionGateway）+ 必要的冒烟/契约策略。

### 依赖与约束

- Python 3.12 + Poetry；现有 Nonebot2 插件生态不应被破坏；
- 重构期间必须保持“可运行”，不接受长时间不可用的中间态；
- 允许新增脚本/测试/文档，但避免无关的大范围格式化改动。

## 里程碑（Milestones）

### M1（1–2 周）：可运行 + 可回滚 + 有门禁

- M1-1：完成 `scripts/check_layer_imports.py`，并在本地/CI 可一键运行；
- M1-2：完成 Vision 切片迁移打通（含回滚点）；
- M1-3：落地 `Context DTO + UseCaseResult` 口径；
- M1-4：补齐最小测试骨架与关键 happy path 覆盖。

## 功能性需求（Functional Requirements）

### FR-1 依赖门禁（Import Gate）

- 扫描范围：`src/**/*.py`（排除 `src/vendors/**` 等第三方/临时目录）
- 规则：
  - `src/interfaces/**` 禁止 import `src/infrastructure/**`
  - `src/application/**` 禁止 import `src/interfaces/**` 与 `src/infrastructure/**`
  - `src/domain/**` 禁止 import `nonebot*`、`aiohttp`、`httpx`、`openai` 等外部框架模块
- 输出：违规逐条打印到 stderr，退出码 `1`；无违规退出码 `0`

### FR-2 Contracts 作为插件稳定入口

- `application.contracts`（或等价 facade）提供插件唯一调用入口；
- 插件入口层禁止直接调用 domain/infrastructure；
- contracts 内部调用 use_cases，并通过 ports 使用外部能力。

### FR-3 Vision 切片迁移模板

- 提供一条完整链路示例（vision）：入口层适配 → contracts → use_case → VisionGateway（ports）→ HttpVisionGateway（infrastructure）
- 保留回滚点（feature flag 或保留旧入口）确保风险可控。

## 非功能性需求（Non-Functional Requirements）

- **NFR-1 可回滚**：每条迁移切片必须明确回滚方式，避免“灰色中间态”长期存在。
- **NFR-2 可维护**：架构约束可机器验证；新增模块必须清楚落点与依赖方向。
- **NFR-3 性能基线**：AI 链路（尤其编排）避免显著增加多次序列化/重复 I/O；必要时做 P95 对比。
- **NFR-4 兼容性**：对外（插件）稳定面优先向后兼容；破坏性变更必须有迁移指南。

## 风险与缓解

- 风险：ports 颗粒度失控 → 缓解：优先按“外部能力域”抽象；持续合并/拆分以可测试性为准。
- 风险：DI 生命周期不清导致状态串台 → 缓解：组合根先显式装配；明确 scope；引入 request_id/correlation id。
- 风险：门禁误报影响效率 → 缓解：提供 allowlist（必须附原因/issue），并设定清理机制。

## 验收（Acceptance）

- `scripts/check_layer_imports.py` 可在仓库根目录运行并按规则返回 0/1；
- Vision 切片链路可运行且可回滚；
- 至少 1 个用例单测（mock VisionGateway）通过；
- 架构与范围在 `docs/planning-artifacts/architecture.md` 中被落实为可执行决策与约束。

