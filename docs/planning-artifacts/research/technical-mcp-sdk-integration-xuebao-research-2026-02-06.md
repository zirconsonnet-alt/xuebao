---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
workflowType: 'research'
lastStep: 5
research_type: 'technical'
research_topic: 'MCP Python SDK（mcp==1.26.0）在 xuebao（Nonebot2/FastAPI）中的接入与替换评估'
research_goals: '评估 mcp SDK 能力边界与接入方式；输出“现有手写工具/治理层”到 MCP Server/Client 的映射、迁移步骤、验收用例与风险清单'
user_name: 'Bylou'
date: '2026-02-06'
web_research_enabled: true
source_verification: true
---

# Research Report: technical

**Date:** 2026-02-06
**Author:** Bylou
**Research Type:** technical

---

## Research Overview

本报告聚焦于把 `mcp==1.26.0`（Model Context Protocol SDK）落到 xuebao 的现有技术栈（Python 3.12 / Nonebot2 / FastAPI/Starlette / Uvicorn），并回答：

1) `mcp` SDK 能替代你“手写 MCP 架构”的哪些部分（尤其是传输层、协议生命周期、schema 校验）
2) 哪些部分必须继续自研并作为你的“治理层/领域层”保留（权限、幂等、审计、策略、可观测）
3) MCP Server / MCP Client 的优先级与落地路径（MVP → 生产）

研究方法：
- 优先引用：MCP 官方规范、官方文档与官方 Python SDK（GitHub/PyPI）
- 对关键协议行为（Transport、Header、安全要求）以规范为准；SDK 细节以官方仓库为准

---

## Technical Research Scope Confirmation

**Research Topic:** MCP Python SDK（mcp==1.26.0）在 xuebao（Nonebot2/FastAPI）中的接入与替换评估  
**Research Goals:** 评估 mcp SDK 能力边界与接入方式；输出映射/迁移步骤/验收用例/风险清单

**Technical Research Scope:**

- Architecture Analysis - 分层边界、SDK/自研职责划分
- Implementation Approaches - 最小可行接入到生产化治理闭环
- Technology Stack - Python/ASGI/Starlette/Uvicorn + MCP SDK
- Integration Patterns - Tool/Resource/Prompt 与现有 tools 系统对接
- Performance Considerations - 并发、连接管理、超时/重试、背压、安全

**Scope Confirmed:** 2026-02-06

---

<!-- Content will be appended sequentially through research workflow steps -->

## Technology Stack Analysis

### Programming Languages

- **核心语言**：Python（MCP Python SDK 以 Python 作为 server/client 的官方实现之一，覆盖 MCP 协议与标准 transports）。参考：PyPI 项目描述与官方 SDK 仓库。  
  - Source: https://pypi.org/pypi/mcp  
  - Source: https://github.com/modelcontextprotocol/python-sdk
- **消息编码与协议**：MCP 使用 JSON-RPC；消息需 UTF-8 编码。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18

### Development Frameworks and Libraries

**1) MCP SDK 核心：FastMCP（server）**

- MCP Python SDK 提供 `FastMCP`，用于快速构建 MCP server（tools/resources/prompts）并处理连接、协议合规、消息路由。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

**2) ASGI/Starlette 生态适配（与 xuebao 高度兼容）**

- 官方 SDK 支持将 Streamable HTTP server 挂载到现有 ASGI 应用中（Starlette 例子），用于与已有 FastAPI/Starlette 路由共存。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

**3) Transports（传输层）：stdio 与 Streamable HTTP**

- MCP 规范在最新修订中定义两种标准 transport：`stdio` 与 `Streamable HTTP`。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Streamable HTTP**：客户端以 HTTP POST 发送每条 JSON-RPC 消息；服务端可返回 `application/json`（单响应）或 `text/event-stream`（SSE，多消息流）。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Session / Header 关键点**：
  - `Mcp-Session-Id`：服务端可在初始化响应中下发 session id；客户端后续请求携带此 header。  
    - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  - `MCP-Protocol-Version`：HTTP 场景客户端必须在后续请求中携带该 header（例如 `2025-06-18`）。  
    - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

**4) 安全要求（Streamable HTTP）**

规范明确给出安全警告：实现 Streamable HTTP 时服务端必须验证 `Origin` 以防 DNS rebinding，并建议本地只绑定 `127.0.0.1`，且应实施认证。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

### Database and Storage Technologies

MCP 协议与 SDK 不规定数据层；它只提供“对 LLM 应用暴露 Tools/Resources/Prompts 的标准接口”。因此：
- 你现有的 sqlite/GroupDatabase 继续可用；
- 重点是把“工具调用治理（权限/幂等/审计/策略）”从 interfaces/infrastructure 中抽出，放到 application/contracts + domain 不变量中，然后由 MCP tool handler 调用这些稳定入口。

### Development Tools and Platforms

- **调试工具**：MCP Inspector（通过 `@modelcontextprotocol/inspector`）可用于连接本地 MCP server。  
  - Source: https://pypi.org/project/mcp/
- **运行工具链**：官方仓库提供 `mcp run` / `mcp dev` 等开发体验（示例/脚手架以仓库为准）。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

### Cloud Infrastructure and Deployment

**生产建议（来自官方 SDK 仓库）**

- 官方仓库提示：Streamable HTTP transport 更推荐用于生产部署，并给出 `stateless_http=True`、`json_response=True` 作为“更可扩展”的配置方向（适用于无会话或轻会话场景、便于水平扩展）。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

### Technology Adoption Trends（对 xuebao 的可执行含义）

- 传输层不再自研：直接采用 MCP 的 Streamable HTTP / SSE / stdio（由 SDK 与规范兜底）。
- 自研重点转移到“治理层”：
  - tool 注册/目录：与现有 `src/core/ai_tools/registry.py` 对齐，输出 MCP tools 的 schema；
  - tool 执行：统一通过 `application/contracts` 收口（权限/幂等/审计/可观测）。

## Integration Patterns Analysis

> 本节的目标是把 MCP SDK（`mcp==1.26.0`）与 xuebao 现有工具系统（`src/core/ai_tools/*` + `ToolGateway` + `application/contracts`）做出“可实现的对接形态”，并把协议层与治理层分开。

### API Design Patterns（面向 MCP，而不是泛 REST/GraphQL）

**1) MCP 的“API 风格”本质是 JSON-RPC + 标准 primitives（Tools/Resources/Prompts）**

- MCP 不是让你重新发明一套 REST/GraphQL，而是约束“工具目录 + 工具调用”的标准消息流与数据类型（Tool / ToolResult）。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

**2) Transport 选择：优先 Streamable HTTP（生产），必要时兼容 SSE（旧）**

- MCP 规范把 `stdio` 与 `Streamable HTTP` 作为标准 transports，并说明 Streamable HTTP 可以用 `text/event-stream`（SSE）返回多条服务端消息。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- MCP Python SDK 文档明确：SSE transport 正在被 Streamable HTTP supersede（SDK 仍保留 `sse_app()` 以兼容）。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

**对 xuebao 的建议（可直接落地）**：

- **首选**：把 xuebao 暴露为 MCP Server（Streamable HTTP），作为“外部 LLM/Agent 客户端调用你工具”的统一入口。  
  - SDK：`FastMCP(...).streamable_http_app()` / `mcp.run(transport="streamable-http")`  
  - Source: https://modelcontextprotocol.github.io/python-sdk/
- **可选兼容**：若你需要兼容旧客户端/现有工具链，再额外挂载 `FastMCP(...).sse_app()`；但要注意多路径 mount 时的 messages endpoint 前缀问题（社区已有反馈）。  
  - Source: https://github.com/modelcontextprotocol/python-sdk/issues/412

### Communication Protocols（在 xuebao 里怎么接入现有 FastAPI/Nonebot）

**1) 把 MCP 当成 interfaces 层协议适配器**

推荐边界（你“手写 MCP 架构”最容易写错的地方就是把边界写混）：

- MCP SDK（interfaces 适配层）：只负责协议/transport/生命周期（Streamable HTTP / SSE / stdio）
- xuebao 的治理层（application/contracts + domain 不变量）：权限、幂等、审计、策略、可观测
- 具体执行（ports + adapters）：DB/nonebot/HTTP/外部系统

**2) Streamable HTTP 必要 Header / Session 行为（实现要点）**

- `MCP-Protocol-Version`：HTTP 场景客户端必须在后续请求中携带该 header（例如 `2025-06-18`）。  
- `Mcp-Session-Id`：服务端可在初始化响应中下发 session id，客户端后续必须回传；服务端可用 404 驱动客户端重建会话。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

### Data Formats and Standards（把你现有 tools schema 变成 MCP tools）

**1) inputSchema：必须是 JSON Schema**

- MCP Tool 定义要求提供 `inputSchema`（JSON Schema），并可选 `outputSchema`；ToolResult 支持多种 content 类型。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

**对 xuebao 的建议：从现有 `ToolRegistry` 做“无损映射”**

- 你现有 `ToolRegistry.get_openai_tools_schema()` 输出的 parameters 本质就是 JSON Schema 风格，基本可以直接作为 MCP 的 `inputSchema`（只要确保是合法 JSON Schema）。  
- 执行层复用 `ToolRegistry.execute_tool(...)`，但将返回值转换成 MCP ToolResult（至少提供 `text` 类型 content，必要时补充 image/resource 等）。  
  - SDK/规范参考：  
    - https://modelcontextprotocol.io/specification/2025-06-18/server/tools  
    - https://github.com/modelcontextprotocol/python-sdk

### System Interoperability Approaches（MCP Server / MCP Client 各怎么对接）

**A) MCP Server（推荐优先做）**

用途：让外部客户端（Claude Desktop / 自研 agent / 其它 LLM app）通过 MCP 调用 xuebao 的工具与能力。

建议对接方式：

1) MCP handler 只做“参数解析 + 调用治理入口”，不要直接碰 `GroupDatabase` 或 nonebot bot 对象  
2) 治理入口固定为 `application/contracts`（例如你后续会做的 `ToolInvocationFacade`），内部再调用 ports/adapters  
3) Audit/Idempotency/Policy 在治理层统一执行（避免 tool handler 各写一份）

**B) MCP Client（第二阶段）**

用途：让 xuebao 主动去调用外部 MCP servers（相当于“把外部工具当成 ToolGateway”）。

建议对接方式：

- 新增 `McpClientToolGateway`（实现你现有 `src/application/ports/tool_gateway.py` 语义），内部用 MCP Python SDK 的 client/session 进行 `tools/list` + `tools/call`。
- 把“外部 MCP tools”融合进你现有的 tool registry（按 namespace 前缀隔离，例如 `mcp.<server>.<tool>`），并保留你自己的 policy/审计/预算控制面。
  - Source: https://github.com/modelcontextprotocol/python-sdk

### Integration Security Patterns（必须提前规划的安全门槛）

**1) Streamable HTTP 的安全警告（DNS rebinding）**

规范明确要求：
- 服务器必须验证 `Origin` 以防 DNS rebinding；
- 本地运行建议仅绑定 `127.0.0.1`；
- 应实施认证。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

补充：社区也有基于 SSE transport 的 DNS rebinding 漏洞案例，进一步说明“Origin/Host 校验 + 认证”是必须项而不是可选项。  
- Source: https://mcpsec.dev/advisories/2025-10-06-vet-mcp-dns-rebinding/

**2) 授权机制（建议按规范走 OAuth 2.1，或先用内网 token 过渡）**

- MCP Authorization 规范定义了基于 OAuth 2.1 的授权方式与 Bearer token 用法。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

对 xuebao 的落地顺序建议：

1) MVP：仅本机/内网暴露（127.0.0.1 或内网 IP），使用静态 token + allowlist Origin
2) 生产：OAuth 2.1 / 企业统一认证 + tool 权限映射到你 domain policy（群/用户/角色）

## Architectural Patterns and Design

### System Architecture Patterns

本节只讨论“把 MCP SDK 体系接进 xuebao”时真正会影响实现的架构形态（而不是泛泛的微服务/单体对比）。

**模式 A：In-process MCP Server（推荐第一阶段）**

- 形态：在同一个进程里把 MCP server 作为 ASGI 子应用挂载到 FastAPI/Starlette（与 nonebot.get_app() 共存）。
- 优点：最少改动、最容易复用现有 service/tool 注册与 group 上下文、调试成本低。
- 风险：如果工具执行会阻塞事件循环（长耗时 CPU 或同步 I/O），需要额外隔离（线程池/子进程）；否则会影响 MCP 与 bot 本体吞吐。
- 关键实现点：
  - 使用 MCP Python SDK 提供的 FastMCP 与 Streamable HTTP 挂载方案；
  - 若希望水平扩展，倾向 `stateless_http=True` 并把状态下沉到你自己的存储（审计/幂等/会话）。
  - Source: https://github.com/modelcontextprotocol/python-sdk

**模式 B：Sidecar/独立 MCP Server（推荐第二阶段）**

- 形态：将 MCP server 独立为单独进程/容器，通过网络调用 xuebao 的“治理入口”（例如将 `application/contracts` 暴露为内部 API）。
- 优点：隔离故障域、可独立扩缩容、可独立做安全边界（mTLS、网关、WAF）。
- 风险：需要维护内部 API/消息协议与一致性语义（审计/幂等/重试）以及更复杂的部署拓扑。

**模式 C：xuebao 作为 MCP Client 聚合器（外部工具市场）**

- 形态：xuebao 作为 MCP client 调用外部 MCP servers，把外部 tools “纳入你自己的工具目录”。
- 关键点：外部 tool 必须纳入你的 policy/审计/预算控制面；否则会绕过既有治理规则。
- Source: https://github.com/modelcontextprotocol/python-sdk

### Design Principles and Best Practices

**1) 协议适配与治理分离（强约束）**

- MCP handler 只负责：参数解析 → 调用治理入口 → 组装 MCP ToolResult。
- 任何权限判断、幂等、审计、速率/预算、敏感字段脱敏，必须在“治理层”统一做（推荐放到 `application/contracts`，并以 domain 不变量约束）。
- Source: https://modelcontextprotocol.io/specification/2025-06-18

**2) Tool 定义单一来源（Single Source of Truth）**

- 你当前 `src/core/ai_tools/registry.py` 已是工具事实来源（name/description/parameters/handler/permission/gate）。
- MCP tool 列表生成逻辑只做“schema/返回格式转换”，不要复制一份工具定义（否则两边会漂移）。

**3) Schema 先行 + 输入严格校验**

- MCP Tools 要求 `inputSchema`（JSON Schema），并定义 tool 调用与结果结构。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

### Scalability and Performance Patterns

**1) Stateless 优先（便于水平扩展）**

- Streamable HTTP 允许 JSON response（单响应）或 SSE（多消息流）。多实例扩展时，建议尽量减少 server-side session 依赖，并将“状态”下沉到你自己的存储（会话表/审计表/幂等表）。
- SDK 侧提供 `stateless_http`、`json_response` 等配置开关，支持偏“无状态/可扩展”的部署倾向。  
  - Source: https://github.com/modelcontextprotocol/python-sdk

**2) 超时、取消与背压**

- tool 调用必须设置超时（客户端/服务端都要），并支持取消（避免长挂连接占用资源）。
- 对长耗时工具（vision/文件处理/外部 HTTP）做并发限制与背压，避免拖垮 bot 主循环。

### Integration and Communication Patterns

**1) 统一一个“Tool Invocation”应用层入口**

- 把 MCP tool 调用与“LLM tool-calling（OpenAI function tools）”统一走同一个应用层入口（例如 `ToolInvocationFacade`），从而只维护一套：权限、幂等、审计、错误分类、可观测。
- MCP server 与 LLM tool-calling 只是两种不同的“入口/适配层”。

**2) 结果返回双通道：人读 + 机读**

- ToolResult 支持多种 content 类型；建议同时返回：
  - 给人：简短文本（做了什么、结果是什么、是否幂等命中）
  - 给机：结构化结果（`success/message/data/audit_id/idempotency_hit`）
- Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

### Security Architecture Patterns

**1) Origin 校验与认证是底线**

- Streamable HTTP 规范明确：服务端必须校验 `Origin` 防 DNS rebinding，且应实施认证；本地服务建议绑定 `127.0.0.1`。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- 现实风险：已有 MCP（SSE transport）DNS rebinding 漏洞案例披露，说明“只在本机监听”仍不等于安全。  
  - Source: https://mcpsec.dev/advisories/2025-10-06-vet-mcp-dns-rebinding/

**2) 授权模型与 domain policy 对齐**

- MCP 规范定义 OAuth 2.1 授权（HTTP 场景）。你可以：
  - MVP：静态 token（内网）+ allowlist origin
  - 生产：OAuth 2.1 / 企业统一认证，并把 token identity 映射成 xuebao 的“群/用户/角色”策略
- Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

### Data Architecture Patterns

建议的最小数据面（与 xuebao 当前演进一致）：

- `idempotency_keys`：副作用幂等拦截（你在 vote 切片已验证价值）
- `audit_events`：记录 tool 调用开始/成功/失败、policy deny、side effect apply 等
- `sessions`：MCP session（协议层）不等于业务 session；业务仍按你自己的会话模型管理（例如 group flow session）

### Deployment and Operations Architecture

建议的上线方式：

1) 先以 In-process + Streamable HTTP 上线（路径固定），仅在受控网络范围内开放  
2) 最小观测：每次 tool call 记录 request_id/correlation_id、耗时、结果类型、幂等命中、policy 命中  
3) 再按负载与风险把 MCP server 拆成 sidecar（独立扩缩容 + 更强安全边界）

## Implementation Approaches and Technology Adoption

### Technology Adoption Strategies

**总体策略：Strangler Fig（渐进式替换）**

适用于你当前“已有一套 tools 系统 + 正在推进分层重构 + 想引入 MCP 生态”的现状：先建立一条新的、可治理的入口（MCP Server），让新入口逐步“包围并替代”旧路径，而不是一次性重写。  
- Source: https://martinfowler.com/bliki/StranglerFigApplication.html

**建议里程碑（按风险降低优先）**

- **M0（1–2 天）**：仅实现“可跑通的 MCP Server（Streamable HTTP）”
  - DoD：能启动；能列出 tools；能调用 1 个只读工具并返回 ToolResult（text content + structuredContent）。
- **M1（3–5 天）**：治理闭环最小集
  - DoD：静态 token + Origin allowlist；所有 tool call 写审计事件；对副作用工具强制幂等键；错误分类稳定（bad_request/denied/transient/permanent）。
- **M2（1–2 周）**：统一入口（MCP 调用与现有 LLM tool-calling 同一路径）
  - DoD：新增 `ToolInvocationFacade`（或同义 contracts）作为单一治理入口；MCP handler 与现有 tool 调用都走这条入口；幂等/审计/权限/预算策略只维护一份。
- **M3（后续）**：MCP Client 聚合外部 MCP tools
  - DoD：实现 `McpClientToolGateway`（适配 `ToolGateway`），将外部 tools 以 `mcp.<server>.<tool>` 注入 tool registry，并纳入 policy/审计/预算控制面。

### Development Workflows and Tooling

**依赖可复现（必须）**

- 将 `mcp` 写入 Poetry 依赖（避免“本地装了但团队/CI 复现不了”）。
- 为 MCP server 提供一键启动脚本（本地/CI-ready），并用 MCP Inspector 做黑盒联调。  
  - Source: https://pypi.org/project/mcp/

**代码结构（建议）**

- MCP 协议适配：放在 interfaces/plugins 层（ASGI 子应用/路由挂载）
- 治理入口：放在 `application/contracts`
- 执行依赖：放在 ports/adapters（DB、nonebot、外部 HTTP）

### Testing and Quality Assurance

**基于 OWASP LLM Top 10 的最小安全回归集**

工具调用系统至少要覆盖：
- Prompt Injection/Excessive Agency：外部输入不得直接越权触发高风险工具；高风险工具需额外确认/更严格 policy。
- Unbounded Consumption / Model DoS：对工具调用次数、并发、超时、预算做硬限制。
- Insecure Plugin Design：工具输入严格校验；工具访问控制要显式、可审计。  
  - Source: https://owasp.org/www-project-top-10-for-large-language-model-applications/

**测试金字塔（建议）**

- 单测（快）：对 `ToolInvocationFacade` 做 mock ports 测试（权限拒绝、幂等命中、副作用一次性、审计必达、错误分类）。
- 集成测（少量）：启动 MCP ASGI app，用 HTTP 走 Streamable HTTP 调用 1–2 个工具，覆盖：
  - 必要 header（`MCP-Protocol-Version` / `Mcp-Session-Id`）
  - token/Origin 拦截
  - 超时与取消

### Deployment and Operations Practices

**上线方式**

- MVP：仅本机/内网暴露（绑定 `127.0.0.1` 或内网），静态 token + Origin allowlist（满足规范的最小安全要求）。
- 生产：按 MCP Authorization 规范走 OAuth 2.1/统一认证，并把 identity 映射成你 domain policy（群/用户/角色）。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

**可观测性（最小字段）**

每次 tool call 建议记录：
- `request_id/correlation_id`
- `tool_name`
- `actor`（群/用户/角色）
- `policy_decision`（allow/deny + reason）
- `idempotency_hit`
- `duration_ms`
- `result_type`（success/failure/transient/permanent）

若要和行业对齐，可参考 OpenTelemetry GenAI semantic conventions（仍处于 development 状态，建议固定版本策略、避免“指标口径漂移”）。  
- Source: https://opentelemetry.io/docs/specs/semconv/gen-ai/

### Team Organization and Skills

最小人力拆分（避免一人扛所有导致质量下降）：
- 协议适配/安全：MCP server 挂载、Origin 校验、认证
- 治理入口：policy/幂等/审计/错误分类 + 单测
- 工具目录对齐：registry → MCP tools schema/ToolResult 映射

### Cost Optimization and Resource Management

- 限流：按群/用户/工具维度限流，避免“工具风暴”
- 预算：为工具定义 cost_class / side_effect_level，并在 policy 决策时结合预算
- 并发：对 vision/外部 HTTP 等长耗时工具做 semaphore 限制

### Risk Assessment and Mitigation

- Prompt Injection 无法彻底消除：用最小权限、明确 policy、幂等、审计、预算/限流把损失面压到可控。
- SSE/HTTP 暴露风险：Origin 校验 + 认证是底线；默认只在受控网络开放。  
  - Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  - Source: https://mcpsec.dev/advisories/2025-10-06-vet-mcp-dns-rebinding/
- 架构漂移风险：Tool 定义单一来源（registry），MCP 层只做转换。

## Technical Research Recommendations

### Implementation Roadmap（最终建议）

1) 先做 MCP Server（Streamable HTTP）+ 1 个只读工具联通
2) 引入 `ToolInvocationFacade`（治理入口），把审计/幂等/权限统一收口
3) 把 LLM tool-calling 与 MCP tool 调用统一到同一入口
4) 再做 MCP Client 聚合外部 tools

### Success Metrics and KPIs（建议用 DORA/Four Keys 口径）

DORA/Four Keys 常用指标包括：部署频率、变更前置时间、变更失败率、恢复时间（DORA 近期也讨论扩展到更多指标的演进）。  
- Source: https://dora.dev/guides/dora-metrics-four-keys/
- Source: https://cloud.google.com/blog/products/devops-sre/using-the-four-keys-to-measure-your-devops-performance

对 xuebao 可落地的 KPI（建议按“每个入口/每个工具”打点）：

- Deployment Frequency
- Lead Time for Changes
- Change Failure Rate（MCP/工具调用相关变更导致的故障占比）
- Time to Restore Service / Failed deployment recovery time
- 业务侧附加：tool 调用成功率、幂等命中率、policy deny 命中率、超时/预算超标次数
