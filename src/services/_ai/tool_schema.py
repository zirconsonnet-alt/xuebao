"""AI 工具 schema 获取辅助。"""

from contextlib import AsyncExitStack
from typing import Any, Dict, Iterable, List

from src.support.ai import build_mcp_tooling, coerce_server_configs, config
from src.support.core import tool_registry

from .common import _default_excluded_tool_names


class ToolSchemaMixin:
    def _filter_openai_tools_schema(
        self,
        tools: Iterable[Dict[str, Any]],
        exclude_tool_names: List[str] = None,
    ) -> List[Dict[str, Any]]:
        excluded = set(_default_excluded_tool_names)
        excluded.update(exclude_tool_names or [])
        if not excluded:
            return list(tools or [])

        filtered_tools: List[Dict[str, Any]] = []
        for tool in tools or []:
            function = tool.get("function") or {}
            if function.get("name") in excluded:
                continue
            filtered_tools.append(tool)
        return filtered_tools

    def _get_openai_tools_schema(
        self,
        *,
        exclude_categories: List[str],
        tools_enable: bool,
        context: Dict[str, Any],
        exclude_tool_names: List[str] = None,
    ) -> List[Dict[str, Any]]:
        if not tools_enable:
            return []
        effective_exclude_tool_names = list(_default_excluded_tool_names)
        effective_exclude_tool_names.extend(exclude_tool_names or [])
        mcp_tools = (context or {}).get("mcp_tools_schema") or []
        if mcp_tools:
            return self._filter_openai_tools_schema(mcp_tools, effective_exclude_tool_names)
        return tool_registry.get_openai_tools_schema(exclude_categories, effective_exclude_tool_names)

    async def _get_mcp_tools_schema_for_request(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        service_config = (context or {}).get("service_config") or {}
        raw_mcp_servers = service_config.get("mcp_servers", getattr(config, "mcp_servers", []))
        mcp_servers = coerce_server_configs(raw_mcp_servers)
        if not mcp_servers:
            return []

        try:
            async with AsyncExitStack() as stack:
                tooling = await build_mcp_tooling(servers=mcp_servers, exit_stack=stack)
                return list(tooling.get("mcp_tools_schema") or [])
        except Exception as exc:
            print(f"[MCP] 获取 tools schema 失败：{exc}")
            return []


__all__ = ["ToolSchemaMixin"]
