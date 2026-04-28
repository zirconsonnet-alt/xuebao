"""AI 工具执行辅助。"""

import json
from typing import Any, Dict, List

from src.support.core import tool_registry

from .tool_rendering import ToolResultRenderMixin


class ToolExecutionMixin(ToolResultRenderMixin):
    @staticmethod
    def _normalize_scheduled_target_name(raw_name: Any) -> str:
        return str(raw_name or "").strip()

    def _get_scheduled_tool_targets(self, context: Dict[str, Any]) -> set[str]:
        scheduled_targets = context.get("_scheduled_tool_targets")
        if isinstance(scheduled_targets, set):
            return scheduled_targets
        normalized_targets = {str(item).strip() for item in (scheduled_targets or []) if str(item).strip()}
        context["_scheduled_tool_targets"] = normalized_targets
        return normalized_targets

    def _build_scheduled_tool_skip_result(self, tool_name: str) -> Dict[str, Any]:
        return {
            "success": True,
            "message": f"已创建对应定时任务，本轮跳过即时执行：{tool_name}",
            "data": {
                "tool": tool_name,
                "skipped": True,
                "reason": "scheduled_same_round",
            },
        }

    def _has_recorded_tool_results(self, message) -> bool:
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return False

        expected_ids = [tool_call.id for tool_call in tool_calls if getattr(tool_call, "id", None)]
        if not expected_ids:
            return False

        recorded_ids = {
            msg.get("tool_call_id")
            for msg in self.msg_list
            if msg.get("role") == "tool" and msg.get("tool_call_id")
        }
        return all(tool_call_id in recorded_ids for tool_call_id in expected_ids)

    async def _execute_tool_calls(self, message, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"[工具调用] 执行 {len(message.tool_calls)} 个工具")

        tool_calls_data = []
        tool_results = []
        user_lines: List[str] = []

        mcp_tool_map = (context or {}).get("mcp_tool_map") or {}
        mcp_sessions = (context or {}).get("mcp_sessions") or {}
        use_mcp_only = bool(mcp_tool_map)
        scheduled_tool_targets = self._get_scheduled_tool_targets(context)

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            print(f"[工具调用] {func_name}: {func_args}")

            if func_name != "schedule_tool_call" and func_name in scheduled_tool_targets:
                result = self._build_scheduled_tool_skip_result(func_name)
                print(f"[工具调用] 跳过即时执行 {func_name}：本轮已创建对应定时任务")
                print(f"[工具结果] {result}")
                tool_results.append(
                    {
                        "name": func_name,
                        "success": result.get("success", False),
                        "message": result.get("message", ""),
                    }
                )
                tool_calls_data.append({"tool_call": tool_call, "result": result})
                rendered = self._render_tool_result_for_user(tool_name=func_name, result=result)
                if rendered:
                    user_lines.append(rendered)
                continue

            if use_mcp_only:
                mapped = mcp_tool_map.get(func_name) or {}
                server_name = mapped.get("server")
                mcp_tool_name = mapped.get("tool")
                if not server_name or not mcp_tool_name:
                    result = {
                        "success": False,
                        "message": f"未找到 MCP 工具映射: {func_name}",
                        "data": {"tool": func_name},
                    }
                else:
                    session = mcp_sessions.get(server_name)
                    if not session:
                        result = {
                            "success": False,
                            "message": f"MCP session 不存在: {server_name}",
                            "data": {"server": server_name, "tool": mcp_tool_name},
                        }
                    else:
                        try:
                            meta = {
                                "group_id": context.get("group_id"),
                                "user_id": context.get("user_id"),
                                "member_role": context.get("member_role"),
                                "service_config": context.get("service_config") or {},
                                "image_registry": context.get("image_registry") or {},
                                "video_registry": context.get("video_registry") or {},
                                "message": context.get("message") or "",
                                "message_id": context.get("message_id") or 0,
                                "self_id": context.get("self_id") or 0,
                                "reply_text": context.get("reply_text") or "",
                                "reply_message_id": context.get("reply_message_id") or 0,
                            }
                            call_res = await session.call_tool(mcp_tool_name, func_args or {}, meta=meta)
                            result = self._normalize_mcp_call_tool_result(call_res)
                        except Exception as exc:
                            result = {
                                "success": False,
                                "message": f"MCP 工具执行异常: {exc}",
                                "data": {"server": server_name, "tool": mcp_tool_name},
                            }
            else:
                tool_context = dict(context or {})
                tool_context["_tool_call_id"] = getattr(tool_call, "id", "")
                result = await tool_registry.execute_tool(func_name, func_args, tool_context)

            print(f"[工具结果] {result}")
            if func_name == "schedule_tool_call" and result.get("success", False):
                target_tool_name = self._normalize_scheduled_target_name(func_args.get("tool_name"))
                if target_tool_name:
                    scheduled_tool_targets.add(target_tool_name)
            tool_results.append(
                {
                    "name": func_name,
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                }
            )
            tool_calls_data.append({"tool_call": tool_call, "result": result})
            rendered = self._render_tool_result_for_user(tool_name=func_name, result=result)
            if rendered:
                user_lines.append(rendered)

        await self._send_tool_feedback(tool_results)

        self.add_message(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc["tool_call"].id,
                        "type": "function",
                        "function": {
                            "name": tc["tool_call"].function.name,
                            "arguments": tc["tool_call"].function.arguments,
                        },
                    }
                    for tc in tool_calls_data
                ],
            }
        )
        for tc in tool_calls_data:
            self.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tc["tool_call"].id,
                    "content": json.dumps(tc["result"], ensure_ascii=False),
                }
            )

        any_failed = any(not result.get("success", False) for result in tool_results)
        user_text = "\n\n".join(user_lines).strip()
        return {"tool_results": tool_results, "user_text": user_text, "any_failed": any_failed}

    async def _send_tool_feedback(self, tool_results: List[Dict[str, Any]]):
        failed_feedback: List[str] = []
        for result in tool_results:
            tool_name = result.get("name", "未知工具")
            if result["success"]:
                continue

            error_msg = str(result.get("message") or "未知错误")
            if len(error_msg) > 50:
                error_msg = error_msg[:50] + "..."
            failed_feedback.append(f"❌ {tool_name}: {error_msg}")

        if not failed_feedback:
            return
        if len(failed_feedback) == 1:
            await self.send_text(failed_feedback[0])
            return
        await self.send_text("工具执行遇到问题：\n" + "\n".join(failed_feedback))


__all__ = ["ToolExecutionMixin"]
