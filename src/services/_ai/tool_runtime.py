"""AI 工具调用运行时入口。"""

from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.support.ai import get_official_llm_fallback_upstream_context, has_official_llm_fallback_upstream
from src.support.core import gate_hit, make_dict, match_any_keyword, match_any_pattern, tool_registry

from .common import (
    InvalidModelResponseError,
    _stream_only_models,
    extract_completion_message,
    reset_model_invalid_response_state,
)
from .tool_orchestration import ToolOrchestrationMixin


class AIAssistantToolRuntimeMixin(ToolOrchestrationMixin):
    def _get_last_user_text(self) -> str:
        for message in reversed(self.msg_list):
            if message.get("role") == "user":
                return message.get("content", "") or ""
        return ""

    def _select_gated_tool(self, user_text: str, assistant_text: str):
        if not user_text or not assistant_text:
            return None
        for tool in tool_registry.tools.values():
            gate = getattr(tool, "gate", None)
            if not gate:
                continue
            if gate_hit(gate, user_text, assistant_text):
                return tool
        return None

    def _pre_tool_gate_hit(self, gate: Dict[str, Any], user_text: str) -> bool:
        if not gate or not user_text:
            return False

        user_patterns = gate.get("pre_user_patterns") or []
        if user_patterns and match_any_pattern(user_patterns, user_text):
            return True

        user_keywords = gate.get("pre_user_keywords") or []
        return bool(user_keywords) and match_any_keyword(user_keywords, user_text)

    def _select_preferred_tool_for_user(
        self,
        user_text: str,
        *,
        exclude_categories: List[str] = None,
    ):
        if not user_text:
            return None

        excluded = set(exclude_categories or [])
        selected_tool = None
        selected_priority = float("-inf")
        for tool in tool_registry.tools.values():
            if tool.category in excluded:
                continue
            gate = getattr(tool, "gate", None)
            if not gate:
                continue
            if self._pre_tool_gate_hit(gate, user_text):
                try:
                    priority = int(gate.get("pre_route_priority") or 0)
                except (TypeError, ValueError):
                    priority = 0
                if selected_tool is None or priority > selected_priority:
                    selected_tool = tool
                    selected_priority = priority
        return selected_tool

    async def _call_api_with_forced_tool(
        self,
        model: str,
        context: Dict[str, Any],
        tool_name: str,
        exclude_categories: List[str],
        thinking_enable: bool,
    ) -> str:
        for attempt in range(2):
            try:
                if attempt == 1:
                    print(f"[工具调用] 模型 {model} 上一次强制工具调用返回无效响应，立即重试 1 次")
                return await self._call_forced_tool_once(
                    model=model,
                    context=context,
                    tool_name=tool_name,
                    exclude_categories=exclude_categories,
                    thinking_enable=(thinking_enable and attempt == 0),
                )
            except InvalidModelResponseError as exc:
                if attempt == 0:
                    print(f"[工具调用] 模型 {model} 强制工具调用返回无效响应，准备立即重试: {exc.reason}")
                    if exc.summary:
                        print(f"[API DEBUG] 模型 {model} 无效响应摘要: {exc.summary}")
                    continue

                self._log_invalid_model_response(model, exc, prefix="[工具调用]")
                fallback_model = self._get_official_fallback_model()
                if (
                    not fallback_model
                    or fallback_model == model
                    or not has_official_llm_fallback_upstream()
                ):
                    print("[工具调用] DeepSeek 官方兜底未配置可用上游，无法接管这次强制工具调用")
                    return "当前上游模型未返回有效响应，暂时无法完成这次工具调用，请稍后重试。"

                print(f"[工具调用] 模型 {model} 连续无效响应，切换到 DeepSeek 官方兜底 {fallback_model}")
                try:
                    fallback_client = get_official_llm_fallback_upstream_context(fallback_model).client
                    return await self._call_forced_tool_once(
                        model=fallback_model,
                        context=context,
                        tool_name=tool_name,
                        exclude_categories=exclude_categories,
                        thinking_enable=False,
                        client=fallback_client,
                    )
                except InvalidModelResponseError as fallback_exc:
                    self._log_invalid_model_response(
                        fallback_model,
                        fallback_exc,
                        prefix="[工具调用]",
                    )
                    return "DeepSeek 官方兜底也未返回有效响应，暂时无法完成这次工具调用，请稍后重试。"
                except Exception as fallback_exc:
                    print(f"[工具调用] DeepSeek 官方兜底调用失败: {fallback_exc}")
                    return "DeepSeek 官方兜底调用失败，暂时无法完成这次工具调用，请稍后重试。"

        return "当前上游模型未返回有效响应，暂时无法完成这次工具调用，请稍后重试。"

    async def _call_forced_tool_once(
        self,
        *,
        model: str,
        context: Dict[str, Any],
        tool_name: str,
        exclude_categories: List[str],
        thinking_enable: bool,
        client: Optional[OpenAI] = None,
    ) -> str:
        request_messages = self._build_request_messages()
        request_params = {
            "model": model,
            "messages": request_messages,
            "temperature": self.temperature,
        }
        if thinking_enable:
            request_params["extra_body"] = {"enable_thinking": True}

        mcp_tools = await self._get_mcp_tools_schema_for_request(context)
        schema_context = dict(context)
        if mcp_tools:
            schema_context["mcp_tools_schema"] = mcp_tools
        tools = self._get_openai_tools_schema(
            exclude_categories=exclude_categories,
            tools_enable=True,
            context=schema_context,
        )
        if not tools:
            return "当前未加载可用工具，无法强制工具调用。"

        request_params["tools"] = tools
        request_params["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_name},
        }

        client = client or self._get_client_for_model(model)
        if model in _stream_only_models:
            return await self._call_api_stream(
                request_params,
                context,
                client,
                model,
                exclude_categories,
                True,
                thinking_enable,
            )

        response = client.chat.completions.create(**request_params)
        if isinstance(response, str):
            reset_model_invalid_response_state(model)
            self.add_message(make_dict("assistant", response))
            return response

        message = extract_completion_message(response)
        reset_model_invalid_response_state(model)
        if message.tool_calls and self.tools_enable:
            return await self._run_tool_loop(
                first_message=message,
                context=context,
                model=model,
                client=client,
                temperature=request_params.get("temperature", self.temperature),
                exclude_categories=exclude_categories,
                tools_enable=True,
                thinking_enable=thinking_enable,
            )

        this_reply = message.content or ""
        self.add_message(make_dict("assistant", this_reply))
        return this_reply

    async def _enforce_tool_gate(
        self,
        user_text: str,
        assistant_text: str,
        context: Dict[str, Any],
        model: str,
        exclude_categories: List[str],
        thinking_enable: bool,
    ) -> Optional[str]:
        if context.get("tool_gate_enforced") or not self.tools_enable:
            return None

        gated_tool = self._select_gated_tool(user_text, assistant_text)
        if not gated_tool:
            return None

        gate_prompt = gated_tool.gate.get(
            "system_prompt",
            f"检测到该请求需要使用工具 {gated_tool.name}。必须调用工具并返回真实结果，禁止仅用文字敷衍。",
        )
        self.add_message(make_dict("system", gate_prompt))

        forced_context = dict(context)
        forced_context["tool_gate_enforced"] = True
        return await self._call_api_with_forced_tool(
            model=model,
            context=forced_context,
            tool_name=gated_tool.name,
            exclude_categories=exclude_categories,
            thinking_enable=thinking_enable,
        )


__all__ = ["AIAssistantToolRuntimeMixin"]
