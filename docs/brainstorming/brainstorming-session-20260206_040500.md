---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: '重构为最佳项目结构（Nonebot2 群管理 + AI 助手）'
session_goals: '产出可落地的架构方案（目录结构/模块边界/依赖方向/扩展与测试策略）'
selected_approach: 'user-selected'
techniques_used:
  - Six Thinking Hats
  - Mind Mapping
  - Yes And Building
  - Brain Writing Round Robin
ideas_generated: 20
technique_execution_complete: true
session_active: false
workflow_completed: true
context_file: ''
---

# 头脑风暴会话记录

**促成者：** Bylou  
**日期：** 2026-02-06 04:05:00

## Session Overview

**Topic：**重构为最佳项目结构（Nonebot2 群管理 + AI 助手）  
**Goals：**产出可落地的架构方案（目录结构/模块边界/依赖方向/扩展与测试策略）

### Session Setup

- 采用方式：User-Selected Techniques（用户自选技巧）

## Technique Selection

**Approach：**User-Selected Techniques  
**Selected Techniques：**

- `Six Thinking Hats`：用事实/情绪/收益/风险/创意/过程六视角全面扫描重构取舍
- `Mind Mapping`：把结构要素可视化发散，发现缺口与连接
- `Yes And Building`：在每个想法上持续加码扩展，快速堆量
- `Brain Writing Round Robin`：先静默写一批点子，再逐条接力改进

## Technique Execution（进行中）

### Six Thinking Hats｜白帽确认（事实 + 约束）

- 最优先目标：可维护性、开发效率
- 依赖规则：必须单向
- 插件边界：插件只通过接口调用应用服务
- 允许动作：允许拆包 / 引入 DI / 引入新模块
- 结构偏好：只保留“一套分层入口”；`src/plugins` 主要是业务插件；可用工具/CI 强制单向依赖

### Yes And Building｜基于你圈定的点子（#2/#3/#4/#5/#6/#8/#12）继续加码（第一批）

**[结构 #1]**: 插件=纯适配器 + 命令路由
_Concept_: 每个业务插件只做：注册命令/事件、解析输入、组装 `application.dto`、调用 `application.use_cases`；禁止直接 import `infrastructure/*` 与 `domain/*` 的实现细节。
_Novelty_: 把“插件只通过接口调用应用服务”落成硬规则：插件唯一依赖面是 `application.ports + application.dto`。

**[结构 #2]**: 用例包=最小可重构单元
_Concept_: 以“用例”为粒度拆包：例如 `application/use_cases/ai_chat/`、`.../vision/`、`.../group_admin/`；每个用例目录内部固定四件套：`dto.py`、`use_case.py`、`ports.py`（或引用公共 ports）、`policies.py`。
_Novelty_: 让重构工作可以按用例逐步迁移，不需要一次性搬全项目结构。

**[结构 #3]**: Ports 细颗粒化（按外部能力域）
_Concept_: `application/ports/` 分成 `llm.py`、`tts.py`、`media.py`、`search.py`、`storage.py`、`messaging.py`、`scheduler.py`…；用例只依赖这些 ports 的 Protocol/ABC。
_Novelty_: 用“能力契约”代替“服务类互相 import”，天然形成单向依赖与可替换实现。

**[结构 #4]**: AIAssistant 拆成编排器 + 会话状态 + 能力适配
_Concept_: 把 `AIAssistant` 的职责拆为：`ConversationState`（纯数据 + 规则）、`ChatOrchestratorUseCase`（编排 LLM/工具/策略）、`MessagePresenter`（把结果渲染成 nonebot 消息）。
_Novelty_: 巨石类拆成可单测的编排用例，开发效率提升来自“改一处不连坐”。

**[结构 #5]**: ServiceManager 变成“组合根”（Composition Root）
_Concept_: `ServiceManager` 只负责：构建 `GroupContainer`（DI scope），把 ports 的实现绑定进去；不再在文件顶部 import 一长串服务类，而是用注册表/模块发现加载。
_Novelty_: 把“实例管理 + 依赖装配”集中到入口层，减少应用层对具体实现的静态依赖。

**[结构 #6]**: 领域模型回归 + 以策略表达业务规则
_Concept_: 把“群上下文/权限/限流/会话策略”抽到 `domain/`（实体/值对象/策略接口）；`application` 负责调用；`interfaces` 提供外部上下文数据。
_Novelty_: 让业务规则从插件/服务里抽离，形成可复用、可推理的内核。

**[结构 #7]**: core.ai_tools 下沉为 application 能力（工具调用也是用例）
_Concept_: 把“工具注册/门控/执行”视作应用能力：`application/use_cases/tool_invocation/`；`core` 只保留无业务依赖的通用工具（如文本处理）。
_Novelty_: 工具链不再是“core 万能层”，而是可被测试与替换的用例编排。

**[结构 #8]**: 单向依赖的“硬门禁”落地（import 规则）
_Concept_: 建立层级映射：`interfaces|plugins -> application -> domain`，`infrastructure` 只能被 `application` 通过 ports 间接使用；用 `ruff` 或自定义脚本检测非法 import。
_Novelty_: 把架构约束从文档变成 CI 失败条件，长期可维护性直接受益。

**[结构 #9]**: “业务插件”分域 + 统一入口导出
_Concept_: `src/plugins/` 下按能力域分组（如 `ai/`、`group_admin/`、`media/`）；每个域只暴露一个 `plugin.py` 作为 Nonebot 注册入口，其它文件都只是内部适配器。
_Novelty_: 结构更像“产品能力地图”，新需求落点更直观。

**[结构 #10]**: 应用层输出“可回放”的用例结果
_Concept_: 用例返回统一结果对象（如 `UseCaseResult`），包含 `messages_to_send`、`side_effects`、`audit`；`interfaces` 负责把它转换成 Nonebot 发送动作。
_Novelty_: 把副作用外推，便于测试与回放，提升开发效率。

**[结构 #11]**: 以模块边界替代“共享 utils”
_Concept_: 把常见工具函数迁移到“离使用方最近的模块”（用例内私有），只有确实跨域复用的才放 `core/`，并限制 `core/` 只能依赖标准库。
_Novelty_: 防止 `core` 再次膨胀成隐形耦合中心。

**[结构 #12]**: 插件调用应用服务的“接口层”统一命名
_Concept_: 为每个用例提供显式入口接口（例如 `application/contracts/*.py` 或 `application/api/*.py`），插件仅调用这些 Facade；Facade 内部调用用例/ports。
_Novelty_: 对插件作者而言，“唯一正确入口”清晰可查，减少误用内部模块。

**[结构 #13]**: DI 分两步引入（先显式工厂，再容器）
_Concept_: 先建立 `interfaces/composition_root.py`（显式 new + 传参），把 ports 实现绑定到用例；稳定后再替换为 DI 容器（保持构造签名不变）。
_Novelty_: 避免一次性引入 DI 复杂度影响开发效率，同时为长远可维护性铺路。

**[结构 #14]**: 迁移路线=按用例切片（可并行重构）
_Concept_: 先从 `VisionService` 这种已独立的能力入手，把其入口迁到 `application/use_cases/vision/`；再逐步把 `AIAssistant` 里的功能按用例抽出，每次只改一条调用链。
_Novelty_: 重构不需要“大爆炸”，可持续交付与回滚。

**[结构 #15]**: 工程化收益域（正交切换：开发体验）
_Concept_: 建立 `make`/脚本：一键跑 `lint + import-graph-check + unit tests`；新增“新用例模板脚手架”（生成 `dto/use_case/tests`）。
_Novelty_: 把“开发效率”作为架构一等公民，通过脚手架把正确结构固化。

**[结构 #16]**: 测试策略域（正交切换：质量与速度）
_Concept_: 用例层做纯单测（mock ports），接口层做少量集成测（fake bot event），基础设施做契约测（对外 API 响应模拟）。
_Novelty_: 测试金字塔贴合单向依赖，既快又能覆盖关键逻辑。

**[结构 #17]**: “群/用户上下文”数据化（减少隐式全局）
_Concept_: 把 `GroupContext` 变成 `application.dto.Context`（纯数据：group_id/user_id/permissions/feature flags），由 interfaces 构建传入用例。
_Novelty_: 消除隐式依赖，单测更容易，结构边界更清晰。

**[结构 #18]**: 接口稳定性域（正交切换：兼容性）
_Concept_: 对外（插件）暴露的 Facade/Contracts 版本化（轻量：模块路径不变 + 向后兼容字段），内部实现随意重构。
_Novelty_: 兼顾重构自由与插件生态稳定。

**[结构 #19]**: 观测域（正交切换：可维护性）
_Concept_: 用例统一打结构化日志（用例名/输入摘要/耗时/ports 调用次数/异常分类），接口层补充群/用户维度追踪。
_Novelty_: 线上问题定位更快，维护成本下降。

**[结构 #20]**: 把“禁止跨层 import”变成开发期即时反馈
_Concept_: 除了 CI，再加 pre-commit 钩子或 IDE 规则，让开发者在本地就看到跨层 import 的提示与修复建议。
_Novelty_: 把架构治理从“事后纠错”变成“事前引导”，提升开发效率。

## 目录结构草案 v1（单入口 + 单向依赖 + 插件薄适配）

> 目标：`interfaces/nonebot` 作为唯一入口层；业务插件只做适配；业务逻辑以用例为中心；外部依赖全部经 ports 单向注入。

```text
src/
  domain/                         # 业务规则内核（不依赖 nonebot / aiohttp / openai 等）
    models/                       # 实体/聚合（如 Group、User、Conversation）
    value_objects/                # 值对象（如 RateLimitPolicy、ModelName）
    services/                     # 领域服务（纯业务）
    policies/                     # 策略/规则（限流、路由、权限等）
    events/                       # 领域事件（可选）

  application/                    # 用例编排层（依赖 domain；通过 ports 依赖外部）
    dto/                          # 用例输入/输出 DTO（插件/接口层唯一可见数据结构之一）
    ports/                        # Protocol/ABC：LLM/TTS/Storage/Search/Messaging/Media...
    use_cases/
      ai_chat/                    # 聊天编排（替代当前 AIAssistant 的“大部分业务编排”）
        dto.py
        use_case.py
        policies.py
      tool_invocation/            # 工具调用与门控（把 ai_tools 逻辑“业务化”）
      vision/                     # 视觉能力用例（对接 VisionService 的抽象能力）
      group_admin/                # 群管理能力用例（权限/群规/投票等）
      ...
    strategies/                   # 应用层策略实现（在 domain 策略之上做编排/选择）
    contracts/                    # 面向插件的 Facade/门面（可选：稳定入口，内部调用用例）

  infrastructure/                 # 外部系统实现（实现 application.ports）
    persistence/                  # DB/文件存储实现
    external/                     # 外部 API 客户端（如 Zhihu、LLM Provider）
    llm/                          # OpenAI SDK / upstream_factory 等落点
    media/                        # 图片/视频/语音相关实现

  interfaces/                     # 入口层（适配外部世界 -> 调用 application）
    nonebot/
      composition_root.py         # 组合根：装配 ports 实现、组装 use_cases（可逐步引入 DI）
      runtime/
        service_manager.py        # Bot 运行时容器/按群 scope 管理（替代当前集中注册的重耦合写法）
        context_builders.py       # event -> application.dto.Context
      presenters/                 # 用例结果 -> Nonebot 消息（UniMessage 等）
      plugins/                    # 业务插件入口（薄适配器：命令路由/参数解析/调用 contracts）
        ai/
          plugin.py
        group_admin/
          plugin.py
        media/
          plugin.py

  core/                           # 纯通用、不含业务依赖的工具库（尽量只依赖标准库）
    text_processing.py
    ...
```

### 关键依赖方向（口径）

- `interfaces.nonebot.*` -> `application.*` -> `domain.*`
- `application.*` 只能通过 `application.ports.*` 使用 `infrastructure.*` 的能力（不得反向 import 实现）
- 业务插件（`interfaces.nonebot.plugins.*`）只允许依赖：`application.dto`、`application.contracts`、`interfaces.nonebot.presenters`（禁止直达 domain/infrastructure）

## 最小落地模板（已在仓库生成）

- `application ports`（协议定义）：`src/application/ports/clock.py`、`src/application/ports/llm_gateway.py`、`src/application/ports/messaging_gateway.py`、`src/application/ports/tool_gateway.py`、`src/application/ports/vision_gateway.py`
- `composition root`（依赖装配骨架）：`src/interfaces/nonebot/composition_root.py`

说明：`composition_root.py` 里的 `llm/vision/tools` 目前是 `NotWired*` 占位实现，后续你可以逐步把现有 `upstream_factory + OpenAI SDK`、`VisionService`、`src.core.ai_tools` 适配成对应 ports 的真实实现。

### 已继续：VisionGateway 真实实现已接入

- 新增 `VisionGateway` 的 HTTP 实现：`src/infrastructure/vision/http_vision_gateway.py`（复用了现有 `config + get_upstream_context` 的调用方式）
- `src/interfaces/nonebot/composition_root.py` 已把 `vision` 装配为 `HttpVisionGateway`（`llm/tools` 仍保持占位，避免一次性引入过多改动）

## Idea Organization and Prioritization

### Thematic Organization（8 个主题收敛）

1) **分层与依赖方向（硬规则）**（#1 #8 #11 #20）  
决策点：`interfaces -> application -> domain`；`infrastructure` 只能被 `application` 通过 `ports` 间接使用；用脚本/CI 把规则变成“失败条件”。

2) **用例中心（可切片迁移）**（#2 #14 #10）  
决策点：以用例目录为最小迁移单元；用例返回 `UseCaseResult`（可回放/可测/副作用外推），接口层负责发送与落地副作用。

3) **Ports 设计与适配器策略**（#3 #7）  
决策点：按“外部能力域”拆 ports（LLM/Vision/Tools/Storage/Messaging…）；工具调用同样用例化，避免 `core` 变万能层。

4) **组合根 / DI 生命周期**（#5 #13 #17）  
决策点：先“显式组合根（new + 传参）”，稳定后再引入 DI 容器；明确 scope（按 bot/按群/按请求），用 `Context DTO` 去掉隐式全局。

5) **插件边界与 Facade（对插件稳定面）**（#1 #9 #12 #18）  
决策点：插件薄适配，只依赖 `application.dto + application.contracts`；contracts 作为“唯一正确入口”，对外稳定、可渐进版本化。

6) **领域内核与业务规则表达**（#6）  
决策点：权限/限流/路由/会话策略等业务规则尽可能表达为 `domain` 的实体/值对象/策略；`application` 做编排，`interfaces` 只做适配。

7) **测试金字塔（速度 + 质量）**（#16 #10）  
决策点：用例单测（mock ports）为主；ports 做契约测；接口层只保留少量冒烟/集成，保证迁移不走偏。

8) **工程化与可观测性**（#15 #19）  
决策点：把正确结构“工具化”（一键检查：lint/import-gate/tests）；用例统一结构化日志 + correlation id，降低重构期排障成本。

### Prioritization Results

**Top 3 Priority（高杠杆 + 降风险）**

1. **依赖门禁脚本（import-gate）**：把单向依赖从“约定”变成“硬约束”。（#8 #20）
2. **Vision 用例切片迁移跑通**：选最独立链路打通迁移套路与回滚点。（#14 + 当前已接入 VisionGateway）
3. **Context DTO + UseCaseResult 口径**：统一输入/输出边界，接口层只做适配与发送。（#10 #17）

**Quick Wins（短平快收益）**

- 插件入口统一只调用 `application.contracts`（#12），降低误用内部模块的概率。
- `core` 只保留标准库可复用工具，避免新“耦合中心”（#11）。

**Breakthrough Concepts（长期收益最大）**

- `UseCaseResult` 可回放：把副作用外推，极大提升可测试性与回归效率。（#10）
- CI 强约束依赖方向：长期可维护性从“文档”变成“机器可验证”。（#8 #20）

## Action Planning

### Milestone（1–2 周）：可运行 + 可回滚 + 有门禁

**M1-1：依赖门禁（import-gate）**

- 规则（最小可行）：
  - `src/interfaces/**` 禁止 import `src/infrastructure/**`
  - `src/application/**` 禁止 import `src/interfaces/**` 与 `src/infrastructure/**`（允许 import `src/application/ports/**`、`src/domain/**`）
  - `src/domain/**` 禁止 import `nonebot*`、`aiohttp`、`httpx`、`openai` 等外部框架
- 交付：`scripts/check_layer_imports.py` + CI 可直接调用的返回码（0/1）

**M1-2：Vision 切片迁移跑通**

- 插件/入口只调用 contracts（或稳定 Facade），用例层只依赖 ports。
- 用例单测覆盖 happy path（mock `VisionGateway`）。
- 门禁脚本全绿；出现问题可回滚到旧链路（保留旧入口/加 feature flag 二选一）。

**M1-3：Context DTO 与用例输出口径**

- `application.dto.Context` 明确字段：`group_id/user_id/permissions/feature_flags/request_id` 等。
- 用例统一返回 `UseCaseResult`，接口层负责发送与副作用执行（写库/发消息等）。

**M1-4：最小测试骨架**

- 用例单测（快）+ ports 契约测（稳）+ 入口冒烟（少量）。

### Migration Slices（建议顺序 + 回滚点）

1) **vision**（已具备真实 gateway 落点）  
回滚点：保留旧调用链/以 feature flag 切回。

2) **tool_invocation**（工具调用用例化 + ToolGateway 适配）  
回滚点：工具执行走旧 `core.ai_tools`，新链路并行对照。

3) **ai_chat**（编排器/状态/呈现层拆分）  
回滚点：保留原 AIAssistant 入口，逐步把子能力迁走。

4) **group_admin**（权限/群规/投票等）  
回滚点：按命令/事件逐个迁移，保持旧插件可用。

### Governance（避免“架构回退”）

- 门禁脚本是“硬门禁”，新增例外必须：
  - 写入 allowlist（附 issue/原因），并有到期清理机制；
  - 或通过重构消除跨层依赖（优先）。
- 对插件稳定面只暴露 `application.contracts`；插件禁止直达 `domain/infrastructure`。

## Session Summary and Insights

- **用例切片 + contracts + 门禁** 是“效率与可维护性”的最大杠杆：迁移可增量交付，架构可机器验证。
- 先打通 **Vision** 这条独立链路能快速建立“迁移套路”（目录落点、ports 契约、组合根装配、测试与回滚）。
- 通过 `Context DTO` 与 `UseCaseResult` 把接口层副作用外推，能显著降低回归成本，并让编排逻辑可单测。

**下一步建议（按 BMAD 顺序）：** 先产出 PRD（范围/验收/不做什么），再产出 Architecture（硬约束与可执行决策）。
