"""AI 工具编排辅助。"""

from contextlib import AsyncExitStack
from typing import Any, Dict, List

from openai import OpenAI

from src.support.ai import build_mcp_tooling, coerce_server_configs, config

from .tool_backends import ToolBackendMixin


class ToolOrchestrationMixin(ToolBackendMixin):
    async def _run_tool_loop(
        self,
        *,
        first_message,
        context: Dict[str, Any],
        model: str,
        client: OpenAI,
        temperature: float,
        exclude_categories: List[str],
        tools_enable: bool,
        thinking_enable: bool,
    ) -> str:
        service_config = (context or {}).get("service_config") or {}
        backend = (
            service_config.get("tool_orchestrator")
            or getattr(config, "tool_orchestrator", "internal")
            or "internal"
        ).strip().lower()
        if backend not in ("internal", "langgraph"):
            backend = "internal"

        async with AsyncExitStack() as stack:
            merged_context = dict(context or {})
            raw_mcp_servers = service_config.get("mcp_servers", getattr(config, "mcp_servers", []))
            mcp_servers = coerce_server_configs(raw_mcp_servers)
            if mcp_servers:
                try:
                    tooling = await build_mcp_tooling(servers=mcp_servers, exit_stack=stack)
                    merged_context.update(tooling)
                except Exception as exc:
                    print(f"[MCP] 初始化失败：{exc}")

            if backend == "langgraph":
                try:
                    return await self._run_tool_loop_langgraph(
                        first_message=first_message,
                        context=merged_context,
                        model=model,
                        client=client,
                        temperature=temperature,
                        exclude_categories=exclude_categories,
                        tools_enable=tools_enable,
                        thinking_enable=thinking_enable,
                    )
                except Exception as exc:
                    print(f"[LangGraph] 执行失败，降级 internal：{exc}")

            return await self._run_tool_loop_internal(
                first_message=first_message,
                context=merged_context,
                model=model,
                client=client,
                temperature=temperature,
                exclude_categories=exclude_categories,
                tools_enable=tools_enable,
                thinking_enable=thinking_enable,
            )

    def _get_tool_max_rounds(self, context: Dict[str, Any]) -> int:
        service_config = (context or {}).get("service_config") or {}
        max_rounds = service_config.get("tool_max_rounds", getattr(config, "tool_max_rounds", 3))
        try:
            max_rounds = int(max_rounds)
        except Exception:
            max_rounds = 3
        if max_rounds < 1:
            max_rounds = 1
        if max_rounds > 8:
            max_rounds = 8
        return max_rounds

__all__ = ["ToolOrchestrationMixin"]
