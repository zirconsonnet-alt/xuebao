"""AI 工具执行后端。"""

import json
from typing import Any, Dict, List, TypedDict

from openai import OpenAI

from src.support.ai import get_official_llm_fallback_upstream_context, has_official_llm_fallback_upstream
from src.support.core import make_dict

from .common import (
    InvalidModelResponseError,
    _strip_model_thought,
    extract_completion_message,
    reset_model_invalid_response_state,
)
from .tool_execution import ToolExecutionMixin
from .tool_schema import ToolSchemaMixin


class _ToolLoopState(TypedDict):
    current_message: Any
    tool_summaries: List[str]
    rounds_used: int


class ToolBackendMixin(ToolExecutionMixin, ToolSchemaMixin):
    @staticmethod
    def _make_fake_tool_loop_message(content: str):
        return type("FakeMessage", (), {"content": content, "tool_calls": None})()

    def _get_last_successful_tool_result_text(self) -> str:
        for record in reversed(self.msg_list):
            if record.get("role") != "tool":
                continue

            raw_content = str(record.get("content") or "").strip()
            if not raw_content:
                continue

            try:
                payload = json.loads(raw_content)
            except Exception:
                continue

            if not isinstance(payload, dict) or not payload.get("success", False):
                continue

            message = str(payload.get("message") or "").strip()
            if message and message != "执行成功":
                return _strip_model_thought(message)

            data = payload.get("data")
            if data is None:
                continue
            data_text = self._format_tool_data_for_user(data).strip()
            if data_text:
                return _strip_model_thought(data_text)

        return ""

    def _build_tool_loop_failure_reply(self, default_text: str) -> str:
        tool_result_text = self._get_last_successful_tool_result_text()
        if tool_result_text:
            return tool_result_text
        return default_text

    async def _call_tool_loop_model_once(
        self,
        *,
        model: str,
        client: OpenAI,
        request_params: Dict[str, Any],
    ):
        response = client.chat.completions.create(**request_params)
        if isinstance(response, str):
            reset_model_invalid_response_state(model)
            return self._make_fake_tool_loop_message(response)

        current_message = extract_completion_message(response)
        reset_model_invalid_response_state(model)
        return current_message

    async def _recover_tool_loop_after_invalid_response(
        self,
        *,
        failed_model: str,
        request_params: Dict[str, Any],
        default_failure_text: str,
    ):
        fallback_model = self._get_official_fallback_model()
        if (
            not fallback_model
            or fallback_model == failed_model
            or not has_official_llm_fallback_upstream()
        ):
            print("[工具调用] DeepSeek 官方兜底未配置可用上游，无法接管这次工具循环")
            return self._make_fake_tool_loop_message(
                self._build_tool_loop_failure_reply(default_failure_text)
            )

        print(f"[工具调用] 模型 {failed_model} 连续无效响应，切换到 DeepSeek 官方兜底 {fallback_model}")
        fallback_params = dict(request_params)
        fallback_params["model"] = fallback_model
        fallback_params.pop("extra_body", None)

        try:
            fallback_client = get_official_llm_fallback_upstream_context(fallback_model).client
            return await self._call_tool_loop_model_once(
                model=fallback_model,
                client=fallback_client,
                request_params=fallback_params,
            )
        except InvalidModelResponseError as exc:
            self._log_invalid_model_response(fallback_model, exc, prefix="[工具调用]")
            return self._make_fake_tool_loop_message(
                self._build_tool_loop_failure_reply("DeepSeek 官方兜底也未返回有效结果，请稍后重试。")
            )
        except Exception as exc:
            print(f"[工具调用] DeepSeek 官方兜底调用失败: {exc}")
            return self._make_fake_tool_loop_message(
                self._build_tool_loop_failure_reply("DeepSeek 官方兜底调用失败，请稍后重试。")
            )

    async def _request_tool_loop_message_with_recovery(
        self,
        *,
        model: str,
        client: OpenAI,
        request_params: Dict[str, Any],
        log_label: str,
    ):
        default_failure_text = "工具执行完成，但上游模型暂时未返回有效结果，请稍后重试。"
        for attempt in range(2):
            try:
                if attempt == 1:
                    print(f"[工具调用] 模型 {model} {log_label}上一次返回无效响应，立即重试 1 次")
                return await self._call_tool_loop_model_once(
                    model=model,
                    client=client,
                    request_params=request_params,
                )
            except InvalidModelResponseError as exc:
                if attempt == 0:
                    print(f"[工具调用] 模型 {model} {log_label}返回无效响应，准备立即重试: {exc.reason}")
                    if exc.summary:
                        print(f"[API DEBUG] 模型 {model} 无效响应摘要: {exc.summary}")
                    continue

                self._log_invalid_model_response(model, exc, prefix="[工具调用]")
                return await self._recover_tool_loop_after_invalid_response(
                    failed_model=model,
                    request_params=request_params,
                    default_failure_text=default_failure_text,
                )

        return self._make_fake_tool_loop_message(
            self._build_tool_loop_failure_reply(default_failure_text)
        )

    def _finalize_tool_loop_reply(self, reply: str) -> str:
        final_text = _strip_model_thought((reply or "").strip())
        if final_text:
            self.add_message(make_dict("assistant", final_text))
        return final_text

    async def _run_tool_loop_internal(
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
        max_rounds = self._get_tool_max_rounds(context)

        tool_summaries: List[str] = []
        current_message = first_message
        stopped_by_limit = True

        for _ in range(max_rounds):
            if not getattr(current_message, "tool_calls", None) or not tools_enable or not self.tools_enable:
                stopped_by_limit = False
                break

            if self._has_recorded_tool_results(current_message):
                print("[工具调用] 检测到当前 tool_call 已有历史结果，跳过重复执行")
                executed = {"user_text": "", "any_failed": False}
            else:
                executed = await self._execute_tool_calls(current_message, context)
                if executed.get("user_text"):
                    tool_summaries.append(executed["user_text"])

                if executed.get("any_failed"):
                    return ""

            tools = self._get_openai_tools_schema(
                exclude_categories=exclude_categories,
                tools_enable=tools_enable,
                context=context,
            )
            request_messages = self._build_request_messages()
            request_params = {
                "model": model,
                "messages": request_messages,
                "temperature": temperature,
            }
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"
            if thinking_enable:
                request_params["extra_body"] = {"enable_thinking": True}
            current_message = await self._request_tool_loop_message_with_recovery(
                model=model,
                client=client,
                request_params=request_params,
                log_label="在工具循环中",
            )

            if not getattr(current_message, "tool_calls", None):
                stopped_by_limit = False
                final_text = (current_message.content or "").strip()
                if not final_text:
                    return ""
                return self._finalize_tool_loop_reply(final_text)

        if stopped_by_limit:
            return self._finalize_tool_loop_reply("已达到最大工具调用轮数，已停止继续调用。")
        return ""

    async def _run_tool_loop_langgraph(
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
        from langgraph.graph import END, StateGraph

        max_rounds = self._get_tool_max_rounds(context)
        tools_schema = self._get_openai_tools_schema(
            exclude_categories=exclude_categories,
            tools_enable=tools_enable,
            context=context,
        )

        async def _node_tools(state: _ToolLoopState) -> Dict[str, Any]:
            message = state["current_message"]
            executed = await self._execute_tool_calls(message, context)
            summaries = list(state.get("tool_summaries") or [])
            if executed.get("user_text"):
                summaries.append(executed["user_text"])
            return {
                "tool_summaries": summaries,
                "rounds_used": int(state.get("rounds_used", 0)) + 1,
            }

        async def _node_model(state: _ToolLoopState) -> Dict[str, Any]:
            request_messages = self._build_request_messages()
            request_params = {
                "model": model,
                "messages": request_messages,
                "temperature": temperature,
            }
            if tools_schema:
                request_params["tools"] = tools_schema
                request_params["tool_choice"] = "auto"
            if thinking_enable:
                request_params["extra_body"] = {"enable_thinking": True}
            current_message = await self._request_tool_loop_message_with_recovery(
                model=model,
                client=client,
                request_params=request_params,
                log_label="在 LangGraph 工具循环中",
            )
            return {"current_message": current_message}

        def _should_continue(state: _ToolLoopState) -> str:
            message = state.get("current_message")
            rounds_used = int(state.get("rounds_used", 0))
            if rounds_used >= max_rounds:
                return "end"
            if not tools_enable or not self.tools_enable:
                return "end"
            if getattr(message, "tool_calls", None):
                return "continue"
            return "end"

        graph = StateGraph(_ToolLoopState)
        graph.add_node("tools", _node_tools)
        graph.add_node("model", _node_model)
        graph.set_entry_point("tools")
        graph.add_edge("tools", "model")
        graph.add_conditional_edges("model", _should_continue, {"continue": "tools", "end": END})
        app = graph.compile()

        state = await app.ainvoke(
            {
                "current_message": first_message,
                "tool_summaries": [],
                "rounds_used": 0,
            }
        )

        tool_summaries = list(state.get("tool_summaries") or [])
        current_message = state.get("current_message")
        stopped_by_limit = bool(getattr(current_message, "tool_calls", None)) and int(
            state.get("rounds_used", 0)
        ) >= max_rounds

        if not getattr(current_message, "tool_calls", None):
            final_text = (getattr(current_message, "content", "") or "").strip()
            if not final_text:
                return ""
            return self._finalize_tool_loop_reply(final_text)

        if stopped_by_limit:
            return self._finalize_tool_loop_reply("已达到最大工具调用轮数，已停止继续调用。")
        return ""


__all__ = ["ToolBackendMixin"]
