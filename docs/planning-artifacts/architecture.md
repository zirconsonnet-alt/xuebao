---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - docs/planning-artifacts/prd.md
  - docs/brainstorming/brainstorming-session-20260206_040500.md
workflowType: 'architecture'
project_name: 'xuebao'
user_name: 'Bylou'
date: '2026-02-06'
lastStep: 8
status: 'complete'
completedAt: '2026-02-06'
---

# Architecture Decision Document（xuebao 重构）

本文档将 PRD 的范围与验收转化为**可执行、可验证、可持续演进**的架构决策，目标是让后续实现/迁移不会在边界与依赖上走偏。

## 1. 架构目标与约束

- 目标：单向依赖、用例中心、插件薄适配、可切片迁移、可回滚、可测试。
- 约束：保持可运行；避免一次性大爆炸迁移；先显式组合根再逐步引入 DI 容器化。

## 2. 分层与依赖方向（硬约束）

### 2.1 层级定义

- `interfaces`：入口适配层（Nonebot/事件/命令），负责把外部输入转换为 `application.dto`，调用 contracts/use_cases，并把结果呈现/发送。
- `application`：用例编排层，依赖 `domain`，通过 `ports` 抽象依赖外部能力。
- `domain`：业务规则内核（实体/值对象/策略），不依赖外部框架与网络库。
- `infrastructure`：外部系统实现（实现 `application.ports`），例如 HTTP Vision/LLM SDK、存储等。

### 2.2 依赖规则（必须通过门禁脚本验证）

- `interfaces.*` **禁止**直接 import `infrastructure.*`（应通过 use_case + ports）。
- `application.*` **禁止** import `interfaces.*` 与 `infrastructure.*`（只允许依赖 `domain.*` 与 `application.ports.*`）。
- `domain.*` **禁止** import `nonebot* / aiohttp / httpx / openai` 等外部框架模块（必须通过 ports 抽象）。

### 2.3 门禁落地

- 单一真源：`scripts/check_layer_imports.py`
- 执行方式：
  - 本地：`scripts/check_arch.ps1` 或 `scripts/check_arch.sh`
  - CI：直接调用 `python scripts/check_layer_imports.py`
- 例外策略：允许 allowlist（必须附 issue/原因，并设到期清理）。

## 3. 项目结构与模块边界

目标结构（与当前 `src/` 实际目录保持一致，逐步迁移填充）：

```text
src/
  domain/
  application/
    ports/
    use_cases/
    dto/
    contracts/
  infrastructure/
  interfaces/
    nonebot/
      composition_root.py
      runtime/
      presenters/
      plugins/
  plugins/            # 逐步收敛到 interfaces.nonebot.plugins
  core/               # 仅保留与业务无关的通用能力
```

关键约束：**任何“共享 utils”必须优先放回最近的用例/模块内，只有跨域且纯通用才允许进入 `core/`，并限制 `core/` 仅依赖标准库。**

## 4. 用例中心（Use Case First）

### 4.1 用例最小单元

每个用例目录至少包含：

- `dto.py`：输入/输出 DTO（与 contracts 使用的稳定数据结构）
- `use_case.py`：业务编排（纯逻辑，依赖 ports 契约）
- `policies.py`（可选）：策略/规则选择、重试/裁剪等可测试逻辑

### 4.2 用例输出口径

建议统一返回 `UseCaseResult`（或等价结构），包含：

- `messages_to_send`：待发送的消息/呈现数据
- `side_effects`：可执行副作用描述（写库/调度/缓存更新等）
- `audit/metrics`：审计信息与基础指标（可观测性）

接口层负责把 result 转为 Nonebot 的发送动作与副作用执行。

## 5. Ports 与适配器（Adapters）

### 5.1 Ports 划分原则

- 按“外部能力域”划分（Vision/LLM/Tools/Storage/Messaging/Scheduler…）
- 用例只依赖 Protocol/ABC（`application.ports.*`），不依赖具体实现

### 5.2 组合根（Composition Root）

- 位置：`src/interfaces/nonebot/composition_root.py`
- 策略：先显式装配（new + 传参），确保依赖关系可读可控；后续再引入 DI 容器化（保持构造签名稳定）。
- 生命周期：明确 scope（按 bot/按群/按请求）；避免共享状态导致串台。

## 6. 插件边界与稳定入口（Contracts）

- 插件入口只做：命令/事件注册、参数解析、DTO 构建、调用 `application.contracts`、结果呈现。
- contracts 对插件是稳定面：内部可以重构，但对外应尽量保持向后兼容（必要时版本化）。

## 7. 测试策略（最小金字塔）

- 用例单测（主力）：mock ports，覆盖业务编排与策略。
- Ports 契约测：验证适配器符合 ports 的行为契约（错误分类、超时、重试边界等）。
- 入口冒烟：少量用例在接口层打通（fake event / minimal bot context），确保集成不走偏。

## 8. 迁移策略与切片顺序（含回滚点）

### 8.1 切片顺序（推荐）

1) **vision**：最独立、最适合作为迁移模板  
2) **tool_invocation**：工具调用用例化 + ToolGateway  
3) **ai_chat**：编排器/状态/呈现层拆分（逐步抽离原巨石类）  
4) **group_admin**：按命令/事件逐个迁移

### 8.2 每条切片的 DoD（Definition of Done）

- 门禁脚本通过（无跨层 import）
- 用例单测通过（mock ports）
- 明确回滚点（feature flag 或保留旧入口）
- 关键日志/审计字段可追踪（至少 request_id/correlation id）

---

结论：以“门禁 + 用例切片 + 稳定 contracts + 组合根显式装配”为核心抓手，能在保持可运行的前提下，用最小风险把现有代码逐步收敛到可维护、可扩展、可测试的结构。

